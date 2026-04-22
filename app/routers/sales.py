from fastapi import APIRouter, HTTPException, BackgroundTasks, Depends
from typing import List, Dict, Any
from datetime import datetime

from app.models.schemas import (
    SaleInitRequest, SaleInitResponse, SalePublishRequest, 
    BundleCreateRequest, ItemCreateRequest, ItemUpdate, SaleStatus
)

# Import shared service singletons
from app.services import firestore_svc, gemini_processor, gcs_utils, BUCKET_NAME

router = APIRouter(prefix="/sales")

# --- BACKGROUND PIPELINES ---

async def run_extraction_pipeline(event_id: str, gcs_uri: str):
    """
    Stage 1: AI Vision Analysis.
    Extracts bundles and items from the GCS video walkthrough.
    """
    try:
        # 1. Update status to processing
        firestore_svc.transition_sale_status(event_id, SaleStatus.PROCESSING)
        
        # 2. Call Gemini Vision
        bundles = gemini_processor.process_walkthrough(gcs_uri)
        
        # 3. Save results to Firestore hierarchy
        for b in bundles:
            bundle_id = firestore_svc.add_bundle(event_id, b.bundle_name, 0)
            for item in b.items:
                # Convert Pydantic model to dict for Firestore
                item_data = item.model_dump() if hasattr(item, 'model_dump') else item.dict()
                firestore_svc.add_item_to_bundle(event_id, bundle_id, item_data)
        
        # 4. Move to Review stage
        firestore_svc.transition_sale_status(event_id, SaleStatus.READY_FOR_REVIEW)
    except Exception as e:
        print(f"Extraction Pipeline Failed: {e}")
        firestore_svc.transition_sale_status(event_id, SaleStatus.FAILED)

async def run_pricing_pipeline(event_id: str):
    """
    Stage 2: AI Pricing Analysis.
    Analyzes verified inventory data against Sydney market trends.
    """
    try:
        summary = firestore_svc.get_full_event_summary(event_id)
        move_out_date = summary.get("moveOutDate") or datetime.now().strftime("%Y-%m-%d")

        context_items = []
        item_to_bundle_map = {}
        
        for bundle in summary['bundles']:
            for item in bundle['items']:
                item_to_bundle_map[item['id']] = bundle['id']
                context_items.append({
                    "id": item['id'],
                    "name": item['name'],
                    "brand": item['brand'],
                    "condition": item['condition'],
                    "original_price": item.get('actual_original_price') or item.get('predicted_original_price'),
                    "purchase_year": item.get('actual_year_of_purchase') or item.get('predicted_year_of_purchase')
                })

        priced_results = gemini_processor.estimate_listing_prices(context_items, move_out_date)

        for p in priced_results:
            item_id = p.get('id')
            bundle_id = item_to_bundle_map.get(item_id)
            if bundle_id:
                firestore_svc.update_item_data(event_id, bundle_id, item_id, {
                    "predicted_listing_price": p.get('listing_price', 0),
                    "actual_listing_price": p.get('listing_price', 0),
                    "pricing_reasoning": p.get('reasoning', 'Market adjustment based on Sydney demand.')
                })
        
        for bundle in summary['bundles']:
            firestore_svc.recalculate_bundle_total(event_id, bundle['id'])

        firestore_svc.transition_sale_status(event_id, SaleStatus.READY_FOR_REVIEW)
    except Exception as e:
        firestore_svc.transition_sale_status(event_id, SaleStatus.FAILED)

# --- CORE SALE ROUTES ---

@router.post("/init", response_model=SaleInitResponse)
async def init_sale(payload: SaleInitRequest):
    """
    Step 1: Create the Firestore record and get a GCS Signed URL for upload.
    Path: POST /api/v1/sales/init
    """
    # Create GCS URI
    gcs_uri = f"gs://{BUCKET_NAME}/{payload.user_id}/{payload.filename}"
    
    # Initialize in Firestore
    event_id = firestore_svc.create_sale_event(payload.user_id, gcs_uri)
    
    # Generate Signed URL for frontend PUT request
    upload_url = gcs_utils.generate_upload_url(BUCKET_NAME, f"{payload.user_id}/{payload.filename}")
    
    return {
        "event_id": event_id,
        "upload_url": upload_url,
        "gcs_uri": gcs_uri
    }

@router.post("/{event_id}/process")
async def start_processing(event_id: str, background_tasks: BackgroundTasks):
    """
    Step 2: Trigger Stage 1 AI (Vision Extraction).
    Path: POST /api/v1/sales/{event_id}/process
    """
    event = firestore_svc.get_sale_event(event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Sale not found")
    
    background_tasks.add_task(run_extraction_pipeline, event_id, event['videoUrl'])
    return {"status": "processing_started"}

@router.get("/")
async def list_sales(user_id: str = "ajay_web_test"):
    return firestore_svc.list_all_sales(user_id)

@router.get("/{event_id}/summary")
async def get_sale_summary(event_id: str):
    summary = firestore_svc.get_full_event_summary(event_id)
    if not summary:
        raise HTTPException(status_code=404, detail="Sale not found")
    
    gcs_uri = summary.get("videoUrl")
    if gcs_uri and gcs_uri.startswith("gs://"):
        stripped = gcs_uri.replace("gs://", "").split("/", 1)
        summary["videoUrl"] = gcs_utils.generate_download_url(stripped[0], stripped[1])
    return summary

@router.get("/{event_id}/status")
async def get_status(event_id: str):
    event = firestore_svc.get_sale_event(event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Sale Event not found")
    return {"status": event.get("status", SaleStatus.PENDING_UPLOAD)}

# --- STATE TRANSITIONS ---

@router.post("/{event_id}/estimate")
async def trigger_reestimation(event_id: str, background_tasks: BackgroundTasks):
    firestore_svc.transition_sale_status(event_id, SaleStatus.PRICING_IN_PROGRESS)
    background_tasks.add_task(run_pricing_pipeline, event_id)
    return {"status": SaleStatus.PRICING_IN_PROGRESS}

@router.post("/{event_id}/publish")
async def publish_sale(event_id: str, payload: SalePublishRequest):
    summary = firestore_svc.get_full_event_summary(event_id)
    if not summary:
        raise HTTPException(status_code=404, detail="Sale not found")

    for bundle in summary.get('bundles', []):
        for item in bundle['items']:
            if item.get('actual_listing_price') is None:
                fallback = item.get('predicted_listing_price') or 0
                firestore_svc.update_item_data(event_id, bundle['id'], item['id'], {"actual_listing_price": fallback})

    firestore_svc.db.collection("saleEvents").document(event_id).update({
        "moveOutDate": payload.move_out_date,
        "publishedAt": datetime.now()
    })
    firestore_svc.transition_sale_status(event_id, SaleStatus.LIVE)
    return {"status": SaleStatus.LIVE}

@router.post("/{event_id}/unpublish")
async def unpublish_sale(event_id: str):
    event = firestore_svc.get_sale_event(event_id)
    if not event or event['status'] not in [SaleStatus.LIVE, SaleStatus.PARTIALLY_SOLD]:
        raise HTTPException(status_code=400, detail="Sale is not currently active.")
    
    firestore_svc.transition_sale_status(event_id, SaleStatus.READY_FOR_REVIEW)
    return {"status": SaleStatus.READY_FOR_REVIEW}

# --- INVENTORY CRUD ---

@router.post("/{event_id}/bundles")
async def add_bundle(event_id: str, payload: BundleCreateRequest):
    bundle_id = firestore_svc.add_bundle(event_id, payload.name, 0)
    return {"bundle_id": bundle_id}

@router.delete("/{event_id}/bundles/{bundle_id}")
async def remove_bundle(event_id: str, bundle_id: str):
    firestore_svc.delete_bundle(event_id, bundle_id)
    return {"status": "deleted"}

@router.post("/{event_id}/bundles/{bundle_id}/items")
async def add_manual_item(event_id: str, bundle_id: str, payload: ItemCreateRequest):
    item_id = firestore_svc.add_item_to_bundle(event_id, bundle_id, payload.dict())
    firestore_svc.recalculate_bundle_total(event_id, bundle_id)
    return {"item_id": item_id}

@router.patch("/{event_id}/bundles/{bundle_id}/items/{item_id}")
async def update_item(event_id: str, bundle_id: str, item_id: str, updates: Dict[str, Any]):
    firestore_svc.update_item_data(event_id, bundle_id, item_id, updates)
    if "actual_listing_price" in updates:
        firestore_svc.recalculate_bundle_total(event_id, bundle_id)
    return {"status": "updated"}

@router.delete("/{event_id}/bundles/{bundle_id}/items/{item_id}")
async def remove_item(event_id: str, bundle_id: str, item_id: str):
    firestore_svc.delete_item(event_id, bundle_id, item_id)
    return {"status": "deleted"}
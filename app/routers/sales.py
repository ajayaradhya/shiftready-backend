from fastapi import APIRouter, HTTPException, BackgroundTasks
from typing import List, Dict, Any
from datetime import datetime

from app.models.schemas import (
    SaleInitRequest, SaleInitResponse, SalePublishRequest, 
    BundleCreateRequest, ItemCreateRequest, ItemUpdate
)

# FIX: Import from services, not main
from app.services import firestore_svc, gemini_processor, gcs_utils, BUCKET_NAME

router = APIRouter()

# --- HELPER: Background Pricing Logic ---

async def run_pricing_pipeline(event_id: str):
    """Refined pricing loop using Gemini market analysis."""
    try:
        summary = firestore_svc.get_full_event_summary(event_id)
        move_out_date = summary.get("moveOutDate") or datetime.now().strftime("%Y-%m-%d")

        item_to_bundle_map = {}
        context_items = []
        
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
            item_id, bundle_id = p.get('id'), item_to_bundle_map.get(p.get('id'))
            if bundle_id:
                firestore_svc.update_item_data(event_id, bundle_id, item_id, {
                    "predicted_listing_price": p.get('listing_price', 0),
                    "actual_listing_price": p.get('listing_price', 0),
                    "pricing_reasoning": p.get('reasoning', 'Sydney Market Trend Adjustment')
                })
        
        for bundle in summary['bundles']:
            firestore_svc.recalculate_bundle_total(event_id, bundle['id'])

        firestore_svc.update_sale_status(event_id, "ready_for_review")
    except Exception as e:
        firestore_svc.update_sale_status(event_id, "failed")

# --- ENDPOINTS: Sale Management ---

@router.get("/sales")
async def list_sales(user_id: str = "ajay_web_test"):
    """Future-proof: List all sale events for the dashboard."""
    return firestore_svc.list_all_sales(user_id)

@router.get("/sales/{event_id}/summary")
async def get_sale_summary(event_id: str):
    """Full hierarchical view for the Review Cockpit."""
    summary = firestore_svc.get_full_event_summary(event_id)
    if not summary:
        raise HTTPException(status_code=404, detail="Sale not found")
    
    # Refresh Signed URL for video playback
    gcs_uri = summary.get("videoUrl")
    if gcs_uri and gcs_uri.startswith("gs://"):
        stripped = gcs_uri.replace("gs://", "").split("/", 1)
        summary["videoUrl"] = gcs_utils.generate_download_url(stripped[0], stripped[1])

    return summary

@router.get("/sales/{event_id}/status")
async def get_status(event_id: str):
    """Polling endpoint for 'Zero-Blink' UI transitions."""
    event = firestore_svc.get_sale_event(event_id)
    if not event: raise HTTPException(status_code=404)
    return {"status": event.get("status", "unknown")}

# --- ENDPOINTS: Mutations (CRUD) ---

@router.post("/sales/{event_id}/estimate")
async def trigger_reestimation(event_id: str, background_tasks: BackgroundTasks):
    """Triggers the Gemini Pricing Pipeline."""
    firestore_svc.update_sale_status(event_id, "pricing_in_progress")
    background_tasks.add_task(run_pricing_pipeline, event_id)
    return {"status": "pricing_in_progress"}

@router.post("/sales/{event_id}/publish")
async def publish_sale(event_id: str, payload: SalePublishRequest):
    """Moves sale to 'live' status and anchors move-out date."""
    summary = firestore_svc.get_full_event_summary(event_id)
    if not summary: raise HTTPException(status_code=404)

    # Ensure actual_listing_price fallbacks
    for bundle in summary['bundles']:
        for item in bundle['items']:
            if item.get('actual_listing_price') is None:
                price = item.get('predicted_listing_price') or 0
                firestore_svc.update_item_data(event_id, bundle['id'], item['id'], {"actual_listing_price": price})

    firestore_svc.db.collection("saleEvents").document(event_id).update({
        "status": "live",
        "moveOutDate": payload.move_out_date,
        "publishedAt": datetime.now()
    })
    return {"status": "live"}

# --- ENDPOINTS: Bundle & Item CRUD ---

@router.post("/sales/{event_id}/bundles")
async def add_bundle(event_id: str, payload: BundleCreateRequest):
    bundle_id = firestore_svc.add_bundle(event_id, payload.name, 0)
    return {"bundle_id": bundle_id}

@router.delete("/sales/{event_id}/bundles/{bundle_id}")
async def remove_bundle(event_id: str, bundle_id: str):
    firestore_svc.delete_bundle(event_id, bundle_id)
    return {"status": "deleted"}

@router.post("/sales/{event_id}/bundles/{bundle_id}/items")
async def add_manual_item(event_id: str, bundle_id: str, payload: ItemCreateRequest):
    item_id = firestore_svc.add_item_to_bundle(event_id, bundle_id, payload.dict())
    firestore_svc.recalculate_bundle_total(event_id, bundle_id)
    return {"item_id": item_id}

@router.patch("/sales/{event_id}/bundles/{bundle_id}/items/{item_id}")
async def update_item(event_id: str, bundle_id: str, item_id: str, updates: Dict[str, Any]):
    firestore_svc.update_item_data(event_id, bundle_id, item_id, updates)
    # If price changed, update bundle total
    if "actual_listing_price" in updates:
        firestore_svc.recalculate_bundle_total(event_id, bundle_id)
    return {"status": "updated"}

@router.delete("/sales/{event_id}/bundles/{bundle_id}/items/{item_id}")
async def remove_item(event_id: str, bundle_id: str, item_id: str):
    firestore_svc.delete_item(event_id, bundle_id, item_id)
    return {"status": "deleted"}
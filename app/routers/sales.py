from fastapi import APIRouter, HTTPException, BackgroundTasks, Depends, WebSocket, WebSocketDisconnect
from typing import List, Dict, Any
from datetime import datetime

from app.models.schemas import (
    SaleInitRequest, SaleInitResponse, SalePublishRequest, 
    BundleCreateRequest, ItemCreateRequest, ItemUpdate, SaleStatus
)

# Import shared service singletons
from app.services import firestore_svc, gemini_processor, gcs_utils, BUCKET_NAME
from app.services.pipelines import run_extraction_pipeline, run_pricing_pipeline
from app.services.notifier import notifier
from app.services.auth import get_current_user, validate_sale_owner, User

router = APIRouter(prefix="/sales")

# --- CORE SALE ROUTES ---

@router.post("/init", response_model=SaleInitResponse)
async def init_sale(payload: SaleInitRequest, current_user: User = Depends(get_current_user)):
    """
    Step 1: Create the Firestore record and get a GCS Signed URL for upload.
    Path: POST /api/v1/sales/init
    """
    # Create GCS URI
    gcs_uri = f"gs://{BUCKET_NAME}/{current_user.id}/{payload.filename}"
    
    # Initialize in Firestore
    event_id = firestore_svc.create_sale_event(current_user.id, gcs_uri)
    
    # Generate Signed URL for frontend PUT request
    upload_url = gcs_utils.generate_upload_url(BUCKET_NAME, f"{current_user.id}/{payload.filename}")
    
    return {
        "event_id": event_id,
        "upload_url": upload_url,
        "gcs_uri": gcs_uri
    }

@router.post("/{event_id}/process")
async def start_processing(
    event_id: str, 
    background_tasks: BackgroundTasks,
    event: dict = Depends(validate_sale_owner)
):
    """
    Step 2: Trigger Stage 1 AI (Vision Extraction).
    Path: POST /api/v1/sales/{event_id}/process
    """
    background_tasks.add_task(run_extraction_pipeline, event_id, event['videoUrl'])
    return {"status": "processing_started"}

@router.get("/")
async def list_sales(current_user: User = Depends(get_current_user)):
    return firestore_svc.list_all_sales(current_user.id)

@router.get("/{event_id}/summary")
async def get_sale_summary(event_id: str, _ = Depends(validate_sale_owner)):
    summary = firestore_svc.get_full_event_summary(event_id) # Validated via dependency
    if not summary:
        raise HTTPException(status_code=404, detail="Sale not found")
    
    gcs_uri = summary.get("videoUrl")
    if gcs_uri and gcs_uri.startswith("gs://"):
        stripped = gcs_uri.replace("gs://", "").split("/", 1)
        summary["videoUrl"] = gcs_utils.generate_download_url(stripped[0], stripped[1])
    return summary

@router.get("/{event_id}/status")
async def get_status(event_id: str, event: dict = Depends(validate_sale_owner)):
    if not event:
        raise HTTPException(status_code=404, detail="Sale Event not found")
    return {"status": event.get("status", SaleStatus.PENDING_UPLOAD)}

@router.websocket("/{event_id}/ws")
async def status_websocket(
    websocket: WebSocket, 
    event_id: str,
    event: dict = Depends(validate_sale_owner)
):
    """
    Real-time status updates via WebSocket.
    The client connects here to be notified when the pipeline finishes.
    """
    await notifier.connect(event_id, websocket)
    try:
        # State Sync on Connect: Use the event already fetched by validate_sale_owner
        await websocket.send_json({
            "type": "STATUS_UPDATE",
            "status": event.get("status"),
            "message": "Connected to status stream"
        })
            
        # Keep connection open until client disconnects
        while True:
            # We can optionally listen for pings/messages from client here
            await websocket.receive_text()
    except WebSocketDisconnect:
        notifier.disconnect(event_id, websocket)


# --- STATE TRANSITIONS ---

@router.post("/{event_id}/estimate")
async def trigger_reestimation(
    event_id: str, 
    background_tasks: BackgroundTasks,
    _ = Depends(validate_sale_owner)
):
    firestore_svc.transition_sale_status(event_id, SaleStatus.PRICING_IN_PROGRESS)
    background_tasks.add_task(run_pricing_pipeline, event_id)
    return {"status": SaleStatus.PRICING_IN_PROGRESS}

@router.post("/{event_id}/publish")
async def publish_sale(
    event_id: str, 
    payload: SalePublishRequest,
    _ = Depends(validate_sale_owner)
):
    summary = firestore_svc.get_full_event_summary(event_id) # Scoped
    if not summary:
        raise HTTPException(status_code=404, detail="Sale not found")

    for bundle in summary.get('bundles', []):
        for item in bundle['items']:
            if item.get('actual_listing_price') is None:
                fallback = item.get('predicted_listing_price') or 0
                firestore_svc.update_item_data(event_id, bundle['id'], item['id'], {"actual_listing_price": fallback})

    # Move direct DB access to service layer
    firestore_svc.update_sale_metadata(event_id, {
        "moveOutDate": payload.move_out_date,
        "publishedAt": datetime.now()
    })
    
    firestore_svc.transition_sale_status(event_id, SaleStatus.LIVE)
    return {"status": SaleStatus.LIVE}

@router.post("/{event_id}/unpublish")
async def unpublish_sale(event_id: str, event: dict = Depends(validate_sale_owner)):
    if event['status'] not in [SaleStatus.LIVE, SaleStatus.PARTIALLY_SOLD]:
        raise HTTPException(status_code=400, detail="Sale is not currently active.")
    
    firestore_svc.transition_sale_status(event_id, SaleStatus.READY_FOR_REVIEW)
    return {"status": SaleStatus.READY_FOR_REVIEW}

# --- INVENTORY CRUD ---

@router.post("/{event_id}/bundles")
async def add_bundle(event_id: str, payload: BundleCreateRequest, _ = Depends(validate_sale_owner)):
    bundle_id = firestore_svc.add_bundle(event_id, payload.name, 0)
    return {"bundle_id": bundle_id}

@router.delete("/{event_id}/bundles/{bundle_id}")
async def remove_bundle(event_id: str, bundle_id: str, _ = Depends(validate_sale_owner)):
    firestore_svc.delete_bundle(event_id, bundle_id)
    return {"status": "deleted"}

@router.post("/{event_id}/bundles/{bundle_id}/items")
async def add_manual_item(event_id: str, bundle_id: str, payload: ItemCreateRequest, _ = Depends(validate_sale_owner)):
    item_id = firestore_svc.add_item_to_bundle(event_id, bundle_id, payload.dict())
    firestore_svc.recalculate_bundle_total(event_id, bundle_id)
    return {"item_id": item_id}

@router.patch("/{event_id}/bundles/{bundle_id}/items/{item_id}")
async def update_item(event_id: str, bundle_id: str, item_id: str, updates: Dict[str, Any], _ = Depends(validate_sale_owner)):
    firestore_svc.update_item_data(event_id, bundle_id, item_id, updates)
    
    # Notify connected clients that an item has changed (Real-time sync)
    await notifier.notify_event(event_id, {
        "type": "ITEM_UPDATED",
        "item_id": item_id,
        "updates": updates
    })

    if "actual_listing_price" in updates:
        firestore_svc.recalculate_bundle_total(event_id, bundle_id)
    return {"status": "updated"}

@router.delete("/{event_id}/bundles/{bundle_id}/items/{item_id}")
async def remove_item(event_id: str, bundle_id: str, item_id: str, _ = Depends(validate_sale_owner)):
    firestore_svc.delete_item(event_id, bundle_id, item_id)
    return {"status": "deleted"}
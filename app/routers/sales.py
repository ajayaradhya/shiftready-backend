import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, BackgroundTasks, Depends, WebSocket, WebSocketDisconnect

from app.domain.status import SaleStatus
from app.models.schemas import (
    BundleCreateRequest, BundleCreateResponse,
    ItemCreateRequest, ItemCreateResponse, ItemUpdate,
    PriceEstimationRequest,
    SaleInitRequest, SaleInitResponse, SalePublishRequest,
    SaleStatusResponse, StatusResponse,
)

from app.core.deps import FirestoreDep, GCSDep, BucketDep, GeminiDep
from app.services.pipelines import run_extraction_pipeline, run_pricing_pipeline
from app.services.notifier import notifier
from app.services.auth import get_current_user, validate_sale_owner, User, security

router = APIRouter(prefix="/sales")

# --- CORE SALE ROUTES ---

@router.post("/init", response_model=SaleInitResponse)
async def init_sale(
    payload: SaleInitRequest,
    firestore: FirestoreDep,
    gcs: GCSDep,
    bucket: BucketDep,
    current_user: User = Depends(get_current_user),
    _ = Depends(security),  # Re-adds the "Lock" icon to Swagger UI
):
    """
    Step 1: Create the Firestore record and get a GCS Signed URL for upload.
    Path: POST /api/v1/sales/init
    """
    # Create GCS URI
    gcs_uri = f"gs://{bucket}/{current_user.id}/{payload.filename}"

    # Initialize in Firestore
    event_id = await firestore.create_sale_event(current_user.id, gcs_uri)

    # Generate Signed URL for frontend PUT request
    upload_url = gcs.generate_upload_url(bucket, f"{current_user.id}/{payload.filename}")

    return {
        "event_id": event_id,
        "upload_url": upload_url,
        "gcs_uri": gcs_uri,
    }

@router.post("/{event_id}/process", response_model=StatusResponse)
async def start_processing(
    event_id: str,
    background_tasks: BackgroundTasks,
    firestore: FirestoreDep,
    gemini: GeminiDep,
    event: dict = Depends(validate_sale_owner),
):
    """
    Step 2: Trigger Stage 1 AI (Vision Extraction).
    Path: POST /api/v1/sales/{event_id}/process
    """
    background_tasks.add_task(run_extraction_pipeline, event_id, event["videoUrl"], firestore, gemini)
    return {"status": "processing_started"}

@router.get("/", response_model=list[SaleStatusResponse])
async def list_sales(
    firestore: FirestoreDep,
    current_user: User = Depends(get_current_user),
):
    return await firestore.list_all_sales(current_user.id)


@router.get("/{event_id}/summary")
async def get_sale_summary(
    event_id: str,
    firestore: FirestoreDep,
    gcs: GCSDep,
    _: dict = Depends(validate_sale_owner),
):
    summary = await firestore.get_full_event_summary(event_id)  # Validated via dependency
    if not summary:
        raise HTTPException(status_code=404, detail="Sale not found")

    gcs_uri = summary.get("videoUrl")
    if gcs_uri and gcs_uri.startswith("gs://"):
        stripped = gcs_uri.replace("gs://", "").split("/", 1)
        summary["videoUrl"] = gcs.generate_download_url(stripped[0], stripped[1])
    return summary


@router.get("/{event_id}/status", response_model=StatusResponse)
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

@router.post("/{event_id}/estimate", response_model=StatusResponse)
async def trigger_reestimation(
    event_id: str,
    payload: PriceEstimationRequest,
    background_tasks: BackgroundTasks,
    firestore: FirestoreDep,
    gemini: GeminiDep,
    event: dict = Depends(validate_sale_owner),
):
    # Store the move-out date to improve AI pricing urgency analysis
    await firestore.update_sale_metadata(event_id, {"moveOutDate": payload.move_out_date})
    await firestore.transition_sale_status(event_id, SaleStatus.PRICING_IN_PROGRESS)
    background_tasks.add_task(run_pricing_pipeline, event_id, firestore, gemini)
    return {"status": SaleStatus.PRICING_IN_PROGRESS}

@router.post("/{event_id}/publish", response_model=StatusResponse)
async def publish_sale(
    event_id: str,
    payload: SalePublishRequest,
    firestore: FirestoreDep,
    _: dict = Depends(validate_sale_owner),
):
    summary = await firestore.get_full_event_summary(event_id)  # Scoped
    if not summary:
        raise HTTPException(status_code=404, detail="Sale not found")

    # Optimization: Gather item updates to run concurrently
    update_tasks = []
    for bundle in summary.get("bundles", []):
        for item in bundle["items"]:
            if item.get("actual_listing_price") is None:
                fallback = item.get("predicted_listing_price") or 0
                update_tasks.append(
                    firestore.update_item_data(event_id, bundle["id"], item["id"], {"actual_listing_price": fallback})
                )

    if update_tasks:
        await asyncio.gather(*update_tasks)

    await firestore.update_sale_metadata(event_id, {
        "moveOutDate": payload.move_out_date,
        "streetAddress": payload.street_address,
        "suburb": payload.suburb,
        "pincode": payload.pincode,
        "state": payload.state,
        "publishedAt": datetime.now(timezone.utc),
    })

    await firestore.transition_sale_status(event_id, SaleStatus.LIVE)
    return {"status": SaleStatus.LIVE}

@router.post("/{event_id}/unpublish", response_model=StatusResponse)
async def unpublish_sale(
    event_id: str,
    firestore: FirestoreDep,
    event: dict = Depends(validate_sale_owner),
):
    if event["status"] not in [SaleStatus.LIVE, SaleStatus.PARTIALLY_SOLD]:
        raise HTTPException(status_code=400, detail="Sale is not currently active.")

    await firestore.transition_sale_status(event_id, SaleStatus.READY_FOR_REVIEW)
    return {"status": SaleStatus.READY_FOR_REVIEW}

# --- INVENTORY CRUD ---

@router.post("/{event_id}/bundles", response_model=BundleCreateResponse)
async def add_bundle(
    event_id: str,
    payload: BundleCreateRequest,
    firestore: FirestoreDep,
    _: dict = Depends(validate_sale_owner),
):
    bundle_id = await firestore.add_bundle(event_id, payload.name, 0)
    return {"bundle_id": bundle_id}


@router.delete("/{event_id}/bundles/{bundle_id}", response_model=StatusResponse)
async def remove_bundle(
    event_id: str,
    bundle_id: str,
    firestore: FirestoreDep,
    _: dict = Depends(validate_sale_owner),
):
    await firestore.delete_bundle(event_id, bundle_id)
    return {"status": "deleted"}


@router.post("/{event_id}/bundles/{bundle_id}/items", response_model=ItemCreateResponse)
async def add_manual_item(
    event_id: str,
    bundle_id: str,
    payload: ItemCreateRequest,
    firestore: FirestoreDep,
    _: dict = Depends(validate_sale_owner),
):
    item_id = await firestore.add_item_to_bundle(event_id, bundle_id, payload.model_dump())
    await firestore.recalculate_bundle_total(event_id, bundle_id)
    return {"item_id": item_id}


@router.patch("/{event_id}/bundles/{bundle_id}/items/{item_id}", response_model=StatusResponse)
async def update_item(
    event_id: str,
    bundle_id: str,
    item_id: str,
    payload: ItemUpdate,
    firestore: FirestoreDep,
    _: dict = Depends(validate_sale_owner),
):
    updates = payload.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=422, detail="No valid fields provided")

    await firestore.update_item_data(event_id, bundle_id, item_id, updates)

    # Notify connected clients that an item has changed (Real-time sync)
    await notifier.notify_event(event_id, {
        "type": "ITEM_UPDATED",
        "item_id": item_id,
        "updates": updates,
    })

    if "actual_listing_price" in updates:
        await firestore.recalculate_bundle_total(event_id, bundle_id)
    return {"status": "updated"}


@router.delete("/{event_id}/bundles/{bundle_id}/items/{item_id}", response_model=StatusResponse)
async def remove_item(
    event_id: str,
    bundle_id: str,
    item_id: str,
    firestore: FirestoreDep,
    _: dict = Depends(validate_sale_owner),
):
    await firestore.delete_item(event_id, bundle_id, item_id)
    return {"status": "deleted"}
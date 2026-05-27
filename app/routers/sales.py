import asyncio
import logging
import mimetypes
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, BackgroundTasks, Depends, WebSocket, WebSocketDisconnect, UploadFile, File
from google.cloud.firestore import ArrayUnion

from app.domain.status import SaleStatus
from app.models.schemas import (
    BundleCreateRequest, BundleCreateResponse, BundleUpdateRequest,
    CaptureInitResponse, CaptureFrameResponse, CaptureFinalizeV2Request, CaptureFinalizeV2Response,
    CoverConfirmRequest, CoverFromItemRequest, CoverUploadUrlResponse,
    ImageConfirmRequest, ImageUploadUrlItem, ImageUploadUrlsRequest, ImageUploadUrlsResponse, ImageReorderRequest,
    ItemCreateRequest, ItemCreateResponse, ItemUpdate, ItemMoveRequest, ItemRepriceResponse,
    SalePublishRequest, SaleUpdate, SuggestTitleRequest, SuggestTitleResponse,
    SaleStatusResponse, StatusResponse,
)
from app.services.permissions import assert_editable
from app.core.deps import FirestoreDep, GCSDep, BucketDep, GeminiDep
from app.services.pipelines import run_capture_refinement_pipeline
from app.services.notifier import notifier
from app.services.auth import get_current_user, validate_sale_owner, User, security

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sales")

# --- CORE SALE ROUTES ---

@router.post("/init-capture", response_model=CaptureInitResponse)
async def init_capture_sale(
    firestore: FirestoreDep,
    current_user: User = Depends(get_current_user),
    _ = Depends(security),
):
    """
    Create a sale event for the live-capture (frames) flow. No video upload needed.
    Path: POST /api/v1/sales/init-capture
    """
    event_id = await firestore.create_sale_event(current_user.id)
    return {"event_id": event_id}


@router.post("/{event_id}/capture/frame", response_model=CaptureFrameResponse)
async def capture_frame(
    event_id: str,
    gcs: GCSDep,
    bucket: BucketDep,
    gemini: GeminiDep,
    frame: UploadFile = File(...),
    event: dict = Depends(validate_sale_owner),
):
    """
    Upload a single confirmed capture frame, run quick Gemini identification (name + brand + price),
    and return the result for the live bucket. Does NOT write to Firestore — display only.
    Path: POST /api/v1/sales/{event_id}/capture/frame
    """
    data = await frame.read()
    frame_id = str(uuid.uuid4())
    blob_name = f"captures/{event_id}/{frame_id}.jpg"
    gcs_uri = gcs.upload_bytes(bucket, blob_name, data, content_type="image/jpeg")

    try:
        result = await gemini.identify_single_frame(gcs_uri)
        name = result.get("name") or "Unidentified Item"
        brand = result.get("brand") or None
        price = float(result.get("predicted_original_price") or 0.0)
        confidence = result.get("confidence") or "medium"
    except Exception as exc:
        logger.warning(f"Frame identification failed for {gcs_uri}: {exc}")
        name = "Unidentified Item"
        brand = None
        price = 0.0
        confidence = "low"

    return CaptureFrameResponse(
        name=name,
        brand=brand,
        predicted_original_price=price,
        gcs_uri=gcs_uri,
        confidence=confidence,
    )


@router.post("/{event_id}/capture/finalize-v2", response_model=CaptureFinalizeV2Response)
async def finalize_capture_v2(
    event_id: str,
    payload: CaptureFinalizeV2Request,
    background_tasks: BackgroundTasks,
    firestore: FirestoreDep,
    gemini: GeminiDep,
    event: dict = Depends(validate_sale_owner),
):
    """
    Phase 2 live-capture finalize: accepts pre-analyzed items (name/brand/price/gcs_uri already
    extracted per-frame), skips re-extraction, runs refinement + pricing in background.
    Path: POST /api/v1/sales/{event_id}/capture/finalize-v2
    """
    if not payload.items:
        raise HTTPException(status_code=400, detail="At least one item is required")
    meta: dict = {"captureInput": [item.model_dump() for item in payload.items]}
    if payload.sale_title and payload.sale_title.strip():
        meta["title"] = payload.sale_title.strip()
    await firestore.update_sale_metadata(event_id, meta)
    background_tasks.add_task(run_capture_refinement_pipeline, event_id, payload.items, firestore, gemini)
    return CaptureFinalizeV2Response(event_id=event_id, status="processing_started", item_count=len(payload.items))


@router.post("/{event_id}/suggest-title", response_model=SuggestTitleResponse)
async def suggest_sale_title(
    event_id: str,
    payload: SuggestTitleRequest,
    gemini: GeminiDep,
    _: dict = Depends(validate_sale_owner),
):
    """
    Text-only Gemini call: given item names, suggest a sale title.
    Path: POST /api/v1/sales/{event_id}/suggest-title
    """
    if not payload.item_names:
        raise HTTPException(status_code=400, detail="item_names required")
    title = await gemini.suggest_sale_title(payload.item_names)
    return SuggestTitleResponse(title=title)


@router.post("/{event_id}/retry-finalize", response_model=CaptureFinalizeV2Response)
async def retry_finalize(
    event_id: str,
    background_tasks: BackgroundTasks,
    firestore: FirestoreDep,
    gemini: GeminiDep,
    sale: dict = Depends(validate_sale_owner),
):
    """
    Re-run capture refinement pipeline using stored captureInput payload.
    Clears existing bundles first. Only valid for FAILED sales.
    Path: POST /api/v1/sales/{event_id}/retry-finalize
    """
    if sale.get("status") != "failed":
        raise HTTPException(status_code=409, detail="Sale must be in failed state to retry")

    raw_items = sale.get("captureInput")
    if not raw_items:
        raise HTTPException(status_code=422, detail="No stored capture input found — cannot retry")

    from app.models.schemas import CapturedItemInput
    items = [CapturedItemInput(**i) for i in raw_items]

    # Clear existing bundles from failed run
    summary = await firestore.get_full_event_summary(event_id)
    if summary:
        for bundle in summary.get("bundles", []):
            await firestore.delete_bundle(event_id, bundle["id"])

    background_tasks.add_task(run_capture_refinement_pipeline, event_id, items, firestore, gemini)
    return CaptureFinalizeV2Response(event_id=event_id, status="processing_started", item_count=len(items))


@router.get("/", response_model=list[SaleStatusResponse])
async def list_sales(
    firestore: FirestoreDep,
    gcs: GCSDep,
    current_user: User = Depends(get_current_user),
):
    sales = await firestore.list_all_sales(current_user.id)
    for sale in sales:
        signed: list[str] = []
        for path in sale.get("preview_images", []):
            if path.startswith("gs://"):
                parts = path.replace("gs://", "").split("/", 1)
                signed.append(gcs.generate_download_url(parts[0], parts[1]))
        sale["preview_images"] = signed
    return sales


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

    cover = summary.get("coverImage")
    if cover and isinstance(cover, dict):
        cover_path = cover.get("gcs_path", "")
        if cover_path.startswith("gs://"):
            s = cover_path.replace("gs://", "").split("/", 1)
            cover["url"] = gcs.generate_download_url(s[0], s[1])

    for bundle in summary.get("bundles", []):
        for item in bundle.get("items", []):
            if "images" in item and isinstance(item["images"], list):
                for img in item["images"]:
                    img_path = img.get("gcs_path")
                    if img_path and img_path.startswith("gs://"):
                        s = img_path.replace("gs://", "").split("/", 1)
                        img["url"] = gcs.generate_download_url(s[0], s[1])

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

# --- SALE METADATA PATCH ---

@router.patch("/{event_id}", response_model=StatusResponse)
async def patch_sale(
    event_id: str,
    payload: SaleUpdate,
    firestore: FirestoreDep,
    current_user: User = Depends(get_current_user),
    sale: dict = Depends(validate_sale_owner),
):
    """
    Update sale metadata (title, description, address, move-out date).
    Status-gated: only editable in ready_for_review, live, partially_sold, failed.
    Path: PATCH /api/v1/sales/{event_id}
    """
    assert_editable(sale)
    updates = payload.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=422, detail="No valid fields provided")
    field_map = {"move_out_date": "moveOutDate", "street_address": "streetAddress"}
    mapped = {field_map.get(k, k): v for k, v in updates.items()}
    await firestore.patch_sale(event_id, mapped, current_user.id)
    await notifier.notify_event(event_id, {"type": "SALE_UPDATED", "updates": list(mapped.keys())})
    return {"status": "updated"}


# --- SALE COVER IMAGE ---

@router.post("/{event_id}/cover/upload-url", response_model=CoverUploadUrlResponse)
async def get_cover_upload_url(
    event_id: str,
    gcs: GCSDep,
    bucket: BucketDep,
    sale: dict = Depends(validate_sale_owner),
):
    """Get a signed PUT URL to upload a sale cover image."""
    assert_editable(sale)
    image_id = str(uuid.uuid4())
    blob_name = f"sales/{event_id}/cover/{image_id}.jpg"
    gcs_path = f"gs://{bucket}/{blob_name}"
    upload_url = gcs.generate_image_upload_url(bucket, blob_name)
    return CoverUploadUrlResponse(image_id=image_id, upload_url=upload_url, gcs_path=gcs_path)


@router.post("/{event_id}/cover/confirm", response_model=StatusResponse)
async def confirm_cover(
    event_id: str,
    payload: CoverConfirmRequest,
    firestore: FirestoreDep,
    sale: dict = Depends(validate_sale_owner),
):
    """Confirm a cover image that was PUT to GCS."""
    assert_editable(sale)
    cover_data = {"id": payload.image_id, "gcs_path": payload.gcs_path, "source": "user_upload"}
    await firestore.set_cover(event_id, cover_data)
    await notifier.notify_event(event_id, {"type": "COVER_UPDATED"})
    return {"status": "updated"}


@router.post("/{event_id}/cover/from-item", response_model=StatusResponse)
async def cover_from_item(
    event_id: str,
    payload: CoverFromItemRequest,
    firestore: FirestoreDep,
    sale: dict = Depends(validate_sale_owner),
):
    """Promote an existing item image to the sale cover image."""
    assert_editable(sale)
    item = await firestore.get_item_standalone(event_id, payload.bundle_id, payload.item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    images: list[dict] = item.get("images", [])
    target = next((img for img in images if img.get("id") == payload.image_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="Image not found")
    cover_data = {
        "id": payload.image_id,
        "gcs_path": target["gcs_path"],
        "source": target.get("source", "user_upload"),
    }
    await firestore.set_cover(event_id, cover_data)
    await notifier.notify_event(event_id, {"type": "COVER_UPDATED"})
    return {"status": "updated"}


@router.delete("/{event_id}/cover", response_model=StatusResponse)
async def delete_cover(
    event_id: str,
    firestore: FirestoreDep,
    sale: dict = Depends(validate_sale_owner),
):
    """Remove the sale cover image."""
    assert_editable(sale)
    await firestore.clear_cover(event_id)
    return {"status": "deleted"}


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


@router.patch("/{event_id}/bundles/{bundle_id}", response_model=StatusResponse)
async def update_bundle(
    event_id: str,
    bundle_id: str,
    payload: BundleUpdateRequest,
    firestore: FirestoreDep,
    sale: dict = Depends(validate_sale_owner),
):
    assert_editable(sale)
    raw = payload.model_dump(exclude_none=True)
    if not raw:
        raise HTTPException(status_code=422, detail="No valid fields provided")
    # Remap snake_case payload keys to camelCase Firestore convention
    key_map = {"bundle_discount_percent": "bundleDiscountPercent"}
    updates = {key_map.get(k, k): v for k, v in raw.items()}
    await firestore.update_bundle_metadata(event_id, bundle_id, updates)
    await notifier.notify_event(event_id, {"type": "BUNDLE_UPDATED", "bundle_id": bundle_id, **updates})
    return {"status": "updated"}


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
        return {"status": "updated"}

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


@router.post("/{event_id}/bundles/{bundle_id}/items/{item_id}/reprice", response_model=ItemRepriceResponse)
async def reprice_item(
    event_id: str,
    bundle_id: str,
    item_id: str,
    firestore: FirestoreDep,
    gemini: GeminiDep,
    _: dict = Depends(validate_sale_owner),
):
    sale = await firestore.get_full_event_summary(event_id)
    if not sale:
        raise HTTPException(status_code=404, detail="Sale not found")

    item_doc = None
    for bundle in sale.get("bundles", []):
        if bundle["id"] == bundle_id:
            for it in bundle["items"]:
                if it["id"] == item_id:
                    item_doc = it
                    break

    if not item_doc:
        raise HTTPException(status_code=404, detail="Item not found")

    move_out_date = sale.get("moveOutDate") or datetime.now(timezone.utc).strftime("%Y-%m-%d")

    context_item = {
        "id": item_id,
        "name": item_doc["name"],
        "brand": item_doc.get("brand"),
        "condition": item_doc.get("condition"),
        "original_price": item_doc.get("actual_original_price") or item_doc.get("predicted_original_price"),
        "purchase_year": item_doc.get("actual_year_of_purchase") or item_doc.get("predicted_year_of_purchase"),
    }

    priced_results, _ = await gemini.estimate_listing_prices([context_item], move_out_date)

    if not priced_results:
        raise HTTPException(status_code=502, detail="AI pricing returned no results")

    result = priced_results[0]
    listing_price = result.get("listing_price", 0)
    reasoning = result.get("reasoning", "Market adjustment based on Sydney demand.")

    # Return suggestion only — caller applies via PATCH if user accepts
    return ItemRepriceResponse(
        predicted_listing_price=listing_price,
        actual_listing_price=listing_price,
        pricing_reasoning=reasoning,
    )


@router.patch("/{event_id}/bundles/{bundle_id}/items/{item_id}/move", response_model=StatusResponse)
async def move_item(
    event_id: str,
    bundle_id: str,
    item_id: str,
    payload: ItemMoveRequest,
    firestore: FirestoreDep,
    sale: dict = Depends(validate_sale_owner),
):
    assert_editable(sale)
    if payload.to_bundle_id == bundle_id:
        return {"status": "updated"}
    try:
        await firestore.move_item(event_id, bundle_id, item_id, payload.to_bundle_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    await notifier.notify_event(event_id, {
        "type": "ITEM_MOVED",
        "item_id": item_id,
        "from_bundle_id": bundle_id,
        "to_bundle_id": payload.to_bundle_id,
    })
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


# --- ITEM IMAGE ENDPOINTS ---

@router.post(
    "/{event_id}/bundles/{bundle_id}/items/{item_id}/images/upload-urls",
    response_model=ImageUploadUrlsResponse,
)
async def get_item_image_upload_urls(
    event_id: str,
    bundle_id: str,
    item_id: str,
    payload: ImageUploadUrlsRequest,
    gcs: GCSDep,
    bucket: BucketDep,
    _: dict = Depends(validate_sale_owner),
):
    urls: list[ImageUploadUrlItem] = []
    for f in payload.files:
        image_id = str(uuid.uuid4())
        ext = mimetypes.guess_extension(f.content_type) or ".jpg"
        if ext == ".jpe":
            ext = ".jpg"
        blob_name = f"sales/{event_id}/items/{item_id}/{image_id}{ext}"
        gcs_path = f"gs://{bucket}/{blob_name}"
        upload_url = gcs.generate_image_upload_url(bucket, blob_name, f.content_type)
        urls.append(ImageUploadUrlItem(image_id=image_id, upload_url=upload_url, gcs_path=gcs_path))
    return ImageUploadUrlsResponse(urls=urls)


@router.post(
    "/{event_id}/bundles/{bundle_id}/items/{item_id}/images/confirm",
    response_model=StatusResponse,
)
async def confirm_item_images(
    event_id: str,
    bundle_id: str,
    item_id: str,
    payload: ImageConfirmRequest,
    firestore: FirestoreDep,
    _: dict = Depends(validate_sale_owner),
):
    now = datetime.now(timezone.utc).isoformat()
    for img in payload.images:
        image_obj = {
            "id": img.image_id,
            "gcs_path": img.gcs_path,
            "source": "user_upload",
            "is_cover": False,
            "uploaded_at": now,
        }
        await firestore.update_item_data(
            event_id, bundle_id, item_id,
            {"images": ArrayUnion([image_obj])},
        )
    return {"status": "confirmed"}


@router.delete(
    "/{event_id}/bundles/{bundle_id}/items/{item_id}/images/{image_id}",
    response_model=StatusResponse,
)
async def delete_item_image(
    event_id: str,
    bundle_id: str,
    item_id: str,
    image_id: str,
    firestore: FirestoreDep,
    gcs: GCSDep,
    bucket: BucketDep,
    _: dict = Depends(validate_sale_owner),
):
    item = await firestore.get_item_standalone(event_id, bundle_id, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    images: list[dict] = item.get("images", [])
    target = next((img for img in images if img.get("id") == image_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="Image not found")

    gcs_path: str = target.get("gcs_path", "")
    if gcs_path.startswith("gs://"):
        blob_name = gcs_path.replace(f"gs://{bucket}/", "")
        try:
            gcs.delete_blob(bucket, blob_name)
        except Exception:
            pass  # GCS deletion is best-effort

    was_cover = target.get("is_cover", False)
    new_images = [img for img in images if img.get("id") != image_id]
    if was_cover and new_images:
        new_images[0]["is_cover"] = True

    await firestore.update_item_data(event_id, bundle_id, item_id, {"images": new_images})
    return {"status": "deleted"}


@router.patch(
    "/{event_id}/bundles/{bundle_id}/items/{item_id}/images/{image_id}/cover",
    response_model=StatusResponse,
)
async def set_item_image_cover(
    event_id: str,
    bundle_id: str,
    item_id: str,
    image_id: str,
    firestore: FirestoreDep,
    _: dict = Depends(validate_sale_owner),
):
    item = await firestore.get_item_standalone(event_id, bundle_id, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    images: list[dict] = item.get("images", [])
    if not any(img.get("id") == image_id for img in images):
        raise HTTPException(status_code=404, detail="Image not found")

    new_images = [
        {**img, "is_cover": img.get("id") == image_id}
        for img in images
    ]
    await firestore.update_item_data(event_id, bundle_id, item_id, {"images": new_images})
    return {"status": "updated"}


@router.patch(
    "/{event_id}/bundles/{bundle_id}/items/{item_id}/images/order",
    response_model=StatusResponse,
)
async def reorder_item_images(
    event_id: str,
    bundle_id: str,
    item_id: str,
    payload: ImageReorderRequest,
    firestore: FirestoreDep,
    sale: dict = Depends(validate_sale_owner),
):
    assert_editable(sale)
    try:
        await firestore.reorder_item_images(event_id, bundle_id, item_id, payload.image_ids)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"status": "updated"}


# --- SALE LIFECYCLE ---

@router.post("/{event_id}/archive", response_model=StatusResponse)
async def archive_sale_endpoint(
    event_id: str,
    firestore: FirestoreDep,
    sale: dict = Depends(validate_sale_owner),
):
    """Soft-archive a sale (sets status=ARCHIVED). Blocked while processing."""
    if sale.get("status") in [SaleStatus.PROCESSING, SaleStatus.PRICING_IN_PROGRESS]:
        raise HTTPException(status_code=409, detail="Cannot archive while AI is processing.")
    await firestore.archive_sale(event_id)
    await notifier.notify_event(event_id, {"type": "SALE_ARCHIVED"})
    return {"status": SaleStatus.ARCHIVED}


@router.delete("/{event_id}", response_model=StatusResponse)
async def delete_sale(
    event_id: str,
    firestore: FirestoreDep,
    gcs: GCSDep,
    bucket: BucketDep,
    sale: dict = Depends(validate_sale_owner),
):
    """Hard-delete a sale (PENDING_UPLOAD or FAILED only). Purges GCS + Firestore."""
    if sale.get("status") not in [SaleStatus.PENDING_UPLOAD, SaleStatus.FAILED]:
        raise HTTPException(
            status_code=409,
            detail="Only pending_upload or failed sales can be permanently deleted. Use /archive for others.",
        )
    gcs_paths = await firestore.hard_delete_sale(event_id)
    for path in gcs_paths:
        blob_name = path.replace(f"gs://{bucket}/", "")
        gcs.delete_blob(bucket, blob_name)
    return {"status": "deleted"}


@router.post("/{event_id}/republish", response_model=StatusResponse)
async def republish_sale(
    event_id: str,
    firestore: FirestoreDep,
    sale: dict = Depends(validate_sale_owner),
):
    """Re-publish a sale that was unpublished. Must be ready_for_review."""
    if sale.get("status") not in [SaleStatus.READY_FOR_REVIEW]:
        raise HTTPException(status_code=400, detail="Sale must be ready_for_review to republish.")
    await firestore.transition_sale_status(event_id, SaleStatus.LIVE)
    await notifier.notify_event(event_id, {"type": "SALE_REPUBLISHED"})
    return {"status": SaleStatus.LIVE}



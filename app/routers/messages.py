import logging
import time
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect

# Per-user TTL cache for unread count: {uid: (count, expires_at)}
_unread_cache: dict[str, tuple[int, float]] = {}
_UNREAD_TTL = 20.0

from app.core.deps import FirestoreDep, MessagingDep
from app.models.schemas import (
    ConversationStartRequest,
    ConversationStartResponse,
    ConversationSummaryResponse,
    CounterOfferRequest,
    MessagesListResponse,
    MessageResponse,
    PhoneRevealResponse,
    SendMessageRequest,
    SendOfferRequest,
    SetPinRequest,
    StatusResponse,
    UnreadCountResponse,
)
from app.core.deps import GCSDep
from app.services.auth import User, get_current_user
from app.services.notifier import notifier

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/messages", tags=["Messaging"])

CurrentUser = Annotated[User, Depends(get_current_user)]


@router.post("/conversations", response_model=ConversationStartResponse)
async def start_conversation(
    body: ConversationStartRequest,
    current_user: CurrentUser,
    firestore: FirestoreDep,
    messaging: MessagingDep,
):
    if body.otherUserId == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot message yourself")

    other_user = await firestore.get_user(body.otherUserId)
    if not other_user:
        raise HTTPException(status_code=404, detail="User not found")

    conv_id, conv_data = await messaging.start_conversation(current_user.id, body.otherUserId)

    if body.initialMessage:
        ctx = body.context.model_dump() if body.context else None
        try:
            await messaging.send(conv_id, current_user.id, body.initialMessage, ctx)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))

    return ConversationStartResponse(conversationId=conv_id, created=True)


@router.get("/conversations", response_model=list[ConversationSummaryResponse])
async def list_conversations(current_user: CurrentUser, firestore: FirestoreDep, messaging: MessagingDep):
    convs = await messaging.list_conversations(current_user.id, firestore.users)
    return [ConversationSummaryResponse(**c) for c in convs]


@router.get("/conversations/unread", response_model=UnreadCountResponse)
async def unread_count(current_user: CurrentUser, messaging: MessagingDep):
    uid = current_user.id
    cached = _unread_cache.get(uid)
    if cached and time.monotonic() < cached[1]:
        return UnreadCountResponse(unreadCount=cached[0])
    count = await messaging.get_unread_count(uid)
    _unread_cache[uid] = (count, time.monotonic() + _UNREAD_TTL)
    return UnreadCountResponse(unreadCount=count)


@router.get("/conversations/{conv_id}/messages", response_model=MessagesListResponse)
async def get_messages(
    conv_id: str,
    current_user: CurrentUser,
    messaging: MessagingDep,
    before: str | None = Query(None),
    limit: int = Query(50, ge=1, le=100),
):
    try:
        msgs = await messaging.list_messages(conv_id, current_user.id, before=before, limit=limit)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    return MessagesListResponse(
        messages=[MessageResponse(**m) for m in msgs],
        conversationId=conv_id,
    )


@router.post("/conversations/{conv_id}/messages", response_model=MessageResponse)
async def send_message(
    conv_id: str,
    body: SendMessageRequest,
    current_user: CurrentUser,
    messaging: MessagingDep,
    firestore: FirestoreDep,
):
    ctx = body.context.model_dump() if body.context else None
    try:
        msg = await messaging.send(conv_id, current_user.id, body.text, ctx)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    await firestore.users.update_last_seen(current_user.id)
    _unread_cache.pop(current_user.id, None)
    return MessageResponse(**msg)


@router.post("/conversations/{conv_id}/read", response_model=dict)
async def mark_read(conv_id: str, current_user: CurrentUser, messaging: MessagingDep):
    await messaging.mark_read(conv_id, current_user.id)
    _unread_cache.pop(current_user.id, None)
    return {"status": "ok"}


@router.post("/conversations/{conv_id}/block", response_model=dict)
async def block_conversation(conv_id: str, current_user: CurrentUser, messaging: MessagingDep):
    try:
        await messaging.block(conv_id, current_user.id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    return {"status": "blocked"}


@router.post("/conversations/{conv_id}/unblock", response_model=dict)
async def unblock_conversation(conv_id: str, current_user: CurrentUser, messaging: MessagingDep):
    try:
        await messaging.unblock(conv_id, current_user.id)
    except (PermissionError, ValueError) as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    return {"status": "active"}


@router.patch("/conversations/{conv_id}/pin", response_model=MessageResponse)
async def patch_pin(
    conv_id: str,
    body: SetPinRequest,
    current_user: CurrentUser,
    firestore: FirestoreDep,
    messaging: MessagingDep,
    gcs: GCSDep,
):
    # Validate participant
    conv = await firestore.conversations.get_conversation(conv_id)
    if not conv or current_user.id not in conv.get("participants", []):
        raise HTTPException(status_code=403, detail="Not a participant")

    # Clear pin
    if body.kind is None:
        user = await firestore.get_user(current_user.id)
        username = user.get("username") if user else None
        try:
            msg = await messaging.clear_pin(conv_id, current_user.id, username)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        return MessageResponse(**msg)

    # Validate required fields
    if not body.saleEventId:
        raise HTTPException(status_code=422, detail="saleEventId required")
    if body.kind == "item" and (not body.bundleId or not body.itemId):
        raise HTTPException(status_code=422, detail="bundleId and itemId required for kind=item")
    if body.kind == "bundle" and not body.bundleId:
        raise HTTPException(status_code=422, detail="bundleId required for kind=bundle")

    # Resolve snapshot + cross-seller check
    sale = await firestore.sales.get_sale_event(body.saleEventId)
    if not sale:
        raise HTTPException(status_code=404, detail="Sale not found")
    sale_seller = sale.get("sellerId") or sale.get("userId")
    if sale_seller not in conv.get("participants", []):
        raise HTTPException(status_code=403, detail="Sale seller is not a conversation participant")

    def _gcs_url(gcs_path: str | None) -> str | None:
        if not gcs_path or not gcs_path.startswith("gs://"):
            return None
        try:
            parts = gcs_path.replace("gs://", "").split("/", 1)
            return gcs.generate_download_url(parts[0], parts[1])
        except Exception:
            return None

    snapshot: dict = {}
    if body.kind == "item":
        item = await firestore.get_item_standalone(body.saleEventId, body.bundleId, body.itemId)
        if not item:
            raise HTTPException(status_code=404, detail="Item not found")
        images = item.get("images", [])
        cover = next((img for img in images if img.get("is_cover")), images[0] if images else None)
        snapshot = {
            "name": item.get("name"),
            "imageUrl": _gcs_url(cover.get("gcs_path") if cover else None),
            "price": item.get("actual_listing_price") or item.get("predicted_listing_price"),
            "rrp": item.get("original_price"),
            "condition": item.get("condition"),
            "itemCount": None,
            "suburb": sale.get("suburb"),
        }
    elif body.kind == "bundle":
        bundle_ref = firestore.db.collection("saleEvents").document(body.saleEventId).collection("bundles").document(body.bundleId)
        bundle_doc = await bundle_ref.get()
        if not bundle_doc.exists:
            raise HTTPException(status_code=404, detail="Bundle not found")
        bundle_data = bundle_doc.to_dict()
        item_count = 0
        cover_gcs = None
        async for item_snap in bundle_ref.collection("items").stream():
            item_count += 1
            if cover_gcs is None:
                idata = item_snap.to_dict()
                imgs = idata.get("images", [])
                cover_img = next((img for img in imgs if img.get("is_cover")), imgs[0] if imgs else None)
                if cover_img:
                    cover_gcs = cover_img.get("gcs_path")
        snapshot = {
            "name": bundle_data.get("name"),
            "imageUrl": _gcs_url(cover_gcs),
            "price": bundle_data.get("suggested_price"),
            "rrp": None,
            "condition": None,
            "itemCount": item_count,
            "suburb": sale.get("suburb"),
        }
    else:  # kind == "sale"
        sale_cover = sale.get("coverImage") or {}
        item_count = 0
        total_price = 0.0
        event_ref = firestore.db.collection("saleEvents").document(body.saleEventId)
        async for b in event_ref.collection("bundles").stream():
            async for i in b.reference.collection("items").stream():
                item_count += 1
                idata = i.to_dict()
                total_price += idata.get("actual_listing_price") or idata.get("predicted_listing_price") or 0
        snapshot = {
            "name": sale.get("title") or (f"{sale.get('suburb')} Moving Sale" if sale.get("suburb") else "Moving Sale"),
            "imageUrl": _gcs_url(sale_cover.get("gcs_path")),
            "price": total_price if total_price > 0 else None,
            "rrp": None,
            "condition": None,
            "itemCount": item_count,
            "suburb": sale.get("suburb"),
        }

    pin_ref = {
        "kind": body.kind,
        "saleEventId": body.saleEventId,
        "bundleId": body.bundleId,
        "itemId": body.itemId,
    }

    user = await firestore.get_user(current_user.id)
    username = user.get("username") if user else None

    try:
        msg = await messaging.set_pin(conv_id, current_user.id, pin_ref, snapshot, username)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    return MessageResponse(**msg)


@router.post("/conversations/{conv_id}/offers", response_model=MessageResponse)
async def send_offer(
    conv_id: str,
    body: SendOfferRequest,
    current_user: CurrentUser,
    messaging: MessagingDep,
):
    if body.amount <= 0:
        raise HTTPException(status_code=422, detail="Offer amount must be positive")
    try:
        msg = await messaging.send_offer(
            conv_id, current_user.id, body.amount,
            parent_offer_id=body.parentOfferId,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return MessageResponse(**msg)


@router.post("/conversations/{conv_id}/offers/{offer_id}/accept", response_model=MessageResponse)
async def accept_offer(
    conv_id: str,
    offer_id: str,
    current_user: CurrentUser,
    messaging: MessagingDep,
):
    try:
        msg = await messaging.accept_offer(conv_id, offer_id, current_user.id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return MessageResponse(**msg)


@router.post("/conversations/{conv_id}/offers/{offer_id}/counter", response_model=MessageResponse)
async def counter_offer(
    conv_id: str,
    offer_id: str,
    body: CounterOfferRequest,
    current_user: CurrentUser,
    messaging: MessagingDep,
):
    if body.amount <= 0:
        raise HTTPException(status_code=422, detail="Counter amount must be positive")
    try:
        msg = await messaging.counter_offer(conv_id, offer_id, current_user.id, body.amount)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return MessageResponse(**msg)


@router.post("/conversations/{conv_id}/offers/{offer_id}/withdraw", response_model=MessageResponse)
async def withdraw_offer(
    conv_id: str,
    offer_id: str,
    current_user: CurrentUser,
    messaging: MessagingDep,
):
    try:
        msg = await messaging.withdraw_offer(conv_id, offer_id, current_user.id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return MessageResponse(**msg)


@router.post("/conversations/{conv_id}/phone/share", response_model=StatusResponse)
async def share_phone(
    conv_id: str,
    current_user: CurrentUser,
    firestore: FirestoreDep,
):
    try:
        await firestore.share_phone(conv_id, current_user.id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return StatusResponse(status="shared")


@router.get("/conversations/{conv_id}/phone", response_model=PhoneRevealResponse)
async def get_phone(
    conv_id: str,
    current_user: CurrentUser,
    firestore: FirestoreDep,
):
    try:
        phone = await firestore.get_phone_reveal(conv_id, current_user.id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    logger.info("phone_reveal conv=%s requester=%s", conv_id, current_user.id)
    return PhoneRevealResponse(phoneE164=phone)


@router.websocket("/ws")
async def user_ws(websocket: WebSocket, firestore: FirestoreDep, token: str = Query(...)):
    from app.services.auth import get_current_user as _gcv
    try:
        user = await _gcv(websocket, token=token, firestore=firestore)
    except Exception:
        await websocket.close(code=4001)
        return

    await notifier.connect_user(user.id, websocket)
    await firestore.users.update_last_seen(user.id)
    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await firestore.users.update_last_seen(user.id)
    except WebSocketDisconnect:
        notifier.disconnect_user(user.id, websocket)

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect

from app.core.deps import FirestoreDep, MessagingDep
from app.models.schemas import (
    ConversationStartRequest,
    ConversationStartResponse,
    ConversationSummaryResponse,
    MessagesListResponse,
    MessageResponse,
    SendMessageRequest,
    UnreadCountResponse,
)
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
    created = conv_data.get("createdAt") is None  # rough heuristic; repo sets SERVER_TIMESTAMP

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
    count = await messaging.get_unread_count(current_user.id)
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
):
    ctx = body.context.model_dump() if body.context else None
    try:
        msg = await messaging.send(conv_id, current_user.id, body.text, ctx)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return MessageResponse(**msg)


@router.post("/conversations/{conv_id}/read", response_model=dict)
async def mark_read(conv_id: str, current_user: CurrentUser, messaging: MessagingDep):
    await messaging.mark_read(conv_id, current_user.id)
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


@router.websocket("/ws")
async def user_ws(websocket: WebSocket, token: str = Query(...), firestore: FirestoreDep = Depends()):
    from app.services.auth import get_current_user as _gcv
    try:
        user = await _gcv(websocket, token=token, firestore=firestore)
    except Exception:
        await websocket.close(code=4001)
        return

    await notifier.connect_user(user.id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        notifier.disconnect_user(user.id, websocket)

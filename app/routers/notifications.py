import logging
from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.deps import FirestoreDep
from app.services.auth import User, get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/notifications", tags=["Notifications"])

CurrentUser = Annotated[User, Depends(get_current_user)]


@router.get("/unread-count")
async def get_unread_count(current_user: CurrentUser, firestore: FirestoreDep) -> dict:
    count = await firestore.notifications.unread_count(current_user.id)
    return {"unread_count": count}


@router.get("")
async def list_notifications(current_user: CurrentUser, firestore: FirestoreDep) -> list[dict]:
    notifs = await firestore.notifications.list(current_user.id, limit=30)
    return [_serialize(n) for n in notifs]


@router.post("/{notif_id}/read")
async def mark_read(notif_id: str, current_user: CurrentUser, firestore: FirestoreDep) -> dict:
    await firestore.notifications.mark_read(current_user.id, notif_id)
    return {"ok": True}


@router.post("/mark-all-read")
async def mark_all_read(current_user: CurrentUser, firestore: FirestoreDep) -> dict:
    await firestore.notifications.mark_all_read(current_user.id)
    return {"ok": True}


def _serialize(n: dict) -> dict:
    def _ts(v):
        if v is None:
            return None
        try:
            return v.isoformat() if hasattr(v, "isoformat") else str(v)
        except Exception:
            return None

    return {
        "id": n.get("id"),
        "type": n.get("type"),
        "title": n.get("title"),
        "body": n.get("body"),
        "link": n.get("link"),
        "readAt": _ts(n.get("readAt")),
        "createdAt": _ts(n.get("createdAt")),
    }

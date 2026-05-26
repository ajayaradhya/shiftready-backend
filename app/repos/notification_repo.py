import logging
import uuid
from datetime import datetime, timezone
from typing import Literal

from google.cloud import firestore

logger = logging.getLogger(__name__)

NotifType = Literal["message.new", "offer.new", "offer.accepted", "offer.countered", "sale.ready"]


class NotificationRepo:
    def __init__(self, db: firestore.AsyncClient):
        self.db = db

    def _col(self, uid: str):
        return self.db.collection("users").document(uid).collection("notifications")

    async def create(
        self,
        uid: str,
        type: NotifType,
        title: str,
        body: str,
        link: str,
    ) -> str:
        notif_id = str(uuid.uuid4())
        await self._col(uid).document(notif_id).set({
            "type": type,
            "title": title,
            "body": body,
            "link": link,
            "readAt": None,
            "createdAt": firestore.SERVER_TIMESTAMP,
        })
        return notif_id

    async def list(self, uid: str, limit: int = 30) -> list[dict]:
        snaps = (
            await self._col(uid)
            .order_by("createdAt", direction=firestore.Query.DESCENDING)
            .limit(limit)
            .get()
        )
        result = []
        for s in snaps:
            d = s.to_dict() or {}
            d["id"] = s.id
            result.append(d)
        return result

    async def mark_read(self, uid: str, notif_id: str) -> None:
        ref = self._col(uid).document(notif_id)
        snap = await ref.get()
        if snap.exists and snap.get("readAt") is None:
            await ref.update({"readAt": firestore.SERVER_TIMESTAMP})

    async def mark_all_read(self, uid: str) -> None:
        snaps = await self._col(uid).where("readAt", "==", None).get()
        now = datetime.now(timezone.utc)
        for s in snaps:
            await s.reference.update({"readAt": now})

    async def unread_count(self, uid: str) -> int:
        snaps = await self._col(uid).where("readAt", "==", None).get()
        return len(snaps)

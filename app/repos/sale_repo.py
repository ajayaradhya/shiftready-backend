from datetime import datetime
from typing import Optional
from google.cloud import firestore

from app.domain.status import SaleStatus


class SaleRepo:
    def __init__(self, db: firestore.AsyncClient):
        self.db = db

    def _ref(self, event_id: str):
        return self.db.collection("saleEvents").document(event_id)

    async def create_sale_event(self, user_id: str, video_url: str) -> str:
        doc_ref = self.db.collection("saleEvents").document()
        await doc_ref.set({
            "sellerId": user_id,
            "status": SaleStatus.PENDING_UPLOAD,
            "videoUrl": video_url,
            "createdAt": firestore.SERVER_TIMESTAMP,
            "updatedAt": firestore.SERVER_TIMESTAMP,
            "statusHistory": [{"status": SaleStatus.PENDING_UPLOAD, "timestamp": datetime.now()}],
        })
        return doc_ref.id

    async def get_sale_event(self, event_id: str) -> Optional[dict]:
        doc = await self._ref(event_id).get()
        return doc.to_dict() if doc.exists else None

    async def transition_sale_status(self, event_id: str, new_status: SaleStatus) -> bool:
        await self._ref(event_id).update({
            "status": new_status,
            "lastTransitionAt": firestore.SERVER_TIMESTAMP,
            "updatedAt": firestore.SERVER_TIMESTAMP,
            "statusHistory": firestore.ArrayUnion([
                {"status": new_status, "timestamp": datetime.now()}
            ]),
        })
        return True

    async def update_sale_metadata(self, event_id: str, updates: dict) -> None:
        await self._ref(event_id).update({**updates, "updatedAt": firestore.SERVER_TIMESTAMP})

    async def list_all_sales(self, user_id: str) -> list[dict]:
        docs = (
            self.db.collection("saleEvents")
            .where(filter=firestore.FieldFilter("sellerId", "==", user_id))
            .order_by("createdAt", direction="DESCENDING")
            .stream()
        )
        return [{**d.to_dict(), "id": d.id} async for d in docs]

    async def get_full_event_summary(self, event_id: str) -> Optional[dict]:
        event_ref = self._ref(event_id)
        event_doc = await event_ref.get()
        if not event_doc.exists:
            return None

        data = {**event_doc.to_dict(), "id": event_id, "bundles": []}

        async for b in event_ref.collection("bundles").stream():
            b_data = {**b.to_dict(), "id": b.id, "items": []}
            async for i in b.reference.collection("items").stream():
                b_data["items"].append({**i.to_dict(), "id": i.id})
            data["bundles"].append(b_data)

        return data

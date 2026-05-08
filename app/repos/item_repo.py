from typing import Optional
from google.cloud import firestore

from app.repos.bundle_repo import BundleRepo


class ItemRepo:
    def __init__(self, db: firestore.AsyncClient, bundle_repo: BundleRepo):
        self.db = db
        self._bundles = bundle_repo

    def _item_ref(self, event_id: str, bundle_id: str, item_id: str):
        return (
            self.db.collection("saleEvents")
            .document(event_id)
            .collection("bundles")
            .document(bundle_id)
            .collection("items")
            .document(item_id)
        )

    async def add_item_to_bundle(self, event_id: str, bundle_id: str, item_data: dict) -> str:
        ref = (
            self.db.collection("saleEvents")
            .document(event_id)
            .collection("bundles")
            .document(bundle_id)
            .collection("items")
            .document()
        )
        await ref.set(item_data)
        return ref.id

    async def update_item_data(
        self, event_id: str, bundle_id: str, item_id: str, updates: dict
    ) -> None:
        await self._item_ref(event_id, bundle_id, item_id).update(updates)

    async def delete_item(self, event_id: str, bundle_id: str, item_id: str) -> bool:
        await self._item_ref(event_id, bundle_id, item_id).delete()
        await self._bundles.recalculate_bundle_total(event_id, bundle_id)
        return True

    async def get_item_standalone(
        self, event_id: str, bundle_id: str, item_id: str
    ) -> Optional[dict]:
        doc = await self._item_ref(event_id, bundle_id, item_id).get()
        return {**doc.to_dict(), "id": doc.id} if doc.exists else None

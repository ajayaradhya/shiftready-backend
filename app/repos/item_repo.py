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
    ) -> dict | None:
        doc = await self._item_ref(event_id, bundle_id, item_id).get()
        return {**doc.to_dict(), "id": doc.id} if doc.exists else None

    async def move_item(
        self, event_id: str, from_bundle_id: str, item_id: str, to_bundle_id: str
    ) -> None:
        src_ref = self._item_ref(event_id, from_bundle_id, item_id)
        dst_ref = self._item_ref(event_id, to_bundle_id, item_id)
        doc = await src_ref.get()
        if not doc.exists:
            raise ValueError("Item not found")
        await dst_ref.set(doc.to_dict())
        await src_ref.delete()
        await self._bundles.recalculate_bundle_total(event_id, from_bundle_id)
        await self._bundles.recalculate_bundle_total(event_id, to_bundle_id)

    async def reorder_images(
        self, event_id: str, bundle_id: str, item_id: str, image_ids: list[str]
    ) -> None:
        item_ref = self._item_ref(event_id, bundle_id, item_id)
        doc = await item_ref.get()
        if not doc.exists:
            raise ValueError("Item not found")
        images: list[dict] = doc.to_dict().get("images") or []
        id_to_img = {img["id"]: img for img in images}
        ordered = [id_to_img[iid] for iid in image_ids if iid in id_to_img]
        remaining = [img for img in images if img["id"] not in set(image_ids)]
        await item_ref.update({"images": ordered + remaining})

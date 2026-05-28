from google.cloud import firestore


class BundleRepo:
    def __init__(self, db: firestore.AsyncClient):
        self.db = db

    def _bundle_ref(self, event_id: str, bundle_id: str):
        return (
            self.db.collection("saleEvents")
            .document(event_id)
            .collection("bundles")
            .document(bundle_id)
        )

    async def add_bundle(
        self, event_id: str, bundle_name: str, suggested_price: float = 0.0
    ) -> str:
        ref = (
            self.db.collection("saleEvents")
            .document(event_id)
            .collection("bundles")
            .document()
        )
        await ref.set(
            {
                "name": bundle_name,
                "suggestedPrice": suggested_price,
                "isPublished": False,
                "createdAt": firestore.SERVER_TIMESTAMP,
            }
        )
        return ref.id

    async def update_bundle_metadata(
        self, event_id: str, bundle_id: str, updates: dict
    ) -> None:
        await self._bundle_ref(event_id, bundle_id).update(updates)

    async def delete_bundle(self, event_id: str, bundle_id: str) -> bool:
        bundle_ref = self._bundle_ref(event_id, bundle_id)
        async for item in bundle_ref.collection("items").stream():
            await item.reference.delete()
        await bundle_ref.delete()
        return True

    async def list_bundles(self, event_id: str) -> list[dict]:
        docs = await (
            self.db.collection("saleEvents")
            .document(event_id)
            .collection("bundles")
            .get()
        )
        return [{**d.to_dict(), "id": d.id} for d in docs]

    async def recalculate_bundle_total(self, event_id: str, bundle_id: str) -> float:
        bundle_ref = self._bundle_ref(event_id, bundle_id)
        total = 0.0
        async for i in bundle_ref.collection("items").stream():
            try:
                total += float(i.to_dict().get("actual_listing_price") or 0)
            except (ValueError, TypeError):
                continue
        await bundle_ref.update(
            {
                "suggestedPrice": total,
                "updatedAt": firestore.SERVER_TIMESTAMP,
            }
        )
        return total

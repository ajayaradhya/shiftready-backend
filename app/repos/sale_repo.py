from datetime import datetime, timezone
from google.cloud import firestore

from app.domain.status import SaleStatus


class SaleRepo:
    def __init__(self, db: firestore.AsyncClient):
        self.db = db

    def _ref(self, event_id: str):
        return self.db.collection("saleEvents").document(event_id)

    async def create_sale_event(self, user_id: str) -> str:
        doc_ref = self.db.collection("saleEvents").document()
        await doc_ref.set({
            "sellerId": user_id,
            "status": SaleStatus.PENDING_UPLOAD,
            "createdAt": firestore.SERVER_TIMESTAMP,
            "updatedAt": firestore.SERVER_TIMESTAMP,
            "statusHistory": [{"status": SaleStatus.PENDING_UPLOAD, "timestamp": datetime.now(timezone.utc)}],
        })
        return doc_ref.id

    async def get_sale_event(self, event_id: str) -> dict | None:
        doc = await self._ref(event_id).get()
        return doc.to_dict() if doc.exists else None

    async def transition_sale_status(self, event_id: str, new_status: SaleStatus) -> bool:
        await self._ref(event_id).update({
            "status": new_status,
            "lastTransitionAt": firestore.SERVER_TIMESTAMP,
            "updatedAt": firestore.SERVER_TIMESTAMP,
            "statusHistory": firestore.ArrayUnion([
                {"status": new_status, "timestamp": datetime.now(timezone.utc)}
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
        results = []
        async for d in docs:
            data = {**d.to_dict(), "id": d.id}
            item_count = 0
            total_value = 0.0
            preview_paths: list[str] = []
            async for b in self._ref(d.id).collection("bundles").stream():
                async for item in b.reference.collection("items").stream():
                    item_data = item.to_dict()
                    item_count += 1
                    price = (
                        item_data.get("actual_listing_price")
                        or item_data.get("predicted_listing_price")
                        or 0
                    )
                    total_value += price
                    if len(preview_paths) < 5:
                        images = item_data.get("images") or []
                        cover = next((img for img in images if img.get("is_cover")), images[0] if images else None)
                        if cover and cover.get("gcs_path"):
                            preview_paths.append(cover["gcs_path"])
            data["itemCount"] = item_count
            data["totalValue"] = total_value
            data["preview_images"] = preview_paths
            results.append(data)
        return results

    async def patch_sale(self, event_id: str, updates: dict, user_id: str) -> None:
        current = await self.get_sale_event(event_id)
        before = {k: (current or {}).get(k) for k in updates}
        history_entry = {
            "fields": list(updates.keys()),
            "before": before,
            "after": updates,
            "userId": user_id,
            "ts": datetime.now(timezone.utc),
        }
        await self._ref(event_id).update({
            **updates,
            "updatedAt": firestore.SERVER_TIMESTAMP,
            "editHistory": firestore.ArrayUnion([history_entry]),
        })

    async def set_cover(self, event_id: str, cover_data: dict) -> None:
        await self._ref(event_id).update({
            "coverImage": cover_data,
            "updatedAt": firestore.SERVER_TIMESTAMP,
        })

    async def clear_cover(self, event_id: str) -> None:
        await self._ref(event_id).update({
            "coverImage": firestore.DELETE_FIELD,
            "updatedAt": firestore.SERVER_TIMESTAMP,
        })

    async def get_full_event_summary(self, event_id: str) -> dict | None:
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

    async def archive_sale(self, event_id: str) -> None:
        await self._ref(event_id).update({
            "status": SaleStatus.ARCHIVED,
            "deletedAt": firestore.SERVER_TIMESTAMP,
            "updatedAt": firestore.SERVER_TIMESTAMP,
            "statusHistory": firestore.ArrayUnion([
                {"status": SaleStatus.ARCHIVED, "timestamp": datetime.now(timezone.utc)}
            ]),
        })

    async def hard_delete_sale(self, event_id: str) -> list[str]:
        """Cascade-delete all subcollections + sale doc. Returns GCS paths for caller to purge."""
        gcs_paths: list[str] = []
        event_ref = self._ref(event_id)

        async for bundle in event_ref.collection("bundles").stream():
            async for item in bundle.reference.collection("items").stream():
                item_data = item.to_dict() or {}
                for img in item_data.get("images") or []:
                    if img.get("gcs_path"):
                        gcs_paths.append(img["gcs_path"])
                await item.reference.delete()
            await bundle.reference.delete()

        sale_doc = await event_ref.get()
        if sale_doc.exists:
            data = sale_doc.to_dict() or {}
            cover = data.get("coverImage") or {}
            if cover.get("gcs_path"):
                gcs_paths.append(cover["gcs_path"])

        await event_ref.delete()
        return gcs_paths


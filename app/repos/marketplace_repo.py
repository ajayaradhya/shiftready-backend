import asyncio
from google.cloud import firestore

from app.domain.status import SaleStatus


class MarketplaceRepo:
    def __init__(self, db: firestore.AsyncClient):
        self.db = db

    async def get_active_inventory(
        self, suburb: str | None = None, query: str | None = None
    ) -> list[dict]:
        sales_query = self.db.collection("saleEvents").where(
            filter=firestore.FieldFilter("status", "==", SaleStatus.LIVE)
        )
        if suburb:
            sales_query = sales_query.where(
                filter=firestore.FieldFilter("suburb", "==", suburb)
            )
        live_sales = await sales_query.limit(20).get()
        if not live_sales:
            return []

        # Fetch all bundles for all LIVE sales concurrently (eliminates N sequential reads)
        bundle_snapshots = await asyncio.gather(*[
            self.db.collection("saleEvents").document(sale.id)
                   .collection("bundles").get()
            for sale in live_sales
        ])

        # Build (sale_meta, bundle_doc) pairs then fetch all item collections concurrently
        bundle_pairs = [
            (sale, bundle)
            for sale, bundles in zip(live_sales, bundle_snapshots)
            for bundle in bundles
        ]
        if not bundle_pairs:
            return []

        item_snapshots = await asyncio.gather(*[
            bundle.reference.collection("items").get()
            for _, bundle in bundle_pairs
        ])

        results = []
        q_lower = query.lower() if query else None
        for (sale, bundle), items in zip(bundle_pairs, item_snapshots):
            sale_data = sale.to_dict()
            b_data = bundle.to_dict()
            for item in items:
                item_data = item.to_dict()
                if q_lower and (
                    q_lower not in item_data.get("name", "").lower()
                    and q_lower not in item_data.get("brand", "").lower()
                ):
                    continue
                results.append({
                    **item_data,
                    "id": item.id,
                    "bundleName": b_data.get("name"),
                    "eventId": sale.id,
                    "sellerId": sale_data.get("sellerId"),
                })
        return results

    async def get_item_standalone(
        self, event_id: str, bundle_id: str, item_id: str
    ) -> dict | None:
        doc = await (
            self.db.collection("saleEvents").document(event_id)
                   .collection("bundles").document(bundle_id)
                   .collection("items").document(item_id).get()
        )
        return {**doc.to_dict(), "id": doc.id} if doc.exists else None

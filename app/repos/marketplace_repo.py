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

    async def get_public_sale(self, event_id: str) -> dict | None:
        sale_doc = await self.db.collection("saleEvents").document(event_id).get()
        if not sale_doc.exists:
            return None

        sale_data = sale_doc.to_dict()
        if sale_data.get("status") != SaleStatus.LIVE:
            return None

        bundle_docs = await (
            self.db.collection("saleEvents").document(event_id)
                   .collection("bundles").get()
        )

        item_snapshots = await asyncio.gather(*[
            self.db.collection("saleEvents").document(event_id)
                   .collection("bundles").document(b.id)
                   .collection("items").get()
            for b in bundle_docs
        ])

        BUNDLE_DISCOUNT = 0.20
        bundles = []
        for bundle_doc, items in zip(bundle_docs, item_snapshots):
            b_data = bundle_doc.to_dict()
            bundle_items = [
                {
                    "id": item.id,
                    "name": item.to_dict().get("name"),
                    "brand": item.to_dict().get("brand"),
                    "condition": item.to_dict().get("condition"),
                    "price": item.to_dict().get("actual_listing_price") or 0,
                }
                for item in items
            ]
            item_total = sum(i["price"] for i in bundle_items)
            bundle_price = round(item_total * (1 - BUNDLE_DISCOUNT), 2)
            bundles.append({
                "id": bundle_doc.id,
                "name": b_data.get("name"),
                "items": bundle_items,
                "itemTotal": item_total,
                "bundlePrice": bundle_price,
                "discountPct": int(BUNDLE_DISCOUNT * 100),
            })

        return {
            "eventId": event_id,
            "suburb": sale_data.get("suburb"),
            "state": sale_data.get("state"),
            "moveOutDate": sale_data.get("moveOutDate"),
            "publishedAt": sale_data.get("publishedAt"),
            "bundles": bundles,
        }

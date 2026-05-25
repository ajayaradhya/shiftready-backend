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

    async def list_live_sales(self) -> list[dict]:
        """Return summary rows for every LIVE sale — used by the landing page sales scroll."""
        live_docs = await (
            self.db.collection("saleEvents")
            .where(filter=firestore.FieldFilter("status", "==", SaleStatus.LIVE))
            .limit(20)
            .get()
        )
        if not live_docs:
            return []

        # Fetch all bundle sub-collections concurrently to get item counts + min price
        bundle_snapshots = await asyncio.gather(*[
            self.db.collection("saleEvents").document(doc.id)
                   .collection("bundles").get()
            for doc in live_docs
        ])

        item_snapshots = await asyncio.gather(*[
            asyncio.gather(*[
                bundle.reference.collection("items").get()
                for bundle in bundles
            ])
            for bundles in bundle_snapshots
        ])

        results = []
        for sale_doc, bundles, per_bundle_items in zip(live_docs, bundle_snapshots, item_snapshots):
            data = sale_doc.to_dict()
            all_items = [item for items in per_bundle_items for item in items]
            prices = []
            preview_paths: list[str] = []
            for i in all_items:
                d = i.to_dict()
                price = d.get("actual_listing_price")
                if price is not None:
                    prices.append(price)
                if len(preview_paths) < 4:
                    images = d.get("images") or []
                    cover = next((img for img in images if img.get("is_cover")), images[0] if images else None)
                    if cover and cover.get("gcs_path"):
                        preview_paths.append(cover["gcs_path"])
            sale_cover = data.get("coverImage") or {}
            results.append({
                "eventId": sale_doc.id,
                "suburb": data.get("suburb"),
                "state": data.get("state"),
                "title": data.get("title"),
                "description": data.get("description"),
                "itemCount": len(all_items),
                "minPrice": min(prices) if prices else None,
                "publishedAt": data.get("publishedAt"),
                "preview_images": preview_paths,
                "cover_image_gcs": sale_cover.get("gcs_path"),
            })
        return results

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

        DEFAULT_BUNDLE_DISCOUNT = 0.20
        bundles = []
        for bundle_doc, items in zip(bundle_docs, item_snapshots):
            b_data = bundle_doc.to_dict()
            bundle_items = []
            for item in items:
                d = item.to_dict()
                images = d.get("images") or []
                cover = next((img for img in images if img.get("is_cover")), images[0] if images else None)
                bundle_items.append({
                    "id": item.id,
                    "name": d.get("name"),
                    "brand": d.get("brand"),
                    "condition": d.get("condition"),
                    "price": d.get("actual_listing_price") or 0,
                    "image_gcs_path": cover.get("gcs_path") if cover else None,
                })
            item_total = sum(i["price"] for i in bundle_items)
            stored_pct = b_data.get("bundleDiscountPercent")
            discount = (stored_pct / 100.0) if stored_pct is not None else DEFAULT_BUNDLE_DISCOUNT
            bundle_price = round(item_total * (1 - discount), 2)
            bundles.append({
                "id": bundle_doc.id,
                "name": b_data.get("name"),
                "items": bundle_items,
                "itemTotal": item_total,
                "bundlePrice": bundle_price,
                "discountPct": int(discount * 100),
            })

        sale_cover = sale_data.get("coverImage") or {}
        return {
            "eventId": event_id,
            "sellerId": sale_data.get("sellerId"),
            "suburb": sale_data.get("suburb"),
            "state": sale_data.get("state"),
            "title": sale_data.get("title"),
            "description": sale_data.get("description"),
            "moveOutDate": sale_data.get("moveOutDate"),
            "publishedAt": sale_data.get("publishedAt"),
            "bundles": bundles,
            "cover_image_gcs": sale_cover.get("gcs_path"),
        }

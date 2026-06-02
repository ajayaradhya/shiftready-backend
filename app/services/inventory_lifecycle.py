from datetime import datetime, timezone

from google.cloud import firestore

from app.domain.status import BundleSaleStatus, ItemSaleStatus, SaleStatus
from app.repos.bundle_repo import BundleRepo
from app.repos.item_repo import ItemRepo
from app.repos.sale_repo import SaleRepo
from app.repos.transaction_repo import TransactionRepo


class InventoryLifecycleService:
    def __init__(
        self,
        db: firestore.AsyncClient,
        items: ItemRepo,
        bundles: BundleRepo,
        sales: SaleRepo,
        transactions: TransactionRepo,
    ):
        self.db = db
        self.items = items
        self.bundles = bundles
        self.sales = sales
        self.transactions = transactions

    # ── Reserve ──────────────────────────────────────────────────────

    async def reserve_item(
        self,
        event_id: str,
        bundle_id: str,
        item_id: str,
        buyer_uid: str | None = None,
        conversation_id: str | None = None,
        offer_id: str | None = None,
        buyer_label: str | None = None,
        notes: str | None = None,
    ) -> None:
        item = await self.items.get_item_standalone(event_id, bundle_id, item_id)
        if not item:
            raise ValueError("Item not found")
        if item.get("sale_status") == ItemSaleStatus.SOLD:
            raise ValueError("Item is already sold")
        if item.get("sale_status") == ItemSaleStatus.WITHDRAWN:
            raise ValueError("Item is withdrawn")
        if item.get("sale_status") == ItemSaleStatus.RESERVED:
            raise ValueError("Item is already reserved")

        now = datetime.now(timezone.utc)
        await self.items.update_item_data(
            event_id,
            bundle_id,
            item_id,
            {
                "sale_status": ItemSaleStatus.RESERVED,
                "reserved_for_uid": buyer_uid,
                "reserved_via_conversation_id": conversation_id,
                "reserved_offer_id": offer_id,
                "reserved_at": now,
                "buyer_label": buyer_label,
            },
        )
        await self.transactions.add_transaction(
            event_id,
            {
                "type": "reserved",
                "granularity": "item",
                "itemId": item_id,
                "bundleId": bundle_id,
                "buyerUid": buyer_uid,
                "buyerLabel": buyer_label,
                "conversationId": conversation_id,
                "offerId": offer_id,
                "amount": item.get("actual_listing_price")
                or item.get("predicted_listing_price"),
                "actorUid": buyer_uid,
                "notes": notes,
            },
        )
        await self._rollup_bundle_and_sale(event_id, bundle_id)

    async def release_reservation(
        self,
        event_id: str,
        bundle_id: str,
        item_id: str,
        actor_uid: str,
    ) -> None:
        item = await self.items.get_item_standalone(event_id, bundle_id, item_id)
        if not item:
            raise ValueError("Item not found")
        if item.get("sale_status") != ItemSaleStatus.RESERVED:
            raise ValueError("Item is not reserved")

        await self.items.update_item_data(
            event_id,
            bundle_id,
            item_id,
            {
                "sale_status": ItemSaleStatus.AVAILABLE,
                "reserved_for_uid": None,
                "reserved_via_conversation_id": None,
                "reserved_offer_id": None,
                "reserved_at": None,
            },
        )
        await self.transactions.add_transaction(
            event_id,
            {
                "type": "released",
                "granularity": "item",
                "itemId": item_id,
                "bundleId": bundle_id,
                "buyerUid": item.get("reserved_for_uid"),
                "actorUid": actor_uid,
            },
        )
        await self._rollup_bundle_and_sale(event_id, bundle_id)

    # ── Mark sold ────────────────────────────────────────────────────

    async def mark_item_sold(
        self,
        event_id: str,
        bundle_id: str,
        item_id: str,
        actor_uid: str,
        final_price: float | None = None,
        buyer_uid: str | None = None,
        buyer_label: str | None = None,
        conversation_id: str | None = None,
        offer_id: str | None = None,
        payment_method: str | None = None,
        notes: str | None = None,
    ) -> None:
        item = await self.items.get_item_standalone(event_id, bundle_id, item_id)
        if not item:
            raise ValueError("Item not found")
        if item.get("sale_status") == ItemSaleStatus.SOLD:
            raise ValueError("Item already sold")
        if item.get("sale_status") == ItemSaleStatus.WITHDRAWN:
            raise ValueError("Item is withdrawn")

        # Prefill from reservation fields if not explicitly provided
        if item.get("sale_status") == ItemSaleStatus.RESERVED:
            buyer_uid = buyer_uid or item.get("reserved_for_uid")
            conversation_id = conversation_id or item.get(
                "reserved_via_conversation_id"
            )
            offer_id = offer_id or item.get("reserved_offer_id")

        effective_price = (
            final_price
            if final_price is not None
            else (
                item.get("actual_listing_price")
                or item.get("predicted_listing_price")
                or 0
            )
        )
        now = datetime.now(timezone.utc)

        await self.items.update_item_data(
            event_id,
            bundle_id,
            item_id,
            {
                "sale_status": ItemSaleStatus.SOLD,
                "sold_to_uid": buyer_uid,
                "sold_at": now,
                "final_price": effective_price,
                "sold_via_conversation_id": conversation_id,
                "sold_offer_id": offer_id,
                "sold_payment_method": payment_method,
                "sold_notes": notes,
                "sold_as": "item",
                "buyer_label": buyer_label,
                "reserved_for_uid": None,
                "reserved_via_conversation_id": None,
                "reserved_offer_id": None,
                "reserved_at": None,
            },
        )
        await self.transactions.add_transaction(
            event_id,
            {
                "type": "sold",
                "granularity": "item",
                "itemId": item_id,
                "bundleId": bundle_id,
                "buyerUid": buyer_uid,
                "buyerLabel": buyer_label,
                "sellerUid": actor_uid,
                "conversationId": conversation_id,
                "offerId": offer_id,
                "amount": effective_price,
                "paymentMethod": payment_method,
                "actorUid": actor_uid,
                "notes": notes,
            },
        )
        await self._rollup_bundle_and_sale(event_id, bundle_id)

    async def mark_bundle_sold(
        self,
        event_id: str,
        bundle_id: str,
        actor_uid: str,
        scope: str = "bundle_as_unit",
        final_price: float | None = None,
        buyer_uid: str | None = None,
        buyer_label: str | None = None,
        conversation_id: str | None = None,
        payment_method: str | None = None,
        notes: str | None = None,
    ) -> None:
        all_items = await self.items.list_items(event_id, bundle_id)
        sellable = [
            i
            for i in all_items
            if i.get("sale_status")
            not in (ItemSaleStatus.SOLD, ItemSaleStatus.WITHDRAWN)
        ]
        if not sellable:
            raise ValueError("No available items in bundle")

        now = datetime.now(timezone.utc)
        bundle_total = sum(
            float(
                i.get("actual_listing_price") or i.get("predicted_listing_price") or 0
            )
            for i in sellable
        )
        effective_price = final_price if final_price is not None else bundle_total

        for item in sellable:
            await self.items.update_item_data(
                event_id,
                bundle_id,
                item["id"],
                {
                    "sale_status": ItemSaleStatus.SOLD,
                    "sold_to_uid": buyer_uid,
                    "sold_at": now,
                    "final_price": None,
                    "sold_via_conversation_id": conversation_id,
                    "sold_payment_method": payment_method,
                    "sold_notes": notes,
                    "sold_as": "bundle",
                    "buyer_label": buyer_label,
                    "reserved_for_uid": None,
                    "reserved_via_conversation_id": None,
                    "reserved_offer_id": None,
                    "reserved_at": None,
                },
            )

        await self.transactions.add_transaction(
            event_id,
            {
                "type": "sold",
                "granularity": "bundle",
                "bundleId": bundle_id,
                "itemIds": [i["id"] for i in sellable],
                "buyerUid": buyer_uid,
                "buyerLabel": buyer_label,
                "sellerUid": actor_uid,
                "conversationId": conversation_id,
                "amount": effective_price,
                "paymentMethod": payment_method,
                "actorUid": actor_uid,
                "notes": notes,
                "scope": scope,
            },
        )
        await self._rollup_bundle_and_sale(event_id, bundle_id)

    async def mark_sale_sold(
        self,
        event_id: str,
        actor_uid: str,
        final_price: float | None = None,
        buyer_uid: str | None = None,
        buyer_label: str | None = None,
        payment_method: str | None = None,
        notes: str | None = None,
    ) -> None:
        all_bundles = await self.bundles.list_bundles(event_id)
        now = datetime.now(timezone.utc)

        for bundle in all_bundles:
            items = await self.items.list_items(event_id, bundle["id"])
            for item in items:
                if item.get("sale_status") not in (
                    ItemSaleStatus.SOLD,
                    ItemSaleStatus.WITHDRAWN,
                ):
                    await self.items.update_item_data(
                        event_id,
                        bundle["id"],
                        item["id"],
                        {
                            "sale_status": ItemSaleStatus.SOLD,
                            "sold_to_uid": buyer_uid,
                            "sold_at": now,
                            "final_price": None,
                            "sold_payment_method": payment_method,
                            "sold_notes": notes,
                            "sold_as": "sale",
                            "buyer_label": buyer_label,
                            "reserved_for_uid": None,
                            "reserved_via_conversation_id": None,
                            "reserved_offer_id": None,
                            "reserved_at": None,
                        },
                    )
            await self._rollup_bundle(event_id, bundle["id"])

        await self.transactions.add_transaction(
            event_id,
            {
                "type": "sold",
                "granularity": "sale",
                "buyerUid": buyer_uid,
                "buyerLabel": buyer_label,
                "sellerUid": actor_uid,
                "amount": final_price,
                "paymentMethod": payment_method,
                "actorUid": actor_uid,
                "notes": notes,
            },
        )
        await self._rollup_sale(event_id)

    # ── Withdraw ─────────────────────────────────────────────────────

    async def withdraw_item(
        self,
        event_id: str,
        bundle_id: str,
        item_id: str,
        actor_uid: str,
        notes: str | None = None,
    ) -> None:
        item = await self.items.get_item_standalone(event_id, bundle_id, item_id)
        if not item:
            raise ValueError("Item not found")
        if item.get("sale_status") == ItemSaleStatus.SOLD:
            raise ValueError("Cannot withdraw a sold item")

        await self.items.update_item_data(
            event_id,
            bundle_id,
            item_id,
            {
                "sale_status": ItemSaleStatus.WITHDRAWN,
                "reserved_for_uid": None,
                "reserved_via_conversation_id": None,
                "reserved_offer_id": None,
                "reserved_at": None,
            },
        )
        await self.transactions.add_transaction(
            event_id,
            {
                "type": "withdrawn",
                "granularity": "item",
                "itemId": item_id,
                "bundleId": bundle_id,
                "actorUid": actor_uid,
                "notes": notes,
            },
        )
        await self._rollup_bundle_and_sale(event_id, bundle_id)

    async def relist_item(
        self,
        event_id: str,
        bundle_id: str,
        item_id: str,
        actor_uid: str,
    ) -> None:
        item = await self.items.get_item_standalone(event_id, bundle_id, item_id)
        if not item:
            raise ValueError("Item not found")
        if item.get("sale_status") == ItemSaleStatus.SOLD:
            raise ValueError("Cannot relist a sold item")
        if item.get("sale_status") != ItemSaleStatus.WITHDRAWN:
            raise ValueError("Item is not withdrawn")

        await self.items.update_item_data(
            event_id,
            bundle_id,
            item_id,
            {
                "sale_status": ItemSaleStatus.AVAILABLE,
            },
        )
        await self._rollup_bundle_and_sale(event_id, bundle_id)

    async def withdraw_bundle(
        self,
        event_id: str,
        bundle_id: str,
        actor_uid: str,
        notes: str | None = None,
    ) -> None:
        items = await self.items.list_items(event_id, bundle_id)
        for item in items:
            if item.get("sale_status") not in (
                ItemSaleStatus.SOLD,
                ItemSaleStatus.WITHDRAWN,
            ):
                await self.items.update_item_data(
                    event_id,
                    bundle_id,
                    item["id"],
                    {
                        "sale_status": ItemSaleStatus.WITHDRAWN,
                        "reserved_for_uid": None,
                        "reserved_via_conversation_id": None,
                        "reserved_offer_id": None,
                        "reserved_at": None,
                    },
                )
        await self.transactions.add_transaction(
            event_id,
            {
                "type": "withdrawn",
                "granularity": "bundle",
                "bundleId": bundle_id,
                "actorUid": actor_uid,
                "notes": notes,
            },
        )
        await self._rollup_bundle_and_sale(event_id, bundle_id)

    async def withdraw_sale(
        self,
        event_id: str,
        actor_uid: str,
        notes: str | None = None,
    ) -> None:
        all_bundles = await self.bundles.list_bundles(event_id)
        for bundle in all_bundles:
            items = await self.items.list_items(event_id, bundle["id"])
            for item in items:
                if item.get("sale_status") not in (
                    ItemSaleStatus.SOLD,
                    ItemSaleStatus.WITHDRAWN,
                ):
                    await self.items.update_item_data(
                        event_id,
                        bundle["id"],
                        item["id"],
                        {
                            "sale_status": ItemSaleStatus.WITHDRAWN,
                            "reserved_for_uid": None,
                            "reserved_via_conversation_id": None,
                            "reserved_offer_id": None,
                            "reserved_at": None,
                        },
                    )
            await self._rollup_bundle(event_id, bundle["id"])

        await self.transactions.add_transaction(
            event_id,
            {
                "type": "withdrawn",
                "granularity": "sale",
                "actorUid": actor_uid,
                "notes": notes,
            },
        )
        await self._rollup_sale(event_id)

    # ── Rollup ───────────────────────────────────────────────────────

    async def _rollup_bundle(self, event_id: str, bundle_id: str) -> BundleSaleStatus:
        items = await self.items.list_items(event_id, bundle_id)
        if not items:
            return BundleSaleStatus.AVAILABLE

        statuses = [i.get("sale_status", ItemSaleStatus.AVAILABLE) for i in items]
        sold_count = sum(1 for s in statuses if s == ItemSaleStatus.SOLD)
        withdrawn_count = sum(1 for s in statuses if s == ItemSaleStatus.WITHDRAWN)
        reserved_count = sum(1 for s in statuses if s == ItemSaleStatus.RESERVED)
        available_count = sum(1 for s in statuses if s == ItemSaleStatus.AVAILABLE)
        total = len(statuses)

        if withdrawn_count == total:
            bundle_status = BundleSaleStatus.WITHDRAWN
        elif sold_count + withdrawn_count == total and sold_count > 0:
            bundle_status = BundleSaleStatus.SOLD
        elif sold_count > 0 and available_count > 0:
            bundle_status = BundleSaleStatus.PARTIALLY_SOLD
        elif reserved_count > 0 and available_count == 0 and sold_count == 0:
            bundle_status = BundleSaleStatus.RESERVED
        else:
            bundle_status = BundleSaleStatus.AVAILABLE

        await self.bundles.update_bundle_metadata(
            event_id,
            bundle_id,
            {
                "sale_status": bundle_status,
                "sold_count": sold_count,
                "total_count": total,
            },
        )
        return bundle_status

    async def _rollup_sale(self, event_id: str) -> SaleStatus:
        all_bundles = await self.bundles.list_bundles(event_id)
        if not all_bundles:
            return SaleStatus.LIVE

        bundle_statuses = [
            b.get("sale_status", BundleSaleStatus.AVAILABLE) for b in all_bundles
        ]
        withdrawn_count = sum(
            1 for s in bundle_statuses if s == BundleSaleStatus.WITHDRAWN
        )
        sold_count = sum(1 for s in bundle_statuses if s == BundleSaleStatus.SOLD)
        total = len(bundle_statuses)

        sold_items = sum(b.get("sold_count", 0) for b in all_bundles)
        total_items = sum(b.get("total_count", 0) for b in all_bundles)

        if sold_count + withdrawn_count == total and sold_count > 0:
            new_status = SaleStatus.SOLD
        elif sold_items > 0:
            new_status = SaleStatus.PARTIALLY_SOLD
        else:
            new_status = SaleStatus.LIVE

        sale = await self.sales.get_sale_event(event_id)
        current_status = (sale or {}).get("status")
        if current_status not in (
            SaleStatus.LIVE,
            SaleStatus.PARTIALLY_SOLD,
            SaleStatus.SOLD,
        ):
            return new_status

        if new_status != current_status:
            await self.sales.transition_sale_status(event_id, new_status)

        await self.sales.update_sale_metadata(
            event_id,
            {
                "sold_item_count": sold_items,
                "total_item_count": total_items,
            },
        )
        return new_status

    async def _rollup_bundle_and_sale(self, event_id: str, bundle_id: str) -> None:
        await self._rollup_bundle(event_id, bundle_id)
        await self._rollup_sale(event_id)

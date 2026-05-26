from google.cloud import firestore

from app.core.config import settings
from app.domain.status import SaleStatus
from app.repos.bundle_repo import BundleRepo
from app.repos.conversation_repo import ConversationRepo
from app.repos.item_repo import ItemRepo
from app.repos.marketplace_repo import MarketplaceRepo
from app.repos.sale_repo import SaleRepo
from app.repos.notification_repo import NotificationRepo
from app.repos.transaction_repo import TransactionRepo
from app.repos.user_repo import UserRepo
from app.services.inventory_lifecycle import InventoryLifecycleService


class FirestoreService:
    """
    Thin facade that wires the focused repo classes together and exposes the
    original public API.  Callers (routers, pipelines, auth) are unchanged.
    Individual repos are available as attributes for future direct access.
    """

    def __init__(self):
        self.db = firestore.AsyncClient(project=settings.gcp_project_id)
        self._wire(self.db)

    def _wire(self, db: firestore.AsyncClient) -> None:
        """(Re)initialise all repos against the given client. Called by tests to swap the event loop."""
        self.db = db
        self.sales = SaleRepo(db)
        self.bundles = BundleRepo(db)
        self.items = ItemRepo(db, self.bundles)
        self.users = UserRepo(db)
        self.marketplace = MarketplaceRepo(db)
        self.conversations = ConversationRepo(db)
        self.notifications = NotificationRepo(db)
        self.transactions = TransactionRepo(db)
        self.lifecycle = InventoryLifecycleService(
            db, self.items, self.bundles, self.sales, self.transactions
        )

    # --- user ---
    async def upsert_user(self, user_id: str, email: str, name: str | None = None) -> str:
        return await self.users.upsert_user(user_id, email, name)

    async def get_user(self, user_id: str) -> dict | None:
        return await self.users.get_user(user_id)

    async def get_user_by_username(self, username: str) -> dict | None:
        return await self.users.get_by_username(username)

    async def update_username(self, user_id: str, new_username: str) -> None:
        return await self.users.update_username(user_id, new_username)

    async def is_username_available(self, username: str, requesting_uid: str | None = None) -> bool:
        return await self.users.is_username_available(username, requesting_uid)

    async def update_phone(self, user_id: str, phone_e164: str, share_opt_in: bool) -> None:
        return await self.users.update_phone(user_id, phone_e164, share_opt_in)

    async def update_profile_fields(self, user_id: str, display_name: str | None, bio: str | None) -> None:
        return await self.users.update_profile_fields(user_id, display_name, bio)

    async def update_location(self, user_id: str, suburb: str | None, state: str | None) -> None:
        return await self.users.update_location(user_id, suburb, state)

    async def update_notif_prefs(self, user_id: str, prefs: dict) -> None:
        return await self.users.update_notif_prefs(user_id, prefs)

    async def update_seller_prefs(self, user_id: str, prefs: dict) -> None:
        return await self.users.update_seller_prefs(user_id, prefs)

    async def update_privacy_prefs(self, user_id: str, prefs: dict) -> None:
        return await self.users.update_privacy_prefs(user_id, prefs)

    async def share_phone(self, conv_id: str, uid: str) -> None:
        return await self.conversations.share_phone(conv_id, uid)

    async def get_phone_reveal(self, conv_id: str, requester_uid: str) -> str:
        return await self.conversations.get_phone_reveal(conv_id, requester_uid, self.users)

    async def save_sale(self, user_id: str, event_id: str, metadata: dict) -> None:
        return await self.users.save_sale(user_id, event_id, metadata)

    async def unsave_sale(self, user_id: str, event_id: str) -> None:
        return await self.users.unsave_sale(user_id, event_id)

    async def is_sale_saved(self, user_id: str, event_id: str) -> bool:
        return await self.users.is_sale_saved(user_id, event_id)

    async def save_item(self, user_id: str, item_id: str, metadata: dict) -> None:
        return await self.users.save_item(user_id, item_id, metadata)

    async def unsave_item(self, user_id: str, item_id: str) -> None:
        return await self.users.unsave_item(user_id, item_id)

    async def is_item_saved(self, user_id: str, item_id: str) -> bool:
        return await self.users.is_item_saved(user_id, item_id)

    async def get_saved(self, user_id: str) -> dict:
        return await self.users.get_saved(user_id)

    # --- sale ---
    async def create_sale_event(self, user_id: str) -> str:
        return await self.sales.create_sale_event(user_id)

    async def get_sale_event(self, event_id: str) -> dict | None:
        return await self.sales.get_sale_event(event_id)

    async def transition_sale_status(self, event_id: str, new_status: SaleStatus) -> bool:
        return await self.sales.transition_sale_status(event_id, new_status)

    async def update_sale_metadata(self, event_id: str, updates: dict) -> None:
        return await self.sales.update_sale_metadata(event_id, updates)

    async def list_all_sales(self, user_id: str) -> list[dict]:
        return await self.sales.list_all_sales(user_id)

    async def patch_sale(self, event_id: str, updates: dict, user_id: str) -> None:
        return await self.sales.patch_sale(event_id, updates, user_id)

    async def set_cover(self, event_id: str, cover_data: dict) -> None:
        return await self.sales.set_cover(event_id, cover_data)

    async def clear_cover(self, event_id: str) -> None:
        return await self.sales.clear_cover(event_id)

    async def get_full_event_summary(self, event_id: str) -> dict | None:
        return await self.sales.get_full_event_summary(event_id)

    async def archive_sale(self, event_id: str) -> None:
        return await self.sales.archive_sale(event_id)

    async def hard_delete_sale(self, event_id: str) -> list[str]:
        return await self.sales.hard_delete_sale(event_id)


    # --- bundle ---
    async def add_bundle(self, event_id: str, bundle_name: str, suggested_price: float = 0.0) -> str:
        return await self.bundles.add_bundle(event_id, bundle_name, suggested_price)

    async def update_bundle_metadata(self, event_id: str, bundle_id: str, updates: dict) -> None:
        return await self.bundles.update_bundle_metadata(event_id, bundle_id, updates)

    async def delete_bundle(self, event_id: str, bundle_id: str) -> bool:
        return await self.bundles.delete_bundle(event_id, bundle_id)

    async def recalculate_bundle_total(self, event_id: str, bundle_id: str) -> float:
        return await self.bundles.recalculate_bundle_total(event_id, bundle_id)

    # --- item ---
    async def add_item_to_bundle(self, event_id: str, bundle_id: str, item_data: dict) -> str:
        return await self.items.add_item_to_bundle(event_id, bundle_id, item_data)

    async def update_item_data(
        self, event_id: str, bundle_id: str, item_id: str, updates: dict
    ) -> None:
        return await self.items.update_item_data(event_id, bundle_id, item_id, updates)

    async def delete_item(self, event_id: str, bundle_id: str, item_id: str) -> bool:
        return await self.items.delete_item(event_id, bundle_id, item_id)

    async def get_item_standalone(
        self, event_id: str, bundle_id: str, item_id: str
    ) -> dict | None:
        return await self.items.get_item_standalone(event_id, bundle_id, item_id)

    async def move_item(
        self, event_id: str, from_bundle_id: str, item_id: str, to_bundle_id: str
    ) -> None:
        return await self.items.move_item(event_id, from_bundle_id, item_id, to_bundle_id)

    async def reorder_item_images(
        self, event_id: str, bundle_id: str, item_id: str, image_ids: list[str]
    ) -> None:
        return await self.items.reorder_images(event_id, bundle_id, item_id, image_ids)

    async def rename_bundle(self, event_id: str, bundle_id: str, name: str) -> None:
        return await self.bundles.update_bundle_metadata(event_id, bundle_id, {"name": name})

    # --- marketplace ---
    async def list_live_sales(self) -> list[dict]:
        return await self.marketplace.list_live_sales()

    async def get_active_inventory(
        self,
        suburb: str | None = None,
        query: str | None = None,
        category: str | None = None,
        condition: str | None = None,
        min_price: float | None = None,
        max_price: float | None = None,
        sort: str | None = None,
    ) -> list[dict]:
        return await self.marketplace.get_active_inventory(
            suburb=suburb, query=query, category=category,
            condition=condition, min_price=min_price, max_price=max_price, sort=sort,
        )

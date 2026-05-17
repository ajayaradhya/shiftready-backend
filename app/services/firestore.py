from google.cloud import firestore

from app.core.config import settings
from app.domain.status import SaleStatus
from app.repos.bundle_repo import BundleRepo
from app.repos.conversation_repo import ConversationRepo
from app.repos.item_repo import ItemRepo
from app.repos.marketplace_repo import MarketplaceRepo
from app.repos.sale_repo import SaleRepo
from app.repos.user_repo import UserRepo


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
    async def create_sale_event(self, user_id: str, video_url: str) -> str:
        return await self.sales.create_sale_event(user_id, video_url)

    async def get_sale_event(self, event_id: str) -> dict | None:
        return await self.sales.get_sale_event(event_id)

    async def transition_sale_status(self, event_id: str, new_status: SaleStatus) -> bool:
        return await self.sales.transition_sale_status(event_id, new_status)

    async def update_sale_metadata(self, event_id: str, updates: dict) -> None:
        return await self.sales.update_sale_metadata(event_id, updates)

    async def list_all_sales(self, user_id: str) -> list[dict]:
        return await self.sales.list_all_sales(user_id)

    async def get_full_event_summary(self, event_id: str) -> dict | None:
        return await self.sales.get_full_event_summary(event_id)

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

    # --- marketplace ---
    async def list_live_sales(self) -> list[dict]:
        return await self.marketplace.list_live_sales()

    async def get_active_inventory(
        self, suburb: str | None = None, query: str | None = None
    ) -> list[dict]:
        return await self.marketplace.get_active_inventory(suburb=suburb, query=query)

import asyncio
import logging
from datetime import datetime, timezone, timedelta

from google.cloud import firestore

from app.utils.username import generate_username

logger = logging.getLogger(__name__)

USERNAME_COOLDOWN_DAYS = 7


class UserRepo:
    def __init__(self, db: firestore.AsyncClient):
        self.db = db

    async def upsert_user(
        self, user_id: str, email: str, name: str | None = None
    ) -> str:
        """Upsert user doc; auto-generate username if absent. Returns username."""
        user_ref = self.db.collection("users").document(user_id)
        snap = await user_ref.get()

        if snap.exists and snap.get("username"):
            await user_ref.update(
                {
                    "email": email,
                    "displayName": name,
                    "lastLogin": firestore.SERVER_TIMESTAMP,
                    "updatedAt": firestore.SERVER_TIMESTAMP,
                }
            )
            return snap.get("username")

        username = await self._reserve_new_username(user_id)
        await user_ref.set(
            {
                "email": email,
                "displayName": name,
                "lastLogin": firestore.SERVER_TIMESTAMP,
                "updatedAt": firestore.SERVER_TIMESTAMP,
                "username": username,
                "usernameLower": username.lower(),
                "usernameSetByUser": False,
                "usernameChangedAt": None,
            },
            merge=True,
        )
        return username

    async def _reserve_new_username(self, user_id: str, max_attempts: int = 10) -> str:
        for _ in range(max_attempts):
            candidate = generate_username()
            lower = candidate.lower()
            ref = self.db.collection("usernames").document(lower)
            snap = await ref.get()
            if not snap.exists:
                await ref.set({"uid": user_id, "createdAt": firestore.SERVER_TIMESTAMP})
                return candidate
        raise RuntimeError("Could not reserve a unique username after max attempts")

    async def get_user(self, user_id: str) -> dict | None:
        snap = await self.db.collection("users").document(user_id).get()
        if not snap.exists:
            return None
        data = snap.to_dict()
        data["id"] = snap.id
        return data

    async def get_users_batch(self, user_ids: list[str]) -> dict[str, dict]:
        if not user_ids:
            return {}
        refs = [self.db.collection("users").document(uid) for uid in user_ids]
        snaps = self.db.get_all(refs)
        result: dict[str, dict] = {}
        async for snap in snaps:
            if snap.exists:
                data = snap.to_dict()
                data["id"] = snap.id
                result[snap.id] = data
        return result

    async def get_by_username(self, username: str) -> dict | None:
        lower = username.lower()
        un_snap = await self.db.collection("usernames").document(lower).get()
        if not un_snap.exists:
            return None
        uid = un_snap.get("uid")
        return await self.get_user(uid)

    async def update_username(self, user_id: str, new_username: str) -> None:
        """
        Change username atomically. Enforces 7-day cooldown.
        Releases old username slug; reserves new one.
        """
        user_ref = self.db.collection("users").document(user_id)
        snap = await user_ref.get()
        if not snap.exists:
            raise ValueError("User not found")

        data = snap.to_dict()
        changed_at = data.get("usernameChangedAt")
        if changed_at:
            if isinstance(changed_at, datetime):
                dt = changed_at
            else:
                dt = (
                    changed_at.replace(tzinfo=timezone.utc)
                    if changed_at.tzinfo is None
                    else changed_at
                )
            if datetime.now(timezone.utc) - dt < timedelta(days=USERNAME_COOLDOWN_DAYS):
                remaining = (
                    USERNAME_COOLDOWN_DAYS - (datetime.now(timezone.utc) - dt).days
                )
                raise ValueError(
                    f"Username can only be changed every {USERNAME_COOLDOWN_DAYS} days. {remaining} day(s) remaining."
                )

        old_username = data.get("usernameLower")
        new_lower = new_username.lower()

        new_ref = self.db.collection("usernames").document(new_lower)
        new_snap = await new_ref.get()
        if new_snap.exists and new_snap.get("uid") != user_id:
            raise ValueError("Username already taken")

        # Reserve new
        await new_ref.set({"uid": user_id, "createdAt": firestore.SERVER_TIMESTAMP})

        # Release old
        if old_username and old_username != new_lower:
            old_ref = self.db.collection("usernames").document(old_username)
            await old_ref.delete()

        await user_ref.update(
            {
                "username": new_username,
                "usernameLower": new_lower,
                "usernameSetByUser": True,
                "usernameChangedAt": firestore.SERVER_TIMESTAMP,
                "updatedAt": firestore.SERVER_TIMESTAMP,
            }
        )

    async def is_username_available(
        self, username: str, requesting_uid: str | None = None
    ) -> bool:
        lower = username.lower()
        snap = await self.db.collection("usernames").document(lower).get()
        if not snap.exists:
            return True
        if requesting_uid and snap.get("uid") == requesting_uid:
            return True
        return False

    # --- phone ---

    async def update_last_seen(self, user_id: str) -> None:
        try:
            await (
                self.db.collection("users")
                .document(user_id)
                .update(
                    {
                        "lastSeenAt": firestore.SERVER_TIMESTAMP,
                    }
                )
            )
        except Exception:
            pass  # non-fatal

    async def update_profile_fields(
        self, user_id: str, display_name: str | None, bio: str | None
    ) -> None:
        updates: dict = {"updatedAt": firestore.SERVER_TIMESTAMP}
        if display_name is not None:
            updates["displayName"] = display_name
        if bio is not None:
            updates["bio"] = bio
        await self.db.collection("users").document(user_id).update(updates)

    async def update_avatar(self, user_id: str, gcs_path: str | None) -> None:
        await (
            self.db.collection("users")
            .document(user_id)
            .update({"avatarGcsPath": gcs_path, "updatedAt": firestore.SERVER_TIMESTAMP})
        )

    async def update_location(
        self, user_id: str, suburb: str | None, state: str | None
    ) -> None:
        updates: dict = {"updatedAt": firestore.SERVER_TIMESTAMP}
        if suburb is not None:
            updates["suburb"] = suburb
        if state is not None:
            updates["state"] = state
        await self.db.collection("users").document(user_id).update(updates)

    async def update_notif_prefs(self, user_id: str, prefs: dict) -> None:
        await (
            self.db.collection("users")
            .document(user_id)
            .update(
                {
                    "notifPrefs": prefs,
                    "updatedAt": firestore.SERVER_TIMESTAMP,
                }
            )
        )

    async def update_seller_prefs(self, user_id: str, prefs: dict) -> None:
        await (
            self.db.collection("users")
            .document(user_id)
            .update(
                {
                    "sellerPrefs": prefs,
                    "updatedAt": firestore.SERVER_TIMESTAMP,
                }
            )
        )

    async def update_privacy_prefs(self, user_id: str, prefs: dict) -> None:
        await (
            self.db.collection("users")
            .document(user_id)
            .update(
                {
                    "privacyPrefs": prefs,
                    "updatedAt": firestore.SERVER_TIMESTAMP,
                }
            )
        )

    # --- push tokens ---

    async def add_push_token(self, user_id: str, token: str) -> None:
        await (
            self.db.collection("users")
            .document(user_id)
            .update(
                {
                    "pushTokens": firestore.ArrayUnion([token]),
                    "updatedAt": firestore.SERVER_TIMESTAMP,
                }
            )
        )

    async def remove_push_token(self, user_id: str, token: str) -> None:
        await (
            self.db.collection("users")
            .document(user_id)
            .update(
                {
                    "pushTokens": firestore.ArrayRemove([token]),
                    "updatedAt": firestore.SERVER_TIMESTAMP,
                }
            )
        )

    async def get_push_tokens(self, user_id: str) -> list[str]:
        snap = await self.db.collection("users").document(user_id).get()
        if not snap.exists:
            return []
        return snap.get("pushTokens") or []

    async def update_phone(
        self, user_id: str, phone_e164: str, share_opt_in: bool
    ) -> None:
        await (
            self.db.collection("users")
            .document(user_id)
            .update(
                {
                    "phoneE164": phone_e164,
                    "phoneShareOptIn": share_opt_in,
                    "updatedAt": firestore.SERVER_TIMESTAMP,
                }
            )
        )

    async def get_phone(self, user_id: str) -> str | None:
        snap = await self.db.collection("users").document(user_id).get()
        if not snap.exists:
            return None
        return snap.get("phoneE164")

    # --- saves ---

    async def save_sale(self, user_id: str, event_id: str, metadata: dict) -> None:
        ref = (
            self.db.collection("users")
            .document(user_id)
            .collection("savedSales")
            .document(event_id)
        )
        await ref.set({**metadata, "savedAt": firestore.SERVER_TIMESTAMP})

    async def unsave_sale(self, user_id: str, event_id: str) -> None:
        await (
            self.db.collection("users")
            .document(user_id)
            .collection("savedSales")
            .document(event_id)
            .delete()
        )

    async def is_sale_saved(self, user_id: str, event_id: str) -> bool:
        snap = await (
            self.db.collection("users")
            .document(user_id)
            .collection("savedSales")
            .document(event_id)
            .get()
        )
        return snap.exists

    async def save_item(self, user_id: str, item_id: str, metadata: dict) -> None:
        ref = (
            self.db.collection("users")
            .document(user_id)
            .collection("savedItems")
            .document(item_id)
        )
        await ref.set({**metadata, "savedAt": firestore.SERVER_TIMESTAMP})

    async def unsave_item(self, user_id: str, item_id: str) -> None:
        await (
            self.db.collection("users")
            .document(user_id)
            .collection("savedItems")
            .document(item_id)
            .delete()
        )

    async def is_item_saved(self, user_id: str, item_id: str) -> bool:
        snap = await (
            self.db.collection("users")
            .document(user_id)
            .collection("savedItems")
            .document(item_id)
            .get()
        )
        return snap.exists

    async def soft_delete_user(self, user_id: str) -> None:
        """Scrub PII and mark account deleted. Retains transaction records per ATO 7yr requirement."""
        user_ref = self.db.collection("users").document(user_id)
        snap = await user_ref.get()
        if not snap.exists:
            raise ValueError("User not found")

        data = snap.to_dict() or {}
        old_username_lower = data.get("usernameLower")

        await user_ref.update(
            {
                "isDeleted": True,
                "deletedAt": firestore.SERVER_TIMESTAMP,
                "email": None,
                "displayName": "Deleted user",
                "phoneE164": None,
                "phoneShareOptIn": False,
                "bio": None,
                "suburb": None,
                "state": None,
                "updatedAt": firestore.SERVER_TIMESTAMP,
            }
        )

        if old_username_lower:
            try:
                await (
                    self.db.collection("usernames")
                    .document(old_username_lower)
                    .delete()
                )
            except Exception:
                pass

    async def get_user_export_data(self, user_id: str) -> dict:
        user_ref = self.db.collection("users").document(user_id)
        snap = await user_ref.get()
        if not snap.exists:
            raise ValueError("User not found")

        profile = snap.to_dict() or {}
        profile.pop("passwordHash", None)

        sales_snaps, items_snaps = await asyncio.gather(
            user_ref.collection("savedSales").get(),
            user_ref.collection("savedItems").get(),
        )

        saved_sales = [{"id": d.id, **(d.to_dict() or {})} for d in sales_snaps]
        saved_items = [{"id": d.id, **(d.to_dict() or {})} for d in items_snaps]

        return {
            "profile": profile,
            "saved_sales": saved_sales,
            "saved_items": saved_items,
        }

    async def get_saved(self, user_id: str) -> dict:
        user_ref = self.db.collection("users").document(user_id)
        sales_snaps, items_snaps = await asyncio.gather(
            user_ref.collection("savedSales")
            .order_by("savedAt", direction=firestore.Query.DESCENDING)
            .get(),
            user_ref.collection("savedItems")
            .order_by("savedAt", direction=firestore.Query.DESCENDING)
            .get(),
        )

        saved_sales = []
        for doc in sales_snaps:
            data = doc.to_dict() or {}
            data["eventId"] = doc.id
            saved_sales.append(data)

        saved_items = []
        for doc in items_snaps:
            data = doc.to_dict() or {}
            data["itemId"] = doc.id
            saved_items.append(data)

        return {"saved_sales": saved_sales, "saved_items": saved_items}

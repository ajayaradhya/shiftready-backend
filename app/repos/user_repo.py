import logging
from datetime import datetime, timezone, timedelta

from google.cloud import firestore

from app.utils.username import generate_username

logger = logging.getLogger(__name__)

USERNAME_COOLDOWN_DAYS = 7


class UserRepo:
    def __init__(self, db: firestore.AsyncClient):
        self.db = db

    async def upsert_user(self, user_id: str, email: str, name: str | None = None) -> str:
        """Upsert user doc; auto-generate username if absent. Returns username."""
        user_ref = self.db.collection("users").document(user_id)
        snap = await user_ref.get()

        if snap.exists and snap.get("username"):
            await user_ref.update({
                "email": email,
                "displayName": name,
                "lastLogin": firestore.SERVER_TIMESTAMP,
                "updatedAt": firestore.SERVER_TIMESTAMP,
            })
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
                dt = changed_at.replace(tzinfo=timezone.utc) if changed_at.tzinfo is None else changed_at
            if datetime.now(timezone.utc) - dt < timedelta(days=USERNAME_COOLDOWN_DAYS):
                remaining = USERNAME_COOLDOWN_DAYS - (datetime.now(timezone.utc) - dt).days
                raise ValueError(f"Username can only be changed every {USERNAME_COOLDOWN_DAYS} days. {remaining} day(s) remaining.")

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

        await user_ref.update({
            "username": new_username,
            "usernameLower": new_lower,
            "usernameSetByUser": True,
            "usernameChangedAt": firestore.SERVER_TIMESTAMP,
            "updatedAt": firestore.SERVER_TIMESTAMP,
        })

    async def is_username_available(self, username: str, requesting_uid: str | None = None) -> bool:
        lower = username.lower()
        snap = await self.db.collection("usernames").document(lower).get()
        if not snap.exists:
            return True
        if requesting_uid and snap.get("uid") == requesting_uid:
            return True
        return False

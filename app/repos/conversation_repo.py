import logging
from datetime import datetime, timezone

from google.cloud import firestore

from app.utils.username import make_conversation_id

logger = logging.getLogger(__name__)

MAX_MESSAGE_LENGTH = 2000
RATE_LIMIT_PER_MIN = 30
RATE_LIMIT_PER_DAY = 500


class ConversationRepo:
    def __init__(self, db: firestore.AsyncClient):
        self.db = db

    # ── conversation ──────────────────────────────────────────────────────────

    def _conv_ref(self, conv_id: str) -> firestore.AsyncDocumentReference:
        return self.db.collection("conversations").document(conv_id)

    async def get_or_create_conversation(
        self,
        uid_a: str,
        uid_b: str,
    ) -> tuple[str, dict]:
        conv_id = make_conversation_id(uid_a, uid_b)
        ref = self._conv_ref(conv_id)
        snap = await ref.get()
        if snap.exists:
            return conv_id, snap.to_dict()

        participants = sorted([uid_a, uid_b])
        data = {
            "participants": participants,
            "participantsMap": {
                participants[0]: {"lastReadAt": None, "unreadCount": 0},
                participants[1]: {"lastReadAt": None, "unreadCount": 0},
            },
            "lastMessage": None,
            "lastMessageAt": None,
            "createdAt": firestore.SERVER_TIMESTAMP,
            "updatedAt": firestore.SERVER_TIMESTAMP,
            "status": "active",
            "blockedBy": None,
        }
        await ref.set(data)
        return conv_id, data

    async def get_conversation(self, conv_id: str) -> dict | None:
        snap = await self._conv_ref(conv_id).get()
        if not snap.exists:
            return None
        return {"id": snap.id, **snap.to_dict()}

    async def list_user_conversations(self, uid: str) -> list[dict]:
        query = (
            self.db.collection("conversations")
            .where("participants", "array_contains", uid)
            .order_by("updatedAt", direction=firestore.Query.DESCENDING)
            .limit(50)
        )
        snaps = query.stream()
        result = []
        async for snap in snaps:
            result.append({"id": snap.id, **snap.to_dict()})
        return result

    async def block_conversation(self, conv_id: str, blocker_uid: str) -> None:
        await self._conv_ref(conv_id).update({
            "status": "blocked",
            "blockedBy": blocker_uid,
            "updatedAt": firestore.SERVER_TIMESTAMP,
        })

    async def unblock_conversation(self, conv_id: str, uid: str) -> None:
        conv = await self.get_conversation(conv_id)
        if not conv:
            return
        if conv.get("blockedBy") != uid:
            raise ValueError("Only the blocker can unblock")
        await self._conv_ref(conv_id).update({
            "status": "active",
            "blockedBy": None,
            "updatedAt": firestore.SERVER_TIMESTAMP,
        })

    async def set_pin(
        self,
        conv_id: str,
        pin_ref: dict,
        snapshot: dict,
        actor_uid: str,
        actor_username: str | None = None,
    ) -> dict:
        await self._conv_ref(conv_id).update({
            "pin": pin_ref,
            "pinSnapshot": snapshot,
            "updatedAt": firestore.SERVER_TIMESTAMP,
        })
        msg_ref = self._msg_col(conv_id).document()
        now = datetime.now(timezone.utc)
        target_name = snapshot.get("name") or pin_ref.get("kind", "item")
        msg_data = {
            "senderId": actor_uid,
            "text": f"{actor_username or actor_uid} pinned {target_name}",
            "createdAt": now,
            "type": "system",
            "subtype": "pin_changed",
            "pinRef": pin_ref,
            "pinSnapshot": snapshot,
            "deletedAt": None,
        }
        await msg_ref.set(msg_data)
        return {"id": msg_ref.id, **msg_data}

    async def clear_pin(
        self,
        conv_id: str,
        actor_uid: str,
        actor_username: str | None = None,
    ) -> dict:
        await self._conv_ref(conv_id).update({
            "pin": None,
            "pinSnapshot": None,
            "updatedAt": firestore.SERVER_TIMESTAMP,
        })
        msg_ref = self._msg_col(conv_id).document()
        now = datetime.now(timezone.utc)
        msg_data = {
            "senderId": actor_uid,
            "text": f"{actor_username or actor_uid} removed the pinned item",
            "createdAt": now,
            "type": "system",
            "subtype": "pin_cleared",
            "deletedAt": None,
        }
        await msg_ref.set(msg_data)
        return {"id": msg_ref.id, **msg_data}

    async def mark_read(self, conv_id: str, uid: str) -> None:
        await self._conv_ref(conv_id).update({
            f"participantsMap.{uid}.lastReadAt": firestore.SERVER_TIMESTAMP,
            f"participantsMap.{uid}.unreadCount": 0,
            "updatedAt": firestore.SERVER_TIMESTAMP,
        })

    # ── messages ──────────────────────────────────────────────────────────────

    def _msg_col(self, conv_id: str):
        return self._conv_ref(conv_id).collection("messages")

    async def send_message(
        self,
        conv_id: str,
        sender_uid: str,
        text: str,
        context: dict | None = None,
    ) -> dict:
        conv = await self.get_conversation(conv_id)
        if not conv:
            raise ValueError("Conversation not found")
        if sender_uid not in conv.get("participants", []):
            raise PermissionError("Not a participant")
        if conv.get("status") == "blocked":
            blocked_by = conv.get("blockedBy")
            if blocked_by != sender_uid:
                raise PermissionError("Message blocked")

        if len(text) > MAX_MESSAGE_LENGTH:
            raise ValueError(f"Message exceeds {MAX_MESSAGE_LENGTH} characters")

        await self._check_rate_limit(conv_id, sender_uid)

        msg_ref = self._msg_col(conv_id).document()
        now = datetime.now(timezone.utc)
        msg_data = {
            "senderId": sender_uid,
            "text": text,
            "createdAt": now,
            "type": "text",
            "deletedAt": None,
        }
        if context:
            msg_data["context"] = context
        await msg_ref.set(msg_data)

        # Increment unread for other participant
        other = [p for p in conv["participants"] if p != sender_uid]
        if other:
            other_uid = other[0]
            await self._conv_ref(conv_id).update({
                "lastMessage": text[:100],
                "lastMessageAt": firestore.SERVER_TIMESTAMP,
                "updatedAt": firestore.SERVER_TIMESTAMP,
                f"participantsMap.{other_uid}.unreadCount": firestore.Increment(1),
            })

        return {"id": msg_ref.id, **msg_data}

    async def list_messages(
        self,
        conv_id: str,
        before: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        query = (
            self._msg_col(conv_id)
            .order_by("createdAt", direction=firestore.Query.DESCENDING)
            .limit(limit)
        )
        if before:
            cursor_snap = await self._msg_col(conv_id).document(before).get()
            if cursor_snap.exists:
                query = query.start_after(cursor_snap)

        result = []
        async for snap in query.stream():
            data = snap.to_dict()
            if not data.get("deletedAt"):
                result.append({"id": snap.id, **data})
        return list(reversed(result))

    async def get_total_unread(self, uid: str) -> int:
        convs = await self.list_user_conversations(uid)
        total = 0
        for c in convs:
            pm = c.get("participantsMap", {})
            total += pm.get(uid, {}).get("unreadCount", 0)
        return total

    # ── rate limiting ─────────────────────────────────────────────────────────

    async def _check_rate_limit(self, conv_id: str, sender_uid: str) -> None:
        from datetime import timedelta
        now = datetime.now(timezone.utc)
        one_min_ago = now - timedelta(minutes=1)
        one_day_ago = now - timedelta(days=1)

        # Per-minute: count messages by sender in this conversation in last 60s
        min_query = (
            self._msg_col(conv_id)
            .where("senderId", "==", sender_uid)
            .where("createdAt", ">=", one_min_ago)
        )
        min_count = 0
        async for _ in min_query.stream():
            min_count += 1
            if min_count >= RATE_LIMIT_PER_MIN:
                raise PermissionError("Rate limit: 30 messages per minute")

        # Per-day: check across all conversations for this user
        day_query = (
            self.db.collection_group("messages")
            .where("senderId", "==", sender_uid)
            .where("createdAt", ">=", one_day_ago)
            .limit(RATE_LIMIT_PER_DAY + 1)
        )
        day_count = 0
        async for _ in day_query.stream():
            day_count += 1
        if day_count >= RATE_LIMIT_PER_DAY:
            raise PermissionError("Rate limit: 500 messages per day")

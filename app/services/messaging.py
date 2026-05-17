import logging
from typing import Any

logger = logging.getLogger(__name__)


class MessagingService:
    """Thin orchestration layer over ConversationRepo + notifier."""

    def __init__(self, conversation_repo, notifier):
        self.convs = conversation_repo
        self.notifier = notifier

    async def start_conversation(self, uid_a: str, uid_b: str) -> tuple[str, dict]:
        return await self.convs.get_or_create_conversation(uid_a, uid_b)

    async def send(
        self,
        conv_id: str,
        sender_uid: str,
        text: str,
        context: dict | None = None,
    ) -> dict:
        msg = await self.convs.send_message(conv_id, sender_uid, text, context)

        conv = await self.convs.get_conversation(conv_id)
        if conv:
            other_uid = next(
                (p for p in conv.get("participants", []) if p != sender_uid), None
            )
            if other_uid:
                await self.notifier.notify_user(other_uid, {
                    "type": "message.new",
                    "conversationId": conv_id,
                    "message": _serialize_msg(msg),
                })
        return _serialize_msg(msg)

    async def list_conversations(self, uid: str, user_repo) -> list[dict]:
        convs = await self.convs.list_user_conversations(uid)
        result = []
        for c in convs:
            other_uid = next((p for p in c.get("participants", []) if p != uid), None)
            other_username = None
            if other_uid:
                other_user = await user_repo.get_user(other_uid)
                other_username = other_user.get("username") if other_user else None
            pm = c.get("participantsMap", {})
            result.append({
                "id": c["id"],
                "otherUserId": other_uid,
                "otherUsername": other_username,
                "lastMessage": c.get("lastMessage"),
                "lastMessageAt": _ts(c.get("lastMessageAt")),
                "unreadCount": pm.get(uid, {}).get("unreadCount", 0),
                "status": c.get("status", "active"),
                "updatedAt": _ts(c.get("updatedAt")),
            })
        return result

    async def list_messages(
        self, conv_id: str, uid: str, before: str | None = None, limit: int = 50
    ) -> list[dict]:
        conv = await self.convs.get_conversation(conv_id)
        if not conv or uid not in conv.get("participants", []):
            raise PermissionError("Not a participant")
        msgs = await self.convs.list_messages(conv_id, before=before, limit=limit)
        return [_serialize_msg(m) for m in msgs]

    async def mark_read(self, conv_id: str, uid: str) -> None:
        await self.convs.mark_read(conv_id, uid)

    async def block(self, conv_id: str, uid: str) -> None:
        conv = await self.convs.get_conversation(conv_id)
        if not conv or uid not in conv.get("participants", []):
            raise PermissionError("Not a participant")
        await self.convs.block_conversation(conv_id, uid)

    async def unblock(self, conv_id: str, uid: str) -> None:
        await self.convs.unblock_conversation(conv_id, uid)

    async def get_unread_count(self, uid: str) -> int:
        return await self.convs.get_total_unread(uid)


def _ts(val: Any) -> str | None:
    if val is None:
        return None
    try:
        if hasattr(val, "isoformat"):
            return val.isoformat()
        return str(val)
    except Exception:
        return None


def _serialize_msg(m: dict) -> dict:
    return {
        "id": m.get("id"),
        "senderId": m.get("senderId"),
        "text": m.get("text"),
        "createdAt": _ts(m.get("createdAt")),
        "type": m.get("type", "text"),
        "context": m.get("context"),
    }

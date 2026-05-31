import logging
from typing import Any

logger = logging.getLogger(__name__)


class MessagingService:
    """Thin orchestration layer over ConversationRepo + notifier."""

    def __init__(self, conversation_repo, notifier, notification_repo=None):
        self.convs = conversation_repo
        self.notifier = notifier
        self.notifs = notification_repo

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
                await self.notifier.notify_user(
                    other_uid,
                    {
                        "type": "message.new",
                        "conversationId": conv_id,
                        "message": _serialize_msg(msg),
                    },
                )
                if self.notifs:
                    preview = text[:80] + "…" if len(text) > 80 else text
                    notif_id = await self.notifs.create(
                        uid=other_uid,
                        type="message.new",
                        title="New message",
                        body=preview,
                        link="/messages",
                    )
                    await self.notifier.notify_user(
                        other_uid,
                        {
                            "type": "notification.new",
                            "notificationId": notif_id,
                        },
                    )
        return _serialize_msg(msg)

    async def list_conversations(self, uid: str, user_repo) -> list[dict]:
        convs = await self.convs.list_user_conversations(uid)

        other_uids = list({
            next((p for p in c.get("participants", []) if p != uid), None)
            for c in convs
        } - {None})
        users_map = await user_repo.get_users_batch(other_uids)

        result = []
        for c in convs:
            other_uid = next((p for p in c.get("participants", []) if p != uid), None)
            other_username = None
            other_last_seen_at = None
            other_verified = False
            if other_uid:
                other_user = users_map.get(other_uid)
                if other_user:
                    other_username = other_user.get("username")
                    other_last_seen_at = _ts(other_user.get("lastSeenAt"))
                    other_verified = bool(other_user.get("verified", False))
            pm = c.get("participantsMap", {})
            shared_by = c.get("phoneSharedBy", {})
            deal_agreed = c.get("dealStatus") == "agreed"
            result.append(
                {
                    "id": c["id"],
                    "otherUserId": other_uid,
                    "otherUsername": other_username,
                    "lastMessage": c.get("lastMessage"),
                    "lastMessageAt": _ts(c.get("lastMessageAt")),
                    "unreadCount": pm.get(uid, {}).get("unreadCount", 0),
                    "status": c.get("status", "active"),
                    "updatedAt": _ts(c.get("updatedAt")),
                    "pin": c.get("pin"),
                    "pinSnapshot": c.get("pinSnapshot"),
                    "activeOfferId": c.get("activeOfferId"),
                    "dealStatus": c.get("dealStatus", "none"),
                    "phoneSharedByMe": bool(shared_by.get(uid)),
                    "phoneRevealAvailable": deal_agreed
                    and bool(shared_by.get(other_uid)),
                    "otherLastSeenAt": other_last_seen_at,
                    "otherVerified": other_verified,
                }
            )
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

    async def set_pin(
        self,
        conv_id: str,
        uid: str,
        pin_ref: dict,
        snapshot: dict,
        username: str | None = None,
    ) -> dict:
        conv = await self.convs.get_conversation(conv_id)
        if not conv or uid not in conv.get("participants", []):
            raise PermissionError("Not a participant")
        msg = await self.convs.set_pin(conv_id, pin_ref, snapshot, uid, username)
        for participant_uid in conv.get("participants", []):
            await self.notifier.notify_user(
                participant_uid,
                {
                    "type": "conversation.pin_changed",
                    "conversationId": conv_id,
                    "pinRef": pin_ref,
                    "pinSnapshot": snapshot,
                    "message": _serialize_msg(msg),
                },
            )
        return _serialize_msg(msg)

    async def clear_pin(
        self,
        conv_id: str,
        uid: str,
        username: str | None = None,
    ) -> dict:
        conv = await self.convs.get_conversation(conv_id)
        if not conv or uid not in conv.get("participants", []):
            raise PermissionError("Not a participant")
        msg = await self.convs.clear_pin(conv_id, uid, username)
        for participant_uid in conv.get("participants", []):
            await self.notifier.notify_user(
                participant_uid,
                {
                    "type": "conversation.pin_changed",
                    "conversationId": conv_id,
                    "pinRef": None,
                    "pinSnapshot": None,
                    "message": _serialize_msg(msg),
                },
            )
        return _serialize_msg(msg)

    async def get_unread_count(self, uid: str) -> int:
        return await self.convs.get_total_unread(uid)

    # ── offers ────────────────────────────────────────────────────────────────

    async def send_offer(
        self,
        conv_id: str,
        sender_uid: str,
        amount: float,
        parent_offer_id: str | None = None,
        list_price: float | None = None,
    ) -> dict:
        conv = await self.convs.get_conversation(conv_id)
        if not conv:
            raise ValueError("Conversation not found")
        pin = conv.get("pin")
        offer, msg = await self.convs.send_offer(
            conv_id,
            sender_uid,
            amount,
            parent_offer_id=parent_offer_id,
            list_price=list_price,
            pin_target=pin,
        )
        other_uid = next(
            (p for p in conv.get("participants", []) if p != sender_uid), None
        )
        if other_uid:
            await self.notifier.notify_user(
                other_uid,
                {
                    "type": "message.new",
                    "conversationId": conv_id,
                    "message": _serialize_msg(msg),
                },
            )
            if self.notifs:
                notif_id = await self.notifs.create(
                    uid=other_uid,
                    type="offer.new",
                    title="New offer received",
                    body=f"${amount:.0f} offer",
                    link="/messages",
                )
                await self.notifier.notify_user(
                    other_uid,
                    {
                        "type": "notification.new",
                        "notificationId": notif_id,
                    },
                )
        return _serialize_msg(msg)

    async def accept_offer(
        self,
        conv_id: str,
        offer_id: str,
        acceptor_uid: str,
    ) -> dict:
        conv = await self.convs.get_conversation(conv_id)
        if not conv:
            raise ValueError("Conversation not found")
        _offer, accepted_msg, deal_msg = await self.convs.accept_offer(
            conv_id, offer_id, acceptor_uid
        )
        amount = _offer.get("amount", 0)
        for uid in conv.get("participants", []):
            await self.notifier.notify_user(
                uid,
                {
                    "type": "conversation.deal_agreed",
                    "conversationId": conv_id,
                    "amount": amount,
                    "message": _serialize_msg(accepted_msg),
                    "dealMessage": _serialize_msg(deal_msg),
                },
            )
            if self.notifs and uid != acceptor_uid:
                notif_id = await self.notifs.create(
                    uid=uid,
                    type="offer.accepted",
                    title="Offer accepted 🎉",
                    body=f"Your ${amount:.0f} offer was accepted",
                    link="/messages",
                )
                await self.notifier.notify_user(
                    uid,
                    {
                        "type": "notification.new",
                        "notificationId": notif_id,
                    },
                )
        return _serialize_msg(accepted_msg)

    async def counter_offer(
        self,
        conv_id: str,
        offer_id: str,
        counter_uid: str,
        new_amount: float,
    ) -> dict:
        conv = await self.convs.get_conversation(conv_id)
        if not conv:
            raise ValueError("Conversation not found")
        _offer, msg = await self.convs.counter_offer(
            conv_id, offer_id, counter_uid, new_amount
        )
        other_uid = next(
            (p for p in conv.get("participants", []) if p != counter_uid), None
        )
        if other_uid:
            await self.notifier.notify_user(
                other_uid,
                {
                    "type": "message.new",
                    "conversationId": conv_id,
                    "message": _serialize_msg(msg),
                },
            )
            if self.notifs:
                notif_id = await self.notifs.create(
                    uid=other_uid,
                    type="offer.countered",
                    title="Counter-offer received",
                    body=f"${new_amount:.0f} counter-offer",
                    link="/messages",
                )
                await self.notifier.notify_user(
                    other_uid,
                    {
                        "type": "notification.new",
                        "notificationId": notif_id,
                    },
                )
        for uid in conv.get("participants", []):
            await self.notifier.notify_user(
                uid,
                {
                    "type": "offer.updated",
                    "conversationId": conv_id,
                    "offerId": offer_id,
                    "status": "countered",
                },
            )
        return _serialize_msg(msg)

    async def withdraw_offer(
        self,
        conv_id: str,
        offer_id: str,
        withdrawer_uid: str,
    ) -> dict:
        msg = await self.convs.withdraw_offer(conv_id, offer_id, withdrawer_uid)
        conv = await self.convs.get_conversation(conv_id)
        if conv:
            for uid in conv.get("participants", []):
                await self.notifier.notify_user(
                    uid,
                    {
                        "type": "offer.updated",
                        "conversationId": conv_id,
                        "offerId": offer_id,
                        "status": "withdrawn",
                        "message": _serialize_msg(msg),
                    },
                )
        return _serialize_msg(msg)


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
        "subtype": m.get("subtype"),
        "context": m.get("context"),
        "pinSnapshot": m.get("pinSnapshot"),
        "offerPayload": m.get("offerPayload"),
    }

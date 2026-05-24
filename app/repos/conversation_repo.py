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

    # ── offers ────────────────────────────────────────────────────────────────

    def _offer_col(self, conv_id: str):
        return self._conv_ref(conv_id).collection("offers")

    async def get_offer(self, conv_id: str, offer_id: str) -> dict | None:
        snap = await self._offer_col(conv_id).document(offer_id).get()
        if not snap.exists:
            return None
        return {"id": snap.id, **snap.to_dict()}

    async def send_offer(
        self,
        conv_id: str,
        sender_uid: str,
        amount: float,
        parent_offer_id: str | None = None,
        list_price: float | None = None,
        pin_target: dict | None = None,
    ) -> tuple[dict, dict]:
        """Create offer doc + offer message. Returns (offer, message)."""
        conv = await self.get_conversation(conv_id)
        if not conv:
            raise ValueError("Conversation not found")
        if sender_uid not in conv.get("participants", []):
            raise PermissionError("Not a participant")
        if conv.get("status") == "blocked":
            if conv.get("blockedBy") != sender_uid:
                raise PermissionError("Message blocked")

        now = datetime.now(timezone.utc)
        offer_ref = self._offer_col(conv_id).document()
        offer_data = {
            "senderUid": sender_uid,
            "amount": amount,
            "currency": "AUD",
            "listPrice": list_price,
            "parentOfferId": parent_offer_id,
            "status": "pending",
            "pinTarget": pin_target,
            "createdAt": now,
            "updatedAt": now,
        }
        await offer_ref.set(offer_data)

        # If counter, mark parent countered
        if parent_offer_id:
            await self._offer_col(conv_id).document(parent_offer_id).update({
                "status": "countered",
                "updatedAt": firestore.SERVER_TIMESTAMP,
            })

        saves_str = ""
        if list_price and list_price > amount:
            saves_str = f" (saves ${list_price - amount:.0f})"

        msg_ref = self._msg_col(conv_id).document()
        msg_data = {
            "senderId": sender_uid,
            "text": f"Offered ${amount:.0f}{saves_str}",
            "createdAt": now,
            "type": "offer",
            "deletedAt": None,
            "offerPayload": {
                "offerId": offer_ref.id,
                "amount": amount,
                "currency": "AUD",
                "listPrice": list_price,
                "parentOfferId": parent_offer_id,
                "status": "pending",
                "pinTarget": pin_target,
            },
        }
        await msg_ref.set(msg_data)

        other = [p for p in conv["participants"] if p != sender_uid]
        update: dict = {
            "activeOfferId": offer_ref.id,
            "dealStatus": "negotiating",
            "lastMessage": msg_data["text"][:100],
            "lastMessageAt": firestore.SERVER_TIMESTAMP,
            "updatedAt": firestore.SERVER_TIMESTAMP,
        }
        if other:
            update[f"participantsMap.{other[0]}.unreadCount"] = firestore.Increment(1)
        await self._conv_ref(conv_id).update(update)

        offer_out = {"id": offer_ref.id, **offer_data}
        msg_out = {"id": msg_ref.id, **msg_data}
        return offer_out, msg_out

    async def accept_offer(
        self,
        conv_id: str,
        offer_id: str,
        acceptor_uid: str,
    ) -> tuple[dict, dict, dict]:
        """Accept offer. Returns (offer, accepted_msg, deal_agreed_msg)."""
        conv = await self.get_conversation(conv_id)
        if not conv:
            raise ValueError("Conversation not found")
        if acceptor_uid not in conv.get("participants", []):
            raise PermissionError("Not a participant")

        offer = await self.get_offer(conv_id, offer_id)
        if not offer:
            raise ValueError("Offer not found")
        if offer["status"] != "pending":
            raise ValueError(f"Offer is {offer['status']}, cannot accept")
        if offer["senderUid"] == acceptor_uid:
            raise PermissionError("Cannot accept your own offer")

        now = datetime.now(timezone.utc)
        await self._offer_col(conv_id).document(offer_id).update({
            "status": "accepted",
            "updatedAt": firestore.SERVER_TIMESTAMP,
        })

        accepted_msg_ref = self._msg_col(conv_id).document()
        accepted_payload = {
            **{k: v for k, v in offer.get("offerPayload", {}).items()
               if k != "status"},
            "offerId": offer_id,
            "amount": offer["amount"],
            "currency": offer.get("currency", "AUD"),
            "listPrice": offer.get("listPrice"),
            "parentOfferId": offer.get("parentOfferId"),
            "status": "accepted",
            "pinTarget": offer.get("pinTarget"),
        }
        accepted_msg_data = {
            "senderId": acceptor_uid,
            "text": f"Accepted offer of ${offer['amount']:.0f}",
            "createdAt": now,
            "type": "offer_accepted",
            "deletedAt": None,
            "offerPayload": accepted_payload,
        }
        await accepted_msg_ref.set(accepted_msg_data)

        deal_msg_ref = self._msg_col(conv_id).document()
        deal_msg_data = {
            "senderId": acceptor_uid,
            "text": f"Deal agreed at ${offer['amount']:.0f}",
            "createdAt": now,
            "type": "system",
            "subtype": "deal_agreed",
            "deletedAt": None,
        }
        await deal_msg_ref.set(deal_msg_data)

        other = [p for p in conv["participants"] if p != acceptor_uid]
        update: dict = {
            "activeOfferId": None,
            "dealStatus": "agreed",
            "lastMessage": accepted_msg_data["text"][:100],
            "lastMessageAt": firestore.SERVER_TIMESTAMP,
            "updatedAt": firestore.SERVER_TIMESTAMP,
        }
        if other:
            update[f"participantsMap.{other[0]}.unreadCount"] = firestore.Increment(1)
        await self._conv_ref(conv_id).update(update)

        return (
            {"id": offer_id, **offer, "status": "accepted"},
            {"id": accepted_msg_ref.id, **accepted_msg_data},
            {"id": deal_msg_ref.id, **deal_msg_data},
        )

    async def counter_offer(
        self,
        conv_id: str,
        offer_id: str,
        counter_uid: str,
        new_amount: float,
    ) -> tuple[dict, dict]:
        """Counter an offer. Returns (new_offer, message)."""
        conv = await self.get_conversation(conv_id)
        if not conv:
            raise ValueError("Conversation not found")
        if counter_uid not in conv.get("participants", []):
            raise PermissionError("Not a participant")

        offer = await self.get_offer(conv_id, offer_id)
        if not offer:
            raise ValueError("Offer not found")
        if offer["status"] != "pending":
            raise ValueError(f"Offer is {offer['status']}, cannot counter")
        if offer["senderUid"] == counter_uid:
            raise PermissionError("Cannot counter your own offer")

        return await self.send_offer(
            conv_id,
            counter_uid,
            new_amount,
            parent_offer_id=offer_id,
            list_price=offer.get("listPrice"),
            pin_target=offer.get("pinTarget"),
        )

    async def withdraw_offer(
        self,
        conv_id: str,
        offer_id: str,
        withdrawer_uid: str,
    ) -> dict:
        """Withdraw own offer. Returns system message."""
        conv = await self.get_conversation(conv_id)
        if not conv:
            raise ValueError("Conversation not found")
        if withdrawer_uid not in conv.get("participants", []):
            raise PermissionError("Not a participant")

        offer = await self.get_offer(conv_id, offer_id)
        if not offer:
            raise ValueError("Offer not found")
        if offer["status"] != "pending":
            raise ValueError(f"Offer is {offer['status']}, cannot withdraw")
        if offer["senderUid"] != withdrawer_uid:
            raise PermissionError("Can only withdraw your own offer")

        now = datetime.now(timezone.utc)
        await self._offer_col(conv_id).document(offer_id).update({
            "status": "withdrawn",
            "updatedAt": firestore.SERVER_TIMESTAMP,
        })

        msg_ref = self._msg_col(conv_id).document()
        msg_data = {
            "senderId": withdrawer_uid,
            "text": "Offer withdrawn",
            "createdAt": now,
            "type": "system",
            "subtype": "offer_withdrawn",
            "deletedAt": None,
        }
        await msg_ref.set(msg_data)

        update: dict = {
            "updatedAt": firestore.SERVER_TIMESTAMP,
        }
        if conv.get("activeOfferId") == offer_id:
            update["activeOfferId"] = None
        await self._conv_ref(conv_id).update(update)

        return {"id": msg_ref.id, **msg_data}

    # ── phone reveal ──────────────────────────────────────────────────────────

    async def share_phone(self, conv_id: str, uid: str) -> None:
        """Opt this user into phone sharing for this conversation thread."""
        conv = await self.get_conversation(conv_id)
        if not conv:
            raise ValueError("Conversation not found")
        if uid not in conv.get("participants", []):
            raise PermissionError("Not a participant")
        await self._conv_ref(conv_id).update({
            f"phoneSharedBy.{uid}": True,
            "updatedAt": firestore.SERVER_TIMESTAMP,
        })

    async def get_phone_reveal(
        self,
        conv_id: str,
        requester_uid: str,
        user_repo,
    ) -> str:
        """
        Return counterparty's phoneE164.
        Raises PermissionError if gates not met.
        """
        conv = await self.get_conversation(conv_id)
        if not conv or requester_uid not in conv.get("participants", []):
            raise PermissionError("Not a participant")
        if conv.get("dealStatus") != "agreed":
            raise PermissionError("No agreed deal on this conversation")
        other_uid = next(
            (p for p in conv.get("participants", []) if p != requester_uid), None
        )
        if not other_uid:
            raise PermissionError("No counterparty found")
        shared_by = conv.get("phoneSharedBy", {})
        if not shared_by.get(other_uid):
            raise PermissionError("Counterparty has not shared their phone number")
        phone = await user_repo.get_phone(other_uid)
        if not phone:
            raise PermissionError("Counterparty has no phone number on file")
        return phone

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

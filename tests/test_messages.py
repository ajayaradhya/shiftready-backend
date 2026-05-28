"""Unit tests for messages router — all services mocked via dep overrides."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from app.core.deps import get_firestore, get_messaging
from app.services.auth import get_current_user, User


def _user(uid="buyer_123"):
    return User(id=uid, email="buyer@test.com", name="Buyer")


def _msg(**overrides):
    base = {
        "id": "msg1",
        "senderId": "buyer_123",
        "text": "Hello",
        "type": "text",
        "createdAt": None,
        "subtype": None,
        "context": None,
        "pinSnapshot": None,
        "offerPayload": None,
    }
    return {**base, **overrides}


@pytest.fixture(autouse=True)
def mock_msg_deps(mock_services):
    """Override firestore + messaging + auth deps for all messages unit tests."""
    from app.main import app

    fs = MagicMock()
    fs.get_user = AsyncMock(return_value={"id": "seller_456", "username": "seller"})
    fs.users = MagicMock()
    fs.users.update_last_seen = AsyncMock()
    fs.conversations = MagicMock()
    fs.conversations.get_conversation = AsyncMock(
        return_value={
            "id": "conv1",
            "participants": ["buyer_123", "seller_456"],
            "status": "active",
        }
    )
    fs.get_phone_reveal = AsyncMock(return_value="+61412345678")
    fs.share_phone = AsyncMock()

    svc = MagicMock()
    svc.start_conversation = AsyncMock(return_value=("conv1", {"id": "conv1"}))
    svc.send = AsyncMock(return_value=_msg())
    svc.list_conversations = AsyncMock(return_value=[])
    svc.get_unread_count = AsyncMock(return_value=3)
    svc.list_messages = AsyncMock(return_value=[_msg()])
    svc.mark_read = AsyncMock()
    svc.block = AsyncMock()
    svc.unblock = AsyncMock()
    svc.send_offer = AsyncMock(return_value=_msg(type="offer"))
    svc.accept_offer = AsyncMock(return_value=_msg(type="offer_accepted"))
    svc.counter_offer = AsyncMock(return_value=_msg(type="counter_offer"))
    svc.withdraw_offer = AsyncMock(return_value=_msg(type="offer_withdrawn"))

    app.dependency_overrides[get_firestore] = lambda: fs
    app.dependency_overrides[get_messaging] = lambda: svc
    app.dependency_overrides[get_current_user] = lambda: _user()

    yield {"fs": fs, "svc": svc}

    for dep in (get_firestore, get_messaging, get_current_user):
        app.dependency_overrides.pop(dep, None)


# ── Conversation creation ─────────────────────────────────────────────────────


async def test_start_conversation_success(async_client):
    r = await async_client.post(
        "/api/v1/messages/conversations",
        json={"otherUserId": "seller_456"},
    )
    assert r.status_code == 200
    assert r.json()["conversationId"] == "conv1"
    assert r.json()["created"] is True


async def test_start_conversation_self_blocked(async_client):
    r = await async_client.post(
        "/api/v1/messages/conversations",
        json={"otherUserId": "buyer_123"},
    )
    assert r.status_code == 400
    assert "Cannot message yourself" in r.json()["detail"]


async def test_start_conversation_unknown_user_returns_404(async_client, mock_msg_deps):
    mock_msg_deps["fs"].get_user = AsyncMock(return_value=None)
    r = await async_client.post(
        "/api/v1/messages/conversations",
        json={"otherUserId": "ghost"},
    )
    assert r.status_code == 404


async def test_start_conversation_with_initial_message(async_client, mock_msg_deps):
    r = await async_client.post(
        "/api/v1/messages/conversations",
        json={"otherUserId": "seller_456", "initialMessage": "Hi, is this available?"},
    )
    assert r.status_code == 200
    mock_msg_deps["svc"].send.assert_called_once()


# ── Conversation list + unread ────────────────────────────────────────────────


async def test_list_conversations_returns_empty(async_client):
    r = await async_client.get("/api/v1/messages/conversations")
    assert r.status_code == 200
    assert r.json() == []


async def test_unread_count(async_client):
    r = await async_client.get("/api/v1/messages/conversations/unread")
    assert r.status_code == 200
    assert r.json()["unreadCount"] == 3


# ── Messages ──────────────────────────────────────────────────────────────────


async def test_get_messages(async_client):
    r = await async_client.get("/api/v1/messages/conversations/conv1/messages")
    assert r.status_code == 200
    body = r.json()
    assert body["conversationId"] == "conv1"
    assert len(body["messages"]) == 1


async def test_send_message_success(async_client):
    r = await async_client.post(
        "/api/v1/messages/conversations/conv1/messages",
        json={"text": "Is the sofa still available?"},
    )
    assert r.status_code == 200
    assert r.json()["id"] == "msg1"


async def test_send_message_calls_last_seen_update(async_client, mock_msg_deps):
    await async_client.post(
        "/api/v1/messages/conversations/conv1/messages",
        json={"text": "Hello"},
    )
    mock_msg_deps["fs"].users.update_last_seen.assert_called_once_with("buyer_123")


async def test_mark_read_success(async_client):
    r = await async_client.post("/api/v1/messages/conversations/conv1/read")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


# ── Offers ────────────────────────────────────────────────────────────────────


async def test_send_offer_success(async_client):
    r = await async_client.post(
        "/api/v1/messages/conversations/conv1/offers",
        json={"amount": 250.0},
    )
    assert r.status_code == 200
    assert r.json()["type"] == "offer"


async def test_send_offer_zero_amount_rejected(async_client):
    r = await async_client.post(
        "/api/v1/messages/conversations/conv1/offers",
        json={"amount": 0},
    )
    assert r.status_code == 422
    assert "positive" in r.json()["detail"]


async def test_send_offer_negative_amount_rejected(async_client):
    r = await async_client.post(
        "/api/v1/messages/conversations/conv1/offers",
        json={"amount": -50.0},
    )
    assert r.status_code == 422


async def test_accept_offer_success(async_client):
    r = await async_client.post(
        "/api/v1/messages/conversations/conv1/offers/offer1/accept"
    )
    assert r.status_code == 200


async def test_counter_offer_success(async_client):
    r = await async_client.post(
        "/api/v1/messages/conversations/conv1/offers/offer1/counter",
        json={"amount": 200.0},
    )
    assert r.status_code == 200


async def test_counter_zero_amount_rejected(async_client):
    r = await async_client.post(
        "/api/v1/messages/conversations/conv1/offers/offer1/counter",
        json={"amount": 0},
    )
    assert r.status_code == 422


async def test_withdraw_offer_success(async_client):
    r = await async_client.post(
        "/api/v1/messages/conversations/conv1/offers/offer1/withdraw"
    )
    assert r.status_code == 200


# ── Permission errors bubble up correctly ─────────────────────────────────────


async def test_send_message_permission_error_is_403(async_client, mock_msg_deps):
    mock_msg_deps["svc"].send.side_effect = PermissionError("Not a participant")
    r = await async_client.post(
        "/api/v1/messages/conversations/conv1/messages",
        json={"text": "Sneaky"},
    )
    assert r.status_code == 403


async def test_accept_offer_permission_error_is_403(async_client, mock_msg_deps):
    mock_msg_deps["svc"].accept_offer.side_effect = PermissionError(
        "Only seller can accept"
    )
    r = await async_client.post(
        "/api/v1/messages/conversations/conv1/offers/offer1/accept"
    )
    assert r.status_code == 403

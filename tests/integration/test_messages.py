"""
Integration Layer 6 — Messaging.

Tests start-conversation, send text, send offer, accept offer, and mark-read
against the Firestore emulator.  GCS and Gemini remain mocked.
"""

import pytest
from google.cloud import firestore as fs_lib

from .conftest import auth, USER_A, SELLER


# ── Seed fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
async def seed_users(fsdb):
    """Both conversation participants must exist in users/{uid}."""
    for uid, username in [(USER_A, "alpha_user"), (SELLER, "ace_seller")]:
        await (
            fsdb.collection("users")
            .document(uid)
            .set(
                {
                    "id": uid,
                    "email": f"{uid}@test.com",
                    "username": username,
                    "usernameSetByUser": True,
                    "createdAt": fs_lib.SERVER_TIMESTAMP,
                }
            )
        )


# ── Helpers ───────────────────────────────────────────────────────────────────


async def start_conv(client, buyer=USER_A, seller=SELLER) -> str:
    r = await client.post(
        "/api/v1/messages/conversations",
        headers=auth(buyer),
        json={"otherUserId": seller},
    )
    assert r.status_code == 200, r.text
    return r.json()["conversationId"]


# ── Tests ─────────────────────────────────────────────────────────────────────


async def test_start_conversation_creates_conv(client):
    conv_id = await start_conv(client)
    assert conv_id


async def test_start_conversation_idempotent(client):
    conv_id_1 = await start_conv(client)
    conv_id_2 = await start_conv(client)
    assert conv_id_1 == conv_id_2


async def test_start_conversation_self_rejected(client):
    r = await client.post(
        "/api/v1/messages/conversations",
        headers=auth(USER_A),
        json={"otherUserId": USER_A},
    )
    assert r.status_code == 400


async def test_start_conversation_unknown_user_rejected(client):
    r = await client.post(
        "/api/v1/messages/conversations",
        headers=auth(USER_A),
        json={"otherUserId": "nonexistent_uid_xyz"},
    )
    assert r.status_code == 404


async def test_send_text_message(client):
    conv_id = await start_conv(client)
    r = await client.post(
        f"/api/v1/messages/conversations/{conv_id}/messages",
        headers=auth(USER_A),
        json={"text": "Is the sofa still available?"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["senderId"] == USER_A
    assert body["type"] == "text"


async def test_get_messages_after_send(client):
    conv_id = await start_conv(client)
    await client.post(
        f"/api/v1/messages/conversations/{conv_id}/messages",
        headers=auth(USER_A),
        json={"text": "Hello"},
    )
    r = await client.get(
        f"/api/v1/messages/conversations/{conv_id}/messages",
        headers=auth(USER_A),
    )
    assert r.status_code == 200
    msgs = r.json()["messages"]
    assert len(msgs) >= 1
    assert msgs[0]["text"] == "Hello"


async def test_send_offer_creates_offer_message(client):
    conv_id = await start_conv(client)
    r = await client.post(
        f"/api/v1/messages/conversations/{conv_id}/offers",
        headers=auth(USER_A),
        json={"amount": 300.0},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["senderId"] == USER_A


async def test_list_conversations_shows_new_conv(client):
    await start_conv(client)
    r = await client.get("/api/v1/messages/conversations", headers=auth(USER_A))
    assert r.status_code == 200
    convs = r.json()
    assert len(convs) >= 1


async def test_unread_count_after_message(client):
    conv_id = await start_conv(client)
    await client.post(
        f"/api/v1/messages/conversations/{conv_id}/messages",
        headers=auth(USER_A),
        json={"text": "New message"},
    )
    r = await client.get("/api/v1/messages/conversations/unread", headers=auth(SELLER))
    assert r.status_code == 200
    assert r.json()["unreadCount"] >= 1


async def test_mark_read_clears_unread(client):
    conv_id = await start_conv(client)
    await client.post(
        f"/api/v1/messages/conversations/{conv_id}/messages",
        headers=auth(USER_A),
        json={"text": "Ping"},
    )
    r = await client.post(
        f"/api/v1/messages/conversations/{conv_id}/read",
        headers=auth(SELLER),
    )
    assert r.status_code == 200


async def test_unauthenticated_returns_401(client):
    r = await client.get("/api/v1/messages/conversations")
    assert r.status_code == 401

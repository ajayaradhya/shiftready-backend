"""
Integration Layer 7 — Users.

Tests profile read, username update, account deletion, and data export
against the Firestore emulator.
"""

import pytest
from google.cloud import firestore as fs_lib

from .conftest import auth, USER_A


# ── Seed fixture ──────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
async def seed_user(fsdb):
    """Seed a user doc for USER_A before each test."""
    await (
        fsdb.collection("users")
        .document(USER_A)
        .set(
            {
                "id": USER_A,
                "email": f"{USER_A}@test.com",
                "username": "alpha_user",
                "usernameSetByUser": True,
                "usernameChangedAt": None,
                "displayName": "Alpha",
                "bio": None,
                "phoneE164": None,
                "phoneShareOptIn": True,
                "suburb": "Waterloo",
                "state": "NSW",
                "notifPrefs": {},
                "sellerPrefs": {},
                "privacyPrefs": {},
                "createdAt": fs_lib.SERVER_TIMESTAMP,
                "isDeleted": False,
            }
        )
    )


# ── Profile read ──────────────────────────────────────────────────────────────


async def test_get_me_returns_profile(client):
    r = await client.get("/api/v1/users/me", headers=auth(USER_A))
    assert r.status_code == 200
    data = r.json()
    assert data["username"] == "alpha_user"


async def test_get_me_without_user_doc_returns_404(client, fsdb):
    """When the user doc is missing (e.g. first login before upsert), return 404."""
    await fsdb.collection("users").document(USER_A).delete()
    r = await client.get("/api/v1/users/me", headers=auth(USER_A))
    assert r.status_code == 404


async def test_get_settings_returns_prefs(client):
    r = await client.get("/api/v1/users/me/settings", headers=auth(USER_A))
    assert r.status_code == 200
    data = r.json()
    assert "notifPrefs" in data
    assert data["suburb"] == "Waterloo"


# ── Username ──────────────────────────────────────────────────────────────────


async def test_check_username_available(client):
    r = await client.get(
        "/api/v1/users/username-available",
        params={"u": "brandnewname"},
        headers=auth(USER_A),
    )
    assert r.status_code == 200
    assert r.json()["available"] is True


async def test_check_own_username_available(client):
    """A user checking their own username should see it as available."""
    r = await client.get(
        "/api/v1/users/username-available",
        params={"u": "alpha_user"},
        headers=auth(USER_A),
    )
    assert r.status_code == 200
    assert r.json()["available"] is True


async def test_update_username_success(client):
    r = await client.patch(
        "/api/v1/users/me/username",
        headers=auth(USER_A),
        json={"username": "alpha_v2"},
    )
    assert r.status_code == 200
    assert r.json()["username"] == "alpha_v2"


async def test_update_username_invalid_format_rejected(client):
    r = await client.patch(
        "/api/v1/users/me/username",
        headers=auth(USER_A),
        json={"username": "InvalidCaps"},
    )
    assert r.status_code == 422


async def test_update_username_too_short_rejected(client):
    r = await client.patch(
        "/api/v1/users/me/username",
        headers=auth(USER_A),
        json={"username": "ab"},
    )
    assert r.status_code == 422


# ── Profile update ────────────────────────────────────────────────────────────


async def test_update_phone_valid(client):
    r = await client.patch(
        "/api/v1/users/me/phone",
        headers=auth(USER_A),
        json={"phoneE164": "+61412345678"},
    )
    assert r.status_code == 200


async def test_update_phone_non_au_rejected(client):
    r = await client.patch(
        "/api/v1/users/me/phone",
        headers=auth(USER_A),
        json={"phoneE164": "+12125551234"},
    )
    assert r.status_code == 422


async def test_update_profile_fields(client):
    r = await client.patch(
        "/api/v1/users/me/profile",
        headers=auth(USER_A),
        json={"displayName": "Updated Name", "bio": "Selling furniture"},
    )
    assert r.status_code == 200


async def test_update_location(client):
    r = await client.patch(
        "/api/v1/users/me/location",
        headers=auth(USER_A),
        json={"suburb": "Newtown", "state": "NSW"},
    )
    assert r.status_code == 200


# ── Account deletion ──────────────────────────────────────────────────────────


async def test_delete_account_succeeds(client, fsdb):
    r = await client.delete("/api/v1/users/me", headers=auth(USER_A))
    assert r.status_code == 200
    assert r.json()["status"] == "deleted"

    doc = await fsdb.collection("users").document(USER_A).get()
    assert doc.exists
    assert doc.to_dict().get("isDeleted") is True


# ── Data export ───────────────────────────────────────────────────────────────


async def test_export_data_returns_profile(client):
    r = await client.get("/api/v1/users/me/export", headers=auth(USER_A))
    assert r.status_code == 200
    data = r.json()
    assert "profile" in data
    assert "saved_sales" in data
    assert "saved_items" in data
    assert "exported_at" in data


# ── Auth guard ────────────────────────────────────────────────────────────────


async def test_unauthenticated_returns_401(client):
    r = await client.get("/api/v1/users/me")
    assert r.status_code == 401

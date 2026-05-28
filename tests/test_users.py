"""Unit tests for users router — firestore dep mocked via dep overrides."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from app.core.deps import get_firestore, get_gcs
from app.services.auth import get_current_user, User


def _user(uid="uid123"):
    return User(id=uid, email="user@test.com", name="Test User")


def _user_doc(**overrides):
    base = {
        "id": "uid123",
        "username": "testuser",
        "usernameSetByUser": True,
        "usernameChangedAt": None,
        "email": "user@test.com",
        "displayName": "Test User",
        "bio": None,
        "phoneE164": None,
        "phoneShareOptIn": True,
        "suburb": "Waterloo",
        "state": "NSW",
        "notifPrefs": {},
        "sellerPrefs": {},
        "privacyPrefs": {},
        "createdAt": None,
    }
    return {**base, **overrides}


@pytest.fixture(autouse=True)
def mock_user_services(mock_services):
    from app.main import app

    fs = MagicMock()
    fs.get_user = AsyncMock(return_value=_user_doc())
    fs.get_user_by_username = AsyncMock(return_value=_user_doc())
    fs.is_username_available = AsyncMock(return_value=True)
    fs.update_username = AsyncMock()
    fs.update_phone = AsyncMock()
    fs.update_profile_fields = AsyncMock()
    fs.update_location = AsyncMock()
    fs.update_notif_prefs = AsyncMock()
    fs.update_seller_prefs = AsyncMock()
    fs.update_privacy_prefs = AsyncMock()
    fs.soft_delete_user = AsyncMock()
    fs.get_user_export_data = AsyncMock(return_value={
        "profile": {"username": "testuser"},
        "saved_sales": [],
        "saved_items": [],
    })
    fs.get_saved = AsyncMock(return_value={"saved_sales": [], "saved_items": []})

    gcs = MagicMock()
    gcs.generate_download_url = MagicMock(return_value="https://mock-gcs/img.jpg")

    app.dependency_overrides[get_firestore] = lambda: fs
    app.dependency_overrides[get_gcs] = lambda: gcs
    app.dependency_overrides[get_current_user] = lambda: _user()

    yield {"fs": fs}

    for dep in (get_firestore, get_gcs, get_current_user):
        app.dependency_overrides.pop(dep, None)


# ── GET /me ───────────────────────────────────────────────────────────────────

async def test_get_me_returns_profile(async_client):
    r = await async_client.get("/api/v1/users/me")
    assert r.status_code == 200
    data = r.json()
    assert data["username"] == "testuser"
    assert data["usernameSetByUser"] is True


async def test_get_me_user_not_found(async_client, mock_user_services):
    mock_user_services["fs"].get_user = AsyncMock(return_value=None)
    r = await async_client.get("/api/v1/users/me")
    assert r.status_code == 404


# ── Username ──────────────────────────────────────────────────────────────────

async def test_check_username_available(async_client):
    r = await async_client.get("/api/v1/users/username-available", params={"u": "newname"})
    assert r.status_code == 200
    assert r.json()["available"] is True
    assert r.json()["username"] == "newname"


async def test_check_username_unavailable(async_client, mock_user_services):
    mock_user_services["fs"].is_username_available = AsyncMock(return_value=False)
    r = await async_client.get("/api/v1/users/username-available", params={"u": "taken"})
    assert r.status_code == 200
    assert r.json()["available"] is False


async def test_check_username_invalid_format_rejected(async_client):
    # "ab1" is 3 chars — passes Query min_length=3 but fails regex (needs 4+ chars total)
    r = await async_client.get("/api/v1/users/username-available", params={"u": "ab1"})
    assert r.status_code == 200
    assert r.json()["available"] is False


async def test_update_username_success(async_client):
    r = await async_client.patch("/api/v1/users/me/username", json={"username": "newname"})
    assert r.status_code == 200


async def test_update_username_taken_returns_409(async_client, mock_user_services):
    mock_user_services["fs"].update_username = AsyncMock(side_effect=ValueError("Username already taken"))
    r = await async_client.patch("/api/v1/users/me/username", json={"username": "takenname"})
    assert r.status_code == 409


async def test_update_username_invalid_format_returns_422(async_client):
    # "ab" is too short per regex ^[a-zA-Z][a-zA-Z0-9]{3,19}$
    r = await async_client.patch("/api/v1/users/me/username", json={"username": "ab"})
    assert r.status_code == 422


# ── Profile fields ────────────────────────────────────────────────────────────

async def test_update_phone_valid_au_number(async_client):
    r = await async_client.patch("/api/v1/users/me/phone", json={"phoneE164": "+61412345678"})
    assert r.status_code == 200
    assert r.json()["status"] == "updated"


async def test_update_phone_invalid_number_rejected(async_client):
    r = await async_client.patch("/api/v1/users/me/phone", json={"phoneE164": "+1555123456"})
    assert r.status_code == 422
    assert "Australian" in r.json()["detail"]


async def test_update_profile_success(async_client):
    r = await async_client.patch("/api/v1/users/me/profile", json={"displayName": "Jane", "bio": "Hello"})
    assert r.status_code == 200


async def test_update_location_success(async_client):
    r = await async_client.patch("/api/v1/users/me/location", json={"suburb": "Newtown", "state": "NSW"})
    assert r.status_code == 200


# ── Settings ──────────────────────────────────────────────────────────────────

async def test_get_settings_returns_prefs(async_client):
    r = await async_client.get("/api/v1/users/me/settings")
    assert r.status_code == 200
    data = r.json()
    assert "notifPrefs" in data
    assert "sellerPrefs" in data
    assert "privacyPrefs" in data


async def test_update_notifications_success(async_client):
    r = await async_client.patch(
        "/api/v1/users/me/notifications",
        json={"prefs": {"messages": True, "offers": True}},
    )
    assert r.status_code == 200


# ── Account management ────────────────────────────────────────────────────────

async def test_delete_account_success(async_client):
    r = await async_client.delete("/api/v1/users/me")
    assert r.status_code == 200
    assert r.json()["status"] == "deleted"


async def test_delete_account_not_found_returns_404(async_client, mock_user_services):
    mock_user_services["fs"].soft_delete_user = AsyncMock(side_effect=ValueError("User not found"))
    r = await async_client.delete("/api/v1/users/me")
    assert r.status_code == 404


async def test_export_data_success(async_client):
    r = await async_client.get("/api/v1/users/me/export")
    assert r.status_code == 200
    data = r.json()
    assert "profile" in data
    assert "saved_sales" in data
    assert "exported_at" in data


async def test_export_data_not_found_returns_404(async_client, mock_user_services):
    mock_user_services["fs"].get_user_export_data = AsyncMock(side_effect=ValueError("User not found"))
    r = await async_client.get("/api/v1/users/me/export")
    assert r.status_code == 404


# ── Saved items ───────────────────────────────────────────────────────────────

async def test_get_saved_returns_empty(async_client):
    r = await async_client.get("/api/v1/users/me/saved")
    assert r.status_code == 200
    data = r.json()
    assert data["saved_sales"] == []
    assert data["saved_items"] == []

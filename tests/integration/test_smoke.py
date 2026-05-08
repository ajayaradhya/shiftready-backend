"""Layer 1 — Smoke tests: app boots, base routes respond, auth guards are active."""
import pytest
from .conftest import auth, USER_A


async def test_root(client):
    r = await client.get("/")
    assert r.status_code == 200
    assert "ShiftReady" in r.json()["message"]


async def test_health(client):
    r = await client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "operational"
    assert "uptime_seconds" in body


async def test_sales_init_requires_auth(client):
    r = await client.post("/api/v1/sales/init", json={"filename": "test.mp4"})
    assert r.status_code == 401
    assert "Missing authentication token" in r.json()["detail"]


async def test_sales_list_requires_auth(client):
    r = await client.get("/api/v1/sales/")
    assert r.status_code == 401


async def test_marketplace_search_is_public(client):
    r = await client.get("/api/v1/marketplace/search")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 0
    assert body["is_authenticated"] is False


async def test_dev_token_accepted_locally(client):
    """Dev tokens (dev_*) must be accepted when K_SERVICE is not set."""
    r = await client.post(
        "/api/v1/sales/init",
        json={"filename": "smoke.mp4"},
        headers=auth(USER_A),
    )
    assert r.status_code == 200
    assert "event_id" in r.json()

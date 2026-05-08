"""
Layer 3 — Authorisation.

Every sale-mutating and sale-reading endpoint must reject a user who does not
own the sale.  Only the sale owner should succeed.
"""
import pytest
from .conftest import auth, init_sale, USER_A, USER_B


@pytest.fixture
async def user_a_sale(client) -> str:
    """Create a sale owned by USER_A and return its event_id."""
    return await init_sale(client, USER_A)


async def test_owner_can_read_own_sale(client, user_a_sale):
    r = await client.get(f"/api/v1/sales/{user_a_sale}/summary", headers=auth(USER_A))
    assert r.status_code == 200


async def test_other_user_cannot_read_sale_summary(client, user_a_sale):
    r = await client.get(f"/api/v1/sales/{user_a_sale}/summary", headers=auth(USER_B))
    assert r.status_code == 403
    assert "Access denied" in r.json()["detail"]


async def test_other_user_cannot_read_sale_status(client, user_a_sale):
    r = await client.get(f"/api/v1/sales/{user_a_sale}/status", headers=auth(USER_B))
    assert r.status_code == 403


async def test_other_user_cannot_trigger_processing(client, user_a_sale):
    r = await client.post(f"/api/v1/sales/{user_a_sale}/process", headers=auth(USER_B))
    assert r.status_code == 403


async def test_other_user_cannot_publish_sale(client, user_a_sale):
    r = await client.post(
        f"/api/v1/sales/{user_a_sale}/publish",
        json={
            "move_out_date": "2026-06-01",
            "street_address": "1 Test St",
            "suburb": "Waterloo",
            "pincode": "2017",
            "state": "NSW",
        },
        headers=auth(USER_B),
    )
    assert r.status_code == 403


async def test_other_user_cannot_add_bundle(client, user_a_sale):
    r = await client.post(
        f"/api/v1/sales/{user_a_sale}/bundles",
        json={"name": "Intruder Bundle"},
        headers=auth(USER_B),
    )
    assert r.status_code == 403


async def test_nonexistent_event_returns_404(client):
    r = await client.get("/api/v1/sales/nonexistent_event_id/status", headers=auth(USER_A))
    assert r.status_code == 404


async def test_unauthenticated_request_returns_401(client, user_a_sale):
    r = await client.get(f"/api/v1/sales/{user_a_sale}/summary")
    assert r.status_code == 401

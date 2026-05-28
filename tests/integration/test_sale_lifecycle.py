"""
Layer 2 — Full sale lifecycle.

Tests the state machine: init → (CRUD items) → estimate (mock pricing) → publish → unpublish.
"""

import pytest
from app.domain.status import SaleStatus
from .conftest import auth, init_sale, add_bundle_with_item, USER_A


@pytest.fixture
def mock_pricing(mock_external_services):
    """Configure Gemini pricing mock to echo back item IDs with a flat price."""

    async def _pricing(items, move_out_date):
        return (
            [
                {
                    "id": it["id"],
                    "listing_price": 500.0,
                    "reasoning": "Good market value",
                }
                for it in items
            ],
            {"model": "test", "status": "success"},
        )

    mock_external_services["price"].side_effect = _pricing
    return mock_external_services


# ── Tests ─────────────────────────────────────────────────────────────────────


async def test_init_capture_returns_event_id(client):
    r = await client.post("/api/v1/sales/init-capture", headers=auth(USER_A))
    assert r.status_code == 200
    body = r.json()
    assert "event_id" in body


async def test_init_capture_persists_sale_in_firestore(client, fsdb):
    r = await client.post("/api/v1/sales/init-capture", headers=auth(USER_A))
    event_id = r.json()["event_id"]
    doc = await fsdb.collection("saleEvents").document(event_id).get()
    assert doc.exists
    data = doc.to_dict()
    assert data["sellerId"] == USER_A
    assert data["status"] == SaleStatus.PENDING_UPLOAD
    assert "videoUrl" not in data


async def test_get_status_after_init(client):
    event_id = await init_sale(client)
    r = await client.get(f"/api/v1/sales/{event_id}/status", headers=auth(USER_A))
    assert r.status_code == 200
    assert r.json()["status"] == SaleStatus.PENDING_UPLOAD


async def test_list_sales_returns_created_sale(client):
    event_id = await init_sale(client)
    r = await client.get("/api/v1/sales/", headers=auth(USER_A))
    assert r.status_code == 200
    ids = [s["id"] for s in r.json()]
    assert event_id in ids


async def test_get_summary_returns_hierarchy(client):
    event_id = await init_sale(client)
    await add_bundle_with_item(client, event_id, item_name="Velvet Sofa")

    r = await client.get(f"/api/v1/sales/{event_id}/summary", headers=auth(USER_A))
    assert r.status_code == 200
    body = r.json()
    assert len(body["bundles"]) == 1
    assert len(body["bundles"][0]["items"]) == 1
    assert body["bundles"][0]["items"][0]["name"] == "Velvet Sofa"
    assert "videoUrl" not in body


async def test_estimate_triggers_pricing_and_updates_items(client, mock_pricing):
    event_id = await init_sale(client)
    await add_bundle_with_item(client, event_id)

    r = await client.post(
        f"/api/v1/sales/{event_id}/estimate",
        json={"move_out_date": "2026-06-01"},
        headers=auth(USER_A),
    )
    assert r.status_code == 200

    r = await client.get(f"/api/v1/sales/{event_id}/status", headers=auth(USER_A))
    assert r.json()["status"] == SaleStatus.READY_FOR_REVIEW

    r = await client.get(f"/api/v1/sales/{event_id}/summary", headers=auth(USER_A))
    item = r.json()["bundles"][0]["items"][0]
    assert item["actual_listing_price"] == 500.0
    assert item["pricing_reasoning"] == "Good market value"


async def test_publish_sets_status_live(client):
    event_id = await init_sale(client)
    await add_bundle_with_item(client, event_id)

    r = await client.post(
        f"/api/v1/sales/{event_id}/publish",
        json={
            "move_out_date": "2026-06-01",
            "street_address": "12 Botany Rd",
            "suburb": "Waterloo",
            "pincode": "2017",
            "state": "NSW",
        },
        headers=auth(USER_A),
    )
    assert r.status_code == 200
    assert r.json()["status"] == SaleStatus.LIVE


async def test_publish_stores_address_in_firestore(client, fsdb):
    event_id = await init_sale(client)
    await add_bundle_with_item(client, event_id)
    await client.post(
        f"/api/v1/sales/{event_id}/publish",
        json={
            "move_out_date": "2026-06-01",
            "street_address": "12 Botany Rd",
            "suburb": "Waterloo",
            "pincode": "2017",
            "state": "NSW",
        },
        headers=auth(USER_A),
    )

    doc = await fsdb.collection("saleEvents").document(event_id).get()
    data = doc.to_dict()
    assert data["status"] == SaleStatus.LIVE
    assert data["suburb"] == "Waterloo"
    assert data["streetAddress"] == "12 Botany Rd"


async def test_publish_applies_fallback_price_for_unpriced_items(client):
    """Items without actual_listing_price should fall back to predicted_listing_price on publish."""
    event_id = await init_sale(client)
    bundle_id, item_id = await add_bundle_with_item(
        client, event_id, actual_listing_price=0.0
    )
    # Set predicted price but leave actual as 0 (fallback path)
    await client.patch(
        f"/api/v1/sales/{event_id}/bundles/{bundle_id}/items/{item_id}",
        json={"actual_listing_price": None},
        headers=auth(USER_A),
    )

    r = await client.post(
        f"/api/v1/sales/{event_id}/publish",
        json={
            "move_out_date": "2026-06-01",
            "street_address": "1 Test St",
            "suburb": "Zetland",
            "pincode": "2017",
            "state": "NSW",
        },
        headers=auth(USER_A),
    )
    assert r.status_code == 200


async def test_unpublish_reverts_to_ready_for_review(client):
    event_id = await init_sale(client)
    await add_bundle_with_item(client, event_id)
    await client.post(
        f"/api/v1/sales/{event_id}/publish",
        json={
            "move_out_date": "2026-06-01",
            "street_address": "1 Test",
            "suburb": "Waterloo",
            "pincode": "2017",
            "state": "NSW",
        },
        headers=auth(USER_A),
    )

    r = await client.post(f"/api/v1/sales/{event_id}/unpublish", headers=auth(USER_A))
    assert r.status_code == 200
    assert r.json()["status"] == SaleStatus.READY_FOR_REVIEW


async def test_unpublish_from_non_live_status_is_rejected(client):
    event_id = await init_sale(client)
    r = await client.post(f"/api/v1/sales/{event_id}/unpublish", headers=auth(USER_A))
    assert r.status_code == 400

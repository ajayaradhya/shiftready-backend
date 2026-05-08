"""
Layer 2 — Full sale lifecycle.

Tests the entire state machine: init → process (mock extraction) → estimate
(mock pricing) → publish → unpublish.  Each step asserts the HTTP response AND
verifies Firestore state directly via fsdb.
"""
import pytest
from app.models.inventory import InventoryItem, RoomBundle
from app.domain.status import SaleStatus
from .conftest import auth, init_sale, USER_A


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_extraction(mock_external_services):
    """Configure Gemini extraction mock to return one bundle with one item."""
    item = InventoryItem(
        name="Velvet Sofa",
        brand="West Elm",
        condition="Excellent",
        confidence=0.95,
        predicted_year_of_purchase=2023,
        predicted_original_price=1200.0,
        timestamp_label="01:30",
        video_timestamp=90.0,
    )
    bundle = RoomBundle(bundle_name="Living Room", items=[item])
    mock_external_services["extract"].return_value = (
        [bundle],
        {"model": "test", "usage": {}, "status": "success"},
    )
    return mock_external_services


@pytest.fixture
def mock_pricing(mock_external_services):
    """Configure Gemini pricing mock to echo back item IDs with a flat price."""
    async def _pricing(items, move_out_date):
        return (
            [{"id": it["id"], "listing_price": 500.0, "reasoning": "Good market value"}
             for it in items],
            {"model": "test", "status": "success"},
        )
    mock_external_services["price"].side_effect = _pricing
    return mock_external_services


# ── Tests ─────────────────────────────────────────────────────────────────────

async def test_init_returns_event_id_and_upload_url(client):
    r = await client.post(
        "/api/v1/sales/init",
        json={"filename": "walk.mp4"},
        headers=auth(USER_A),
    )
    assert r.status_code == 200
    body = r.json()
    assert "event_id" in body
    assert body["upload_url"] == "https://mock-gcs/upload"
    assert body["gcs_uri"].startswith("gs://")


async def test_init_persists_sale_in_firestore(client, fsdb):
    r = await client.post(
        "/api/v1/sales/init",
        json={"filename": "walk.mp4"},
        headers=auth(USER_A),
    )
    event_id = r.json()["event_id"]
    doc = await fsdb.collection("saleEvents").document(event_id).get()
    assert doc.exists
    data = doc.to_dict()
    assert data["sellerId"] == USER_A
    assert data["status"] == SaleStatus.PENDING_UPLOAD


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


async def test_process_triggers_extraction_and_reaches_ready(client, mock_extraction):
    event_id = await init_sale(client)
    r = await client.post(f"/api/v1/sales/{event_id}/process", headers=auth(USER_A))
    assert r.status_code == 200

    # Background task ran inline with ASGITransport
    r = await client.get(f"/api/v1/sales/{event_id}/status", headers=auth(USER_A))
    assert r.json()["status"] == SaleStatus.READY_FOR_REVIEW


async def test_process_creates_bundles_and_items_in_firestore(client, fsdb, mock_extraction):
    event_id = await init_sale(client)
    await client.post(f"/api/v1/sales/{event_id}/process", headers=auth(USER_A))

    bundles = await fsdb.collection("saleEvents").document(event_id) \
                        .collection("bundles").get()
    bundles = list(bundles)
    assert len(bundles) == 1
    assert bundles[0].to_dict()["name"] == "Living Room"

    items = await bundles[0].reference.collection("items").get()
    items = list(items)
    assert len(items) == 1
    assert items[0].to_dict()["name"] == "Velvet Sofa"


async def test_get_summary_returns_hierarchy(client, mock_extraction):
    event_id = await init_sale(client)
    await client.post(f"/api/v1/sales/{event_id}/process", headers=auth(USER_A))

    r = await client.get(f"/api/v1/sales/{event_id}/summary", headers=auth(USER_A))
    assert r.status_code == 200
    body = r.json()
    assert len(body["bundles"]) == 1
    assert len(body["bundles"][0]["items"]) == 1
    assert body["bundles"][0]["items"][0]["name"] == "Velvet Sofa"
    # GCS URI should be rewritten to a signed URL
    assert body["videoUrl"] == "https://mock-gcs/video"


async def test_estimate_triggers_pricing_and_updates_items(client, mock_extraction, mock_pricing):
    event_id = await init_sale(client)
    await client.post(f"/api/v1/sales/{event_id}/process", headers=auth(USER_A))

    r = await client.post(
        f"/api/v1/sales/{event_id}/estimate",
        json={"move_out_date": "2026-06-01"},
        headers=auth(USER_A),
    )
    assert r.status_code == 200

    r = await client.get(f"/api/v1/sales/{event_id}/status", headers=auth(USER_A))
    assert r.json()["status"] == SaleStatus.READY_FOR_REVIEW

    # Items should have pricing applied
    r = await client.get(f"/api/v1/sales/{event_id}/summary", headers=auth(USER_A))
    item = r.json()["bundles"][0]["items"][0]
    assert item["actual_listing_price"] == 500.0
    assert item["pricing_reasoning"] == "Good market value"


async def test_publish_sets_status_live(client, mock_extraction, mock_pricing):
    event_id = await init_sale(client)
    await client.post(f"/api/v1/sales/{event_id}/process", headers=auth(USER_A))
    await client.post(
        f"/api/v1/sales/{event_id}/estimate",
        json={"move_out_date": "2026-06-01"},
        headers=auth(USER_A),
    )

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


async def test_publish_stores_address_in_firestore(client, fsdb, mock_extraction, mock_pricing):
    event_id = await init_sale(client)
    await client.post(f"/api/v1/sales/{event_id}/process", headers=auth(USER_A))
    await client.post(
        f"/api/v1/sales/{event_id}/estimate",
        json={"move_out_date": "2026-06-01"},
        headers=auth(USER_A),
    )
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


async def test_publish_applies_fallback_price_for_unpriced_items(client, mock_extraction):
    """Items without actual_listing_price should fall back to predicted_listing_price on publish."""
    # Use extraction mock that returns an item with predicted price but no actual price
    from unittest.mock import AsyncMock
    item = InventoryItem(
        name="Old Chair",
        brand="IKEA",
        condition="Good",
        confidence=0.8,
        predicted_year_of_purchase=2020,
        predicted_original_price=200.0,
        predicted_listing_price=80.0,  # AI predicted price
        actual_listing_price=None,     # user hasn't set one
    )
    bundle = RoomBundle(bundle_name="Office", items=[item])
    mock_extraction["extract"].return_value = ([bundle], {"status": "success"})

    event_id = await init_sale(client)
    await client.post(f"/api/v1/sales/{event_id}/process", headers=auth(USER_A))

    # Publish WITHOUT running estimate first (no actual_listing_price set)
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

    # Verify fallback was applied
    r = await client.get(f"/api/v1/sales/{event_id}/summary", headers=auth(USER_A))
    item_data = r.json()["bundles"][0]["items"][0]
    assert item_data["actual_listing_price"] == 80.0


async def test_unpublish_reverts_to_ready_for_review(client, mock_extraction, mock_pricing):
    event_id = await init_sale(client)
    await client.post(f"/api/v1/sales/{event_id}/process", headers=auth(USER_A))
    await client.post(
        f"/api/v1/sales/{event_id}/estimate",
        json={"move_out_date": "2026-06-01"},
        headers=auth(USER_A),
    )
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
    # Sale is PENDING_UPLOAD — unpublish must be rejected
    r = await client.post(f"/api/v1/sales/{event_id}/unpublish", headers=auth(USER_A))
    assert r.status_code == 400

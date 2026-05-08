"""
Layer 6 — AI Pipeline behaviour.

Tests the extraction and pricing pipelines end-to-end using Gemini mocks:
success paths, failure paths, and retry semantics.  Background tasks run
synchronously in ASGITransport so no polling is needed.
"""
import pytest
from app.models.inventory import InventoryItem, RoomBundle
from app.models.schemas import SaleStatus
from .conftest import auth, init_sale, USER_A


# ── Shared mock data ──────────────────────────────────────────────────────────

def make_bundle(name="Living Room", items=None):
    if items is None:
        items = [
            InventoryItem(
                name="Velvet Sofa",
                brand="West Elm",
                condition="Excellent",
                confidence=0.95,
                predicted_year_of_purchase=2023,
                predicted_original_price=1200.0,
            )
        ]
    return RoomBundle(bundle_name=name, items=items)


# ── Extraction pipeline ───────────────────────────────────────────────────────

async def test_extraction_success_creates_items_and_transitions_status(
    client, mock_external_services
):
    mock_external_services["extract"].return_value = (
        [make_bundle()],
        {"model": "test", "status": "success"},
    )

    event_id = await init_sale(client)
    r = await client.post(f"/api/v1/sales/{event_id}/process", headers=auth(USER_A))
    assert r.status_code == 200

    status_r = await client.get(f"/api/v1/sales/{event_id}/status", headers=auth(USER_A))
    assert status_r.json()["status"] == SaleStatus.READY_FOR_REVIEW

    summary_r = await client.get(f"/api/v1/sales/{event_id}/summary", headers=auth(USER_A))
    bundles = summary_r.json()["bundles"]
    assert len(bundles) == 1
    assert bundles[0]["name"] == "Living Room"
    assert len(bundles[0]["items"]) == 1


async def test_extraction_failure_sets_status_failed(client, mock_external_services):
    mock_external_services["extract"].side_effect = Exception("Gemini unavailable")

    event_id = await init_sale(client)
    await client.post(f"/api/v1/sales/{event_id}/process", headers=auth(USER_A))

    status_r = await client.get(f"/api/v1/sales/{event_id}/status", headers=auth(USER_A))
    assert status_r.json()["status"] == SaleStatus.FAILED


async def test_extraction_retry_succeeds_on_second_attempt(client, mock_external_services):
    """First call raises, second call returns bundles — status should be READY_FOR_REVIEW."""
    call_count = 0

    async def flaky_extract(gcs_uri):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise Exception("Transient error")
        return ([make_bundle()], {"status": "success"})

    mock_external_services["extract"].side_effect = flaky_extract

    event_id = await init_sale(client)
    await client.post(f"/api/v1/sales/{event_id}/process", headers=auth(USER_A))

    status_r = await client.get(f"/api/v1/sales/{event_id}/status", headers=auth(USER_A))
    assert status_r.json()["status"] == SaleStatus.READY_FOR_REVIEW
    assert call_count == 2


async def test_extraction_stores_ai_metadata_in_firestore(client, fsdb, mock_external_services):
    mock_external_services["extract"].return_value = (
        [make_bundle()],
        {"model": "gemini-test", "usage": {"input_tokens": 10}, "status": "success"},
    )

    event_id = await init_sale(client)
    await client.post(f"/api/v1/sales/{event_id}/process", headers=auth(USER_A))

    doc = await fsdb.collection("saleEvents").document(event_id).get()
    meta = doc.to_dict().get("extractionMetadata", {})
    assert meta.get("model") == "gemini-test"


# ── Pricing pipeline ──────────────────────────────────────────────────────────

async def test_pricing_success_updates_items_and_transitions_status(
    client, mock_external_services
):
    # First run extraction to create items
    mock_external_services["extract"].return_value = (
        [make_bundle()],
        {"status": "success"},
    )
    event_id = await init_sale(client)
    await client.post(f"/api/v1/sales/{event_id}/process", headers=auth(USER_A))

    # Configure pricing mock to echo item IDs
    async def pricing(items, move_out_date):
        return (
            [{"id": it["id"], "listing_price": 600.0, "reasoning": "Sydney market rate"}
             for it in items],
            {"status": "success"},
        )
    mock_external_services["price"].side_effect = pricing

    r = await client.post(
        f"/api/v1/sales/{event_id}/estimate",
        json={"move_out_date": "2026-06-15"},
        headers=auth(USER_A),
    )
    assert r.status_code == 200

    status_r = await client.get(f"/api/v1/sales/{event_id}/status", headers=auth(USER_A))
    assert status_r.json()["status"] == SaleStatus.READY_FOR_REVIEW

    summary_r = await client.get(f"/api/v1/sales/{event_id}/summary", headers=auth(USER_A))
    item = summary_r.json()["bundles"][0]["items"][0]
    assert item["actual_listing_price"] == 600.0
    assert item["pricing_reasoning"] == "Sydney market rate"


async def test_pricing_failure_sets_status_failed(client, mock_external_services):
    mock_external_services["extract"].return_value = ([make_bundle()], {"status": "success"})
    event_id = await init_sale(client)
    await client.post(f"/api/v1/sales/{event_id}/process", headers=auth(USER_A))

    mock_external_services["price"].side_effect = Exception("Pricing service down")

    await client.post(
        f"/api/v1/sales/{event_id}/estimate",
        json={"move_out_date": "2026-06-15"},
        headers=auth(USER_A),
    )

    status_r = await client.get(f"/api/v1/sales/{event_id}/status", headers=auth(USER_A))
    assert status_r.json()["status"] == SaleStatus.FAILED


async def test_pricing_recalculates_bundle_total(client, mock_external_services):
    mock_external_services["extract"].return_value = (
        [RoomBundle(
            bundle_name="Office",
            items=[
                InventoryItem(name="Desk",  brand="IKEA", condition="Good",
                              confidence=0.9, predicted_year_of_purchase=2021,
                              predicted_original_price=300.0),
                InventoryItem(name="Chair", brand="IKEA", condition="Good",
                              confidence=0.9, predicted_year_of_purchase=2021,
                              predicted_original_price=150.0),
            ],
        )],
        {"status": "success"},
    )
    event_id = await init_sale(client)
    await client.post(f"/api/v1/sales/{event_id}/process", headers=auth(USER_A))

    async def pricing(items, move_out_date):
        prices = [200.0, 80.0]
        return (
            [{"id": it["id"], "listing_price": prices[i], "reasoning": "ok"}
             for i, it in enumerate(items)],
            {"status": "success"},
        )
    mock_external_services["price"].side_effect = pricing

    await client.post(
        f"/api/v1/sales/{event_id}/estimate",
        json={"move_out_date": "2026-06-15"},
        headers=auth(USER_A),
    )

    summary_r = await client.get(f"/api/v1/sales/{event_id}/summary", headers=auth(USER_A))
    assert summary_r.json()["bundles"][0]["suggestedPrice"] == 280.0

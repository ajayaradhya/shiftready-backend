"""
Integration Layer 8 — Sold lifecycle state machine.

Seeds a LIVE sale with 2 items in 1 bundle, then exercises:
  - mark item sold → item.sale_status = SOLD, sale → PARTIALLY_SOLD
  - mark remaining item sold → bundle SOLD, sale → SOLD
  - mark bundle sold (as unit) → all items SOLD
  - mark sale sold (all at once) → all items SOLD
  - withdraw + relist item
"""

import pytest

from app.domain.status import BundleSaleStatus, ItemSaleStatus, SaleStatus
from .conftest import auth, init_sale, add_bundle_with_item, USER_A


# ── Sale with 2 items fixture ─────────────────────────────────────────────────


@pytest.fixture
async def live_sale_two_items(client, fsdb) -> dict:
    """Create a LIVE sale with one bundle containing two items."""
    event_id = await init_sale(client, USER_A)
    bundle_id, item_a = await add_bundle_with_item(
        client,
        event_id,
        USER_A,
        bundle_name="Living Room",
        item_name="Sofa",
        actual_listing_price=500.0,
    )
    r = await client.post(
        f"/api/v1/sales/{event_id}/bundles/{bundle_id}/items",
        json={
            "name": "Coffee Table",
            "brand": "IKEA",
            "condition": "Good",
            "actual_listing_price": 150.0,
            "actual_original_price": 300.0,
            "actual_year_of_purchase": 2022,
        },
        headers=auth(USER_A),
    )
    assert r.status_code == 200
    item_b = r.json()["item_id"]

    # Publish to make LIVE
    await client.post(
        f"/api/v1/sales/{event_id}/publish",
        json={
            "move_out_date": "2026-08-01",
            "street_address": "10 King St",
            "suburb": "Newtown",
            "pincode": "2042",
            "state": "NSW",
        },
        headers=auth(USER_A),
    )

    return {
        "event_id": event_id,
        "bundle_id": bundle_id,
        "item_a": item_a,
        "item_b": item_b,
    }


# ── Tests ─────────────────────────────────────────────────────────────────────


async def test_mark_one_item_sold_makes_sale_partially_sold(
    client, live_sale_two_items
):
    ids = live_sale_two_items
    r = await client.post(
        f"/api/v1/sales/{ids['event_id']}/bundles/{ids['bundle_id']}/items/{ids['item_a']}/mark-sold",
        json={"final_price": 480.0, "buyer_label": "Alice"},
        headers=auth(USER_A),
    )
    assert r.status_code == 200

    status_r = await client.get(
        f"/api/v1/sales/{ids['event_id']}/status",
        headers=auth(USER_A),
    )
    assert status_r.json()["status"] == SaleStatus.PARTIALLY_SOLD


async def test_mark_both_items_sold_makes_sale_sold(client, live_sale_two_items, fsdb):
    ids = live_sale_two_items
    for item_id in (ids["item_a"], ids["item_b"]):
        r = await client.post(
            f"/api/v1/sales/{ids['event_id']}/bundles/{ids['bundle_id']}/items/{item_id}/mark-sold",
            json={"buyer_label": "Bob"},
            headers=auth(USER_A),
        )
        assert r.status_code == 200

    status_r = await client.get(
        f"/api/v1/sales/{ids['event_id']}/status",
        headers=auth(USER_A),
    )
    assert status_r.json()["status"] == SaleStatus.SOLD

    # Verify item sale_status persisted
    item_doc = (
        await fsdb.collection("saleEvents")
        .document(ids["event_id"])
        .collection("bundles")
        .document(ids["bundle_id"])
        .collection("items")
        .document(ids["item_a"])
        .get()
    )
    assert item_doc.to_dict()["sale_status"] == ItemSaleStatus.SOLD


async def test_mark_bundle_sold_as_unit(client, live_sale_two_items, fsdb):
    ids = live_sale_two_items
    r = await client.post(
        f"/api/v1/sales/{ids['event_id']}/bundles/{ids['bundle_id']}/mark-sold",
        json={"scope": "bundle_as_unit", "final_price": 600.0, "buyer_label": "Carol"},
        headers=auth(USER_A),
    )
    assert r.status_code == 200

    status_r = await client.get(
        f"/api/v1/sales/{ids['event_id']}/status",
        headers=auth(USER_A),
    )
    assert status_r.json()["status"] == SaleStatus.SOLD

    bundle_doc = (
        await fsdb.collection("saleEvents")
        .document(ids["event_id"])
        .collection("bundles")
        .document(ids["bundle_id"])
        .get()
    )
    assert bundle_doc.to_dict()["sale_status"] == BundleSaleStatus.SOLD


async def test_mark_sale_sold_marks_all(client, live_sale_two_items, fsdb):
    ids = live_sale_two_items
    r = await client.post(
        f"/api/v1/sales/{ids['event_id']}/mark-sold",
        json={"buyer_label": "Dave"},
        headers=auth(USER_A),
    )
    assert r.status_code == 200

    for item_id in (ids["item_a"], ids["item_b"]):
        item_doc = (
            await fsdb.collection("saleEvents")
            .document(ids["event_id"])
            .collection("bundles")
            .document(ids["bundle_id"])
            .collection("items")
            .document(item_id)
            .get()
        )
        assert item_doc.to_dict()["sale_status"] == ItemSaleStatus.SOLD


async def test_mark_sold_non_active_sale_rejected(client, live_sale_two_items, fsdb):
    """Once a sale is SOLD, further mark-sold calls should fail (409 — not active)."""
    ids = live_sale_two_items
    await client.post(
        f"/api/v1/sales/{ids['event_id']}/mark-sold",
        json={},
        headers=auth(USER_A),
    )
    r = await client.post(
        f"/api/v1/sales/{ids['event_id']}/mark-sold",
        json={},
        headers=auth(USER_A),
    )
    assert r.status_code == 409


async def test_withdraw_item_and_relist(client, live_sale_two_items, fsdb):
    ids = live_sale_two_items
    r = await client.post(
        f"/api/v1/sales/{ids['event_id']}/bundles/{ids['bundle_id']}/items/{ids['item_a']}/withdraw",
        json={"notes": "Damaged"},
        headers=auth(USER_A),
    )
    assert r.status_code == 200

    item_doc = (
        await fsdb.collection("saleEvents")
        .document(ids["event_id"])
        .collection("bundles")
        .document(ids["bundle_id"])
        .collection("items")
        .document(ids["item_a"])
        .get()
    )
    assert item_doc.to_dict()["sale_status"] == ItemSaleStatus.WITHDRAWN

    r = await client.post(
        f"/api/v1/sales/{ids['event_id']}/bundles/{ids['bundle_id']}/items/{ids['item_a']}/relist",
        headers=auth(USER_A),
    )
    assert r.status_code == 200

    item_doc = (
        await fsdb.collection("saleEvents")
        .document(ids["event_id"])
        .collection("bundles")
        .document(ids["bundle_id"])
        .collection("items")
        .document(ids["item_a"])
        .get()
    )
    assert item_doc.to_dict()["sale_status"] == ItemSaleStatus.AVAILABLE


async def test_transactions_recorded_on_sold(client, live_sale_two_items):
    ids = live_sale_two_items
    await client.post(
        f"/api/v1/sales/{ids['event_id']}/bundles/{ids['bundle_id']}/items/{ids['item_a']}/mark-sold",
        json={"final_price": 500.0},
        headers=auth(USER_A),
    )
    r = await client.get(
        f"/api/v1/sales/{ids['event_id']}/transactions",
        headers=auth(USER_A),
    )
    assert r.status_code == 200
    txns = r.json()
    assert len(txns) >= 1
    assert txns[0]["type"] == "sold"

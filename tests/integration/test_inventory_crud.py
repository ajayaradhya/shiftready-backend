"""
Layer 5 — Inventory CRUD.

Covers bundle and item create/update/delete operations and verifies that
bundle totals are recalculated correctly after every mutation.
"""
from .conftest import auth, init_sale, USER_A


# ── Helpers ───────────────────────────────────────────────────────────────────

async def add_bundle(client, event_id: str, name: str = "Test Bundle") -> str:
    r = await client.post(
        f"/api/v1/sales/{event_id}/bundles",
        json={"name": name},
        headers=auth(USER_A),
    )
    assert r.status_code == 200
    return r.json()["bundle_id"]


async def add_item(client, event_id: str, bundle_id: str, **overrides) -> str:
    payload = {
        "name": "Test Chair",
        "brand": "IKEA",
        "condition": "Good",
        "actual_listing_price": 100.0,
        "actual_original_price": 200.0,
        "actual_year_of_purchase": 2022,
        **overrides,
    }
    r = await client.post(
        f"/api/v1/sales/{event_id}/bundles/{bundle_id}/items",
        json=payload,
        headers=auth(USER_A),
    )
    assert r.status_code == 200
    return r.json()["item_id"]


async def get_summary(client, event_id: str) -> dict:
    r = await client.get(f"/api/v1/sales/{event_id}/summary", headers=auth(USER_A))
    assert r.status_code == 200
    return r.json()


# ── Tests ─────────────────────────────────────────────────────────────────────

async def test_add_bundle_appears_in_summary(client):
    event_id = await init_sale(client)
    await add_bundle(client, event_id, "Living Room")

    summary = await get_summary(client, event_id)
    bundle_names = [b["name"] for b in summary["bundles"]]
    assert "Living Room" in bundle_names


async def test_delete_bundle_removes_it(client):
    event_id = await init_sale(client)
    bundle_id = await add_bundle(client, event_id)

    r = await client.delete(
        f"/api/v1/sales/{event_id}/bundles/{bundle_id}",
        headers=auth(USER_A),
    )
    assert r.status_code == 200

    summary = await get_summary(client, event_id)
    assert len(summary["bundles"]) == 0


async def test_delete_bundle_also_removes_its_items(client, fsdb):
    event_id = await init_sale(client)
    bundle_id = await add_bundle(client, event_id)
    await add_item(client, event_id, bundle_id)

    await client.delete(
        f"/api/v1/sales/{event_id}/bundles/{bundle_id}",
        headers=auth(USER_A),
    )

    # Sub-collection items must be gone too
    items = await fsdb.collection("saleEvents").document(event_id) \
                      .collection("bundles").document(bundle_id) \
                      .collection("items").get()
    assert list(items) == []


async def test_add_item_appears_in_bundle(client):
    event_id = await init_sale(client)
    bundle_id = await add_bundle(client, event_id)
    await add_item(client, event_id, bundle_id, name="Bookshelf")

    summary = await get_summary(client, event_id)
    items = summary["bundles"][0]["items"]
    assert any(i["name"] == "Bookshelf" for i in items)


async def test_add_item_updates_bundle_total(client):
    event_id = await init_sale(client)
    bundle_id = await add_bundle(client, event_id)
    await add_item(client, event_id, bundle_id, actual_listing_price=150.0)
    await add_item(client, event_id, bundle_id, actual_listing_price=50.0)

    summary = await get_summary(client, event_id)
    bundle = summary["bundles"][0]
    assert bundle["suggestedPrice"] == 200.0


async def test_patch_item_price_updates_bundle_total(client):
    event_id = await init_sale(client)
    bundle_id = await add_bundle(client, event_id)
    item_id = await add_item(client, event_id, bundle_id, actual_listing_price=100.0)

    r = await client.patch(
        f"/api/v1/sales/{event_id}/bundles/{bundle_id}/items/{item_id}",
        json={"actual_listing_price": 250.0},
        headers=auth(USER_A),
    )
    assert r.status_code == 200

    summary = await get_summary(client, event_id)
    assert summary["bundles"][0]["suggestedPrice"] == 250.0


async def test_patch_item_non_price_field_does_not_recalculate(client):
    event_id = await init_sale(client)
    bundle_id = await add_bundle(client, event_id)
    item_id = await add_item(client, event_id, bundle_id, actual_listing_price=100.0)

    await client.patch(
        f"/api/v1/sales/{event_id}/bundles/{bundle_id}/items/{item_id}",
        json={"condition": "Fair"},
        headers=auth(USER_A),
    )

    summary = await get_summary(client, event_id)
    # Price should be unchanged
    assert summary["bundles"][0]["suggestedPrice"] == 100.0
    assert summary["bundles"][0]["items"][0]["condition"] == "Fair"


async def test_delete_item_recalculates_bundle_total(client):
    event_id = await init_sale(client)
    bundle_id = await add_bundle(client, event_id)
    item_id_a = await add_item(client, event_id, bundle_id, actual_listing_price=200.0)
    await add_item(client, event_id, bundle_id, actual_listing_price=100.0)

    r = await client.delete(
        f"/api/v1/sales/{event_id}/bundles/{bundle_id}/items/{item_id_a}",
        headers=auth(USER_A),
    )
    assert r.status_code == 200

    summary = await get_summary(client, event_id)
    assert len(summary["bundles"][0]["items"]) == 1
    assert summary["bundles"][0]["suggestedPrice"] == 100.0


async def test_patch_invalid_price_returns_422(client):
    event_id = await init_sale(client)
    bundle_id = await add_bundle(client, event_id)
    item_id = await add_item(client, event_id, bundle_id)

    r = await client.patch(
        f"/api/v1/sales/{event_id}/bundles/{bundle_id}/items/{item_id}",
        json={"actual_listing_price": "not-a-number"},
        headers=auth(USER_A),
    )
    assert r.status_code == 422

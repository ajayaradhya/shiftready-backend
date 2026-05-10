"""
Layer 4 — Marketplace.

Seeds Firestore directly (bypassing the API) to control sale state precisely,
then exercises search, privacy masking, suburb filtering, keyword search,
and item detail endpoints.
"""
import pytest
from google.cloud import firestore as fs_lib
from app.domain.status import SaleStatus
from .conftest import auth, SELLER, USER_A


# ── Seed fixture ──────────────────────────────────────────────────────────────

@pytest.fixture
async def marketplace_data(fsdb):
    """
    Seeds:
      - event_waterloo: LIVE, suburb=Waterloo, owned by SELLER, 2 items (sofa + lamp)
      - event_zetland:  LIVE, suburb=Zetland,  owned by dev_seller_bob, 1 item (bed)
      - event_hidden:   READY_FOR_REVIEW, must NOT appear in search
    """
    # --- LIVE sale: Waterloo ---
    w_ref = fsdb.collection("saleEvents").document("event_waterloo")
    await w_ref.set({
        "sellerId": SELLER,
        "status": SaleStatus.LIVE,
        "suburb": "Waterloo",
        "createdAt": fs_lib.SERVER_TIMESTAMP,
    })
    b1 = w_ref.collection("bundles").document("b1")
    await b1.set({"name": "Living Room"})
    await b1.collection("items").document("item_sofa").set({
        "name": "Velvet Sofa",
        "brand": "West Elm",
        "condition": "Excellent",
        "actual_listing_price": 450.0,
        "actual_original_price": 1200.0,
        "actual_year_of_purchase": 2023,
        "confidence": 0.98,
    })
    await b1.collection("items").document("item_lamp").set({
        "name": "Industrial Lamp",
        "brand": "IKEA",
        "condition": "Good",
        "actual_listing_price": 50.0,
        "actual_original_price": 99.0,
        "actual_year_of_purchase": 2021,
        "confidence": 1.0,
    })

    # --- LIVE sale: Zetland ---
    z_ref = fsdb.collection("saleEvents").document("event_zetland")
    await z_ref.set({
        "sellerId": "dev_seller_bob",
        "status": SaleStatus.LIVE,
        "suburb": "Zetland",
        "createdAt": fs_lib.SERVER_TIMESTAMP,
    })
    b2 = z_ref.collection("bundles").document("b2")
    await b2.set({"name": "Bedroom"})
    await b2.collection("items").document("item_bed").set({
        "name": "Queen Bed",
        "brand": "Koala",
        "condition": "New",
        "actual_listing_price": 800.0,
        "actual_original_price": 1500.0,
        "actual_year_of_purchase": 2024,
        "confidence": 0.95,
    })

    # --- Non-LIVE sale (hidden) ---
    h_ref = fsdb.collection("saleEvents").document("event_hidden")
    await h_ref.set({
        "sellerId": SELLER,
        "status": SaleStatus.READY_FOR_REVIEW,
        "suburb": "Waterloo",
        "createdAt": fs_lib.SERVER_TIMESTAMP,
    })
    b3 = h_ref.collection("bundles").document("b3")
    await b3.set({"name": "Misc"})
    await b3.collection("items").document("ghost").set({"name": "Invisible Chair"})

    return {
        "sofa":  {"event_id": "event_waterloo", "bundle_id": "b1", "item_id": "item_sofa"},
        "lamp":  {"event_id": "event_waterloo", "bundle_id": "b1", "item_id": "item_lamp"},
        "bed":   {"event_id": "event_zetland",  "bundle_id": "b2", "item_id": "item_bed"},
        "ghost": {"event_id": "event_hidden",   "bundle_id": "b3", "item_id": "ghost"},
    }


# ── Helpers ───────────────────────────────────────────────────────────────────

async def search(client, *, q=None, suburb=None, headers=None):
    params = {}
    if q:
        params["q"] = q
    if suburb:
        params["suburb"] = suburb
    return await client.get("/api/v1/marketplace/search", params=params, headers=headers or {})


# ── Tests ─────────────────────────────────────────────────────────────────────

async def test_list_live_sales(client, marketplace_data):
    r = await client.get("/api/v1/marketplace/sales")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, list)
    event_ids = {s["eventId"] for s in body}
    assert "event_waterloo" in event_ids
    assert "event_zetland" in event_ids
    assert "event_hidden" not in event_ids

    waterloo = next(s for s in body if s["eventId"] == "event_waterloo")
    assert waterloo["suburb"] == "Waterloo"
    assert waterloo["itemCount"] == 2
    assert waterloo["minPrice"] == 50.0


async def test_live_sales_appear_in_search(client, marketplace_data):
    r = await search(client)
    assert r.status_code == 200
    # 3 items (sofa + lamp + bed) from the 2 LIVE sales
    assert r.json()["count"] == 3


async def test_non_live_sale_is_hidden(client, marketplace_data):
    r = await search(client, q="Invisible")
    assert r.json()["count"] == 0


async def test_suburb_filter_waterloo(client, marketplace_data):
    r = await search(client, suburb="Waterloo")
    assert r.json()["count"] == 2
    names = {it["name"] for it in r.json()["items"]}
    assert "Velvet Sofa" in names
    assert "Industrial Lamp" in names


async def test_suburb_filter_zetland(client, marketplace_data):
    r = await search(client, suburb="Zetland")
    assert r.json()["count"] == 1
    assert r.json()["items"][0]["name"] == "Queen Bed"


async def test_keyword_search_name(client, marketplace_data):
    r = await search(client, q="sofa")
    assert r.json()["count"] == 1
    assert r.json()["items"][0]["name"] == "Velvet Sofa"


async def test_keyword_search_brand_case_insensitive(client, marketplace_data):
    r = await search(client, q="ikea")
    assert r.json()["count"] == 1
    assert r.json()["items"][0]["name"] == "Industrial Lamp"


async def test_anonymous_hides_metadata(client, marketplace_data):
    r = await search(client, q="sofa")
    meta = r.json()["items"][0]["metadata"]
    assert meta["originalPrice"] is None
    assert meta["year"] is None
    assert meta["confidence"] is None
    assert r.json()["is_authenticated"] is False


async def test_authenticated_non_owner_sees_price_and_year(client, marketplace_data):
    r = await search(client, q="sofa", headers=auth(USER_A))
    meta = r.json()["items"][0]["metadata"]
    assert meta["originalPrice"] == 1200.0
    assert meta["year"] == 2023
    # USER_A does not own this item (owned by SELLER)
    assert meta["confidence"] is None


async def test_owner_sees_confidence_score(client, marketplace_data):
    r = await search(client, q="sofa", headers=auth(SELLER))
    meta = r.json()["items"][0]["metadata"]
    assert meta["confidence"] == 0.98


async def test_non_owner_does_not_see_confidence(client, marketplace_data):
    r = await search(client, q="bed", headers=auth(SELLER))
    # SELLER owns the sofa, NOT the bed (owned by dev_seller_bob)
    meta = r.json()["items"][0]["metadata"]
    assert meta["confidence"] is None


async def test_item_detail_public_fields(client, marketplace_data):
    ids = marketplace_data["sofa"]
    r = await client.get(
        f"/api/v1/marketplace/items/{ids['event_id']}/{ids['bundle_id']}/{ids['item_id']}"
    )
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "Velvet Sofa"
    assert body["price"] == 450.0
    assert body["condition"] == "Excellent"
    # Not authenticated — premium fields absent
    assert "brand" not in body
    assert "reasoning" not in body


async def test_item_detail_authenticated_fields(client, marketplace_data):
    ids = marketplace_data["sofa"]
    r = await client.get(
        f"/api/v1/marketplace/items/{ids['event_id']}/{ids['bundle_id']}/{ids['item_id']}",
        headers=auth(USER_A),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["brand"] == "West Elm"
    assert body["purchase_year"] == 2023


async def test_item_detail_not_found(client):
    r = await client.get("/api/v1/marketplace/items/no/such/item")
    assert r.status_code == 404
    assert r.json()["detail"] == "Item not found"

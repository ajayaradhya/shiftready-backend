"""Unit tests for sold/lifecycle router — services mocked via dep overrides."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from app.core.deps import get_firestore
from app.domain.status import SaleStatus
from app.services.auth import get_current_user, validate_sale_owner


@pytest.fixture(autouse=True)
def mock_sold_services(mock_services):
    """Patch firestore dep with a mock lifecycle + transactions."""
    from app.main import app

    fs = MagicMock()
    lc = MagicMock()
    lc.mark_item_sold = AsyncMock()
    lc.mark_bundle_sold = AsyncMock()
    lc.mark_sale_sold = AsyncMock()
    lc.withdraw_item = AsyncMock()
    lc.withdraw_bundle = AsyncMock()
    lc.withdraw_sale = AsyncMock()
    lc.release_reservation = AsyncMock()
    lc.relist_item = AsyncMock()
    fs.lifecycle = lc
    fs.transactions = MagicMock()
    fs.transactions.list_transactions = AsyncMock(return_value=[])

    app.dependency_overrides[get_firestore] = lambda: fs
    yield {"fs": fs, "lc": lc}
    app.dependency_overrides.pop(get_firestore, None)


@pytest.fixture
def live_sale(mock_user):
    from app.main import app

    event = {"id": "evt1", "sellerId": mock_user.id, "status": SaleStatus.LIVE}
    app.dependency_overrides[validate_sale_owner] = lambda: event
    app.dependency_overrides[get_current_user] = lambda: mock_user
    yield event
    app.dependency_overrides.pop(validate_sale_owner, None)
    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture
def non_live_sale(mock_user):
    from app.main import app

    event = {
        "id": "evt1",
        "sellerId": mock_user.id,
        "status": SaleStatus.PENDING_UPLOAD,
    }
    app.dependency_overrides[validate_sale_owner] = lambda: event
    app.dependency_overrides[get_current_user] = lambda: mock_user
    yield event
    app.dependency_overrides.pop(validate_sale_owner, None)
    app.dependency_overrides.pop(get_current_user, None)


# ── Mark item sold ────────────────────────────────────────────────────────────


async def test_mark_item_sold_success(async_client, live_sale):
    r = await async_client.post(
        "/api/v1/sales/evt1/bundles/b1/items/i1/mark-sold",
        json={"final_price": 100.0, "buyer_label": "John"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "sold"


async def test_mark_item_sold_inactive_sale_rejected(async_client, non_live_sale):
    r = await async_client.post(
        "/api/v1/sales/evt1/bundles/b1/items/i1/mark-sold",
        json={},
    )
    assert r.status_code == 409
    assert "live or partially_sold" in r.json()["detail"]


async def test_mark_item_sold_already_sold_returns_400(
    async_client, live_sale, mock_sold_services
):
    mock_sold_services["lc"].mark_item_sold.side_effect = ValueError(
        "Item already sold"
    )
    r = await async_client.post(
        "/api/v1/sales/evt1/bundles/b1/items/i1/mark-sold",
        json={},
    )
    assert r.status_code == 400
    assert "already sold" in r.json()["detail"]


async def test_mark_item_sold_no_body_uses_defaults(async_client, live_sale):
    r = await async_client.post(
        "/api/v1/sales/evt1/bundles/b1/items/i1/mark-sold",
        json={},
    )
    assert r.status_code == 200


# ── Mark bundle sold ──────────────────────────────────────────────────────────


async def test_mark_bundle_sold_success(async_client, live_sale):
    r = await async_client.post(
        "/api/v1/sales/evt1/bundles/b1/mark-sold",
        json={"scope": "bundle_as_unit", "final_price": 500.0},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "sold"


async def test_mark_bundle_sold_inactive_sale_rejected(async_client, non_live_sale):
    r = await async_client.post(
        "/api/v1/sales/evt1/bundles/b1/mark-sold",
        json={"scope": "bundle_as_unit"},
    )
    assert r.status_code == 409


async def test_mark_bundle_no_items_returns_400(
    async_client, live_sale, mock_sold_services
):
    mock_sold_services["lc"].mark_bundle_sold.side_effect = ValueError(
        "No available items in bundle"
    )
    r = await async_client.post(
        "/api/v1/sales/evt1/bundles/b1/mark-sold",
        json={"scope": "bundle_as_unit"},
    )
    assert r.status_code == 400


# ── Mark sale sold ────────────────────────────────────────────────────────────


async def test_mark_sale_sold_success(async_client, live_sale):
    r = await async_client.post("/api/v1/sales/evt1/mark-sold", json={})
    assert r.status_code == 200
    assert r.json()["status"] == "sold"


async def test_mark_sale_sold_inactive_rejected(async_client, non_live_sale):
    r = await async_client.post("/api/v1/sales/evt1/mark-sold", json={})
    assert r.status_code == 409


# ── Withdraw ──────────────────────────────────────────────────────────────────


async def test_withdraw_item_success(async_client, live_sale):
    r = await async_client.post(
        "/api/v1/sales/evt1/bundles/b1/items/i1/withdraw",
        json={"notes": "Changed mind"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "withdrawn"


async def test_withdraw_item_not_found_returns_400(
    async_client, live_sale, mock_sold_services
):
    mock_sold_services["lc"].withdraw_item.side_effect = ValueError("Item not found")
    r = await async_client.post(
        "/api/v1/sales/evt1/bundles/b1/items/i1/withdraw",
        json={},
    )
    assert r.status_code == 400


async def test_withdraw_bundle_success(async_client, live_sale):
    r = await async_client.post(
        "/api/v1/sales/evt1/bundles/b1/withdraw",
        json={},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "withdrawn"


# ── Transactions ──────────────────────────────────────────────────────────────


async def test_list_transactions_empty(async_client, live_sale):
    r = await async_client.get("/api/v1/sales/evt1/transactions")
    assert r.status_code == 200
    assert r.json() == []


# ── Relist ────────────────────────────────────────────────────────────────────


async def test_relist_item_success(async_client, live_sale):
    r = await async_client.post(
        "/api/v1/sales/evt1/bundles/b1/items/i1/relist",
    )
    assert r.status_code == 200
    assert r.json()["status"] == "available"

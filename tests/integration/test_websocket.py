"""
Layer 7 — WebSocket.

Verifies that the status stream endpoint:
  - sends an initial STATUS_UPDATE immediately on connect
  - rejects connections from users who don't own the sale
  - broadcasts pipeline completion notifications to connected clients

Uses httpx-ws which handles the WebSocket upgrade over the ASGITransport.
"""
import pytest
import asyncio
from httpx_ws import aconnect_ws
from app.domain.status import SaleStatus
from .conftest import auth, init_sale, add_bundle_with_item, USER_A, USER_B


async def test_ws_sends_initial_status_on_connect(client):
    event_id = await init_sale(client)

    async with aconnect_ws(
        f"http://test/api/v1/sales/{event_id}/ws?token={USER_A}", client
    ) as ws:
        msg = await ws.receive_json()
        assert msg["type"] == "STATUS_UPDATE"
        assert msg["status"] == SaleStatus.PENDING_UPLOAD
        assert "Connected" in msg["message"]


async def test_ws_rejects_non_owner(client):
    """User B must not be able to connect to User A's WebSocket stream."""
    event_id = await init_sale(client, USER_A)

    with pytest.raises(Exception):
        async with aconnect_ws(
            f"http://test/api/v1/sales/{event_id}/ws?token={USER_B}", client
        ) as ws:
            await ws.receive_json()


async def test_ws_receives_pricing_complete_notification(client, mock_external_services):
    """After the pricing pipeline completes, connected clients get a READY_FOR_REVIEW broadcast."""
    async def _pricing(items, move_out_date):
        return (
            [{"id": it["id"], "listing_price": 300.0, "reasoning": "Market rate"} for it in items],
            {"status": "success"},
        )
    mock_external_services["price"].side_effect = _pricing

    event_id = await init_sale(client)
    await add_bundle_with_item(client, event_id)

    async with aconnect_ws(
        f"http://test/api/v1/sales/{event_id}/ws?token={USER_A}", client
    ) as ws:
        # Consume the initial STATUS_UPDATE
        initial = await ws.receive_json()
        assert initial["type"] == "STATUS_UPDATE"

        # Trigger pricing pipeline (runs inline with ASGITransport)
        await client.post(
            f"/api/v1/sales/{event_id}/estimate",
            json={"move_out_date": "2026-06-01"},
            headers=auth(USER_A),
        )

        # The pipeline notifier broadcasts READY_FOR_REVIEW
        notification = await asyncio.wait_for(ws.receive_json(), timeout=5.0)
        assert notification["status"] == SaleStatus.READY_FOR_REVIEW

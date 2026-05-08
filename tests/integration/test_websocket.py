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
from app.models.inventory import InventoryItem, RoomBundle
from app.models.schemas import SaleStatus
from .conftest import auth, init_sale, USER_A, USER_B


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


async def test_ws_receives_extraction_complete_notification(client, mock_external_services):
    """After the pipeline completes, connected clients get a READY_FOR_REVIEW broadcast."""
    mock_external_services["extract"].return_value = (
        [RoomBundle(
            bundle_name="Kitchen",
            items=[InventoryItem(
                name="Coffee Table", brand="IKEA", condition="Good",
                confidence=0.9, predicted_year_of_purchase=2022,
                predicted_original_price=200.0,
            )],
        )],
        {"status": "success"},
    )

    event_id = await init_sale(client)

    async with aconnect_ws(
        f"http://test/api/v1/sales/{event_id}/ws?token={USER_A}", client
    ) as ws:
        # Consume the initial STATUS_UPDATE
        initial = await ws.receive_json()
        assert initial["type"] == "STATUS_UPDATE"

        # Trigger the extraction pipeline (runs inline with ASGITransport)
        await client.post(f"/api/v1/sales/{event_id}/process", headers=auth(USER_A))

        # The pipeline notifier broadcasts READY_FOR_REVIEW
        notification = await asyncio.wait_for(ws.receive_json(), timeout=5.0)
        assert notification["status"] == SaleStatus.READY_FOR_REVIEW

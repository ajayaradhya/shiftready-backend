import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.models.schemas import SaleStatus

@pytest.mark.asyncio
async def test_init_sale_success(async_client, authenticated_user, mock_services):
    """Test full sale initialization flow with signed URL generation."""
    payload = {"filename": "my_move.mp4"}
    response = await async_client.post("/api/v1/sales/init", json=payload)
    
    assert response.status_code == 200
    data = response.json()
    assert data["event_id"] == "mock_event_id"
    assert "upload_url" in data
    mock_services["firestore"].create_sale_event.assert_called_once()

@pytest.mark.asyncio
async def test_get_sale_summary_ownership_enforcement(async_client, authenticated_user, mock_services):
    """Verify that validate_sale_owner dependency is active and blocking."""
    # We DON'T use the sale_ownership_verified fixture here to test the real dependency
    mock_services["firestore"].get_sale_event.return_value = {
        "sellerId": "someone_else"
    }
    
    response = await async_client.get("/api/v1/sales/mock_event_id/summary")
    assert response.status_code == 403
    assert "Access denied" in response.json()["detail"]

@pytest.mark.asyncio
async def test_publish_sale_logic(async_client, sale_ownership_verified, mock_services):
    """Tests the iterative price fallback logic during publication."""
    event_id = "mock_event_id"
    mock_services["firestore"].get_full_event_summary.return_value = {
        "bundles": [{
            "id": "b1",
            "items": [
                {"id": "i1", "actual_listing_price": None, "predicted_listing_price": 150.0},
                {"id": "i2", "actual_listing_price": 200.0, "predicted_listing_price": 100.0}
            ]
        }]
    }
    
    payload = {"move_out_date": "2026-05-22"}
    response = await async_client.post(f"/api/v1/sales/{event_id}/publish", json=payload)
    
    assert response.status_code == 200
    # Item 1 should have fallback applied
    mock_services["firestore"].update_item_data.assert_any_call(
        event_id, "b1", "i1", {"actual_listing_price": 150.0}
    )
    # Item 2 should NOT have fallback applied as it was already set
    assert mock_services["firestore"].update_item_data.call_count == 1

def test_websocket_status_updates():
    """WebSocket tests require TestClient (Sync) for easier handshake management."""
    from app.services.auth import validate_sale_owner
    
    # Setup WS Auth Override
    app.dependency_overrides[validate_sale_owner] = lambda: {"status": "processing"}
    
    client = TestClient(app)
    with client.websocket_connect("/api/v1/sales/mock_event_id/ws") as websocket:
        # 1. Check Initial State Sync
        data = websocket.receive_json()
        assert data["type"] == "STATUS_UPDATE"
        assert data["status"] == "processing"
        
    app.dependency_overrides.clear()

@pytest.mark.asyncio
async def test_unauthorized_access(async_client):
    """Verify that routes are protected by default."""
    # No authenticated_user fixture used here
    response = await async_client.get("/api/v1/sales/")
    assert response.status_code == 401
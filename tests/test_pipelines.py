import pytest
from unittest.mock import MagicMock
from app.services.pipelines import run_extraction_pipeline
from app.models.schemas import SaleStatus
from app.models.inventory import RoomBundle, InventoryItem

@pytest.mark.asyncio
async def test_extraction_pipeline_success(mock_services):
    """Verifies the background extraction logic and status transitions."""
    event_id = "test_event"
    gcs_uri = "gs://bucket/video.mp4"
    
    # Setup Mock Gemini Output
    mock_item = InventoryItem(name="Chair", brand="IKEA", condition="New", 
                              confidence=0.9, predicted_year_of_purchase=2024, 
                              predicted_original_price=50.0)
    mock_bundle = RoomBundle(bundle_name="Living Room", items=[mock_item])
    mock_services["gemini"].process_walkthrough.return_value = [mock_bundle]
    
    await run_extraction_pipeline(event_id, gcs_uri)
    
    # Check Transitions
    # 1. PROCESSING -> 2. READY_FOR_REVIEW
    mock_services["firestore"].transition_sale_status.assert_any_call(event_id, SaleStatus.PROCESSING)
    mock_services["firestore"].transition_sale_status.assert_any_call(event_id, SaleStatus.READY_FOR_REVIEW)
    
    # Check Persistence
    mock_services["firestore"].add_bundle.assert_called_once()
    mock_services["firestore"].add_item_to_bundle.assert_called_once()
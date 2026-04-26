import pytest
import asyncio
import sys
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.services.auth import User

# Fix for "Event loop is closed" on Windows
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

@pytest.fixture(scope="session")
def event_loop():
    """Overrides the default event_loop to ensure it stays open for the whole session."""
    policy = asyncio.get_event_loop_policy()
    loop = policy.new_event_loop()
    yield loop
    loop.close()

@pytest.fixture(scope="session")
async def async_client():
    """Async client for testing FastAPI endpoints."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac

@pytest.fixture
def mock_user():
    return User(id="test_user_123", email="tester@shiftready.test", name="Test User")

@pytest.fixture(autouse=True)
def mock_services():
    """
    Aggressively patches the SERVICE INSTANCES and CLIENT CLASSES.
    This ensures that even if modules already imported the services, 
    the underlying network calls are intercepted.
    """
    # Patch the actual instances used by the app
    from app.services import firestore_svc, gemini_processor, gcs_utils
    
    with patch.object(firestore_svc, 'db', new=AsyncMock()), \
         patch.object(firestore_svc, 'transition_sale_status', new=AsyncMock(return_value=True)), \
         patch.object(firestore_svc, 'create_sale_event', new=AsyncMock(return_value="mock_event_id")), \
         patch.object(firestore_svc, 'get_sale_event', new=AsyncMock()), \
         patch.object(firestore_svc, 'get_full_event_summary', new=AsyncMock()), \
         patch.object(firestore_svc, 'update_item_data', new=AsyncMock()), \
         patch.object(firestore_svc, 'update_sale_metadata', new=AsyncMock()), \
         patch.object(firestore_svc, 'list_all_sales', new=AsyncMock(return_value=[])), \
         patch.object(firestore_svc, 'add_bundle', new=AsyncMock(return_value="mock_bundle_id")), \
         patch.object(firestore_svc, 'add_item_to_bundle', new=AsyncMock(return_value="mock_item_id")), \
         patch.object(firestore_svc, 'recalculate_bundle_total', new=AsyncMock()), \
         patch.object(gemini_processor, 'client', new=MagicMock()), \
         patch.object(gemini_processor, 'process_walkthrough', new=AsyncMock()), \
         patch.object(gemini_processor, 'estimate_listing_prices', new=AsyncMock()), \
         patch.object(gcs_utils, 'generate_upload_url', return_value="https://mock-upload-url"):
        
        yield {
            "firestore": firestore_svc,
            "gemini": gemini_processor,
            "gcs": gcs_utils
        }

@pytest.fixture
def authenticated_user(mock_user):
    """Overrides the auth dependency to simulate a logged-in user."""
    from app.services.auth import get_current_user
    app.dependency_overrides[get_current_user] = lambda: mock_user
    yield mock_user
    app.dependency_overrides.pop(get_current_user, None)

@pytest.fixture
def sale_ownership_verified(mock_user):
    """Simulates that the current user owns the requested event."""
    from app.services.auth import validate_sale_owner
    mock_event = {
        "id": "mock_event_id",
        "sellerId": mock_user.id,
        "status": "pending_upload",
        "videoUrl": "gs://mock/path.mp4"
    }
    async def mock_validate():
        return mock_event
    app.dependency_overrides[validate_sale_owner] = mock_validate
    yield mock_event
    app.dependency_overrides.pop(validate_sale_owner, None)
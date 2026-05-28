"""
Integration test infrastructure.

Loads BEFORE the root tests/conftest.py imports app.main (because root conftest now
uses lazy imports inside fixtures). This lets us set FIRESTORE_EMULATOR_HOST first,
so FirestoreService connects to the emulator — not a real GCP project.

External paid services (GCS signed URLs, Gemini AI) are mocked at the singleton level
via a session-scoped fixture so every test gets safe defaults without any network calls.
"""

import os
import sys

# ── Must be set before any app import so FirestoreService picks them up ──────
os.environ["FIRESTORE_EMULATOR_HOST"] = "127.0.0.1:8089"
os.environ["GCP_PROJECT_ID"] = "shiftready-test"
os.environ["GCP_UPLOAD_BUCKET"] = "test-bucket"
os.environ["GCP_SERVICE_ACCOUNT"] = "test@test.iam.gserviceaccount.com"
os.environ.pop("K_SERVICE", None)  # absence enables dev-token auth bypass

import pytest
import httpx
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import AsyncClient
from httpx_ws.transport import ASGIWebSocketTransport
from google.cloud import firestore as fs_lib

# ── Windows async fix (mirrors root conftest) ─────────────────────────────────
if sys.platform == "win32":
    import asyncio

    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# ── Patch google.auth.default BEFORE app.services is imported ─────────────────
# services/__init__.py calls load_dotenv() then GCSUtils() which calls
# google.auth.default(). If GOOGLE_APPLICATION_CREDENTIALS points at a missing
# file (common in worktrees), that raises DefaultCredentialsError.
# Starting the patcher here — before any fixture runs — intercepts the call.
_mock_gcp_creds = MagicMock()
_auth_patcher = patch(
    "google.auth.default", return_value=(_mock_gcp_creds, "shiftready-test")
)
_auth_patcher.start()

# storage.Client validates credentials.universe_domain against "googleapis.com".
# Patching the whole class avoids that check and keeps GCSUtils.__init__ clean.
_storage_patcher = patch("google.cloud.storage.Client")
_storage_patcher.start()


# ─────────────────────────────────────────────────────────────────────────────
# Override the root conftest's autouse mock_services.
# Integration tests use a real Firestore emulator — no patching of firestore_svc.
# GCS and Gemini are handled separately in mock_external_services below.
# ─────────────────────────────────────────────────────────────────────────────
@pytest.fixture(autouse=True)
def mock_services():
    """No-op override: integration tests use the real Firestore emulator."""
    yield {}


# ─────────────────────────────────────────────────────────────────────────────
# Session-level: mock GCS (no bucket) and Gemini (paid/slow AI).
# Returns the mock objects so individual tests can configure return values.
# ─────────────────────────────────────────────────────────────────────────────
@pytest.fixture(scope="session", autouse=True)
def mock_external_services():
    from app.services import gcs_utils, gemini_processor

    with (
        patch.object(
            gcs_utils, "generate_upload_url", return_value="https://mock-gcs/upload"
        ) as mock_upload,
        patch.object(
            gcs_utils, "generate_download_url", return_value="https://mock-gcs/video"
        ) as mock_download,
        patch.object(
            gemini_processor, "process_walkthrough", new_callable=AsyncMock
        ) as mock_extract,
        patch.object(
            gemini_processor, "estimate_listing_prices", new_callable=AsyncMock
        ) as mock_price,
    ):
        # Safe defaults — tests that don't care about AI output get empty results
        mock_extract.return_value = ([], {"model": "test", "status": "success"})
        mock_price.return_value = ([], {"model": "test", "status": "success"})

        yield {
            "gcs_upload": mock_upload,
            "gcs_download": mock_download,
            "extract": mock_extract,
            "price": mock_price,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Reinitialise the Firestore AsyncClient on the TEST event loop.
#
# firestore.AsyncClient (and its gRPC channel) is created at module-import time
# (services/__init__.py) before any asyncio event loop is running.  gRPC binds
# to the loop that was current at creation time, so subsequent calls fail with
# "Event loop is closed" once pytest-asyncio's own loop starts.
# Replacing the client inside an async session fixture ensures it is bound to
# the correct, running loop from the very first test.
# ─────────────────────────────────────────────────────────────────────────────
@pytest.fixture(autouse=True)
async def reinit_firestore():
    """
    Replace firestore_svc and all its repos with a fresh AsyncClient bound to
    THIS test's event loop.  pytest-asyncio 1.x gives each test function its
    own loop, so the gRPC channel must be created here — not at session scope
    — to avoid "Future attached to a different loop" errors.
    _wire() rebuilds every repo against the new client in one call.

    Also re-binds messaging_svc.convs/notifs to the newly-wired repos so that
    messaging integration tests use the same emulator-backed client.
    """
    from app.services import firestore_svc, messaging_svc

    firestore_svc._wire(fs_lib.AsyncClient(project="shiftready-test"))
    messaging_svc.convs = firestore_svc.conversations
    messaging_svc.notifs = firestore_svc.notifications
    yield


# ─────────────────────────────────────────────────────────────────────────────
# FastAPI async test client — function-scoped so it binds to the same event
# loop as each test function.
#
# We manually enter the transport and call aclose() (a no-op on ASGITransport)
# instead of using the async context manager, because ASGIWebSocketTransport
# __aexit__ destroys an anyio TaskGroup that must be exited in the same task
# it was created in — pytest-asyncio 1.x runs fixture teardown in a different
# task, which causes "cancel scope in a different task" RuntimeErrors.
# The event loop teardown at the end of each test cancels any lingering tasks.
# ─────────────────────────────────────────────────────────────────────────────
@pytest.fixture
async def client():
    from app.main import app

    transport = ASGIWebSocketTransport(app=app)
    await transport.__aenter__()
    c = AsyncClient(transport=transport, base_url="http://test")
    yield c
    await c.aclose()


# ─────────────────────────────────────────────────────────────────────────────
# Direct Firestore client for test seeding & assertion (bypasses the API).
# Function-scoped so gRPC binds to the current test's event loop.
# ─────────────────────────────────────────────────────────────────────────────
@pytest.fixture
async def fsdb():
    return fs_lib.AsyncClient(project="shiftready-test")


# ─────────────────────────────────────────────────────────────────────────────
# Wipe emulator state + reset AI mocks between every test (function scope).
# Uses the emulator's admin REST endpoint — one call clears everything.
# ─────────────────────────────────────────────────────────────────────────────
@pytest.fixture(autouse=True)
async def clean_db(mock_external_services):
    yield
    # 1. Reset Gemini mocks to safe defaults so tests don't bleed into each other
    mock_external_services["extract"].reset_mock(return_value=False, side_effect=False)
    mock_external_services["extract"].return_value = (
        [],
        {"model": "test", "status": "success"},
    )
    mock_external_services["extract"].side_effect = None
    mock_external_services["price"].reset_mock(return_value=False, side_effect=False)
    mock_external_services["price"].return_value = (
        [],
        {"model": "test", "status": "success"},
    )
    mock_external_services["price"].side_effect = None

    # 2. Wipe all Firestore data via the emulator admin API
    async with httpx.AsyncClient() as hc:
        await hc.delete(
            "http://127.0.0.1:8089/emulator/v1/projects/shiftready-test"
            "/databases/(default)/documents"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Helpers used across test modules
# ─────────────────────────────────────────────────────────────────────────────
USER_A = "dev_user_alpha"
USER_B = "dev_user_beta"
SELLER = "dev_seller_ace"


def auth(user_id: str) -> dict:
    """Returns Authorization header dict for a dev-token user."""
    return {"Authorization": f"Bearer {user_id}"}


async def init_sale(client, user_id: str = USER_A, filename: str = "walk.mp4") -> str:
    """Helper: initialise a capture sale and return the event_id."""
    r = await client.post(
        "/api/v1/sales/init-capture",
        headers=auth(user_id),
    )
    assert r.status_code == 200, r.text
    return r.json()["event_id"]


async def add_bundle_with_item(
    client,
    event_id: str,
    user_id: str = USER_A,
    bundle_name: str = "Living Room",
    item_name: str = "Velvet Sofa",
    actual_listing_price: float = 500.0,
) -> tuple[str, str]:
    """Helper: add a bundle with one item, return (bundle_id, item_id)."""
    r = await client.post(
        f"/api/v1/sales/{event_id}/bundles",
        json={"name": bundle_name},
        headers=auth(user_id),
    )
    assert r.status_code == 200, r.text
    bundle_id = r.json()["bundle_id"]

    r = await client.post(
        f"/api/v1/sales/{event_id}/bundles/{bundle_id}/items",
        json={
            "name": item_name,
            "brand": "West Elm",
            "condition": "Excellent",
            "actual_listing_price": actual_listing_price,
            "actual_original_price": 1200.0,
            "actual_year_of_purchase": 2023,
        },
        headers=auth(user_id),
    )
    assert r.status_code == 200, r.text
    item_id = r.json()["item_id"]
    return bundle_id, item_id

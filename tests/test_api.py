from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_read_root():
    """Verify the base endpoint is accessible."""
    response = client.get("/")
    assert response.status_code == 200
    assert "ShiftReady API is live" in response.json()["message"]


def test_health_check():
    """Health endpoint returns 200 with expected keys (Firestore may be degraded in test env)."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert data["status"] in ("operational", "degraded")
    assert "checks" in data
    assert "version" in data


def test_sales_init_capture_unauthorized():
    """Auth guard on init-capture returns 401 when no token provided."""
    response = client.post("/api/v1/sales/init-capture")
    assert response.status_code == 401
    assert "Missing authentication token" in response.json()["detail"]

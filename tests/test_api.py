from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_read_root():
    """Verify the base endpoint is accessible."""
    response = client.get("/")
    assert response.status_code == 200
    assert "ShiftReady API is live" in response.json()["message"]

def test_health_check():
    """Verify the health check used by Cloud Run is functional."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "operational"

def test_sales_init_unauthorized():
    """
    Verify that security dependencies are active.
    Should return 401 because no Bearer token is provided.
    """
    response = client.post(
        "/api/v1/sales/init",
        json={"filename": "walkthrough.mp4"}
    )
    assert response.status_code == 401
    assert "Missing authentication token" in response.json()["detail"]

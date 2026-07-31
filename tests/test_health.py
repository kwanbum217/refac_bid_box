from fastapi.testclient import TestClient
from src.app.main import app

client = TestClient(app)


def test_root():
    response = client.get("/")
    assert response.status_code == 200
    assert "refac_bid_box" in response.json()["message"]


def test_health():
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["framework"] == "FastAPI (ASGI)"

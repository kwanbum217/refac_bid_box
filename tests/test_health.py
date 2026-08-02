from fastapi.testclient import TestClient

from src.app.main import app

client = TestClient(app)


def test_root():
    """루트는 원본과 동일하게 로그인이 필요한 홈 화면(SSR)이다."""
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/accounts/login/?next=/"


def test_health():
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["framework"] == "FastAPI (ASGI)"

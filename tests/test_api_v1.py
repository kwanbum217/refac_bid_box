import os

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("SKIP_MODEL_LOAD", "true")

from src.app.main import app

client = TestClient(app)


def test_predict_endpoint():
    payload = {
        "presumed_price": 500000000,
        "base_price": 495000000,
        "category_code": "Thng",
    }
    response = client.post("/api/v1/predictions/predict", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["predicted_price"] > 0
    assert "features_used" in data
    assert len(data["features_used"]) > 5


def test_chatbot_query_endpoint():
    payload = {"query": "적격심사 감점 요인이 무엇인가요?", "stream": False}
    response = client.post("/api/v1/chatbot/query", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["query"] == payload["query"]
    assert data["response"]
    assert "latency_ms" in data


def test_chatbot_stream_endpoint():
    response = client.get("/api/v1/chatbot/stream?query=적격심사")
    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]
    assert "data:" in response.text


def test_ui_dashboard():
    """대시보드는 원본 경로 /dashboard/ 로 이식되었고 로그인을 요구한다."""
    response = client.get("/dashboard/", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/accounts/login/?next=/dashboard/"


@pytest.mark.skipif(
    not (os.getenv("RUN_MODEL_TESTS") == "1"),
    reason="RUN_MODEL_TESTS=1 필요 (무거운 joblib 로드)",
)
def test_predict_with_real_models():
    os.environ["SKIP_MODEL_LOAD"] = "false"
    from importlib import reload

    import src.ml.predictor as predictor_mod

    reload(predictor_mod)
    payload = {
        "presumed_price": 500000000,
        "base_price": 495000000,
        "category_code": "Thng",
        "title": "사무용품 구매",
        "dminstt_nm": "조달청",
    }
    result = predictor_mod.predictor.predict(payload)
    assert result["model_version"] != "fallback"
    assert 75 < result["predicted_rate"] < 105

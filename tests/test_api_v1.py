from fastapi.testclient import TestClient
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
    assert "predicted_price" in data
    assert "features_used" in data
    assert data["model_version"] == "quantum_leap_v25_pro"


def test_chatbot_query_endpoint():
    payload = {
        "query": "낙찰 상한선 기준이 어떻게 되나요?",
        "stream": False,
    }
    response = client.post("/api/v1/chatbot/query", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["query"] == payload["query"]
    assert "retrieved_docs" in data
    assert len(data["retrieved_docs"]) > 0

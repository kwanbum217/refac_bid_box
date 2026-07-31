import json
from fastapi.testclient import TestClient
from src.app.main import app

client = TestClient(app)


def test_e2e_full_flow():
    # 1. 헬스체크
    res_health = client.get("/api/v1/health")
    assert res_health.status_code == 200
    assert res_health.json()["status"] == "healthy"

    # 2. AI 예측 API
    payload_pred = {"presumed_price": 600000000, "base_price": 590000000, "category_code": "Servc"}
    res_pred = client.post("/api/v1/predictions/predict", json=payload_pred)
    assert res_pred.status_code == 200
    assert res_pred.json()["predicted_price"] > 0

    # 3. RAG 챗봇 API
    payload_chat = {"query": "적격심사 감점 요인이 무엇인가요?"}
    res_chat = client.post("/api/v1/chatbot/query", json=payload_chat)
    assert res_chat.status_code == 200
    assert len(res_chat.json()["retrieved_docs"]) > 0

    # 4. SSE 챗봇 스트리밍 API
    res_stream = client.get("/api/v1/chatbot/stream?query=적격심사")
    assert res_stream.status_code == 200
    assert "text/event-stream" in res_stream.headers["content-type"]

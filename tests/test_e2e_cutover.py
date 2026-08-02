import os

os.environ.setdefault("SKIP_MODEL_LOAD", "true")

from fastapi.testclient import TestClient

from src.app.main import app

client = TestClient(app)


def test_e2e_full_flow():
    res_health = client.get("/api/v1/health")
    assert res_health.status_code == 200
    assert res_health.json()["status"] == "healthy"

    payload_pred = {"presumed_price": 600000000, "base_price": 590000000, "category_code": "Servc"}
    res_pred = client.post("/api/v1/predictions/predict", json=payload_pred)
    assert res_pred.status_code == 200
    assert res_pred.json()["predicted_price"] > 0

    payload_chat = {"query": "적격심사 감점 요인이 무엇인가요?"}
    res_chat = client.post("/api/v1/chatbot/query", json=payload_chat)
    assert res_chat.status_code == 200
    assert res_chat.json()["response"]

    res_stream = client.get("/api/v1/chatbot/stream?query=적격심사")
    assert res_stream.status_code == 200
    assert "text/event-stream" in res_stream.headers["content-type"]

    # 챗봇 화면은 원본 경로 /chat/ 로 이식되었고 로그인을 요구한다.
    res_ui = client.get("/chat/", follow_redirects=False)
    assert res_ui.status_code == 303
    assert res_ui.headers["location"] == "/accounts/login/?next=/chat/"

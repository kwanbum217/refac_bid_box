"""tests/test_backend_rest_fixes.py

2026-11-06 백엔드 API 감사 잔여 항목의 계약 시험입니다.

- API-01: SSE final 의 provenance 가 비스트리밍 /chat 과 같은 구조로 채워진다.
- A10: 특징 직접 입력 예측이 공고일시(선택)를 받아 시점 특징에 쓰고 기준을 응답에 남긴다.
- VAL-01: 수집 API 의 fetch_type·날짜가 잘못되면 422 로 거절한다.
- TEST-01: use_sql 질의에서 스트림·비스트림의 구조화 근거 포함 여부가 같다.
- TEST-02: 공고 JSON 상세 성공 응답의 계약이 유지된다.
- DEBT-01: 모든 역량 executor 경로가 실제 함수로 해석된다.
- DEBT-02: 시험에서만 쓰던 get_top_industry_choices 가 제거되었다.
"""

from __future__ import annotations

import importlib
import json
from types import SimpleNamespace
from typing import Any

from src.app.api.v1 import bids as bids_api
from src.app.api.v1 import chatbot as chatbot_mod
from src.app.api.v1 import predictions as predictions_mod
from src.app.core.timeutil import utcnow
from src.app.main import app
from src.app.models.bids import BidAnnouncement, BidResult
from src.app.services import bid_queries
from src.app.services.capability_registry import CAPABILITY_REGISTRY
from src.app.services.planner import plan_chat_request
from src.ml.features import build_feature_dict
from src.rag.answer_format import _build_evidence_items
from src.rag.query_planning import build_retrieval_plan
from src.rag.schemas import Provenance

CHAT_URL = "/api/v1/chatbot/chat"
STREAM_URL = "/api/v1/chatbot/chat/stream"
SQL_QUESTION = "최근 30일 서울 공고의 낙찰률 추세를 보여줘"
TRACE_ID = "rag-stream-parity"
KB_STATUS = {"updated_at": "2026-11-01T00:00:00", "kb_version": "2026-11-01"}


def _structured_data() -> dict[str, Any]:
    return {
        "summary": {
            "total_count": 3,
            "avg_rate": 88.1,
            "sample_announcements": [{"bid_ntce_no": "A-1", "bid_ntce_nm": "시험 공고"}],
            "recent_results": [{"bid_ntce_no": "A-1", "sucsfbid_rate": 88.1}],
        },
        "filters": {"institution_name": "서울"},
        "insufficiency_hints": [],
    }


def _vector_docs() -> list[dict[str, Any]]:
    return [{"document": "시험 근거 문서", "metadata": {"bid_ntce_no": "A-1"}, "distance": 0.1}]


def _tool_context() -> dict[str, Any]:
    return {
        "tool_results": {
            "bid_query": {"result": _structured_data()},
            "semantic_search": {"documents": _vector_docs()},
        }
    }


def _pending_answer() -> chatbot_mod._PendingRagAnswer:
    return chatbot_mod._PendingRagAnswer(
        message=SQL_QUESTION,
        session_key="provenance-parity",
        history=[],
        kb_status=dict(KB_STATUS),
        plan=plan_chat_request(SQL_QUESTION),
        tool_context=_tool_context(),
        user_id=None,
    )


def _expected_provenance() -> Provenance:
    return Provenance(
        trace_id=TRACE_ID,
        retrieval_mode=build_retrieval_plan(SQL_QUESTION).route_reason,
        items=_build_evidence_items(_structured_data(), _vector_docs(), KB_STATUS),
        insufficiency_hints=list(build_retrieval_plan(SQL_QUESTION).insufficiency_hints),
        kb_version=str(KB_STATUS["updated_at"]),
        vector_filter_provenance=None,
    )


def _parse_sse(text: str) -> list[tuple[str, dict[str, Any]]]:
    events: list[tuple[str, dict[str, Any]]] = []
    for chunk in text.split("\n\n"):
        if not chunk.strip():
            continue
        name = "message"
        data_lines: list[str] = []
        for line in chunk.split("\n"):
            if line.startswith("event:"):
                name = line[6:].strip()
            elif line.startswith("data:"):
                data_lines.append(line[5:].strip())
        if data_lines:
            events.append((name, json.loads("\n".join(data_lines))))
    return events


def _stream_final(events: list[tuple[str, dict[str, Any]]]) -> dict[str, Any]:
    return next(data for name, data in events if name == "final")


def _patch_chat_pipeline(monkeypatch, isolated_db) -> None:
    pending = _pending_answer()
    provenance = _expected_provenance()

    def fake_get_answer_sync(*args: Any, **kwargs: Any):
        return SimpleNamespace(answer="동일 근거", provenance=provenance, latency_ms=0.0)

    async def fake_stream_tokens(
        user_query: str,
        db: Any = None,
        history: list[dict] | None = None,
        tool_context: dict | None = None,
    ):
        yield {"type": "docs", "docs": _vector_docs()}
        yield {"type": "token", "text": "동일 근거"}
        yield {
            "type": "done",
            "citations": [],
            "trace_id": TRACE_ID,
            "final_answer": "동일 근거",
        }

    monkeypatch.setattr(chatbot_mod, "enforce_anonymous_api_quota", lambda *a, **k: None)
    monkeypatch.setattr(chatbot_mod, "_prepare_chat", lambda db, payload, user_id=None: pending)
    monkeypatch.setattr(chatbot_mod, "_prepare_chat_sync", lambda payload, uid: pending)
    monkeypatch.setattr(chatbot_mod, "open_thread_session", lambda: (isolated_db, False))
    monkeypatch.setattr(chatbot_mod.rag_engine, "get_answer_sync", fake_get_answer_sync)
    monkeypatch.setattr(chatbot_mod.rag_engine, "stream_tokens", fake_stream_tokens)


def test_stream_final_provenance_matches_non_stream_contract(client, isolated_db, monkeypatch):
    """API-01·TEST-01: 스트림 final 도 비스트림과 같은 provenance 구조를 싣는다."""
    _patch_chat_pipeline(monkeypatch, isolated_db)

    plain = client.post(CHAT_URL, json={"message": SQL_QUESTION}).json()
    events = _parse_sse(client.post(STREAM_URL, json={"message": SQL_QUESTION}).text)
    streamed = _stream_final(events)

    assert streamed["provenance"] is not None
    assert set(streamed["provenance"]) == set(plain["provenance"])
    assert streamed["provenance"]["trace_id"] == plain["provenance"]["trace_id"]

    stream_types = {item["type"] for item in streamed["provenance"]["items"]}
    plain_types = {item["type"] for item in plain["provenance"]["items"]}
    assert "sql_stats" in plain_types
    assert stream_types == plain_types


def test_predict_accepts_bid_ntce_dt_and_reports_time_basis(client, monkeypatch):
    """A10: 공고일시를 주면 그 시각 기준으로 특징을 만들고 기준을 응답에 남긴다."""
    captured: dict[str, Any] = {}

    def fake_predict(
        request_data: dict[str, Any], model_id: str | None = None, session: Any = None
    ):
        captured["request_data"] = request_data
        return {
            "predicted_price": 1000.0,
            "predicted_rate": 90.0,
            "model_version": "test",
            "features_used": {},
        }

    monkeypatch.setattr(predictions_mod, "enforce_anonymous_api_quota", lambda *a, **k: None)
    monkeypatch.setattr(predictions_mod.predictor, "predict", fake_predict)

    response = client.post(
        "/api/v1/predictions/predict",
        json={
            "presumed_price": 100000000,
            "base_price": 110000000,
            "bid_ntce_dt": "2024-01-02T10:00:00",
        },
    )

    assert response.status_code == 200
    assert captured["request_data"]["bid_ntce_dt"] is not None
    assert response.json()["feature_time_basis"] == "bid_ntce_dt"


def test_predict_without_bid_ntce_dt_keeps_request_time_basis(client, monkeypatch):
    """A10: 공고일시가 없으면 지금처럼 요청 시각 기준이고 그 사유를 응답에 남긴다."""
    captured: dict[str, Any] = {}

    def fake_predict(
        request_data: dict[str, Any], model_id: str | None = None, session: Any = None
    ):
        captured["request_data"] = request_data
        return {
            "predicted_price": 1000.0,
            "predicted_rate": 90.0,
            "model_version": "test",
            "features_used": {},
        }

    monkeypatch.setattr(predictions_mod, "enforce_anonymous_api_quota", lambda *a, **k: None)
    monkeypatch.setattr(predictions_mod.predictor, "predict", fake_predict)

    response = client.post(
        "/api/v1/predictions/predict",
        json={"presumed_price": 100000000, "base_price": 110000000},
    )

    assert response.status_code == 200
    assert captured["request_data"]["bid_ntce_dt"] is None
    assert response.json()["feature_time_basis"] == "request_time"


def test_bid_ntce_dt_feeds_time_features():
    """A10: 공고일시가 있으면 레짐·월 특징이 요청 시각이 아니라 그 시각 기준이다."""
    base = {"presumed_price": 100000000, "base_price": 110000000, "category_code": "Thng"}

    without_dt = build_feature_dict(dict(base), None)
    with_dt = build_feature_dict({**base, "bid_ntce_dt": "2024-01-02T10:00:00"}, None)

    assert without_dt["is_post_regime_shift"] == 1.0
    assert with_dt["is_post_regime_shift"] == 0.0
    assert with_dt["month"] != without_dt["month"]


def test_collect_rejects_unknown_fetch_type(client, isolated_db):
    """VAL-01: fetch_type 오타는 수집을 건너뛰고 200 success 를 주지 않는다."""
    app.dependency_overrides[bids_api.require_current_user] = lambda: SimpleNamespace(
        id=1, is_staff=True, is_superuser=True
    )
    try:
        response = client.post("/api/v1/bids/collect", params={"fetch_type": "annouce"})
    finally:
        app.dependency_overrides.pop(bids_api.require_current_user, None)

    assert response.status_code == 422


def test_collect_rejects_malformed_date(client, isolated_db):
    """VAL-01: 날짜가 YYYYMMDD 가 아니면 외부 API 로 넘기지 않고 422 로 거절한다."""
    app.dependency_overrides[bids_api.require_current_user] = lambda: SimpleNamespace(
        id=1, is_staff=True, is_superuser=True
    )
    try:
        response = client.post("/api/v1/bids/collect", params={"start_date": "abc"})
    finally:
        app.dependency_overrides.pop(bids_api.require_current_user, None)

    assert response.status_code == 422


def _make_announcement(**overrides: Any) -> BidAnnouncement:
    defaults = {
        "bid_ntce_no": "DETAIL-TEST-1",
        "bid_ntce_ord": "000",
        "bid_ntce_nm": "상세 계약 시험 공고",
        "dminstt_nm": "시험 발주기관",
        "base_amount": 110000000,
        "presmpt_prce": 100000000,
        "bid_ntce_dt": utcnow(),
        "category": "Thng",
        "raw_data": None,
    }
    defaults.update(overrides)
    return BidAnnouncement(**defaults)


def test_bid_detail_json_success_contract(client, isolated_db):
    """TEST-02: 공고 상세 라우트가 직렬화·유사 공고·과거 낙찰 계약을 지킨다."""
    bid = _make_announcement()
    similar = _make_announcement(
        bid_ntce_no="DETAIL-TEST-2",
        bid_ntce_nm="유사 공고",
    )
    result = BidResult(
        bid_ntce_no="DETAIL-TEST-1",
        bid_ntce_ord="000",
        bid_ntce_nm="상세 계약 시험 공고",
        bidwinnr_nm="시험 업체",
        sucsf_bid_amt=95000000,
        sucsf_bid_rate=95.0,
        rl_openg_dt=utcnow(),
        dminstt_nm="시험 발주기관",
        category="Thng",
    )
    isolated_db.add_all([bid, similar, result])
    isolated_db.commit()
    isolated_db.refresh(bid)
    isolated_db.refresh(similar)
    isolated_db.refresh(result)

    response = client.get(f"/api/v1/bids/{bid.id}")

    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {"bid", "similar_bids", "past_results", "default_prediction_model"}
    assert payload["bid"]["id"] == bid.id
    assert payload["bid"]["bid_ntce_no"] == "DETAIL-TEST-1"
    assert any(item["id"] == similar.id for item in payload["similar_bids"])
    assert any(item["id"] == result.id for item in payload["past_results"])
    assert payload["default_prediction_model"]


def test_capability_executor_paths_resolve():
    """DEBT-01: 역량 레지스트리의 executor 문자열이 모두 실제 함수로 해석된다."""
    for name, capability in CAPABILITY_REGISTRY.items():
        module_path, _, attribute = capability.executor.rpartition(".")
        module = importlib.import_module(module_path)
        assert callable(getattr(module, attribute)), f"{name}: {capability.executor}"


def test_test_only_industry_choice_helper_is_removed():
    """DEBT-02: 시험에서만 쓰던 전량 적재 헬퍼가 남아 있지 않다."""
    assert not hasattr(bid_queries, "get_top_industry_choices")

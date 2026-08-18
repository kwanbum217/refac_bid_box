"""
tests/test_chatbot_prediction.py

원본 apps/chatbot/tests.py ChatAutomationApiTests 중 예측/답변 계약 이식.

예측 값 자체가 아니라 "자연어 요청이 예측 도구로 라우팅되고, 결과가 원본과 같은
마크다운 계약으로 렌더링되는가" 를 봅니다. 모델 추론은 원본과 동일하게 mock 합니다.

A4 교정: bid_prediction_tool 이 predict_optimal_price_with_provenance 를 사용하므로
mock 대상이 PredictionOutcome 을 돌려주도록 변경합니다.
"""

from datetime import timedelta
from unittest.mock import patch

from src.app.core.timeutil import utcnow
from src.app.models.bids import BidAnnouncement
from src.app.models.chatbot import ChatSessionState, KnowledgeBaseStatus
from src.ml.model_registry import PredictionOutcome
from src.rag.schemas import AnswerBundle, Provenance

VALID_SIGNUP = {
    "username": "chat-pred-user",
    "password1": "StrongPass123!!",
    "password2": "StrongPass123!!",
    "nickname": "테스터",
    "email": "chat-pred@example.com",
    "birth_date": "1999-05-17",
    "gender": "F",
    "agree_terms": True,
    "agree_privacy": True,
}

PROVENANCE_TARGET = (
    "src.app.services.tools.bid_prediction_tool.predict_optimal_price_with_provenance"
)
REGISTRY_TARGET = "src.app.services.tools.bid_prediction_tool.ModelRegistry.get_model"
CLASSIFY_TARGET = "src.app.services.tools.bid_prediction_tool.classify_price_decision_method"
PLAN_EXEC_TARGET = "src.app.api.v1.chatbot.execute_plan_steps"
RAG_TARGET = "src.app.api.v1.chatbot.rag_engine.get_answer_sync"


class DummyWrapper:
    """원본 테스트의 DummyWrapper 대응."""

    def get_display_name(self):
        return "V25 테스트 모델"


def _login(client) -> int:
    signup = client.post("/api/v1/accounts/signup", json=VALID_SIGNUP)
    client.post(
        "/api/v1/accounts/login",
        json={"username": "chat-pred-user", "password": "StrongPass123!!"},
    )
    return signup.json()["id"]


def _seed_kb_status(db, **overrides) -> KnowledgeBaseStatus:
    payload = {
        "kb_version": "bidding_kb",
        "status": "ready",
        "source_bid_count": 321,
        "last_pipeline_run_id": "exec_002",
        "updated_at": utcnow(),
    }
    payload.update(overrides)
    kb = KnowledgeBaseStatus(**payload)
    db.add(kb)
    db.commit()
    return kb


def _seed_bid(db, index: int = 0, **overrides) -> BidAnnouncement:
    now = utcnow()
    payload = {
        "bid_ntce_nm": f"최근 물품 공고 {index + 1}",
        "bid_ntce_no": f"BID-GOODS-{index + 1:03d}",
        "bid_ntce_ord": "000",
        "ntce_instt_nm": "테스트 공고기관",
        "dminstt_nm": "테스트 수요기관",
        "base_amount": 100000000 + (index * 1000000),
        "presmpt_prce": 90000000,
        "bid_ntce_dt": now + timedelta(minutes=index),
        "bid_clse_dt": now,
        "openg_dt": now,
        "category": "Thng",
        "collected_at": now + timedelta(minutes=index),
    }
    payload.update(overrides)
    bid = BidAnnouncement(**payload)
    db.add(bid)
    db.commit()
    return bid


def _chat(client, message: str, **extra):
    return client.post("/api/v1/chatbot/chat", json={"message": message, **extra})


def _answer_bundle(*_args, **_kwargs) -> AnswerBundle:
    """원본은 get_chatbot_response 가 문자열을 돌려줬습니다.

    이식본은 근거(provenance)를 함께 실어 보내므로 최소 형태의 번들을 만듭니다.
    """
    return AnswerBundle(
        answer="기본 답변",
        provenance=Provenance(trace_id="test-trace", retrieval_mode="vector"),
    )


# --------------------------------------------------------------------------- #
# 투찰가 예측
# --------------------------------------------------------------------------- #


@patch(CLASSIFY_TARGET, return_value="복수예가")
@patch(REGISTRY_TARGET, return_value=DummyWrapper())
@patch(
    PROVENANCE_TARGET,
    return_value=PredictionOutcome(
        predicted_rate=0.973,
        requested_model="v25",
        actual_model="v25",
        fallback_used=False,
        fallback_reason=None,
    ),
)
def test_chat_predicts_latest_goods_bid_price_directly(
    mocked_provenance, mocked_get_model, mocked_classify, client, isolated_db
):
    """원본 test_chat_api_predicts_latest_goods_bid_price_directly 대응."""
    _login(client)
    _seed_kb_status(isolated_db)
    _seed_bid(isolated_db)

    payload = _chat(client, "v25 모델로 최근에 수집된 물품 공고 투찰가 예측해줘").json()
    assert payload["mode"] == "answer"
    assert payload["intent"] == "prediction_query"
    assert "### 투찰가 예측 결과" in payload["answer"]
    assert "추천 투찰가" in payload["answer"]
    assert "97,300,000원" in payload["answer"]
    assert "V25 테스트 모델" in payload["answer"]
    assert payload["plan_steps"][0]["tool"] == "bid_prediction_tool"

    called_model_id, called_features = mocked_provenance.call_args.args
    assert called_model_id == "v25"
    assert called_features["category"] == "Thng"
    assert called_features["presmpt_prce"] == 100000000.0


@patch(CLASSIFY_TARGET, return_value="복수예가")
@patch(REGISTRY_TARGET, return_value=DummyWrapper())
@patch(
    PROVENANCE_TARGET,
    side_effect=[
        PredictionOutcome(
            predicted_rate=0.91, requested_model="v25", actual_model="v25", fallback_used=False
        ),
        PredictionOutcome(
            predicted_rate=0.92, requested_model="v25", actual_model="v25", fallback_used=False
        ),
        PredictionOutcome(
            predicted_rate=0.93, requested_model="v25", actual_model="v25", fallback_used=False
        ),
        PredictionOutcome(
            predicted_rate=0.94, requested_model="v25", actual_model="v25", fallback_used=False
        ),
        PredictionOutcome(
            predicted_rate=0.95, requested_model="v25", actual_model="v25", fallback_used=False
        ),
    ],
)
def test_chat_predicts_requested_count_of_latest_goods_bids(
    mocked_provenance, mocked_get_model, mocked_classify, client, isolated_db
):
    """원본 test_chat_api_predicts_requested_count_of_latest_goods_bids 대응.

    KB 가 30시간 낡은 상태이므로 답변 본문은 깨끗하되 advisory_signals 로만
    kb_refresh 를 알려야 합니다 (원본과 동일한 분리 규칙).
    """
    _login(client)
    _seed_kb_status(isolated_db, updated_at=utcnow() - timedelta(hours=30))
    for index in range(5):
        _seed_bid(isolated_db, index)

    payload = _chat(client, "v25 모델로 최근에 수집된 물품 공고 5개만 투찰가 예측해줘").json()
    assert payload["mode"] == "answer"
    assert payload["intent"] == "prediction_query"
    answer = payload["answer"]
    assert "### 투찰가 예측 결과" in answer
    assert "최근 수집된 물품 공고 **5건**" in answer
    assert "| # | 공고 | 수요기관 | 기초금액 | 예상 낙찰률 | 추천 투찰가 |" in answer
    assert "**최근 물품 공고" in answer
    assert "**V25 테스트 모델**" in answer
    assert "KB 최신화가" not in answer
    assert any(signal["action_key"] == "kb_refresh" for signal in payload["advisory_signals"])

    assert mocked_provenance.call_count == 5
    first_model_id, first_features = mocked_provenance.call_args_list[0].args
    assert first_model_id == "v25"
    assert first_features["category"] == "Thng"


# --------------------------------------------------------------------------- #
# 답변 모드 계약
# --------------------------------------------------------------------------- #


@patch(RAG_TARGET, side_effect=_answer_bundle)
@patch(PLAN_EXEC_TARGET)
def test_chat_answer_mode_includes_kb_status_and_tool_context(
    mocked_plan_steps, mocked_rag, client, isolated_db
):
    """원본 test_chat_api_answer_mode_includes_kb_status_and_tool_context 대응."""
    _login(client)
    _seed_kb_status(isolated_db)
    mocked_plan_steps.return_value = {
        "tool_results": {"semantic_search": {"document": "요약 문서"}},
        "visualizations": [
            {
                "type": "chart",
                "chart_type": "line",
                "title": "추세",
                "labels": ["1월"],
                "values": [98.1],
            }
        ],
    }

    payload = _chat(client, "최근 공고 특징 알려줘").json()
    assert payload["mode"] == "answer"
    assert payload["kb_status"]["source_bid_count"] == 321
    assert "기본 답변" in payload["answer"]
    assert "KB" in payload["answer"]
    assert payload["visualizations"]

    assert mocked_rag.call_args.args[0] == "최근 공고 특징 알려줘"
    tool_context = mocked_rag.call_args.kwargs["tool_context"]
    assert tool_context["tool_results"]["semantic_search"]["document"] == "요약 문서"


@patch(RAG_TARGET, side_effect=_answer_bundle)
@patch(PLAN_EXEC_TARGET)
def test_chat_persists_conversation_state_after_answer(
    mocked_plan_steps, mocked_rag, client, isolated_db
):
    """원본 test_chat_api_persists_conversation_state_after_answer 대응."""
    user_id = _login(client)
    _seed_kb_status(isolated_db)
    mocked_plan_steps.return_value = {
        "tool_results": {
            "bid_query": {
                "retrieval_plan": {"filters": {"institution_name": "서울"}},
                "result": {"summary": {"time_series": []}},
            }
        }
    }

    _chat(client, "최근 낙찰률 추세 알려줘")

    session_state = (
        isolated_db.query(ChatSessionState)
        .filter(
            ChatSessionState.user_id == user_id,
            ChatSessionState.session_key.not_like("user:%"),
        )
        .one()
    )
    assert session_state.last_query == "최근 낙찰률 추세 알려줘"
    assert session_state.last_plan_json["mode"] == "answer"
    assert session_state.last_filters_json["institution_name"] == "서울"

    user_state = isolated_db.query(ChatSessionState).filter_by(session_key=f"user:{user_id}").one()
    assert user_state.last_filters_json["institution_name"] == "서울"


@patch(RAG_TARGET, side_effect=_answer_bundle)
@patch(PLAN_EXEC_TARGET)
def test_chat_reuses_last_tool_results_for_result_followup(
    mocked_plan_steps, mocked_rag, client, isolated_db
):
    """원본 test_chat_api_reuses_last_tool_results_for_result_followup 대응.

    후속 질의는 직전 도구 결과를 실행 컨텍스트로 물려받아야 합니다.
    """
    user_id = _login(client)
    _seed_kb_status(isolated_db)
    trend_results = {
        "trend_analysis": {
            "series": [{"label": "2026-01", "value": 98.1, "volume": 4}],
            "direction": "flat",
            "summary_text": "최근 구간 변화가 크지 않습니다.",
        }
    }
    chart = {
        "type": "chart",
        "chart_type": "line",
        "title": "최근 낙찰률 추세",
        "labels": ["2026-01"],
        "values": [98.1],
    }
    isolated_db.add(
        ChatSessionState(
            session_key="session-followup-001",
            user_id=user_id,
            last_query="최근 낙찰률 추세를 보여줘",
            last_result_payload={"tool_results": trend_results},
            last_chart_payload=[chart],
        )
    )
    isolated_db.commit()
    mocked_plan_steps.return_value = {
        "tool_results": trend_results,
        "visualizations": [chart],
    }

    _chat(client, "그 차트 다시 보여줘", session_key="session-followup-001")

    execute_context = mocked_plan_steps.call_args.args[1]
    assert "tool_results" in execute_context
    assert "trend_analysis" in execute_context["tool_results"]
    assert execute_context["visualizations"]


@patch(RAG_TARGET, side_effect=_answer_bundle)
@patch(PLAN_EXEC_TARGET, return_value={})
def test_chat_answer_mode_includes_proactive_suggestions(
    mocked_plan_steps, mocked_rag, client, isolated_db
):
    """원본 test_chat_api_answer_mode_includes_proactive_suggestions 대응.

    운영 신호는 advisory_signals 로만 전달하고 답변 본문에는 섞지 않습니다.
    """
    _login(client)
    _seed_kb_status(
        isolated_db,
        source_bid_count=0,
        updated_at=utcnow() - timedelta(days=2),
    )

    payload = _chat(client, "최근 공고 특징 알려줘").json()
    assert payload["advisory_signals"]
    assert any("kb_refresh" in item for item in payload["suggestions"])
    assert "운영 제안" not in payload["answer"]
    for signal in payload["advisory_signals"]:
        assert signal["message"] not in payload["answer"]


# --------------------------------------------------------------------------- #
# 금액 없는 공고 회피
# --------------------------------------------------------------------------- #


def test_prediction_tool_skips_bids_without_amount(isolated_db):
    """가장 최근 공고라도 금액이 없으면 예측 후보에서 제외한다.

    NULL 만 거르면 presmpt_prce = 0 인 공고가 통과해 추천 투찰가가 0 원으로
    나옵니다. 실제로 외자 공고에서 기초금액 0 원, 추천 투찰가 0 원이 나왔습니다.
    """
    from src.app.services.tools.bid_prediction_tool import _latest_predictable_bids

    priced = _seed_bid(isolated_db, index=0)
    # 더 최근이지만 금액이 없는 공고
    _seed_bid(
        isolated_db,
        index=5,
        bid_ntce_no="BID-NO-AMOUNT",
        base_amount=None,
        presmpt_prce=0,
    )

    rows = _latest_predictable_bids(isolated_db, category="Thng", limit=1)

    assert [row.bid_ntce_no for row in rows] == [priced.bid_ntce_no]


def test_prediction_tool_skips_zero_budget_in_raw_data(isolated_db):
    """raw_data 예산이 0 이면 SQL 필터를 통과해도 후보에서 제외한다."""
    from src.app.services.tools.bid_prediction_tool import _latest_predictable_bids

    priced = _seed_bid(isolated_db, index=0)
    _seed_bid(
        isolated_db,
        index=5,
        bid_ntce_no="BID-ZERO-BUDGET",
        raw_data={"bdgtAmt": "0"},
    )

    rows = _latest_predictable_bids(isolated_db, category="Thng", limit=1)

    assert [row.bid_ntce_no for row in rows] == [priced.bid_ntce_no]


def test_prediction_tool_still_fills_requested_count(isolated_db):
    """금액 없는 건이 섞여도 요청한 건수를 채운다."""
    from src.app.services.tools.bid_prediction_tool import _latest_predictable_bids

    for index in range(3):
        _seed_bid(isolated_db, index=index)
    for index in range(3, 6):
        _seed_bid(
            isolated_db,
            index=index,
            bid_ntce_no=f"BID-EMPTY-{index}",
            base_amount=None,
            presmpt_prce=0,
        )

    rows = _latest_predictable_bids(isolated_db, category="Thng", limit=3)

    assert len(rows) == 3
    assert all(float(row.prediction_reference_amount or 0) > 0 for row in rows)

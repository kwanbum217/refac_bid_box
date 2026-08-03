"""
tests/test_chatbot_planner.py

원본 apps/chatbot/tests.py PlannerTests 이식.
챗봇 플래너의 의도 분류 및 계획 수립 규칙을 검증합니다.
"""

from unittest.mock import patch

from src.app.services.planner import plan_chat_request


def _context_state(
    base_message,
    *,
    filters=None,
    last_chart_payload=None,
    last_result_payload=None,
    last_tool_results=None,
):
    base_plan = plan_chat_request(base_message)
    return {
        "last_query": base_message,
        "last_plan_json": base_plan.model_dump(),
        "last_filters_json": filters or {},
        "last_result_summary": "",
        "last_chart_payload": last_chart_payload or [],
        "last_result_payload": last_result_payload or {},
        "last_tool_results": last_tool_results or {},
    }


def test_plan_data_refresh_with_graph_request():
    plan = plan_chat_request("오늘 데이터 갱신해서 그래프 보여줘")
    assert plan.mode == "action"
    assert plan.primary_action_key == "data_refresh"
    assert plan.followup_after_completion
    assert plan.steps[0].kind == "pipeline"
    assert plan.steps[0].tool == "data_refresh"


def test_plan_full_validation_requires_confirmation():
    plan = plan_chat_request("전체 점검해줘")
    assert plan.primary_action_key == "full_validation"
    assert plan.requires_confirmation
    assert plan.steps[0].requires_confirmation


def test_plan_full_validation_after_answer_keeps_current_request_as_followup():
    context_state = _context_state("최근 서울 지역 용역 공고 흐름 알려줘")
    plan = plan_chat_request("전체 점검해줘", context_state=context_state)
    assert plan.primary_action_key == "full_validation"
    assert plan.followup_query == "전체 점검해줘"


def test_plan_progress_status_request_uses_automation_status_tool():
    plan = plan_chat_request("현재 점검 진행 상황 알려줘")
    assert plan.mode == "answer"
    assert plan.intent_type == "automation_status"
    assert plan.steps[0].tool == "automation_status_tool"
    assert not plan.steps[0].mutating


def test_plan_recent_result_graph_request_prefers_status_visualization():
    context_state = _context_state("전체 점검해줘")
    context_state["last_job_id"] = "job-123"

    plan = plan_chat_request("방금 결과를 그래프로 보여줘", context_state=context_state)

    assert plan.mode == "answer"
    assert plan.intent_type == "automation_status"
    assert plan.response_mode == "visual"
    assert plan.steps[0].tool == "automation_status_tool"
    assert plan.steps[0].params["prefer_visualization"]


def test_plan_prediction_request_with_collected_context_uses_prediction_tool():
    plan = plan_chat_request("v25 모델로 최근에 수집된 물품 공고 투찰가 예측해줘")
    assert plan.mode == "answer"
    assert plan.intent_type == "prediction_query"
    assert plan.steps[0].tool == "bid_prediction_tool"
    assert plan.steps[0].params["category"] == "Thng"
    assert plan.steps[0].params["model_id"] == "v25"
    assert plan.steps[0].params["limit"] == 1
    assert not plan.steps[0].mutating


def test_plan_prediction_request_extracts_requested_count():
    plan = plan_chat_request("v25 모델로 최근에 수집된 물품 공고 5개만 투찰가 예측해줘")
    assert plan.mode == "answer"
    assert plan.intent_type == "prediction_query"
    assert plan.steps[0].params["limit"] == 5
    assert plan.steps[0].params["model_id"] == "v25"


def test_plan_explicit_collection_request_still_uses_collect_only():
    plan = plan_chat_request("최신 입찰 데이터 수집해줘")
    assert plan.mode == "action"
    assert plan.primary_action_key == "collect_refresh"
    assert plan.steps[0].params["run_mode"] == "collect_only"


def test_plan_advisory_request():
    plan = plan_chat_request("매일 아침 신규 공고 요약 보내줘")
    assert plan.mode == "advisory"
    assert plan.intent_type == "create_scheduled_report"
    assert plan.steps[0].kind == "advisory"


def test_plan_statistics_answer_uses_bid_query_tool():
    plan = plan_chat_request("낙찰률 추세 비교해줘")
    assert plan.mode == "answer"
    assert plan.intent_type == "statistics_query"
    assert plan.steps[0].tool == "bid_query_tool"
    assert "trend_analyzer" in [step.tool for step in plan.steps]
    assert "chart_builder" in [step.tool for step in plan.steps]


def test_plan_result_list_request_uses_bid_query_tool():
    plan = plan_chat_request("최근 낙찰된 용역 사업 5개만 리스트 해봐라")
    assert plan.mode == "answer"
    assert plan.intent_type == "statistics_query"
    assert plan.steps[0].tool == "bid_query_tool"
    assert plan.steps[0].params["category"] == "Servc"
    assert plan.steps[0].params["limit"] == 5


def test_plan_hybrid_answer_uses_bid_and_semantic_tools():
    plan = plan_chat_request("최근 낙찰률 추세와 사례를 같이 알려줘")
    assert plan.mode == "answer"
    assert plan.steps[0].tool == "bid_query_tool"
    assert "trend_analyzer" in [step.tool for step in plan.steps]
    assert "chart_builder" in [step.tool for step in plan.steps]
    assert "semantic_search_tool" in [step.tool for step in plan.steps]


@patch("src.app.services.planner._request_llm_plan_draft")
def test_plan_llm_draft_feature_flag_off_keeps_rule_only(mocked_llm_request, monkeypatch):
    monkeypatch.setenv("CHATBOT_ENABLE_LLM_PLAN_DRAFT", "false")
    plan = plan_chat_request("최근 낙찰률 추세와 사례를 같이 알려줘")
    assert not plan.llm_draft_used
    mocked_llm_request.assert_not_called()


@patch("src.app.services.planner._request_llm_plan_draft")
def test_plan_invalid_llm_draft_falls_back_to_rule_based(mocked_llm_request, monkeypatch):
    monkeypatch.setenv("CHATBOT_ENABLE_LLM_PLAN_DRAFT", "true")
    mocked_llm_request.return_value = {
        "steps": [
            {
                "step_id": "s1",
                "kind": "internal_tool",
                "tool": "unknown_tool",
                "params": {},
                "output_key": "unknown",
            }
        ]
    }
    plan = plan_chat_request("최근 낙찰률 추세와 사례를 같이 알려줘")
    assert not plan.llm_draft_used
    assert plan.mode == "answer"
    assert plan.steps[0].tool == "bid_query_tool"


def test_followup_region_refines_previous_statistics_query():
    context_state = _context_state(
        "최근 1년 낙찰률 추세를 보여줘",
        filters={"date_from": "2026-01-01", "date_to": "2026-04-20"},
    )
    plan = plan_chat_request("서울만 다시", context_state=context_state)
    assert plan.mode == "answer"
    assert plan.steps[0].tool == "bid_query_tool"
    assert plan.steps[0].params["institution_name"] == "서울"
    assert plan.steps[0].params["date_from"] == "2026-01-01"


def test_followup_category_refines_previous_statistics_query():
    context_state = _context_state("최근 1년 입찰 통계를 보여줘")
    plan = plan_chat_request("용역만 다시", context_state=context_state)
    assert plan.mode == "answer"
    assert plan.steps[0].params["category"] == "Servc"


def test_followup_detail_promotes_to_hybrid_answer():
    context_state = _context_state("낙찰률 추세 비교해줘")
    plan = plan_chat_request("좀 더 자세히 설명해줘", context_state=context_state)
    assert plan.mode == "answer"
    assert plan.steps[0].tool == "bid_query_tool"
    assert "semantic_search_tool" in [step.tool for step in plan.steps]


def test_followup_chart_reuses_previous_query():
    context_state = _context_state("최근 1년 낙찰률 추세를 보여줘")
    plan = plan_chat_request("이번엔 차트로 보여줘", context_state=context_state)
    assert plan.mode == "answer"
    assert "차트" in plan.steps[0].params["query"]
    assert "chart_builder" in [step.tool for step in plan.steps]


def test_followup_chart_reuses_previous_result_object():
    context_state = _context_state(
        "최근 1년 낙찰률 추세를 보여줘",
        last_chart_payload=[
            {"type": "chart", "chart_type": "line", "title": "최근 낙찰률 추세", "labels": ["2026-01"], "values": [98.1]}
        ],
        last_tool_results={
            "trend_analysis": {
                "series": [{"label": "2026-01", "value": 98.1, "volume": 4}],
                "direction": "flat",
                "summary_text": "최근 구간 변화가 크지 않습니다.",
            }
        },
    )
    plan = plan_chat_request("그 차트 다시 보여줘", context_state=context_state)
    assert plan.mode == "answer"
    assert plan.reason == "conversation result-object followup refinement"
    assert plan.steps[0].tool == "chart_builder"


def test_followup_kb_refresh_escalates_to_action():
    context_state = _context_state("최근 낙찰률 추세와 사례를 알려줘")
    plan = plan_chat_request("KB 갱신 포함해서 다시 해줘", context_state=context_state)
    assert plan.mode == "action"
    assert plan.primary_action_key == "data_refresh"
    assert plan.followup_query == "최근 낙찰률 추세와 사례를 알려줘"

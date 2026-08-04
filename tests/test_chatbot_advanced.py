"""
tests/test_chatbot_advanced.py

원본 apps/chatbot/tests.py 중 InterpretationLayerTests, ResultPresenterTests,
AdvisoryEngineTests, StepExecutorTests 이식.
 - interpret_request / compile_plan: 의도 해석 및 계획 컴파일
 - build_visualizations / build_result_intelligence: 결과 시각화 및 인사이트
 - AdvisoryEngine: KB 신선도, 실패 감지, 우선순위 정렬
 - execute_internal_tool_step / execute_plan_steps: 스텝 실행기
"""

from datetime import timedelta
from unittest.mock import patch

from src.app.core.timeutil import utcnow
from src.app.models.chatbot import AutomationRequest, KnowledgeBaseStatus
from src.app.schemas.chat import ChatPlan, PlanStep
from src.app.services.advisory_engine import AdvisoryEngine
from src.app.services.plan_executor import execute_internal_tool_step, execute_plan_steps
from src.app.services.planner import compile_plan, interpret_request
from src.app.services.result_presenter import (
    build_result_intelligence,
    build_terminal_answer,
    build_visualizations,
)

# --------------------------------------------------------------------------- #
# InterpretationLayerTests
# --------------------------------------------------------------------------- #


def test_interpret_request_basic_answer():
    exec_plan = interpret_request("낙찰률 알려줘")
    assert exec_plan.query_type == "answer"
    assert "bid_query_tool" in exec_plan.requested_capabilities


def test_interpret_request_advisory():
    exec_plan = interpret_request("매일 아침 알림 설정해줘")
    assert exec_plan.query_type == "advisory"
    assert "subscription_advisory" in exec_plan.requested_capabilities


def test_interpret_request_action():
    exec_plan = interpret_request("데이터 갱신해줘")
    assert exec_plan.query_type == "action"
    assert "data_refresh" in exec_plan.requested_capabilities


def test_interpret_request_embedding_refresh_wording_routes_to_kb_refresh():
    exec_plan = interpret_request("현재 기준으로 임베딩을 최신화하여 업데이트해줘")
    assert exec_plan.query_type == "action"
    assert exec_plan.action_key == "kb_refresh"
    assert "kb_refresh" in exec_plan.requested_capabilities


def test_compile_plan_preserves_execution_metadata():
    exec_plan = interpret_request("낙찰률 추세 그래프로 보여줘")
    plan = compile_plan(exec_plan)
    assert plan.mode == "answer"
    assert "chart_builder" in [s.tool for s in plan.steps]
    assert plan.reason == exec_plan.reasoning


# --------------------------------------------------------------------------- #
# ResultPresenterTests (순수 함수)
# --------------------------------------------------------------------------- #


def test_build_visualizations_supports_recent_freshness_metrics():
    visualizations = build_visualizations(
        {
            "steps": {
                "inspect": {
                    "metrics": {
                        "recent_bid_results": 12,
                        "recent_bid_announcements": 34,
                        "fresh_ingest_results": 2,
                        "fresh_ingest_announcements": 3,
                        "vector_count": 128,
                    }
                }
            }
        }
    )
    assert visualizations
    assert visualizations[0]["chart_type"] == "bar"
    assert visualizations[0]["unit"] == "건"
    assert visualizations[0]["y_label"] == "건수 (건)"
    assert any("KB" in label for label in visualizations[0]["labels"])


def test_build_result_intelligence_generates_insights_and_recommendations():
    intelligence = build_result_intelligence(
        {
            "steps": {
                "inspect": {
                    "metrics": {
                        "today_rows": 0,
                        "vector_count": 50,
                        "api_check": False,
                    }
                },
                "predict": {
                    "metrics": {
                        "model_name": "v25",
                        "avg_r2": 0.55,
                        "pass_all": False,
                    }
                },
                "rag": {
                    "metrics": {
                        "source_bid_count": 0,
                    }
                },
            }
        }
    )
    assert intelligence["health_status"] == "critical"
    assert any("오늘 신규 수집 데이터" in item for item in intelligence["insights"])
    assert any("prediction_validate" in item for item in intelligence["recommended_actions"])


def test_build_terminal_answer_includes_insights_and_recommended_actions():
    """자동화 종료 답변은 스텝 요약에서 끝나지 않고 해석과 다음 액션까지 담는다.

    사용자는 "predict: success" 만 봐서는 무엇을 해야 할지 모릅니다. avg_r2 가
    0.58 로 기준 미달인데 status 는 success 라 더 그렇습니다. 해석 문단이
    빠지면 실패에 가까운 결과를 성공으로 읽게 됩니다.
    """
    request_obj = AutomationRequest(
        request_id="terminal-answer",
        user_id=1,
        intent_type="data_refresh",
        action_key="data_refresh",
        requested_text="오늘 데이터 갱신해줘",
        status="success",
        result_summary="최종 점검 완료",
        result_payload={
            "steps": {
                "inspect": {
                    "status": "success",
                    "summary": "inspect done",
                    "metrics": {"today_rows": 0, "vector_count": 20},
                },
                "predict": {
                    "status": "success",
                    "summary": "predict done",
                    "metrics": {"model_name": "v25", "avg_r2": 0.58, "pass_all": False},
                },
            }
        },
    )

    answer = build_terminal_answer(request_obj)

    assert "운영 해석" in answer
    assert "권장 액션" in answer
    assert "prediction_validate" in answer


# --------------------------------------------------------------------------- #
# AdvisoryEngineTests (DB 필요)
# --------------------------------------------------------------------------- #


def test_advisory_engine_detects_stale_kb(isolated_db):
    kb = KnowledgeBaseStatus(
        kb_version="bidding_kb",
        status="ready",
        source_bid_count=0,
    )
    isolated_db.add(kb)
    isolated_db.commit()
    kb.updated_at = utcnow() - timedelta(days=2)
    isolated_db.commit()

    suggestions = AdvisoryEngine().suggestion_texts(isolated_db)
    assert any("kb_refresh" in item for item in suggestions)


def test_advisory_engine_detects_recent_failures(isolated_db):
    for offset in range(2):
        isolated_db.add(
            AutomationRequest(
                request_id=f"fail-{offset}",
                # user_id 는 원본 스키마에서 NOT NULL 입니다. 익명 요청은 존재할 수 없습니다.
                user_id=1,
                intent_type="data_refresh",
                action_key="data_refresh",
                requested_text=f"실패 테스트 {offset}",
                status="failed",
            )
        )
    isolated_db.commit()

    suggestions = AdvisoryEngine().suggestion_texts(isolated_db)
    assert any("full_validation" in item for item in suggestions)


def test_advisory_engine_ignores_failures_before_latest_successful_health_check(
    isolated_db,
):
    """전체 점검이 성공한 뒤에는 그 이전 실패를 다시 꺼내지 않는다.

    점검으로 이미 해소된 실패까지 계속 세면, 사용자가 아무리 점검해도
    "최근 자동화 실패" 경고가 사라지지 않아 신호가 무의미해집니다.
    """
    now = utcnow()
    for offset in range(2):
        isolated_db.add(
            AutomationRequest(
                request_id=f"stale-fail-{offset}",
                user_id=1,
                intent_type="kb_refresh",
                action_key="kb_refresh",
                requested_text=f"과거 실패 {offset}",
                status="failed",
                created_at=now,
            )
        )
    isolated_db.add(
        AutomationRequest(
            request_id="health-check",
            user_id=1,
            intent_type="full_validation",
            action_key="full_validation",
            requested_text="전체 점검해줘",
            status="success",
            # 실패들보다 나중에 끝나야 체크포인트 역할을 합니다.
            created_at=now + timedelta(seconds=1),
            completed_at=now + timedelta(seconds=2),
        )
    )
    isolated_db.commit()

    suggestions = AdvisoryEngine().suggestion_texts(isolated_db, user_id=1)

    assert not any("최근 자동화 실패" in item for item in suggestions), suggestions


def test_advisory_engine_returns_priority_and_severity_sorted_signals(isolated_db):
    kb = KnowledgeBaseStatus(
        kb_version="bidding_kb_priority",
        status="ready",
        source_bid_count=0,
    )
    isolated_db.add(kb)
    isolated_db.commit()
    kb.updated_at = utcnow() - timedelta(days=3)
    isolated_db.commit()

    signals = AdvisoryEngine().suggest(isolated_db)
    assert signals
    assert signals[0]["severity"] == "critical"
    assert signals[0]["priority"] == "urgent"
    assert "reason_code" in signals[0]


# --------------------------------------------------------------------------- #
# StepExecutorTests
# --------------------------------------------------------------------------- #


def test_execute_internal_tool_step_populates_context_for_kb_status(isolated_db):
    isolated_db.add(
        KnowledgeBaseStatus(
            kb_version="bidding_kb",
            status="ready",
            source_bid_count=321,
            last_pipeline_run_id="exec-001",
        )
    )
    isolated_db.commit()

    context: dict = {}
    step = PlanStep(
        step_id="s1",
        kind="internal_tool",
        tool="kb_status_tool",
        output_key="kb_status",
    )
    execute_internal_tool_step(step, context, db=isolated_db)
    assert context["kb_status"]["source_bid_count"] == 321
    assert "kb_status" in context["tool_results"]


@patch("src.app.services.tools.bid_query_tool.execute", return_value={"result": {"total_bids": 5}})
def test_execute_plan_steps_for_answer_mode_does_not_create_automation_request(
    mocked_execute, isolated_db
):
    before_count = isolated_db.query(AutomationRequest).count()
    plan = ChatPlan(
        mode="answer",
        intent_type="statistics_query",
        steps=[
            PlanStep(
                step_id="s1",
                kind="internal_tool",
                tool="bid_query_tool",
                params={"query": "낙찰률 추세"},
                output_key="bid_query",
            ),
        ],
    )
    context = execute_plan_steps(plan, {}, db=isolated_db)
    assert isolated_db.query(AutomationRequest).count() == before_count
    assert context["tool_results"]["bid_query"]["result"]["total_bids"] == 5
    mocked_execute.assert_called_once()


def test_execute_internal_tool_step_supports_contextual_trend_and_chart_tools():
    context = {
        "tool_results": {
            "bid_query": {
                "result": {
                    "summary": {
                        "time_series": [
                            {"month": "2026-01", "avg_rate": 97.1, "bid_count": 4},
                            {"month": "2026-02", "avg_rate": 98.4, "bid_count": 5},
                            {"month": "2026-03", "avg_rate": 99.0, "bid_count": 6},
                        ]
                    }
                }
            }
        }
    }
    trend_step = PlanStep(
        step_id="s1",
        kind="internal_tool",
        tool="trend_analyzer",
        params={"source_key": "bid_query"},
        output_key="trend_analysis",
    )
    chart_step = PlanStep(
        step_id="s2",
        kind="internal_tool",
        tool="chart_builder",
        params={"source_key": "trend_analysis"},
        output_key="chart_payload",
    )

    execute_internal_tool_step(trend_step, context)
    execute_internal_tool_step(chart_step, context)

    assert context["tool_results"]["trend_analysis"]["direction"] == "up"
    assert context["tool_results"]["chart_payload"]["visualizations"]
    assert context["visualizations"]
    assert context["visualizations"][0]["chart_type"] == "line"

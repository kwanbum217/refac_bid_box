"""잘못된 요청과 실패한 부수 작업이 정상으로 보고되지 않는지 검증합니다."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.rag.structured_data import (
    InvalidDateFilterError,
    _parse_date,
    _resolve_window,
    retrieve_structured_data,
)

# ---------------------------------------------------------------------------
# 날짜 필터 파싱 실패 (전체 기간으로 조용히 넓히지 않는다)
# ---------------------------------------------------------------------------


def test_parse_date_raises_on_unparsable_value():
    """값이 없는 것과 해석하지 못한 것은 다릅니다."""
    assert _parse_date(None) is None
    assert _parse_date("") is None

    with pytest.raises(InvalidDateFilterError):
        _parse_date("작년 여름", "date_from")


def test_resolve_window_propagates_parse_failure():
    with pytest.raises(InvalidDateFilterError):
        _resolve_window({"date_from": "2026-13-99"})


def test_retrieve_structured_data_skips_query_on_bad_date():
    """해석 못 한 날짜로 전체 기간 통계를 돌려주면 사용자가 오독합니다."""
    plan = MagicMock()
    plan.filters = {"date_from": "지난달쯤"}
    db = MagicMock()

    result = retrieve_structured_data(db, plan)

    assert result["query_skipped"] is True
    assert result["summary"]["total_bids"] is None
    assert any("YYYY-MM-DD" in hint for hint in result["insufficiency_hints"])
    # 조회 자체를 하지 않았어야 한다
    db.scalar.assert_not_called()


def test_resolve_window_accepts_valid_date():
    """정상 날짜는 종전대로 창을 만듭니다."""
    date_from, _date_to = _resolve_window({"date_from": "2026-01-01"})
    assert date_from is not None
    assert date_from.year == 2026


# ---------------------------------------------------------------------------
# 상태 동기화 실패 (최신이 아님을 기계로 알 수 있어야 한다)
# ---------------------------------------------------------------------------


def test_status_tool_marks_stale_when_sync_fails():
    from src.app.services.tools import automation_status_tool as tool

    request_obj = MagicMock()
    request_obj.status = tool.ACTIVE_STATUSES[0]
    request_obj.plan_execution_id = "exec-1"
    request_obj.result_summary = ""

    with (
        patch.object(tool, "_find_request", return_value=request_obj),
        patch.object(tool, "sync_automation_status", side_effect=RuntimeError("boom")),
        patch.object(tool, "build_action_response", return_value={}),
        patch.object(tool, "_adapt_status_payload", side_effect=lambda p, *a, **k: p),
    ):
        payload = tool.execute(db=MagicMock(), job_id="job-1")

    assert payload["found"] is True
    assert payload["sync_failed"] is True
    assert payload["status_is_stale"] is True


def test_status_tool_not_stale_on_success():
    from src.app.services.tools import automation_status_tool as tool

    request_obj = MagicMock()
    request_obj.status = tool.ACTIVE_STATUSES[0]
    request_obj.plan_execution_id = "exec-1"

    with (
        patch.object(tool, "_find_request", return_value=request_obj),
        patch.object(tool, "sync_automation_status", return_value=request_obj),
        patch.object(tool, "build_action_response", return_value={}),
        patch.object(tool, "_adapt_status_payload", side_effect=lambda p, *a, **k: p),
    ):
        payload = tool.execute(db=MagicMock(), job_id="job-1")

    assert payload["sync_failed"] is False
    assert payload["status_is_stale"] is False


# ---------------------------------------------------------------------------
# 미등록 액션 (오타 하나가 완료로 기록되지 않는다)
# ---------------------------------------------------------------------------


def _request(action_key: str) -> MagicMock:
    request_obj = MagicMock()
    request_obj.action_key = action_key
    request_obj.payload = {}
    return request_obj


def test_unknown_action_key_is_failed_not_success():
    from src.app.services import automation_orchestrator as orch

    request_obj = _request("collect_bidz")
    db = MagicMock()

    with (
        patch.object(orch, "_load_plan_from_request_payload", return_value=None),
        patch.object(orch, "_get_pipeline_step", return_value=None),
        patch.object(orch, "get_action", return_value=None),
    ):
        orch.start_automation_request(db, request_obj)

    assert request_obj.status == orch.STATUS_FAILED
    assert "등록되지 않은 액션" in request_obj.result_summary
    assert "collect_bidz" in request_obj.result_summary


def test_empty_action_key_stays_success():
    """실행할 것이 없는 요청은 종전대로 성공입니다."""
    from src.app.services import automation_orchestrator as orch

    request_obj = _request("")
    db = MagicMock()

    with (
        patch.object(orch, "_load_plan_from_request_payload", return_value=None),
        patch.object(orch, "_get_pipeline_step", return_value=None),
        patch.object(orch, "get_action", return_value=None),
    ):
        orch.start_automation_request(db, request_obj)

    assert request_obj.status == orch.STATUS_SUCCESS
    assert "필요하지 않은 요청" in request_obj.result_summary


def test_stale_flags_survive_into_result_payload_and_answer():
    """플래그를 payload 최상위에만 두면 API 응답 경계에서 사라집니다.

    chatbot.py 는 result_payload 만 ChatResponse 로 옮기므로, 내부적으로는
    stale 을 아는데 사용자에게는 현재 상태처럼 보였습니다.
    """
    from src.app.services.tools import automation_status_tool as tool

    request_obj = MagicMock()
    request_obj.status = tool.ACTIVE_STATUSES[0]
    request_obj.plan_execution_id = "exec-1"
    request_obj.result_summary = ""

    base = {"answer": "현재 점검 상태: 진행 중입니다.", "result_payload": {"steps": []}}
    with (
        patch.object(tool, "_find_request", return_value=request_obj),
        patch.object(tool, "sync_automation_status", side_effect=RuntimeError("boom")),
        patch.object(tool, "build_action_response", return_value=base),
        patch.object(tool, "_adapt_status_payload", side_effect=lambda p, *a, **k: p),
    ):
        payload = tool.execute(db=MagicMock(), job_id="job-1")

    assert payload["result_payload"]["sync_failed"] is True
    assert payload["result_payload"]["status_is_stale"] is True
    # 기존 내용을 덮어쓰지 않아야 합니다.
    assert payload["result_payload"]["steps"] == []
    assert "최신이 아닐 수 있습니다" in payload["answer"]
    assert "현재 점검 상태" in payload["answer"]


def test_stale_notice_is_not_duplicated():
    """같은 안내가 두 번 붙으면 사용자가 오류로 읽습니다."""
    from src.app.services.tools import automation_status_tool as tool

    request_obj = MagicMock()
    request_obj.status = tool.ACTIVE_STATUSES[0]
    request_obj.plan_execution_id = "exec-1"
    request_obj.result_summary = ""

    base = {"answer": "상태 동기화에 실패해 아래 정보는 최신이 아닐 수 있습니다.\n\n본문"}
    with (
        patch.object(tool, "_find_request", return_value=request_obj),
        patch.object(tool, "sync_automation_status", side_effect=RuntimeError("boom")),
        patch.object(tool, "build_action_response", return_value=base),
        patch.object(tool, "_adapt_status_payload", side_effect=lambda p, *a, **k: p),
    ):
        payload = tool.execute(db=MagicMock(), job_id="job-1")

    assert payload["answer"].count("최신이 아닐 수 있습니다") == 1


def test_successful_sync_does_not_add_stale_notice():
    """동기화가 성공하면 안내도 플래그도 붙지 않아야 합니다."""
    from src.app.services.tools import automation_status_tool as tool

    request_obj = MagicMock()
    request_obj.status = tool.ACTIVE_STATUSES[0]
    request_obj.plan_execution_id = "exec-1"

    base = {"answer": "현재 점검 상태: 진행 중입니다.", "result_payload": {}}
    with (
        patch.object(tool, "_find_request", return_value=request_obj),
        patch.object(tool, "sync_automation_status", return_value=request_obj),
        patch.object(tool, "build_action_response", return_value=base),
        patch.object(tool, "_adapt_status_payload", side_effect=lambda p, *a, **k: p),
    ):
        payload = tool.execute(db=MagicMock(), job_id="job-1")

    assert "최신이 아닐 수 있습니다" not in payload["answer"]
    assert "sync_failed" not in payload["result_payload"]

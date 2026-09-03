"""검증하지 못한 스텝과 치명적 점검 결과가 성공으로 승격되지 않는지 검증합니다.

`run_automation_pipeline` 의 디스패치 루프는 2요소 튜플에 `status` 가 없으면
`STATUS_SUCCESS` 를 기본값으로 줍니다. 스텝이 아무것도 검증하지 못했거나
치명적 문제를 발견해도 성공으로 기록되던 경로입니다.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.tasks import automation_tasks
from src.tasks.automation_tasks import _step_inspect, _step_predict, _step_rag
from src.tasks.scheduled_tasks import _mark_followup_failures


def _unpack(result: tuple) -> tuple[str | None, str, dict[str, Any]]:
    """스텝 반환값을 (status, summary, metrics) 로 정규화합니다."""
    if len(result) == 3:
        return result[0], result[1], result[2]
    return None, result[0], result[1]


def test_step_predict_without_models_is_not_success():
    """검증할 모델이 없으면 성공이 아니라 partial_success 입니다."""
    db = MagicMock()
    db.execute.return_value.scalar_one_or_none.return_value = None

    with patch("src.ml.model_registry.ModelRegistry.available_models", return_value=[]):
        status, summary, metrics = _unpack(_step_predict(db))

    assert status == "partial_success"
    assert metrics["skipped"] is True
    assert metrics["skip_reason"] == "등록된 모델 없음"
    assert "수행하지 못했습니다" in summary


def test_step_predict_without_sample_is_not_success():
    """검증 대상 공고가 없어도 성공으로 보고하지 않습니다."""
    db = MagicMock()
    db.execute.return_value.scalar_one_or_none.return_value = None

    with patch("src.ml.model_registry.ModelRegistry.available_models", return_value=["lgbm"]):
        status, _summary, metrics = _unpack(_step_predict(db))

    assert status == "partial_success"
    assert metrics["skip_reason"] == "검증 대상 공고 없음"


def _inspect_db() -> MagicMock:
    """_step_inspect 는 집계를 전부 db.scalar 로 읽습니다.

    None 을 돌려주면 건수는 0, 최신 수집 시각은 없음이 되어 치명 경고와
    무관한 소프트 경고만 생깁니다. 치명 경고 판정만 격리해 볼 수 있습니다.
    """
    db = MagicMock()
    db.scalar.return_value = None
    return db


def test_step_inspect_missing_tables_is_not_success():
    """DB 필수 테이블 누락은 경고 문구가 아니라 상태로 드러나야 합니다."""
    inspector = MagicMock()
    inspector.get_table_names.return_value = ["bid_announcements"]

    with (
        patch("sqlalchemy.inspect", return_value=inspector),
        patch("src.tasks.automation_steps._check_chroma_vectors", return_value=100),
    ):
        status, summary, metrics = _unpack(_step_inspect(_inspect_db()))

    assert status == "partial_success"
    assert any("DB 필수 테이블 누락" in w for w in metrics["critical_warnings"])
    assert "DB 필수 테이블 누락" in summary


def test_step_inspect_empty_vector_store_is_not_success():
    """ChromaDB 임베딩 0건은 시스템 불능 상태입니다."""
    inspector = MagicMock()
    inspector.get_table_names.return_value = [
        "bid_announcements",
        "bid_results",
        "accounts_customuser",
    ]

    with (
        patch("sqlalchemy.inspect", return_value=inspector),
        patch("src.tasks.automation_steps._check_chroma_vectors", return_value=0),
    ):
        status, _summary, metrics = _unpack(_step_inspect(_inspect_db()))

    assert status == "partial_success"
    assert any("ChromaDB 임베딩" in w for w in metrics["critical_warnings"])


def test_step_inspect_healthy_state_stays_success():
    """정상 상태는 종전대로 2요소 튜플(성공)로 남습니다."""
    inspector = MagicMock()
    inspector.get_table_names.return_value = [
        "bid_announcements",
        "bid_results",
        "accounts_customuser",
    ]

    with (
        patch("sqlalchemy.inspect", return_value=inspector),
        patch("src.tasks.automation_steps._check_chroma_vectors", return_value=100),
    ):
        result = _step_inspect(_inspect_db())

    assert len(result) == 2
    assert result[1]["critical_warnings"] == []


def test_step_rag_failure_returns_three_tuple_status():
    """KB 재구축 실패 상태가 3요소 튜플로 그대로 전파됩니다."""
    db = MagicMock()

    with patch(
        "src.app.services.kb_builder.rebuild_knowledge_base",
        return_value={"status": "failed", "summary": "인덱싱 실패", "metrics": {}},
    ):
        result = _step_rag(db)

    assert len(result) == 3
    assert result[0] == "failed"
    assert "인덱싱 실패" in result[1]


def test_step_rag_success_stays_three_tuple():
    """KB 재구축 성공도 3요소 튜플로 status 를 그대로 돌려줍니다."""
    db = MagicMock()

    with patch(
        "src.app.services.kb_builder.rebuild_knowledge_base",
        return_value={"status": "success", "summary": "인덱싱 완료", "metrics": {}},
    ):
        result = _step_rag(db)

    assert len(result) == 3
    assert result[0] == "success"
    assert "인덱싱 완료" in result[1]


def test_step_rag_unknown_status_is_demoted_to_failed():
    """알 수 없는 status 는 성공이 아니라 실패로 강등됩니다."""
    db = MagicMock()

    with patch(
        "src.app.services.kb_builder.rebuild_knowledge_base",
        return_value={"status": "mystery", "summary": "모호한 결과", "metrics": {}},
    ):
        status, summary, _metrics = _step_rag(db)

    assert status == "failed"
    assert "알 수 없어 실패 처리" in summary


@pytest.mark.asyncio
async def test_rag_failure_marks_pipeline_failed():
    """KB 재구축 실패가 파이프라인 최종 상태를 실패로 만듭니다."""
    with (
        patch(
            "src.app.services.kb_builder.rebuild_knowledge_base",
            return_value={"status": "failed", "summary": "인덱싱 실패", "metrics": {}},
        ),
        patch.object(automation_tasks, "get_run_mode_steps", return_value=["rag"]),
        patch.object(automation_tasks, "_report") as mock_report,
        patch.object(automation_tasks, "SessionLocal", return_value=MagicMock()),
    ):
        res = await automation_tasks.run_automation_pipeline(
            {}, run_mode="kb_only", automation_request_id="req_rag_failed"
        )

    assert res["status"] == automation_tasks.STATUS_FAILED
    rag_reports = [c for c in mock_report.call_args_list if c.args[2] == "rag"]
    assert rag_reports
    assert rag_reports[0].args[3] == "failed"
    final_reports = [c for c in mock_report.call_args_list if c.kwargs.get("final")]
    assert final_reports
    assert final_reports[-1].args[5]["step_statuses"]["rag"] == "failed"


@pytest.mark.asyncio
async def test_rag_success_keeps_pipeline_success():
    """KB 재구축 성공은 기존과 동일하게 파이프라인 성공으로 이어집니다."""
    with (
        patch(
            "src.app.services.kb_builder.rebuild_knowledge_base",
            return_value={
                "status": "success",
                "summary": "인덱싱 완료",
                "metrics": {"source_bid_count": 10},
            },
        ),
        patch.object(automation_tasks, "get_run_mode_steps", return_value=["rag"]),
        patch.object(automation_tasks, "_report"),
        patch.object(automation_tasks, "SessionLocal", return_value=MagicMock()),
    ):
        res = await automation_tasks.run_automation_pipeline(
            {}, run_mode="kb_only", automation_request_id="req_rag_ok"
        )

    assert res["status"] == automation_tasks.STATUS_SUCCESS


def test_step_inspect_unavailable_vector_count_is_not_success():
    """벡터DB를 확인하지 못한 경우(None)는 치명 처리합니다."""
    inspector = MagicMock()
    inspector.get_table_names.return_value = [
        "bid_announcements",
        "bid_results",
        "accounts_customuser",
    ]

    with (
        patch("sqlalchemy.inspect", return_value=inspector),
        patch("src.tasks.automation_steps._check_chroma_vectors", return_value=None),
    ):
        status, _summary, metrics = _unpack(_step_inspect(_inspect_db()))

    assert status == "partial_success"
    assert any(
        w == "ChromaDB 임베딩 수를 확인하지 못했습니다." for w in metrics["critical_warnings"]
    )


def test_step_inspect_unavailable_table_count_is_not_success():
    """DB 테이블 목록 확인 실패(None)는 치명 처리합니다."""
    with (
        patch("sqlalchemy.inspect", side_effect=RuntimeError("검사 불능")),
        patch("src.tasks.automation_steps._check_chroma_vectors", return_value=100),
    ):
        status, _summary, metrics = _unpack(_step_inspect(_inspect_db()))

    assert status == "partial_success"
    assert any(w == "DB 테이블 목록을 확인하지 못했습니다." for w in metrics["critical_warnings"])


def test_vector_count_zero_and_none_warnings_differ():
    """0건(검사 완료)과 None(검사 불가)은 다른 경고 문구로 구분됩니다."""
    inspector = MagicMock()
    inspector.get_table_names.return_value = [
        "bid_announcements",
        "bid_results",
        "accounts_customuser",
    ]

    def metrics_with_vector_count(value: int | None) -> dict[str, Any]:
        with (
            patch("sqlalchemy.inspect", return_value=inspector),
            patch("src.tasks.automation_steps._check_chroma_vectors", return_value=value),
        ):
            _status, _summary, metrics = _unpack(_step_inspect(_inspect_db()))
        return metrics

    zero_messages = [
        w for w in metrics_with_vector_count(0)["critical_warnings"] if "ChromaDB" in w
    ]
    none_messages = [
        w for w in metrics_with_vector_count(None)["critical_warnings"] if "ChromaDB" in w
    ]
    assert zero_messages
    assert none_messages
    assert zero_messages != none_messages
    assert any("비어 있습니다" in w for w in zero_messages)
    assert any("확인하지 못했습니다" in w for w in none_messages)


def test_followup_failure_degrades_schedule_status():
    """기관 이력 집계 실패는 스케줄 최종 상태에 드러나야 합니다."""
    outcome = _mark_followup_failures(
        {
            "status": "success",
            "ranking_snapshots": {"status": "success"},
            "institution_stats": {"status": "failed", "error": "boom"},
        }
    )

    assert outcome["status"] == "partial_success"
    assert outcome["failed_followups"] == ["institution_stats"]


def test_followup_success_keeps_schedule_status():
    outcome = _mark_followup_failures(
        {
            "status": "success",
            "ranking_snapshots": {"status": "success"},
            "institution_stats": {"status": "success"},
        }
    )

    assert outcome["status"] == "success"
    assert "failed_followups" not in outcome

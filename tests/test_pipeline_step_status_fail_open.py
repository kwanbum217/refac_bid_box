"""검증하지 못한 스텝과 치명적 점검 결과가 성공으로 승격되지 않는지 검증합니다.

`run_automation_pipeline` 의 디스패치 루프는 2요소 튜플에 `status` 가 없으면
`STATUS_SUCCESS` 를 기본값으로 줍니다. 스텝이 아무것도 검증하지 못했거나
치명적 문제를 발견해도 성공으로 기록되던 경로입니다.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from src.tasks.automation_tasks import _step_inspect, _step_predict
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
        patch("src.tasks.automation_tasks._check_chroma_vectors", return_value=100),
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
        patch("src.tasks.automation_tasks._check_chroma_vectors", return_value=0),
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
        patch("src.tasks.automation_tasks._check_chroma_vectors", return_value=100),
    ):
        result = _step_inspect(_inspect_db())

    assert len(result) == 2
    assert result[1]["critical_warnings"] == []


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

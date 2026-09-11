"""tests/test_restore_drill_freshness.py

복원 드릴 정례화 신선도 점검기 및 야간 경로 연동 단위/통합 테스트.

Capsule 불변조건 검증:
1. 드릴 보고서 최상위에 started_at 과 finished_at 이 기록된다 (기존 키 보존).
2. 점검기가 success 가 참(True)인 보고서만 후보로 삼는다.
3. 실패한 드릴만 있으면 판정 불가(UNDECIDABLE)다.
4. 보고서가 없으면 판정 불가(UNDECIDABLE)이며 정상이 아니다.
5. started_at 이 없는 구 보고서는 g1_verification.file.report.generated_at 으로 후퇴해 판정한다.
6. 파일명이나 mtime 으로 시각을 추측하지 않는다.
7. 임계 초과(OVERDUE) 시 경고 로그가 남고 outcome 에 담긴다. 정상(OK) 시 정보 로그가 남는다.
8. 점검기와 야간 경로가 drill 이나 restore 를 호출하지 않는다 (읽기 전용).
9. 점검이 예외를 던져도 야간 작업 전체가 중단되지 않는다.
"""

from __future__ import annotations

import inspect
import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.app.services.restore_drill_freshness import (
    EXIT_OK,
    EXIT_OVERDUE,
    EXIT_UNDECIDABLE,
    STATUS_OK,
    STATUS_OVERDUE,
    STATUS_UNDECIDABLE,
    check_restore_drill_freshness,
    evaluate_drill_freshness,
    find_latest_successful_drill,
    parse_drill_timestamp,
)
from src.tasks import scheduled_tasks
from src.tasks.scheduled_tasks import _check_restore_drill_freshness

NOW = datetime(2026, 9, 11, 12, 0, 0, tzinfo=UTC)


def test_드릴보고서_최상위에_started_at과_finished_at이_기록된다(tmp_path: Path) -> None:
    """scripts/backup_recovery.py 의 run_restore_drill 이 started_at 과 finished_at 을 남기는지 검증."""
    from scripts.backup_recovery import run_restore_drill

    project_root = tmp_path / "repo"
    project_root.mkdir()
    target_dir = tmp_path / "target"
    snapshot_dir = tmp_path / "snapshot"
    snapshot_dir.mkdir()

    # 최소한의 매니페스트 생성 (스냅샷 검증 실패 케이스에서도 _drill_rep 가 호출됨)
    (snapshot_dir / "backup_manifest.json").write_text(
        json.dumps({"schema": "BACKUP_MANIFEST_V1", "partial_backup": True}),
        encoding="utf-8",
    )

    fake_prod_db = {
        "host": "localhost",
        "port": 3306,
        "user": "root",
        "password": "pwd",
        "name": "procurement",
    }
    with patch("scripts.backup_recovery.get_db_config", return_value=fake_prod_db):
        rep = run_restore_drill(
            snapshot_dir=snapshot_dir,
            target_dir=target_dir,
            project_root=project_root,
        )

    # 1. started_at 과 finished_at 필드 존재 확인
    assert "started_at" in rep, "started_at 필드가 누락되었습니다."
    assert "finished_at" in rep, "finished_at 필드가 누락되었습니다."

    # 2. ISO 8601 UTC 파싱 가능 여부 확인
    dt_st = parse_drill_timestamp(rep["started_at"])
    dt_fi = parse_drill_timestamp(rep["finished_at"])
    assert dt_st is not None, f"started_at 파싱 불가: {rep['started_at']}"
    assert dt_fi is not None, f"finished_at 파싱 불가: {rep['finished_at']}"
    assert dt_fi >= dt_st

    # 3. 기존 키 보존 확인
    for key in (
        "schema",
        "snapshot_dir",
        "target_dir",
        "drill_db",
        "snapshot_valid",
        "components",
        "extracted_components",
        "timings",
        "total_duration_seconds",
        "rpo_measurements",
        "g1_verification",
        "keep_artifacts",
        "errors",
        "success",
    ):
        assert key in rep, f"기존 필수 키 누락: {key}"
    assert rep["schema"] == "RESTORE_DRILL_REPORT_V2"


def test_점검기가_성공한_보고서만_후보로_삼는다(tmp_path: Path) -> None:
    """점검기가 success: true 인 보고서만 후보로 삼고, 실패한 최신 보고서는 건너뛴다."""
    reports_dir = tmp_path / "backups"
    reports_dir.mkdir()

    older_success_time = NOW - timedelta(days=20)
    newer_failure_time = NOW - timedelta(days=1)

    # 오래되었지만 성공한 보고서
    succ_report = {
        "schema": "RESTORE_DRILL_REPORT_V2",
        "success": True,
        "started_at": older_success_time.isoformat(),
        "finished_at": (older_success_time + timedelta(minutes=15)).isoformat(),
    }
    (reports_dir / "restore_drill_report_20260822.json").write_text(
        json.dumps(succ_report), encoding="utf-8"
    )

    # 최신이지만 실패한 보고서
    fail_report = {
        "schema": "RESTORE_DRILL_REPORT_V2",
        "success": False,
        "started_at": newer_failure_time.isoformat(),
        "finished_at": (newer_failure_time + timedelta(minutes=5)).isoformat(),
        "errors": ["G1 검증 실패"],
    }
    (reports_dir / "restore_drill_report_20260910.json").write_text(
        json.dumps(fail_report), encoding="utf-8"
    )

    latest_dt, latest_path, total, succ = find_latest_successful_drill(reports_dir)
    assert total == 2
    assert succ == 1
    assert latest_dt == older_success_time
    assert latest_path == reports_dir / "restore_drill_report_20260822.json"

    res = check_restore_drill_freshness(reports_dir=reports_dir, now=NOW)
    assert res["status"] == STATUS_OK
    assert res["successful_candidates"] == 1
    assert res["total_candidates"] == 2
    assert res["last_drill_at"] == older_success_time.isoformat()


def test_실패한_드릴만_있으면_판정_불가다(tmp_path: Path) -> None:
    """성공한 드릴이 하나도 없고 실패 보고서만 있는 경우 UNDECIDABLE 로 판정한다."""
    reports_dir = tmp_path / "backups"
    reports_dir.mkdir()

    fail_report = {
        "schema": "RESTORE_DRILL_REPORT_V2",
        "success": False,
        "started_at": (NOW - timedelta(days=5)).isoformat(),
        "errors": ["DB import 에러"],
    }
    (reports_dir / "restore_drill_report_failed.json").write_text(
        json.dumps(fail_report), encoding="utf-8"
    )

    res = check_restore_drill_freshness(reports_dir=reports_dir, now=NOW)
    assert res["status"] == STATUS_UNDECIDABLE
    assert res["is_undecidable"] is True
    assert res["is_overdue"] is False
    assert res["exit_code"] == EXIT_UNDECIDABLE
    assert "성공(success: true)한 복원 드릴 보고서가 존재하지 않습니다" in res["reason"]


def test_보고서가_없으면_판정_불가이며_정상이_아니다(tmp_path: Path) -> None:
    """보고서가 아예 존재하지 않는 빈 디렉터리인 경우 정상이 아니라 UNDECIDABLE 로 판정한다."""
    empty_dir = tmp_path / "empty_backups"
    empty_dir.mkdir()

    res = check_restore_drill_freshness(reports_dir=empty_dir, now=NOW)
    assert res["status"] == STATUS_UNDECIDABLE
    assert res["status"] != STATUS_OK
    assert res["is_undecidable"] is True
    assert res["exit_code"] == EXIT_UNDECIDABLE
    assert res["last_drill_at"] is None
    assert "보고서가 존재하지 않습니다" in res["reason"]


def test_started_at이_없는_구_보고서는_중첩_시각으로_후퇴해_판정한다(tmp_path: Path) -> None:
    """started_at 이 없는 레거시 보고서는 g1_verification.file.report.generated_at 을 사용한다."""
    reports_dir = tmp_path / "backups"
    reports_dir.mkdir()

    legacy_gen_at = NOW - timedelta(days=30)
    legacy_report = {
        "schema": "RESTORE_DRILL_REPORT_V2",
        "success": True,
        # 최상위 started_at 누락
        "g1_verification": {
            "success": True,
            "file": {
                "report": {
                    "generated_at": legacy_gen_at.isoformat(),
                }
            },
        },
    }
    (reports_dir / "restore_drill_report_legacy.json").write_text(
        json.dumps(legacy_report), encoding="utf-8"
    )

    latest_dt, _, _, succ = find_latest_successful_drill(reports_dir)
    assert succ == 1
    assert latest_dt == legacy_gen_at

    res = check_restore_drill_freshness(reports_dir=reports_dir, now=NOW)
    assert res["status"] == STATUS_OK
    assert res["last_drill_at"] == legacy_gen_at.isoformat()
    assert res["elapsed_days"] is not None
    assert abs(res["elapsed_days"] - 30.0) < 0.01


def test_파일명이나_mtime으로_시각을_추측하지_않는다(tmp_path: Path) -> None:
    """보고서 내부에 유효 시각이 없으면 파일명 날짜나 파일 mtime 에 기대지 않고 판정 불가로 처리한다."""
    reports_dir = tmp_path / "backups"
    reports_dir.mkdir()

    # 파일명에는 20260910 이 있지만 내용에 started_at 과 g1_verification 시각이 모두 없음
    invalid_report = {
        "schema": "RESTORE_DRILL_REPORT_V2",
        "success": True,
        "g1_verification": {"file": {}},
    }
    fpath = reports_dir / "restore_drill_report_20260910.json"
    fpath.write_text(json.dumps(invalid_report), encoding="utf-8")

    latest_dt, _, total, succ = find_latest_successful_drill(reports_dir)
    assert total == 1
    assert succ == 1
    assert latest_dt is None  # 시각 판독 불가

    res = check_restore_drill_freshness(reports_dir=reports_dir, now=NOW)
    assert res["status"] == STATUS_UNDECIDABLE
    assert res["is_undecidable"] is True
    assert "유효한 실행 시각" in res["reason"]


def test_임계초과_및_정상_순수함수_판정() -> None:
    """80일 이하 경과는 정상(OK), 80일 초과는 초과(OVERDUE)로 판정한다."""
    # 79일 경과 -> 정상
    drill_time_79d = NOW - timedelta(days=79)
    res_ok = evaluate_drill_freshness(
        latest_drill_at=drill_time_79d,
        now=NOW,
        warn_threshold_days=80.0,
        cadence_days=90.0,
    )
    assert res_ok["status"] == STATUS_OK
    assert res_ok["is_overdue"] is False
    assert res_ok["exit_code"] == EXIT_OK

    # 81일 경과 -> 경고 임계 초과
    drill_time_81d = NOW - timedelta(days=81)
    res_overdue = evaluate_drill_freshness(
        latest_drill_at=drill_time_81d,
        now=NOW,
        warn_threshold_days=80.0,
        cadence_days=90.0,
    )
    assert res_overdue["status"] == STATUS_OVERDUE
    assert res_overdue["is_overdue"] is True
    assert res_overdue["exit_code"] == EXIT_OVERDUE
    assert "초과했습니다" in res_overdue["reason"]


def test_점검기와_야간경로가_드릴이나_복원을_호출하지_않는다() -> None:
    """신선도 점검기 및 야간 점검 모듈 내에 run_restore_drill, restore 등의 호출 코드가 없음을 확인한다."""
    import src.app.services.restore_drill_freshness as freshness_mod
    import src.tasks.scheduled_tasks as sched_mod

    for mod in (freshness_mod, sched_mod):
        source = inspect.getsource(mod)
        lines = [line.strip() for line in source.splitlines() if not line.strip().startswith("#")]
        for line in lines:
            if "check_restore_drill_freshness" in line or "_check_restore_drill_freshness" in line:
                continue
            assert "run_restore_drill(" not in line
            assert "restore_mysql_database(" not in line
            assert "execute_restore(" not in line


def test_임계초과시_경고로그가_남고_outcome에_초과사실이_담긴다(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """임계 초과 시 warning 로그를 남기고, _check_restore_drill_freshness 반환값에 담긴다."""
    overdue_payload = {
        "status": STATUS_OVERDUE,
        "is_overdue": True,
        "is_undecidable": False,
        "last_drill_at": (NOW - timedelta(days=85)).isoformat(),
        "elapsed_days": 85.0,
        "warn_threshold_days": 80.0,
        "cadence_days": 90.0,
        "reason": "마지막 성공 복원 드릴로부터 85.0일 경과하여 경고 임계(80.0일)를 초과했습니다.",
    }

    with (
        patch(
            "src.app.services.restore_drill_freshness.check_restore_drill_freshness",
            return_value=overdue_payload,
        ),
        caplog.at_level(logging.INFO),
    ):
        caplog.clear()
        res = _check_restore_drill_freshness()

        assert res["status"] == STATUS_OVERDUE
        assert res["is_overdue"] is True

        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) >= 1
        assert "임계 초과 감지" in warnings[0].message
        assert "85.0일" in warnings[0].message


def test_판정불가시_경고로그가_남는다(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """판정 불가 시에도 정보 로그가 아닌 warning 로그를 남긴다."""
    undecidable_payload = {
        "status": STATUS_UNDECIDABLE,
        "is_overdue": False,
        "is_undecidable": True,
        "last_drill_at": None,
        "reason": "복원 드릴 보고서가 존재하지 않습니다.",
    }

    with (
        patch(
            "src.app.services.restore_drill_freshness.check_restore_drill_freshness",
            return_value=undecidable_payload,
        ),
        caplog.at_level(logging.INFO),
    ):
        caplog.clear()
        res = _check_restore_drill_freshness()

        assert res["status"] == STATUS_UNDECIDABLE

        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) >= 1
        assert "판정 불가" in warnings[0].message


def test_정상일때_경고로그가_남지_않고_정보로그가_남는다(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """정상 범위일 때는 warning 로그 없이 info 로그만 남긴다."""
    ok_payload = {
        "status": STATUS_OK,
        "is_overdue": False,
        "is_undecidable": False,
        "last_drill_at": (NOW - timedelta(days=20)).isoformat(),
        "elapsed_days": 20.0,
        "warn_threshold_days": 80.0,
        "cadence_days": 90.0,
        "reason": "임계 이내입니다.",
    }

    with (
        patch(
            "src.app.services.restore_drill_freshness.check_restore_drill_freshness",
            return_value=ok_payload,
        ),
        caplog.at_level(logging.INFO),
    ):
        caplog.clear()
        res = _check_restore_drill_freshness()

        assert res["status"] == STATUS_OK

        warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert len(warnings) == 0

        infos = [r for r in caplog.records if r.levelno == logging.INFO]
        assert any("정상" in r.message for r in infos)


def test_점검이_예외를_던져도_야간작업이_중단되지_않는다() -> None:
    """점검 함수가 예외를 발생시켜도 외부로 전파하지 않고 status: failed 딕셔너리를 반환한다."""
    with patch(
        "src.app.services.restore_drill_freshness.check_restore_drill_freshness",
        side_effect=OSError("디스크 I/O 오류 모의"),
    ):
        res = _check_restore_drill_freshness()
        assert isinstance(res, dict)
        assert res.get("status") == "failed"
        assert "디스크 I/O 오류 모의" in res.get("error", "")


@pytest.mark.asyncio
async def test_nightly_schedule_task_후속단계에_복원드릴점검결과가_담긴다() -> None:
    """nightly_schedule_task 실행 후 outcome 에 restore_drill_freshness 결과가 담기는지 통합 검증."""
    dummy_claim = MagicMock()
    dummy_claim.acquired = True
    dummy_claim.key = "claim_key"
    dummy_claim.token = "claim_token"  # noqa: S105

    dummy_pipeline_outcome = {
        "status": "success",
        "execution_id": "test_exec_restore_drill",
    }

    freshness_drill_res = {
        "status": STATUS_OK,
        "is_overdue": False,
        "last_drill_at": NOW.isoformat(),
        "elapsed_days": 0.5,
    }

    with (
        patch("src.tasks.scheduled_tasks.settings.AUTOMATION_NIGHTLY_SCHEDULE_ENABLED", True),
        patch("src.tasks.scheduled_tasks.acquire_schedule_claim", return_value=dummy_claim),
        patch(
            "src.tasks.scheduled_tasks._create_scheduled_execution",
            return_value="test_exec_restore_drill",
        ),
        patch(
            "src.tasks.scheduled_tasks.run_automation_pipeline",
            return_value=dummy_pipeline_outcome,
        ),
        patch(
            "src.tasks.scheduled_tasks._rebuild_ranking_snapshots",
            return_value={"status": "success"},
        ),
        patch(
            "src.tasks.scheduled_tasks._rebuild_compare_stats_snapshots",
            return_value={"status": "success"},
        ),
        patch(
            "src.tasks.scheduled_tasks._rebuild_institution_stats",
            return_value={"status": "success"},
        ),
        patch(
            "src.tasks.scheduled_tasks._check_mysql_stats_freshness",
            return_value={"status": "success", "stale": False},
        ),
        patch(
            "src.tasks.scheduled_tasks._check_restore_drill_freshness",
            return_value=freshness_drill_res,
        ),
        patch("src.tasks.scheduled_tasks.release_schedule_claim"),
    ):
        ctx: dict[str, Any] = {}
        outcome = await scheduled_tasks.nightly_schedule_task(ctx)

        assert outcome["status"] == "success"
        assert "restore_drill_freshness" in outcome
        assert outcome["restore_drill_freshness"] == freshness_drill_res

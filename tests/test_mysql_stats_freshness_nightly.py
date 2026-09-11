"""tests/test_mysql_stats_freshness_nightly.py

야간 MySQL 영속 통계 신선도 점검 후속 단계 단위 테스트.

Capsule 불변조건 검증:
1. 야간 점검이 ANALYZE TABLE 을 포함한 어떤 쓰기도 실행하지 않는다 (읽기 전용).
2. 임계 초과 시 경고 로그가 남고 outcome 에 초과 사실이 담긴다.
3. 정상일 때 경고 로그가 남지 않고 정보 로그가 남는다.
4. 점검이 예외를 던져도 야간 작업 전체가 중단되지 않는다.
5. 기준 행 수가 하드코딩이 아니라 조회로 온다.
"""

from __future__ import annotations

import inspect
import logging
from datetime import datetime
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.app.services.mysql_stats_freshness import (
    check_mysql_stats_freshness,
    fetch_live_row_counts,
)
from src.tasks import scheduled_tasks
from src.tasks.scheduled_tasks import _check_mysql_stats_freshness

NOW = datetime(2026, 9, 11, 12, 0, 0)


def test_야간점검_코드베이스_실행구문_ANALYZE_TABLE_쓰기명령_부재() -> None:
    """코드베이스 내에 ANALYZE TABLE 등을 실행하는 SQL 문자열이나 코드가 존재하지 않음을 확인한다."""
    import src.app.services.mysql_stats_freshness as freshness_svc
    import src.tasks.scheduled_tasks as sched

    for mod in (freshness_svc, sched):
        source = inspect.getsource(mod)
        # 독스트링/주석 제외 후 실행 코드에서 ANALYZE TABLE 실행 시도 검사
        lines = [line.strip() for line in source.splitlines() if not line.strip().startswith("#")]
        for line in lines:
            if "execute(" in line or "scalar(" in line:
                assert "ANALYZE" not in line.upper()
                assert "OPTIMIZE" not in line.upper()


def test_야간점검_조회시_쓰기명령이나_ANALYZE_실행_없음() -> None:
    """점검 함수 실행 시 DB 에 쓰기나 ANALYZE 명령이 전혀 실행되지 않고 오직 SELECT 만 실행됨을 확인한다."""
    mock_db = MagicMock()

    # DB 시각 및 통계 행 모의
    mock_db.execute.return_value.scalar.return_value = NOW
    mock_db.execute.return_value.mappings.return_value.all.return_value = [
        {"table_name": "bid_results", "last_update": NOW, "n_rows": 100},
        {"table_name": "bid_announcements", "last_update": NOW, "n_rows": 200},
    ]
    # 실제 행 수 조회 모의
    mock_db.scalar.side_effect = [100, 200]

    result = check_mysql_stats_freshness(mock_db)

    # 실행된 모든 SQL 검사
    executed_queries: list[str] = []
    for call in mock_db.execute.call_args_list:
        args, _ = call
        if args:
            executed_queries.append(str(args[0]).strip().upper())

    # 모든 쿼리는 SELECT 로 시작해야 하며 DDL/DML/ANALYZE 문이 아니어야 함
    for q in executed_queries:
        assert q.startswith("SELECT"), f"SELECT 가 아닌 쿼리 발견: {q}"
        assert not q.startswith("ANALYZE"), f"ANALYZE 쿼리 발견: {q}"
        assert not q.startswith("OPTIMIZE"), f"OPTIMIZE 쿼리 발견: {q}"
        assert not q.startswith("UPDATE "), f"UPDATE 쿼리 발견: {q}"
        assert not q.startswith("INSERT "), f"INSERT 쿼리 발견: {q}"
        assert not q.startswith("DELETE "), f"DELETE 쿼리 발견: {q}"

    # commit / rollback 호출 여부 검사 (순수 조회이므로 호출되지 않아야 함)
    assert mock_db.commit.call_count == 0
    assert result["status"] == "success"
    assert result["stale"] is False


def test_기준행수가_하드코딩이_아니라_조회로_온다() -> None:
    """기준 행 수가 코드에 고정된 상수가 아니라 실시간 DB 조회 결과로 결정됨을 검증한다."""
    mock_db = MagicMock()

    # 케이스 1: 행 수가 500, 1000 일 때
    mock_db.scalar.side_effect = [500, 1000]
    counts_1 = fetch_live_row_counts(mock_db, tables=("bid_results", "bid_announcements"))
    assert counts_1 == {"bid_results": 500, "bid_announcements": 1000}

    # 케이스 2: 데이터가 증가하여 12345, 67890 일 때
    mock_db.scalar.side_effect = [12345, 67890]
    counts_2 = fetch_live_row_counts(mock_db, tables=("bid_results", "bid_announcements"))
    assert counts_2 == {"bid_results": 12345, "bid_announcements": 67890}

    # check_mysql_stats_freshness 에 전달 시 expected_rows 로 매핑되는지 확인
    with (
        patch("src.app.services.mysql_stats_freshness.fetch_innodb_stats") as mock_stats,
        patch("src.app.services.mysql_stats_freshness.fetch_live_row_counts") as mock_counts,
    ):
        mock_stats.return_value = (
            NOW,
            {
                "bid_results": (100, NOW),
                "bid_announcements": (200, NOW),
            },
        )
        mock_counts.return_value = {
            "bid_results": 999999,
            "bid_announcements": 888888,
        }

        outcome = check_mysql_stats_freshness(mock_db)
        tables_res = {item["table"]: item for item in outcome["tables"]}
        assert tables_res["bid_results"]["expected_rows"] == 999999
        assert tables_res["bid_announcements"]["expected_rows"] == 888888


def test_임계초과시_경고로그가_남고_outcome에_초과사실이_담긴다(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """통계 편차나 경과일이 임계를 초과하면 경고 로그를 남기고 outcome 에 stale 사실이 담긴다."""
    stale_payload = {
        "status": "success",
        "stale": True,
        "checked_at": "2026-09-11 12:00:00",
        "thresholds": {"max_drift_pct": 25.0, "max_stale_days": 3.0},
        "tables": [
            {
                "table": "bid_results",
                "stats_rows": 100,
                "expected_rows": 1000,
                "drift_pct": 90.0,
                "last_update": "2026-09-01 12:00:00",
                "age_days": 10.0,
                "status": "STALE",
                "reason": "편차 90.0% 가 임계 25.0% 초과; 경과 10.0일 이 임계 3.0일 초과",
                "stale": True,
            }
        ],
    }

    with (
        patch(
            "src.app.services.mysql_stats_freshness.check_mysql_stats_freshness",
            return_value=stale_payload,
        ),
        caplog.at_level(logging.INFO),
    ):
        caplog.clear()
        result = _check_mysql_stats_freshness()

        assert result["stale"] is True
        assert result["tables"][0]["status"] == "STALE"

        warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warning_records) >= 1
        assert "임계 초과 감지" in warning_records[0].message
        assert "bid_results" in warning_records[0].message


def test_정상일때_경고로그가_남지_않고_정보로그가_남는다(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """통계 신선도가 정상 범위일 때는 경고 로그가 남지 않고 정보 로그가 남는다."""
    ok_payload = {
        "status": "success",
        "stale": False,
        "checked_at": "2026-09-11 12:00:00",
        "thresholds": {"max_drift_pct": 25.0, "max_stale_days": 3.0},
        "tables": [
            {
                "table": "bid_results",
                "stats_rows": 1000,
                "expected_rows": 1000,
                "drift_pct": 0.0,
                "last_update": "2026-09-11 11:00:00",
                "age_days": 0.04,
                "status": "OK",
                "reason": "임계 이내입니다.",
                "stale": False,
            }
        ],
    }

    with (
        patch(
            "src.app.services.mysql_stats_freshness.check_mysql_stats_freshness",
            return_value=ok_payload,
        ),
        caplog.at_level(logging.INFO),
    ):
        caplog.clear()
        result = _check_mysql_stats_freshness()

        assert result["stale"] is False

        warning_records = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert len(warning_records) == 0

        info_records = [r for r in caplog.records if r.levelno == logging.INFO]
        assert any("정상" in r.message for r in info_records)


def test_점검이_예외를_던져도_야간작업이_중단되지_않는다() -> None:
    """신선도 점검 중 예외가 발생해도 예외를 외부로 전파하지 않고 실패 딕셔너리를 반환한다."""
    with patch(
        "src.app.services.mysql_stats_freshness.check_mysql_stats_freshness",
        side_effect=RuntimeError("DB 연결 시간 초과 모의"),
    ):
        result = _check_mysql_stats_freshness()

        assert isinstance(result, dict)
        assert result.get("status") == "failed"
        assert "DB 연결 시간 초과 모의" in result.get("error", "")


@pytest.mark.asyncio
async def test_nightly_schedule_task_후속단계에_점검결과가_담긴다() -> None:
    """야간 스케줄 실행 완료 시 outcome 에 mysql_stats_freshness 결과가 담기는지 통합 검증."""
    dummy_claim = MagicMock()
    dummy_claim.acquired = True
    dummy_claim.key = "claim_key"
    dummy_claim.token = "claim_token"  # noqa: S105

    dummy_pipeline_outcome = {
        "status": "success",
        "execution_id": "test_exec_123",
    }

    freshness_result = {
        "status": "success",
        "stale": False,
        "checked_at": "2026-09-11 12:00:00",
    }

    with (
        patch("src.tasks.scheduled_tasks.settings.AUTOMATION_NIGHTLY_SCHEDULE_ENABLED", True),
        patch("src.tasks.scheduled_tasks.acquire_schedule_claim", return_value=dummy_claim),
        patch(
            "src.tasks.scheduled_tasks._create_scheduled_execution", return_value="test_exec_123"
        ),
        patch(
            "src.tasks.scheduled_tasks.run_automation_pipeline", return_value=dummy_pipeline_outcome
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
            "src.tasks.scheduled_tasks._check_mysql_stats_freshness", return_value=freshness_result
        ),
        patch("src.tasks.scheduled_tasks.release_schedule_claim"),
    ):
        ctx: dict[str, Any] = {}
        outcome = await scheduled_tasks.nightly_schedule_task(ctx)

        assert outcome["status"] == "success"
        assert "mysql_stats_freshness" in outcome
        assert outcome["mysql_stats_freshness"] == freshness_result


def test_조회가_빠뜨린_테이블도_판정_목록에_남는다() -> None:
    """fetched 를 그대로 순회하면 빠진 테이블이 조용히 사라진다.

    리뷰어가 잔여로 지적한 경로다. 임계 초과가 정상으로 보이면 안 된다.
    """
    from datetime import datetime

    from src.app.services.mysql_stats_freshness import evaluate_all

    results = evaluate_all(
        ("bid_results", "bid_announcements"),
        {"bid_results": (100, datetime(2026, 9, 11))},
        {"bid_results": 100},
        datetime(2026, 9, 11),
    )

    assert [r["table"] for r in results] == ["bid_results", "bid_announcements"]
    missing = next(r for r in results if r["table"] == "bid_announcements")
    assert missing["status"] == "MISSING"
    assert missing["stale"] is True

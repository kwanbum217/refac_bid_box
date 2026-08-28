"""
tests/test_run_data_reconciliation.py

하류 동기화 오케스트레이션(scripts/run_data_reconciliation.py) 및 백필 연동 단위 테스트.
실제 DB, ChromaDB, Meilisearch 서버에 연결하지 않고 격리된 목(mock) 환경에서 검증합니다.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from scripts.backfill_from_g2b import _backfill
from scripts.run_data_reconciliation import (
    STAGE_CHROMADB_KB,
    STAGE_CONSISTENCY_CHECK,
    STAGE_DERIVED_AGGREGATES,
    STAGE_MEILISEARCH_INDEX,
    STAGE_ORDER,
    parse_date_or_datetime,
    run_reconciliation,
    verify_reconciliation,
)


@pytest.fixture
def mock_session():
    """테스트용 가상 DB 세션."""
    session = MagicMock()
    return session


def test_parse_date_or_datetime():
    """다양한 날짜 및 시각 문자열 형식이 올바르게 파싱되는지 검증."""
    dt1 = parse_date_or_datetime("20260827")
    assert dt1 == datetime(2026, 8, 27, 0, 0, 0)

    dt2 = parse_date_or_datetime("2026-08-27")
    assert dt2 == datetime(2026, 8, 27, 0, 0, 0)

    dt3 = parse_date_or_datetime("2026-08-27T14:30:00")
    assert dt3 == datetime(2026, 8, 27, 14, 30, 0)

    with pytest.raises(ValueError):
        parse_date_or_datetime("invalid-date")


def test_stage_order_is_correct(mock_session):
    """(e) 단계 실행 순서가 파생 집계 -> KB 색인 -> 검색 색인 -> 정합성 검사 순인지 검증."""
    executed_stages: list[str] = []

    def make_handler(stage_name: str):
        def handler(db):
            executed_stages.append(stage_name)
            return {"status": "ok"}

        return handler

    handlers = {
        STAGE_DERIVED_AGGREGATES: make_handler(STAGE_DERIVED_AGGREGATES),
        STAGE_CHROMADB_KB: make_handler(STAGE_CHROMADB_KB),
        STAGE_MEILISEARCH_INDEX: make_handler(STAGE_MEILISEARCH_INDEX),
        STAGE_CONSISTENCY_CHECK: make_handler(STAGE_CONSISTENCY_CHECK),
    }

    ret = run_reconciliation(
        since="20260827",
        session=mock_session,
        step_handlers=handlers,
    )

    assert ret == 0
    assert executed_stages == [
        STAGE_DERIVED_AGGREGATES,
        STAGE_CHROMADB_KB,
        STAGE_MEILISEARCH_INDEX,
        STAGE_CONSISTENCY_CHECK,
    ]
    assert executed_stages == STAGE_ORDER


def test_fail_closed_early_exit_on_stage_failure(mock_session):
    """(a) 한 단계가 실패하면 뒤 단계가 호출되지 않고 종료 코드가 1인지 검증 (fail-closed)."""
    executed_stages: list[str] = []

    def failing_kb_handler(db):
        executed_stages.append(STAGE_CHROMADB_KB)
        raise RuntimeError("ChromaDB 연결 실패 모의")

    handlers = {
        STAGE_DERIVED_AGGREGATES: lambda db: (
            executed_stages.append(STAGE_DERIVED_AGGREGATES) or {"status": "ok"}
        ),
        STAGE_CHROMADB_KB: failing_kb_handler,
        STAGE_MEILISEARCH_INDEX: lambda db: (
            executed_stages.append(STAGE_MEILISEARCH_INDEX) or {"status": "ok"}
        ),
        STAGE_CONSISTENCY_CHECK: lambda db: (
            executed_stages.append(STAGE_CONSISTENCY_CHECK) or {"status": "ok"}
        ),
    }

    ret = run_reconciliation(
        since="20260827",
        session=mock_session,
        step_handlers=handlers,
    )

    assert ret == 1
    # 파생 집계와 KB 색인까지만 실행되고, 이후 검색 색인과 정합성 검사는 호출되지 않아야 함
    assert executed_stages == [STAGE_DERIVED_AGGREGATES, STAGE_CHROMADB_KB]


def test_consistency_check_fails_when_diff_non_empty(mock_session):
    """(b) 모든 단계가 성공해도 정합성 차집합이 비어 있지 않으면 종료 코드가 1인지 검증."""
    db_items = {"20260827001", "20260827002", "20260827003"}
    chroma_items = {"20260827001", "20260827002"}  # 20260827003 누락
    meili_items = {"20260827001", "20260827002", "20260827003"}

    step_handlers = {
        STAGE_DERIVED_AGGREGATES: lambda db: {"status": "ok"},
        STAGE_CHROMADB_KB: lambda db: {"status": "success", "summary": "ok"},
        STAGE_MEILISEARCH_INDEX: lambda db: {"announcements": 0, "results": 3},
    }

    ret = run_reconciliation(
        since="20260827",
        session=mock_session,
        step_handlers=step_handlers,
        db_fetcher=lambda db, **kwargs: db_items,
        chroma_fetcher=lambda: chroma_items,
        meili_fetcher=lambda: meili_items,
    )

    assert ret == 1


def test_all_stages_and_consistency_check_pass(mock_session):
    """(c) 전부 통과하고 정합성 차집합이 0이면 종료 코드가 0인지 검증."""
    db_items = {"20260827001", "20260827002"}
    chroma_items = {"20260827001", "20260827002"}
    meili_items = {"20260827001", "20260827002"}

    step_handlers = {
        STAGE_DERIVED_AGGREGATES: lambda db: {"status": "ok"},
        STAGE_CHROMADB_KB: lambda db: {"status": "success", "summary": "ok"},
        STAGE_MEILISEARCH_INDEX: lambda db: {"announcements": 0, "results": 2},
    }

    ret = run_reconciliation(
        since="20260827",
        session=mock_session,
        step_handlers=step_handlers,
        db_fetcher=lambda db, **kwargs: db_items,
        chroma_fetcher=lambda: chroma_items,
        meili_fetcher=lambda: meili_items,
    )

    assert ret == 0


def test_dry_run_does_not_execute_actual_stages(mock_session):
    """(d) --dry-run 플래그 지정 시 실제 단계가 호출되지 않고 0으로 종료되는지 검증."""
    executed_stages: list[str] = []

    handlers = {
        stage: (lambda s: lambda db: executed_stages.append(s))(stage) for stage in STAGE_ORDER
    }

    ret = run_reconciliation(
        since="20260827",
        dry_run=True,
        session=mock_session,
        step_handlers=handlers,
    )

    assert ret == 0
    assert len(executed_stages) == 0


def test_missing_scope_arguments_returns_error(mock_session):
    """대상 구간 인자(--since 또는 --since-hours)가 없으면 1로 실패하는지 검증."""
    ret = run_reconciliation(
        since=None,
        since_hours=None,
        collected_since=None,
        session=mock_session,
    )
    assert ret == 1


def test_verify_reconciliation_logic():
    """verify_reconciliation 함수 자체의 차집합 계산 및 반환 스키마 검증."""
    mock_db = MagicMock()

    # 케이스 1: 일치
    res1 = verify_reconciliation(
        mock_db,
        db_fetcher=lambda db, **kw: {"A", "B"},
        chroma_fetcher=lambda: {"A", "B", "C"},
        meili_fetcher=lambda: {"A", "B"},
    )
    assert res1["passed"] is True
    assert res1["db_count"] == 2
    assert len(res1["missing_in_chroma"]) == 0
    assert len(res1["missing_in_meili"]) == 0

    # 케이스 2: Meilisearch 누락
    res2 = verify_reconciliation(
        mock_db,
        db_fetcher=lambda db, **kw: {"A", "B", "C"},
        chroma_fetcher=lambda: {"A", "B", "C"},
        meili_fetcher=lambda: {"A"},
    )
    assert res2["passed"] is False
    assert res2["missing_in_meili"] == {"B", "C"}


@pytest.mark.asyncio
async def test_backfill_sync_downstream_triggers_reconciliation():
    """scripts/backfill_from_g2b.py의 --sync-downstream 동작 검증."""
    with (
        patch("scripts.backfill_from_g2b.SessionLocal"),
        patch("scripts.backfill_from_g2b._latest", return_value=None),
        patch("scripts.backfill_from_g2b.collect_bids") as mock_collect,
        patch("scripts.backfill_from_g2b._refresh_aggregates"),
        patch(
            "scripts.run_data_reconciliation.run_reconciliation", return_value=0
        ) as mock_reconcile,
    ):
        mock_collect.return_value = {
            "status": "success",
            "announcement_count": 5,
            "result_count": 5,
        }

        # 1. sync_downstream=True: run_reconciliation이 호출되고 반환코드가 전파됨
        ret = await _backfill(
            categories=["Cnstwk"],
            since="20260827",
            dry_run=False,
            until="20260827",
            sync_downstream=True,
        )
        assert ret == 0
        assert mock_reconcile.call_count == 1

        # 2. sync_downstream=False: run_reconciliation이 호출되지 않음
        mock_reconcile.reset_mock()
        ret_no_sync = await _backfill(
            categories=["Cnstwk"],
            since="20260827",
            dry_run=False,
            until="20260827",
            sync_downstream=False,
        )
        assert ret_no_sync == 0
        assert mock_reconcile.call_count == 0

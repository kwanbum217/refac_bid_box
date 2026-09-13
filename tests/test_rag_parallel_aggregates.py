"""
tests/test_rag_parallel_aggregates.py

정형 검색 집계 병렬 실행과 기관명 목록 예열 계약 검증.

병렬 실행은 결과 순서와 구간 라벨이 순차 실행과 같아야 합니다. 통합 테스트는 실제 MySQL 에서
병렬 경로와 순차 경로의 집계 결과를 대조합니다.
    uv run pytest tests/test_rag_parallel_aggregates.py -m mysql_integration -v
"""

from __future__ import annotations

import os
import threading
import time

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from src.app.core.cache import cache
from src.app.models.bids import BidAnnouncement, BidResult
from src.rag import structured_data
from src.rag.schemas import RetrievalPlan


def test_sequential_path_keeps_order_on_sqlite(isolated_db):
    calls = []

    def task(name):
        def run(session):
            calls.append((name, session is isolated_db))
            return name

        return run

    result = structured_data._run_aggregates(
        isolated_db, [("a", task("first")), ("b", task("second"))]
    )

    assert result == ["first", "second"]
    assert calls == [("first", True), ("second", True)]


def test_parallel_path_keeps_result_order_and_labels(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'parallel.db'}")
    monkeypatch.setattr(structured_data.settings, "LATENCY_SEGMENT_LOGGING", True)
    monkeypatch.setattr(structured_data, "_parallel_aggregates_enabled", lambda db: True)
    threads = set()

    @structured_data._measure_call("cached_aggregate")
    def measured(delay, value, session):
        threads.add(threading.get_ident())
        time.sleep(delay)
        session.execute(text("SELECT 1"))
        return value

    tasks = [
        ("cached_aggregate", lambda session: measured(0.15, "slow", session)),
        ("cached_aggregate", lambda session: measured(0.0, "fast", session)),
        ("cached_aggregate", lambda session: measured(0.05, "last", session)),
    ]
    record = structured_data._open_latency_record()
    with Session(engine) as db:
        result = structured_data._run_aggregates(db, tasks)
    structured_data._close_latency_record(record)

    assert result == ["slow", "fast", "last"]
    assert len(threads) >= 2
    segments = record["segments"]
    assert segments["cached_aggregate_1"] >= 150
    assert segments["cached_aggregate_2"] < 150
    assert set(segments) >= {"cached_aggregate_1", "cached_aggregate_2", "cached_aggregate_3"}
    assert record["cursor_count"] == 3


def test_parallel_task_error_propagates(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'parallel_error.db'}")
    monkeypatch.setattr(structured_data, "_parallel_aggregates_enabled", lambda db: True)

    def boom(session):
        raise RuntimeError("집계 실패")

    with Session(engine) as db, pytest.raises(RuntimeError, match="집계 실패"):
        structured_data._run_aggregates(db, [("a", boom), ("b", lambda session: 1)])


def test_refresh_overwrites_both_catalogs_with_refresh_ttl(isolated_db, monkeypatch):
    isolated_db.add(BidAnnouncement(bid_ntce_no="A1", dminstt_nm="광주광역시", category="Servc"))
    isolated_db.add(BidResult(bid_ntce_no="R1", dminstt_nm="광주교육청", category="Servc"))
    isolated_db.commit()
    stored = {}
    original_set = cache.set

    def recording_set(key, value, ttl):
        stored[key] = ttl
        original_set(key, value, ttl)

    monkeypatch.setattr(cache, "set", recording_set)

    counts = structured_data.refresh_institution_name_catalogs(isolated_db)

    assert counts == {"bid_announcements": 1, "bid_results": 1}
    assert stored == {
        "rag:inst_catalog:bid_announcements": structured_data.INSTITUTION_CATALOG_REFRESH_TTL,
        "rag:inst_catalog:bid_results": structured_data.INSTITUTION_CATALOG_REFRESH_TTL,
    }

    def fail_execute(*args, **kwargs):
        raise AssertionError("예열된 목록이 있으면 해석이 DB 를 조회하면 안 됩니다")

    monkeypatch.setattr(isolated_db, "execute", fail_execute)
    assert structured_data._resolve_institution_names(
        isolated_db, BidResult.dminstt_nm, "광주"
    ) == ["광주교육청"]


def test_refresh_ttl_outlives_refresh_interval():
    assert structured_data.INSTITUTION_CATALOG_REFRESH_TTL >= 2 * 60 * 60


def test_catalog_refresh_is_scheduled_hourly():
    from src.tasks.summary_tasks import refresh_institution_catalog_task
    from src.tasks.worker import WorkerSettings

    jobs = [
        job
        for job in WorkerSettings.cron_jobs
        if job.name.endswith("refresh_institution_catalog_task")
    ]

    assert len(jobs) == 1
    assert jobs[0].hour is None
    assert refresh_institution_catalog_task in WorkerSettings.functions


def _mysql_engine():
    url = os.environ.get("MYSQL_TEST_URL")
    if not url or "mysql" not in url:
        return None
    try:
        engine = create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 3})
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return engine
    except Exception:
        return None


def _summary_signature(result):
    summary = result["summary"]
    return (
        summary["total_bids"],
        summary["announcement_count"],
        summary["average_winning_rate"],
        summary["total_winning_amount"],
        sorted(row["win_count"] for row in summary["top_winners"]),
        sorted(row["ntce_count"] for row in summary["top_institutions"]),
        sorted(row["ntce_count"] for row in summary["top_announcements"]),
    )


@pytest.mark.mysql_integration
@pytest.mark.parametrize(
    "filters",
    [
        {"institution_name": "광주", "category": "Servc"},
        {"institution_name": "서울회생법원"},
    ],
)
def test_mysql_parallel_equals_sequential(filters, monkeypatch):
    engine = _mysql_engine()
    if engine is None:
        pytest.skip("MYSQL_TEST_URL 이 없거나 MySQL 에 연결할 수 없습니다")
    plan = RetrievalPlan(use_sql=True, filters=filters)

    with Session(engine) as db:
        parallel = structured_data.retrieve_structured_data(db, plan)
    monkeypatch.setattr(cache, "_local", {})
    monkeypatch.setattr(structured_data, "_parallel_aggregates_enabled", lambda db: False)
    with Session(engine) as db:
        sequential = structured_data.retrieve_structured_data(db, plan)

    assert _summary_signature(parallel) == _summary_signature(sequential)

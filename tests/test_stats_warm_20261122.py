"""
tests/test_stats_warm_20261122.py

시·도 용역 통계 RAG 캐시 예열의 계약을 고정합니다.

예열 질문은 챗봇 정형 경로가 실제로 만드는 계획과 같은 계획으로 돌아야 하고,
예열 뒤 같은 질문은 집계 SQL 을 다시 실행하지 않아야 합니다. 운영 DB·Redis 에
기대지 않고 SQLite 인메모리와 메모리 캐시만 씁니다.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from src.app.core.cache import cache
from src.app.core.config import settings
from src.app.core.db import Base
from src.app.models.bids import BidAnnouncement, BidResult
from src.rag.engine import HybridRAGEngine, _apply_entry_default_statistics_window
from src.rag.query_planning import build_retrieval_plan
from src.tasks import rag_stats_warm, scheduled_tasks
from src.tasks.worker import WorkerSettings

# 캐시가 비면 다시 실행되는 무거운 집계의 표지입니다. 예열 뒤에는 이 표지가
# 붙은 SQL 이 한 건도 나오지 않아야 합니다.
AGGREGATE_MARKERS = ("count(", "avg(", "sum(", "group by")

# 5년 창과 공고 건수 기본 창(최근 30일) 양쪽에 들어오는 고정 시각입니다.
# date.today() 기준 상대 창을 쓰므로 실행일과 무관하게 창 안에 남도록 최근
# 시각을 씁니다.
RECENT = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=10)


@pytest.fixture
def warm_db() -> Iterator[Session]:
    """시·도 용역 통계 예열에 필요한 최소 행만 가진 SQLite 세션."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autocommit=False, autoflush=False)()
    session.add_all(
        [
            BidAnnouncement(
                bid_ntce_no="WARM-A1",
                bid_ntce_ord="000",
                category="Servc",
                bid_ntce_nm="인천 청소 용역",
                dminstt_nm="인천광역시",
                bid_ntce_dt=RECENT,
                base_amount=100_000_000,
            ),
            BidAnnouncement(
                bid_ntce_no="WARM-A2",
                bid_ntce_ord="000",
                category="Servc",
                bid_ntce_nm="인천 경비 용역",
                dminstt_nm="인천광역시교육청",
                bid_ntce_dt=RECENT,
                base_amount=200_000_000,
            ),
            BidAnnouncement(
                bid_ntce_no="WARM-S1",
                bid_ntce_ord="000",
                category="Servc",
                bid_ntce_nm="서울 시설 관리 용역",
                dminstt_nm="서울특별시",
                bid_ntce_dt=RECENT,
                base_amount=150_000_000,
            ),
            BidResult(
                bid_ntce_no="WARM-A1",
                bid_ntce_ord="000",
                category="Servc",
                bid_ntce_nm="인천 청소 용역",
                dminstt_nm="인천광역시",
                bidwinnr_nm="가나다",
                sucsf_bid_rate=88.5,
                sucsf_bid_amt=90_000_000,
                rl_openg_dt=RECENT,
            ),
            BidResult(
                bid_ntce_no="WARM-S1",
                bid_ntce_ord="000",
                category="Servc",
                bid_ntce_nm="서울 시설 관리 용역",
                dminstt_nm="서울특별시",
                bidwinnr_nm="라마바",
                sucsf_bid_rate=91.2,
                sucsf_bid_amt=140_000_000,
                rl_openg_dt=RECENT,
            ),
        ]
    )
    session.commit()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def memory_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """Redis 없이 프로세스 메모리 캐시만 쓰게 만듭니다."""
    monkeypatch.setattr(cache._conn, "client", lambda: None)
    monkeypatch.setattr(cache, "_local", {})


@contextmanager
def _capture_sql(db: Session) -> Iterator[list[str]]:
    """세션이 실제로 실행한 SQL 문장을 모읍니다."""
    statements: list[str] = []

    def _before(conn, cursor, statement, parameters, context, executemany) -> None:
        statements.append(" ".join(statement.split()))

    engine = db.get_bind()
    event.listen(engine, "before_cursor_execute", _before)
    try:
        yield statements
    finally:
        event.remove(engine, "before_cursor_execute", _before)


def _aggregate_statements(statements: list[str]) -> list[str]:
    return [
        statement
        for statement in statements
        if any(marker in statement.lower() for marker in AGGREGATE_MARKERS)
    ]


# --------------------------------------------------------------------------- #
# (a) 예열 뒤 같은 질문이 캐시에서 답한다
# --------------------------------------------------------------------------- #


def test_every_warm_question_matches_chat_plan() -> None:
    """예열 계획이 챗봇 정형 분기와 같아야 캐시 키도 같아집니다."""
    questions = rag_stats_warm.warm_questions()

    assert len(questions) == len(rag_stats_warm.WARM_REGIONS) * len(
        rag_stats_warm.WARM_QUESTION_TEMPLATES
    )
    for question in questions:
        warm_plan = rag_stats_warm.build_warm_plan(question)
        chat_plan = _apply_entry_default_statistics_window(build_retrieval_plan(question))
        assert warm_plan.use_sql is True, question
        assert warm_plan.filters == chat_plan.filters, question
        assert warm_plan.insufficiency_hints == chat_plan.insufficiency_hints, question


@pytest.mark.parametrize(
    "question",
    ["인천 용역 낙찰률 알려줘", "인천 용역 공고 건수"],
)
def test_warmed_question_skips_aggregate_sql(
    warm_db: Session, memory_cache: None, question: str
) -> None:
    """예열 뒤 챗봇 정형 경로는 집계 SQL 을 다시 실행하지 않습니다.

    structured_data.py 는 캐시 계층이 없는 표본 목록 조회(LIMIT 9, 인덱스 범위)를
    항상 한 번 실행합니다. 이 Task 는 structured_data.py 를 수정하지 않으므로 그
    목록 조회는 남습니다. 여기서 고정하는 것은 20초대 집계 COUNT/AVG/SUM 과
    GROUP BY 순위 질의가 0건이라는 점입니다.
    """
    with _capture_sql(warm_db) as warm_sql:
        outcome = rag_stats_warm.warm_rag_region_stats(warm_db, questions=[question])

    assert outcome["status"] == "success"
    assert outcome["succeeded"] == 1
    assert _aggregate_statements(warm_sql), "예열이 집계 SQL 을 실행하지 않았습니다"
    keys = list(cache._local)
    assert any(key.startswith("rag:agg:") for key in keys)
    assert any(key.startswith("rag:top:") for key in keys)

    with _capture_sql(warm_db) as chat_sql:
        prepared = HybridRAGEngine()._prepare_context(question, db=warm_db)

    assert _aggregate_statements(chat_sql) == []
    # 캐시 계층이 없는 표본 목록 조회만 남습니다.
    assert all(" group by " not in statement.lower() for statement in chat_sql)
    assert len(chat_sql) <= 2, chat_sql
    assert prepared.structured_data["summary"]["announcement_count"] >= 1


def test_warm_does_not_call_llm(warm_db: Session, memory_cache: None, monkeypatch) -> None:
    """예열은 정형 경로만 돌므로 LLM 백엔드·실행기를 부르지 않습니다."""

    def _fail(*args, **kwargs):
        raise AssertionError("예열이 LLM 을 호출했습니다")

    monkeypatch.setattr("src.rag.llm.build_backend", _fail)
    monkeypatch.setattr("src.rag.llm_executor.run_in_llm_executor", _fail)

    outcome = rag_stats_warm.warm_rag_region_stats(warm_db, questions=["인천 용역 낙찰률 알려줘"])

    assert outcome["status"] == "success"


# --------------------------------------------------------------------------- #
# (b) 한 질문이 실패해도 나머지가 진행된다
# --------------------------------------------------------------------------- #


def test_failed_question_does_not_stop_the_rest(
    warm_db: Session, memory_cache: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    questions = ["서울 용역 낙찰률 알려줘", "부산 용역 낙찰률 알려줘", "제주 용역 낙찰률 알려줘"]
    attempted: list[str] = []
    original = rag_stats_warm.retrieve_structured_data

    def _flaky(db, plan):
        if "부산" in plan.semantic_query:
            attempted.append(plan.semantic_query)
            raise RuntimeError("집계 실패: first line\n두 번째 줄은 남기지 않습니다")
        attempted.append(plan.semantic_query)
        return original(db, plan)

    monkeypatch.setattr(rag_stats_warm, "retrieve_structured_data", _flaky)

    outcome = rag_stats_warm.warm_rag_region_stats(warm_db, questions=questions)

    assert len(attempted) == 3, "실패 뒤에도 다음 질문을 실행해야 합니다"
    assert outcome["status"] == "partial_success"
    assert outcome["succeeded"] == 2
    assert outcome["failed"] == 1
    assert outcome["question_count"] == 3
    assert outcome["failures"][0]["question"] == "부산 용역 낙찰률 알려줘"
    assert outcome["failures"][0]["error_type"] == "RuntimeError"
    assert "\n" not in outcome["failures"][0]["error"]


# --------------------------------------------------------------------------- #
# (c) 중복 실행 방지
# --------------------------------------------------------------------------- #


# claim 소유 표식. 값 자체를 비밀번호로 오인하지 않도록 이름을 달리 둡니다.
_CLAIM_OWNER = "warm-owner"


def _claim(
    status: scheduled_tasks.ScheduleClaimStatus = scheduled_tasks.ScheduleClaimStatus.ACQUIRED,
    token: str | None = _CLAIM_OWNER,
) -> scheduled_tasks.ScheduleClaimResult:
    return scheduled_tasks.ScheduleClaimResult(
        status=status,
        key=scheduled_tasks.RAG_STATS_WARM_CLAIM_KEY,
        owner=scheduled_tasks.RAG_STATS_WARM_SCHEDULE_NAME,
        ttl=scheduled_tasks.RAG_STATS_WARM_JOB_TIMEOUT_SECONDS,
        token=token,
    )


def test_warm_task_skips_when_previous_run_is_in_progress(monkeypatch) -> None:
    monkeypatch.setattr("src.tasks.worker.record_schedule_result", lambda *a, **k: None)
    monkeypatch.setattr(
        scheduled_tasks,
        "acquire_schedule_claim",
        lambda owner, **kwargs: _claim(
            status=scheduled_tasks.ScheduleClaimStatus.ALREADY_CLAIMED,
            token=None,
        ),
    )

    def _fail() -> dict[str, int]:
        raise AssertionError("선점을 얻지 못했는데 예열을 실행했습니다")

    monkeypatch.setattr(scheduled_tasks, "_warm_rag_stats_thread", _fail)

    outcome = asyncio.run(scheduled_tasks.warm_rag_region_stats_task({}))

    assert outcome == {"status": "skipped", "reason": "already_running"}


def test_warm_task_releases_claim_and_returns_counts(monkeypatch) -> None:
    monkeypatch.setattr("src.tasks.worker.record_schedule_result", lambda *a, **k: None)
    acquire = MagicMock(return_value=_claim())
    monkeypatch.setattr(scheduled_tasks, "acquire_schedule_claim", acquire)
    released: list[tuple[str, str]] = []
    monkeypatch.setattr(
        scheduled_tasks,
        "release_schedule_claim",
        lambda key, token: released.append((key, token)),
    )
    monkeypatch.setattr(
        scheduled_tasks,
        "_warm_rag_stats_thread",
        lambda: {"status": "success", "succeeded": 34, "failed": 0},
    )

    outcome = asyncio.run(scheduled_tasks.warm_rag_region_stats_task({}))

    assert outcome["status"] == "success"
    assert outcome["succeeded"] == 34
    assert acquire.call_args.kwargs["key"] == scheduled_tasks.RAG_STATS_WARM_CLAIM_KEY
    assert (
        acquire.call_args.kwargs["ttl_seconds"]
        == scheduled_tasks.RAG_STATS_WARM_JOB_TIMEOUT_SECONDS
    )
    assert released == [(scheduled_tasks.RAG_STATS_WARM_CLAIM_KEY, _CLAIM_OWNER)]


# --------------------------------------------------------------------------- #
# (d) 워커 크론 등록
# --------------------------------------------------------------------------- #


def test_warm_task_registered_in_worker_cron() -> None:
    jobs = [
        job
        for job in WorkerSettings.cron_jobs
        if getattr(getattr(job, "coroutine", job), "__name__", "") == "warm_rag_region_stats_task"
    ]

    assert len(jobs) == 1
    job = jobs[0]
    assert job.hour == scheduled_tasks.RAG_STATS_WARM_HOUR
    assert job.minute == scheduled_tasks.RAG_STATS_WARM_MINUTE
    assert job.run_at_startup is False
    assert job.timeout_s == scheduled_tasks.RAG_STATS_WARM_JOB_TIMEOUT_SECONDS
    assert job.timeout_s > WorkerSettings.job_timeout
    assert scheduled_tasks.warm_rag_region_stats_task in WorkerSettings.functions


# --------------------------------------------------------------------------- #
# (e) 수집 뒤 훅
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_nightly_schedule_warms_after_collection(isolated_db, monkeypatch) -> None:
    """야간 수집이 성공하면 그 직후 예열을 실행합니다."""
    monkeypatch.setattr(settings, "AUTOMATION_NIGHTLY_SCHEDULE_ENABLED", True, raising=False)
    monkeypatch.setattr("src.tasks.worker.record_schedule_result", lambda *a, **k: None)
    monkeypatch.setattr(scheduled_tasks, "SessionLocal", lambda: isolated_db)
    monkeypatch.setattr(scheduled_tasks, "acquire_schedule_claim", lambda owner, **k: _claim())
    monkeypatch.setattr(scheduled_tasks, "release_schedule_claim", lambda *a, **k: None)
    monkeypatch.setattr(
        scheduled_tasks,
        "run_automation_pipeline",
        AsyncMock(return_value={"status": "success"}),
    )
    for name in (
        "_rebuild_ranking_snapshots",
        "_rebuild_compare_stats_snapshots",
        "_rebuild_institution_stats",
        "_check_mysql_stats_freshness",
        "_check_restore_drill_freshness",
        "_check_search_index_parity",
    ):
        monkeypatch.setattr(scheduled_tasks, name, lambda: {"status": "success"})
    monkeypatch.setattr(
        scheduled_tasks, "_notify_search_index_parity", AsyncMock(return_value=None)
    )
    warm = MagicMock(return_value={"status": "success", "succeeded": 34})
    monkeypatch.setattr(scheduled_tasks, "_warm_rag_stats_thread", warm)
    isolated_db.close = lambda: None

    result = await scheduled_tasks.nightly_schedule_task({})

    assert result["status"] == "success"
    assert result["rag_stats_warm"]["succeeded"] == 34
    warm.assert_called_once()


@pytest.mark.asyncio
async def test_intraday_collect_warms_after_new_rows(isolated_db, monkeypatch) -> None:
    """증분 수집이 실제로 적재했을 때만 캐시를 다시 채웁니다."""
    monkeypatch.setattr(settings, "INTRADAY_COLLECT_ENABLED", True)
    monkeypatch.setattr("src.tasks.worker.record_schedule_result", lambda *a, **k: None)
    monkeypatch.setattr(scheduled_tasks, "utcnow", lambda: datetime(2026, 11, 22, 3, 0, 0))
    monkeypatch.setattr("src.tasks.worker.get_heavy_task_lock", lambda: asyncio.Lock())
    monkeypatch.setattr(scheduled_tasks, "acquire_schedule_claim", lambda owner, **k: _claim())
    monkeypatch.setattr(scheduled_tasks, "release_schedule_claim", lambda *a, **k: None)

    def _collect_thread(today: str, collected_since: datetime) -> dict:
        return {
            "collect": {"status": "success", "total_records": 5, "announcement_count": 5},
            "indexed": {"announcements": 5, "results": 0},
            "api_requests": 0,
            "api_rate_limited": 0,
            "collect_seconds": 0.0,
            "sync_seconds": 0.0,
        }

    monkeypatch.setattr(scheduled_tasks, "_intraday_collect_thread", _collect_thread)
    warm = AsyncMock(return_value={"status": "success", "succeeded": 34})
    monkeypatch.setattr(scheduled_tasks, "_run_rag_stats_warm", warm)

    outcome = await scheduled_tasks.intraday_collect_task({})

    assert outcome["status"] == "success"
    assert outcome["rag_stats_warm"]["succeeded"] == 34
    warm.assert_awaited_once()


@pytest.mark.asyncio
async def test_intraday_collect_skips_warm_without_new_rows(isolated_db, monkeypatch) -> None:
    """적재가 없으면 collect_bids 가 캐시를 비우지 않으므로 예열도 하지 않습니다."""
    monkeypatch.setattr(settings, "INTRADAY_COLLECT_ENABLED", True)
    monkeypatch.setattr("src.tasks.worker.record_schedule_result", lambda *a, **k: None)
    monkeypatch.setattr(scheduled_tasks, "utcnow", lambda: datetime(2026, 11, 22, 3, 0, 0))
    monkeypatch.setattr("src.tasks.worker.get_heavy_task_lock", lambda: asyncio.Lock())
    monkeypatch.setattr(scheduled_tasks, "acquire_schedule_claim", lambda owner, **k: _claim())
    monkeypatch.setattr(scheduled_tasks, "release_schedule_claim", lambda *a, **k: None)
    monkeypatch.setattr(
        scheduled_tasks,
        "_intraday_collect_thread",
        lambda today, collected_since: {
            "collect": {"status": "success", "total_records": 0},
            "indexed": {"announcements": 0, "results": 0},
            "api_requests": 0,
            "api_rate_limited": 0,
            "collect_seconds": 0.0,
            "sync_seconds": 0.0,
        },
    )
    warm = AsyncMock()
    monkeypatch.setattr(scheduled_tasks, "_run_rag_stats_warm", warm)

    outcome = await scheduled_tasks.intraday_collect_task({})

    assert outcome["status"] == "success"
    assert "rag_stats_warm" not in outcome
    warm.assert_not_awaited()

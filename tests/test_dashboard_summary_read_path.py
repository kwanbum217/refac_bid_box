"""
tests/test_dashboard_summary_read_path.py

대시보드 요약 읽기 경로와 비동기 재집계 쓰기 경로 분리 검증 테스트.

Fact 및 코디네이터 계약 검증 항목:
1. 스냅샷이 있고 stale 이면 조회가 재집계(rebuild)를 호출하지 않고 이전 스냅샷 값을 그대로 돌려준다.
2. stale 조회 시 재집계 작업이 정확히 한 번 등록된다.
3. 같은 stale 상태에서 조회가 여러 번 일어나도 큐에 고정 job id로 중복 등록되지 않는다.
4. 스냅샷이 없으면 동기 집계가 일어나고 분산 락(또는 프로세스 락)으로 한 번만 수행된다.
5. 조회가 fresh 면 아무 작업도 등록하지 않는다.
6. stale 상태일 때 대시보드 통계 캐시 TTL은 24시간이 아닌 60초 단기 TTL로 설정된다.
7. Redis 미가용 시에도 fail-open 없이 프로세스 락으로 초기 집계를 단일 제어한다.
8. arq 백그라운드 태스크 rebuild_dataset_summary_task 가 정상 동작한다.
"""

from datetime import datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from src.app.core.timeutil import utcnow
from src.app.models.bids import (
    DATASET_ANNOUNCEMENT,
    DATASET_RESULT,
    BidAnnouncement,
    BidDatasetSummary,
    BidResult,
)
from src.app.services.dashboard import (
    COMPARE_STATS_CACHE_TTL,
    COMPARE_STATS_STALE_CACHE_TTL,
    DASHBOARD_STATS_CACHE_TTL,
    DASHBOARD_STATS_STALE_CACHE_TTL,
    SUMMARY_ALGORITHM_VERSIONS,
    get_bid_dataset_summary,
    get_compare_stats_data,
    get_dashboard_stats,
    rebuild_bid_dataset_summary,
)
from src.tasks.summary_tasks import rebuild_dataset_summary_task


def _seed_announcement(db, **overrides) -> BidAnnouncement:
    now = utcnow()
    payload = {
        "bid_ntce_no": "TEST-ANN-READ-001",
        "bid_ntce_ord": "000",
        "bid_ntce_nm": "읽기 경로 테스트 공고",
        "dminstt_nm": "테스트 조달청",
        "category": "Thng",
        "base_amount": 2000000,
        "presmpt_prce": 2000000,
        "bid_ntce_dt": now,
        "collected_at": now,
    }
    payload.update(overrides)
    row = BidAnnouncement(**payload)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _seed_result(db, **overrides) -> BidResult:
    now = utcnow()
    payload = {
        "bid_ntce_no": "TEST-RES-READ-001",
        "bid_ntce_ord": "000",
        "bid_ntce_nm": "읽기 경로 테스트 낙찰",
        "bidwinnr_nm": "테스트 주식회사",
        "dminstt_nm": "테스트 수요기관",
        "category": "Servc",
        "sucsf_bid_amt": 1800000,
        "sucsf_bid_rate": Decimal("90.0000"),
        "rl_openg_dt": now,
        "collected_at": now,
    }
    payload.update(overrides)
    row = BidResult(**payload)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def test_stale_summary_returns_previous_snapshot_without_rebuild(isolated_db):
    """1. 스냅샷이 있고 stale 이면 조회가 rebuild 를 호출하지 않고 이전 스냅샷 값을 반환한다."""
    ann = _seed_announcement(isolated_db)
    expected_version = SUMMARY_ALGORITHM_VERSIONS[DATASET_ANNOUNCEMENT]

    old_rebuilt_at = datetime(2026, 9, 1, 10, 0, 0)
    old_summary = BidDatasetSummary(
        dataset=DATASET_ANNOUNCEMENT,
        total_count=10,
        total_amount=Decimal("50000000"),
        avg_rate=None,
        source_latest_collected_at=ann.collected_at,
        aggregation_version=expected_version - 1,  # stale: 이전 알고리즘 버전
        rebuilt_at=old_rebuilt_at,
    )
    isolated_db.add(old_summary)
    isolated_db.commit()

    with (
        patch("src.app.services.dashboard.rebuild_bid_dataset_summary") as mock_rebuild,
        patch("src.app.services.dashboard.enqueue_rebuild_dataset_summary") as mock_enqueue,
    ):
        result = get_bid_dataset_summary(isolated_db, DATASET_ANNOUNCEMENT)

        mock_rebuild.assert_not_called()
        mock_enqueue.assert_called_once_with(DATASET_ANNOUNCEMENT)

    assert result.is_stale is True
    assert result.total_count == 10
    assert result.total_amount == Decimal("50000000")
    assert result.aggregation_version == expected_version - 1
    assert result.rebuilt_at == old_rebuilt_at


def test_stale_summary_enqueues_rebuild_job_exactly_once(isolated_db):
    """2. stale 조회 시 재집계 작업이 정확히 한 번 등록된다."""
    ann = _seed_announcement(isolated_db)
    expected_version = SUMMARY_ALGORITHM_VERSIONS[DATASET_ANNOUNCEMENT]

    old_summary = BidDatasetSummary(
        dataset=DATASET_ANNOUNCEMENT,
        total_count=5,
        total_amount=Decimal("10000000"),
        avg_rate=None,
        source_latest_collected_at=ann.collected_at,
        aggregation_version=expected_version - 1,
        rebuilt_at=utcnow(),
    )
    isolated_db.add(old_summary)
    isolated_db.commit()

    with patch("src.app.services.dashboard.enqueue_rebuild_dataset_summary") as mock_enqueue:
        get_bid_dataset_summary(isolated_db, DATASET_ANNOUNCEMENT)
        mock_enqueue.assert_called_once_with(DATASET_ANNOUNCEMENT)


def test_repeated_stale_reads_do_not_duplicate_enqueue(isolated_db):
    """3. 같은 stale 상태에서 조회가 여러 번 일어나도 고정 job_id 로 enqueue 가 호출된다."""
    ann = _seed_announcement(isolated_db)
    expected_version = SUMMARY_ALGORITHM_VERSIONS[DATASET_ANNOUNCEMENT]

    old_summary = BidDatasetSummary(
        dataset=DATASET_ANNOUNCEMENT,
        total_count=5,
        total_amount=Decimal("10000000"),
        avg_rate=None,
        source_latest_collected_at=ann.collected_at,
        aggregation_version=expected_version - 1,
        rebuilt_at=utcnow(),
    )
    isolated_db.add(old_summary)
    isolated_db.commit()

    with patch("src.app.services.automation_jobs._enqueue_arq_job") as mock_arq_push:
        mock_arq_push.return_value = True

        # 연속 3회 stale 조회 수행
        for _ in range(3):
            summary = get_bid_dataset_summary(isolated_db, DATASET_ANNOUNCEMENT)
            assert summary.is_stale is True

        # 매 호출 시 동일한 고정 job_id 로 enqueue 시도됨 (arq 내부에서 중복 등록 방지)
        assert mock_arq_push.call_count == 3
        expected_job_id = f"rebuild_dataset_summary:{DATASET_ANNOUNCEMENT}"
        for call_args in mock_arq_push.call_args_list:
            assert call_args.args[0] == "rebuild_dataset_summary_task"
            assert call_args.kwargs["arq_job_id"] == expected_job_id
            assert call_args.kwargs["dataset"] == DATASET_ANNOUNCEMENT


def test_missing_summary_triggers_sync_rebuild_with_lock(isolated_db):
    """4. 스냅샷이 없으면 동기 집계가 일어나고 분산 락 하에서 1회만 수행된다."""
    _seed_announcement(isolated_db)

    # 초기 상태: summary 레코드가 없음
    assert isolated_db.get(BidDatasetSummary, DATASET_ANNOUNCEMENT) is None

    mock_client = MagicMock()
    mock_lock_ctx = MagicMock()
    mock_client.lock.return_value.__enter__ = MagicMock(return_value=mock_lock_ctx)
    mock_client.lock.return_value.__exit__ = MagicMock(return_value=False)

    with (
        patch("src.app.services.dashboard.cache._conn.client", return_value=mock_client),
        patch(
            "src.app.services.dashboard.rebuild_bid_dataset_summary",
            wraps=rebuild_bid_dataset_summary,
        ) as spy_rebuild,
    ):
        summary = get_bid_dataset_summary(isolated_db, DATASET_ANNOUNCEMENT)

        # 락이 올바른 키와 함께 획득되었는지 확인
        mock_client.lock.assert_called_once_with(
            f"lock:bid_dataset_summary:init:{DATASET_ANNOUNCEMENT}",
            timeout=600,
            blocking_timeout=30,
        )
        # 동기 rebuild 가 정확히 1회 수행됨
        assert spy_rebuild.call_count == 1
        assert summary is not None
        assert summary.is_stale is False
        assert summary.total_count == 1


def test_fresh_summary_does_not_enqueue_any_task(isolated_db):
    """5. 조회가 fresh 면 아무 재집계 작업도 등록하지 않는다."""
    ann = _seed_announcement(isolated_db)
    expected_version = SUMMARY_ALGORITHM_VERSIONS[DATASET_ANNOUNCEMENT]

    fresh_rebuilt_at = datetime(2026, 9, 4, 12, 0, 0)
    fresh_summary = BidDatasetSummary(
        dataset=DATASET_ANNOUNCEMENT,
        total_count=1,
        total_amount=Decimal("2000000"),
        avg_rate=None,
        source_latest_collected_at=ann.collected_at,
        aggregation_version=expected_version,
        rebuilt_at=fresh_rebuilt_at,
    )
    isolated_db.add(fresh_summary)
    isolated_db.commit()

    with (
        patch("src.app.services.dashboard.rebuild_bid_dataset_summary") as mock_rebuild,
        patch("src.app.services.dashboard.enqueue_rebuild_dataset_summary") as mock_enqueue,
    ):
        summary = get_bid_dataset_summary(isolated_db, DATASET_ANNOUNCEMENT)

        mock_rebuild.assert_not_called()
        mock_enqueue.assert_not_called()

    assert summary.is_stale is False
    assert summary.aggregation_version == expected_version
    assert summary.rebuilt_at == fresh_rebuilt_at


def test_stale_response_cached_with_short_ttl(isolated_db):
    """6. stale 상태일 때 대시보드 통계 응답은 24시간이 아닌 60초 단기 TTL 로 캐시된다."""
    res = _seed_result(isolated_db)
    ann = _seed_announcement(isolated_db)

    # stale 상태인 result summary 설정
    stale_result_summary = BidDatasetSummary(
        dataset=DATASET_RESULT,
        total_count=1,
        total_amount=Decimal("1800000"),
        avg_rate=Decimal("90.0000"),
        source_latest_collected_at=res.collected_at,
        aggregation_version=SUMMARY_ALGORITHM_VERSIONS[DATASET_RESULT] - 1,
        rebuilt_at=utcnow(),
    )
    isolated_db.add(stale_result_summary)

    # fresh 상태인 announcement summary 설정
    fresh_ann_summary = BidDatasetSummary(
        dataset=DATASET_ANNOUNCEMENT,
        total_count=1,
        total_amount=Decimal("2000000"),
        avg_rate=None,
        source_latest_collected_at=ann.collected_at,
        aggregation_version=SUMMARY_ALGORITHM_VERSIONS[DATASET_ANNOUNCEMENT],
        rebuilt_at=utcnow(),
    )
    isolated_db.add(fresh_ann_summary)
    isolated_db.commit()

    with (
        patch("src.app.services.dashboard.cache.get", return_value=None),
        patch("src.app.services.dashboard.cache.set") as mock_cache_set,
        patch("src.app.services.dashboard.enqueue_rebuild_dataset_summary"),
    ):
        # 1) get_dashboard_stats: result_summary 가 stale 이므로 60초 TTL 적용
        get_dashboard_stats(isolated_db)
        assert mock_cache_set.call_count == 1
        _, set_args, _ = mock_cache_set.mock_calls[0]
        # set(key, data, ttl)
        assert set_args[2] == DASHBOARD_STATS_STALE_CACHE_TTL
        assert set_args[2] != DASHBOARD_STATS_CACHE_TTL

        mock_cache_set.reset_mock()

        # 2) get_compare_stats_data: result_summary 가 stale 이므로 60초 TTL 적용
        get_compare_stats_data(isolated_db)
        assert mock_cache_set.call_count == 1
        _, set_args, _ = mock_cache_set.mock_calls[0]
        assert set_args[2] == COMPARE_STATS_STALE_CACHE_TTL
        assert set_args[2] != COMPARE_STATS_CACHE_TTL


def test_fresh_response_cached_with_standard_24h_ttl(isolated_db):
    """6-2. fresh 상태일 때 대시보드 통계 응답은 표준 24시간 TTL 로 캐시된다."""
    res = _seed_result(isolated_db)
    ann = _seed_announcement(isolated_db)

    fresh_result_summary = BidDatasetSummary(
        dataset=DATASET_RESULT,
        total_count=1,
        total_amount=Decimal("1800000"),
        avg_rate=Decimal("90.0000"),
        source_latest_collected_at=res.collected_at,
        aggregation_version=SUMMARY_ALGORITHM_VERSIONS[DATASET_RESULT],
        rebuilt_at=utcnow(),
    )
    fresh_ann_summary = BidDatasetSummary(
        dataset=DATASET_ANNOUNCEMENT,
        total_count=1,
        total_amount=Decimal("2000000"),
        avg_rate=None,
        source_latest_collected_at=ann.collected_at,
        aggregation_version=SUMMARY_ALGORITHM_VERSIONS[DATASET_ANNOUNCEMENT],
        rebuilt_at=utcnow(),
    )
    isolated_db.add(fresh_result_summary)
    isolated_db.add(fresh_ann_summary)
    isolated_db.commit()

    with (
        patch("src.app.services.dashboard.cache.get", return_value=None),
        patch("src.app.services.dashboard.cache.set") as mock_cache_set,
        patch("src.app.services.dashboard.enqueue_rebuild_dataset_summary"),
    ):
        get_dashboard_stats(isolated_db)
        assert mock_cache_set.call_count == 1
        _, set_args, _ = mock_cache_set.mock_calls[0]
        assert set_args[2] == DASHBOARD_STATS_CACHE_TTL

        mock_cache_set.reset_mock()

        get_compare_stats_data(isolated_db)
        assert mock_cache_set.call_count == 1
        _, set_args, _ = mock_cache_set.mock_calls[0]
        assert set_args[2] == COMPARE_STATS_CACHE_TTL


def test_missing_summary_redis_unavailable_uses_process_lock(isolated_db):
    """7. Redis 미가용 시에도 fail-open 없이 프로세스 락 하에서 1회만 초기 집계를 수행한다."""
    _seed_announcement(isolated_db)

    with (
        patch("src.app.services.dashboard.cache._conn.client", return_value=None),
        patch(
            "src.app.services.dashboard.rebuild_bid_dataset_summary",
            wraps=rebuild_bid_dataset_summary,
        ) as spy_rebuild,
    ):
        summary = get_bid_dataset_summary(isolated_db, DATASET_ANNOUNCEMENT)

        assert spy_rebuild.call_count == 1
        assert summary is not None
        assert summary.is_stale is False
        assert summary.total_count == 1


@pytest.mark.asyncio
async def test_rebuild_dataset_summary_task_executes_successfully(isolated_db):
    """8. arq 백그라운드 태스크 rebuild_dataset_summary_task 가 정상 동작한다."""
    _seed_announcement(isolated_db)

    # SessionLocal 을 isolated_db 세션을 제공하도록 모킹
    mock_session_factory = MagicMock()
    mock_session_factory.return_value.__enter__ = MagicMock(return_value=isolated_db)
    mock_session_factory.return_value.__exit__ = MagicMock(return_value=False)

    with patch("src.tasks.summary_tasks.SessionLocal", mock_session_factory):
        result = await rebuild_dataset_summary_task({}, DATASET_ANNOUNCEMENT)

    assert result["dataset"] == DATASET_ANNOUNCEMENT
    assert result["total_count"] == 1
    assert result["total_amount"] == 2000000
    assert result["aggregation_version"] == SUMMARY_ALGORITHM_VERSIONS[DATASET_ANNOUNCEMENT]
    assert result["rebuilt_at"] is not None

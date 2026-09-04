"""
tests/test_dashboard_summary_version.py

bid_dataset_summaries 집계 알고리즘 버전 기반 신선도 판정 및 비동기 재집계 등록 검증 테스트.

Fact 48 및 읽기/쓰기 분리 계약 검증 항목:
1. 저장된 버전이 기대 버전보다 낮으면 stale로 판정되어 (a) 이전 스냅샷이 반환되고 (b) 재집계 작업이 1회 등록된다.
2. 버전과 수집 시각이 모두 같으면 fresh로 판정되어 재집계 호출도 없고 작업 등록도 일어나지 않는다.
3. 재집계된 요약에 기대 버전이 기록된다.
4. 기존 announcement 행에 기본 버전 1이 부여되면 기대 버전 2와 달라 stale로 판정된다.
"""

from datetime import datetime
from decimal import Decimal
from unittest.mock import patch

from src.app.core.timeutil import utcnow
from src.app.models.bids import (
    DATASET_ANNOUNCEMENT,
    DATASET_RESULT,
    BidAnnouncement,
    BidDatasetSummary,
    BidResult,
)
from src.app.services.dashboard import (
    SUMMARY_ALGORITHM_VERSIONS,
    get_bid_dataset_summary,
    rebuild_bid_dataset_summary,
)


def _seed_announcement(db, **overrides) -> BidAnnouncement:
    now = utcnow()
    payload = {
        "bid_ntce_no": "TEST-ANN-001",
        "bid_ntce_ord": "000",
        "bid_ntce_nm": "테스트 공고",
        "dminstt_nm": "테스트 기관",
        "category": "Thng",
        "base_amount": 1000000,
        "presmpt_prce": 1000000,
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
        "bid_ntce_no": "TEST-RES-001",
        "bid_ntce_ord": "000",
        "bid_ntce_nm": "테스트 낙찰",
        "bidwinnr_nm": "테스트 업체",
        "dminstt_nm": "테스트 발주기관",
        "category": "Servc",
        "sucsf_bid_amt": 950000,
        "sucsf_bid_rate": Decimal("95.0000"),
        "rl_openg_dt": now,
        "collected_at": now,
    }
    payload.update(overrides)
    row = BidResult(**payload)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def test_summary_rebuilds_when_stored_version_is_lower_than_expected(isolated_db):
    """저장된 버전이 기대 버전보다 낮으면 stale로 판정되어 이전 스냅샷이 반환되고 재집계 작업이 등록된다."""
    ann = _seed_announcement(isolated_db)
    expected_version = SUMMARY_ALGORITHM_VERSIONS[DATASET_ANNOUNCEMENT]
    assert expected_version > 1

    # 원본 수집 시각과 동일하지만 버전이 이전 버전(1)인 stale 요약 저장
    old_summary = BidDatasetSummary(
        dataset=DATASET_ANNOUNCEMENT,
        total_count=1,
        total_amount=Decimal("-6063896128872295352"),
        avg_rate=None,
        source_latest_collected_at=ann.collected_at,
        aggregation_version=expected_version - 1,
        rebuilt_at=utcnow(),
    )
    isolated_db.add(old_summary)
    isolated_db.commit()

    with (
        patch("src.app.services.dashboard.rebuild_bid_dataset_summary") as mock_rebuild,
        patch("src.app.services.dashboard.enqueue_rebuild_dataset_summary") as mock_enqueue,
    ):
        # get_bid_dataset_summary 호출 시 버전 불일치로 인해 stale 판정
        returned_summary = get_bid_dataset_summary(isolated_db, DATASET_ANNOUNCEMENT)

        # 동기 rebuild 는 호출되지 않아야 함
        mock_rebuild.assert_not_called()
        # 재집계 작업이 정확히 한 번 등록되어야 함
        assert mock_enqueue.call_count == 1
        assert mock_enqueue.call_args.args[0] == DATASET_ANNOUNCEMENT

    # (a) 이전 스냅샷이 그대로 반환되고, stale 여부가 표시되어야 함
    assert returned_summary.is_stale is True
    assert returned_summary.aggregation_version == old_summary.aggregation_version
    assert returned_summary.total_amount == old_summary.total_amount
    assert returned_summary.total_count == old_summary.total_count


def test_summary_does_not_rebuild_when_version_and_collection_time_match(isolated_db):
    """버전과 수집 시각이 모두 같으면 재집계 및 작업 등록이 일어나지 않는다."""
    ann = _seed_announcement(isolated_db)
    expected_version = SUMMARY_ALGORITHM_VERSIONS[DATASET_ANNOUNCEMENT]

    original_rebuilt_at = datetime(2026, 9, 1, 12, 0, 0)
    existing_summary = BidDatasetSummary(
        dataset=DATASET_ANNOUNCEMENT,
        total_count=1,
        total_amount=Decimal("1000000"),
        avg_rate=None,
        source_latest_collected_at=ann.collected_at,
        aggregation_version=expected_version,
        rebuilt_at=original_rebuilt_at,
    )
    isolated_db.add(existing_summary)
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
    assert summary.rebuilt_at == original_rebuilt_at


def test_rebuilt_summary_records_expected_version(isolated_db):
    """재집계된 요약에 기대 버전이 기록된다."""
    _seed_announcement(isolated_db)
    _seed_result(isolated_db)

    ann_summary = rebuild_bid_dataset_summary(isolated_db, DATASET_ANNOUNCEMENT)
    assert ann_summary.aggregation_version == SUMMARY_ALGORITHM_VERSIONS[DATASET_ANNOUNCEMENT]

    res_summary = rebuild_bid_dataset_summary(isolated_db, DATASET_RESULT)
    assert res_summary.aggregation_version == SUMMARY_ALGORITHM_VERSIONS[DATASET_RESULT]


def test_existing_announcement_summary_with_default_version_is_stale(isolated_db):
    """기존 announcement 행에 마이그레이션 기본값(1)이 부여되면 기대 버전(2)과 달라 stale로 판정된다."""
    ann = _seed_announcement(isolated_db)

    legacy_summary = BidDatasetSummary(
        dataset=DATASET_ANNOUNCEMENT,
        total_count=5497840,
        total_amount=Decimal("-6063896128872295352"),
        avg_rate=None,
        source_latest_collected_at=ann.collected_at,
        aggregation_version=1,
        rebuilt_at=utcnow(),
    )
    isolated_db.add(legacy_summary)
    isolated_db.commit()

    with (
        patch("src.app.services.dashboard.rebuild_bid_dataset_summary") as mock_rebuild,
        patch("src.app.services.dashboard.enqueue_rebuild_dataset_summary") as mock_enqueue,
    ):
        summary = get_bid_dataset_summary(isolated_db, DATASET_ANNOUNCEMENT)
        mock_rebuild.assert_not_called()
        assert mock_enqueue.call_count == 1
        assert mock_enqueue.call_args.args[0] == DATASET_ANNOUNCEMENT

    assert summary.is_stale is True
    assert summary.aggregation_version == legacy_summary.aggregation_version
    assert summary.total_amount == legacy_summary.total_amount
    assert summary.total_count == legacy_summary.total_count

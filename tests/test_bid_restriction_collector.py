"""
tests/test_bid_restriction_collector.py

조달청 공고 면허제한정보 및 참가가능지역 수집기 단위 및 통합 테스트.
- XML 응답 파싱 및 필드 매핑 검증 (빈 문자열 NULL 변환, rgstDt datetime 변환)
- SQLite 인메모리 세션 기반 멱등 적재 검증 (COUNT 단언)
- collect_bids fetch_type 분기 검증 (both/announce 수집, result 미수집)
- 오류 마스킹 및 partial_success 상태 전이 검증
- total_records 보존 검증 (제한 건수 미가산)
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from src.app.core.db import Base
from src.app.models.bid_restrictions import (
    BidAnnouncementLicenseLimit,
    BidAnnouncementParticipationRegion,
)
from src.app.services.api_collector import (
    RangeCollectionError,
    _map_license_limit_item,
    _map_participation_region_item,
)
from src.app.services.collector_service import _bulk_insert, collect_bids

# ============================================================================
# 1. XML 응답 파싱 및 매퍼 검증
# ============================================================================


def test_map_license_limit_item_basic_and_conversions() -> None:
    """면허제한정보 XML을 매핑할 때 빈 문자열은 NULL, rgstDt는 datetime으로 변환되는지 검증."""
    xml_content = """
    <item>
        <bidNtceNo>R26BK01706806</bidNtceNo>
        <bidNtceOrd>000</bidNtceOrd>
        <lmtGrpNo>1</lmtGrpNo>
        <lmtSno>1</lmtSno>
        <lcnsLmtNm>정보통신공사업/0036</lcnsLmtNm>
        <permsnIndstrytyList>   </permsnIndstrytyList>
        <indstrytyMfrcFldList></indstrytyMfrcFldList>
        <rgstDt>2026-09-11 07:25:45</rgstDt>
        <bsnsDivNm>공사</bsnsDivNm>
    </item>
    """
    elem = ET.fromstring(xml_content.strip())  # nosec B314 # noqa: S314
    raw_data: dict[str, str] = {}
    row = _map_license_limit_item(elem, raw_data)

    assert row["bid_ntce_no"] == "R26BK01706806"
    assert row["bid_ntce_ord"] == "000"
    assert row["lmt_grp_no"] == "1"
    assert row["lmt_sno"] == "1"
    assert row["lcns_lmt_nm"] == "정보통신공사업/0036"
    assert row["permsn_indstryty_list"] is None
    assert row["indstryty_mfrc_fld_list"] is None
    assert row["rgst_dt"] == datetime(2026, 9, 11, 7, 25, 45)
    assert row["bsns_div_nm"] == "공사"


def test_map_license_limit_item_multiple_groups() -> None:
    """한 공고에 복수 그룹 및 순번이 존재할 때 원값을 그대로 보존하는지 검증."""
    xml_content_1 = """
    <item>
        <bidNtceNo>R26BK01706806</bidNtceNo>
        <bidNtceOrd>000</bidNtceOrd>
        <lmtGrpNo>1</lmtGrpNo>
        <lmtSno>1</lmtSno>
        <lcnsLmtNm>출판사/1517</lcnsLmtNm>
        <permsnIndstrytyList>출판사</permsnIndstrytyList>
        <rgstDt>2026-09-11 07:25:45</rgstDt>
        <bsnsDivNm>용역</bsnsDivNm>
    </item>
    """
    xml_content_2 = """
    <item>
        <bidNtceNo>R26BK01706806</bidNtceNo>
        <bidNtceOrd>000</bidNtceOrd>
        <lmtGrpNo>1</lmtGrpNo>
        <lmtSno>2</lmtSno>
        <lcnsLmtNm>인쇄사/1518</lcnsLmtNm>
        <permsnIndstrytyList>인쇄사</permsnIndstrytyList>
        <rgstDt>2026-09-11 07:25:45</rgstDt>
        <bsnsDivNm>용역</bsnsDivNm>
    </item>
    """
    elem1 = ET.fromstring(xml_content_1.strip())  # nosec B314 # noqa: S314
    elem2 = ET.fromstring(xml_content_2.strip())  # nosec B314 # noqa: S314

    row1 = _map_license_limit_item(elem1, {})
    row2 = _map_license_limit_item(elem2, {})

    assert row1["lmt_grp_no"] == "1"
    assert row1["lmt_sno"] == "1"
    assert row2["lmt_grp_no"] == "1"
    assert row2["lmt_sno"] == "2"
    assert row1["lcns_lmt_nm"] == "출판사/1517"
    assert row2["lcns_lmt_nm"] == "인쇄사/1518"


def test_map_participation_region_item_basic_and_conversions() -> None:
    """참가가능지역 XML 매핑 시 빈 문자열은 NULL, rgstDt는 datetime으로 변환되는지 검증."""
    xml_content = """
    <item>
        <bidNtceNo>R26BK01706806</bidNtceNo>
        <bidNtceOrd>000</bidNtceOrd>
        <lmtSno>1</lmtSno>
        <prtcptPsblRgnNm>충청남도 공주시</prtcptPsblRgnNm>
        <rgstDt>2026-09-11 07:25:45</rgstDt>
        <bsnsDivNm></bsnsDivNm>
    </item>
    """
    elem = ET.fromstring(xml_content.strip())  # nosec B314 # noqa: S314
    row = _map_participation_region_item(elem, {})

    assert row["bid_ntce_no"] == "R26BK01706806"
    assert row["bid_ntce_ord"] == "000"
    assert row["lmt_sno"] == "1"
    assert row["prtcpt_psbl_rgn_nm"] == "충청남도 공주시"
    assert row["rgst_dt"] == datetime(2026, 9, 11, 7, 25, 45)
    assert row["bsns_div_nm"] is None


# ============================================================================
# 2. SQLite 인메모리 멱등 적재 검증
# ============================================================================


@pytest.fixture
def sqlite_session():
    """SQLite 인메모리 DB 세션 픽스처."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            Base.metadata.tables["bid_announcement_license_limits"],
            Base.metadata.tables["bid_announcement_participation_regions"],
        ],
    )
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def test_license_limits_idempotent_insert(sqlite_session) -> None:
    """동일한 면허제한정보를 2회 적재해도 테이블 행 수가 증가하지 않음을 검증."""
    rows = [
        {
            "bid_ntce_no": "20260914001",
            "bid_ntce_ord": "000",
            "lmt_grp_no": "1",
            "lmt_sno": "1",
            "lcns_lmt_nm": "정보통신공사업/0036",
            "permsn_indstryty_list": None,
            "indstryty_mfrc_fld_list": None,
            "rgst_dt": datetime(2026, 9, 14, 10, 0, 0),
            "bsns_div_nm": "용역",
        },
        {
            "bid_ntce_no": "20260914001",
            "bid_ntce_ord": "000",
            "lmt_grp_no": "1",
            "lmt_sno": "2",
            "lcns_lmt_nm": "소프트웨어사업자/1426",
            "permsn_indstryty_list": None,
            "indstryty_mfrc_fld_list": None,
            "rgst_dt": datetime(2026, 9, 14, 10, 0, 0),
            "bsns_div_nm": "용역",
        },
    ]

    inserted_first = _bulk_insert(sqlite_session, BidAnnouncementLicenseLimit, rows)
    count_first = sqlite_session.scalar(select(func.count(BidAnnouncementLicenseLimit.id)))
    assert count_first == 2
    assert inserted_first == 2

    # 동일 데이터 2차 적재 시도
    inserted_second = _bulk_insert(sqlite_session, BidAnnouncementLicenseLimit, rows)
    count_second = sqlite_session.scalar(select(func.count(BidAnnouncementLicenseLimit.id)))
    assert count_second == 2
    assert inserted_second == 2


def test_participation_regions_idempotent_insert(sqlite_session) -> None:
    """동일한 참가가능지역을 2회 적재해도 테이블 행 수가 증가하지 않음을 검증."""
    rows = [
        {
            "bid_ntce_no": "20260914002",
            "bid_ntce_ord": "000",
            "lmt_sno": "1",
            "prtcpt_psbl_rgn_nm": "서울특별시",
            "rgst_dt": datetime(2026, 9, 14, 9, 30, 0),
            "bsns_div_nm": "물품",
        },
        {
            "bid_ntce_no": "20260914002",
            "bid_ntce_ord": "000",
            "lmt_sno": "2",
            "prtcpt_psbl_rgn_nm": "경기도",
            "rgst_dt": datetime(2026, 9, 14, 9, 30, 0),
            "bsns_div_nm": "물품",
        },
    ]

    _bulk_insert(sqlite_session, BidAnnouncementParticipationRegion, rows)
    count_first = sqlite_session.scalar(select(func.count(BidAnnouncementParticipationRegion.id)))
    assert count_first == 2

    _bulk_insert(sqlite_session, BidAnnouncementParticipationRegion, rows)
    count_second = sqlite_session.scalar(select(func.count(BidAnnouncementParticipationRegion.id)))
    assert count_second == 2


# ============================================================================
# 3. collect_bids 실행 분기 및 집계 미가산 검증
# ============================================================================


@pytest.mark.asyncio
async def test_collect_bids_fetch_type_announce_executes_restrictions() -> None:
    """fetch_type='announce' 일 때 공고 수집 후 면허제한 및 참가가능지역 수집이 각각 1회 실행되는지 검증."""
    mock_db = MagicMock()
    mock_db.get_bind.return_value.dialect.name = "sqlite"

    with (
        patch("src.app.services.collector_service.get_service_key", return_value="TEST_KEY"),
        patch(
            "src.app.services.collector_service._resolve_collection_window_thread",
            return_value=("20260901", "20260914", False),
        ),
        patch(
            "src.app.services.collector_service.stream_bid_announcements",
            new_callable=AsyncMock,
            return_value=10,
        ) as mock_stream_ann,
        patch(
            "src.app.services.collector_service.stream_bid_data",
            new_callable=AsyncMock,
        ) as mock_stream_data,
        patch(
            "src.app.services.collector_service.stream_bid_license_limits",
            new_callable=AsyncMock,
            return_value=5,
        ) as mock_stream_lic,
        patch(
            "src.app.services.collector_service.stream_bid_participation_regions",
            new_callable=AsyncMock,
            return_value=7,
        ) as mock_stream_rgn,
        patch("src.app.services.collector_service._warm_aggregates_and_caches_sync"),
    ):
        metrics = await collect_bids(
            mock_db,
            start_date="20260901",
            end_date="20260914",
            fetch_type="announce",
            categories=("Thng",),
            refresh_aggregates=False,
        )

        assert mock_stream_ann.await_count == 1
        assert mock_stream_data.await_count == 0
        assert mock_stream_lic.await_count == 1
        assert mock_stream_rgn.await_count == 1

        assert metrics["announcement_count"] == 10
        assert metrics["result_count"] == 0
        assert metrics["license_limit_count"] == 5
        assert metrics["participation_region_count"] == 7

        # total_records 에 새 수집 건수가 가산되지 않아야 함
        assert metrics["total_records"] == 10
        assert metrics["status"] == "success"
        assert metrics["failed_count"] == 0


@pytest.mark.asyncio
async def test_collect_bids_fetch_type_result_does_not_execute_restrictions() -> None:
    """fetch_type='result' 일 때 면허제한 및 참가가능지역 수집이 실행되지 않는지 검증."""
    mock_db = MagicMock()
    mock_db.get_bind.return_value.dialect.name = "sqlite"

    with (
        patch("src.app.services.collector_service.get_service_key", return_value="TEST_KEY"),
        patch(
            "src.app.services.collector_service._resolve_collection_window_thread",
            return_value=("20260901", "20260914", False),
        ),
        patch(
            "src.app.services.collector_service.stream_bid_announcements",
            new_callable=AsyncMock,
        ) as mock_stream_ann,
        patch(
            "src.app.services.collector_service.stream_bid_data",
            new_callable=AsyncMock,
            return_value=15,
        ) as mock_stream_data,
        patch(
            "src.app.services.collector_service.stream_bid_license_limits",
            new_callable=AsyncMock,
        ) as mock_stream_lic,
        patch(
            "src.app.services.collector_service.stream_bid_participation_regions",
            new_callable=AsyncMock,
        ) as mock_stream_rgn,
        patch("src.app.services.collector_service._warm_aggregates_and_caches_sync"),
    ):
        metrics = await collect_bids(
            mock_db,
            start_date="20260901",
            end_date="20260914",
            fetch_type="result",
            categories=("Thng",),
            refresh_aggregates=False,
        )

        assert mock_stream_ann.await_count == 0
        assert mock_stream_data.await_count == 1
        assert mock_stream_lic.await_count == 0
        assert mock_stream_rgn.await_count == 0

        assert metrics["announcement_count"] == 0
        assert metrics["result_count"] == 15
        assert metrics["license_limit_count"] == 0
        assert metrics["participation_region_count"] == 0
        assert metrics["total_records"] == 15
        assert metrics["status"] == "success"


# ============================================================================
# 4. 제한 수집 실패 시 오류 마스킹 및 partial_success 판정 검증
# ============================================================================


@pytest.mark.asyncio
async def test_collect_bids_restriction_failure_marks_partial_success_and_masks_credential() -> (
    None
):
    """면허제한정보 수집 실패 시 credentials가 마스킹되고 status가 partial_success가 되는지 검증."""
    mock_db = MagicMock()
    mock_db.get_bind.return_value.dialect.name = "sqlite"

    test_secret_token = "MY_SUPER_SECRET_G2B_KEY_999"  # noqa: S105
    error_url = f"https://apis.data.go.kr/license?serviceKey={test_secret_token}"

    with (
        patch("src.app.services.collector_service.get_service_key", return_value="TEST_KEY"),
        patch(
            "src.app.services.collector_service._resolve_collection_window_thread",
            return_value=("20260901", "20260914", False),
        ),
        patch(
            "src.app.services.collector_service.stream_bid_announcements",
            new_callable=AsyncMock,
            return_value=10,
        ),
        patch(
            "src.app.services.collector_service.stream_bid_license_limits",
            new_callable=AsyncMock,
            side_effect=RuntimeError(f"HTTP 연결 오류 발생: {error_url}"),
        ),
        patch(
            "src.app.services.collector_service.stream_bid_participation_regions",
            new_callable=AsyncMock,
            return_value=3,
        ),
        patch("src.app.services.collector_service._warm_aggregates_and_caches_sync"),
    ):
        metrics = await collect_bids(
            mock_db,
            start_date="20260901",
            end_date="20260914",
            fetch_type="announce",
            categories=("Thng",),
            refresh_aggregates=False,
        )

        assert metrics["status"] == "partial_success"
        assert metrics["failed_count"] == 1
        assert "restrictions" in metrics
        assert "license_limit_error" in metrics["restrictions"]

        error_msg = metrics["restrictions"]["license_limit_error"]
        assert test_secret_token not in error_msg
        assert "serviceKey=***" in error_msg


@pytest.mark.asyncio
async def test_collect_bids_restriction_partial_failure_records_failed_ranges() -> None:
    """체크포인트가 공고 MAX(date) 라 제한 수집 실패 구간은 수동 백필 근거로 남아야 합니다."""
    mock_db = MagicMock()
    mock_db.get_bind.return_value.dialect.name = "sqlite"

    with (
        patch("src.app.services.collector_service.get_service_key", return_value="TEST_KEY"),
        patch(
            "src.app.services.collector_service._resolve_collection_window_thread",
            return_value=("20260901", "20260914", False),
        ),
        patch(
            "src.app.services.collector_service.stream_bid_announcements",
            new_callable=AsyncMock,
            return_value=10,
        ),
        patch(
            "src.app.services.collector_service.stream_bid_license_limits",
            new_callable=AsyncMock,
            side_effect=RangeCollectionError("면허제한정보", 7, [("20260901", "20260907")]),
        ),
        patch(
            "src.app.services.collector_service.stream_bid_participation_regions",
            new_callable=AsyncMock,
            side_effect=RangeCollectionError("참가가능지역", 2, [("20260908", "20260914")]),
        ),
    ):
        metrics = await collect_bids(
            mock_db,
            start_date="20260901",
            end_date="20260914",
            fetch_type="announce",
            categories=("Thng",),
            refresh_aggregates=False,
        )

    assert metrics["status"] == "partial_success"
    assert metrics["license_limit_count"] == 7
    assert metrics["participation_region_count"] == 2
    assert metrics["failed_ranges"] == [
        {
            "category": None,
            "kind": "license_limit",
            "start_date": "20260901",
            "end_date": "20260907",
        },
        {
            "category": None,
            "kind": "participation_region",
            "start_date": "20260908",
            "end_date": "20260914",
        },
    ]


# ============================================================================
# 5. ORM 모델 및 마이그레이션 메타데이터 검증
# ============================================================================


def test_models_metadata_integrity() -> None:
    """신규 모델의 테이블 정의, 유니크 제약, 외래 키 부재 검증."""
    table_lic = Base.metadata.tables["bid_announcement_license_limits"]
    table_rgn = Base.metadata.tables["bid_announcement_participation_regions"]

    # 외래 키 없음을 검증
    assert len(table_lic.foreign_keys) == 0
    assert len(table_rgn.foreign_keys) == 0

    # 유니크 제약 검증
    lic_unique_cols = [
        set(uq.columns.keys())
        for uq in table_lic.constraints
        if getattr(uq, "columns", None) and len(uq.columns) == 4
    ]
    assert {"bid_ntce_no", "bid_ntce_ord", "lmt_grp_no", "lmt_sno"} in lic_unique_cols

    rgn_unique_cols = [
        set(uq.columns.keys())
        for uq in table_rgn.constraints
        if getattr(uq, "columns", None) and len(uq.columns) == 3
    ]
    assert {"bid_ntce_no", "bid_ntce_ord", "lmt_sno"} in rgn_unique_cols

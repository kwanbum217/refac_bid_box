"""
tests/test_prearng_prices.py

개찰결과 예비가격 상세(용역) 수집기와 사정률 분포 재집계 검증.

막으려는 사고:
  - 15행을 1행으로 집약하지 못해 child 1,790만 행이 생기거나 사정률이 틀리는 것
  - 두 오류 봉투 중 하나를 검사하지 않아 오류를 정상 데이터로 적재하는 것
  - 06/07 을 조용히 건너뛰어 그 창이 영구 누락되는 것
  - 창 분할이 YYYYMMDDHHMM 규약을 어겨 전 창이 resultCode 06 으로 실패하는 것
  - INSERT IGNORE 멱등성이 깨져 재실행마다 행이 늘어나는 것
  - 사정률 대체 순서와 최소 표본이 어긋나 근거 없는 최저/최상가를 내는 것
  - 소급 스크립트가 명시 플래그 없이 실제 호출·적재를 하는 것

HTTP 는 mock 한 응답 표본으로, DB 는 SQLite 인메모리로 검증합니다.
"""

from __future__ import annotations

import itertools
from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from src.app.core.db import Base
from src.app.core.timeutil import utcnow
from src.app.models.prearng_prices import BidPrearngPrice, InstitutionSajeongRateStat
from src.app.services import api_collector
from src.app.services.api_collector import (
    PrearngResponseError,
    RangeCollectionError,
    _parse_prearng_payload,
    aggregate_prearng_prices,
    compute_sajeong_rate,
    fetch_servc_prearng_detail,
    map_prearng_price_row,
    split_prearng_month_windows,
    stream_servc_prearng_range,
)
from src.app.services.collector_service import _bulk_insert
from src.app.services.sajeong_rate_stats import (
    derive_sido,
    lookup_sajeong_rate_range,
    rebuild_institution_sajeong_rate_stats,
)

# ============================================================================
# 공통 표본: 보고서 4장 구조 (공고 1건 = 15행, drwtYn=Y 4개)
# ============================================================================

BID_NTCE_NO = "R25BK01250632"


def _prearng_item(sno: int, *, drwt: str = "N", drwt_num: int = 0) -> dict:
    return {
        "bidNtceNo": BID_NTCE_NO,
        "bidNtceOrd": "000",
        "bidClsfcNo": "0",
        "rbidNo": "000",
        "bidNtceNm": "PQ 후 가격입찰 공고",
        "plnprc": "1974820700",
        "bssamt": "1981548000",
        "totRsrvtnPrceNum": "15",
        "bidwinrSlctnAplBssCntnts": "행자부",
        "bssamtBssUpNum": "7",
        "compnoRsrvtnPrceMkngDt": "2026-01-08 15:29:08",
        "rlOpengDt": "2026-01-08 15:34:16",
        "inptDt": "2026-01-08 15:34:16",
        "compnoRsrvtnPrceSno": str(sno),
        "bsisPlnprc": str(1927075300 + sno * 1000),
        "drwtYn": drwt,
        "drwtNum": str(drwt_num),
    }


def _sample_items(count: int = 15) -> list[dict]:
    """15행 표본. 앞 4행을 추첨(Y)으로 둡니다."""
    return [
        _prearng_item(sno, drwt="Y" if sno <= 4 else "N", drwt_num=2 if sno <= 4 else 0)
        for sno in range(1, count + 1)
    ]


def _payload(items: list[dict], total: int | None = None) -> dict:
    return {
        "response": {
            "header": {"resultCode": "00", "resultMsg": "NORMAL SERVICE."},
            "body": {
                "items": {"item": items},
                "totalCount": total if total is not None else len(items),
                "pageNo": 1,
                "numOfRows": 500,
            },
        }
    }


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class _FakeClient:
    def __init__(self, pages: dict[int, dict]) -> None:
        self._pages = pages
        self.calls: list[dict] = []

    async def get(self, url: str, params: dict | None = None, timeout: int | None = None):
        self.calls.append(dict(params or {}))
        page_no = int((params or {}).get("pageNo", 1))
        return _FakeResponse(self._pages.get(page_no, _payload([])))

    async def __aenter__(self) -> _FakeClient:
        return self

    async def __aexit__(self, *exc_info) -> bool:
        return False


@pytest.fixture
def install_fake_http(monkeypatch):
    """api_collector 의 httpx.AsyncClient 를 가짜 클라이언트로 바꿉니다."""

    def _install(pages: dict[int, dict]) -> _FakeClient:
        client = _FakeClient(pages)
        monkeypatch.setattr(
            api_collector, "httpx", SimpleNamespace(AsyncClient=lambda *a, **k: client)
        )
        return client

    return _install


# ============================================================================
# 1. 매퍼·집약·사정률
# ============================================================================


def test_map_prearng_price_row_maps_fields() -> None:
    row = map_prearng_price_row(_prearng_item(1, drwt="Y", drwt_num=2))

    assert row["bid_ntce_no"] == BID_NTCE_NO
    assert row["bid_ntce_ord"] == "000"
    assert row["bid_clsfc_no"] == "0"
    assert row["rbid_no"] == "000"
    assert row["category"] == "Servc"
    assert row["bssamt"] == 1_981_548_000
    assert row["plnprc"] == 1_974_820_700
    assert row["tot_prce_num"] == 15
    assert row["bss_up_num"] == 7
    assert row["slctn_bss"] == "행자부"
    assert row["sno"] == 1
    assert row["bsis_plnprc"] == 1_927_076_300
    assert row["drwt_yn"] == "Y"
    assert row["drwt_num"] == 2
    assert row["rl_openg_dt"] == datetime(2026, 1, 8, 15, 34, 16)
    assert row["mkng_dt"] == datetime(2026, 1, 8, 15, 29, 8)


def test_compute_sajeong_rate_rounds_to_four_decimals() -> None:
    assert compute_sajeong_rate(1_974_820_700, 1_981_548_000) == Decimal("99.6605")
    assert compute_sajeong_rate(None, 1000) is None
    assert compute_sajeong_rate(1000, 0) is None


def test_aggregate_15_rows_into_single_row() -> None:
    rows = [map_prearng_price_row(item) for item in _sample_items(15)]
    aggregated = aggregate_prearng_prices(rows)

    assert len(aggregated) == 1
    row = aggregated[0]
    assert row["sajeong_rate"] == Decimal("99.6605")
    assert row["drwt_prce_num"] == 4
    assert row["tot_prce_num"] == 15
    assert len(row["items"]) == 15
    assert row["items"][0]["sno"] == 1
    assert row["items"][-1]["sno"] == 15
    assert row["raw_data"] is not None
    assert len(row["raw_data"]) == 15


def test_aggregate_skips_rows_without_notice_number() -> None:
    assert aggregate_prearng_prices([{"bid_ntce_no": ""}, {"bid_ntce_no": None}]) == []


# ============================================================================
# 2. 오류 봉투 두 종류와 06/07 실패 원장
# ============================================================================


def test_gateway_error_envelope_is_detected() -> None:
    payload = {
        "nkoneps.com.response.ResponseError": {
            "header": {"resultCode": "06", "resultMsg": "DATE Format 에러"}
        }
    }
    with pytest.raises(PrearngResponseError) as excinfo:
        _parse_prearng_payload(payload)

    assert excinfo.value.result_code == "06"
    assert excinfo.value.retryable is False


def test_normal_envelope_error_code_is_detected() -> None:
    payload = {
        "response": {
            "header": {"resultCode": "07", "resultMsg": "입력범위값 초과 에러"},
            "body": {},
        }
    }
    with pytest.raises(PrearngResponseError) as excinfo:
        _parse_prearng_payload(payload)

    assert excinfo.value.result_code == "07"
    assert excinfo.value.retryable is False


def test_non_retryable_code_is_marked_retryable_false() -> None:
    assert PrearngResponseError("06", "x").retryable is False
    assert PrearngResponseError("07", "x").retryable is False
    assert PrearngResponseError("01", "x").retryable is True


@pytest.mark.asyncio
async def test_gateway_error_window_is_recorded_as_failed(install_fake_http) -> None:
    payload = {
        "nkoneps.com.response.ResponseError": {
            "header": {"resultCode": "06", "resultMsg": "DATE Format 에러"}
        }
    }
    install_fake_http({1: payload})
    captured: list[list[dict]] = []

    with pytest.raises(RangeCollectionError) as excinfo:
        await stream_servc_prearng_range(
            "2026-01", "2026-01", lambda rows: captured.append(rows) or len(rows)
        )

    assert captured == []
    assert excinfo.value.saved == 0
    assert excinfo.value.failed_ranges == [("202601010000", "202601312359")]


@pytest.mark.asyncio
async def test_envelope_range_error_window_is_recorded_as_failed(install_fake_http) -> None:
    payload = {
        "response": {
            "header": {"resultCode": "07", "resultMsg": "입력범위값 초과 에러"},
            "body": {},
        }
    }
    install_fake_http({1: payload})

    with pytest.raises(RangeCollectionError) as excinfo:
        await stream_servc_prearng_range("2026-02", "2026-02", lambda rows: len(rows))

    assert excinfo.value.failed_ranges == [("202602010000", "202602282359")]


# ============================================================================
# 3. 창 분할과 페이지 순회
# ============================================================================


def test_split_prearng_month_windows_uses_calendar_months() -> None:
    windows = split_prearng_month_windows("2026-01", "2026-03")

    assert windows == [
        ("202601010000", "202601312359"),
        ("202602010000", "202602282359"),
        ("202603010000", "202603312359"),
    ]


def test_split_prearng_month_windows_rejects_bad_input() -> None:
    with pytest.raises(ValueError):
        split_prearng_month_windows("2026-01-01", "2026-03")
    with pytest.raises(ValueError):
        split_prearng_month_windows("2026-05", "2026-03")


@pytest.mark.asyncio
async def test_stream_range_uses_yyyymmddhhmm_and_sink(install_fake_http) -> None:
    client = install_fake_http({1: _payload(_sample_items(15), total=15)})
    captured: list[list[dict]] = []

    def _sink(rows: list[dict]) -> int:
        captured.append(rows)
        return len(rows)

    saved = await stream_servc_prearng_range("2026-01", "2026-01", _sink)

    assert saved == 1
    assert len(captured) == 1
    assert captured[0][0]["sajeong_rate"] == Decimal("99.6605")
    params = client.calls[0]
    assert params["inqryDiv"] == "1"
    assert params["inqryBgnDt"] == "202601010000"
    assert params["inqryEndDt"] == "202601312359"
    assert params["numOfRows"] == "500"


@pytest.mark.asyncio
async def test_stream_range_fetches_all_pages(install_fake_http) -> None:
    client = install_fake_http(
        {
            1: _payload(_sample_items(15), total=600),
            2: _payload(_sample_items(15), total=600),
        }
    )
    captured: list[list[dict]] = []

    saved = await stream_servc_prearng_range(
        "2026-01", "2026-01", lambda rows: captured.append(rows) or len(rows)
    )

    assert saved == 1
    assert {int(call["pageNo"]) for call in client.calls} == {1, 2}
    assert len(captured[0][0]["items"]) == 30


@pytest.mark.asyncio
async def test_fetch_single_notice_uses_inquiry_div_two(install_fake_http) -> None:
    client = install_fake_http({1: _payload(_sample_items(15), total=15)})

    aggregated = await fetch_servc_prearng_detail(BID_NTCE_NO)

    assert len(aggregated) == 1
    assert aggregated[0]["bid_ntce_no"] == BID_NTCE_NO
    params = client.calls[0]
    assert params["inqryDiv"] == "2"
    assert params["bidNtceNo"] == BID_NTCE_NO
    assert "inqryBgnDt" not in params


# ============================================================================
# 4. INSERT IGNORE 멱등성
# ============================================================================


@pytest.fixture
def prearng_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[Base.metadata.tables["bid_prearng_prices"]])
    factory = sessionmaker(bind=engine)
    session = factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def test_bulk_insert_is_idempotent(prearng_session) -> None:
    rows = aggregate_prearng_prices([map_prearng_price_row(item) for item in _sample_items(15)])

    _bulk_insert(prearng_session, BidPrearngPrice, rows)
    first = prearng_session.scalar(select(func.count(BidPrearngPrice.id)))
    assert first == 1

    _bulk_insert(prearng_session, BidPrearngPrice, rows)
    second = prearng_session.scalar(select(func.count(BidPrearngPrice.id)))
    assert second == 1


# ============================================================================
# 5. 사정률 재집계 대체 순서와 최소 표본
# ============================================================================


def test_derive_sido_normalizes_and_matches() -> None:
    assert derive_sido("서울특별시") == "서울특별시"
    assert derive_sido("서울특별시교육청") == "서울특별시"
    assert derive_sido("경기도 수원시") == "경기도"
    assert derive_sido("전라남도청") == "전남광주통합특별시"
    assert derive_sido("알수없는기관") is None
    assert derive_sido(None) is None


@pytest.fixture
def stats_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            Base.metadata.tables["bid_prearng_prices"],
            Base.metadata.tables["institution_sajeong_rate_stats"],
        ],
    )
    factory = sessionmaker(bind=engine)
    session = factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


_counter = itertools.count(1)


def _add_price(session, *, name: str, rate: float, category: str = "Servc") -> None:
    idx = next(_counter)
    session.add(
        BidPrearngPrice(
            bid_ntce_no=f"R25BK{idx:06d}",
            bid_ntce_ord="000",
            bid_clsfc_no="0",
            rbid_no="000",
            category=category,
            dminstt_nm=name,
            bssamt=1000,
            plnprc=int(rate * 10),
            sajeong_rate=Decimal(str(rate)),
            rl_openg_dt=utcnow(),
        )
    )


def _seed_stats(session) -> None:
    for index in range(30):
        _add_price(session, name="서울특별시", rate=90.0 + index * 0.1)
    for index in range(25):
        _add_price(session, name="경기도 수원시", rate=91.0 + index * 0.1)
    for index in range(25):
        _add_price(session, name="경기도 성남시", rate=91.0 + index * 0.1)
    for index in range(10):
        _add_price(session, name="부산광역시", rate=89.0 + index * 0.1)
    session.commit()


def test_rebuild_creates_three_scopes(stats_session) -> None:
    _seed_stats(stats_session)

    outcome = rebuild_institution_sajeong_rate_stats(stats_session)

    assert outcome["institution_rows"] == 1
    assert outcome["region_rows"] == 1
    assert outcome["category_rows"] == 1
    rows = stats_session.scalars(select(InstitutionSajeongRateStat)).all()
    scopes = {row.scope for row in rows}
    assert scopes == {"institution", "region", "category"}


def test_lookup_prefers_institution_then_region_then_category(stats_session) -> None:
    _seed_stats(stats_session)
    rebuild_institution_sajeong_rate_stats(stats_session)

    institution = lookup_sajeong_rate_range("서울특별시", "Servc", session=stats_session)
    assert institution["scope"] == "institution"
    assert institution["sample_count"] == 30
    assert float(institution["min_rate"]) == 90.0
    assert float(institution["max_rate"]) == 92.9

    region = lookup_sajeong_rate_range("경기도 수원시", "Servc", session=stats_session)
    assert region["scope"] == "region"
    assert region["institution_name"] == "경기도"
    assert region["sample_count"] == 50

    category = lookup_sajeong_rate_range("부산광역시", "Servc", session=stats_session)
    assert category["scope"] == "category"
    assert category["sample_count"] == 90

    missing = lookup_sajeong_rate_range("서울특별시", "Thng", session=stats_session)
    assert missing["scope"] == "none"
    assert missing["min_rate"] is None


def test_rebuild_excludes_rows_outside_window(stats_session) -> None:
    _add_price(stats_session, name="서울특별시", rate=95.0)
    stale = stats_session.scalars(select(BidPrearngPrice)).one()
    stale.rl_openg_dt = utcnow() - timedelta(days=2000)
    stats_session.commit()

    outcome = rebuild_institution_sajeong_rate_stats(stats_session)

    assert outcome["rows"] == 0


# ============================================================================
# 6. 소급 스크립트 기본 dry-run
# ============================================================================


def test_backfill_parser_defaults_to_dry_run() -> None:
    from scripts import backfill_prearng_prices as backfill

    args = backfill.build_parser().parse_args(["--start", "2026-01", "--end", "2026-02"])
    assert args.execute is False


def test_backfill_dry_run_does_not_call_collector(monkeypatch, capsys) -> None:
    from scripts import backfill_prearng_prices as backfill

    spy = AsyncMock(return_value=0)
    monkeypatch.setattr(backfill, "stream_servc_prearng_range", spy)

    exit_code = backfill.run(["--start", "2026-01", "--end", "2026-02"])

    assert exit_code == 0
    assert spy.await_count == 0
    output = capsys.readouterr().out
    assert "dry-run" in output
    assert "대상 월 창 2개" in output


def test_backfill_execute_flag_is_required_for_writes() -> None:
    from scripts import backfill_prearng_prices as backfill

    args = backfill.build_parser().parse_args(
        ["--start", "2026-01", "--end", "2026-02", "--execute"]
    )
    assert args.execute is True

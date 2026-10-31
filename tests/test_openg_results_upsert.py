"""
tests/test_openg_results_upsert.py

T3 검증: `collect_bids` 의 개찰결과 스텝과 `bid_openg_results` upsert 적재.

고정할 계약은 네 가지입니다.
  - 같은 창을 두 번 적재해도 행 수가 늘지 않고 first_seen_at 이 유지됩니다.
  - 두 번째 응답에서 상태가 바뀌면 progrs_div_cd_nm 이 갱신됩니다.
  - 개찰결과 스텝 실패가 공고·낙찰 스텝을 막지 않습니다.
  - 플래그가 꺼져 있으면 스텝을 건너뜁니다.

외부 조달청 API 는 호출하지 않습니다. 수집 경로는 고정 XML 을 돌려주는 가짜
httpx 클라이언트로만 돌리고, 서비스 키도 쓰지 않습니다.

설계 정본: docs/analysis/fail_bid_collection_design_20261031.md 3.3·4.2·8장.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.dialects import mysql as mysql_dialect
from sqlalchemy.dialects import sqlite as sqlite_dialect

import src.app.services.api_collector as ac
import src.app.services.collector_service as svc
from src.app.models.openg_results import BidOpengResult
from src.app.services.api_collector import RangeCollectionError

START_DATE = "20260818"
END_DATE = "20260818"


def _openg_item_xml(status: str, notice_no: str = "20260818123") -> str:
    return (
        "<item>"
        f"<bidNtceNo>{notice_no}</bidNtceNo>"
        "<bidNtceOrd>000</bidNtceOrd>"
        "<rbidNo>000</rbidNo>"
        "<bidClsfcNo>0</bidClsfcNo>"
        "<bidNtceNm>도로 보수 공사</bidNtceNm>"
        "<dminsttNm>서울특별시</dminsttNm>"
        "<opengDt>2026/08/18 11:00:00</opengDt>"
        f"<progrsDivCdNm>{status}</progrsDivCdNm>"
        "<prtcptCnum>0</prtcptCnum>"
        "<opengCorpInfo>&lt;corp&gt;대표자 홍길동&lt;/corp&gt;</opengCorpInfo>"
        "</item>"
    )


def _response_xml(items: str, total_count: int = 1) -> str:
    return (
        "<response>"
        "<header><resultCode>00</resultCode><resultMsg>OK</resultMsg></header>"
        f"<body><totalCount>{total_count}</totalCount><items>{items}</items></body>"
        "</response>"
    )


def _xml_response(xml: str) -> httpx.Response:
    return httpx.Response(
        200,
        text=xml,
        request=httpx.Request("GET", "https://example.invalid/api"),
    )


class _FakeAsyncClient:
    """준비한 응답을 순서대로 돌려줍니다."""

    def __init__(self, responses: list[httpx.Response]) -> None:
        self._responses = responses

    async def __aenter__(self) -> _FakeAsyncClient:
        return self

    async def __aexit__(self, *exc_info) -> bool:
        return False

    async def get(self, url: str, params=None, timeout=None) -> httpx.Response:
        if not self._responses:
            raise AssertionError("준비한 응답을 모두 소진했습니다")
        return self._responses.pop(0)


def _install_fake_client(monkeypatch, responses: list[httpx.Response]) -> None:
    def factory(*args, **kwargs) -> _FakeAsyncClient:
        return _FakeAsyncClient(responses)

    monkeypatch.setattr(ac.httpx, "AsyncClient", factory)


class _Clock:
    """utcnow 대역. 테스트가 관측 시각을 단계적으로 옮깁니다."""

    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


def _openg_row(status: str) -> dict:
    """매퍼가 내는 행과 같은 모양입니다(기본값 컬럼 제외)."""
    return {
        "bid_ntce_no": "20260818123",
        "bid_ntce_ord": "000",
        "rbid_no": "000",
        "bid_clsfc_no": "0",
        "category": "Cnstwk",
        "progrs_div_cd_nm": status,
        "prtcpt_cnum": 0,
        "bid_ntce_nm": "도로 보수 공사",
        "dminstt_nm": "서울특별시",
        "openg_dt": datetime(2026, 8, 18, 11, 0, 0),
        "raw_data": {"progrsDivCdNm": status, "bidNtceNo": "20260818123"},
    }


def _row_count(db) -> int:
    return int(db.scalar(select(func.count()).select_from(BidOpengResult)) or 0)


def _single_row(db) -> BidOpengResult:
    return db.scalars(select(BidOpengResult)).one()


def _statement_for(dialect_name: str):
    """방언 이름만 가진 가짜 세션으로 upsert 문을 만듭니다."""
    bind = SimpleNamespace(dialect=SimpleNamespace(name=dialect_name))
    db = SimpleNamespace(get_bind=lambda: bind)
    return svc._openg_result_upsert_statement(db).values(**_openg_row("유찰"))


def _update_clause(sql: str, marker: str) -> str:
    return sql.split(marker, 1)[1]


def _prepare_collect_bids(monkeypatch, clock: _Clock) -> None:
    monkeypatch.setattr(svc, "utcnow", clock)
    monkeypatch.setattr(svc, "get_service_key", lambda: "dummy-key")
    monkeypatch.setattr(svc, "OPENG_RESULT_COLLECTION_ENABLED", True)


# --------------------------------------------------------------------------- #
# upsert 적재
# --------------------------------------------------------------------------- #


def test_upsert_twice_keeps_rows_and_first_seen_at(isolated_db, monkeypatch):
    """같은 키를 두 번 적재해도 행은 1건이고 first_seen_at 은 첫 관측값입니다."""
    clock = _Clock(datetime(2026, 8, 19, 9, 0, 0))
    monkeypatch.setattr(svc, "utcnow", clock)

    assert svc._upsert_openg_results(isolated_db, [_openg_row("유찰")]) == 1
    first_seen = _single_row(isolated_db).first_seen_at

    clock.now = datetime(2026, 8, 20, 9, 0, 0)
    assert svc._upsert_openg_results(isolated_db, [_openg_row("유찰")]) == 1

    assert _row_count(isolated_db) == 1
    row = _single_row(isolated_db)
    assert row.first_seen_at == first_seen
    assert row.last_seen_at == datetime(2026, 8, 20, 9, 0, 0)
    assert row.collected_at == datetime(2026, 8, 20, 9, 0, 0)


def test_upsert_reflects_state_change(isolated_db, monkeypatch):
    """늦게 확정된 상태(유찰 -> 개찰완료)가 반영되어야 합니다."""
    clock = _Clock(datetime(2026, 8, 19, 9, 0, 0))
    monkeypatch.setattr(svc, "utcnow", clock)

    svc._upsert_openg_results(isolated_db, [_openg_row("유찰")])
    first_seen = _single_row(isolated_db).first_seen_at

    clock.now = datetime(2026, 8, 20, 9, 0, 0)
    svc._upsert_openg_results(isolated_db, [_openg_row("개찰완료")])

    assert _row_count(isolated_db) == 1
    row = _single_row(isolated_db)
    assert row.progrs_div_cd_nm == "개찰완료"
    assert row.raw_data["progrsDivCdNm"] == "개찰완료"
    assert row.first_seen_at == first_seen


def test_upsert_skips_rows_without_notice_number(isolated_db):
    """공고번호가 없는 행은 기존 대량 적재와 같이 버립니다."""
    row = _openg_row("유찰")
    row["bid_ntce_no"] = ""

    assert svc._upsert_openg_results(isolated_db, [row]) == 0
    assert _row_count(isolated_db) == 0


def test_sqlite_statement_updates_status_without_touching_first_seen_at():
    """시험 경로는 ON CONFLICT DO UPDATE 로 상태·원문·관측 시각만 갱신합니다."""
    sql = str(_statement_for("sqlite").compile(dialect=sqlite_dialect.dialect()))
    update = _update_clause(sql, "ON CONFLICT")

    assert "DO UPDATE" in update
    assert "progrs_div_cd_nm" in update
    assert "raw_data" in update
    assert "last_seen_at" in update
    assert "collected_at" in update
    assert "first_seen_at" not in update


def test_mysql_statement_uses_on_duplicate_key_update():
    """운영 경로는 ON DUPLICATE KEY UPDATE 로 같은 네 컬럼만 갱신합니다."""
    sql = str(_statement_for("mysql").compile(dialect=mysql_dialect.dialect()))
    update = _update_clause(sql, "ON DUPLICATE KEY UPDATE")

    assert "progrs_div_cd_nm" in update
    assert "raw_data" in update
    assert "last_seen_at" in update
    assert "collected_at" in update
    assert "first_seen_at" not in update


# --------------------------------------------------------------------------- #
# collect_bids 통합
# --------------------------------------------------------------------------- #


async def test_collect_bids_upserts_same_window_twice(isolated_db, monkeypatch):
    """같은 창을 두 번 수집해도 행 수는 그대로이고 상태만 갱신됩니다."""
    clock = _Clock(datetime(2026, 8, 19, 9, 0, 0))
    _prepare_collect_bids(monkeypatch, clock)
    monkeypatch.setattr(svc, "stream_bid_data", AsyncMock(return_value=0))

    _install_fake_client(monkeypatch, [_xml_response(_response_xml(_openg_item_xml("유찰")))])
    first = await svc.collect_bids(
        isolated_db,
        start_date=START_DATE,
        end_date=END_DATE,
        fetch_type="result",
        categories=("Cnstwk",),
        refresh_aggregates=False,
    )
    first_seen = _single_row(isolated_db).first_seen_at

    assert first["openg_result_count"] == 1
    assert first["categories"]["Cnstwk"]["openg_result_count"] == 1
    assert first["status"] == "success"
    assert _single_row(isolated_db).progrs_div_cd_nm == "유찰"

    clock.now = datetime(2026, 8, 20, 9, 0, 0)
    _install_fake_client(monkeypatch, [_xml_response(_response_xml(_openg_item_xml("개찰완료")))])
    second = await svc.collect_bids(
        isolated_db,
        start_date=START_DATE,
        end_date=END_DATE,
        fetch_type="result",
        categories=("Cnstwk",),
        refresh_aggregates=False,
    )

    assert second["openg_result_count"] == 1
    assert _row_count(isolated_db) == 1
    row = _single_row(isolated_db)
    assert row.progrs_div_cd_nm == "개찰완료"
    assert row.first_seen_at == first_seen
    assert row.last_seen_at == datetime(2026, 8, 20, 9, 0, 0)


async def test_openg_partial_failure_does_not_block_other_steps(isolated_db, monkeypatch):
    """개찰결과 부분 실패는 성공 구간 건수와 재수집 구간을 남기고 다른 스텝은 계속됩니다."""
    clock = _Clock(datetime(2026, 8, 19, 9, 0, 0))
    _prepare_collect_bids(monkeypatch, clock)
    monkeypatch.setattr(svc, "stream_bid_announcements", AsyncMock(return_value=5))
    monkeypatch.setattr(svc, "stream_bid_data", AsyncMock(return_value=7))

    async def failing_openg(start_date, end_date, sink, category="Thng"):
        raise RangeCollectionError("개찰결과", 3, [(START_DATE, END_DATE)])

    monkeypatch.setattr(svc, "stream_openg_results", failing_openg)

    result = await svc.collect_bids(
        isolated_db,
        start_date=START_DATE,
        end_date=END_DATE,
        fetch_type="both",
        categories=("Thng",),
        refresh_aggregates=False,
    )

    assert result["announcement_count"] == 5
    assert result["result_count"] == 7
    assert result["openg_result_count"] == 3
    assert result["categories"]["Thng"]["openg_result_count"] == 3
    assert "openg_result_error" in result["categories"]["Thng"]
    assert result["failed_count"] == 1
    assert result["status"] == "partial_success"
    assert result["failed_ranges"] == [
        {
            "category": "Thng",
            "kind": "openg_result",
            "start_date": START_DATE,
            "end_date": END_DATE,
        }
    ]
    assert _row_count(isolated_db) == 0


async def test_openg_exception_does_not_block_other_steps(isolated_db, monkeypatch):
    """개찰결과 스텝의 일반 예외도 공고·낙찰 적재를 되돌리지 않습니다."""
    clock = _Clock(datetime(2026, 8, 19, 9, 0, 0))
    _prepare_collect_bids(monkeypatch, clock)
    monkeypatch.setattr(svc, "stream_bid_announcements", AsyncMock(return_value=5))
    monkeypatch.setattr(svc, "stream_bid_data", AsyncMock(return_value=7))
    monkeypatch.setattr(
        svc,
        "stream_openg_results",
        AsyncMock(side_effect=RuntimeError("개찰결과 API 502")),
    )

    result = await svc.collect_bids(
        isolated_db,
        start_date=START_DATE,
        end_date=END_DATE,
        fetch_type="both",
        categories=("Thng",),
        refresh_aggregates=False,
    )

    assert result["announcement_count"] == 5
    assert result["result_count"] == 7
    assert result["openg_result_count"] == 0
    assert "개찰결과 API 502" in result["categories"]["Thng"]["openg_result_error"]
    assert result["status"] == "partial_success"


async def test_openg_step_is_skipped_when_flag_off(isolated_db, monkeypatch):
    """플래그 기본값은 꺼짐입니다. 꺼져 있으면 스텝을 부르지 않습니다."""
    clock = _Clock(datetime(2026, 8, 19, 9, 0, 0))
    _prepare_collect_bids(monkeypatch, clock)
    monkeypatch.setattr(svc, "OPENG_RESULT_COLLECTION_ENABLED", False)
    monkeypatch.setattr(svc, "stream_bid_data", AsyncMock(return_value=7))
    openg = AsyncMock(return_value=0)
    monkeypatch.setattr(svc, "stream_openg_results", openg)

    result = await svc.collect_bids(
        isolated_db,
        start_date=START_DATE,
        end_date=END_DATE,
        fetch_type="result",
        categories=("Thng",),
        refresh_aggregates=False,
    )

    openg.assert_not_called()
    assert result["openg_result_count"] == 0
    assert result["result_count"] == 7
    assert result["status"] == "success"


async def test_openg_step_skips_unsupported_category(isolated_db, monkeypatch):
    """외자(Frgcpt)는 개찰결과 오퍼레이션이 없어 호출하지 않고 실패로 세지 않습니다."""
    clock = _Clock(datetime(2026, 8, 19, 9, 0, 0))
    _prepare_collect_bids(monkeypatch, clock)
    monkeypatch.setattr(svc, "stream_bid_data", AsyncMock(return_value=2))
    openg = AsyncMock(return_value=0)
    monkeypatch.setattr(svc, "stream_openg_results", openg)

    result = await svc.collect_bids(
        isolated_db,
        start_date=START_DATE,
        end_date=END_DATE,
        fetch_type="result",
        categories=("Frgcpt",),
        refresh_aggregates=False,
    )

    openg.assert_not_called()
    assert result["openg_result_count"] == 0
    assert result["failed_count"] == 0
    assert result["status"] == "success"


@pytest.mark.parametrize("fetch_type", ["announce"])
async def test_openg_step_is_not_run_on_announce_only(isolated_db, monkeypatch, fetch_type):
    """개찰결과는 낙찰결과 축이라 공고 전용 수집에서는 돌지 않습니다."""
    clock = _Clock(datetime(2026, 8, 19, 9, 0, 0))
    _prepare_collect_bids(monkeypatch, clock)
    monkeypatch.setattr(svc, "stream_bid_announcements", AsyncMock(return_value=4))
    openg = AsyncMock(return_value=0)
    monkeypatch.setattr(svc, "stream_openg_results", openg)

    result = await svc.collect_bids(
        isolated_db,
        start_date=START_DATE,
        end_date=END_DATE,
        fetch_type=fetch_type,
        categories=("Thng",),
        refresh_aggregates=False,
    )

    openg.assert_not_called()
    assert result["announcement_count"] == 4
    assert result["openg_result_count"] == 0

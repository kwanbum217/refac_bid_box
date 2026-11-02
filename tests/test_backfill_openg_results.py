"""
tests/test_backfill_openg_results.py

T4 검증: `scripts/backfill_openg_results.py` 의 창 분할, dry-run, 호출 상한,
창별 실패 원장, 재실행 안전성, 적재 행 수·상태 분포 보고.

외부 조달청 API 는 호출하지 않습니다. 수집 경로는 고정 XML 을 돌려주는 가짜
httpx 클라이언트로만 돌리고, 적재는 SQLite 인메모리 DB 로 격리합니다. 서비스
키도 실제 값을 쓰지 않습니다.

설계 정본: docs/analysis/fail_bid_collection_design_20261031.md 5.3·8장 T4.
"""

from __future__ import annotations

import json
from datetime import date

import httpx
import pytest
from sqlalchemy import func, select

import scripts.backfill_openg_results as bf
import src.app.services.api_collector as ac
from src.app.models.openg_results import BidOpengResult


def _openg_item_xml(
    status: str,
    notice_no: str = "20260101001",
    openg_dt: str = "2026/01/01 11:00:00",
) -> str:
    return (
        "<item>"
        f"<bidNtceNo>{notice_no}</bidNtceNo>"
        "<bidNtceOrd>000</bidNtceOrd>"
        "<rbidNo>000</rbidNo>"
        "<bidClsfcNo>0</bidClsfcNo>"
        "<bidNtceNm>도로 보수 공사</bidNtceNm>"
        "<dminsttNm>서울특별시</dminsttNm>"
        f"<opengDt>{openg_dt}</opengDt>"
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
        200, text=xml, request=httpx.Request("GET", "https://example.invalid/api")
    )


def _error_response() -> httpx.Response:
    xml = (
        "<response>"
        "<header><resultCode>30</resultCode><resultMsg>SERVICE KEY ERROR</resultMsg></header>"
        "<body><totalCount>0</totalCount><items></items></body>"
        "</response>"
    )
    return _xml_response(xml)


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
    monkeypatch.setattr(ac.httpx, "AsyncClient", lambda *a, **k: _FakeAsyncClient(responses))


def _prepare(monkeypatch) -> None:
    monkeypatch.setattr(bf, "get_service_key", lambda: "dummy-key")
    monkeypatch.setattr(ac, "get_service_key", lambda: "dummy-key")


def _row_count(db) -> int:
    return int(db.scalar(select(func.count()).select_from(BidOpengResult)) or 0)


def _read_ledger(path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _statuses(ledger: dict) -> list[str]:
    return sorted(entry["status"] for entry in ledger["windows"].values())


async def _run(db, ledger, *, start=date(2026, 1, 1), end=date(2026, 1, 1), **kwargs):
    return await bf.run_backfill(
        db,
        start=start,
        end=end,
        categories=kwargs.pop("categories", ("Cnstwk",)),
        window_days=kwargs.pop("window_days", 1),
        max_calls=kwargs.pop("max_calls", 10),
        dry_run=kwargs.pop("dry_run", False),
        ledger_path=ledger,
    )


# --------------------------------------------------------------------------- #
# 창 분할
# --------------------------------------------------------------------------- #


def test_split_windows_covers_boundaries_and_last_partial_window():
    assert bf.split_windows(date(2026, 1, 1), date(2026, 1, 15), 7) == [
        (date(2026, 1, 1), date(2026, 1, 7)),
        (date(2026, 1, 8), date(2026, 1, 14)),
        (date(2026, 1, 15), date(2026, 1, 15)),
    ]


def test_split_windows_exact_multiple_has_no_empty_tail():
    assert bf.split_windows(date(2026, 1, 1), date(2026, 1, 14), 7) == [
        (date(2026, 1, 1), date(2026, 1, 7)),
        (date(2026, 1, 8), date(2026, 1, 14)),
    ]
    assert bf.split_windows(date(2026, 1, 5), date(2026, 1, 5), 7) == [
        (date(2026, 1, 5), date(2026, 1, 5)),
    ]


def test_split_windows_rejects_bad_input():
    with pytest.raises(ValueError):
        bf.split_windows(date(2026, 1, 2), date(2026, 1, 1), 7)
    with pytest.raises(ValueError):
        bf.split_windows(date(2026, 1, 1), date(2026, 1, 2), 0)


# --------------------------------------------------------------------------- #
# dry-run
# --------------------------------------------------------------------------- #


async def test_dry_run_makes_no_external_call_and_no_db_write(
    isolated_db, tmp_path, monkeypatch, capsys
):
    _prepare(monkeypatch)

    def forbidden_factory(*args, **kwargs):
        raise AssertionError("dry-run 에서는 외부 클라이언트를 만들면 안 됩니다")

    monkeypatch.setattr(ac.httpx, "AsyncClient", forbidden_factory)
    ledger = tmp_path / "ledger.json"

    summary = await _run(
        isolated_db,
        ledger,
        start=date(2026, 1, 1),
        end=date(2026, 1, 8),
        window_days=7,
        dry_run=True,
        max_calls=5,
    )

    out = capsys.readouterr().out
    assert summary["status"] == "dry_run"
    assert summary["window_count"] == 2
    assert summary["planned_windows"] == 2
    assert summary["calls_used"] == 0
    assert "예상 호출 수(창 단위 최소): 2회" in out
    assert not ledger.exists()
    assert _row_count(isolated_db) == 0


# --------------------------------------------------------------------------- #
# 호출 상한
# --------------------------------------------------------------------------- #


async def test_max_calls_stops_and_records_skipped_windows(isolated_db, tmp_path, monkeypatch):
    _prepare(monkeypatch)
    _install_fake_client(
        monkeypatch,
        [_xml_response(_response_xml(_openg_item_xml("유찰", "20260101001")))],
    )
    ledger = tmp_path / "ledger.json"

    summary = await _run(
        isolated_db,
        ledger,
        start=date(2026, 1, 1),
        end=date(2026, 1, 3),
        window_days=1,
        max_calls=1,
    )

    data = _read_ledger(ledger)
    assert summary["calls_used"] == 1
    assert summary["succeeded"] == 1
    assert summary["skipped"] == 2
    assert summary["status"] == "truncated"
    assert _statuses(data) == ["skipped", "skipped", "success"]
    assert _row_count(isolated_db) == 1


# --------------------------------------------------------------------------- #
# 실패 원장과 재실행 안전성
# --------------------------------------------------------------------------- #


async def test_failed_window_is_retried_and_success_window_skipped(
    isolated_db, tmp_path, monkeypatch
):
    _prepare(monkeypatch)
    ledger = tmp_path / "ledger.json"
    _install_fake_client(
        monkeypatch,
        [
            _error_response(),
            _xml_response(_response_xml(_openg_item_xml("유찰", "20260102001"))),
        ],
    )

    first = await _run(
        isolated_db,
        ledger,
        start=date(2026, 1, 1),
        end=date(2026, 1, 2),
        window_days=1,
        max_calls=5,
    )

    assert first["failed"] == 1
    assert first["succeeded"] == 1
    assert first["status"] == "partial_success"
    assert _statuses(_read_ledger(ledger)) == ["failed", "success"]

    fetched: list[tuple[str, str, str]] = []
    original = bf.stream_openg_results

    async def spy(start_date, end_date, sink, num_of_rows=999, category="Thng"):
        fetched.append((category, start_date, end_date))
        return await original(start_date, end_date, sink, num_of_rows, category)

    monkeypatch.setattr(bf, "stream_openg_results", spy)
    _install_fake_client(
        monkeypatch,
        [_xml_response(_response_xml(_openg_item_xml("개찰완료", "20260101001")))],
    )

    second = await _run(
        isolated_db,
        ledger,
        start=date(2026, 1, 1),
        end=date(2026, 1, 2),
        window_days=1,
        max_calls=5,
    )

    assert fetched == [("Cnstwk", "20260101", "20260101")]
    assert second["skipped"] == 1
    assert second["succeeded"] == 1
    assert second["calls_used"] == 1
    assert _statuses(_read_ledger(ledger)) == ["success", "success"]
    assert _row_count(isolated_db) == 2


async def test_same_window_twice_does_not_add_rows(isolated_db, tmp_path, monkeypatch):
    _prepare(monkeypatch)
    xml = _response_xml(_openg_item_xml("유찰", "20260101001"))

    _install_fake_client(monkeypatch, [_xml_response(xml)])
    first = await _run(isolated_db, tmp_path / "first.json")
    assert first["rows_upserted"] == 1

    _install_fake_client(monkeypatch, [_xml_response(xml)])
    second = await _run(isolated_db, tmp_path / "second.json")
    assert second["rows_upserted"] == 1
    assert _row_count(isolated_db) == 1


async def test_rerun_with_same_ledger_makes_no_calls(isolated_db, tmp_path, monkeypatch):
    _prepare(monkeypatch)
    ledger = tmp_path / "ledger.json"
    xml = _response_xml(_openg_item_xml("유찰", "20260101001"))

    _install_fake_client(monkeypatch, [_xml_response(xml)])
    await _run(isolated_db, ledger)

    def forbidden_factory(*args, **kwargs):
        raise AssertionError("성공한 창은 재실행 시 호출하면 안 됩니다")

    monkeypatch.setattr(ac.httpx, "AsyncClient", forbidden_factory)
    summary = await _run(isolated_db, ledger)

    assert summary["calls_used"] == 0
    assert summary["skipped"] == 1
    assert summary["status"] == "success"
    assert _row_count(isolated_db) == 1


# --------------------------------------------------------------------------- #
# 적재 행 수·상태 분포 보고
# --------------------------------------------------------------------------- #


async def test_report_prints_loaded_rows_and_status_distribution(
    isolated_db, tmp_path, monkeypatch, capsys
):
    _prepare(monkeypatch)
    items = (
        _openg_item_xml("개찰완료", "20260101001")
        + _openg_item_xml("유찰", "20260101002")
        + _openg_item_xml("재입찰", "20260101003")
    )
    _install_fake_client(monkeypatch, [_xml_response(_response_xml(items, total_count=3))])

    summary = await _run(isolated_db, tmp_path / "ledger.json")

    out = capsys.readouterr().out
    assert summary["rows_upserted"] == 3
    assert summary["rows_in_range"] == 3
    assert summary["distribution"] == {"개찰완료": 1, "유찰": 1, "재입찰": 1}
    assert "progrs_div_cd_nm 분포:" in out
    assert "유찰: 1건" in out
    assert "이번 실행 적재: 3건" in out
    assert "기간 내 적재 행 수: 3건" in out

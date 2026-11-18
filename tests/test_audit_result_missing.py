"""낙찰 결과 누락 점검 스크립트 시험.

실제 나라장터와 운영 DB, 로컬 .env 에 기대지 않습니다. API 는 _fetch_paged
monkeypatch 로, DB 는 SQLite 인메모리 세션으로 대체합니다.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from scripts import audit_result_missing as audit
from src.app.core.db import Base
from src.app.models.bids import BidResult

SERVICE_ENDPOINT = "getScsbidListSttusServc"


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[BidResult.__table__])
    with Session(engine) as session:
        yield session
    engine.dispose()


def _add_result(session: Session, bid_ntce_no: str, bid_ntce_ord: str = "00") -> None:
    session.add(
        BidResult(
            bid_ntce_no=bid_ntce_no,
            bid_ntce_ord=bid_ntce_ord,
            category="Servc",
        )
    )
    session.flush()


def _row(
    bid_ntce_no: str,
    bid_ntce_ord: str = "00",
    *,
    winner: str = "테스트업체",
    rate: float | None = 90.5,
    opened: datetime | None = None,
    registered: str = "2026-11-05 19:14:00",
) -> dict[str, Any]:
    return {
        "bid_ntce_nm": f"공고 {bid_ntce_no}",
        "bid_ntce_no": bid_ntce_no,
        "bid_ntce_ord": bid_ntce_ord,
        "bidwinnr_nm": winner,
        "sucsf_bid_amt": 1000,
        "sucsf_bid_rate": rate,
        "rl_openg_dt": opened or datetime(2026, 11, 6, 10, 0, 0),
        "dminstt_nm": "수요기관",
        "category": "Servc",
        "raw_data": {"bidNtceDt": registered},
    }


def _patch_fetch(
    monkeypatch: pytest.MonkeyPatch, by_day: dict[str, Any]
) -> list[tuple[str, str, str, str]]:
    calls: list[tuple[str, str, str, str]] = []

    async def fake_fetch(
        client: Any,
        api_url: str,
        step_start: str,
        step_end: str,
        num_of_rows: int,
        mapper: Any,
        error_label: str,
        sem: Any,
        inqry_div: str = "1",
    ) -> list[dict[str, Any]]:
        calls.append((step_start, step_end, inqry_div, api_url))
        assert step_start == step_end
        assert inqry_div == "1"
        outcome = by_day[step_start]
        if isinstance(outcome, Exception):
            raise outcome
        return [dict(row) for row in outcome]

    monkeypatch.setattr(audit.api_collector, "_fetch_paged", fake_fetch)
    return calls


def _run(session: Session, output_dir: Path, since: str, until: str) -> int:
    return asyncio.run(
        audit.run_audit(
            since=datetime.strptime(since, "%Y%m%d").date(),
            until=datetime.strptime(until, "%Y%m%d").date(),
            category="Servc",
            session=session,
            output_dir=output_dir,
        )
    )


def _read_summary(output_dir: Path) -> dict[str, Any]:
    return json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))


def _read_tsv(output_dir: Path) -> list[list[str]]:
    text = (output_dir / "missing.tsv").read_text(encoding="utf-8")
    return [line.split("\t") for line in text.splitlines()]


def test_no_missing_rows(monkeypatch, db_session, tmp_path):
    calls = _patch_fetch(
        monkeypatch,
        {
            "20261105": [
                _row("R26BK000001", "00"),
                _row("R26BK000002", "01"),
            ]
        },
    )
    _add_result(db_session, "R26BK000001", "000")
    _add_result(db_session, "R26BK000002", "01")

    exit_code = _run(db_session, tmp_path, "20261105", "20261105")

    assert exit_code == 0
    summary = _read_summary(tmp_path)
    assert summary["totals"] == {
        "api_count": 2,
        "db_matched": 2,
        "missing": 0,
        "missing_rate": 0.0,
        "failed_days": 0,
    }
    assert summary["days"][0]["status"] == "ok"
    assert summary["days"][0]["missing"] == 0
    assert _read_tsv(tmp_path) == [list(audit.MISSING_TSV_COLUMNS)]
    assert calls == [
        ("20261105", "20261105", "1", audit.api_collector.BID_CATEGORIES["Servc"]["bid_url"])
    ]
    assert SERVICE_ENDPOINT in calls[0][3]


def test_missing_row_is_written_to_tsv_and_totals(monkeypatch, db_session, tmp_path):
    _patch_fetch(
        monkeypatch,
        {
            "20261105": [
                _row("R26BK000001", "00"),
                _row("R26BK000002", "00", winner="누락업체", rate=88.1234),
            ]
        },
    )
    _add_result(db_session, "R26BK000001", "00")

    exit_code = _run(db_session, tmp_path, "20261105", "20261105")

    assert exit_code == 0
    summary = _read_summary(tmp_path)
    assert summary["totals"]["api_count"] == 2
    assert summary["totals"]["db_matched"] == 1
    assert summary["totals"]["missing"] == 1
    assert summary["totals"]["missing_rate"] == 50.0
    assert summary["days"][0]["missing"] == 1

    rows = _read_tsv(tmp_path)
    assert rows[0] == list(audit.MISSING_TSV_COLUMNS)
    assert rows[1] == [
        "R26BK000002",
        "00",
        "2026-11-05 19:14:00",
        "2026-11-06 10:00:00",
        "누락업체",
        "88.1234",
    ]
    assert (tmp_path / "missing.tsv").as_posix().endswith("missing.tsv")


def test_one_failed_day_marks_failed_and_exits_nonzero(monkeypatch, db_session, tmp_path):
    _patch_fetch(
        monkeypatch,
        {
            "20261105": [_row("R26BK000001", "00")],
            "20261106": RuntimeError("API 오류 [99]: 일시 장애"),
        },
    )
    _add_result(db_session, "R26BK000001", "00")

    exit_code = _run(db_session, tmp_path, "20261105", "20261106")

    assert exit_code == 1
    summary = _read_summary(tmp_path)
    assert summary["days"][0]["status"] == "ok"
    assert summary["days"][1]["status"] == "failed"
    assert "일시 장애" in summary["days"][1]["error"]
    assert summary["totals"]["api_count"] == 1
    assert summary["totals"]["missing"] == 0
    assert summary["totals"]["failed_days"] == 1
    assert _read_tsv(tmp_path) == [list(audit.MISSING_TSV_COLUMNS)]


def test_different_ord_is_counted_as_missing(monkeypatch, db_session, tmp_path):
    _patch_fetch(monkeypatch, {"20261105": [_row("R26BK000001", "01")]})
    _add_result(db_session, "R26BK000001", "00")

    exit_code = _run(db_session, tmp_path, "20261105", "20261105")

    assert exit_code == 0
    summary = _read_summary(tmp_path)
    assert summary["totals"]["missing"] == 1
    assert summary["totals"]["db_matched"] == 0
    rows = _read_tsv(tmp_path)
    assert rows[1][0] == "R26BK000001"
    assert rows[1][1] == "01"

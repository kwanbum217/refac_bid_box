"""
tests/test_result_arrivals.py

늦은 도착(최근 수집 창에서 개찰 후 28일 초과 도착) 집계 회귀 테스트.

conftest 의 SQLite 격리 DB(isolated_db)로 검증한다.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta

from src.app.models.bids import BidAnnouncement, BidResult
from src.app.services.result_arrivals import compute_late_arrivals
from src.app.services.result_coverage import LARGE_PRICE_THRESHOLD

# 창은 [as_of - window_days, as_of) 이다. 기본 7일이면 [2026-09-21 00:00, 2026-09-28 00:00).
AS_OF = date(2026, 9, 28)
COLLECT = datetime(2026, 9, 22, 10, 0)
FRESH = datetime(2026, 9, 23, 10, 0)


def _add_announcement(
    db,
    no: str,
    ord_: str,
    category: str,
    openg_dt: datetime | None,
    *,
    presmpt_prce: int | None = None,
    ntce_kind_nm: str | None = None,
) -> None:
    db.add(
        BidAnnouncement(
            bid_ntce_no=no,
            bid_ntce_ord=ord_,
            category=category,
            openg_dt=openg_dt,
            presmpt_prce=presmpt_prce,
            ntce_kind_nm=ntce_kind_nm,
        )
    )


def _add_result(db, no: str, ord_: str, category: str, collected_at: datetime) -> None:
    db.add(
        BidResult(
            bid_ntce_no=no,
            bid_ntce_ord=ord_,
            category=category,
            collected_at=collected_at,
        )
    )


def _row(rows, category, band):
    matched = [row for row in rows if row["category"] == category and row["band"] == band]
    assert len(matched) == 1
    return matched[0]


def test_returns_all_category_band_rows(isolated_db):
    rows = compute_late_arrivals(isolated_db, as_of=AS_OF)
    assert len(rows) == 6
    for row in rows:
        assert row["late_arrivals"] == 0
        assert row["total_arrivals"] == 0


def test_late_30_days_and_not_late_10_days_split_by_band(isolated_db):
    db = isolated_db
    # 개찰 후 30일 도착, 대형. 결과 차수는 2자리, 공고 차수는 3자리라 정규화 매칭을 확인한다.
    _add_announcement(
        db,
        "2026-A00001",
        "001",
        "Servc",
        COLLECT - timedelta(days=30),
        presmpt_prce=LARGE_PRICE_THRESHOLD,
    )
    _add_result(db, "2026-A00001", "01", "Servc", COLLECT)
    # 개찰 후 10일 도착, 소형.
    _add_announcement(db, "2026-A00002", "001", "Servc", FRESH - timedelta(days=10))
    _add_result(db, "2026-A00002", "001", "Servc", FRESH)
    db.commit()

    rows = compute_late_arrivals(db, as_of=AS_OF)
    large = _row(rows, "Servc", "large")
    small = _row(rows, "Servc", "small")
    assert large["late_arrivals"] == 1
    assert large["total_arrivals"] == 1
    assert small["late_arrivals"] == 0
    assert small["total_arrivals"] == 1
    # 다른 분류는 비어 있다.
    assert _row(rows, "Thng", "large")["total_arrivals"] == 0
    assert _row(rows, "Cnstwk", "small")["total_arrivals"] == 0


def test_late_boundary_28_days_inclusive(isolated_db):
    db = isolated_db
    _add_announcement(db, "2026-B00001", "001", "Servc", COLLECT - timedelta(days=28))
    _add_result(db, "2026-B00001", "001", "Servc", COLLECT)
    _add_announcement(db, "2026-B00002", "001", "Servc", COLLECT - timedelta(days=27))
    _add_result(db, "2026-B00002", "001", "Servc", COLLECT)
    db.commit()

    row = _row(compute_late_arrivals(db, as_of=AS_OF), "Servc", "small")
    assert row["late_arrivals"] == 1
    assert row["total_arrivals"] == 2


def test_collected_at_window_bounds(isolated_db):
    db = isolated_db
    openg = datetime(2026, 6, 1, 10, 0)
    # 창 시작 당일 00:00 은 포함된다.
    _add_announcement(db, "2026-C00001", "001", "Servc", openg)
    _add_result(db, "2026-C00001", "001", "Servc", datetime(2026, 9, 21, 0, 0))
    # 창 바로 전날 23:59 는 제외된다.
    _add_announcement(db, "2026-C00002", "001", "Servc", openg)
    _add_result(db, "2026-C00002", "001", "Servc", datetime(2026, 9, 20, 23, 59))
    # as_of 당일 00:00 은 상한 배타로 제외된다.
    _add_announcement(db, "2026-C00003", "001", "Servc", openg)
    _add_result(db, "2026-C00003", "001", "Servc", datetime(2026, 9, 28, 0, 0))
    # 창 마지막 날 23:59 는 포함된다.
    _add_announcement(db, "2026-C00004", "001", "Servc", openg)
    _add_result(db, "2026-C00004", "001", "Servc", datetime(2026, 9, 27, 23, 59))
    db.commit()

    row = _row(compute_late_arrivals(db, as_of=AS_OF), "Servc", "small")
    assert row["total_arrivals"] == 2
    assert row["late_arrivals"] == 2


def test_window_days_parameter_widens_window(isolated_db):
    db = isolated_db
    _add_announcement(db, "2026-D00001", "001", "Servc", datetime(2026, 6, 1, 10, 0))
    _add_result(db, "2026-D00001", "001", "Servc", datetime(2026, 9, 15, 10, 0))
    db.commit()

    assert _row(compute_late_arrivals(db, as_of=AS_OF), "Servc", "small")["total_arrivals"] == 0
    widened = _row(compute_late_arrivals(db, as_of=AS_OF, window_days=14), "Servc", "small")
    assert widened["total_arrivals"] == 1
    assert widened["late_arrivals"] == 1


def test_cancelled_announcement_excluded(isolated_db):
    db = isolated_db
    _add_announcement(
        db,
        "2026-E00001",
        "001",
        "Servc",
        datetime(2026, 6, 1, 10, 0),
        ntce_kind_nm="취소공고",
    )
    _add_result(db, "2026-E00001", "001", "Servc", COLLECT)
    db.commit()

    row = _row(compute_late_arrivals(db, as_of=AS_OF), "Servc", "small")
    assert row["late_arrivals"] == 0
    assert row["total_arrivals"] == 0


def test_result_without_announcement_excluded(isolated_db):
    db = isolated_db
    _add_result(db, "2026-F00001", "001", "Servc", COLLECT)
    db.commit()

    row = _row(compute_late_arrivals(db, as_of=AS_OF), "Servc", "small")
    assert row["late_arrivals"] == 0
    assert row["total_arrivals"] == 0


def test_category_and_ord_must_match(isolated_db):
    db = isolated_db
    # 같은 공고번호라도 분류가 다르면 별개다. Servc 공고만 있다.
    _add_announcement(db, "2026-G00001", "001", "Servc", datetime(2026, 6, 1, 10, 0))
    _add_result(db, "2026-G00001", "001", "Servc", COLLECT)
    # 분류가 다른 결과는 매칭 공고가 없다.
    _add_result(db, "2026-G00001", "001", "Thng", COLLECT)
    # 차수가 다르면(정규화 후에도) 매칭되지 않는다.
    _add_result(db, "2026-G00001", "002", "Servc", COLLECT)
    # 공고번호가 다르면 매칭되지 않는다.
    _add_result(db, "2026-G00002", "001", "Servc", COLLECT)
    db.commit()

    rows = compute_late_arrivals(db, as_of=AS_OF)
    assert _row(rows, "Servc", "small")["total_arrivals"] == 1
    assert _row(rows, "Thng", "small")["total_arrivals"] == 0


def test_report_json_includes_late_arrivals(isolated_db, monkeypatch, capsys):
    from scripts import result_match_rate_report as report

    db = isolated_db
    _add_announcement(
        db,
        "2026-H00001",
        "001",
        "Servc",
        COLLECT - timedelta(days=30),
        presmpt_prce=LARGE_PRICE_THRESHOLD,
    )
    _add_result(db, "2026-H00001", "001", "Servc", COLLECT)
    db.commit()

    monkeypatch.setattr(report, "SessionLocal", lambda: db)
    rc = report.main(["--as-of", AS_OF.isoformat(), "--weeks", "1", "--format", "json"])
    assert rc == 0

    payload = json.loads(capsys.readouterr().out)
    # 기존 키는 그대로 유지된다.
    assert {"as_of", "rows", "alerts"}.issubset(payload)
    assert "late_arrivals" in payload
    servc_large = [
        row
        for row in payload["late_arrivals"]
        if row["category"] == "Servc" and row["band"] == "large"
    ]
    assert len(servc_large) == 1
    assert servc_large[0]["late_arrivals"] == 1


def test_report_table_shows_late_section(isolated_db, monkeypatch, capsys):
    from scripts import result_match_rate_report as report

    db = isolated_db
    _add_announcement(db, "2026-I00001", "001", "Servc", COLLECT - timedelta(days=30))
    _add_result(db, "2026-I00001", "001", "Servc", COLLECT)
    db.commit()

    monkeypatch.setattr(report, "SessionLocal", lambda: db)
    rc = report.main(
        [
            "--as-of",
            AS_OF.isoformat(),
            "--weeks",
            "1",
            "--format",
            "table",
            "--late-window-days",
            "7",
        ]
    )
    assert rc == 0

    out = capsys.readouterr().out
    assert "늦은 도착(최근 7일, 개찰 후 28일 초과)" in out
    # 기존 요약 표 헤더는 그대로다.
    assert "매칭률" in out

"""
tests/test_result_method_rates.py

입찰방식별 낙찰결과 매칭률 집계와 리포트 표시 회귀 테스트.

conftest 의 SQLite 격리 DB(isolated_db)로 검증한다.
"""

from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta

import pytest

from src.app.models.bids import BidAnnouncement, BidResult
from src.app.services.result_coverage import LARGE_PRICE_THRESHOLD, NULL_METHOD_LABEL
from src.app.services.result_method_rates import compute_method_match_rates

# 2026-08-24 는 월요일이다. as_of 2026-09-28 기준 최근 성숙 주는
# 08-24, 08-17, 08-10, 08-03 네 주다.
W = date(2026, 8, 24)
AS_OF = date(2026, 9, 28)


def _openg(day: date) -> datetime:
    return datetime.combine(day, time(10, 0))


def _add_announcement(
    db,
    no: str,
    ord_: str,
    category: str,
    openg_day: date,
    *,
    presmpt_prce: int | None = None,
    ntce_kind_nm: str | None = None,
    bid_methd_nm: str | None = None,
) -> None:
    db.add(
        BidAnnouncement(
            bid_ntce_no=no,
            bid_ntce_ord=ord_,
            category=category,
            bid_ntce_dt=_openg(openg_day) - timedelta(days=14),
            openg_dt=_openg(openg_day),
            presmpt_prce=presmpt_prce,
            ntce_kind_nm=ntce_kind_nm,
            bid_methd_nm=bid_methd_nm,
        )
    )


def _add_result(db, no: str, ord_: str, category: str, openg_day: date) -> None:
    db.add(
        BidResult(
            bid_ntce_no=no,
            bid_ntce_ord=ord_,
            category=category,
            rl_openg_dt=_openg(openg_day),
        )
    )


def _row_of(rows, category, band, method):
    matched = [
        row
        for row in rows
        if row["category"] == category and row["band"] == band and row["method"] == method
    ]
    assert len(matched) == 1
    return matched[0]


def test_splits_by_method_and_shares_sum_to_one(isolated_db):
    db = isolated_db
    _add_announcement(
        db,
        "2026-M00001",
        "001",
        "Thng",
        W,
        presmpt_prce=LARGE_PRICE_THRESHOLD,
        bid_methd_nm="전자입찰",
    )
    _add_result(db, "2026-M00001", "001", "Thng", W)
    _add_announcement(
        db,
        "2026-M00002",
        "001",
        "Thng",
        W,
        presmpt_prce=LARGE_PRICE_THRESHOLD,
        bid_methd_nm="전자입찰",
    )
    _add_announcement(
        db,
        "2026-M00003",
        "001",
        "Thng",
        W,
        presmpt_prce=LARGE_PRICE_THRESHOLD,
        bid_methd_nm="직찰",
    )
    db.commit()

    rows = compute_method_match_rates(db, as_of=AS_OF, weeks=4)

    electronic = _row_of(rows, "Thng", "large", "전자입찰")
    direct = _row_of(rows, "Thng", "large", "직찰")
    assert electronic["announcements"] == 2
    assert electronic["matched"] == 1
    assert electronic["rate"] == pytest.approx(0.5)
    assert direct["announcements"] == 1
    assert direct["matched"] == 0
    assert direct["rate"] == 0.0
    assert electronic["share"] == pytest.approx(2 / 3)
    assert sum(row["share"] for row in rows) == pytest.approx(1.0)


def test_null_method_grouped_under_null_label(isolated_db):
    db = isolated_db
    _add_announcement(db, "2026-N00001", "001", "Servc", W, bid_methd_nm=None)
    _add_announcement(db, "2026-N00002", "001", "Servc", W)
    _add_result(db, "2026-N00001", "001", "Servc", W)
    db.commit()

    rows = compute_method_match_rates(db, as_of=AS_OF, weeks=4)

    assert NULL_METHOD_LABEL == "(null)"
    null_row = _row_of(rows, "Servc", "small", NULL_METHOD_LABEL)
    assert null_row["announcements"] == 2
    assert null_row["matched"] == 1


def test_cancelled_announcement_excluded(isolated_db):
    db = isolated_db
    _add_announcement(db, "2026-C00001", "001", "Servc", W, bid_methd_nm="전자입찰")
    _add_announcement(
        db,
        "2026-C00002",
        "001",
        "Servc",
        W,
        bid_methd_nm="전자입찰",
        ntce_kind_nm="취소공고",
    )
    _add_result(db, "2026-C00001", "001", "Servc", W)
    _add_result(db, "2026-C00002", "001", "Servc", W)
    db.commit()

    rows = compute_method_match_rates(db, as_of=AS_OF, weeks=4)

    row = _row_of(rows, "Servc", "small", "전자입찰")
    assert row["announcements"] == 1
    assert row["matched"] == 1


def test_large_and_small_split(isolated_db):
    db = isolated_db
    _add_announcement(
        db,
        "2026-B00001",
        "001",
        "Cnstwk",
        W,
        presmpt_prce=LARGE_PRICE_THRESHOLD,
        bid_methd_nm="전자입찰",
    )
    _add_announcement(
        db,
        "2026-B00002",
        "001",
        "Cnstwk",
        W,
        presmpt_prce=LARGE_PRICE_THRESHOLD - 1,
        bid_methd_nm="전자입찰",
    )
    _add_result(db, "2026-B00001", "001", "Cnstwk", W)
    db.commit()

    rows = compute_method_match_rates(db, as_of=AS_OF, weeks=4)

    large = _row_of(rows, "Cnstwk", "large", "전자입찰")
    small = _row_of(rows, "Cnstwk", "small", "전자입찰")
    assert large["announcements"] == 1
    assert large["matched"] == 1
    assert small["announcements"] == 1
    assert small["matched"] == 0


def test_mature_weeks_are_summed(isolated_db):
    db = isolated_db
    # 서로 다른 성숙 주의 같은 방식은 하나의 행으로 합산된다.
    for index, day in enumerate((W, W - timedelta(days=7), W - timedelta(days=14))):
        no = f"2026-S{index:05d}"
        _add_announcement(db, no, "001", "Servc", day, bid_methd_nm="직찰")
    db.commit()

    rows = compute_method_match_rates(db, as_of=AS_OF, weeks=4)

    direct = _row_of(rows, "Servc", "small", "직찰")
    assert direct["announcements"] == 3


def test_immature_week_excluded(isolated_db):
    db = isolated_db
    _add_announcement(db, "2026-T00001", "001", "Servc", W, bid_methd_nm="전자입찰")
    _add_result(db, "2026-T00001", "001", "Servc", W)
    # 다음 주는 아직 성숙하지 않으므로 세지 않는다.
    _add_announcement(db, "2026-T00002", "001", "Servc", W + timedelta(days=7), bid_methd_nm="직찰")
    db.commit()

    rows = compute_method_match_rates(db, as_of=AS_OF, weeks=1)

    assert _row_of(rows, "Servc", "small", "전자입찰")["announcements"] == 1
    assert all(row["method"] != "직찰" for row in rows)


def test_no_announcements_returns_empty(isolated_db):
    assert compute_method_match_rates(isolated_db, as_of=AS_OF, weeks=4) == []


def test_report_json_includes_method_rates(isolated_db, monkeypatch, capsys):
    from scripts import result_match_rate_report as report

    db = isolated_db
    _add_announcement(
        db,
        "2026-J00001",
        "001",
        "Thng",
        W,
        presmpt_prce=LARGE_PRICE_THRESHOLD,
        bid_methd_nm="직찰",
    )
    _add_result(db, "2026-J00001", "001", "Thng", W)
    db.commit()

    monkeypatch.setattr(report, "SessionLocal", lambda: db)
    rc = report.main(
        ["--as-of", AS_OF.isoformat(), "--weeks", "1", "--method-weeks", "1", "--format", "json"]
    )
    assert rc == 0

    payload = json.loads(capsys.readouterr().out)
    # 기존 키는 그대로 유지되고 method_rates 가 추가된다.
    assert {"as_of", "rows", "alerts", "late_arrivals", "method_rates"}.issubset(payload)
    direct = _row_of(payload["method_rates"], "Thng", "large", "직찰")
    assert direct["announcements"] == 1
    assert direct["matched"] == 1


def test_report_table_shows_dash_for_missing_cancel_field(isolated_db, monkeypatch, capsys):
    from scripts import result_match_rate_report as report

    db = isolated_db
    _add_announcement(db, "2026-K00001", "001", "Servc", W, bid_methd_nm="전자입찰")
    _add_result(db, "2026-K00001", "001", "Servc", W)
    db.commit()

    monkeypatch.setattr(report, "SessionLocal", lambda: db)
    rc = report.main(["--as-of", AS_OF.isoformat(), "--weeks", "1", "--format", "table"])
    assert rc == 0

    out = capsys.readouterr().out
    assert "입찰방식별 매칭률(최근 4 성숙 주 합산)" in out
    assert "취소제외보정" in out
    assert "전년취소제외보정" in out
    row_line = next(
        line for line in out.splitlines() if line.startswith("Servc") and "2026-08-24" in line
    )
    # cancel_adjusted_rate 필드가 없으면 하이픈으로 표시한다.
    assert row_line.rstrip().endswith("-")


def test_report_table_formats_cancel_columns_when_present(isolated_db, monkeypatch, capsys):
    from scripts import result_match_rate_report as report

    db = isolated_db
    _add_announcement(db, "2026-L00001", "001", "Servc", W, bid_methd_nm="전자입찰")
    _add_result(db, "2026-L00001", "001", "Servc", W)
    db.commit()

    original = report.compute_result_match_rates

    def with_cancel(session, *, as_of, weeks):
        rows = original(session, as_of=as_of, weeks=weeks)
        for row in rows:
            row["cancel_adjusted_rate"] = 0.25
            row["baseline_cancel_adjusted_rate"] = 0.3
        return rows

    monkeypatch.setattr(report, "SessionLocal", lambda: db)
    monkeypatch.setattr(report, "compute_result_match_rates", with_cancel)
    rc = report.main(["--as-of", AS_OF.isoformat(), "--weeks", "1", "--format", "table"])
    assert rc == 0

    out = capsys.readouterr().out
    row_line = next(
        line for line in out.splitlines() if line.startswith("Servc") and "2026-08-24" in line
    )
    assert "25.0%" in row_line
    assert "30.0%" in row_line

"""
tests/test_result_coverage.py

개찰 완료 공고 대비 낙찰결과 매칭률 집계와 경고 판정 회귀 테스트.

conftest 의 SQLite 격리 DB(isolated_db)로 검증한다.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

import pytest

from src.app.models.bids import BidAnnouncement, BidResult
from src.app.services.result_coverage import (
    LARGE_PRICE_THRESHOLD,
    MIN_WEEK_SAMPLES,
    compute_result_match_rates,
    evaluate_match_rate_alerts,
    normalize_ord,
)

# 2026-08-24 는 월요일이다. as_of = W + 34 일(2026-09-27, 일요일)이면
# 개찰 주 끝(W+6)이 as_of - 28일과 정확히 같아 성숙 경계가 된다.
W = date(2026, 8, 24)
AS_OF = W + timedelta(days=34)


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


def _row_of(rows, category, band, week_start):
    matched = [
        row
        for row in rows
        if row["category"] == category
        and row["band"] == band
        and row["week_start"] == week_start.isoformat()
    ]
    assert len(matched) == 1
    return matched[0]


def _alert_row(
    *,
    rate,
    baseline_rate,
    announcements=MIN_WEEK_SAMPLES,
    baseline_announcements=MIN_WEEK_SAMPLES,
    band="large",
    category="Servc",
    week_start="2026-08-24",
):
    return {
        "category": category,
        "week_start": week_start,
        "band": band,
        "announcements": announcements,
        "matched": 0,
        "rate": rate,
        "baseline_announcements": baseline_announcements,
        "baseline_matched": 0,
        "baseline_rate": baseline_rate,
    }


def test_normalize_ord():
    assert normalize_ord("000") == "000"
    assert normalize_ord("0") == "000"
    assert normalize_ord("1") == "001"
    assert normalize_ord("001") == "001"
    assert normalize_ord(" 2 ") == "002"
    assert normalize_ord("0000") == "000"
    assert normalize_ord(None) == "000"


def test_cancelled_excluded_and_null_kind_included(isolated_db):
    db = isolated_db
    _add_announcement(db, "2026-A00001", "001", "Servc", W, ntce_kind_nm=None)
    _add_announcement(db, "2026-A00002", "001", "Servc", W, ntce_kind_nm="취소공고")
    _add_announcement(db, "2026-A00003", "001", "Servc", W, ntce_kind_nm="일반공고")
    _add_result(db, "2026-A00001", "001", "Servc", W)
    _add_result(db, "2026-A00002", "001", "Servc", W)
    db.commit()

    rows = compute_result_match_rates(db, as_of=AS_OF, weeks=1)
    row = _row_of(rows, "Servc", "small", W)
    assert row["announcements"] == 2
    assert row["matched"] == 1


def test_large_small_boundary_and_null_price(isolated_db):
    db = isolated_db
    _add_announcement(db, "2026-B00001", "001", "Cnstwk", W, presmpt_prce=LARGE_PRICE_THRESHOLD)
    _add_announcement(db, "2026-B00002", "001", "Cnstwk", W, presmpt_prce=LARGE_PRICE_THRESHOLD - 1)
    _add_announcement(db, "2026-B00003", "001", "Cnstwk", W, presmpt_prce=None)
    _add_result(db, "2026-B00001", "001", "Cnstwk", W)
    _add_result(db, "2026-B00002", "001", "Cnstwk", W)
    db.commit()

    rows = compute_result_match_rates(db, as_of=AS_OF, weeks=1)
    large = _row_of(rows, "Cnstwk", "large", W)
    small = _row_of(rows, "Cnstwk", "small", W)
    assert large["announcements"] == 1
    assert large["matched"] == 1
    assert small["announcements"] == 2
    # B00002 만 결과가 있다. B00003(NULL 추정가격, 결과 없음)은 미매칭이다.
    assert small["matched"] == 1


def test_mature_week_selection_boundary(isolated_db):
    db = isolated_db
    _add_announcement(db, "2026-C00001", "001", "Servc", W)
    _add_result(db, "2026-C00001", "001", "Servc", W)
    db.commit()

    # 주 끝(W+6)이 as_of - 28일과 같으면 성숙이다. 3분류 x 2규모 행이 모두 W 주다.
    rows = compute_result_match_rates(db, as_of=W + timedelta(days=34), weeks=1)
    assert len(rows) == 6
    assert {row["week_start"] for row in rows} == {W.isoformat()}

    # 하루 이르면 W 주는 아직 성숙하지 않고 직전 주가 최근 성숙 주다.
    rows = compute_result_match_rates(db, as_of=W + timedelta(days=33), weeks=1)
    assert {row["week_start"] for row in rows} == {(W - timedelta(days=7)).isoformat()}


def test_baseline_year_ago_rate(isolated_db):
    db = isolated_db
    _add_announcement(db, "2026-D00001", "001", "Thng", W, presmpt_prce=LARGE_PRICE_THRESHOLD)
    _add_announcement(db, "2026-D00002", "001", "Thng", W, presmpt_prce=LARGE_PRICE_THRESHOLD)
    _add_result(db, "2026-D00001", "001", "Thng", W)

    baseline = W - timedelta(days=364)
    _add_announcement(
        db, "2025-D00001", "001", "Thng", baseline, presmpt_prce=LARGE_PRICE_THRESHOLD
    )
    _add_announcement(
        db, "2025-D00002", "001", "Thng", baseline, presmpt_prce=LARGE_PRICE_THRESHOLD
    )
    _add_result(db, "2025-D00001", "001", "Thng", baseline)
    _add_result(db, "2025-D00002", "001", "Thng", baseline)
    db.commit()

    rows = compute_result_match_rates(db, as_of=AS_OF, weeks=1)
    row = _row_of(rows, "Thng", "large", W)
    assert row["announcements"] == 2
    assert row["matched"] == 1
    assert row["rate"] == pytest.approx(0.5)
    assert row["baseline_announcements"] == 2
    assert row["baseline_matched"] == 2
    assert row["baseline_rate"] == pytest.approx(1.0)


def test_alert_rule_boundaries():
    # 세 조건이 모두 경계값(공고 100, 하락폭 0.10)일 때 경고다.
    alerts = evaluate_match_rate_alerts([_alert_row(rate=0.5, baseline_rate=0.6)])
    assert len(alerts) == 1
    assert alerts[0]["category"] == "Servc"
    assert alerts[0]["week_start"] == "2026-08-24"

    # 하락폭 0.10 미만은 경고가 아니다.
    assert evaluate_match_rate_alerts([_alert_row(rate=0.5, baseline_rate=0.59)]) == []

    # 실측 공고 수 경계 미만은 경고가 아니다.
    assert (
        evaluate_match_rate_alerts(
            [_alert_row(rate=0.5, baseline_rate=0.6, announcements=MIN_WEEK_SAMPLES - 1)]
        )
        == []
    )

    # 전년 공고 수 경계 미만은 경고가 아니다.
    assert (
        evaluate_match_rate_alerts(
            [_alert_row(rate=0.5, baseline_rate=0.6, baseline_announcements=MIN_WEEK_SAMPLES - 1)]
        )
        == []
    )

    # 소형 행은 대상이 아니고, 분류별 최근 성숙 주만 본다.
    rows = [
        _alert_row(rate=0.5, baseline_rate=0.6, band="small"),
        _alert_row(rate=0.5, baseline_rate=0.6, category="Cnstwk", week_start="2026-08-17"),
        _alert_row(rate=0.9, baseline_rate=0.9, category="Cnstwk", week_start="2026-08-24"),
    ]
    assert evaluate_match_rate_alerts(rows) == []

    rows = [
        _alert_row(rate=0.5, baseline_rate=0.6, category="Cnstwk", week_start="2026-08-24"),
        _alert_row(rate=0.9, baseline_rate=0.9, category="Cnstwk", week_start="2026-08-17"),
    ]
    assert len(evaluate_match_rate_alerts(rows)) == 1


@pytest.mark.asyncio
async def test_task_notifies_only_when_alert(isolated_db, monkeypatch):
    from src.tasks import coverage_tasks

    db = isolated_db
    for i in range(MIN_WEEK_SAMPLES):
        no = f"2026-E{i:05d}"
        _add_announcement(db, no, "001", "Servc", W, presmpt_prce=LARGE_PRICE_THRESHOLD)
        if i < MIN_WEEK_SAMPLES // 2:
            _add_result(db, no, "001", "Servc", W)
    baseline = W - timedelta(days=364)
    for i in range(MIN_WEEK_SAMPLES):
        no = f"2025-E{i:05d}"
        _add_announcement(db, no, "001", "Servc", baseline, presmpt_prce=LARGE_PRICE_THRESHOLD)
        _add_result(db, no, "001", "Servc", baseline)
    db.commit()

    sent: list[tuple[str, list[str], str]] = []

    async def fake_notify(title, lines, *, level="info"):
        sent.append((title, lines, level))

    monkeypatch.setattr(coverage_tasks, "SessionLocal", lambda: db)
    monkeypatch.setattr(coverage_tasks, "notify", fake_notify)

    result = await coverage_tasks.result_coverage_monitor_task({})
    assert result["status"] == "ok"
    assert len(result["alerts"]) == 1
    # 기본 weeks=8 이므로 8주 x 3분류 x 2규모 = 48 행이다.
    assert result["rows"] == 48
    assert len(sent) == 1
    title, lines, level = sent[0]
    assert level == "warning"
    assert "매칭률" in title
    assert "uv run python scripts/result_match_rate_report.py" in "\n".join(lines)


@pytest.mark.asyncio
async def test_task_silent_without_alert(isolated_db, monkeypatch):
    from src.tasks import coverage_tasks

    sent: list[tuple[str, list[str], str]] = []

    async def fake_notify(title, lines, *, level="info"):
        sent.append((title, lines, level))

    monkeypatch.setattr(coverage_tasks, "SessionLocal", lambda: isolated_db)
    monkeypatch.setattr(coverage_tasks, "notify", fake_notify)

    result = await coverage_tasks.result_coverage_monitor_task({})
    assert result["status"] == "ok"
    assert result["alerts"] == []
    assert sent == []


@pytest.mark.asyncio
async def test_task_returns_error_without_raising_on_db_failure(monkeypatch):
    from src.tasks import coverage_tasks

    def boom():
        raise RuntimeError("db unavailable")

    sent: list[tuple[str, list[str], str]] = []

    async def fake_notify(title, lines, *, level="info"):
        sent.append((title, lines, level))

    monkeypatch.setattr(coverage_tasks, "SessionLocal", boom)
    monkeypatch.setattr(coverage_tasks, "notify", fake_notify)

    result = await coverage_tasks.result_coverage_monitor_task({})
    assert result["status"] == "error"
    assert result["alerts"] == []
    assert sent == []


def test_worker_settings_register_task_and_cron():
    from src.tasks.worker import WorkerSettings

    names = [
        getattr(getattr(fn, "coroutine", fn), "__name__", "") for fn in WorkerSettings.functions
    ]
    assert "result_coverage_monitor_task" in names

    jobs = [
        job
        for job in WorkerSettings.cron_jobs
        if getattr(getattr(job, "coroutine", job), "__name__", "") == "result_coverage_monitor_task"
    ]
    assert len(jobs) == 1
    job = jobs[0]
    assert job.weekday in ("mon", {"mon"})
    assert job.hour in (5, {5})
    assert job.minute in (0, {0})
    assert job.run_at_startup is False
    assert job.timeout_s == 3600

"""비교 분석 통계 pending/stale 응답 회귀 테스트.

2026-11-22 사용자 보고 '데이터 출력 렌더링 딜레이'의 재발 방지 고정입니다.
스냅숏이 없거나 낡았고 캐시도 없을 때 요청 안에서 대형 실시간 집계(실측
39.8초)를 하지 않고 pending 으로 즉시 답하는지, 직전 정상 응답이 있으면
stale 로 보여 주는지, 5분 주기 worker 가 빠진 스냅숏만 채우는지 확인합니다.

시험은 SQLite 인메모리 픽스처와 가짜 캐시만 씁니다. 운영 DB·Redis 에
기대지 않습니다.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from pathlib import Path

from src.app.core.timeutil import kst_now, utcnow
from src.app.models.bid_restrictions import BidAnnouncementLicenseLimit
from src.app.models.bids import (
    BidAnnouncement,
    BidCompareStatsSnapshot,
    BidResult,
)
from src.app.services import compare_stats_snapshots as snapshots
from src.app.services import dashboard
from src.tasks import scheduled_tasks

SNAPSHOT_KEYS = (
    snapshots.SNAPSHOT_KEY_AGENCY_TOP10,
    snapshots.SNAPSHOT_KEY_MATCHED_COUNT,
    snapshots.SNAPSHOT_KEY_ANNOUNCE_BY_MONTH,
    snapshots.SNAPSHOT_KEY_RESULT_BY_MONTH,
    snapshots.SNAPSHOT_KEY_INDUSTRY_TOTALS,
)

REALTIME_FUNCTIONS = (
    "_query_matched_count_realtime",
    "_query_match_rate_1y_realtime",
    "_query_announce_by_month_realtime",
    "_query_result_by_month_realtime",
    "_query_agency_announce_top10_realtime",
    "_query_industry_totals_realtime",
)


def _add_announcement(db, **overrides):
    industry_code = overrides.pop("industry_code", "1172")
    now = utcnow()
    payload = {
        "bid_ntce_no": "PEND-001",
        "bid_ntce_ord": "000",
        "bid_ntce_nm": "pending 검증 공고",
        "dminstt_nm": "pending 검증 기관",
        "category": "Thng",
        "base_amount": 1000000,
        "presmpt_prce": 1000000,
        "bid_ntce_dt": now - timedelta(days=10),
        "collected_at": now,
    }
    payload.update(overrides)
    row = BidAnnouncement(**payload)
    db.add(row)
    if industry_code is not None:
        db.add(
            BidAnnouncementLicenseLimit(
                bid_ntce_no=row.bid_ntce_no,
                bid_ntce_ord=row.bid_ntce_ord,
                lmt_grp_no="1",
                lmt_sno="1",
                permsn_indstryty_list=f"업종/{industry_code}",
                collected_at=now,
            )
        )
    db.commit()
    db.refresh(row)
    return row


def _add_result(db, **overrides):
    now = utcnow()
    payload = {
        "bid_ntce_no": "PEND-001",
        "bid_ntce_ord": "000",
        "bid_ntce_nm": "pending 검증 결과",
        "bidwinnr_nm": "pending 검증 업체",
        "dminstt_nm": "pending 검증 기관",
        "category": "Thng",
        "sucsf_bid_amt": 900000,
        "sucsf_bid_rate": 90.0,
        "rl_openg_dt": now - timedelta(days=10),
        "collected_at": now,
    }
    payload.update(overrides)
    row = BidResult(**payload)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _isolated_cache(monkeypatch):
    """캐시를 테스트 로컬 dict 로 바꾸고 set 호출을 기록합니다."""
    store: dict[str, object] = {}
    sets: list[tuple[str, object, int]] = []
    monkeypatch.setattr(dashboard.cache, "get", store.get)

    def _set(key, value, ttl):
        store[key] = value
        sets.append((key, value, ttl))

    monkeypatch.setattr(dashboard.cache, "set", _set)
    return store, sets


def _forbid_realtime(monkeypatch) -> list[str]:
    """요청 경로에서 실시간 집계 함수가 불리면 즉시 실패하게 만듭니다."""
    calls: list[str] = []

    def _forbidden(name):
        def _raise(*_args, **_kwargs):
            calls.append(name)
            raise AssertionError(f"요청 경로에서 실시간 집계가 실행됐다: {name}")

        return _raise

    for name in REALTIME_FUNCTIONS:
        monkeypatch.setattr(dashboard, name, _forbidden(name))
    return calls


def _expire_snapshots(db) -> None:
    old = utcnow() - timedelta(days=3)
    for key in SNAPSHOT_KEYS:
        row = db.get(BidCompareStatsSnapshot, key)
        assert row is not None
        row.rebuilt_at = old
    db.commit()


def test_스냅숏과_캐시가_없으면_실시간_집계_없이_pending_을_즉시_반환한다(isolated_db, monkeypatch):
    """(a) 실시간 집계를 부르지 않고 pending=true 와 0 값을 돌려준다."""
    _add_announcement(isolated_db)
    _add_result(isolated_db)
    store, _sets = _isolated_cache(monkeypatch)
    calls = _forbid_realtime(monkeypatch)

    data = dashboard.get_compare_stats_data(isolated_db)

    assert data["pending"] is True
    assert data["stale"] is False
    assert data["announce_count"] == 0
    assert data["announce_total_base_amount"] == 0
    assert data["result_count"] == 0
    assert data["result_total_amt"] == 0
    assert data["matched_count"] == 0
    assert data["announce_by_month"] == []
    assert data["result_by_month"] == []
    assert data["agency_announce_top10"] == []
    assert calls == []
    assert store == {}


def test_직전_정상_응답이_있으면_stale_로_돌려준다(isolated_db, monkeypatch):
    """(b) 보조 캐시 값이 있으면 pending=false, stale=true 로 그 값을 쓴다."""
    _add_announcement(isolated_db)
    _add_result(isolated_db)
    snapshots.rebuild_compare_stats_snapshots(isolated_db)
    store, _sets = _isolated_cache(monkeypatch)

    fresh = dashboard.get_compare_stats_data(isolated_db)
    assert fresh["pending"] is False
    assert fresh["stale"] is False

    _expire_snapshots(isolated_db)
    for key in [key for key in store if not key.endswith(":last")]:
        store.pop(key)

    data = dashboard.get_compare_stats_data(isolated_db)

    assert data["pending"] is False
    assert data["stale"] is True
    assert data["announce_count"] == fresh["announce_count"] == 1
    assert data["result_count"] == fresh["result_count"] == 1
    assert data["matched_count"] == fresh["matched_count"] == 1
    assert data["agency_announce_top10"] == fresh["agency_announce_top10"]


def test_스냅숏이_신선하면_pending_과_stale_이_false_다(isolated_db, monkeypatch):
    """(c) 신선한 스냅숏 경로는 기존 값과 같고 표시 필드가 꺼져 있다."""
    _add_announcement(isolated_db)
    _add_result(isolated_db)
    snapshots.rebuild_compare_stats_snapshots(isolated_db)
    _store, _sets = _isolated_cache(monkeypatch)

    data = dashboard.get_compare_stats_data(isolated_db)

    assert data["pending"] is False
    assert data["stale"] is False
    assert data["announce_count"] == 1
    assert data["announce_total_base_amount"] == 1000000
    assert data["announce_total_prce"] == 1000000
    assert data["result_count"] == 1
    assert data["result_total_amt"] == 900000
    assert data["matched_count"] == 1
    assert data["announce_count_1y"] == 1
    assert data["matched_count_1y"] == 1
    assert data["announce_by_month"]
    assert data["result_by_month"]
    agency_row = isolated_db.get(BidCompareStatsSnapshot, snapshots.SNAPSHOT_KEY_AGENCY_TOP10)
    assert data["agency_announce_top10"] == agency_row.payload


def test_pending_응답은_일반_캐시와_보조_캐시에_저장되지_않는다(isolated_db, monkeypatch):
    """(d) pending 을 캐시하면 다음 요청이 0 값을 계속 보게 된다."""
    _add_announcement(isolated_db)
    _add_result(isolated_db)
    store, sets = _isolated_cache(monkeypatch)

    first = dashboard.get_compare_stats_data(isolated_db)
    second = dashboard.get_compare_stats_data(isolated_db)

    assert first["pending"] is True
    assert second["pending"] is True
    assert sets == []
    assert store == {}


def _claim():
    return scheduled_tasks.ScheduleClaimResult(
        status=scheduled_tasks.ScheduleClaimStatus.ACQUIRED,
        key=scheduled_tasks.COMPARE_STATS_WARM_CLAIM_KEY,
        owner="compare_stats_snapshot_warm",
        ttl=scheduled_tasks.COMPARE_STATS_WARM_JOB_TIMEOUT_SECONDS,
        token="test-token",
    )


def _patch_worker_io(monkeypatch, db):
    monkeypatch.setattr(scheduled_tasks, "SessionLocal", lambda: db)
    monkeypatch.setattr(scheduled_tasks, "acquire_schedule_claim", lambda *_a, **_k: _claim())
    monkeypatch.setattr(scheduled_tasks, "release_schedule_claim", lambda **_kwargs: None)
    monkeypatch.setattr("src.tasks.worker.record_schedule_result", lambda *_a, **_k: None)


def test_worker_작업은_스냅숏이_신선하면_재생성하지_않는다(isolated_db, monkeypatch):
    """(e) 신선하면 PK 조회만 하고 재집계를 부르지 않는다."""
    _add_announcement(isolated_db)
    _add_result(isolated_db)
    snapshots.rebuild_compare_stats_snapshots(isolated_db)
    _patch_worker_io(monkeypatch, isolated_db)

    def _fail(_db):
        raise AssertionError("스냅숏이 신선한데 재집계를 실행했다")

    monkeypatch.setattr(snapshots, "rebuild_compare_stats_snapshots", _fail)

    outcome = asyncio.run(scheduled_tasks.compare_stats_snapshot_warm_task({}))

    assert outcome["status"] == "skipped"
    assert outcome["reason"] == "snapshots_fresh"
    assert outcome["missing"] == []


def test_worker_작업은_빠진_스냅숏을_채운다(isolated_db, monkeypatch):
    """(e) 스냅숏이 없으면 재집계해 5종을 모두 만든다."""
    _add_announcement(isolated_db)
    _add_result(isolated_db)
    _patch_worker_io(monkeypatch, isolated_db)

    outcome = asyncio.run(scheduled_tasks.compare_stats_snapshot_warm_task({}))

    assert outcome["status"] == "success"
    assert sorted(outcome["missing_before"]) == sorted(SNAPSHOT_KEYS)
    for key in SNAPSHOT_KEYS:
        assert isolated_db.get(BidCompareStatsSnapshot, key) is not None


def test_worker_cron_에_5분_주기로_등록된다():
    from src.tasks.worker import WorkerSettings

    job = None
    for candidate in WorkerSettings.cron_jobs:
        target = getattr(candidate, "coroutine", candidate)
        if getattr(target, "__name__", "") == "compare_stats_snapshot_warm_task":
            job = candidate
            break

    assert job is not None
    assert set(job.minute) == scheduled_tasks.COMPARE_STATS_WARM_MINUTES
    assert job.run_at_startup is False
    assert job.timeout_s == scheduled_tasks.COMPARE_STATS_WARM_JOB_TIMEOUT_SECONDS
    assert "compare_stats_snapshot_warm_task" in {
        getattr(function, "__name__", "") for function in WorkerSettings.functions
    }


def test_비교_화면이_pending_을_처리하고_csp_nonce_를_쓴다():
    """(f) pending 이면 안내를 보이고 간격을 늘려 가며 다시 요청한다."""
    template = (
        Path(__file__).resolve().parents[1] / "src/app/templates/bids/compare.html"
    ).read_text(encoding="utf-8")

    assert "data.pending" in template
    assert "통계를 집계하고 있습니다" in template
    assert "COMPARE_PENDING_RETRY_MS = 10000" in template
    assert "COMPARE_PENDING_RETRY_MAX_MS = 60000" in template
    assert "COMPARE_PENDING_RETRY_WINDOW_MS = 10 * 60 * 1000" in template
    assert "setTimeout(loadCompareData" in template
    assert "data.stale" in template
    assert 'nonce="{{ csp_nonce }}"' in template


def test_실시간_집계_함수는_다른_호출자를_위해_남아_있다(isolated_db):
    """폴백 함수는 지우지 않고 스냅숏 값과 같은 값을 내는지 계속 확인한다."""
    now = utcnow()
    _add_announcement(isolated_db)
    _add_result(isolated_db)
    snapshots.rebuild_compare_stats_snapshots(isolated_db)
    matched_row = isolated_db.get(BidCompareStatsSnapshot, snapshots.SNAPSHOT_KEY_MATCHED_COUNT)

    one_year_ago = kst_now(now) - timedelta(days=365)

    assert dashboard._query_matched_count_realtime(isolated_db, one_year_ago) == 1
    assert dashboard._query_match_rate_1y_realtime(isolated_db, one_year_ago) == {
        "announce_count_1y": matched_row.payload["announce_count_1y"],
        "matched_count_1y": matched_row.payload["matched_count_1y"],
    }

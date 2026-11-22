"""비교 분석 '집계 중' 후속 보완 회귀 테스트.

2026-11-22 병합 3f4473fa 리뷰의 참고 관찰 두 건을 고정합니다.

1. 데이터셋 요약이 stale 로 바뀌는 순간에도 보조 캐시(`<key>:last`)에 남은
   직전 정상 값을 찾아 pending 대신 stale 로 답해야 합니다. 보조 캐시 키가
   stale 접미에 끌려가면(`<key>:stale:last`) 그 순간부터 pending 이 나갑니다.
2. 비교 화면의 pending 재요청은 worker 보충 주기(5분)보다 오래 이어져야 하고,
   탭이 숨겨지면 멈추고 다시 보이면 이어서 해야 합니다. 재시도를 끝낸 뒤에는
   자동 재요청을 약속하지 않고 새로고침을 안내해야 합니다.

시험은 SQLite 인메모리 픽스처와 가짜 캐시만 씁니다. 운영 DB·Redis 에
기대지 않습니다.
"""

from __future__ import annotations

import re
from datetime import timedelta
from pathlib import Path

from src.app.core.timeutil import utcnow
from src.app.models.bid_restrictions import BidAnnouncementLicenseLimit
from src.app.models.bids import (
    BidAnnouncement,
    BidCompareStatsSnapshot,
    BidResult,
)
from src.app.services import compare_stats_snapshots as snapshots
from src.app.services import dashboard

SNAPSHOT_KEYS = (
    snapshots.SNAPSHOT_KEY_AGENCY_TOP10,
    snapshots.SNAPSHOT_KEY_MATCHED_COUNT,
    snapshots.SNAPSHOT_KEY_ANNOUNCE_BY_MONTH,
    snapshots.SNAPSHOT_KEY_RESULT_BY_MONTH,
    snapshots.SNAPSHOT_KEY_INDUSTRY_TOTALS,
)

TEMPLATE_PATH = Path(__file__).resolve().parents[1] / "src/app/templates/bids/compare.html"


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


def _expire_snapshots(db) -> None:
    old = utcnow() - timedelta(days=3)
    for key in SNAPSHOT_KEYS:
        row = db.get(BidCompareStatsSnapshot, key)
        assert row is not None
        row.rebuilt_at = old
    db.commit()


def _make_summaries_stale(db) -> None:
    """수집 시각이 더 새로운 행을 넣어 데이터셋 요약을 stale 로 만듭니다.

    요약의 `source_latest_collected_at` 이 실제 최신 수집 시각과 달라지면
    `is_stale` 이 켜집니다. 캐시 키에 쓰는 값은 요약에 저장된 값이므로
    키 자체는 바뀌지 않고 stale 접미만 달라집니다.
    """
    _add_announcement(
        db,
        bid_ntce_no="PEND-002",
        bid_ntce_nm="요약 stale 유도 공고",
        collected_at=utcnow() + timedelta(minutes=5),
    )


def _last_good_keys(store: dict[str, object]) -> list[str]:
    return [key for key in store if key.endswith(":last")]


def test_요약이_stale_로_바뀌어도_직전_정상_값을_stale_로_돌려준다(isolated_db, monkeypatch):
    """(a) stale 전환 순간에도 `<key>:last` 값을 찾아 pending=false, stale=true 로 답한다."""
    _add_announcement(isolated_db)
    _add_result(isolated_db)
    snapshots.rebuild_compare_stats_snapshots(isolated_db)
    store, _sets = _isolated_cache(monkeypatch)
    monkeypatch.setattr(dashboard, "enqueue_rebuild_dataset_summary", lambda *_a, **_k: True)

    fresh = dashboard.get_compare_stats_data(isolated_db)
    assert fresh["pending"] is False
    assert fresh["stale"] is False
    last_keys = _last_good_keys(store)
    assert len(last_keys) == 1
    base_key = last_keys[0][: -len(":last")]

    _make_summaries_stale(isolated_db)
    _expire_snapshots(isolated_db)

    data = dashboard.get_compare_stats_data(isolated_db)

    assert data["pending"] is False
    assert data["stale"] is True
    assert data["announce_count"] == fresh["announce_count"] == 1
    assert data["result_count"] == fresh["result_count"] == 1
    assert data["matched_count"] == fresh["matched_count"] == 1
    assert data["announce_by_month"] == fresh["announce_by_month"]
    assert data["agency_announce_top10"] == fresh["agency_announce_top10"]
    # 보조 캐시 키는 stale 접미와 무관한 기준 키에서 파생되어야 합니다.
    assert f"{base_key}:stale:last" not in store
    assert base_key in store
    assert f"{base_key}:stale" not in store


def test_pending_과_stale_응답은_보조_캐시를_덮지_않는다(isolated_db, monkeypatch):
    """(b) pending 은 캐시를 만들지 않고, stale 은 직전 정상 값을 그대로 둔다."""
    _add_announcement(isolated_db)
    _add_result(isolated_db)
    store, sets = _isolated_cache(monkeypatch)
    monkeypatch.setattr(dashboard, "enqueue_rebuild_dataset_summary", lambda *_a, **_k: True)

    first = dashboard.get_compare_stats_data(isolated_db)

    assert first["pending"] is True
    assert sets == []
    assert store == {}

    snapshots.rebuild_compare_stats_snapshots(isolated_db)
    fresh = dashboard.get_compare_stats_data(isolated_db)
    assert fresh["pending"] is False
    assert fresh["stale"] is False
    set_count_after_fresh = len(sets)
    last_keys = _last_good_keys(store)
    assert len(last_keys) == 1
    last_key = last_keys[0]

    _make_summaries_stale(isolated_db)
    _expire_snapshots(isolated_db)

    data = dashboard.get_compare_stats_data(isolated_db)

    assert data["pending"] is False
    assert data["stale"] is True
    assert len(sets) == set_count_after_fresh
    assert store[last_key]["pending"] is False
    assert store[last_key]["stale"] is False
    assert not any(":stale:last" in key for key in store)


def test_비교_화면_재요청이_보충_주기를_덮고_숨김_탭에서_멈춘다():
    """(c) 재요청은 최소 10분, 숨김 탭에서는 정지, 종료 뒤에는 새로고침을 안내한다."""
    template = TEMPLATE_PATH.read_text(encoding="utf-8")

    window_match = re.search(r"COMPARE_PENDING_RETRY_WINDOW_MS = (\d+) \* 60 \* 1000", template)
    assert window_match is not None
    assert int(window_match.group(1)) >= 10
    assert "COMPARE_PENDING_RETRY_MS = 10000" in template
    assert "COMPARE_PENDING_RETRY_MAX_MS = 60000" in template
    assert "COMPARE_PENDING_MAX_RETRIES" not in template

    schedule_start = template.index("function scheduleComparePendingRetry")
    visibility_start = template.index("document.addEventListener('visibilitychange'")
    schedule_body = template[schedule_start:visibility_start]
    assert "if (document.hidden)" in schedule_body
    assert "setTimeout(loadCompareData" in schedule_body
    assert "clearComparePendingTimer();" in schedule_body

    give_up = re.search(r"if \(remaining <= 0\) \{(?P<body>.*?)\n        \}", template, re.S)
    assert give_up is not None
    give_up_body = give_up.group("body")
    assert "COMPARE_PENDING_FINAL_MESSAGE" in give_up_body
    assert "setTimeout" not in give_up_body
    assert "return;" in give_up_body

    assert (
        "COMPARE_PENDING_FINAL_MESSAGE = '통계 집계가 예상보다 오래 걸립니다. 잠시 후 새로고침해 주세요.'"
        in template
    )
    assert "comparePendingRetryStartedAt += Date.now() - comparePendingHiddenAt" in template
    assert 'nonce="{{ csp_nonce }}"' in template

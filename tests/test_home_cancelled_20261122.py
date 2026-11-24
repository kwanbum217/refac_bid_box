"""
tests/test_home_cancelled_20261122.py

홈 '입찰 중 공고'·'내 조건 입찰 중' 집계에서 최신 차수 취소공고를 빼는 계약.

막으려는 사고:
  - 구 공고번호의 최신 차수가 취소공고인데 재공고 신 번호와 함께 두 줄로 노출
  - 취소된 공고가 입찰 중 건수·마감 구간에 계속 세어지는 것
  - 취소 제외를 한쪽 집계에만 넣어 건수·목록·구간 정의가 갈리는 것
  - 공고종류가 NULL 인 정상 공고나 재공고·변경공고까지 빠지는 것
  - 캐시 키를 올리지 않아 옛 부풀린 값이 남는 것

실제 MySQL·Redis 에 연결하지 않고 SQLite 와 가짜 캐시를 씁니다.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pytest

from src.app.models.bid_restrictions import (
    BidAnnouncementLicenseLimit,
    BidAnnouncementParticipationRegion,
)
from src.app.models.bids import BidAnnouncement
from src.app.services import bid_preferences, home_summary
from src.app.services.bid_preferences import (
    BidPreferenceView,
    count_open_servc_matching,
    list_open_servc_matching,
)

NOW = datetime(2026, 11, 22, 9, 0)
SECURITY = "경비업/1164"
SEOUL_REGION = "서울특별시 중구"
CANCELLED = "취소공고"


def _add(
    db,
    *,
    no: str,
    ord: str = "000",
    kind: str | None = None,
    notice_days: int = -5,
    close_days: int = 2,
    nm: str | None = None,
) -> BidAnnouncement:
    row = BidAnnouncement(
        bid_ntce_no=no,
        bid_ntce_ord=ord,
        bid_ntce_nm=nm or f"공고 {no}/{ord}",
        category="Servc",
        ntce_kind_nm=kind,
        bid_ntce_dt=NOW + timedelta(days=notice_days),
        bid_clse_dt=NOW + timedelta(days=close_days),
        collected_at=NOW,
    )
    db.add(row)
    return row


def _license_and_region(db, row: BidAnnouncement) -> None:
    db.add(
        BidAnnouncementLicenseLimit(
            bid_ntce_no=row.bid_ntce_no,
            bid_ntce_ord=row.bid_ntce_ord,
            lmt_grp_no="1",
            lmt_sno="1",
            lcns_lmt_nm=SECURITY,
            collected_at=NOW,
        )
    )
    db.add(
        BidAnnouncementParticipationRegion(
            bid_ntce_no=row.bid_ntce_no,
            bid_ntce_ord=row.bid_ntce_ord,
            lmt_sno="1",
            prtcpt_psbl_rgn_nm=SEOUL_REGION,
            collected_at=NOW,
        )
    )


@pytest.fixture
def announced(isolated_db):
    """취소·재공고·변경공고·NULL 이 섞인 공고 픽스처입니다.

    기대하는 입찰 중 건수는 5 입니다.
      - CXL-REISSUE: 구번호 최신 001 취소, 신번호 CXL-REISSUE-NEW 000 등록 -> 1
      - CXL-ONLY: 최신(000) 취소 -> 0
      - KIND-NULL / KIND-NULL-LATEST: 공고종류 NULL -> 1 + 1
      - REISSUE: 최신 001 재공고 -> 1
      - CHANGED: 최신 001 변경공고 -> 1
    """
    rows: dict[str, BidAnnouncement] = {}
    rows["cxl_old"] = _add(
        isolated_db,
        no="CXL-REISSUE",
        ord="000",
        kind="등록공고",
        notice_days=-10,
        nm="서울신용보증재단 경비운영 용역",
    )
    rows["cxl_latest"] = _add(
        isolated_db,
        no="CXL-REISSUE",
        ord="001",
        kind=CANCELLED,
        notice_days=-9,
        nm="서울신용보증재단 경비운영 용역",
    )
    rows["cxl_reissue_new"] = _add(
        isolated_db,
        no="CXL-REISSUE-NEW",
        kind="등록공고",
        notice_days=-8,
        nm="서울신용보증재단 경비운영 용역",
    )
    rows["cxl_only"] = _add(
        isolated_db,
        no="CXL-ONLY",
        kind=CANCELLED,
        notice_days=-7,
    )
    rows["kind_null"] = _add(
        isolated_db,
        no="KIND-NULL",
        kind=None,
        close_days=1,
    )
    rows["kind_null_prev"] = _add(
        isolated_db,
        no="KIND-NULL-LATEST",
        ord="000",
        kind="등록공고",
        notice_days=-9,
    )
    rows["kind_null_latest"] = _add(
        isolated_db,
        no="KIND-NULL-LATEST",
        ord="001",
        kind=None,
        notice_days=-6,
        close_days=4,
    )
    rows["reissue_prev"] = _add(
        isolated_db,
        no="REISSUE",
        ord="000",
        kind="등록공고",
        notice_days=-12,
    )
    rows["reissue_latest"] = _add(
        isolated_db,
        no="REISSUE",
        ord="001",
        kind="재공고",
        notice_days=-4,
        close_days=6,
    )
    rows["changed_prev"] = _add(
        isolated_db,
        no="CHANGED",
        ord="000",
        kind="등록공고",
        notice_days=-11,
    )
    rows["changed_latest"] = _add(
        isolated_db,
        no="CHANGED",
        ord="001",
        kind="변경공고",
        notice_days=-3,
        close_days=9,
    )
    isolated_db.flush()
    for row in rows.values():
        _license_and_region(isolated_db, row)
    isolated_db.commit()
    return rows


def _prefs() -> BidPreferenceView:
    return BidPreferenceView(license_codes=["1164"], region_code="seoul")


# --------------------------------------------------------------------------- #
# (a) 구번호 최신 취소 + 신번호 등록: 신번호 1건만 남는다
# --------------------------------------------------------------------------- #


def test_cancelled_number_and_its_reissue_appear_once(isolated_db, announced):
    listed = list_open_servc_matching(isolated_db, _prefs(), now=NOW)
    listed_ids = [row["id"] for row in listed]

    assert listed_ids.count(announced["cxl_reissue_new"].id) == 1
    assert announced["cxl_old"].id not in listed_ids
    assert announced["cxl_latest"].id not in listed_ids
    # 두 집계 모두 최신 취소 2행을 빼고 5건이다.
    assert count_open_servc_matching(isolated_db, _prefs(), now=NOW) == 5
    assert home_summary._count_open_servc(isolated_db, NOW) == 5


def test_cancelled_rows_are_not_in_either_listing(isolated_db, announced):
    listed_ids = {row["id"] for row in list_open_servc_matching(isolated_db, _prefs(), now=NOW)}

    assert announced["cxl_old"].id not in listed_ids
    assert announced["cxl_latest"].id not in listed_ids
    assert announced["cxl_only"].id not in listed_ids


# --------------------------------------------------------------------------- #
# (b) 취소만 있는 번호는 제외한다
# --------------------------------------------------------------------------- #


def test_cancel_only_number_is_excluded_from_home_count(isolated_db, announced):
    cancel_ids = {announced["cxl_only"].id, announced["cxl_latest"].id}

    stmt_ids = {
        row.id
        for row in isolated_db.query(BidAnnouncement)
        .filter(BidAnnouncement.ntce_kind_nm == CANCELLED)
        .all()
    }

    assert stmt_ids == cancel_ids
    counted_ids = {row["id"] for row in list_open_servc_matching(isolated_db, _prefs(), now=NOW)}
    assert counted_ids.isdisjoint(cancel_ids)


# --------------------------------------------------------------------------- #
# (c) 공고종류 NULL 행은 유지한다
# --------------------------------------------------------------------------- #


def test_null_kind_rows_survive_both_aggregates(isolated_db, announced):
    listed_ids = {row["id"] for row in list_open_servc_matching(isolated_db, _prefs(), now=NOW)}

    assert announced["kind_null"].id in listed_ids
    assert announced["kind_null_latest"].id in listed_ids


# --------------------------------------------------------------------------- #
# (d) 재공고·변경공고는 유효하므로 제외하지 않는다
# --------------------------------------------------------------------------- #


def test_reissue_and_changed_rows_survive(isolated_db, announced):
    listed_ids = {row["id"] for row in list_open_servc_matching(isolated_db, _prefs(), now=NOW)}

    assert announced["reissue_latest"].id in listed_ids
    assert announced["changed_latest"].id in listed_ids
    assert announced["reissue_latest"].ntce_kind_nm == "재공고"
    assert announced["changed_latest"].ntce_kind_nm == "변경공고"


# --------------------------------------------------------------------------- #
# (e) 마감 구간 합 = 건수, 두 집계가 같은 정의를 쓴다
# --------------------------------------------------------------------------- #


def test_deadline_bucket_sum_equals_open_count(isolated_db, announced):
    buckets = home_summary._open_deadline_buckets(isolated_db, NOW)
    open_count = home_summary._count_open_servc(isolated_db, NOW)

    assert sum(bucket["count"] for bucket in buckets) == open_count
    # 신번호 1 + NULL 2 + 재공고 1 + 변경공고 1
    assert open_count == 5


def test_home_and_matching_aggregates_use_the_same_cancel_clause(isolated_db, announced):
    prefs = _prefs()
    matching_count = count_open_servc_matching(isolated_db, prefs, now=NOW)
    listed = list_open_servc_matching(isolated_db, prefs, now=NOW)

    assert matching_count == len(listed) == home_summary._count_open_servc(isolated_db, NOW)


# --------------------------------------------------------------------------- #
# 캐시 키 상향: 옛 부풀린 값이 남지 않는다
# --------------------------------------------------------------------------- #


class _RecordingCache:
    def __init__(self) -> None:
        self.sets: list[tuple[str, Any, int]] = []

    def get(self, key: str) -> Any:
        return None

    def set(self, key: str, value: Any, ttl: int) -> None:
        self.sets.append((key, value, ttl))


def test_cache_keys_moved_past_cancelled_inflated_versions(monkeypatch, isolated_db, announced):
    cache = _RecordingCache()
    monkeypatch.setattr(bid_preferences, "cache", cache)
    monkeypatch.setattr(bid_preferences, "kst_now", lambda: NOW)
    monkeypatch.setattr(home_summary, "cache", cache)
    monkeypatch.setattr(home_summary, "kst_now", lambda: NOW)

    count_open_servc_matching(isolated_db, _prefs(), use_cache=False)
    list_open_servc_matching(isolated_db, _prefs(), use_cache=False)
    home_summary.warm_home_summary_cache(isolated_db)

    written_keys = {key for key, _value, _ttl in cache.sets}
    assert bid_preferences.OPEN_BID_COUNT_CACHE_PREFIX.endswith(":v2")
    assert bid_preferences.OPEN_BID_LIST_CACHE_PREFIX.endswith(":v2")
    assert home_summary.SERVIC_COUNTS_CACHE_KEY.endswith(":v3")
    assert bid_preferences._count_cache_key(_prefs()) in written_keys
    assert (
        bid_preferences._list_cache_key(_prefs(), bid_preferences.OPEN_BID_LIST_DEFAULT_LIMIT)
        in written_keys
    )
    assert home_summary.SERVIC_COUNTS_CACHE_KEY in written_keys

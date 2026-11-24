"""
tests/test_home_prefs_open_perf_20261124.py

메인 화면 '내 조건 입찰 중' 건수·목록의 요청 경로 집계 제거 계약을 고정합니다.

막으려는 사고:
  - 캐시가 빈 요청이 49~60초짜리 공고 집계를 그 자리에서 실행하는 것
  - 신선 캐시가 만료되면 마지막 성공 값이 있어도 화면이 비는 것
  - 예열이 같은 관심 조건을 계정 수만큼 중복 집계하는 것
  - 예열 값과 즉시 집계 값의 건수·목록·순서가 달라지는 것
  - 마감일 인덱스 리비전이 멱등이 아니거나 이력 head 를 둘로 가르는 것

실제 MySQL·Redis 에 연결하지 않고 SQLite 와 테스트 메모리 캐시를 씁니다.
"""

from __future__ import annotations

import importlib.util
import inspect
from datetime import datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from fastapi.testclient import TestClient

from src.app.core.security import SESSION_COOKIE_NAME, create_session
from src.app.core.timeutil import utcnow
from src.app.main import app
from src.app.models.accounts import CustomUser
from src.app.models.bid_preferences import AccountBidPreference
from src.app.models.bid_restrictions import (
    BidAnnouncementLicenseLimit,
    BidAnnouncementParticipationRegion,
)
from src.app.models.bids import BidAnnouncement
from src.app.services import bid_preferences, home_summary
from src.app.services.bid_preferences import BidPreferenceView

BASE_TIME = datetime(2026, 11, 24, 12, 0, 0)
LICENSE = "1172"
REGION_CODE = "seoul"
REGION_NAME = "서울특별시"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
MIGRATION_PATH = (
    PROJECT_ROOT
    / "migrations"
    / "versions"
    / "b8d9e0f1a2b3_add_bid_announcements_cat_clse_index.py"
)


class FakeCache:
    """조회 캐시 대역. Redis 와 프로세스 로컬 저장소를 쓰지 않습니다."""

    def __init__(self) -> None:
        self.store: dict[str, Any] = {}
        self.sets: list[tuple[str, Any, int]] = []

    def get(self, key: str) -> Any:
        return self.store.get(key)

    def set(self, key: str, value: Any, ttl: int) -> None:
        self.store[key] = value
        self.sets.append((key, value, ttl))

    def delete(self, key: str) -> None:
        self.store.pop(key, None)


@pytest.fixture
def fake_cache(monkeypatch):
    fake = FakeCache()
    monkeypatch.setattr(bid_preferences, "cache", fake)
    monkeypatch.setattr(home_summary, "cache", fake)
    return fake


def _create_user(db, username: str) -> CustomUser:
    user = CustomUser(
        username=username,
        password="pbkdf2_sha256$1$salt$hash",
        email=f"{username}@example.com",
        nickname="관심 회원",
        is_active=True,
        is_staff=False,
        is_superuser=False,
        date_joined=utcnow(),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _store_preferences(
    db, user_id: int, license_codes: list[str], region_code: str
) -> AccountBidPreference:
    row = AccountBidPreference(
        user_id=user_id,
        license_codes=license_codes,
        region_code=region_code,
    )
    db.add(row)
    db.commit()
    return row


def _add_announcement(
    db,
    *,
    no: str,
    close_days: int = 2,
    category: str = "Servc",
    license_code: str = LICENSE,
    region_name: str = REGION_NAME,
) -> BidAnnouncement:
    row = BidAnnouncement(
        bid_ntce_no=no,
        bid_ntce_ord="000",
        bid_ntce_nm=f"공고 {no}",
        dminstt_nm="테스트발주기관",
        category=category,
        bid_ntce_dt=BASE_TIME - timedelta(days=1),
        bid_clse_dt=BASE_TIME + timedelta(days=close_days),
        collected_at=BASE_TIME,
    )
    db.add(row)
    db.flush()
    db.add(
        BidAnnouncementLicenseLimit(
            bid_ntce_no=no,
            bid_ntce_ord="000",
            lmt_grp_no="1",
            lmt_sno="1",
            lcns_lmt_nm=f"/{license_code}/",
            collected_at=BASE_TIME,
        )
    )
    db.add(
        BidAnnouncementParticipationRegion(
            bid_ntce_no=no,
            bid_ntce_ord="000",
            lmt_sno="1",
            prtcpt_psbl_rgn_nm=region_name,
            collected_at=BASE_TIME,
        )
    )
    db.commit()
    return row


def _auth_client(user: CustomUser) -> TestClient:
    token = create_session(user.id, user.username)
    return TestClient(app, cookies={SESSION_COOKIE_NAME: token})


# --------------------------------------------------------------------------- #
# (a) 캐시가 없으면 요청 경로는 집계하지 않고 '집계 중' 상태를 돌려준다
# --------------------------------------------------------------------------- #


def test_request_path_returns_pending_without_aggregating(
    isolated_db, fake_cache, monkeypatch, tmp_path
):
    monkeypatch.setattr(home_summary, "SERVING_ROOT", tmp_path)
    user = _create_user(isolated_db, "open_perf_pending")
    _store_preferences(isolated_db, user.id, [LICENSE], REGION_CODE)
    _add_announcement(isolated_db, no="OPEN-PERF-PENDING")

    def _fail(*args: Any, **kwargs: Any):
        raise AssertionError("요청 경로에서 관심 조건 집계를 실행했습니다")

    monkeypatch.setattr(bid_preferences, "_query_open_servc_count", _fail)
    monkeypatch.setattr(bid_preferences, "_query_open_servc_list", _fail)

    summary = home_summary.get_home_summary(isolated_db, user.id)

    assert summary["has_preferences"] is True
    assert summary["matching_count"] is None
    assert summary["matching_bids"] is None


def test_home_shows_pending_label_for_matching_panel(
    isolated_db, fake_cache, monkeypatch, tmp_path
):
    monkeypatch.setattr(home_summary, "SERVING_ROOT", tmp_path)
    user = _create_user(isolated_db, "open_perf_html")
    _store_preferences(isolated_db, user.id, [LICENSE], REGION_CODE)
    _add_announcement(isolated_db, no="OPEN-PERF-HTML")

    body = _auth_client(user).get("/").text

    # 입찰 중 공고와 내 조건 입찰 중, 두 패널 모두 캐시가 비어 '집계 중' 입니다.
    assert body.count("집계 중") == 2
    assert "data-home-matching-count" not in body


# --------------------------------------------------------------------------- #
# (b) 신선 키가 없고 보관 키만 있으면 보관 값을 보여 준다
# --------------------------------------------------------------------------- #


def test_stale_cache_is_used_when_fresh_key_is_gone(isolated_db, fake_cache, monkeypatch, tmp_path):
    monkeypatch.setattr(home_summary, "SERVING_ROOT", tmp_path)
    user = _create_user(isolated_db, "open_perf_stale")
    _store_preferences(isolated_db, user.id, [LICENSE], REGION_CODE)
    prefs = BidPreferenceView([LICENSE], REGION_CODE)
    items = [
        {
            "id": 77,
            "bid_ntce_nm": "보관된 공고",
            "dminstt_nm": "테스트발주기관",
            "deadline_label": "2026.11.26 12:00",
            "dday_label": "D-2",
        }
    ]
    fake_cache.set(
        bid_preferences._count_stale_cache_key(prefs),
        9,
        bid_preferences.OPEN_BID_STALE_CACHE_TTL,
    )
    fake_cache.set(
        bid_preferences._list_stale_cache_key(prefs, bid_preferences.OPEN_BID_LIST_DEFAULT_LIMIT),
        items,
        bid_preferences.OPEN_BID_STALE_CACHE_TTL,
    )

    summary = home_summary.get_home_summary(isolated_db, user.id)

    assert summary["matching_count"] == 9
    assert summary["matching_bids"] == items


def test_stale_cache_ttl_is_at_least_one_day() -> None:
    assert bid_preferences.OPEN_BID_STALE_CACHE_TTL >= 24 * 60 * 60
    assert bid_preferences.OPEN_BID_STALE_CACHE_TTL > bid_preferences.OPEN_BID_COUNT_CACHE_TTL


# --------------------------------------------------------------------------- #
# (c) 예열은 서로 다른 조건별로 한 번만 집계하고 두 키를 채운다
# --------------------------------------------------------------------------- #


def test_warm_aggregates_each_distinct_condition_once(isolated_db, fake_cache, monkeypatch):
    _store_preferences(isolated_db, 1, [LICENSE], REGION_CODE)
    _store_preferences(isolated_db, 2, [LICENSE], REGION_CODE)
    _store_preferences(isolated_db, 3, ["1164"], REGION_CODE)
    _store_preferences(isolated_db, 4, [], "")

    calls = {"count": 0, "list": 0}
    real_count = bid_preferences._query_open_servc_count
    real_list = bid_preferences._query_open_servc_list

    def counting_count(*args: Any, **kwargs: Any) -> int:
        calls["count"] += 1
        return real_count(*args, **kwargs)

    def counting_list(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        calls["list"] += 1
        return real_list(*args, **kwargs)

    monkeypatch.setattr(bid_preferences, "_query_open_servc_count", counting_count)
    monkeypatch.setattr(bid_preferences, "_query_open_servc_list", counting_list)
    monkeypatch.setattr(home_summary, "kst_now", lambda: BASE_TIME)

    payload = home_summary.warm_home_summary_cache(isolated_db)

    assert calls == {"count": 2, "list": 2}
    assert payload["matching_warmed"] == 2
    assert payload["matching_failed"] == 0

    for prefs in (
        BidPreferenceView([LICENSE], REGION_CODE),
        BidPreferenceView(["1164"], REGION_CODE),
    ):
        fresh_count_key = bid_preferences._count_cache_key(prefs)
        stale_count_key = bid_preferences._count_stale_cache_key(prefs)
        fresh_list_key = bid_preferences._list_cache_key(
            prefs, bid_preferences.OPEN_BID_LIST_DEFAULT_LIMIT
        )
        stale_list_key = bid_preferences._list_stale_cache_key(
            prefs, bid_preferences.OPEN_BID_LIST_DEFAULT_LIMIT
        )
        assert fresh_count_key in fake_cache.store
        assert stale_count_key in fake_cache.store
        assert fresh_list_key in fake_cache.store
        assert stale_list_key in fake_cache.store

    ttls = {key: ttl for key, _value, ttl in fake_cache.sets}
    assert ttls[bid_preferences._count_cache_key(BidPreferenceView([LICENSE], REGION_CODE))] == (
        bid_preferences.OPEN_BID_COUNT_CACHE_TTL
    )
    assert (
        ttls[bid_preferences._count_stale_cache_key(BidPreferenceView([LICENSE], REGION_CODE))]
        == bid_preferences.OPEN_BID_STALE_CACHE_TTL
    )


def test_warm_continues_after_one_condition_fails(isolated_db, fake_cache, monkeypatch):
    _store_preferences(isolated_db, 1, ["1172"], REGION_CODE)
    _store_preferences(isolated_db, 2, ["1164"], REGION_CODE)
    real_count = bid_preferences._query_open_servc_count

    def flaky_count(db, prefs, now_dt):
        if prefs.license_codes == ["1172"]:
            raise RuntimeError("집계 실패")
        return real_count(db, prefs, now_dt)

    monkeypatch.setattr(bid_preferences, "_query_open_servc_count", flaky_count)
    monkeypatch.setattr(home_summary, "kst_now", lambda: BASE_TIME)

    payload = home_summary.warm_home_summary_cache(isolated_db)

    assert payload["matching_warmed"] == 1
    assert payload["matching_failed"] == 1
    surviving = BidPreferenceView(["1164"], REGION_CODE)
    assert bid_preferences._count_stale_cache_key(surviving) in fake_cache.store


# --------------------------------------------------------------------------- #
# (d) 예열 값이 use_cache=False 즉시 집계와 같다 (건수·목록·순서)
# --------------------------------------------------------------------------- #


def test_warm_values_match_immediate_aggregation(isolated_db, fake_cache, monkeypatch):
    monkeypatch.setattr(bid_preferences, "kst_now", lambda: BASE_TIME)
    for index, close_days in enumerate((3, 1, 5, 2, 4, 6), start=1):
        _add_announcement(isolated_db, no=f"OPEN-PERF-{index}", close_days=close_days)
    _add_announcement(
        isolated_db,
        no="OPEN-PERF-OTHER-LICENSE",
        close_days=1,
        license_code="1164",
    )
    _add_announcement(
        isolated_db,
        no="OPEN-PERF-OTHER-REGION",
        close_days=1,
        region_name="부산광역시",
    )
    _add_announcement(
        isolated_db,
        no="OPEN-PERF-OTHER-CATEGORY",
        close_days=1,
        category="Cnstwk",
    )

    prefs = BidPreferenceView([LICENSE], REGION_CODE)
    bid_preferences.warm_open_servc_matching(isolated_db, prefs)

    warmed_count = bid_preferences.read_cached_open_servc_count(prefs)
    warmed_list = bid_preferences.read_cached_open_servc_list(prefs)
    immediate_count = bid_preferences.count_open_servc_matching(isolated_db, prefs, use_cache=False)
    immediate_list = bid_preferences.list_open_servc_matching(isolated_db, prefs, use_cache=False)

    assert warmed_count == immediate_count
    assert warmed_list == immediate_list
    assert [item["id"] for item in warmed_list or []] == [
        item["id"] for item in immediate_list or []
    ]


# --------------------------------------------------------------------------- #
# (e) 마감일 인덱스 리비전은 멱등이고 현재 head 를 잇는다
# --------------------------------------------------------------------------- #


def _load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("migration_b8d9e0f1a2b3", MIGRATION_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_index_migration_follows_current_head_and_is_idempotent() -> None:
    module = _load_migration()

    assert module.revision == "b8d9e0f1a2b3"
    assert module.down_revision == "d6e7f8a9b0c1"
    assert module.INDEX_NAME == "ix_bid_ann_cat_clse"
    assert module.TABLE_NAME == "bid_announcements"

    upgrade_source = inspect.getsource(module.upgrade)
    downgrade_source = inspect.getsource(module.downgrade)
    assert "_has_index()" in upgrade_source
    assert "_has_index()" in downgrade_source
    assert '["category", "bid_clse_dt"]' in upgrade_source

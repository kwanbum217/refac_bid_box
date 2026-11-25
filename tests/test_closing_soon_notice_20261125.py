"""
tests/test_closing_soon_notice_20261125.py

로그인 사용자 헤더의 '이번 주 마감 임박' 알림 계약을 고정합니다.

막으려는 사고:
  - 요청 경로가 마감 임박 건수를 그 자리에서 집계해 메인 화면이 다시 느려지는 것
  - 마감 임박 범위가 오늘~오늘+6일을 벗어나 다음 주 공고나 지난 마감이 섞이는 것
  - 취소공고가 알림 목록에 남는 것
  - 관심 조건이 없거나 비로그인인데 종 배지가 보이는 것
  - 알림 읽기 실패가 페이지 렌더를 실패시키는 것
  - 마감 임박 일수 상수가 RAG 질의 계획의 정의와 갈라지는 것

실제 MySQL·Redis 에 연결하지 않고 SQLite 와 시험 메모리 캐시를 씁니다.
"""

from __future__ import annotations

import inspect
from datetime import datetime, timedelta
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

BASE_TIME = datetime(2026, 11, 25, 12, 0, 0)
DAY_START = BASE_TIME.replace(hour=0, minute=0, second=0, microsecond=0)
LICENSE = "1172"
OTHER_LICENSE = "1164"
REGION_CODE = "seoul"
REGION_NAME = "서울특별시"
OTHER_REGION_NAME = "부산광역시"


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
        nickname="알림 회원",
        is_active=True,
        is_staff=False,
        is_superuser=False,
        date_joined=utcnow(),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _store_preferences(db, user_id: int, license_codes: list[str], region_code: str) -> None:
    db.add(
        AccountBidPreference(
            user_id=user_id,
            license_codes=license_codes,
            region_code=region_code,
        )
    )
    db.commit()


def _add_announcement(
    db,
    *,
    no: str,
    close_dt: datetime,
    ord: str = "000",
    category: str = "Servc",
    license_code: str = LICENSE,
    region_name: str = REGION_NAME,
    ntce_kind_nm: str | None = None,
) -> BidAnnouncement:
    row = BidAnnouncement(
        bid_ntce_no=no,
        bid_ntce_ord=ord,
        bid_ntce_nm=f"공고 {no}",
        dminstt_nm="테스트발주기관",
        category=category,
        ntce_kind_nm=ntce_kind_nm,
        bid_ntce_dt=BASE_TIME - timedelta(days=1),
        bid_clse_dt=close_dt,
        collected_at=BASE_TIME,
    )
    db.add(row)
    db.flush()
    db.add(
        BidAnnouncementLicenseLimit(
            bid_ntce_no=no,
            bid_ntce_ord=ord,
            lmt_grp_no="1",
            lmt_sno="1",
            lcns_lmt_nm=f"/{license_code}/",
            collected_at=BASE_TIME,
        )
    )
    db.add(
        BidAnnouncementParticipationRegion(
            bid_ntce_no=no,
            bid_ntce_ord=ord,
            lmt_sno="1",
            prtcpt_psbl_rgn_nm=region_name,
            collected_at=BASE_TIME,
        )
    )
    db.commit()
    return row


def _read_notice(prefs: BidPreferenceView) -> dict[str, Any] | None:
    """기준 코드에서는 없는 함수이므로 단언으로 실패하게 만듭니다."""
    reader = getattr(bid_preferences, "read_closing_soon_notice", None)
    assert callable(reader), "마감 임박 알림 읽기 함수가 없습니다"
    return reader(prefs)


def _seed_window(db) -> dict[str, BidAnnouncement]:
    """이번 주 안/밖, 취소공고, 다른 조건을 한 번에 심습니다."""
    return {
        "soon": _add_announcement(db, no="CS-SOON", close_dt=BASE_TIME + timedelta(days=1)),
        "mid": _add_announcement(db, no="CS-MID", close_dt=BASE_TIME + timedelta(days=3)),
        "end": _add_announcement(
            db,
            no="CS-END",
            close_dt=DAY_START + timedelta(days=7) - timedelta(seconds=1),
        ),
        "next_week": _add_announcement(
            db, no="CS-NEXT-WEEK", close_dt=DAY_START + timedelta(days=7)
        ),
        "closed": _add_announcement(db, no="CS-CLOSED", close_dt=BASE_TIME - timedelta(hours=1)),
        "cancelled_old": _add_announcement(
            db,
            no="CS-CXL",
            ord="000",
            close_dt=BASE_TIME + timedelta(days=2),
            ntce_kind_nm="등록공고",
        ),
        "cancelled": _add_announcement(
            db,
            no="CS-CXL",
            ord="001",
            close_dt=BASE_TIME + timedelta(days=2),
            ntce_kind_nm="취소공고",
        ),
        "other_license": _add_announcement(
            db,
            no="CS-OTHER-LICENSE",
            close_dt=BASE_TIME + timedelta(days=1),
            license_code=OTHER_LICENSE,
        ),
        "other_region": _add_announcement(
            db,
            no="CS-OTHER-REGION",
            close_dt=BASE_TIME + timedelta(days=1),
            region_name=OTHER_REGION_NAME,
        ),
        "other_category": _add_announcement(
            db,
            no="CS-OTHER-CATEGORY",
            close_dt=BASE_TIME + timedelta(days=1),
            category="Cnstwk",
        ),
    }


def _auth_client(user: CustomUser) -> TestClient:
    token = create_session(user.id, user.username)
    return TestClient(app, cookies={SESSION_COOKIE_NAME: token})


# --------------------------------------------------------------------------- #
# (a) 예열한 건수·목록은 오늘~오늘+6일 범위만 담는다
# --------------------------------------------------------------------------- #


def test_warm_notice_covers_today_through_day_six_only(isolated_db, fake_cache):
    rows = _seed_window(isolated_db)
    prefs = BidPreferenceView([LICENSE], REGION_CODE)

    bid_preferences.warm_open_servc_matching(isolated_db, prefs, now=BASE_TIME)
    notice = _read_notice(prefs)

    assert notice is not None
    assert notice["count"] == 3
    assert [item["id"] for item in notice["items"]] == [
        rows["soon"].id,
        rows["mid"].id,
        rows["end"].id,
    ]
    assert rows["next_week"].id not in {item["id"] for item in notice["items"]}


def test_notice_list_is_fastest_first_and_capped_at_five(isolated_db, fake_cache):
    prefs = BidPreferenceView([LICENSE], REGION_CODE)
    ordered = [
        _add_announcement(
            isolated_db,
            no=f"CS-LIMIT-{index}",
            close_dt=BASE_TIME + timedelta(days=index),
        )
        for index in (1, 2, 3, 4, 5, 6)
    ]

    bid_preferences.warm_open_servc_matching(isolated_db, prefs, now=BASE_TIME)
    notice = _read_notice(prefs)

    assert notice is not None
    assert notice["count"] == 6
    assert [item["id"] for item in notice["items"]] == [row.id for row in ordered[:5]]


# --------------------------------------------------------------------------- #
# (b) 지난 마감과 취소공고는 알림에서 빠진다
# --------------------------------------------------------------------------- #


def test_notice_excludes_closed_and_cancelled(isolated_db, fake_cache):
    rows = _seed_window(isolated_db)
    prefs = BidPreferenceView([LICENSE], REGION_CODE)

    bid_preferences.warm_open_servc_matching(isolated_db, prefs, now=BASE_TIME)
    notice = _read_notice(prefs)

    assert notice is not None
    included = {item["id"] for item in notice["items"]}
    assert included == {rows["soon"].id, rows["mid"].id, rows["end"].id}
    assert rows["closed"].id not in included
    assert rows["cancelled"].id not in included
    assert rows["cancelled_old"].id not in included


# --------------------------------------------------------------------------- #
# (c) 요청 경로는 캐시만 읽고 집계하지 않는다
# --------------------------------------------------------------------------- #


def test_read_notice_returns_none_without_cache_and_takes_no_session(isolated_db, fake_cache):
    prefs = BidPreferenceView([LICENSE], REGION_CODE)

    notice = _read_notice(prefs)

    assert notice is None
    reader = getattr(bid_preferences, "read_closing_soon_notice", None)
    assert callable(reader)
    assert "db" not in inspect.signature(reader).parameters


def test_page_does_not_aggregate_closing_soon_notice(
    isolated_db, fake_cache, monkeypatch, tmp_path
):
    monkeypatch.setattr(home_summary, "SERVING_ROOT", tmp_path)
    user = _create_user(isolated_db, "notice_no_aggregate")
    _store_preferences(isolated_db, user.id, [LICENSE], REGION_CODE)
    _seed_window(isolated_db)

    def _fail(*args: Any, **kwargs: Any):
        raise AssertionError("요청 경로에서 마감 임박 집계를 실행했습니다")

    monkeypatch.setattr(bid_preferences, "_query_closing_soon_count", _fail)
    monkeypatch.setattr(bid_preferences, "_query_closing_soon_list", _fail)

    response = _auth_client(user).get("/")

    assert response.status_code == 200
    assert "data-closing-soon-notice" in response.text
    assert "data-closing-soon-pending" in response.text
    assert "data-closing-soon-badge" not in response.text


# --------------------------------------------------------------------------- #
# (d) 로그인 + 관심 조건이 있을 때만 종 배지가 보인다
# --------------------------------------------------------------------------- #


def test_header_shows_badge_count_for_logged_in_preferences(
    isolated_db, fake_cache, monkeypatch, tmp_path
):
    monkeypatch.setattr(home_summary, "SERVING_ROOT", tmp_path)
    user = _create_user(isolated_db, "notice_badge")
    _store_preferences(isolated_db, user.id, [LICENSE], REGION_CODE)
    _seed_window(isolated_db)
    prefs = BidPreferenceView([LICENSE], REGION_CODE)
    bid_preferences.warm_open_servc_matching(isolated_db, prefs, now=BASE_TIME)

    body = _auth_client(user).get("/").text

    assert 'data-closing-soon-badge="3"' in body
    assert "이번 주 마감 임박" in body


def test_header_has_no_badge_without_preferences(isolated_db, fake_cache, monkeypatch, tmp_path):
    monkeypatch.setattr(home_summary, "SERVING_ROOT", tmp_path)
    user = _create_user(isolated_db, "notice_no_prefs")
    _seed_window(isolated_db)

    response = _auth_client(user).get("/")

    assert response.status_code == 200
    assert "data-closing-soon-notice" not in response.text
    assert "data-closing-soon-badge" not in response.text


def test_header_has_no_badge_for_anonymous(isolated_db, fake_cache, monkeypatch, tmp_path):
    monkeypatch.setattr(home_summary, "SERVING_ROOT", tmp_path)

    response = TestClient(app).get("/", follow_redirects=False)

    assert response.status_code == 303
    assert "data-closing-soon-badge" not in response.text


# --------------------------------------------------------------------------- #
# (e) 알림 읽기 실패는 페이지 렌더를 실패시키지 않는다
# --------------------------------------------------------------------------- #


def test_notice_read_failure_keeps_page_ok(isolated_db, fake_cache, monkeypatch, tmp_path):
    from src.app.api import ui as ui_module

    monkeypatch.setattr(home_summary, "SERVING_ROOT", tmp_path)
    user = _create_user(isolated_db, "notice_read_error")
    _store_preferences(isolated_db, user.id, [LICENSE], REGION_CODE)

    def _boom(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("캐시 장애")

    monkeypatch.setattr(ui_module, "read_closing_soon_notice", _boom)

    response = _auth_client(user).get("/")

    assert response.status_code == 200
    assert "data-closing-soon-notice" not in response.text


# --------------------------------------------------------------------------- #
# (f) 마감 임박 일수는 RAG 질의 계획의 정의와 같다
# --------------------------------------------------------------------------- #


def test_closing_soon_days_match_query_planning():
    from src.rag.query_planning import CLOSE_THIS_WEEK_DAYS

    days = getattr(bid_preferences, "CLOSING_SOON_DAYS", None)
    assert days is not None, "마감 임박 일수 상수가 없습니다"
    assert days == CLOSE_THIS_WEEK_DAYS

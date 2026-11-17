"""
tests/test_home_feedback_20261117.py

2026-11-17 사용자 웹 피드백 반영 계약을 고정합니다.

1. 하단 바로가기 4개가 사라지고 상단 지표는 정확도·최근 365일만 남는다.
2. 입찰 중 공고와 내 조건 입찰 중은 하단 2열 패널로 옮긴다.
3. 마감 구간 4개의 합은 입찰 중 건수와 같고 경계(오늘·3일·7일)가 KST 날짜 기준이다.
4. 내 조건 목록은 마감 임박 순 최대 5건이며 지난 공고·조건 밖 공고를 뺀다.
5. 내 조건 건수가 5 이하면 더보기가 없고 6 이상이면 관심 조건을 담은 더보기가 있다.
6. 홈 템플릿에 다크 모드 변형이 있다.

실제 MySQL·Redis 에 연결하지 않고 SQLite 와 테스트 메모리 캐시를 씁니다.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from src.app.core.security import SESSION_COOKIE_NAME, create_session, make_password
from src.app.core.timeutil import utcnow
from src.app.main import app
from src.app.models.accounts import CustomUser
from src.app.models.bid_preferences import AccountBidPreference
from src.app.models.bid_restrictions import (
    BidAnnouncementLicenseLimit,
    BidAnnouncementParticipationRegion,
)
from src.app.models.bids import BidAnnouncement
from src.app.services import home_summary
from src.app.services.bid_preferences import (
    BidPreferenceView,
    list_open_servc_matching,
)

BASE_TIME = datetime(2026, 11, 17, 12, 0, 0)
TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "src" / "app" / "templates"


def _add(db, **overrides) -> BidAnnouncement:
    payload: dict[str, Any] = {
        "bid_ntce_no": "ANN-BASE",
        "bid_ntce_ord": "000",
        "bid_ntce_nm": "기준 공고",
        "dminstt_nm": "테스트발주기관",
        "category": "Servc",
        "bid_ntce_dt": BASE_TIME - timedelta(days=1),
        "bid_clse_dt": BASE_TIME + timedelta(days=1),
        "collected_at": BASE_TIME,
    }
    payload.update(overrides)
    row = BidAnnouncement(**payload)
    db.add(row)
    db.commit()
    return row


def _add_license(db, bid: BidAnnouncement, code: str) -> None:
    db.add(
        BidAnnouncementLicenseLimit(
            bid_ntce_no=bid.bid_ntce_no,
            bid_ntce_ord=bid.bid_ntce_ord,
            lcns_lmt_nm=f"/{code}/",
            collected_at=BASE_TIME,
        )
    )
    db.commit()


def _add_region(db, bid: BidAnnouncement, name: str) -> None:
    db.add(
        BidAnnouncementParticipationRegion(
            bid_ntce_no=bid.bid_ntce_no,
            bid_ntce_ord=bid.bid_ntce_ord,
            prtcpt_psbl_rgn_nm=name,
            collected_at=BASE_TIME,
        )
    )
    db.commit()


@pytest.fixture(autouse=True)
def _serving_root(monkeypatch, tmp_path):
    monkeypatch.setattr(home_summary, "SERVING_ROOT", tmp_path)


@pytest.fixture
def seeded_user(isolated_db):
    user = CustomUser(
        username="home_feedback_tester",
        password=make_password("pw-test-1234"),
        email="home-feedback@example.com",
        nickname="피드백 검증",
        is_active=True,
        is_staff=False,
        is_superuser=False,
        date_joined=utcnow(),
    )
    isolated_db.add(user)
    isolated_db.commit()
    isolated_db.refresh(user)
    return user


@pytest.fixture
def auth_client(seeded_user):
    token = create_session(seeded_user.id, seeded_user.username)
    return TestClient(app, cookies={SESSION_COOKIE_NAME: token})


def _store_preferences(db, user, license_codes, region_code="") -> None:
    db.add(
        AccountBidPreference(
            user_id=user.id, license_codes=list(license_codes), region_code=region_code
        )
    )
    db.commit()


# --------------------------------------------------------------------------- #
# (a), (b) 화면 구성
# --------------------------------------------------------------------------- #


def test_home_removes_shortcuts_and_moves_open_matching_to_panels(auth_client):
    body = auth_client.get("/").text

    assert "data-home-shortcut" not in body
    for metric in ("accuracy", "recent-year"):
        assert f'data-home-metric="{metric}"' in body, metric
    for removed in ("open", "matching"):
        assert f'data-home-metric="{removed}"' not in body, removed
    for panel in ("open", "matching"):
        assert f'data-home-panel="{panel}"' in body, panel


# --------------------------------------------------------------------------- #
# (c) 마감 구간 경계
# --------------------------------------------------------------------------- #


def test_deadline_buckets_match_open_count_and_boundaries(isolated_db):
    _add(
        isolated_db,
        bid_ntce_no="BUCKET-TODAY",
        bid_clse_dt=datetime(2026, 11, 17, 18, 0, 0),
    )
    _add(
        isolated_db,
        bid_ntce_no="BUCKET-D1",
        bid_clse_dt=datetime(2026, 11, 18, 9, 0, 0),
    )
    _add(
        isolated_db,
        bid_ntce_no="BUCKET-D3",
        bid_clse_dt=datetime(2026, 11, 20, 23, 0, 0),
    )
    _add(
        isolated_db,
        bid_ntce_no="BUCKET-D4",
        bid_clse_dt=datetime(2026, 11, 21, 9, 0, 0),
    )
    _add(
        isolated_db,
        bid_ntce_no="BUCKET-D7",
        bid_clse_dt=datetime(2026, 11, 24, 23, 0, 0),
    )
    _add(
        isolated_db,
        bid_ntce_no="BUCKET-D8",
        bid_clse_dt=datetime(2026, 11, 25, 9, 0, 0),
    )
    # 이미 마감된 공고와 다른 분야는 어느 구간에도 들지 않는다.
    _add(
        isolated_db,
        bid_ntce_no="BUCKET-CLOSED",
        bid_clse_dt=BASE_TIME - timedelta(hours=1),
    )
    _add(
        isolated_db,
        bid_ntce_no="BUCKET-CNSTWK",
        category="Cnstwk",
        bid_clse_dt=datetime(2026, 11, 19, 9, 0, 0),
    )

    summary = home_summary.get_home_summary(isolated_db, None, now=BASE_TIME)
    buckets = {bucket["key"]: bucket["count"] for bucket in summary["open_deadline_buckets"]}

    assert buckets == {"today": 1, "d1_3": 2, "d4_7": 2, "d8_plus": 1}
    assert sum(buckets.values()) == summary["open_count"] == 6


# --------------------------------------------------------------------------- #
# (d) 내 조건 목록
# --------------------------------------------------------------------------- #


def test_matching_list_is_deadline_sorted_limited_and_filtered(isolated_db):
    added: dict[str, BidAnnouncement] = {}
    for offset in range(1, 8):
        bid = _add(
            isolated_db,
            bid_ntce_no=f"MATCH-{offset}",
            bid_ntce_nm=f"조건 공고 {offset}일",
            bid_clse_dt=BASE_TIME + timedelta(days=offset),
        )
        _add_license(isolated_db, bid, "1172")
        added[f"MATCH-{offset}"] = bid

    closed = _add(
        isolated_db,
        bid_ntce_no="MATCH-CLOSED",
        bid_clse_dt=BASE_TIME - timedelta(days=1),
    )
    _add_license(isolated_db, closed, "1172")

    other = _add(
        isolated_db,
        bid_ntce_no="MATCH-OTHER",
        bid_clse_dt=BASE_TIME + timedelta(days=1),
    )
    _add_license(isolated_db, other, "9999")

    prefs = BidPreferenceView(license_codes=["1172"], region_code="")
    rows = list_open_servc_matching(isolated_db, prefs, limit=5, now=BASE_TIME)

    assert [row["id"] for row in rows] == [added[f"MATCH-{offset}"].id for offset in range(1, 6)]
    assert len(rows) == 5
    assert all(row["dday_label"] == f"D-{index}" for index, row in enumerate(rows, start=1))


# --------------------------------------------------------------------------- #
# (e) 더보기 링크
# --------------------------------------------------------------------------- #


def test_no_more_link_when_matching_count_is_five_or_less(auth_client, isolated_db, seeded_user):
    _store_preferences(isolated_db, seeded_user, ["1172"], "seoul")
    bid = _add(
        isolated_db,
        bid_ntce_no="MATCH-ONE",
        bid_clse_dt=BASE_TIME + timedelta(days=2),
    )
    _add_license(isolated_db, bid, "1172")
    _add_region(isolated_db, bid, "서울특별시")

    body = auth_client.get("/").text

    assert "내 조건 공고 더보기" not in body
    assert 'data-home-matching-bid="' in body


def test_more_link_carries_license_and_region_when_count_exceeds_five(
    auth_client, isolated_db, seeded_user, monkeypatch
):
    _store_preferences(isolated_db, seeded_user, ["1172", "1268"], "seoul")
    monkeypatch.setattr(home_summary, "count_open_servc_matching", lambda *a, **k: 6)
    monkeypatch.setattr(home_summary, "list_open_servc_matching", lambda *a, **k: [])

    body = auth_client.get("/").text

    assert "내 조건 공고 더보기" in body
    assert "lic=1172,1268" in body
    assert "region=seoul" in body


# --------------------------------------------------------------------------- #
# (f) 다크 모드
# --------------------------------------------------------------------------- #


def test_home_template_has_dark_mode_variants():
    markup = (TEMPLATES_DIR / "index.html").read_text(encoding="utf-8")

    for token in (
        "dark:bg-slate-950",
        "dark:text-white",
        "dark:text-slate-400",
        "dark:bg-slate-800",
        "dark:bg-emerald-500/10",
    ):
        assert token in markup, token

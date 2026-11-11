"""
tests/test_bid_preferences_20261111.py

회원 관심 업종(면허)·지역 저장과 현재 입찰 중인 용역 공고 수 셈 검증.

검증 범위:
  - 저장·조회 왕복과 정의 밖 업종·지역 코드 제거, 사용자당 1행 유지
  - 마감 지난 공고·용역 외 분야·이전 차수·스캔 범위 밖 공고를 세지 않음
  - 업종·지역 조건이 공고 탐색 목록의 DB 경로와 같은 결과를 냄
  - 마이페이지 수정 POST 가 관심 업종·지역을 저장하고 화면에 표시함
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from src.app.core.config import settings
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
from src.app.services import bid_queries
from src.app.services.bid_preferences import (
    BidPreferenceView,
    count_open_servc_matching,
    get_bid_preferences,
    save_bid_preferences,
)
from tests.test_csrf import csrf_form

EDIT_URL = "/accounts/mypage/edit/"
MYPAGE_URL = "/accounts/mypage/"
NOW = datetime(2026, 11, 11, 9, 0)
SANITATION = "위생관리용역업/1162"
SECURITY = "경비업/1164"
SEOUL_REGION = "서울특별시 중구"
BUSAN_REGION = "부산광역시 중구"


def _create_user(db, username: str) -> CustomUser:
    user = CustomUser(
        username=username,
        password=make_password("pw-pref-1234"),
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


def _auth_client(user: CustomUser) -> TestClient:
    token = create_session(user.id, user.username)
    return TestClient(app, cookies={SESSION_COOKIE_NAME: token})


# --------------------------------------------------------------------------- #
# (1) 저장·조회 왕복과 정의 밖 코드 제거
# --------------------------------------------------------------------------- #


def test_save_and_get_roundtrip_drops_unknown_codes(isolated_db):
    user = _create_user(isolated_db, "pref_roundtrip")

    saved = save_bid_preferences(
        isolated_db,
        user.id,
        ["1162", "9999", "abcd", "1162"],
        "not-a-region",
    )
    isolated_db.commit()

    assert saved.license_codes == ["1162"]
    assert saved.region_code == ""
    assert saved.is_empty is False

    stored = get_bid_preferences(isolated_db, user.id)
    assert stored == saved


def test_save_updates_single_row_per_user_and_signals_empty(isolated_db):
    user = _create_user(isolated_db, "pref_upsert")

    save_bid_preferences(isolated_db, user.id, ["1162"], "seoul")
    isolated_db.commit()
    saved = save_bid_preferences(isolated_db, user.id, ["1164,1167"], "busan")
    isolated_db.commit()

    rows = (
        isolated_db.query(AccountBidPreference)
        .filter(AccountBidPreference.user_id == user.id)
        .all()
    )
    assert len(rows) == 1
    assert saved.license_codes == ["1164", "1167"]
    assert saved.region_code == "busan"

    cleared = save_bid_preferences(isolated_db, user.id, [], "")
    isolated_db.commit()
    assert cleared.is_empty is True
    assert count_open_servc_matching(isolated_db, cleared, now=NOW) == 0


def test_get_returns_none_before_first_save(isolated_db):
    user = _create_user(isolated_db, "pref_missing")
    assert get_bid_preferences(isolated_db, user.id) is None


# --------------------------------------------------------------------------- #
# 공고 픽스처
# --------------------------------------------------------------------------- #


def _announcement(
    db,
    *,
    no: str,
    ord: str = "000",
    category: str = "Servc",
    notice_days: int = -2,
    close_days: int = 3,
    nm: str | None = None,
) -> BidAnnouncement:
    row = BidAnnouncement(
        bid_ntce_no=no,
        bid_ntce_ord=ord,
        bid_ntce_nm=nm or f"공고 {no}",
        category=category,
        bid_ntce_dt=NOW + timedelta(days=notice_days),
        bid_clse_dt=NOW + timedelta(days=close_days),
        collected_at=NOW,
    )
    db.add(row)
    return row


def _license(db, no: str, ord: str = "000", text: str = SANITATION) -> None:
    db.add(
        BidAnnouncementLicenseLimit(
            bid_ntce_no=no,
            bid_ntce_ord=ord,
            lmt_grp_no="1",
            lmt_sno="1",
            lcns_lmt_nm=text,
            collected_at=NOW,
        )
    )


def _participation_region(db, no: str, ord: str = "000", region_name: str = SEOUL_REGION) -> None:
    db.add(
        BidAnnouncementParticipationRegion(
            bid_ntce_no=no,
            bid_ntce_ord=ord,
            lmt_sno="1",
            prtcpt_psbl_rgn_nm=region_name,
            collected_at=NOW,
        )
    )


def _seed_announcements(db) -> dict[str, BidAnnouncement]:
    rows = {
        "open": _announcement(db, no="PREF-OPEN"),
        "closed": _announcement(db, no="PREF-CLOSED", close_days=-1),
        "cnstwk": _announcement(db, no="PREF-CNSTWK", category="Cnstwk"),
        "prev_ord": _announcement(db, no="PREF-ORD", ord="000", notice_days=-3),
        "latest_ord": _announcement(db, no="PREF-ORD", ord="001"),
        "old": _announcement(db, no="PREF-OLD", notice_days=-120),
        "no_license": _announcement(db, no="PREF-NOLIC"),
        "other_region": _announcement(db, no="PREF-BUSAN"),
    }
    db.add_all(rows.values())
    db.flush()

    for row in rows.values():
        if row is not rows["no_license"]:
            _license(db, row.bid_ntce_no, row.bid_ntce_ord)
        region_name = BUSAN_REGION if row is rows["other_region"] else SEOUL_REGION
        _participation_region(db, row.bid_ntce_no, row.bid_ntce_ord, region_name)
    db.commit()
    return rows


# --------------------------------------------------------------------------- #
# (2) 마감·분야·차수·스캔 범위를 지켜 셈
# --------------------------------------------------------------------------- #


def test_count_ignores_closed_other_category_previous_ord_and_stale_rows(isolated_db):
    rows = _seed_announcements(isolated_db)
    prefs = BidPreferenceView(license_codes=["1162"], region_code="seoul")

    assert count_open_servc_matching(isolated_db, prefs, now=NOW) == 2

    counted = {"PREF-OPEN", "PREF-ORD"}
    assert rows["open"].bid_ntce_no in counted
    assert rows["closed"].bid_ntce_no not in counted
    assert rows["cnstwk"].bid_ntce_no not in counted
    assert rows["old"].bid_ntce_no not in counted
    assert rows["no_license"].bid_ntce_no not in counted
    assert rows["other_region"].bid_ntce_no not in counted


def test_count_with_empty_preferences_is_zero(isolated_db):
    _seed_announcements(isolated_db)

    assert count_open_servc_matching(isolated_db, BidPreferenceView([], ""), now=NOW) == 0
    assert count_open_servc_matching(isolated_db, None, now=NOW) == 0


# --------------------------------------------------------------------------- #
# (3) 업종·지역 조건이 공고 탐색 DB 경로와 같은 결과를 낸다
# --------------------------------------------------------------------------- #


def test_filters_match_announcement_explorer_db_path(monkeypatch, isolated_db):
    monkeypatch.setattr(settings, "MEILI_ENABLED", False, raising=False)
    rows = _seed_announcements(isolated_db)
    prefs = BidPreferenceView(license_codes=["1162"], region_code="seoul")

    page = bid_queries.list_announcements(
        isolated_db,
        cat="Servc",
        lic="1162",
        region="seoul",
    )
    listed_ids = {row.id for row in page.object_list}

    # 탐색 목록은 마감 전 조건을 걸지 않으므로 마감 지난 공고도 들어온다.
    assert rows["closed"].id in listed_ids

    open_ids = {
        row.id
        for row in page.object_list
        if row.bid_clse_dt is not None
        and row.bid_clse_dt >= NOW
        and row.bid_ntce_dt is not None
        and row.bid_ntce_dt >= NOW - timedelta(days=90)
    }
    assert count_open_servc_matching(isolated_db, prefs, now=NOW) == len(open_ids) == 2


# --------------------------------------------------------------------------- #
# (4) 마이페이지 수정 POST 저장과 표시
# --------------------------------------------------------------------------- #


def test_mypage_edit_saves_and_displays_bid_preferences(client, isolated_db):
    user = _create_user(isolated_db, "pref_mypage")
    auth_client = _auth_client(user)
    payload = {
        "nickname": "관심 회원",
        "email": "pref_mypage@example.com",
        "bid_license_codes": ["1162", "1164,1167"],
        "bid_region_code": "seoul",
    }

    response = auth_client.post(
        EDIT_URL,
        data=csrf_form(auth_client, EDIT_URL, payload),
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == MYPAGE_URL

    isolated_db.expire_all()
    stored = get_bid_preferences(isolated_db, user.id)
    assert stored is not None
    assert stored.license_codes == ["1162", "1164", "1167"]
    assert stored.region_code == "seoul"

    mypage_body = auth_client.get(MYPAGE_URL).text
    assert "위생관리용역업" in mypage_body
    assert "경비업" in mypage_body
    assert "서울특별시" in mypage_body

    edit_body = auth_client.get(EDIT_URL).text
    assert 'name="bid_license_codes" value="1162"' in edit_body
    assert 'name="bid_license_codes" value="1164,1167,1165,1168,2775"' in edit_body
    assert 'value="seoul" selected' in edit_body


def test_mypage_edit_rejects_unknown_region_code(client, isolated_db):
    user = _create_user(isolated_db, "pref_bad_region")
    auth_client = _auth_client(user)
    payload = {
        "nickname": "관심 회원",
        "email": "pref_bad_region@example.com",
        "bid_license_codes": ["9999"],
        "bid_region_code": "not-a-region",
    }

    response = auth_client.post(
        EDIT_URL,
        data=csrf_form(auth_client, EDIT_URL, payload),
        follow_redirects=False,
    )

    assert response.status_code == 303
    isolated_db.expire_all()
    stored = get_bid_preferences(isolated_db, user.id)
    assert stored is not None
    assert stored.is_empty is True


@pytest.mark.parametrize("code_csv", ["1162", "1164,1167,1165,1168,2775"])
def test_edit_form_checks_saved_industry_group(code_csv: str, client, isolated_db):
    user = _create_user(isolated_db, f"pref_group_{code_csv.split(',')[0]}")
    codes = bid_queries.normalize_license_codes(code_csv)
    save_bid_preferences(isolated_db, user.id, codes, "")
    isolated_db.commit()

    body = _auth_client(user).get(EDIT_URL).text

    assert f'name="bid_license_codes" value="{code_csv}"' in body
    assert body.count('name="bid_license_codes"') == len(bid_queries.BID_INDUSTRY_GROUPS)

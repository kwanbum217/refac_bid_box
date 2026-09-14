"""
tests/test_bid_detail_restrictions.py

공고 상세의 참가 자격 제한 카드: 면허제한 그룹·참가가능지역 표시와 미수집 공고 안내.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from src.app.core.security import SESSION_COOKIE_NAME, create_session, make_password
from src.app.core.timeutil import utcnow
from src.app.main import app
from src.app.models.accounts import CustomUser
from src.app.models.bid_restrictions import (
    BidAnnouncementLicenseLimit,
    BidAnnouncementParticipationRegion,
)
from src.app.models.bids import BidAnnouncement
from src.app.services import bid_queries


@pytest.fixture
def auth_client(isolated_db):
    user = CustomUser(
        username="restriction_tester",
        password=make_password("pw-test-1234"),
        email="restriction@example.com",
        nickname="제한 검증",
        is_active=True,
        is_staff=False,
        is_superuser=False,
        date_joined=utcnow(),
    )
    isolated_db.add(user)
    isolated_db.commit()
    token = create_session(user.id, user.username)
    return TestClient(app, cookies={SESSION_COOKIE_NAME: token})


def _bid(db, raw_data=None, ntce_no="R26BK00000001") -> BidAnnouncement:
    now = utcnow()
    bid = BidAnnouncement(
        bid_ntce_no=ntce_no,
        bid_ntce_ord="000",
        bid_ntce_nm="제한 검증 공고",
        dminstt_nm="검증기관",
        category="Servc",
        presmpt_prce=100_000_000,
        base_amount=100_000_000,
        bid_ntce_dt=now,
        bid_clse_dt=now + timedelta(days=7),
        collected_at=now,
        raw_data=raw_data,
    )
    db.add(bid)
    db.commit()
    db.refresh(bid)
    return bid


def _license(db, ntce_no, grp, sno, name, ord_="000", permitted=None):
    db.add(
        BidAnnouncementLicenseLimit(
            bid_ntce_no=ntce_no,
            bid_ntce_ord=ord_,
            lmt_grp_no=grp,
            lmt_sno=sno,
            lcns_lmt_nm=name,
            permsn_indstryty_list=permitted,
        )
    )


def test_restrictions_group_by_number_and_ignore_other_ord(isolated_db):
    bid = _bid(isolated_db, raw_data={"indstrytyLmtYn": "Y"})
    _license(isolated_db, bid.bid_ntce_no, "10", "1", "열번째그룹/9999")
    _license(isolated_db, bid.bid_ntce_no, "2", "2", "인쇄사/1518")
    _license(isolated_db, bid.bid_ntce_no, "2", "1", "출판사/1517", permitted="출판업")
    _license(isolated_db, bid.bid_ntce_no, "1", "1", "다른차수/0000", ord_="001")
    isolated_db.add(
        BidAnnouncementParticipationRegion(
            bid_ntce_no=bid.bid_ntce_no,
            bid_ntce_ord="000",
            lmt_sno="1",
            prtcpt_psbl_rgn_nm="부산광역시",
        )
    )
    isolated_db.commit()

    result = bid_queries.get_announcement_restrictions(isolated_db, bid)

    assert [g["group_no"] for g in result["license_groups"]] == ["2", "10"]
    assert result["license_groups"][0]["licenses"] == [
        {"name": "출판사/1517", "permitted": "출판업"},
        {"name": "인쇄사/1518", "permitted": None},
    ]
    assert result["regions"] == ["부산광역시"]
    assert result["industry_limited"] == "Y"
    assert result["collected"] is True


def test_detail_renders_groups_regions_and_multi_group_notice(auth_client, isolated_db):
    bid = _bid(isolated_db, raw_data={"indstrytyLmtYn": "Y"})
    _license(isolated_db, bid.bid_ntce_no, "1", "1", "정보통신공사업/0036")
    _license(isolated_db, bid.bid_ntce_no, "2", "1", "전기공사업/0038")
    isolated_db.add(
        BidAnnouncementParticipationRegion(
            bid_ntce_no=bid.bid_ntce_no,
            bid_ntce_ord="000",
            lmt_sno="1",
            prtcpt_psbl_rgn_nm="충청남도 공주시",
        )
    )
    isolated_db.commit()

    body = auth_client.get(f"/bids/{bid.id}/").text

    assert 'id="participation-restrictions"' in body
    assert "제한그룹 1" in body
    assert "제한그룹 2" in body
    assert "정보통신공사업/0036" in body
    assert "전기공사업/0038" in body
    assert "충청남도 공주시" in body
    assert "2개 그룹 중 하나를 충족하면 참가할 수 있고" in body
    assert "최종 자격은 공고문에서 확인하십시오" in body
    assert 'id="restriction-groups-more"' not in body
    assert "restrictions-not-collected" not in body


def test_detail_explains_uncollected_industry_limit(auth_client, isolated_db):
    bid = _bid(isolated_db, raw_data={"indstrytyLmtYn": "Y"})

    body = auth_client.get(f"/bids/{bid.id}/").text

    assert 'id="restrictions-not-collected"' in body
    assert "제한그룹" not in body


def test_detail_hides_card_without_restrictions(auth_client, isolated_db):
    bid = _bid(isolated_db, raw_data={"indstrytyLmtYn": "N"})

    body = auth_client.get(f"/bids/{bid.id}/").text

    assert 'id="participation-restrictions"' not in body


def test_detail_collapses_groups_beyond_three_and_marks_joint_requirement(auth_client, isolated_db):
    bid = _bid(isolated_db, raw_data={"indstrytyLmtYn": "Y"})
    for grp in range(1, 6):
        _license(isolated_db, bid.bid_ntce_no, str(grp), "1", f"업종A{grp}/000{grp}")
        _license(isolated_db, bid.bid_ntce_no, str(grp), "2", f"업종B{grp}/100{grp}")
    isolated_db.commit()

    body = auth_client.get(f"/bids/{bid.id}/").text

    visible, _, collapsed = body.partition('id="restriction-groups-more"')
    assert "업종A3/0003" in visible
    assert "업종A4/0004" not in visible
    assert "나머지 2개 그룹 펼치기" in collapsed
    assert "업종A5/0005" in collapsed
    assert "제한그룹 1 (모두 필요)" in body


def test_detail_blocked_guidance_is_per_reason(auth_client, isolated_db):
    bid = _bid(isolated_db, raw_data={"indstrytyLmtYn": "N"})

    body = auth_client.get(f"/bids/{bid.id}/").text

    assert 'id="blocked-guidance"' in body
    assert "function getBlockedGuidanceText(code)" in body
    assert (
        body.count("$('#blocked-guidance').text(getBlockedGuidanceText(data.blocked_reason));") == 2
    )
    for code in (
        "NOT_SERVC",
        "NON_PRED_PRICE",
        "MANUAL_EVALUATION",
        "RULE_NOT_FOUND",
        "NOT_QUALIFICATION_METHOD",
        "RULE_REGIME_MISMATCH",
        "NEGOTIATION_CONTRACT",
        "TECH_SERVICE_MISSING_LWLT",
    ):
        assert (
            f"'{code}':"
            in body.split("function getBlockedGuidanceText(code)")[1].split("function ")[0]
        )

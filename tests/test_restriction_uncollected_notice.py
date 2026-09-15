"""tests/test_restriction_uncollected_notice.py

공고일 2025-07-01 이전 입찰 중 공고의 참가 제한정보 미수집 안내 회귀 테스트.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from src.app.core.security import SESSION_COOKIE_NAME, create_session, make_password
from src.app.core.timeutil import utcnow
from src.app.main import app
from src.app.models.accounts import CustomUser
from src.app.models.bid_restrictions import BidAnnouncementParticipationRegion
from src.app.models.bids import BidAnnouncement
from src.app.services import bid_queries


@pytest.fixture
def auth_client(isolated_db):
    user = CustomUser(
        username="uncollected_tester",
        password=make_password("pw-test-1234"),
        email="uncollected@example.com",
        nickname="미수집 검증",
        is_active=True,
        is_staff=False,
        is_superuser=False,
        date_joined=utcnow(),
    )
    isolated_db.add(user)
    isolated_db.commit()
    token = create_session(user.id, user.username)
    return TestClient(app, cookies={SESSION_COOKIE_NAME: token})


def _create_bid(
    db,
    bid_ntce_no: str,
    bid_ntce_dt: datetime,
    bid_clse_dt: datetime,
) -> BidAnnouncement:
    bid = BidAnnouncement(
        bid_ntce_no=bid_ntce_no,
        bid_ntce_ord="000",
        bid_ntce_nm="미수집 테스트 공고",
        dminstt_nm="테스트수요기관",
        category="Servc",
        presmpt_prce=50_000_000,
        base_amount=50_000_000,
        bid_ntce_dt=bid_ntce_dt,
        bid_clse_dt=bid_clse_dt,
        collected_at=utcnow(),
    )
    db.add(bid)
    db.commit()
    db.refresh(bid)
    return bid


def test_legacy_open_uncollected_notice_rendered(isolated_db, auth_client):
    """(a) 2025-06 공고, 마감 전, 제한정보 없음 -> uncollected_legacy True 및 안내 id 노출."""
    now = utcnow()
    bid = _create_bid(
        isolated_db,
        bid_ntce_no="LEGACY-202506-OPEN",
        bid_ntce_dt=datetime(2025, 6, 15, 10, 0),
        bid_clse_dt=now + timedelta(days=10),
    )

    restrictions = bid_queries.get_announcement_restrictions(isolated_db, bid)
    assert restrictions["uncollected_legacy"] is True

    response = auth_client.get(f"/bids/{bid.id}/")
    assert response.status_code == 200
    assert 'id="restriction-uncollected-notice"' in response.text
    assert (
        "이 공고는 참가 제한정보(면허·지역)를 수집하지 않은 과거 공고입니다. 공고문에서 참가 자격을 확인하십시오."
        in response.text
    )


def test_newer_announcement_not_uncollected_legacy(isolated_db, auth_client):
    """(b) 2025-08 공고 -> uncollected_legacy False 및 안내 id 미노출."""
    now = utcnow()
    bid = _create_bid(
        isolated_db,
        bid_ntce_no="NEWER-202508-OPEN",
        bid_ntce_dt=datetime(2025, 8, 15, 10, 0),
        bid_clse_dt=now + timedelta(days=10),
    )

    restrictions = bid_queries.get_announcement_restrictions(isolated_db, bid)
    assert restrictions["uncollected_legacy"] is False

    response = auth_client.get(f"/bids/{bid.id}/")
    assert response.status_code == 200
    assert 'id="restriction-uncollected-notice"' not in response.text


def test_legacy_with_restrictions_not_uncollected_legacy(isolated_db, auth_client):
    """(c) 제한정보가 있는 공고 -> uncollected_legacy False 및 안내 id 미노출."""
    now = utcnow()
    bid = _create_bid(
        isolated_db,
        bid_ntce_no="LEGACY-202506-HAS-RESTR",
        bid_ntce_dt=datetime(2025, 6, 15, 10, 0),
        bid_clse_dt=now + timedelta(days=10),
    )
    isolated_db.add(
        BidAnnouncementParticipationRegion(
            bid_ntce_no=bid.bid_ntce_no,
            bid_ntce_ord="000",
            lmt_sno="1",
            prtcpt_psbl_rgn_nm="서울특별시",
        )
    )
    isolated_db.commit()

    restrictions = bid_queries.get_announcement_restrictions(isolated_db, bid)
    assert restrictions["collected"] is True
    assert restrictions["uncollected_legacy"] is False

    response = auth_client.get(f"/bids/{bid.id}/")
    assert response.status_code == 200
    assert 'id="restriction-uncollected-notice"' not in response.text
    assert 'id="participation-restrictions"' in response.text


def test_closed_legacy_announcement_not_uncollected_legacy(isolated_db, auth_client):
    """(d) 마감 지난 과거 공고 -> uncollected_legacy False 및 안내 id 미노출."""
    bid = _create_bid(
        isolated_db,
        bid_ntce_no="LEGACY-202506-CLOSED",
        bid_ntce_dt=datetime(2025, 6, 15, 10, 0),
        bid_clse_dt=datetime(2025, 6, 25, 18, 0),
    )

    restrictions = bid_queries.get_announcement_restrictions(isolated_db, bid)
    assert restrictions["uncollected_legacy"] is False

    response = auth_client.get(f"/bids/{bid.id}/")
    assert response.status_code == 200
    assert 'id="restriction-uncollected-notice"' not in response.text

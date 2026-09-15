"""tests/test_negotiation_notice.py

협상에의한계약 공고 가격점수 미계산 안내 회귀 테스트.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from src.app.core.security import SESSION_COOKIE_NAME, create_session, make_password
from src.app.core.timeutil import utcnow
from src.app.main import app
from src.app.models.accounts import CustomUser
from src.app.models.bids import BidAnnouncement


@pytest.fixture
def auth_client(isolated_db):
    user = CustomUser(
        username="negotiation_tester",
        password=make_password("pw-test-1234"),
        email="negotiation@example.com",
        nickname="협상 검증",
        is_active=True,
        is_staff=False,
        is_superuser=False,
        date_joined=utcnow(),
    )
    isolated_db.add(user)
    isolated_db.commit()
    token = create_session(user.id, user.username)
    return TestClient(app, cookies={SESSION_COOKIE_NAME: token})


def test_negotiation_announcement_has_price_score_notice(isolated_db, auth_client):
    """협상에의한계약 공고 상세 HTML에 negotiation-price-score-notice가 노출된다."""
    now = utcnow()
    bid = BidAnnouncement(
        bid_ntce_no="NEGOTIATION-2026-001",
        bid_ntce_ord="000",
        bid_ntce_nm="협상 대상 정보시스템 구축 사업",
        dminstt_nm="한국지능정보사회진흥원",
        category="Servc",
        presmpt_prce=300_000_000,
        base_amount=300_000_000,
        cntrct_mthd_nm="협상에 의한 계약",
        bid_ntce_dt=now,
        bid_clse_dt=now + timedelta(days=14),
        collected_at=now,
        raw_data={
            "sucsfbidMthdNm": "협상에의한계약-협상에 의한 낙찰자 결정(SW사업)",
            "techAbltEvlRt": "80",
            "bidPrceEvlRt": "20",
        },
    )
    isolated_db.add(bid)
    isolated_db.commit()
    isolated_db.refresh(bid)

    response = auth_client.get(f"/bids/{bid.id}/")
    assert response.status_code == 200
    assert 'id="negotiation-price-score-notice"' in response.text
    assert (
        "협상에의한계약은 공고별로 가격점수 산식이 달라 가격점수는 계산하지 않습니다. 기술·가격 평가비율과 낙찰률 참고 분포만 제공합니다."
        in response.text
    )


def test_general_announcement_has_no_price_score_notice(isolated_db, auth_client):
    """일반 공고 상세 HTML에는 negotiation-price-score-notice가 노출되지 않는다."""
    now = utcnow()
    bid = BidAnnouncement(
        bid_ntce_no="GENERAL-2026-001",
        bid_ntce_ord="000",
        bid_ntce_nm="일반 적격심사 시설물 유지보수 용역",
        dminstt_nm="서울특별시",
        category="Servc",
        presmpt_prce=150_000_000,
        base_amount=150_000_000,
        cntrct_mthd_nm="일반경쟁",
        bid_ntce_dt=now,
        bid_clse_dt=now + timedelta(days=14),
        collected_at=now,
        raw_data={
            "sucsfbidMthdNm": "적격심사",
        },
    )
    isolated_db.add(bid)
    isolated_db.commit()
    isolated_db.refresh(bid)

    response = auth_client.get(f"/bids/{bid.id}/")
    assert response.status_code == 200
    assert 'id="negotiation-price-score-notice"' not in response.text

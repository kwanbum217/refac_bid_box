"""공고 상세 사양 카드의 '낙찰 방법' 표시 회귀 테스트.

원본 raw_data 의 sucsfbidMthdNm·sucsfbidMthdCd 로 계산한 표기를 순수 함수와
실제 렌더링 결과에서 함께 고정합니다.
"""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from src.app.core.security import SESSION_COOKIE_NAME, create_session, make_password
from src.app.core.timeutil import utcnow
from src.app.main import app
from src.app.models.accounts import CustomUser
from src.app.models.bids import BidAnnouncement
from src.app.services import bid_queries


@pytest.mark.parametrize(
    ("raw", "label", "source"),
    [
        ({"sucsfbidMthdNm": "적격심사"}, "적격심사", "ANNOUNCEMENT"),
        ({"sucsfbidMthdNm": "공고서참조", "sucsfbidMthdCd": "낙030001"}, "적격심사제", "CODE"),
        ({"sucsfbidMthdNm": "공고서참조", "sucsfbidMthdCd": "낙999999"}, "공고서 참조", None),
        ({"sucsfbidMthdNm": "공고서참조"}, "공고서 참조", None),
        ({}, "-", None),
        ({"sucsfbidMthdCd": "낙030001"}, "적격심사제", "CODE"),
        ({"sucsfbidMthdNm": 123}, "-", None),
        ({"sucsfbidMthdNm": None, "sucsfbidMthdCd": None}, "-", None),
    ],
)
def test_describe_award_method(raw, label, source):
    assert bid_queries.describe_award_method(raw) == {"label": label, "source": source}


@pytest.mark.parametrize("raw", [None, "공고서참조", [], 42])
def test_describe_award_method_non_dict_returns_placeholder(raw):
    assert bid_queries.describe_award_method(raw) == {"label": "-", "source": None}


@pytest.fixture
def seeded_user(isolated_db):
    user = CustomUser(
        username="award_tester",
        password=make_password("pw-test-1234"),
        email="award@example.com",
        nickname="낙찰방법 검증",
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


def _seed_bid(isolated_db, raw_data):
    now = utcnow()
    bid = BidAnnouncement(
        bid_ntce_no=f"20260801-AWARD-{abs(hash(repr(raw_data))) % 100000}",
        bid_ntce_ord="00",
        bid_ntce_nm="낙찰방법 표시 검증 공고",
        dminstt_nm="테스트발주기관",
        category="Servc",
        presmpt_prce=1_000_000_000,
        base_amount=990_000_000,
        bid_ntce_dt=now,
        bid_clse_dt=now + timedelta(days=7),
        collected_at=now,
        raw_data=raw_data,
    )
    isolated_db.add(bid)
    isolated_db.commit()
    isolated_db.refresh(bid)
    return bid


def test_detail_renders_announcement_method_name(auth_client, isolated_db):
    bid = _seed_bid(isolated_db, {"sucsfbidMthdNm": "적격심사"})

    body = auth_client.get(f"/bids/{bid.id}/").text

    assert "낙찰 방법" in body
    assert "적격심사" in body
    assert "(코드 기준)" not in body


def test_detail_renders_code_based_method_name(auth_client, isolated_db):
    bid = _seed_bid(isolated_db, {"sucsfbidMthdNm": "공고서참조", "sucsfbidMthdCd": "낙030001"})

    body = auth_client.get(f"/bids/{bid.id}/").text

    assert "낙찰 방법" in body
    assert "적격심사제" in body
    assert "(코드 기준)" in body


def test_detail_renders_placeholder_when_method_unresolved(auth_client, isolated_db):
    bid = _seed_bid(isolated_db, {"sucsfbidMthdNm": "공고서참조", "sucsfbidMthdCd": "낙999999"})

    body = auth_client.get(f"/bids/{bid.id}/").text

    assert "낙찰 방법" in body
    assert "공고서 참조" in body

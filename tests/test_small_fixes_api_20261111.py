"""2026-11-11 재현 보고서 소규모 결함 회귀 시험.

정본: `.orca/capsules/task_small_fixes_api_20261111/capsule.yaml`

GET /api/v1/evaluations/rules 는 bid_id 없이 부르면 종전처럼 공개 목록을 돌려주고,
bid_id 를 주면 공고·첨부 판별 정보를 조회하므로 로그인과 API 쿼터를 요구한다.
실물 DB 는 쓰지 않고 conftest 의 isolated_db(SQLite 인메모리) 위에서 동작한다.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.app.api.v1 import evaluations
from src.app.api.v1.accounts import get_current_user
from src.app.core.timeutil import utcnow
from src.app.main import app
from src.app.models.bids import BidAnnouncement

RULES_URL = "/api/v1/evaluations/rules"
FACILITY_METHOD = "시설분야용역 적격심사 추정가격 5억원 미만"
FACILITY_RULE_ID = "SERVC_QUAL_POST_20260526_ATTACH_01"
USER_ID = 7


def _create_bid(db) -> BidAnnouncement:
    bid = BidAnnouncement(
        bid_ntce_nm="소규모 결함 회귀 시험 공고",
        bid_ntce_no="SMALL-FIX-20261111",
        bid_ntce_ord="000",
        ntce_instt_nm="테스트 공고기관",
        dminstt_nm="테스트 수요기관",
        base_amount=500_000_000,
        presmpt_prce=500_000_000,
        bid_ntce_dt=utcnow(),
        bid_clse_dt=utcnow(),
        openg_dt=utcnow(),
        category="Servc",
        raw_data={
            "prearngPrceDcsnMthdNm": "복수예가",
            "sucsfbidMthdNm": FACILITY_METHOD,
            "sucsfbidLwltRate": "89.995",
            "srvceDivNm": "일반용역",
            "bidNtceDt": "2026-09-30",
        },
    )
    db.add(bid)
    db.commit()
    db.refresh(bid)
    return bid


@pytest.fixture
def as_logged_in_user():
    """세션 쿠키 없이 요청 사용자만 인증 상태로 바꾸는 대역."""

    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=USER_ID, is_active=True)
    yield
    app.dependency_overrides.pop(get_current_user, None)


def test_rules_without_bid_id_is_public(client):
    """bid_id 없는 공개 목록은 미로그인도 그대로 열린다."""
    response = client.get(RULES_URL)

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["matched_rule"] is None
    assert len(payload["rules"]) == 20


def test_rules_with_bid_id_requires_login(client, isolated_db):
    """bid_id 로 공고 판별 정보를 조회하는 호출은 미로그인에서 401 이다."""
    bid = _create_bid(isolated_db)

    response = client.get(RULES_URL, params={"bid_id": bid.id})

    assert response.status_code == 401, response.text


def test_rules_with_bid_id_keeps_matched_rule_when_logged_in(
    client, isolated_db, as_logged_in_user
):
    """로그인 상태의 bid_id 호출은 기존 matched_rule 동작을 유지한다."""
    bid = _create_bid(isolated_db)

    response = client.get(RULES_URL, params={"bid_id": bid.id})

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["matched_rule"] is not None
    assert payload["matched_rule"]["rule_id"] == FACILITY_RULE_ID
    assert len(payload["rules"]) == 20


def test_rules_applies_quota_once_for_bid_id(client, isolated_db, as_logged_in_user, monkeypatch):
    """bid_id 호출은 쿼터 함수를 정확히 한 번 거친다."""
    bid = _create_bid(isolated_db)
    calls: list[tuple[object, object]] = []

    def _record(request, user):
        calls.append((request, user))

    monkeypatch.setattr(evaluations, "enforce_anonymous_api_quota", _record)

    response = client.get(RULES_URL, params={"bid_id": bid.id})

    assert response.status_code == 200, response.text
    assert len(calls) == 1
    assert getattr(calls[0][1], "id", None) == USER_ID

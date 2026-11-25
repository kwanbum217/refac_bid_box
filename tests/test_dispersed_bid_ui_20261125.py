"""공고 상세 사용자별 분산 추천 투찰가 계약 시험 (2026-11-25).

정본: .orca/capsules/task_dispersed_bid_ui_20261125/capsule.yaml

사용자 결정 A안:
 - 같은 정량점수의 서로 다른 사용자가 같은 공고에서 같은 추천가를 받지 않는다.
 - AI 예측가(모델 출력)는 사용자와 무관하게 모든 사용자에게 같은 값으로 보조 표시한다.
 - 숨은 조작이 되지 않도록 낙찰 가능 구간과 분산 사실을 화면에 공개한다.

분위표는 SQLite 인메모리 픽스처의 `win_interval_stats` 행으로 직접 만든다.
호스트 DB 에 붙지 않으며 실제 모델 추론도 호출하지 않는다.
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from src.app.api.v1 import evaluations
from src.app.api.v1.evaluations import require_current_user
from src.app.core.security import SESSION_COOKIE_NAME, create_session, make_password
from src.app.core.timeutil import utcnow
from src.app.main import app
from src.app.models.accounts import CustomUser
from src.app.models.bids import BidAnnouncement
from src.app.models.company_profiles import AccountQualificationFact
from src.app.models.prearng_prices import WinIntervalStat
from src.app.schemas.predictions import PredictPriceResponse

RECOMMEND_URL = "/api/v1/evaluations/recommend"
NOTICE_NO = "DISPERSED-UI-001"
INSTITUTION_NAME = "테스트 수요기관"
CATEGORY = "Servc"
BASE_AMOUNT = 500_000_000
LWLT_RATE = "89.995"
STUB_OPTIMAL_PRICE = 440_000_000
MEMBER_CREDIT_GRADE = "AAA ~ A-"

# 분위표는 p05 90.0% 에서 0.4%p 씩 올라 p95 97.2% 가 된다. 모두 회원 하한
# (89.995%) 금액보다 커서 두 사용자의 금액이 하한으로 붙지 않는다.
QUANTILE_RATES = tuple(Decimal("90.0") + Decimal("0.4") * index for index in range(19))
QUANTILE_COLUMNS = tuple(f"p{percentile:02d}" for percentile in range(5, 100, 5))

DISCLOSURE_PHRASE = (
    "이 추천가는 과거 낙찰 실적으로 측정한 낙찰 가능 구간 안에서 고른 지점입니다. "
    "같은 공고라도 사용자마다 다른 지점이 제시되며, 구간 안 지점들의 과거 낙찰 "
    "확률에는 유의한 차이가 없습니다."
)
AI_COMMON_PHRASE = "모든 사용자에게 같은 공통 예측값"

SCORE_OVERRIDES = {
    "quant_items": {"performance": 20.0, "labor_plan": 10.0},
    "max_price_score": 60.0,
    "multiplier": 2.0,
    "pass_threshold": 95.0,
}


@pytest.fixture
def as_user():
    """실제 인증·Redis 없이 요청 사용자만 바꾸는 대역."""

    def _set_user(user_id: int) -> None:
        app.dependency_overrides[require_current_user] = lambda: SimpleNamespace(id=user_id)

    yield _set_user
    app.dependency_overrides.pop(require_current_user, None)


@pytest.fixture(autouse=True)
def auto_stub_prediction(monkeypatch):
    """어떤 시험도 실제 모델 가중치를 로드하지 않도록 예측 API 를 대역으로 덮는다."""

    def _fake_predict(payload, request, db, user=None):
        return PredictPriceResponse(
            status="success",
            optimal_price=STUB_OPTIMAL_PRICE,
            prediction_rate=88.0,
            model_name="기본 대역 모델",
            model_id="default-model",
            requested_model=payload.selected_model or "default-model",
            fallback_used=False,
            fallback_reason=None,
            message="테스트용 예측 대역 응답",
        )

    monkeypatch.setattr(evaluations, "predict_price_api", _fake_predict)


def _create_bid(db, *, notice_no: str = NOTICE_NO) -> BidAnnouncement:
    bid = BidAnnouncement(
        bid_ntce_nm="분산 추천가 시험 공고",
        bid_ntce_no=notice_no,
        bid_ntce_ord="000",
        ntce_instt_nm="테스트 공고기관",
        dminstt_nm=INSTITUTION_NAME,
        base_amount=BASE_AMOUNT,
        presmpt_prce=BASE_AMOUNT,
        bid_ntce_dt=utcnow(),
        bid_clse_dt=utcnow(),
        openg_dt=utcnow(),
        collected_at=utcnow(),
        category=CATEGORY,
        raw_data={
            "prearngPrceDcsnMthdNm": "복수예가",
            "sucsfbidMthdNm": "시설분야용역 적격심사 추정가격 5억원 이상",
            "sucsfbidLwltRate": LWLT_RATE,
            "srvceDivNm": "일반용역",
            "totPrdprcNum": "12",
            "drwtPrdprcNum": "3",
        },
    )
    db.add(bid)
    db.commit()
    db.refresh(bid)
    return bid


def _add_member_facts(db, user_id: int) -> None:
    db.add(
        AccountQualificationFact(
            user_id=user_id,
            version="1.0",
            credit_grade=MEMBER_CREDIT_GRADE,
        )
    )
    db.commit()


def _add_win_interval_stats(db, *, institution_name: str = INSTITUTION_NAME) -> None:
    row = {
        "scope": "institution",
        "institution_name": institution_name,
        "category": CATEGORY,
        "lwlt_rate": Decimal(LWLT_RATE),
        "window_days": 365,
        "sample_count": 120,
        "rebuilt_at": utcnow(),
    }
    row.update(dict(zip(QUANTILE_COLUMNS, QUANTILE_RATES, strict=True)))
    db.add(WinIntervalStat(**row))
    db.commit()


def _recommend(client, bid, *, overrides: dict | None = None):
    body = {
        "bid_id": bid.id,
        "overrides": dict(overrides or SCORE_OVERRIDES),
    }
    return client.post(RECOMMEND_URL, json=body)


@pytest.fixture
def auth_client(isolated_db):
    """상세 페이지 SSR HTML 을 로그인 회원 컨텍스트로 보는 클라이언트."""
    user = CustomUser(
        username="dispersed_ui_tester",
        password=make_password("pw-test-1234"),
        email="dispersed_ui@example.com",
        nickname="분산 추천 검증",
        is_active=True,
        is_staff=False,
        is_superuser=False,
        date_joined=utcnow(),
    )
    isolated_db.add(user)
    isolated_db.commit()
    token = create_session(user.id, user.username)
    return TestClient(app, cookies={SESSION_COOKIE_NAME: token})


def _dispersed(payload: dict) -> dict:
    assert payload["status"] == "success", payload
    dispersed = payload.get("dispersed_bid")
    assert dispersed is not None, payload
    return dispersed


# --------------------------------------------------------------------------- #
# (a) 같은 정량점수의 서로 다른 사용자는 같은 공고에서 다른 금액을 받는다
# --------------------------------------------------------------------------- #
def test_different_users_with_same_score_get_different_amount(client, isolated_db, as_user) -> None:
    bid = _create_bid(isolated_db)
    _add_member_facts(isolated_db, 10)
    _add_member_facts(isolated_db, 20)
    _add_win_interval_stats(isolated_db)

    as_user(10)
    first = _recommend(client, bid).json()
    as_user(20)
    second = _recommend(client, bid).json()

    first_dispersed = _dispersed(first)
    second_dispersed = _dispersed(second)
    # 두 사용자의 정량점수는 같다. 금액만 사용자·공고 조합으로 달라져야 한다.
    assert first["non_price_score"] == second["non_price_score"]
    assert first["price_bounds"]["min_bid_amount"] == second["price_bounds"]["min_bid_amount"]
    assert first_dispersed["amount"] != second_dispersed["amount"]
    assert first_dispersed["quantile"] != second_dispersed["quantile"]


# --------------------------------------------------------------------------- #
# (b) 같은 사용자는 다시 요청해도 같은 금액을 받는다
# --------------------------------------------------------------------------- #
def test_same_user_gets_same_amount_on_repeat(client, isolated_db, as_user) -> None:
    bid = _create_bid(isolated_db)
    _add_member_facts(isolated_db, 10)
    _add_win_interval_stats(isolated_db)

    as_user(10)
    first = _dispersed(_recommend(client, bid).json())
    second = _dispersed(_recommend(client, bid).json())

    assert first["amount"] == second["amount"]
    assert first["quantile"] == second["quantile"]
    assert first["band_low_amount"] == second["band_low_amount"]
    assert first["band_high_amount"] == second["band_high_amount"]


# --------------------------------------------------------------------------- #
# (c) 금액은 회원 최저 통과 금액 이상이고 낙찰 가능 구간 안이다
# --------------------------------------------------------------------------- #
def test_amount_stays_above_floor_and_inside_band(client, isolated_db, as_user) -> None:
    bid = _create_bid(isolated_db)
    _add_member_facts(isolated_db, 10)
    _add_win_interval_stats(isolated_db)

    as_user(10)
    payload = _recommend(client, bid).json()
    dispersed = _dispersed(payload)
    member_bid = payload["member_bid"]

    assert member_bid["status"] in ("already_sufficient", "compensate")
    assert member_bid["bid_amount"] is not None
    assert dispersed["amount"] >= member_bid["bid_amount"]
    assert dispersed["band_low_amount"] >= member_bid["bid_amount"]
    assert dispersed["band_low_amount"] <= dispersed["amount"]
    assert dispersed["amount"] <= dispersed["band_high_amount"]
    assert dispersed["sample_count"] == 120
    assert dispersed["scope"] == "institution"


# --------------------------------------------------------------------------- #
# (d) AI 예측가(모델 출력)는 두 사용자에게 같은 값이다
# --------------------------------------------------------------------------- #
def test_ai_prediction_is_common_to_all_users(client, isolated_db, as_user) -> None:
    bid = _create_bid(isolated_db)
    _add_member_facts(isolated_db, 10)
    _add_member_facts(isolated_db, 20)
    _add_win_interval_stats(isolated_db)

    as_user(10)
    first = _recommend(client, bid).json()
    as_user(20)
    second = _recommend(client, bid).json()

    assert first["prediction"]["optimal_price"] == STUB_OPTIMAL_PRICE
    assert second["prediction"]["optimal_price"] == STUB_OPTIMAL_PRICE
    assert first["prediction"]["optimal_price"] == second["prediction"]["optimal_price"]
    # 분산 추천가는 AI 예측가를 대체하지 않고 별도 필드로만 덧붙는다.
    assert _dispersed(first)["amount"] != first["prediction"]["optimal_price"]


# --------------------------------------------------------------------------- #
# (e) 분위표가 없거나 보완 투찰가가 불가면 dispersed_bid 는 null 이다
# --------------------------------------------------------------------------- #
def test_missing_quantiles_leave_dispersed_bid_null(client, isolated_db, as_user) -> None:
    bid = _create_bid(isolated_db)
    _add_member_facts(isolated_db, 10)

    as_user(10)
    payload = _recommend(client, bid).json()

    assert payload["status"] == "success", payload
    assert payload.get("dispersed_bid") is None


def test_impossible_member_bid_leaves_dispersed_bid_null(client, isolated_db, as_user) -> None:
    bid = _create_bid(isolated_db)
    _add_member_facts(isolated_db, 10)
    _add_win_interval_stats(isolated_db)

    as_user(10)
    payload = _recommend(
        client,
        bid,
        overrides={**SCORE_OVERRIDES, "max_price_score": 50.0, "pass_threshold": 100.0},
    ).json()

    assert payload["member_bid"]["status"] == "impossible", payload["member_bid"]
    assert payload.get("dispersed_bid") is None


# --------------------------------------------------------------------------- #
# (f) 상세 페이지 HTML 에 구간·분산 공개 문구가 있다
# --------------------------------------------------------------------------- #
def test_detail_page_discloses_band_and_dispersion(auth_client, isolated_db) -> None:
    bid = _create_bid(isolated_db)

    body = auth_client.get(f"/bids/{bid.id}/").text

    assert DISCLOSURE_PHRASE in body
    assert AI_COMMON_PHRASE in body

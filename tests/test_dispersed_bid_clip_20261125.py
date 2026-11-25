"""회원 하한 클립에서 금액·투찰률·낙찰 가능 구간 정합성 시험 (2026-11-25).

정본: .orca/capsules/task_dispersed_clip_consistency_20261125/capsule.yaml

분위표의 투찰률이 회원 최저 통과 금액보다 낮아 클립이 걸리는 픽스처를 SQLite
인메모리 `win_interval_stats` 행으로 직접 만든다. 호스트 DB 에 붙지 않으며 실제
모델 추론도 호출하지 않는다.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
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
NOTICE_NO = "DISPERSED-CLIP-001"
INSTITUTION_NAME = "테스트 수요기관"
CATEGORY = "Servc"
BASE_AMOUNT = 500_000_000
LWLT_RATE = "89.995"
STUB_OPTIMAL_PRICE = 440_000_000
MEMBER_CREDIT_GRADE = "AAA ~ A-"
CLIP_NOTICE = "정량점수 기준 최저 통과 금액으로 맞췄습니다."
RATE_QUANTUM = Decimal("0.0001")

# 회원 보완 투찰률(90.5%)보다 낮아 모든 지점이 하한 클립에 걸린다.
CLIPPED_QUANTILE_RATE = Decimal("89.0")
# 회원 하한보다 높아 클립이 걸리지 않는 분위표.
UNCAPPED_QUANTILE_RATES = tuple(Decimal("92.0") + Decimal("0.3") * index for index in range(19))
QUANTILE_COLUMNS = tuple(f"p{percentile:02d}" for percentile in range(5, 100, 5))

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


@pytest.fixture
def auth_client(isolated_db):
    """상세 페이지 SSR HTML 을 로그인 회원 컨텍스트로 보는 클라이언트."""
    user = CustomUser(
        username="dispersed_clip_tester",
        password=make_password("pw-test-1234"),
        email="dispersed_clip@example.com",
        nickname="분산 클립 검증",
        is_active=True,
        is_staff=False,
        is_superuser=False,
        date_joined=utcnow(),
    )
    isolated_db.add(user)
    isolated_db.commit()
    token = create_session(user.id, user.username)
    return TestClient(app, cookies={SESSION_COOKIE_NAME: token})


def _create_bid(db) -> BidAnnouncement:
    bid = BidAnnouncement(
        bid_ntce_nm="분산 클립 정합성 시험 공고",
        bid_ntce_no=NOTICE_NO,
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


def _add_win_interval_stats(db, rates: tuple[Decimal, ...]) -> None:
    row = {
        "scope": "institution",
        "institution_name": INSTITUTION_NAME,
        "category": CATEGORY,
        "lwlt_rate": Decimal(LWLT_RATE),
        "window_days": 365,
        "sample_count": 120,
        "rebuilt_at": utcnow(),
    }
    row.update(dict(zip(QUANTILE_COLUMNS, rates, strict=True)))
    db.add(WinIntervalStat(**row))
    db.commit()


def _recommend(client, bid):
    body = {
        "bid_id": bid.id,
        "overrides": dict(SCORE_OVERRIDES),
    }
    return client.post(RECOMMEND_URL, json=body)


def _dispersed(payload: dict) -> dict:
    assert payload["status"] == "success", payload
    dispersed = payload.get("dispersed_bid")
    assert dispersed is not None, payload
    return dispersed


# --------------------------------------------------------------------------- #
# (a) 클립이 걸리면 금액은 회원 최저 통과 금액과 같다
# --------------------------------------------------------------------------- #
def test_clipped_amount_equals_member_floor(client, isolated_db, as_user) -> None:
    bid = _create_bid(isolated_db)
    _add_member_facts(isolated_db, 10)
    _add_win_interval_stats(
        isolated_db,
        tuple(CLIPPED_QUANTILE_RATE for _ in QUANTILE_COLUMNS),
    )

    as_user(10)
    payload = _recommend(client, bid).json()
    dispersed = _dispersed(payload)
    member_bid = payload["member_bid"]

    assert member_bid["bid_amount"] is not None
    assert dispersed["clipped"] is True
    assert dispersed["amount"] == member_bid["bid_amount"]


# --------------------------------------------------------------------------- #
# (b) 투찰률은 표시 금액에서 다시 계산한 값과 같다
# --------------------------------------------------------------------------- #
def test_clipped_rate_is_recomputed_from_amount(client, isolated_db, as_user) -> None:
    bid = _create_bid(isolated_db)
    _add_member_facts(isolated_db, 10)
    _add_win_interval_stats(
        isolated_db,
        tuple(CLIPPED_QUANTILE_RATE for _ in QUANTILE_COLUMNS),
    )

    as_user(10)
    dispersed = _dispersed(_recommend(client, bid).json())

    expected_rate = (Decimal(dispersed["amount"]) / Decimal(BASE_AMOUNT) * Decimal("100")).quantize(
        RATE_QUANTUM, rounding=ROUND_HALF_UP
    )
    assert Decimal(dispersed["rate_percent"]) == expected_rate


# --------------------------------------------------------------------------- #
# (c) 구간은 회원 하한 위에서 금액을 포함한다
# --------------------------------------------------------------------------- #
def test_clipped_band_contains_amount_above_floor(client, isolated_db, as_user) -> None:
    bid = _create_bid(isolated_db)
    _add_member_facts(isolated_db, 10)
    _add_win_interval_stats(
        isolated_db,
        tuple(CLIPPED_QUANTILE_RATE for _ in QUANTILE_COLUMNS),
    )

    as_user(10)
    payload = _recommend(client, bid).json()
    dispersed = _dispersed(payload)
    floor_amount = payload["member_bid"]["bid_amount"]

    assert dispersed["band_low_amount"] >= floor_amount
    assert dispersed["band_low_amount"] <= dispersed["amount"]
    assert dispersed["amount"] <= dispersed["band_high_amount"]


# --------------------------------------------------------------------------- #
# (d) 클립 안내는 클립일 때만 화면에 채워진다
# --------------------------------------------------------------------------- #
def test_detail_page_has_clipped_notice_only_when_clipped(auth_client, isolated_db) -> None:
    import re

    bid = _create_bid(isolated_db)

    body = auth_client.get(f"/bids/{bid.id}/").text

    assert CLIP_NOTICE in body
    # 안내 문단은 서버 HTML 에서 비어 있고, 클립일 때만 스크립트가 채운다.
    notice = re.search(
        r'<p id="res-member-dispersed-clip"[^>]*>(.*?)</p>',
        body,
        re.DOTALL,
    )
    assert notice is not None
    assert notice.group(1).strip() == ""
    assert "dispersed.clipped === true" in body


# --------------------------------------------------------------------------- #
# (e) 내부 호출은 회원 하한 투찰률을 퍼센트로 넘긴다
# --------------------------------------------------------------------------- #
def test_internal_call_passes_member_floor_rate_as_percent(
    client, isolated_db, as_user, monkeypatch
) -> None:
    bid = _create_bid(isolated_db)
    _add_member_facts(isolated_db, 10)
    _add_win_interval_stats(
        isolated_db,
        tuple(CLIPPED_QUANTILE_RATE for _ in QUANTILE_COLUMNS),
    )

    original = evaluations.user_dispersed_bid
    recorded: list[dict] = []

    def _recording(*args, **kwargs):
        recorded.append(dict(kwargs))
        return original(*args, **kwargs)

    monkeypatch.setattr(evaluations, "user_dispersed_bid", _recording)
    as_user(10)
    payload = _recommend(client, bid).json()
    member_bid = payload["member_bid"]

    assert len(recorded) == 1
    passed_floor_rate = Decimal(str(recorded[0]["member_floor_rate"]))
    # 비율(0.87745...)이 아니라 퍼센트(87.745...)로 넘겨야 내부 하한이 실제
    # 금액이 됩니다. 비율로 넘기면 하한이 1/100 로 줄어 클립이 걸리지 않습니다.
    assert passed_floor_rate == Decimal(str(member_bid["bid_rate_percent"]))
    assert passed_floor_rate > Decimal("1")


# --------------------------------------------------------------------------- #
# (f) 내부 반환도 회원 하한에서 클립으로 판정된다
# --------------------------------------------------------------------------- #
def test_internal_result_is_clipped_by_member_floor(
    client, isolated_db, as_user, monkeypatch
) -> None:
    bid = _create_bid(isolated_db)
    _add_member_facts(isolated_db, 10)
    # 분위표 투찰률이 모두 회원 하한보다 낮아 내부 하한 클립이 반드시 걸린다.
    _add_win_interval_stats(
        isolated_db,
        tuple(CLIPPED_QUANTILE_RATE for _ in QUANTILE_COLUMNS),
    )

    original = evaluations.user_dispersed_bid
    results: list = []

    def _recording(*args, **kwargs):
        result = original(*args, **kwargs)
        results.append(result)
        return result

    monkeypatch.setattr(evaluations, "user_dispersed_bid", _recording)
    as_user(10)
    payload = _recommend(client, bid).json()
    member_amount = int(payload["member_bid"]["bid_amount"])

    assert len(results) == 1
    internal = results[0]
    assert internal.clipped is True
    assert internal.amount >= member_amount
    assert payload["dispersed_bid"]["clipped"] is True

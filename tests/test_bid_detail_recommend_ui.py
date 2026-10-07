"""입찰 상세 투찰가 추천 UI 시험.

정본: .orca/capsules/task_k6_detail_recommend_ui/capsule.yaml,
docs/design/web_feedback_redesign_20261006.md 5.1~5.4.
 - 분석 실행 영역, 내 투찰 금액 입력, 결격사유 체크박스, 진입 시 1원 /analyze 호출이 제거된다.
 - 진입 시와 입력 변경 시 /api/v1/evaluations/recommend 를 자동 호출한다(400ms 디바운스).
 - 최저가·AI 예측가·최상가와 근거 문장, 회원 원자료 없음/차단 안내를 보여 준다.

렌더 HTML 은 로그인한 회원 컨텍스트로 확인하고, 추천 계산 끝단은 mock 없이 TestClient 로
호출한다. 규칙 판별·정량 환산·통과 구간 역산은 실제 코드이며, 이 워크트리에 예측 모델
파일이 없어 predict_price_api 만 시험 대역으로 대체한다.
"""

from __future__ import annotations

from datetime import timedelta
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
from src.app.models.prearng_prices import BidPrearngPrice
from src.app.schemas.predictions import PredictPriceResponse
from src.app.services.sajeong_rate_stats import rebuild_institution_sajeong_rate_stats

RECOMMEND_URL = "/api/v1/evaluations/recommend"
PPS_METHOD = "시설분야용역 적격심사 추정가격 5억원 미만"
PRESMPT_PRCE = 400_000_000


@pytest.fixture
def as_user():
    def _set_user(user_id: int) -> None:
        app.dependency_overrides[require_current_user] = lambda: SimpleNamespace(id=user_id)

    yield _set_user
    app.dependency_overrides.pop(require_current_user, None)


@pytest.fixture(autouse=True)
def stub_prediction(monkeypatch):
    """예측 모델 파일이 없는 워크트리라 모델 산출물만 대역으로 대체한다."""

    def _fake_predict(payload, request, db, user=None):
        return PredictPriceResponse(
            status="success",
            optimal_price=440_000_000,
            prediction_rate=88.0,
            model_name="기본 대역 모델",
            model_id=payload.selected_model or "default-model",
            requested_model=payload.selected_model or "default-model",
            fallback_used=False,
            fallback_reason=None,
            message="테스트용 예측 대역 응답",
        )

    monkeypatch.setattr(evaluations, "predict_price_api", _fake_predict)


@pytest.fixture
def auth_client(isolated_db):
    user = CustomUser(
        username="recommend_ui_tester",
        password=make_password("pw-test-1234"),
        email="recommend_ui@example.com",
        nickname="추천 UI 검증",
        is_active=True,
        is_staff=False,
        is_superuser=False,
        date_joined=utcnow(),
    )
    isolated_db.add(user)
    isolated_db.commit()
    token = create_session(user.id, user.username)
    return TestClient(app, cookies={SESSION_COOKIE_NAME: token})


def _create_render_bid(db) -> BidAnnouncement:
    bid = BidAnnouncement(
        bid_ntce_no="EVAL-RECOMMEND-RENDER-001",
        bid_ntce_ord="000",
        bid_ntce_nm="추천 UI 렌더 시험 공고",
        dminstt_nm="검증기관",
        category="Servc",
        presmpt_prce=100_000_000,
        base_amount=100_000_000,
        bid_ntce_dt=utcnow(),
        bid_clse_dt=utcnow() + timedelta(days=7),
        collected_at=utcnow(),
        raw_data={"indstrytyLmtYn": "N"},
    )
    db.add(bid)
    db.commit()
    db.refresh(bid)
    return bid


def _create_pps_bid(db) -> BidAnnouncement:
    bid = BidAnnouncement(
        bid_ntce_nm="투찰가 추천 끝단 시험 공고",
        bid_ntce_no="EVAL-RECOMMEND-PPS-001",
        bid_ntce_ord="000",
        ntce_instt_nm="테스트 공고기관",
        dminstt_nm="테스트 수요기관",
        base_amount=PRESMPT_PRCE,
        presmpt_prce=PRESMPT_PRCE,
        bid_ntce_dt=utcnow(),
        bid_clse_dt=utcnow(),
        openg_dt=utcnow(),
        category="Servc",
        raw_data={
            "prearngPrceDcsnMthdNm": "복수예가",
            "sucsfbidMthdNm": PPS_METHOD,
            "sucsfbidLwltRate": "89.995",
            "srvceDivNm": "일반용역",
            "totPrdprcNum": "12",
            "drwtPrdprcNum": "3",
        },
    )
    db.add(bid)
    db.commit()
    db.refresh(bid)
    return bid


# --------------------------------------------------------------------------- #
# 1. 렌더 시험: 제거된 요소와 새 계산 영역
# --------------------------------------------------------------------------- #


def test_detail_removes_manual_execution_controls(auth_client, isolated_db):
    """분석 실행·내 투찰 금액·결격 체크박스·/analyze 전용 결과가 사라졌다."""
    bid = _create_render_bid(isolated_db)
    body = auth_client.get(f"/bids/{bid.id}/").text

    for removed in (
        'id="user-price"',
        'id="btn-predict"',
        'id="btn-evaluate"',
        'id="input-disqualification"',
        'id="scenario-results"',
        'id="price-compensation"',
        'id="res-interval"',
        'id="res-similarity"',
    ):
        assert removed not in body, f"제거됐어야 할 요소가 남아 있음: {removed}"
    assert "분석 실행" not in body
    assert "내 투찰 금액" not in body
    assert "candidate_bid_amount" not in body


def test_detail_calls_recommend_automatically(auth_client, isolated_db):
    """진입 시와 입력 변경 시 /recommend 를 400ms 디바운스로 자동 호출한다."""
    bid = _create_render_bid(isolated_db)
    body = auth_client.get(f"/bids/{bid.id}/").text

    assert "/evaluations/recommend" in body
    assert "requestRecommend();" in body
    assert "scheduleRecommend" in body
    assert "setTimeout(requestRecommend, 400)" in body
    assert "$('#evaluation-card').on('input change', 'input, select', scheduleRecommend);" in body


def test_detail_shows_three_amounts_and_labels(auth_client, isolated_db):
    """최저가·AI 예측가·최상가를 서버 응답 값으로 표시한다."""
    bid = _create_render_bid(isolated_db)
    body = auth_client.get(f"/bids/{bid.id}/").text

    assert "최저가" in body
    assert "AI 예측가" in body
    assert "최상가" in body
    assert 'id="res-min-price"' in body
    assert 'id="res-optimal-price"' in body
    assert 'id="res-max-price"' in body
    assert "data.price_bounds" in body
    assert "bounds.min_bid_amount" in body
    assert "bounds.max_bid_amount" in body
    assert "prediction.optimal_price" in body
    assert 'id="price-help-modal"' in body
    assert 'data-price-help="min"' in body
    assert 'data-price-help="optimal"' in body
    assert 'data-price-help="max"' in body
    assert "function openPriceHelp" in body
    assert "사정률 하한에 맞춰 계산한 투찰금액입니다." in body
    assert "선택한 예측 모델이 이 공고에 대해 산출한 투찰금액입니다." in body
    assert "사정률 상한에 맞춰 계산한 투찰금액입니다." in body


def test_detail_reason_sentence_templates(auth_client, isolated_db):
    """근거 문장 템플릿과 세 금액 명칭이 화면 스크립트에 있다."""
    bid = _create_render_bid(isolated_db)
    body = auth_client.get(f"/bids/{bid.id}/").text

    for template in (
        "발주처의 기존 낙찰 데이터",
        "건 분석 시 평균",
        "낙찰률을 보이며",
        "로 예측했습니다",
        "표본이 부족해 시·도 평균으로 대체했습니다",
        "해당 공고는 가격점수",
        "낙찰 통과점수",
        "귀사의 정량평가 점수는",
        "이상이어야 합니다",
        "사정률 하한(",
        "최저 투찰금액입니다",
        "사정률 상한(",
        "최고 투찰금액입니다",
        "과거 참가업체 수 평균",
        "결격사유는 확인하지 않은 계산입니다",
    ):
        assert template in body, f"근거 문장 템플릿 누락: {template}"

    # 기존 '추천 최적 투찰가' 단일 표기는 세 금액 표기로 대체됐다.
    assert "추천 최적 투찰가" not in body


def test_detail_member_and_blocked_guidance(auth_client, isolated_db):
    """회원 원자료 없음 안내와 링크, 차단 안내, 이론 사정률 고지를 보여 준다."""
    bid = _create_render_bid(isolated_db)
    body = auth_client.get(f"/bids/{bid.id}/").text

    assert 'id="recommend-member-missing"' in body
    assert "회원 정량 원자료가 없어 AI 예측가만 표시합니다." in body
    assert "회원정보에서 정량 항목" in body
    assert 'id="recommend-profile-link"' in body
    assert 'id="recommend-blocked"' in body
    assert 'id="recommend-blocked-reason"' in body

    assert "data.rate_notice" in body
    assert "data.rate_source === 'measured'" in body
    assert "reputation_grade_required" in body
    assert "applied_reputation_items" in body
    assert "회원가입 때 저장한 신인도를 이 공고에 적용했습니다." in body
    assert "경영상태와 신인도는 회원가입 때 저장한 원자료를 그대로 씁니다." in body


def test_detail_shows_performance_basis(auth_client, isolated_db):
    """수행실적 입력란 아래에 그 공고 규칙의 수행실적 산정 기준을 둔다."""
    bid = _create_render_bid(isolated_db)
    body = auth_client.get(f"/bids/{bid.id}/").text

    assert 'id="performance-basis"' in body
    assert "수행실적 산정 기준" in body
    assert "renderPerformanceBasis" in body


# --------------------------------------------------------------------------- #
# 2. 추천 API 끝단 (규칙 판별·정량 환산은 실제 코드, 모델 산출물만 대역)
# --------------------------------------------------------------------------- #


def test_recommend_returns_three_amounts(client, isolated_db, as_user):
    """회원 정량 원자료가 자동 기입되면 최저가·AI 예측가·최상가를 계산한다."""
    as_user(10)
    isolated_db.add(AccountQualificationFact(user_id=10, credit_grade="BBB+"))
    isolated_db.commit()
    bid = _create_pps_bid(isolated_db)

    response = client.post(RECOMMEND_URL, json={"bid_id": bid.id, "overrides": {}})
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["blocked"] is False, body.get("blocked_reason")
    assert body["price_bounds"]["status"] == "ok"
    assert body["price_bounds"]["min_bid_amount"] is not None
    assert body["price_bounds"]["max_bid_amount"] is not None
    assert body["prediction"]["optimal_price"] == 440_000_000
    assert body["rate_source"] == "theoretical"
    assert body["rate_notice"]
    assert body["disqualification_status"] == "not_checked"
    assert float(body["non_price_score"]) > 0
    management = next(item for item in body["non_price_items"] if item["item_key"] == "management")
    assert float(management["score"]) > 0


def test_recommend_reports_unresolved_bounds_without_member_data(client, isolated_db, as_user):
    """회원 원자료가 없어 정량점수가 0이면 통과 구간을 확정하지 못하고 사유를 돌려준다."""
    as_user(10)
    bid = _create_pps_bid(isolated_db)

    body = client.post(RECOMMEND_URL, json={"bid_id": bid.id}).json()

    assert body["blocked"] is True
    assert "PRICE_BOUNDS_UNRESOLVED" in body["blocked_reason"]
    assert body["prediction"]["optimal_price"] == 440_000_000


def _seed_institution_sajeong_stats(db, institution_name: str, category: str = "Servc") -> None:
    """발주처 사정률 실측 표본 30건을 심고 기관 분포를 재집계한다(격리 시험 DB 전용)."""
    for index in range(30):
        rate = Decimal("89.0") + Decimal(index) / Decimal("10")
        db.add(
            BidPrearngPrice(
                bid_ntce_no=f"R25BK9{index:05d}",
                bid_ntce_ord="000",
                bid_clsfc_no="0",
                rbid_no="000",
                category=category,
                dminstt_nm=institution_name,
                bssamt=1000,
                plnprc=int(rate * 10),
                sajeong_rate=rate,
                rl_openg_dt=utcnow(),
            )
        )
    db.commit()
    rebuild_institution_sajeong_rate_stats(db)


def test_recommend_uses_measured_sajeong_range(client, isolated_db, as_user):
    """발주처 실측 표본이 있으면 최솟값·최댓값을 예정가격 배수로 삼아 최저가·최상가를 낸다."""
    as_user(10)
    isolated_db.add(AccountQualificationFact(user_id=10, credit_grade="BBB+"))
    isolated_db.commit()
    bid = _create_pps_bid(isolated_db)
    _seed_institution_sajeong_stats(isolated_db, "테스트 수요기관")

    body = client.post(RECOMMEND_URL, json={"bid_id": bid.id, "overrides": {}}).json()

    assert body["blocked"] is False, body.get("blocked_reason")
    assert body["rate_source"] == "measured"
    assert "발주처" in body["rate_notice"]
    assert "표본 30건" in body["rate_notice"]
    assert float(body["price_bounds"]["rate_low_percent"]) == 89.0
    assert float(body["price_bounds"]["rate_high_percent"]) == 91.9
    assert body["price_bounds"]["min_bid_amount"] is not None
    assert body["price_bounds"]["max_bid_amount"] is not None

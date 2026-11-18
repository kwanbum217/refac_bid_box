"""내 조건 추천가 오차 범위와 분석기 배치 계약 시험 (2026-11-18).

정본: .orca/capsules/task_detail_recommend_ux_20261118/capsule.yaml

시험 항목:
 (a) 범위 폭 = 기준 금액 x 실측 오차 / 100, 최저가~최상가 자르기, None 전파
 (b) 추천 API 응답에 member_recommended_low/high/error_pp 세 필드가 실린다
 (c) detail.html 분석기 블록이 정량평가 입력표 뒤에 있고, 평점계수(k) 표기가 없고,
     페이지 로드에 자동 분석 호출이 묶여 있지 않다
"""
# ruff: noqa: F811 - 가져온 픽스처 이름을 시험 인자로 받는다

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from src.app.api.v1 import evaluations
from src.app.schemas.predictions import PredictPriceResponse
from src.app.services.evaluation_recommendation import (
    MemberRecommendationBand,
    member_recommended_band,
)
from tests.test_evaluation_recommend import (  # noqa: F401 - 픽스처는 모듈 이름 그대로 등록돼야 한다
    MEMBER_CREDIT_GRADE,
    _add_member_facts,
    _create_bid,
    _recommend,
    _registry_overrides,
    as_user,
    auto_stub_prediction,
)

TEMPLATE_PATH = Path(__file__).resolve().parents[1] / "src/app/templates/bids/detail.html"
RECOMMEND_URL = "/api/v1/evaluations/recommend"


# --------------------------------------------------------------------------- #
# (a) 범위 산식 단위 시험
# --------------------------------------------------------------------------- #


def test_band_width_uses_reference_amount_and_error() -> None:
    """폭은 기준 금액 x 오차 / 100 이며 추천가 양쪽에 붙는다."""
    band = member_recommended_band(
        member_price=100_000_000,
        reference_amount=Decimal("500000000"),
        error_pp=Decimal("2.70"),
    )

    assert band == MemberRecommendationBand(
        low=86_500_000,
        high=113_500_000,
        error_pp=Decimal("2.70"),
    )


def test_band_rounds_width_to_won() -> None:
    """폭은 원 단위로 반올림한다(내림·올림 아님)."""
    band = member_recommended_band(
        member_price=1_000,
        reference_amount=Decimal("100"),
        error_pp=Decimal("2.705"),
    )

    assert band is not None
    assert band.low == 997
    assert band.high == 1_003


def test_band_is_clamped_to_member_price_bounds() -> None:
    """범위는 최저가~최상가 밖으로 나가지 않는다."""
    band = member_recommended_band(
        member_price=50,
        reference_amount=Decimal("1000"),
        error_pp=Decimal("10"),
        min_bid_amount=10,
        max_bid_amount=120,
    )

    assert band == MemberRecommendationBand(low=10, high=120, error_pp=Decimal("10"))


@pytest.mark.parametrize(
    ("member_price", "reference_amount", "error_pp"),
    [
        (None, 100, 2.7),
        (50, None, 2.7),
        (50, 100, None),
        (50, 0, 2.7),
        (50, -100, 2.7),
        (50, 100, -0.1),
    ],
)
def test_band_returns_none_without_valid_inputs(
    member_price: int | None,
    reference_amount: int | None,
    error_pp: float | None,
) -> None:
    """추천가·기준 금액·오차 중 하나라도 없거나 유효하지 않으면 범위를 만들지 않는다."""
    assert (
        member_recommended_band(
            member_price=member_price,
            reference_amount=reference_amount,
            error_pp=error_pp,
        )
        is None
    )


# --------------------------------------------------------------------------- #
# (b) 추천 API 응답 필드
# --------------------------------------------------------------------------- #


def _stub_price(monkeypatch, price: int) -> None:
    def _fake_predict(payload, request, db, user=None):
        return PredictPriceResponse(
            status="success",
            optimal_price=price,
            prediction_rate=88.0,
            model_name="대역 모델",
            model_id="stub-model",
            requested_model=payload.selected_model or "stub-model",
            fallback_used=False,
            fallback_reason=None,
            message="시험용 예측 대역 응답",
        )

    monkeypatch.setattr(evaluations, "predict_price_api", _fake_predict)


def _stub_accuracy(monkeypatch, display: str | None) -> None:
    monkeypatch.setattr(
        evaluations,
        "load_serving_accuracy",
        lambda: {
            "available": display is not None,
            "rmse_display": display,
            "promoted_date": "2026-11-01" if display is not None else None,
        },
    )


def test_recommend_response_includes_error_band(client, isolated_db, as_user, monkeypatch):
    """성공 응답에 범위 하한·상한과 실측 오차가 실린다."""
    as_user(10)
    _add_member_facts(isolated_db, 10, credit_grade=MEMBER_CREDIT_GRADE)
    bid = _create_bid(isolated_db, notice_no="BAND-API-001")
    base = _recommend(client, bid, overrides=_registry_overrides()).json()
    assert base["status"] == "success", base
    bounds = base["price_bounds"]
    inside = (bounds["min_bid_amount"] + bounds["max_bid_amount"]) // 2
    _stub_price(monkeypatch, inside)
    _stub_accuracy(monkeypatch, "2.70")

    payload = _recommend(client, bid, overrides=_registry_overrides()).json()

    assert payload["member_recommended_price"] == inside
    assert payload["member_recommended_low"] == inside - 13_500_000
    assert payload["member_recommended_high"] == inside + 13_500_000
    assert payload["member_recommended_error_pp"] == pytest.approx(2.70)
    assert bounds["min_bid_amount"] <= payload["member_recommended_low"]
    assert payload["member_recommended_high"] <= bounds["max_bid_amount"]


def test_recommend_response_leaves_band_empty_without_accuracy(
    client, isolated_db, as_user, monkeypatch
):
    """실측 오차를 읽지 못하면 범위는 비고 기존 단일 금액은 그대로 남는다."""
    as_user(10)
    _add_member_facts(isolated_db, 10, credit_grade=MEMBER_CREDIT_GRADE)
    bid = _create_bid(isolated_db, notice_no="BAND-API-002")
    _stub_accuracy(monkeypatch, None)

    payload = _recommend(client, bid, overrides=_registry_overrides()).json()

    assert payload["member_recommended_price"] is not None
    assert payload["member_recommended_low"] is None
    assert payload["member_recommended_high"] is None
    assert payload["member_recommended_error_pp"] is None


def test_preload_request_skips_prediction_and_band(client, isolated_db, as_user, monkeypatch):
    """입력표 사전 요청(with_prediction=false)은 AI 예측가와 범위를 계산하지 않는다."""
    as_user(10)
    _add_member_facts(isolated_db, 10, credit_grade=MEMBER_CREDIT_GRADE)
    bid = _create_bid(isolated_db, notice_no="BAND-API-003")
    called = {"value": False}

    def _must_not_predict(*args, **kwargs):
        called["value"] = True
        raise AssertionError("사전 요청에서 AI 예측가를 조회했습니다")

    monkeypatch.setattr(evaluations, "predict_price_api", _must_not_predict)
    response = client.post(
        RECOMMEND_URL,
        json={
            "bid_id": bid.id,
            "with_prediction": False,
            "overrides": _registry_overrides(),
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert called["value"] is False
    assert payload["prediction"] is None
    assert payload["member_recommended_price"] is None
    assert payload["member_recommended_low"] is None
    assert payload["member_recommended_high"] is None
    assert payload["member_recommended_error_pp"] is None
    assert payload["quant_score_table"] is not None


# --------------------------------------------------------------------------- #
# (c) 템플릿 배치·표기·실행 트리거
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def template_source() -> str:
    return TEMPLATE_PATH.read_text(encoding="utf-8")


def test_analyzer_sits_after_quant_input_table(template_source: str) -> None:
    """분석기 카드와 결과는 정량평가 입력표·재계산 버튼 뒤에 온다."""
    qualification = template_source.index('id="qualification-section"')
    recalculate = template_source.index('id="btn-recalculate"')
    intro = template_source.index('id="recommend-intro"')
    result = template_source.index('id="prediction-result"')
    sidebar = template_source.index("Right Column: Sidebar")

    assert qualification < recalculate < intro < result < sidebar
    assert "AI 투찰 금액 분석기" in template_source


def test_score_table_card_hides_multiplier(template_source: str) -> None:
    """규칙 선언 배점표 카드에서 평점계수(k)를 빼고 쉬운 문장으로 설명한다."""
    assert 'id="score-table-k"' not in template_source
    assert "총점" in template_source
    assert "점 이상이면 적격 통과입니다" in template_source
    assert "이 중 가격 점수는" in template_source
    assert "점 만점입니다" in template_source
    assert 'id="score-table-required"' in template_source
    assert "내 비가격 점수 " in template_source
    assert "점이라 가격 점수 " in template_source
    assert "점 이상이 필요합니다." in template_source
    # 수기 입력 경로의 평점 계수 입력란은 그대로 둔다.
    assert 'id="input-multiplier"' in template_source
    assert "평점 계수 (k)" in template_source


def test_member_band_is_highlighted_and_rendered(template_source: str) -> None:
    """내 조건 추천가는 강조 카드와 범위 문구로 보여 준다."""
    member_start = template_source.index('id="res-member-recommendation"')
    member_markup = template_source[member_start : member_start + 1800]
    assert "badge-amber" in member_markup
    assert "border-2" in member_markup
    assert "border-amber-300" in member_markup
    assert "text-2xl" in member_markup
    assert "dark:border-amber-600" in member_markup
    assert "모델 실측 오차 ±" in member_markup
    assert 'id="res-member-error"' in member_markup
    assert 'id="res-member-band-note"' in member_markup
    assert "AI 예측가는 공고 기준 시장 예측이라 정량점수와 무관합니다." in template_source

    render = template_source.split("function renderMemberRecommendation", 1)[1].split(
        "function boundReasonText", 1
    )[0]
    assert "data.member_recommended_low" in render
    assert "data.member_recommended_high" in render
    assert "data.member_recommended_error_pp" in render
    assert "모델 실측 오차 ±" in render
    assert "중심 " in render


def test_price_range_chart_draws_member_band(template_source: str) -> None:
    """그래프 표식은 내 조건 추천가를 점이 아니라 하한~상한 띠로 그린다."""
    render = template_source.split("function renderPriceRangeChart", 1)[1].split(
        "function hasMemberQuantData", 1
    )[0]
    assert "positions.memberLow" in render
    assert "positions.memberHigh" in render
    assert "member_recommended_low" in render
    assert "member_recommended_high" in render
    assert "내 조건 추천가 범위" in render


def test_page_load_does_not_run_analysis(template_source: str) -> None:
    """페이지 로드와 입력 변경은 분석을 실행하지 않는다. 분석은 버튼 클릭뿐이다."""
    assert "scheduleRecommend" not in template_source
    assert "recommendPending" not in template_source
    assert "setTimeout(requestRecommend" not in template_source
    assert "loadEvaluationForm();" in template_source
    assert "buildRecommendPayload(false)" in template_source
    assert "buildRecommendPayload(true)" in template_source
    assert (
        "$('#evaluation-card').on('input change', 'input, select', markRecommendStale);"
        in template_source
    )
    assert (
        "입력값이 바뀌었습니다. [점수 반영해 다시 계산]을 눌러 결과를 갱신하십시오."
        in template_source
    )

    button_handler = template_source.split("$('#btn-recalculate').on('click'", 1)[1].split(
        "});", 1
    )[0]
    assert "requestRecommend()" in button_handler
    boot = template_source.split("if (predictionSupported) {", 1)[1].split("}", 1)[0]
    assert "requestRecommend" not in boot
    assert "loadEvaluationForm()" in boot


def test_intro_replaces_result_before_button(template_source: str) -> None:
    """버튼을 누르기 전에는 분석기 자리에 안내 문장만 둔다."""
    assert (
        "정량평가 점수를 입력하고 [점수 반영해 다시 계산]을 누르면 투찰 금액 분석이 나옵니다."
        in template_source
    )
    assert 'id="recommend-intro"' in template_source
    result_markup = template_source.split('id="prediction-result"', 1)[1].split("</div>", 1)[0]
    assert "hidden" in result_markup

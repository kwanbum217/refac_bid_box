"""내 조건 추천 구간을 주 표시로 두는 계약 시험 (2026-11-25).

정본: .orca/capsules/task_member_range_primary_20261125/capsule.yaml

시험 항목:
 (a) 오차 범위가 정량점수 통과 구간(최저가·최상가)에 잘렸는지 clipped_low/clipped_high 로 표시
 (b) 추천 API 응답에 member_range_clipped_by_score 가 실리고 basis·잘림에서 값을 만든다
 (c) detail.html 에서 AI 예측가는 그리드 밖 보조 줄로 내려가고 기존 id·도움말이 유지되며,
     내 조건 추천 구간 제목과 True 일 때만 덧붙는 문장이 있다
"""
# ruff: noqa: F811 - 가져온 픽스처 이름을 시험 인자로 받는다

from __future__ import annotations

import json
import shutil
import subprocess
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
CLIPPED_SENTENCE = (
    "정량점수 기준 통과 구간이 추천 구간을 잘랐습니다. 점수가 바뀌면 이 구간도 바뀝니다."
)


# --------------------------------------------------------------------------- #
# (a) 범위 잘림 표시 단위 시험
# --------------------------------------------------------------------------- #


def test_band_marks_both_edges_clipped() -> None:
    """통과 구간이 오차 범위 양쪽을 자르면 두 표시가 모두 True 다."""
    band = member_recommended_band(
        member_price=50,
        reference_amount=Decimal("1000"),
        error_pp=Decimal("10"),
        min_bid_amount=10,
        max_bid_amount=120,
    )

    assert band is not None
    assert (band.low, band.high) == (10, 120)
    assert band.clipped_low is True
    assert band.clipped_high is True


def test_band_marks_single_clipped_edge() -> None:
    """한쪽만 잘려도 그쪽 표시만 True 다."""
    low_only = member_recommended_band(
        member_price=1000,
        reference_amount=Decimal("10000"),
        error_pp=Decimal("1"),
        min_bid_amount=950,
        max_bid_amount=5000,
    )
    high_only = member_recommended_band(
        member_price=1000,
        reference_amount=Decimal("10000"),
        error_pp=Decimal("1"),
        min_bid_amount=10,
        max_bid_amount=1050,
    )

    assert low_only is not None
    assert high_only is not None
    assert (low_only.clipped_low, low_only.clipped_high) == (True, False)
    assert (high_only.clipped_low, high_only.clipped_high) == (False, True)


def test_band_inside_bounds_is_not_clipped() -> None:
    """범위가 통과 구간 안에 온전히 들어가면 잘림 표시가 모두 False 다."""
    band = member_recommended_band(
        member_price=1000,
        reference_amount=Decimal("10000"),
        error_pp=Decimal("1"),
        min_bid_amount=10,
        max_bid_amount=5000,
    )

    assert band is not None
    assert (band.low, band.high) == (900, 1100)
    assert (band.clipped_low, band.clipped_high) == (False, False)


def test_band_touching_bounds_is_not_clipped() -> None:
    """범위 끝이 통과 구간 경계와 정확히 같으면 자르지 않은 것으로 본다."""
    band = member_recommended_band(
        member_price=1000,
        reference_amount=Decimal("10000"),
        error_pp=Decimal("1"),
        min_bid_amount=900,
        max_bid_amount=1100,
    )

    assert band is not None
    assert (band.low, band.high) == (900, 1100)
    assert (band.clipped_low, band.clipped_high) == (False, False)


def test_band_defaults_keep_flags_false() -> None:
    """기존 위치 인자 호출은 잘림 표시 기본값 False 로 그대로 동작한다."""
    band = MemberRecommendationBand(low=1, high=2, error_pp=Decimal("0"))

    assert (band.clipped_low, band.clipped_high) == (False, False)


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


def _base_payload(client, bid):
    base = _recommend(client, bid, overrides=_registry_overrides()).json()
    assert base["status"] == "success", base
    return base


def test_response_false_when_score_does_not_cut_band(client, isolated_db, as_user, monkeypatch):
    """범위가 통과 구간 안에 들어가면 점수가 잘랐다고 표시하지 않는다."""
    as_user(10)
    _add_member_facts(isolated_db, 10, credit_grade=MEMBER_CREDIT_GRADE)
    bid = _create_bid(isolated_db, notice_no="RANGE-API-001")
    bounds = _base_payload(client, bid)["price_bounds"]
    inside = (bounds["min_bid_amount"] + bounds["max_bid_amount"]) // 2
    _stub_price(monkeypatch, inside)
    _stub_accuracy(monkeypatch, "2.70")

    payload = _recommend(client, bid, overrides=_registry_overrides()).json()

    assert payload["member_recommendation_basis"] == "ai"
    assert payload["member_range_clipped_by_score"] is False


def test_response_true_when_band_is_cut_by_score(client, isolated_db, as_user, monkeypatch):
    """AI 예측가가 그대로여도 통과 구간이 범위를 자르면 True 다."""
    as_user(10)
    _add_member_facts(isolated_db, 10, credit_grade=MEMBER_CREDIT_GRADE)
    bid = _create_bid(isolated_db, notice_no="RANGE-API-002")
    bounds = _base_payload(client, bid)["price_bounds"]
    _stub_price(monkeypatch, bounds["min_bid_amount"])
    _stub_accuracy(monkeypatch, "2.70")

    payload = _recommend(client, bid, overrides=_registry_overrides()).json()

    assert payload["member_recommendation_basis"] == "ai"
    assert payload["member_recommended_low"] == bounds["min_bid_amount"]
    assert payload["member_range_clipped_by_score"] is True


def test_response_true_when_ai_price_is_raised(client, isolated_db, as_user, monkeypatch):
    """최저가로 올린 경우도 점수가 구간을 정했으므로 True 다."""
    as_user(10)
    _add_member_facts(isolated_db, 10, credit_grade=MEMBER_CREDIT_GRADE)
    bid = _create_bid(isolated_db, notice_no="RANGE-API-003")
    bounds = _base_payload(client, bid)["price_bounds"]
    _stub_price(monkeypatch, bounds["min_bid_amount"] - 1)
    _stub_accuracy(monkeypatch, "2.70")

    payload = _recommend(client, bid, overrides=_registry_overrides()).json()

    assert payload["member_recommendation_basis"] == "raised_to_min"
    assert payload["member_range_clipped_by_score"] is True


def test_response_none_without_band(client, isolated_db, as_user, monkeypatch):
    """실측 오차를 읽지 못해 범위가 없으면 잘림 여부도 비운다."""
    as_user(10)
    _add_member_facts(isolated_db, 10, credit_grade=MEMBER_CREDIT_GRADE)
    bid = _create_bid(isolated_db, notice_no="RANGE-API-004")
    _stub_accuracy(monkeypatch, None)

    payload = _recommend(client, bid, overrides=_registry_overrides()).json()

    assert payload["member_recommended_price"] is not None
    assert payload["member_recommended_low"] is None
    assert payload["member_range_clipped_by_score"] is None


def test_preload_response_has_no_clip_flag(client, isolated_db, as_user):
    """입력표 사전 요청은 예측가·범위·잘림 표시를 모두 비운다."""
    as_user(10)
    _add_member_facts(isolated_db, 10, credit_grade=MEMBER_CREDIT_GRADE)
    bid = _create_bid(isolated_db, notice_no="RANGE-API-005")

    response = client.post(
        "/api/v1/evaluations/recommend",
        json={
            "bid_id": bid.id,
            "with_prediction": False,
            "overrides": _registry_overrides(),
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["member_range_clipped_by_score"] is None


# --------------------------------------------------------------------------- #
# (c) 화면 배치·문구
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def template_source() -> str:
    return TEMPLATE_PATH.read_text(encoding="utf-8")


def test_ai_price_sits_outside_grid_with_ids_kept(template_source: str) -> None:
    """AI 예측가는 그리드 밖 보조 줄로 내려가고 기존 id·도움말은 그대로다."""
    grid_markup = template_source.split('class="price-result-grid"', 1)[1].split(
        'id="res-optimal-price-cell"', 1
    )[0]
    assert 'id="res-min-price-cell"' in grid_markup
    assert 'id="res-max-price-cell"' in grid_markup
    assert 'id="res-optimal-price"' not in grid_markup
    assert 'id="res-prediction-rate"' not in grid_markup

    secondary = template_source.split('id="res-optimal-price-cell"', 1)[1].split("</button>", 1)[0]
    assert 'data-price-help="optimal"' in secondary
    assert 'id="res-optimal-price"' in secondary
    assert 'id="res-prediction-rate"' in secondary
    assert "참고: AI 예측가" in secondary
    assert "예상 낙찰률" in secondary
    assert "공고 기준 시장 예측" in secondary


def test_grid_has_two_columns(template_source: str) -> None:
    """최저가·최상가 두 칸만 남으므로 그리드도 두 열로 바뀐다."""
    style = template_source.split("</style>", 1)[0]
    assert "repeat(2, minmax(0, 1fr))" in style
    assert "repeat(3, minmax(0, 1fr))" not in style


def test_member_block_is_titled_as_range(template_source: str) -> None:
    """내 조건 블록 제목은 추천가가 아니라 추천 구간이다."""
    start = template_source.index('id="res-member-recommendation"')
    markup = template_source[start : start + 1200]
    assert "내 조건 추천 구간" in markup
    assert "내 조건 추천가" not in markup


CASES = {
    "clipped": {
        "member_recommendation_basis": "ai",
        "member_range_clipped_by_score": True,
        "non_price_score": "30",
        "prediction": {"optimal_price": 1000},
    },
    "not_clipped": {
        "member_recommendation_basis": "ai",
        "member_range_clipped_by_score": False,
        "non_price_score": "30",
        "prediction": {"optimal_price": 1000},
    },
    "absent": {
        "member_recommendation_basis": "ai",
        "member_range_clipped_by_score": None,
        "non_price_score": "30",
        "prediction": {"optimal_price": 1000},
    },
    "raised_clipped": {
        "member_recommendation_basis": "raised_to_min",
        "member_range_clipped_by_score": True,
        "non_price_score": "25",
        "prediction": {"optimal_price": 900},
    },
}


@pytest.fixture(scope="module")
def reason_texts() -> dict[str, str]:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node 를 사용할 수 없습니다")
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    from tests.test_evaluation_scope_badge_per_notice import _function_source

    source = "\n".join(
        _function_source(template, name) for name in ("scoreText", "memberRecommendationText")
    )
    script = f"""
const amountText = value => value == null ? '-' : String(value) + '원';
{source}
const cases = {json.dumps(CASES, ensure_ascii=False)};
const out = {{}};
for (const [key, data] of Object.entries(cases)) out[key] = memberRecommendationText(data);
process.stdout.write(JSON.stringify(out));
"""
    result = subprocess.run(  # noqa: S603 - node 경로와 인자를 이 테스트가 직접 고정합니다
        [node, "-e", script], capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_clipped_sentence_is_appended_only_when_true(reason_texts: dict[str, str]) -> None:
    """잘림이 True 일 때만 점수 때문에 구간이 달라진다는 문장을 덧붙인다."""
    base = "정량점수 30점 기준 통과 구간(최저가~최상가) 안이라 AI 예측가를 그대로 추천합니다."
    assert reason_texts["clipped"] == base + " " + CLIPPED_SENTENCE
    assert reason_texts["not_clipped"] == base
    assert reason_texts["absent"] == base
    assert CLIPPED_SENTENCE not in reason_texts["not_clipped"]
    assert CLIPPED_SENTENCE not in reason_texts["absent"]


def test_raised_reason_keeps_its_own_sentence(reason_texts: dict[str, str]) -> None:
    """최저가로 올린 경우의 기존 문장 뒤에 잘림 문장이 붙는다."""
    assert reason_texts["raised_clipped"] == (
        "AI 예측가 900원은 정량점수 25점으로는 어떤 예정가격에서도 적격 통과점수에 못 미쳐 "
        "최저가로 올렸습니다. " + CLIPPED_SENTENCE
    )

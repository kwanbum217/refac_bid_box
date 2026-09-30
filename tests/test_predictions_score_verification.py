"""
tests/test_predictions_score_verification.py

낙찰가 예측 응답(POST /api/v1/predictions/predict-price)에 붙는 정량평가 점수
통과 판정을 검증합니다.

- B·k·T·Q 를 주면 price_score_verification 정본 함수로 추천가와 예측 구간을 채점한다
- B·k·T 중 하나라도 없으면 점수를 만들지 않고 확인 불가 사유를 돌려준다
- 구 모델처럼 예측 구간이 없으면 구간 평점을 계산하지 않는다
- Q 미입력 시 0 으로 가정했음과 그 경고가 응답에 드러난다
- 기존 응답 필드는 이름·의미·기본값이 그대로다

산식을 다시 구현하지 않고 verify_price_score·invert_pass_bid_range 를 호출하는지도
호출 횟수로 고정합니다.
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from src.app.core.timeutil import utcnow
from src.app.models.bids import BidAnnouncement
from src.ml.model_registry import PredictionOutcome

# 가이드 예시: 예정가격 500,000,000 / B=70 / k=2 / 기준 88% / T=85
GUIDE_PRED_PRICE = 500_000_000
GUIDE_RATE = 0.8148976  # 500,000,000 * 0.8148976 = 407,448,800 (= 비율 0.8149)
GUIDE_B = 70.0
GUIDE_K = 2.0
GUIDE_T = 85.0
GUIDE_BASE_RATE = "88"

# B=70, k=2, 기준 88%, T=85, Q=30 이면 N=55, 허용차 0.075 로 구간이 성립한다.
GUIDE_Q = 30.0
GUIDE_PASS_AMOUNT_LOW = 402_475_000
GUIDE_PASS_AMOUNT_HIGH = 477_524_999


def _outcome(rate: float = GUIDE_RATE) -> PredictionOutcome:
    return PredictionOutcome(
        predicted_rate=rate,
        requested_model="test_model",
        actual_model="test_model",
        fallback_used=False,
        fallback_reason=None,
    )


def _wrapper() -> MagicMock:
    wrapper = MagicMock()
    wrapper.get_display_name.return_value = "테스트 모델"
    return wrapper


def _rule(base_rate: str = GUIDE_BASE_RATE) -> SimpleNamespace:
    return SimpleNamespace(
        is_blocked=False,
        block_reason_code=None,
        block_reason_message=None,
        rule=SimpleNamespace(base_rate=Decimal(base_rate)),
        warnings=[],
        effective_lwlt_rate=Decimal("89.995"),
    )


def _blocked_rule() -> SimpleNamespace:
    return SimpleNamespace(
        is_blocked=True,
        block_reason_code="NOT_SERVC",
        block_reason_message="용역 적격심사 대상이 아닙니다.",
        rule=None,
        warnings=[],
    )


def _create_bid(db, **overrides) -> BidAnnouncement:
    raw = overrides.pop(
        "raw_data", {"prearngPrceDcsnMthdNm": "복수예가", "bdgtAmt": GUIDE_PRED_PRICE}
    )
    defaults = {
        "bid_ntce_nm": "점수 판정 테스트 공고",
        "bid_ntce_no": "SCORE-BID-001",
        "bid_ntce_ord": "000",
        "ntce_instt_nm": "테스트 공고기관",
        "dminstt_nm": "테스트 수요기관",
        "base_amount": GUIDE_PRED_PRICE,
        "presmpt_prce": GUIDE_PRED_PRICE,
        "bid_ntce_dt": utcnow(),
        "bid_clse_dt": utcnow(),
        "openg_dt": utcnow(),
        "category": "Servc",
        "raw_data": raw,
    }
    defaults.update(overrides)
    bid = BidAnnouncement(**defaults)
    db.add(bid)
    db.commit()
    db.refresh(bid)
    return bid


def _post(client, bid_id: int, **extra):
    payload = {"bid_id": bid_id, "user_price": "0"}
    payload.update(extra)
    return client.post("/api/v1/predictions/predict-price", json=payload)


def test_verdict_scores_guide_example_and_feasible_pass_range(client, isolated_db):
    """가이드 예시에서 추천가 평점이 산식과 일치하고 통과 구간이 역산된다."""
    bid = _create_bid(isolated_db, bid_ntce_no="SCORE-GUIDE")
    with (
        patch(
            "src.app.api.v1.predictions.predict_optimal_price_with_provenance",
            return_value=_outcome(),
        ),
        patch("src.app.api.v1.predictions.predict_interval", return_value=(80.0, 85.0, 0.9)),
        patch("src.app.api.v1.predictions.ModelRegistry.get_model", return_value=_wrapper()),
        patch(
            "src.app.api.v1.predictions.resolve_evaluation_rule_from_raw_data",
            return_value=_rule(),
        ),
    ):
        response = _post(
            client,
            bid.id,
            max_price_score=GUIDE_B,
            multiplier=GUIDE_K,
            pass_threshold=GUIDE_T,
            non_price_score=GUIDE_Q,
        )

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["optimal_price"] == 407_448_800
    assert data["price_low"] == 400_000_000
    assert data["price_high"] == 425_000_000

    verdict = data["score_verdict"]
    assert verdict["verifiable"] is True
    assert verdict["base_rate"] == "88"
    assert verdict["max_price_score"] == "70"
    assert verdict["multiplier"] == "2"
    assert verdict["pass_threshold"] == "85"  # noqa: S105 - 배점표 항목 키이지 비밀번호가 아님
    assert verdict["non_price_score"] == "30"
    assert verdict["non_price_score_assumed_zero"] is False
    # P = B - k*|기준율 - x|*100 = 70 - 2*|0.88 - 0.8149|*100 = 56.98
    assert verdict["optimal_price_score"] == "56.98"
    assert verdict["price_low_score"] == "54"
    assert verdict["price_high_score"] == "64"
    assert verdict["pass_range_status"] == "feasible"  # noqa: S105 - 판정 상태값이지 비밀번호가 아님
    assert verdict["pass_amount_low"] == GUIDE_PASS_AMOUNT_LOW
    assert verdict["pass_amount_high"] == GUIDE_PASS_AMOUNT_HIGH
    assert verdict["pass_ratio_low"] == "0.805"  # noqa: S105 - 통과 비율 하한이지 비밀번호가 아님
    assert verdict["pass_ratio_high"] == "0.955"  # noqa: S105 - 통과 비율 상한이지 비밀번호가 아님
    # 낙찰하한율이 없으면 유효 구간은 점수 구간과 같다.
    assert verdict["effective_amount_low"] == GUIDE_PASS_AMOUNT_LOW
    assert verdict["effective_amount_high"] == GUIDE_PASS_AMOUNT_HIGH
    assert verdict["optimal_price_passes"] is True
    # 교집합 22,525,000 / 예측 구간 폭 25,000,000 = 0.901
    assert verdict["predicted_interval_overlap_ratio"] == "0.901"
    assert verdict["unavailable_reasons"] == []


def test_verdict_unverifiable_when_score_table_incomplete(client, isolated_db):
    """B·k·T 중 하나라도 없으면 점수를 만들지 않고 확인 불가 사유를 돌려준다."""
    bid = _create_bid(isolated_db, bid_ntce_no="SCORE-INCOMPLETE")
    with (
        patch(
            "src.app.api.v1.predictions.predict_optimal_price_with_provenance",
            return_value=_outcome(),
        ),
        patch("src.app.api.v1.predictions.predict_interval", return_value=(80.0, 85.0, 0.9)),
        patch("src.app.api.v1.predictions.ModelRegistry.get_model", return_value=_wrapper()),
        patch(
            "src.app.api.v1.predictions.resolve_evaluation_rule_from_raw_data",
            return_value=_rule(),
        ),
    ):
        response = _post(client, bid.id, max_price_score=GUIDE_B, multiplier=GUIDE_K)

    assert response.status_code == 200, response.text
    verdict = response.json()["score_verdict"]
    assert verdict["verifiable"] is False
    assert verdict["optimal_price_score"] is None
    assert verdict["price_low_score"] is None
    assert verdict["pass_range_status"] is None
    assert any("적격 통과점수" in reason for reason in verdict["unavailable_reasons"])


def test_verdict_returns_reason_when_no_score_table_given(client, isolated_db):
    """배점표를 안 준 요청도 판정 불가 사유를 응답과 메시지에 남긴다."""
    bid = _create_bid(
        isolated_db,
        bid_ntce_no="SCORE-NONE",
        raw_data={
            "prearngPrceDcsnMthdNm": "복수예가",
            "bdgtAmt": GUIDE_PRED_PRICE,
            "sucsfbidLwltRate": "87.745",
        },
    )
    with (
        patch(
            "src.app.api.v1.predictions.predict_optimal_price_with_provenance",
            return_value=_outcome(),
        ),
        patch("src.app.api.v1.predictions.predict_interval", return_value=(87.0, 90.0, 0.9)),
        patch("src.app.api.v1.predictions.ModelRegistry.get_model", return_value=_wrapper()),
        patch(
            "src.app.api.v1.predictions.resolve_evaluation_rule_from_raw_data",
            return_value=_rule(),
        ),
    ):
        response = _post(client, bid.id)

    assert response.status_code == 200, response.text
    data = response.json()
    verdict = data["score_verdict"]
    assert verdict["verifiable"] is False
    assert verdict["optimal_price_score"] is None
    assert any("배점표" in reason for reason in verdict["unavailable_reasons"])
    assert "정량평가 점수 통과 판정을 하지 못했습니다" in data["message"]
    # 배점표를 주지 않은 요청은 기존 불확실성 경고를 건드리지 않는다.
    assert data["uncertainty_warning"] is None


def test_verdict_unverifiable_when_rule_blocked(client, isolated_db):
    """규칙이 차단되면 평점을 시도하지 않고 차단 사유를 남긴다."""
    bid = _create_bid(isolated_db, bid_ntce_no="SCORE-BLOCKED")
    with (
        patch(
            "src.app.api.v1.predictions.predict_optimal_price_with_provenance",
            return_value=_outcome(),
        ),
        patch("src.app.api.v1.predictions.predict_interval", return_value=(80.0, 85.0, 0.9)),
        patch("src.app.api.v1.predictions.ModelRegistry.get_model", return_value=_wrapper()),
        patch(
            "src.app.api.v1.predictions.resolve_evaluation_rule_from_raw_data",
            return_value=_blocked_rule(),
        ),
    ):
        response = _post(
            client,
            bid.id,
            max_price_score=GUIDE_B,
            multiplier=GUIDE_K,
            pass_threshold=GUIDE_T,
            non_price_score=GUIDE_Q,
        )

    assert response.status_code == 200, response.text
    data = response.json()
    verdict = data["score_verdict"]
    assert verdict["verifiable"] is False
    assert verdict["optimal_price_score"] is None
    assert any("NOT_SERVC" in reason for reason in verdict["unavailable_reasons"])
    # 배점표를 줬는데도 판정하지 못했으므로 불확실성 경고에 이유를 덧붙인다.
    assert data["uncertainty_warning"] is not None
    assert "판정 불가" in data["uncertainty_warning"]


def test_interval_scores_absent_when_interval_missing(client, isolated_db):
    """예측 구간이 없는 구 모델에서는 구간 평점을 계산하지 않는다 (0 으로 채우지 않음)."""
    bid = _create_bid(isolated_db, bid_ntce_no="SCORE-NO-INTERVAL")
    with (
        patch(
            "src.app.api.v1.predictions.predict_optimal_price_with_provenance",
            return_value=_outcome(),
        ),
        patch("src.app.api.v1.predictions.predict_interval", return_value=None),
        patch("src.app.api.v1.predictions.ModelRegistry.get_model", return_value=_wrapper()),
        patch(
            "src.app.api.v1.predictions.resolve_evaluation_rule_from_raw_data",
            return_value=_rule(),
        ),
    ):
        response = _post(
            client,
            bid.id,
            max_price_score=GUIDE_B,
            multiplier=GUIDE_K,
            pass_threshold=GUIDE_T,
            non_price_score=GUIDE_Q,
        )

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["price_low"] is None
    assert data["price_high"] is None
    verdict = data["score_verdict"]
    assert verdict["verifiable"] is True
    assert verdict["optimal_price_score"] == "56.98"
    assert verdict["price_low_score"] is None
    assert verdict["price_high_score"] is None
    assert verdict["predicted_interval_overlap_ratio"] is None


def test_q_zero_assumption_disclosed(client, isolated_db):
    """Q 미입력 시 0 으로 가정했음과 그 영향이 응답과 경고에 드러난다."""
    bid = _create_bid(isolated_db, bid_ntce_no="SCORE-QZERO")
    with (
        patch(
            "src.app.api.v1.predictions.predict_optimal_price_with_provenance",
            return_value=_outcome(),
        ),
        patch("src.app.api.v1.predictions.predict_interval", return_value=(80.0, 85.0, 0.9)),
        patch("src.app.api.v1.predictions.ModelRegistry.get_model", return_value=_wrapper()),
        patch(
            "src.app.api.v1.predictions.resolve_evaluation_rule_from_raw_data",
            return_value=_rule(),
        ),
    ):
        response = _post(
            client, bid.id, max_price_score=GUIDE_B, multiplier=GUIDE_K, pass_threshold=GUIDE_T
        )

    assert response.status_code == 200, response.text
    data = response.json()
    verdict = data["score_verdict"]
    assert verdict["verifiable"] is True
    assert verdict["non_price_score_assumed_zero"] is True
    assert verdict["non_price_score"] == "0"
    assert verdict["uncertainty_note"] is not None
    assert "Q" in verdict["uncertainty_note"]
    assert data["uncertainty_warning"] is not None
    assert "Q" in data["uncertainty_warning"]
    # Q=0 이면 N=T=85 > B=70 이라 만점으로도 통과할 수 없다.
    assert verdict["pass_range_status"] == "impossible"  # noqa: S105 - 판정 상태값
    assert verdict["pass_amount_low"] is None
    assert verdict["pass_amount_high"] is None
    assert verdict["optimal_price_passes"] is None
    assert verdict["pass_range_reasons"]


def test_announcement_lwlt_rate_narrows_effective_range(client, isolated_db):
    """공고 낙찰하한율이 있으면 유효 통과 구간이 하한율 위로 올라간다."""
    bid = _create_bid(
        isolated_db,
        bid_ntce_no="SCORE-LWLT",
        raw_data={
            "prearngPrceDcsnMthdNm": "복수예가",
            "bdgtAmt": GUIDE_PRED_PRICE,
            "sucsfbidLwltRate": "89.995",
        },
    )
    with (
        patch(
            "src.app.api.v1.predictions.predict_optimal_price_with_provenance",
            return_value=_outcome(),
        ),
        patch("src.app.api.v1.predictions.predict_interval", return_value=(80.0, 85.0, 0.9)),
        patch("src.app.api.v1.predictions.ModelRegistry.get_model", return_value=_wrapper()),
        patch(
            "src.app.api.v1.predictions.resolve_evaluation_rule_from_raw_data",
            return_value=_rule(),
        ),
    ):
        response = _post(
            client,
            bid.id,
            max_price_score=GUIDE_B,
            multiplier=GUIDE_K,
            pass_threshold=GUIDE_T,
            non_price_score=GUIDE_Q,
        )

    assert response.status_code == 200, response.text
    verdict = response.json()["score_verdict"]
    assert verdict["pass_range_status"] == "feasible"  # noqa: S105 - 판정 상태값
    # 점수 구간 하한은 402,475,000 이지만 하한율 금액 449,975,000 이 실질 하한이다.
    assert verdict["pass_amount_low"] == GUIDE_PASS_AMOUNT_LOW
    assert verdict["effective_amount_low"] == 449_975_000
    assert verdict["effective_amount_high"] == GUIDE_PASS_AMOUNT_HIGH
    # 추천가 407,448,800 은 하한율 미달이라 통과하지 못한다.
    assert verdict["optimal_price_passes"] is False
    assert verdict["predicted_interval_overlap_ratio"] == "0"


def test_uses_price_score_verification_functions(client, isolated_db):
    """평점 산식을 재구현하지 않고 price_score_verification 함수를 호출한다."""
    import src.app.api.v1.predictions as predictions_module

    bid = _create_bid(isolated_db, bid_ntce_no="SCORE-SINGLE")
    with (
        patch(
            "src.app.api.v1.predictions.predict_optimal_price_with_provenance",
            return_value=_outcome(),
        ),
        patch("src.app.api.v1.predictions.predict_interval", return_value=(80.0, 85.0, 0.9)),
        patch("src.app.api.v1.predictions.ModelRegistry.get_model", return_value=_wrapper()),
        patch(
            "src.app.api.v1.predictions.resolve_evaluation_rule_from_raw_data",
            return_value=_rule(),
        ),
        patch(
            "src.app.api.v1.predictions.verify_price_score",
            side_effect=predictions_module.verify_price_score,
        ) as mock_verify,
        patch(
            "src.app.api.v1.predictions.invert_pass_bid_range",
            side_effect=predictions_module.invert_pass_bid_range,
        ) as mock_range,
    ):
        response = _post(
            client,
            bid.id,
            max_price_score=GUIDE_B,
            multiplier=GUIDE_K,
            pass_threshold=GUIDE_T,
            non_price_score=GUIDE_Q,
        )

    assert response.status_code == 200, response.text
    # 추천가와 예측 구간 하단·상단 세 건을 채점한다.
    assert mock_verify.call_count == 3
    assert mock_range.call_count == 1


def test_existing_response_fields_unchanged(client, isolated_db):
    """기존 응답 필드가 그대로 남고 신규 필드는 기본값을 가진다."""
    from src.app.schemas.predictions import PredictPriceResponse

    properties = PredictPriceResponse.model_json_schema()["properties"]
    legacy_fields = [
        "status",
        "optimal_price",
        "prediction_rate",
        "user_bid_similarity",
        "model_name",
        "model_id",
        "requested_model",
        "fallback_used",
        "fallback_reason",
        "message",
        "rate_low",
        "rate_high",
        "price_low",
        "price_high",
        "interval_coverage",
        "lwlt_missing",
        "lwlt_missing_reason",
        "wide_interval_warning",
        "extreme_prediction_warning",
        "uncertainty_warning",
    ]
    for field in legacy_fields:
        assert field in properties, field
    assert "score_verdict" in properties

    # 신규 필드는 기본값이 있어 score_verdict 없이도 응답을 만들 수 있다.
    response = PredictPriceResponse(
        optimal_price=1,
        prediction_rate=90.0,
        model_name="m",
        model_id="m",
        requested_model="m",
        message="ok",
    )
    assert response.score_verdict is None


def test_score_table_inputs_reject_non_positive(client, isolated_db):
    """배점표 입력은 음수와 0 을 받지 않는다."""
    bid = _create_bid(isolated_db, bid_ntce_no="SCORE-VALIDATION")
    bad_payloads = (
        {"max_price_score": 0, "multiplier": GUIDE_K, "pass_threshold": GUIDE_T},
        {"max_price_score": GUIDE_B, "multiplier": -1, "pass_threshold": GUIDE_T},
        {"max_price_score": GUIDE_B, "multiplier": GUIDE_K, "pass_threshold": 0},
        {
            "max_price_score": GUIDE_B,
            "multiplier": GUIDE_K,
            "pass_threshold": GUIDE_T,
            "non_price_score": 0,
        },
    )
    for bad in bad_payloads:
        response = _post(client, bid.id, **bad)
        assert response.status_code == 422, (bad, response.text)

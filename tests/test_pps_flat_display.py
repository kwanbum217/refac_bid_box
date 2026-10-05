"""
tests/test_pps_flat_display.py

사용자가 B·k 를 직접 입력해 조달청 평탄이 실제로 적용되지 않는 경우, 응답의
flat_ratio·flat_score 표시가 실제 점수 계산의 평탄 적용 여부와 일치하는지 고정합니다.

핵심 계약:
1. /evaluations/analyze 의 score_table.flat_ratio·flat_score 는 점수 계산에 실제 쓴 B·k 로
   조회한다. 입력 B·k 가 규칙의 어느 축 값과도 다르면 평탄은 계산에 쓰이지 않으므로 표시도
   null 이고, 시나리오 가격점수는 평탄 없이 산식값이 된다.
2. /predictions 도 같은 세 입력에서 표시 점수(추천가 가격평점)와 실제 계산이 일치한다.
   어느 축과도 다른 B·k 면 점수가 평탄값으로 고정되지 않는다.
3. 지방 규칙은 실제 적용한 B·k 를 추정가격 구간 값으로 고르므로 종전 결과가 바뀌지 않는다.

규칙 판별·평탄 조회·점수 계산은 mock 없이 실제 코드로 돌리고, 외부 모델 추론만 대역으로
바꿉니다.
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.app.api.v1 import evaluations
from src.app.api.v1.evaluations import require_current_user
from src.app.api.v1.predictions import _flat_zone_for_bid
from src.app.core.timeutil import utcnow
from src.app.main import app
from src.app.models.bids import BidAnnouncement
from src.app.models.demand_institutions import G2BDemandInstitution
from src.app.schemas.predictions import PredictPriceResponse
from src.app.services.evaluation_flat_zones import pps_flat_zone_for
from src.app.services.evaluation_rules import POST_20260526_RULES
from src.app.services.evaluation_scoring import format_decimal_plain
from src.ml.model_registry import PredictionOutcome

ANALYZE_URL = "/api/v1/evaluations/analyze"
PREDICT_URL = "/api/v1/predictions/predict-price"

# 시설분야용역 적격심사 추정가격 5억원 미만: B 축 조건부(미만 70), k 5, T 85, 기준비율 0.93.
RULE_ID = "SERVC_QUAL_POST_20260526_ATTACH_01"
METHOD_NAME = "시설분야용역 적격심사 추정가격 5억원 미만"
PRESMPT_PRCE = 400_000_000
# 평탄 시작 비율(0.96)보다 위쪽이라 산식값과 평탄 고정값이 확실히 갈린다.
RATIO = Decimal("0.98")
CANDIDATE = int(Decimal(PRESMPT_PRCE) * RATIO)

B_AXIS = Decimal("70")
K_AXIS = Decimal("5")
# 규칙 축 사전의 어느 쪽 값(70/60, k 5)과도 다른 입력.
B_OFF_AXIS = Decimal("65")
K_OFF_AXIS = Decimal("3")
BASE_RATE = Decimal("0.93")

ALGEBRA_AXIS = B_AXIS - K_AXIS * abs(BASE_RATE - RATIO) * Decimal("100")
ALGEBRA_OFF_AXIS = B_OFF_AXIS - K_OFF_AXIS * abs(BASE_RATE - RATIO) * Decimal("100")


@pytest.fixture
def as_user():
    def _set_user(user_id: int) -> None:
        app.dependency_overrides[require_current_user] = lambda: SimpleNamespace(id=user_id)

    yield _set_user
    app.dependency_overrides.pop(require_current_user, None)


@pytest.fixture(autouse=True)
def stub_evaluation_prediction(monkeypatch):
    """평가 응답의 모델 출처만 고정 대역으로 바꿉니다. 규칙·평탄·점수 계산은 실제 코드입니다."""

    def _fake_predict(payload, request, db):
        return PredictPriceResponse(
            status="success",
            optimal_price=CANDIDATE,
            prediction_rate=98.0,
            model_name="테스트 대역 모델",
            model_id=payload.selected_model or "default-model",
            requested_model=payload.selected_model or "default-model",
            fallback_used=False,
            fallback_reason=None,
            message="테스트용 예측 대역 응답",
        )

    monkeypatch.setattr(evaluations, "predict_price_api", _fake_predict)


def _create_pps_bid(db) -> BidAnnouncement:
    """조달청 일반용역 적격심사 공고를 만들어 실제 규칙 판별 경로를 엽니다."""
    bid = BidAnnouncement(
        bid_ntce_nm="조달청 평탄 표시 끝단 테스트 공고",
        bid_ntce_no="PPS-FLAT-DISPLAY-001",
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
            "sucsfbidMthdNm": METHOD_NAME,
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


def _create_local_bid(db) -> BidAnnouncement:
    """인천광역시 지방계약 공고. 지방 규칙 결과 불변 확인용입니다."""
    db.add(
        G2BDemandInstitution(
            dminstt_cd="1234",
            dminstt_nm="인천광역시 본청",
            jrsdctn_div_nm="지방자치단체",
            rgn_cd="28000",
            rgn_nm="인천광역시 남구",
            toplvl_instt_cd="6270000",
            toplvl_instt_nm="인천광역시",
            raw_json={},
        )
    )
    db.commit()
    bid = BidAnnouncement(
        bid_ntce_nm="지방계약 평탄 표시 끝단 테스트 공고",
        bid_ntce_no="LOCAL-FLAT-DISPLAY-001",
        bid_ntce_ord="000",
        ntce_instt_nm="테스트 공고기관",
        dminstt_nm="인천광역시 본청",
        base_amount=150_000_000,
        presmpt_prce=150_000_000,
        bid_ntce_dt=utcnow(),
        bid_clse_dt=utcnow(),
        openg_dt=utcnow(),
        category="Servc",
        raw_data={
            "prearngPrceDcsnMthdNm": "복수예가",
            "sucsfbidMthdNm": "용역 적격심사",
            "sucsfbidLwltRate": "87.995",
            "srvceDivNm": "일반용역",
            "cntrctCnclsMthdNm": "지방자치단체 제한경쟁",
            "dminsttCd": "1234",
            "totPrdprcNum": "12",
            "drwtPrdprcNum": "3",
        },
    )
    db.add(bid)
    db.commit()
    db.refresh(bid)
    return bid


def _expected_axis_flat() -> tuple[str, str]:
    """추정가격 5억원 미만(B 축 False)의 원문 평탄 비율·점수."""
    zone = pps_flat_zone_for(RULE_ID, above_500m=False, above_notice=None)
    assert zone is not None
    assert zone.flat_score is not None
    return format_decimal_plain(zone.flat_ratio), format_decimal_plain(zone.flat_score)


def _analyze(client, bid: BidAnnouncement, qualification_input: dict) -> dict:
    response = client.post(
        ANALYZE_URL,
        json={
            "bid_id": bid.id,
            "candidate_bid_amount": CANDIDATE,
            "qualification_input": qualification_input,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _base_scenario(body: dict) -> dict:
    return next(row for row in body["scenario_results"] if row["scenario_name"] == "기준")


def _outcome(rate: float) -> PredictionOutcome:
    return PredictionOutcome(
        predicted_rate=rate,
        requested_model="test_model",
        actual_model="test_model",
        fallback_used=False,
        fallback_reason=None,
    )


def _wrapper() -> MagicMock:
    wrapper = MagicMock()
    wrapper.get_display_name.return_value = "테스트 대역 모델"
    return wrapper


def _predict(client, bid: BidAnnouncement, payload: dict, *, rate: float = 0.98) -> dict:
    with (
        patch(
            "src.app.api.v1.predictions.predict_optimal_price_with_provenance",
            return_value=_outcome(rate),
        ),
        patch("src.app.api.v1.predictions.predict_interval", return_value=(96.0, 99.0, 0.9)),
        patch("src.app.api.v1.predictions.ModelRegistry.get_model", return_value=_wrapper()),
    ):
        response = client.post(PREDICT_URL, json={"bid_id": bid.id, "user_price": "0", **payload})
    assert response.status_code == 200, response.text
    return response.json()


class TestEvaluationsFlatDisplayMatchesApplied:
    """세 입력 경우의 score_table.flat_* 표시가 실제 점수 계산의 평탄 적용 여부와 같아야 한다."""

    def test_missing_bk_uses_declared_axis_and_pins_score(
        self, client, isolated_db, as_user
    ) -> None:
        as_user(10)
        bid = _create_pps_bid(isolated_db)
        flat_ratio, flat_score = _expected_axis_flat()

        body = _analyze(client, bid, {"disqualification": False, "quant_items": {}})

        assert body["status"] == "success", body.get("blocked_reason")
        table = body["score_table"]
        assert table["flat_ratio"] == flat_ratio
        assert table["flat_score"] == flat_score
        assert _base_scenario(body)["price_score"] == pytest.approx(float(Decimal(flat_score)))

    def test_on_axis_bk_matches_flat_and_pins_score(self, client, isolated_db, as_user) -> None:
        as_user(10)
        bid = _create_pps_bid(isolated_db)
        flat_ratio, flat_score = _expected_axis_flat()

        body = _analyze(
            client,
            bid,
            {
                "disqualification": False,
                "quant_items": {},
                "max_price_score": float(B_AXIS),
                "multiplier": float(K_AXIS),
                "pass_threshold": 85.0,
            },
        )

        assert body["status"] == "success", body.get("blocked_reason")
        table = body["score_table"]
        assert table["flat_ratio"] == flat_ratio
        assert table["flat_score"] == flat_score
        assert _base_scenario(body)["price_score"] == pytest.approx(float(Decimal(flat_score)))
        # 평탄이 없었다면 산식값(45)이었으므로 고정이 실제로 일어났다.
        assert Decimal(flat_score) > ALGEBRA_AXIS

    def test_off_axis_bk_hides_flat_and_leaves_algebraic_score(
        self, client, isolated_db, as_user
    ) -> None:
        as_user(10)
        bid = _create_pps_bid(isolated_db)
        _flat_ratio, flat_score = _expected_axis_flat()

        body = _analyze(
            client,
            bid,
            {
                "disqualification": False,
                "quant_items": {},
                "max_price_score": float(B_OFF_AXIS),
                "multiplier": float(K_OFF_AXIS),
                "pass_threshold": 85.0,
            },
        )

        assert body["status"] == "success", body.get("blocked_reason")
        table = body["score_table"]
        # 계산에 평탄을 쓰지 않았으므로 표시도 null 이어야 한다.
        assert table["flat_ratio"] is None
        assert table["flat_score"] is None
        # 표시된 평탄이 없으므로 점수는 평탄 고정값이 아니라 산식값이다.
        price_score = _base_scenario(body)["price_score"]
        assert price_score != pytest.approx(float(Decimal(flat_score)))
        assert price_score == pytest.approx(float(ALGEBRA_OFF_AXIS))


class TestPredictionsFlatDisplayMatchesApplied:
    """세 입력 경우의 표시 점수가 실제 평탄 적용 여부와 같아야 한다."""

    def test_on_axis_bk_pins_optimal_price_score(self, client, isolated_db) -> None:
        bid = _create_pps_bid(isolated_db)
        _flat_ratio, flat_score = _expected_axis_flat()

        data = _predict(
            client,
            bid,
            {
                "max_price_score": float(B_AXIS),
                "multiplier": float(K_AXIS),
                "pass_threshold": 85.0,
                "non_price_score": 45.0,
            },
        )

        verdict = data["score_verdict"]
        assert verdict["verifiable"] is True
        assert verdict["optimal_price_score"] == flat_score
        assert Decimal(flat_score) > ALGEBRA_AXIS

    def test_off_axis_bk_does_not_pin_optimal_price_score(self, client, isolated_db) -> None:
        bid = _create_pps_bid(isolated_db)
        _flat_ratio, flat_score = _expected_axis_flat()

        data = _predict(
            client,
            bid,
            {
                "max_price_score": float(B_OFF_AXIS),
                "multiplier": float(K_OFF_AXIS),
                "pass_threshold": 85.0,
                "non_price_score": 45.0,
            },
        )

        verdict = data["score_verdict"]
        assert verdict["verifiable"] is True
        assert verdict["optimal_price_score"] != flat_score
        assert verdict["optimal_price_score"] == format_decimal_plain(ALGEBRA_OFF_AXIS)

    def test_missing_bk_is_unverifiable(self, client, isolated_db) -> None:
        bid = _create_pps_bid(isolated_db)

        data = _predict(client, bid, {})

        verdict = data["score_verdict"]
        assert verdict["verifiable"] is False
        assert verdict["unavailable_reasons"]

    def test_lookup_without_applied_axis_does_not_substitute_declared_value(
        self, isolated_db
    ) -> None:
        bid = _create_pps_bid(isolated_db)
        rule = next(rule for rule in POST_20260526_RULES if rule.rule_id == RULE_ID)
        assert rule.max_price_score_by_500m is not None

        # 적용 B 를 주지 않으면 규칙 선언값(70)으로 대체하지 않고 평탄을 적용하지 않는다.
        assert _flat_zone_for_bid(bid, rule, multiplier=K_AXIS) is None


class TestLocalRuleDisplayUnchanged:
    """지방 규칙은 추정가격 구간으로 평탄을 고르므로 실제 적용 B·k 배선 후에도 결과가 같다."""

    def test_incheon_flat_display_and_score_unchanged(self, client, isolated_db, as_user) -> None:
        as_user(10)
        bid = _create_local_bid(isolated_db)

        body = _analyze(
            client,
            bid,
            {
                "disqualification": False,
                "manual_non_price_score": 60.0,
                "local_service_type": "GENERAL",
            },
        )

        assert body["status"] == "success", body.get("blocked_reason")
        assert body["rule_id"] == "SERVC_LOCAL_INCHEON_20251224_ATTACH_01"
        table = body["score_table"]
        assert table["flat_ratio"] == "0.8825"
        assert table["flat_score"] == "85"
        assert _base_scenario(body)["price_score"] == pytest.approx(85.0)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))

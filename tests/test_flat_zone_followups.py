"""
tests/test_flat_zone_followups.py

평탄 구간 반영의 후속 결함 세 가지를 고정합니다.

1. 보정 경로 시험 공백: resolve_price_compensation 의 하한 금액 채점이 평탄 구간 위에서
   동작하는 경우(하한 비율이 평탄 시작 비율 이상)를 시나리오 경로로 고정합니다.
2. 비연속 구간: flat_score 가 산식(flat_ratio) 대입값보다 큰 합성 데이터에서 통과 구간이
   둘로 갈라질 때 invert_pass_bid_range 가 잘못된 단일 구간(가운데 미통과 구간 포함)을
   내지 않는지 0.0001 간격 점수로 대조합니다.
3. /predictions 평탄 미반영: TestClient 끝단에서 선택 규칙·구간의 평탄이 추천가 점수와
   통과 구간에 실제로 반영되는지 mock 없이 규칙 판별까지 실제 코드로 확인합니다.

평탄 데이터가 없는 규칙의 결과가 기존과 같은지도 함께 고정합니다.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, ClassVar
from unittest.mock import MagicMock, patch

import pytest

from src.app.core.timeutil import utcnow
from src.app.models.bids import BidAnnouncement
from src.app.models.demand_institutions import G2BDemandInstitution
from src.app.services.evaluation_flat_zones import flat_zone_for
from src.app.services.evaluation_scoring import calculate_price_score, resolve_price_compensation
from src.app.services.price_score_verification import invert_pass_bid_range
from src.ml.model_registry import PredictionOutcome

PRED = Decimal("100000000")
PREDICT_URL = "/api/v1/predictions/predict-price"


# =============================================================================
# 1. 보정 경로 평탄 시험
# =============================================================================


class TestCompensationPathFlat:
    """하한 금액 채점이 평탄 구간 위에서 동작하는 경우를 고정합니다.

    공고 하한율이 평탄 시작 비율(0.8825)보다 높으면 최저 투찰금액의 가격점수는 산식값이
    아니라 평탄 고정 점수(85)가 됩니다. 평탄 데이터가 없으면 같은 입력이 도달 불가로
    판정되는 대비까지 함께 봅니다.
    """

    BASE_KWARGS: ClassVar[dict[str, Any]] = {
        "pass_threshold": Decimal("95"),
        "non_price_score": Decimal("15"),
        "base_rate": Decimal("0.88"),
        "max_price_score": Decimal("90"),
        "multiplier": Decimal("20"),
        "announcement_lwlt_rate": Decimal("90"),
        "scenarios": [("기준", "base", PRED)],
    }

    def test_flat_floor_makes_scenario_already_sufficient(self) -> None:
        # N = 95 - 15 = 80, 하한 90% -> x 0.90 (평탄 88.25% 위) -> 평탄 점수 85 >= 80
        with_flat = resolve_price_compensation(
            **self.BASE_KWARGS,
            flat_ratio=Decimal("0.8825"),
            flat_score=Decimal("85"),
        )
        assert with_flat.score_status == "already_sufficient"
        assert with_flat.floor_price_score == Decimal("85")
        assert with_flat.score_gap == Decimal("0")
        assert with_flat.score_slack == Decimal("5")
        assert with_flat.amount_status == "verified"
        assert with_flat.floor_score_basis == "forward_verified"
        assert with_flat.score_floor_amount == Decimal("90000000")

        # 평탄이 없으면 하한 90% 의 산식값 50 점으로는 80 점에 닿지 못해 도달 불가다.
        without_flat = resolve_price_compensation(**self.BASE_KWARGS)
        assert without_flat.floor_price_score == Decimal("50.0000")
        assert without_flat.score_status == "impossible"

    def test_flat_floor_below_requirement_is_impossible(self) -> None:
        # N = 95 - 9 = 86 이면 평탄 고정 점수 85 로는 부족하고, 하한 금액 x 가 기준비율을
        # 넘어 원 단위로 되돌릴 수 없다.
        result = resolve_price_compensation(
            pass_threshold=Decimal("95"),
            non_price_score=Decimal("9"),
            base_rate=Decimal("0.88"),
            max_price_score=Decimal("90"),
            multiplier=Decimal("20"),
            announcement_lwlt_rate=Decimal("90"),
            scenarios=[("기준", "base", PRED)],
            flat_ratio=Decimal("0.8825"),
            flat_score=Decimal("85"),
        )
        assert result.score_status == "impossible"
        assert result.floor_price_score == Decimal("85")
        assert result.score_gap == Decimal("1")

    def test_floor_exactly_at_flat_ratio_uses_flat_score(self) -> None:
        # 하한율 88.25% -> x 가 평탄 시작 비율과 정확히 같다. 이 지점부터 평탄이 적용된다.
        result = resolve_price_compensation(
            pass_threshold=Decimal("95"),
            non_price_score=Decimal("10"),
            base_rate=Decimal("0.88"),
            max_price_score=Decimal("90"),
            multiplier=Decimal("20"),
            announcement_lwlt_rate=Decimal("88.25"),
            scenarios=[("기준", "base", PRED)],
            flat_ratio=Decimal("0.8825"),
            flat_score=Decimal("85"),
        )
        assert result.floor_price_score == Decimal("85")
        assert result.score_status == "already_sufficient"


# =============================================================================
# 2. 비연속 구간 합성 시험
# =============================================================================


def _discontinuous_args() -> dict[str, Decimal]:
    """flat_score 26 이 산식 대입값 24 보다 커서 통과 구간이 둘로 갈라지는 합성 입력."""
    return {
        "pass_threshold": Decimal("95"),  # T
        "non_price_score": Decimal("70"),  # Q -> N = 25
        "base_rate": Decimal("0.90"),
        "max_price_score": Decimal("30"),  # B
        "multiplier": Decimal("2"),  # k
        "pred_price": PRED,
        "flat_ratio": Decimal("0.93"),
        "flat_score": Decimal("26"),
    }


def _flat_score_at(ratio: str, flat_ratio: str, flat_score: str) -> Decimal:
    bid = (PRED * Decimal(ratio)).quantize(Decimal("1"))
    return calculate_price_score(
        bid_price=bid,
        pred_price=PRED,
        base_rate=Decimal("0.90"),
        max_price_score=Decimal("30"),
        multiplier=Decimal("2"),
        flat_ratio=Decimal(flat_ratio),
        flat_score=Decimal(flat_score),
    ).score


class TestInvertPassBidRangeDiscontinuousFlat:
    """평탄이 산식 통과 구간과 떨어질 때 통과 구간을 잘못 넓히지 않는지 검증."""

    def test_reports_lower_interval_and_discloses_second_region(self) -> None:
        # 허용차 = (30 - 25) / 200 = 0.025 -> 산식 구간 [0.875, 0.925]
        # 평탄 시작 0.93 은 이 구간 밖이라 통과 구간이 [0.875, 0.925] 와 [0.93, 1] 로 갈라진다.
        result = invert_pass_bid_range(**_discontinuous_args())
        assert result.status == "feasible"
        assert result.is_feasible is True
        assert result.ratio_low == Decimal("0.875")
        assert result.ratio_high == Decimal("0.925")
        assert result.ratio_grid_high == Decimal("0.9250")
        assert result.amount_high == Decimal("92504999")
        # 가운데 미통과 구간을 삼키는 단일 구간(1.0 까지)으로 넓히지 않는다.
        assert result.ratio_high != Decimal("1")
        assert result.reasons
        assert any("둘로 나뉩니다" in reason for reason in result.reasons)
        assert any("0.93" in reason for reason in result.reasons)

    def test_sampled_scores_match_reported_interval(self) -> None:
        result = invert_pass_bid_range(**_discontinuous_args())
        n = result.required_price_score
        assert n == Decimal("25")

        # 보고한 산식 구간 안쪽은 0.0001 간격 전부 통과한다.
        x = Decimal("0.8750")
        while x <= Decimal("0.9250"):
            assert _flat_score_at(str(x), "0.93", "26") >= n, x
            x += Decimal("0.0001")

        # 산식 구간과 평탄 구간 사이(0.9251 ~ 0.9299)는 전부 미통과다.
        x = Decimal("0.9251")
        while x <= Decimal("0.9299"):
            assert _flat_score_at(str(x), "0.93", "26") < n, x
            x += Decimal("0.0001")

        # 평탄 구간(0.93 ~ 1)은 별도로 전부 통과한다 (사유로 알린 두 번째 구간).
        x = Decimal("0.9300")
        while x <= Decimal("1.0000"):
            assert _flat_score_at(str(x), "0.93", "26") >= n, x
            x += Decimal("0.0001")

    def test_contiguous_flat_still_extends_upper_bound_to_one(self) -> None:
        # 평탄 시작 0.905 <= 산식 상한 0.925 이면 두 구간이 이어져 상한이 1 까지 넓어진다.
        result = invert_pass_bid_range(
            pass_threshold=Decimal("95"),
            non_price_score=Decimal("70"),
            base_rate=Decimal("0.90"),
            max_price_score=Decimal("30"),
            multiplier=Decimal("2"),
            pred_price=PRED,
            flat_ratio=Decimal("0.905"),
            flat_score=Decimal("26"),
        )
        assert result.ratio_high == Decimal("1")
        assert not any("둘로 나뉩니다" in reason for reason in result.reasons)

    def test_flat_below_requirement_does_not_extend(self) -> None:
        result = invert_pass_bid_range(
            pass_threshold=Decimal("96"),  # N = 26
            non_price_score=Decimal("70"),
            base_rate=Decimal("0.90"),
            max_price_score=Decimal("30"),
            multiplier=Decimal("2"),
            pred_price=PRED,
            flat_ratio=Decimal("0.93"),
            flat_score=Decimal("25"),  # 26 미만이라 평탄 구간은 통과하지 못한다
        )
        # 허용차 = (30 - 26) / 200 = 0.02 -> 산식 상한 0.92. 평탄이 못 미쳐 넓히지 않는다.
        assert result.ratio_high == Decimal("0.92")
        assert not any("둘로 나뉩니다" in reason for reason in result.reasons)


# =============================================================================
# 3. /predictions 평탄 반영 시험 (TestClient, 규칙 판별은 실제 코드)
# =============================================================================


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
    wrapper.get_display_name.return_value = "테스트 모델"
    return wrapper


def _create_gn_local_bid(db, *, presmpt_prce: int) -> BidAnnouncement:
    """경상남도 수요기관과 지방계약 공고를 만들어 LOCAL 규칙 판별 경로를 엽니다.

    경상남도는 일반 별표 하나만 있어 용역 세부유형 선택 없이 규칙이 확정된다.
    """
    db.add(
        G2BDemandInstitution(
            dminstt_cd="1234",
            dminstt_nm="경상남도 본청",
            jrsdctn_div_nm="지방자치단체",
            rgn_cd="48000",
            rgn_nm="경상남도 창원시",
            toplvl_instt_cd="6480000",
            toplvl_instt_nm="경상남도",
            raw_json={},
        )
    )
    db.commit()
    raw = {
        "prearngPrceDcsnMthdNm": "복수예가",
        "sucsfbidMthdNm": "용역 적격심사",
        "sucsfbidLwltRate": "87.995",
        "srvceDivNm": "일반용역",
        "cntrctCnclsMthdNm": "지방자치단체 제한경쟁",
        "dminsttCd": "1234",
        "totPrdprcNum": "12",
        "drwtPrdprcNum": "3",
    }
    bid = BidAnnouncement(
        bid_ntce_nm="지방계약 평탄 반영 예측 테스트",
        bid_ntce_no="PRED-FLAT-ZONE-001",
        bid_ntce_ord="000",
        ntce_instt_nm="테스트 공고기관",
        dminstt_nm="경상남도 본청",
        base_amount=presmpt_prce,
        presmpt_prce=presmpt_prce,
        bid_ntce_dt=utcnow(),
        bid_clse_dt=utcnow(),
        openg_dt=utcnow(),
        category="Servc",
        raw_data=raw,
    )
    db.add(bid)
    db.commit()
    db.refresh(bid)
    return bid


class TestPredictionsFlatWiring:
    """/predictions 끝단이 평탄을 반영하지 않던 결함을 고정."""

    def test_predict_price_reflects_flat_zone(self, client, isolated_db) -> None:
        # 경남 2억 미만: B 90, k 20, 기준 88, 평탄 88.25% -> 85점. 추천가 x=0.95 지점의
        # 산식값은 -50 이지만 평탄 고정으로 85 가 되어야 한다.
        bid = _create_gn_local_bid(isolated_db, presmpt_prce=150_000_000)
        with (
            patch(
                "src.app.api.v1.predictions.predict_optimal_price_with_provenance",
                return_value=_outcome(0.95),
            ),
            patch("src.app.api.v1.predictions.predict_interval", return_value=(90.0, 97.0, 0.9)),
            patch("src.app.api.v1.predictions.ModelRegistry.get_model", return_value=_wrapper()),
        ):
            response = client.post(
                PREDICT_URL,
                json={
                    "bid_id": bid.id,
                    "user_price": "0",
                    "max_price_score": 90,
                    "multiplier": 20,
                    "pass_threshold": 95,
                    "non_price_score": 10,
                },
            )

        assert response.status_code == 200, response.text
        data = response.json()
        assert data["optimal_price"] == 142_500_000

        verdict = data["score_verdict"]
        assert verdict["verifiable"] is True
        # 평탄이 없으면 -50 이다. 평탄 고정 점수 85 가 반영되어야 한다.
        assert verdict["optimal_price_score"] == "85"
        assert verdict["base_rate"] == "0.88"
        assert verdict["pass_range_status"] == "feasible"  # noqa: S105 - 판정 상태값
        # 평탄이 필요점수(N=85)를 충족하고 산식 구간과 이어져 상한이 예정가격까지 넓어진다.
        assert verdict["pass_amount_high"] == 150_000_000
        assert verdict["pass_ratio_high"] == "1"  # noqa: S105 - 통과 비율 상한
        assert verdict["effective_amount_high"] == 150_000_000
        assert verdict["optimal_price_passes"] is True


# =============================================================================
# 4. 평탄 없는 규칙 불변 시험
# =============================================================================


class TestNoFlatRuleUnchanged:
    """평탄 데이터가 없는 규칙은 평탄 인자가 None 일 때 기존과 완전히 같다."""

    def test_traffic_rule_has_no_flat_zone(self) -> None:
        assert flat_zone_for("SERVC_QUAL_PRE_20250901_ATTACH_01", None) is None

    def test_calculate_price_score_unchanged_without_flat(self) -> None:
        baseline = calculate_price_score(
            bid_price=Decimal("450000000"),
            pred_price=Decimal("500000000"),
            base_rate=Decimal("0.88"),
            max_price_score=Decimal("30"),
            multiplier=Decimal("2"),
        )
        asserted = calculate_price_score(
            bid_price=Decimal("450000000"),
            pred_price=Decimal("500000000"),
            base_rate=Decimal("0.88"),
            max_price_score=Decimal("30"),
            multiplier=Decimal("2"),
            flat_ratio=None,
            flat_score=None,
        )
        assert asserted.score == baseline.score == Decimal("26.0000")

    def test_invert_pass_range_unchanged_without_flat_args(self) -> None:
        common: dict[str, Decimal] = {
            "pass_threshold": Decimal("95"),
            "non_price_score": Decimal("70"),
            "base_rate": Decimal("0.90"),
            "max_price_score": Decimal("30"),
            "multiplier": Decimal("2"),
            "pred_price": PRED,
        }
        baseline = invert_pass_bid_range(**common)
        asserted = invert_pass_bid_range(**common, flat_ratio=None, flat_score=None)
        assert asserted.status == baseline.status
        assert asserted.ratio_low == baseline.ratio_low
        assert asserted.ratio_high == baseline.ratio_high
        assert asserted.amount_high == baseline.amount_high
        assert asserted.reasons == ()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))

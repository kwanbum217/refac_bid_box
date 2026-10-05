"""
tests/test_flat_zone_rest.py

평탄 구간 반영의 잔여 세 가지를 고정합니다.

1. 하향 단절: flat_score 가 산식(flat_ratio) 대입값보다 낮게 잘린 합성 데이터에서
   invert_pass_bid_range 가 flat_ratio 위쪽 산식 구간을 잘라내는지, 실제 점수를
   0.0001 간격으로 계산해 대조합니다.
2. 규모 구간 대체: /predictions 는 추정가격이 없으면 기초금액으로 규모 구간을
   고르므로 /evaluations(사용자 입력 추정가격 기준)와 다른 평탄 구간을 고를 수
   있음을 TestClient 끝단에서 고정합니다. predictions.py 는 수정하지 않습니다.
3. 세종 SW·육상운송 평탄: mock 없이 TestClient 로 평가 API 를 호출해 평탄 비율·점수와
   평탄 위쪽 투찰률의 점수를 확인합니다.

평탄 데이터가 없거나 연속인 경우 결과가 기존과 같은지도 함께 고정합니다.
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.app.api.v1.evaluations import require_current_user
from src.app.core.timeutil import utcnow
from src.app.main import app
from src.app.models.bids import BidAnnouncement
from src.app.models.demand_institutions import G2BDemandInstitution
from src.app.services.evaluation_scoring import calculate_price_score
from src.app.services.price_score_verification import invert_pass_bid_range
from src.ml.model_registry import PredictionOutcome

PRED = Decimal("100000000")
PREDICT_URL = "/api/v1/predictions/predict-price"
ANALYZE_URL = "/api/v1/evaluations/analyze"


# =============================================================================
# 1. 평탄 하향 절단 합성 시험
# =============================================================================


def _downward_args() -> dict[str, Decimal]:
    """flat_score 24 가 산식 대입값(25)보다 낮은 합성 입력.

    B 30, k 2, 기준 0.90, N 25 -> 허용차 0.025 로 산식 구간은 [0.875, 0.925] 다.
    평탄 시작 0.92 는 이 구간 안이지만, 그 위에서는 점수가 24 로 떨어져 통과하지 못한다.
    """
    return {
        "pass_threshold": Decimal("95"),  # T
        "non_price_score": Decimal("70"),  # Q -> N = 25
        "base_rate": Decimal("0.90"),
        "max_price_score": Decimal("30"),  # B
        "multiplier": Decimal("2"),  # k
        "pred_price": PRED,
        "flat_ratio": Decimal("0.92"),
        "flat_score": Decimal("24"),
    }


def _downward_score_at(ratio: str) -> Decimal:
    bid = (PRED * Decimal(ratio)).quantize(Decimal("1"))
    return calculate_price_score(
        bid_price=bid,
        pred_price=PRED,
        base_rate=Decimal("0.90"),
        max_price_score=Decimal("30"),
        multiplier=Decimal("2"),
        flat_ratio=Decimal("0.92"),
        flat_score=Decimal("24"),
    ).score


class TestInvertPassBidRangeDownwardCut:
    """평탄 고정 점수가 필요점수에 미달할 때 통과 상한을 평탄 시작 미만으로 자른다."""

    def test_upper_bound_is_cut_below_flat_ratio(self) -> None:
        result = invert_pass_bid_range(**_downward_args())
        assert result.status == "feasible"
        assert result.required_price_score == Decimal("25")
        assert result.ratio_low == Decimal("0.875")
        # 산식 상한 0.925 가 아니라 평탄 시작 0.92 까지 자른다.
        assert result.ratio_high == Decimal("0.92")
        assert result.ratio_grid_low == Decimal("0.8750")
        # x >= 0.92 는 평탄으로 점수가 떨어지므로 격자 상한은 0.9199 다.
        assert result.ratio_grid_high == Decimal("0.9199")
        assert result.amount_low == Decimal("87495000")
        assert result.amount_high == Decimal("91994999")
        assert any("잘랐습니다" in reason for reason in result.reasons)

    def test_sampled_scores_match_reported_interval(self) -> None:
        result = invert_pass_bid_range(**_downward_args())
        n = result.required_price_score

        # 보고한 통과 구간 안쪽은 0.0001 간격 전부 통과한다.
        x = Decimal("0.8750")
        while x <= Decimal("0.9199"):
            assert _downward_score_at(str(x)) >= n, x
            x += Decimal("0.0001")

        # 평탄 시작(0.92)부터는 고정 점수 24 로 떨어져 전부 미통과다.
        x = Decimal("0.9200")
        while x <= Decimal("0.9250"):
            assert _downward_score_at(str(x)) < n, x
            x += Decimal("0.0001")

    def test_no_cut_when_algebra_upper_below_flat_ratio(self) -> None:
        # 산식 상한 0.925 가 평탄 시작 0.93 보다 아래면 자를 것이 없다.
        result = invert_pass_bid_range(
            pass_threshold=Decimal("95"),
            non_price_score=Decimal("70"),
            base_rate=Decimal("0.90"),
            max_price_score=Decimal("30"),
            multiplier=Decimal("2"),
            pred_price=PRED,
            flat_ratio=Decimal("0.93"),
            flat_score=Decimal("24"),
        )
        assert result.ratio_high == Decimal("0.925")
        assert result.ratio_grid_high == Decimal("0.9250")
        assert not any("잘랐습니다" in reason for reason in result.reasons)

    def test_k_zero_range_is_cut_below_flat_ratio(self) -> None:
        # k=0 이면 x < flat_ratio 에서 P=B 로 고정되지만, 그 위는 평탄 고정 점수다.
        result = invert_pass_bid_range(
            pass_threshold=Decimal("95"),
            non_price_score=Decimal("70"),
            base_rate=Decimal("0.90"),
            max_price_score=Decimal("30"),
            multiplier=Decimal("0"),
            pred_price=PRED,
            flat_ratio=Decimal("0.92"),
            flat_score=Decimal("24"),
        )
        assert result.ratio_low == Decimal("0")
        assert result.ratio_high == Decimal("0.92")
        assert result.ratio_grid_high == Decimal("0.9199")
        assert result.amount_low == Decimal("0")
        assert result.amount_high == Decimal("91994999")


class TestFlatZoneInvariants:
    """평탄 데이터가 없거나 연속인 경우 결과가 기존과 같다."""

    def test_no_flat_args_matches_baseline(self) -> None:
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
        for attr in (
            "status",
            "ratio_low",
            "ratio_high",
            "ratio_grid_low",
            "ratio_grid_high",
            "amount_low",
            "amount_high",
            "reasons",
        ):
            assert getattr(asserted, attr) == getattr(baseline, attr), attr

    def test_contiguous_flat_still_extends_upper_bound(self) -> None:
        # 평탄 26 이 N 25 를 충족하고 산식 구간과 이어지면 상한이 1 까지 넓어진다.
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
        assert not any("잘랐습니다" in reason for reason in result.reasons)


# =============================================================================
# 2. /predictions 규모 구간 대체 시험 (TestClient)
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


def _create_local_bid(
    db,
    *,
    institution_name: str,
    presmpt_prce: int | None,
    budget_amount: int | None = None,
) -> BidAnnouncement:
    """시·도 수요기관과 지방계약 공고를 만들어 LOCAL 규칙 판별 경로를 엽니다.

    budget_amount 를 주면 raw_data 의 기초금액(bdgtAmt)으로만 남고 presmpt_prce 는 비워
    추정가격 부재를 재현합니다. 경상남도는 일반 별표 하나만 있어 세부유형 선택이 없다.
    """
    db.add(
        G2BDemandInstitution(
            dminstt_cd="1234",
            dminstt_nm=f"{institution_name} 본청",
            jrsdctn_div_nm="지방자치단체",
            rgn_cd="28000",
            rgn_nm=f"{institution_name} 남구",
            toplvl_instt_cd="6270000",
            toplvl_instt_nm=institution_name,
            raw_json={},
        )
    )
    db.commit()
    raw: dict[str, Any] = {
        "prearngPrceDcsnMthdNm": "복수예가",
        "sucsfbidMthdNm": "용역 적격심사",
        "sucsfbidLwltRate": "87.995",
        "srvceDivNm": "일반용역",
        "cntrctCnclsMthdNm": "지방자치단체 제한경쟁",
        "dminsttCd": "1234",
        "totPrdprcNum": "12",
        "drwtPrdprcNum": "3",
    }
    if budget_amount is not None:
        raw["bdgtAmt"] = budget_amount
    bid = BidAnnouncement(
        bid_ntce_nm="평탄 잔여 시험 공고",
        bid_ntce_no="FLAT-REST-001",
        bid_ntce_ord="000",
        ntce_instt_nm="테스트 공고기관",
        dminstt_nm=f"{institution_name} 본청",
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


@pytest.fixture
def as_user():
    def _set_user(user_id: int) -> None:
        app.dependency_overrides[require_current_user] = lambda: SimpleNamespace(id=user_id)

    yield _set_user
    app.dependency_overrides.pop(require_current_user, None)


class TestPredictionsBandSubstitution:
    """추정가격이 없을 때 /predictions 는 기초금액으로 규모 구간을 대체하므로
    /evaluations(사용자 입력 추정가격 기준)와 평탄 구간이 달라질 수 있음을 고정한다."""

    def test_predictions_uses_base_amount_band_while_evaluations_uses_user_price(
        self, client, isolated_db, as_user
    ) -> None:
        # 기초금액 6억은 10억원 미만 구간(평탄 90.5%/45),
        # 사용자 입력 추정가격 1.5억은 2억원 미만 구간(평탄 88.25%/85)이다.
        bid = _create_local_bid(
            isolated_db,
            institution_name="경상남도",
            presmpt_prce=None,
            budget_amount=600_000_000,
        )
        candidate = 570_000_000  # 6억 * 0.95, 두 평탄 시작 비율 위
        with (
            patch(
                "src.app.api.v1.predictions.predict_optimal_price_with_provenance",
                return_value=_outcome(0.95),
            ),
            patch("src.app.api.v1.predictions.predict_interval", return_value=(90.0, 99.0, 0.9)),
            patch("src.app.api.v1.predictions.ModelRegistry.get_model", return_value=_wrapper()),
        ):
            pred_response = client.post(
                PREDICT_URL,
                json={
                    "bid_id": bid.id,
                    "user_price": "0",
                    "max_price_score": 90,
                    "multiplier": 20,
                    "pass_threshold": 95,
                    "non_price_score": 55,
                },
            )
            as_user(10)
            eval_response = client.post(
                ANALYZE_URL,
                json={
                    "bid_id": bid.id,
                    "candidate_bid_amount": candidate,
                    "qualification_input": {
                        "disqualification": False,
                        "manual_non_price_score": 55.0,
                        "estimated_price": 150_000_000,
                        "local_service_type": "GENERAL",
                    },
                },
            )

        assert pred_response.status_code == 200, pred_response.text
        assert eval_response.status_code == 200, eval_response.text

        pred = pred_response.json()
        pred_verdict = pred["score_verdict"]
        assert pred["optimal_price"] == 570_000_000
        assert pred_verdict["verifiable"] is True
        # 기초금액 6억 구간의 평탄(45)이 적용되어 추천가 점수가 45 로 고정된다.
        # /evaluations 가 고른 1.5억 구간의 평탄(85)이었다면 85 가 나온다.
        assert pred_verdict["optimal_price_score"] == "45"

        body = eval_response.json()
        assert body["status"] == "success", body.get("blocked_reason")
        assert body["rule_id"] == "SERVC_LOCAL_GN_20230105_ATTACH_01"
        table = body["score_table"]
        # 사용자 입력 추정가격 1.5억 구간의 평탄이 쓰인다.
        assert table["flat_ratio"] == "0.8825"
        assert table["flat_score"] == "85"
        base = next(row for row in body["scenario_results"] if row["scenario_name"] == "기준")
        assert base["price_score"] == pytest.approx(85.0)


# =============================================================================
# 3. 세종 SW·육상운송 평탄 API 끝단 시험 (mock 없음)
# =============================================================================

# (세부유형, rule_id, 추정가격, 평탄비율, 평탄점수). 세종 SW·육상운송은 중소기업간
# 경쟁제품 대상(_SME) 여부로 평탄 비율(95.5%/91%)과 고정 점수(55/45, 58/48)가 갈린다.
SEJONG_FLAT_CASES = [
    ("SW", "SERVC_LOCAL_SEJONG_20251201_ATTACH_03", 300_000_000, "0.955", "55"),
    ("SW", "SERVC_LOCAL_SEJONG_20251201_ATTACH_03", 600_000_000, "0.955", "45"),
    ("SW_SME", "SERVC_LOCAL_SEJONG_20251201_ATTACH_03_SME", 300_000_000, "0.91", "58"),
    ("SW_SME", "SERVC_LOCAL_SEJONG_20251201_ATTACH_03_SME", 600_000_000, "0.91", "48"),
    ("LAND_TRANSPORT", "SERVC_LOCAL_SEJONG_20251201_ATTACH_05", 300_000_000, "0.955", "55"),
    ("LAND_TRANSPORT", "SERVC_LOCAL_SEJONG_20251201_ATTACH_05", 600_000_000, "0.955", "45"),
    (
        "LAND_TRANSPORT_SME",
        "SERVC_LOCAL_SEJONG_20251201_ATTACH_05_SME",
        300_000_000,
        "0.91",
        "58",
    ),
    (
        "LAND_TRANSPORT_SME",
        "SERVC_LOCAL_SEJONG_20251201_ATTACH_05_SME",
        600_000_000,
        "0.91",
        "48",
    ),
]


class TestSejongFlatZoneApi:
    """세종 소프트웨어·육상운송 평탄을 규칙 판별 mock 없이 응답 끝단에서 확인한다."""

    @pytest.mark.parametrize(
        ("service_type", "rule_id", "presmpt_prce", "flat_ratio", "flat_score"),
        SEJONG_FLAT_CASES,
    )
    def test_sejong_flat_zone_applied_in_response(
        self,
        client,
        isolated_db,
        as_user,
        service_type: str,
        rule_id: str,
        presmpt_prce: int,
        flat_ratio: str,
        flat_score: str,
    ) -> None:
        as_user(10)
        bid = _create_local_bid(
            isolated_db,
            institution_name="세종특별자치시",
            presmpt_prce=presmpt_prce,
        )
        ratio = Decimal("0.98")
        assert ratio > Decimal(flat_ratio)
        candidate = int((Decimal(presmpt_prce) * ratio).quantize(Decimal("1")))
        response = client.post(
            ANALYZE_URL,
            json={
                "bid_id": bid.id,
                "candidate_bid_amount": candidate,
                "qualification_input": {
                    "disqualification": False,
                    "manual_non_price_score": 60.0,
                    "local_service_type": service_type,
                },
            },
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "success", body.get("blocked_reason")
        assert body["rule_id"] == rule_id

        table = body["score_table"]
        assert table["flat_ratio"] == flat_ratio
        assert table["flat_score"] == flat_score

        base = next(row for row in body["scenario_results"] if row["scenario_name"] == "기준")
        assert base["bid_to_estimated_ratio"] == pytest.approx(float(ratio))
        # 평탄이 없으면 이 지점의 산식값은 음수까지 내려가므로 산식값과 평탄점수가 갈린다.
        b = Decimal(table["max_price_score"])
        k = Decimal(table["multiplier"])
        base_rate = Decimal(str(body["base_rate"])) / Decimal("100")
        algebraic = b - k * abs(base_rate - ratio) * Decimal("100")
        assert algebraic < Decimal(flat_score)
        assert base["price_score"] == pytest.approx(float(Decimal(flat_score)))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))

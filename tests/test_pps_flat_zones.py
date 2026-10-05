"""
tests/test_pps_flat_zones.py

조달청 PRE/POST 별표 평탄 구간이 데이터·점수·API 끝단까지 반영되는지 고정합니다.

1. 데이터 불변식: 등록된 평탄 전부가 근거 문서 source 를 가지고, 평탄 비율이 기준비율보다
   크며, 평탄 점수가 B·k·기준비율 산식 대입값과 일치합니다. 두 축 키가 규칙의 조건부 선언과
   맞물리는지, 넣지 않기로 한 규칙(별표 6 보험·일반 띠·기술용역)에 데이터가 없는지도 봅니다.
2. 대표 규칙 점수·통과 구간: 평탄 위쪽 투찰률은 flat_score 로 고정되고 아래쪽은 기존 산식
   그대로이며, 통과 구간 상한이 의도대로 넓어지거나 잘립니다.
3. API 끝단: 규칙 판별을 mock 없이 실제 /evaluations/analyze 를 호출해 score_table 의
   flat_ratio·flat_score 노출과 시나리오 가격점수 고정을 확인합니다.
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest

from src.app.api.v1 import evaluations
from src.app.api.v1.evaluations import require_current_user
from src.app.api.v1.predictions import _flat_zone_for_bid
from src.app.core.timeutil import utcnow
from src.app.main import app
from src.app.models.bids import BidAnnouncement
from src.app.schemas.predictions import PredictPriceResponse
from src.app.services.evaluation_flat_zones import (
    FlatZone,
    pps_axis_side,
    pps_flat_zone_entries,
    pps_flat_zone_for,
)
from src.app.services.evaluation_rules import (
    POST_20260526_RULES,
    POST_20260727_RULES,
    PRE_20230501_RULES,
    PRE_20250901_RULES,
)
from src.app.services.evaluation_scoring import PriceScoreResult, calculate_price_score
from src.app.services.price_score_verification import invert_pass_bid_range

ANALYZE_URL = "/api/v1/evaluations/analyze"
PRED = Decimal("100000000")

PPS_RULES = (
    *PRE_20230501_RULES,
    *PRE_20250901_RULES,
    *POST_20260526_RULES,
    *POST_20260727_RULES,
)
_RULE_BY_ID = {rule.rule_id: rule for rule in PPS_RULES}


def _rule(rule_id: str):
    return _RULE_BY_ID[rule_id]


def _zone(
    rule_id: str, above_500m: bool | None = None, above_notice: bool | None = None
) -> FlatZone:
    zone = pps_flat_zone_for(rule_id, above_500m=above_500m, above_notice=above_notice)
    assert zone is not None, rule_id
    return zone


# =============================================================================
# 1. 데이터 불변식
# =============================================================================


class TestPpsFlatZoneData:
    """평탄 데이터 자체의 출처·형태·산식 일치 검증."""

    def test_every_entry_has_document_source(self) -> None:
        entries = pps_flat_zone_entries()
        assert entries
        for rule_id, _key, zone in entries:
            assert zone.source.strip(), rule_id
            assert "docs/analysis/" in zone.source, rule_id
            assert zone.flat_ratio > Decimal("0"), rule_id

    def test_flat_ratio_is_above_base_rate(self) -> None:
        for rule_id, _key, zone in pps_flat_zone_entries():
            rule = _rule(rule_id)
            assert zone.flat_ratio > rule.base_rate, (rule_id, zone.flat_ratio)

    def test_stored_score_matches_formula(self) -> None:
        # flat_score = B - k x (flat_ratio - 기준비율) x 100 대입값과 0.01점 이내로 같아야 합니다.
        # 별표9(수요기관 지정형)는 B 가 공고 입력값이라 저장하지 않고 조회 시 산출합니다.
        for rule_id, (above_500m, above_notice), zone in pps_flat_zone_entries():
            if zone.flat_score is None:
                continue
            rule = _rule(rule_id)
            b = (
                rule.max_price_score_by_500m[1 if above_500m else 0]
                if above_500m is not None
                else rule.max_price_score
            )
            k = (
                rule.multiplier_by_notice[1 if above_notice else 0]
                if above_notice is not None
                else rule.multiplier
            )
            assert b is not None, rule_id
            assert k is not None, rule_id
            expected = b - k * (zone.flat_ratio - rule.base_rate) * Decimal("100")
            assert abs(expected - zone.flat_score) <= Decimal("0.01"), (rule_id, zone.flat_score)

    def test_key_shape_matches_conditional_axes(self) -> None:
        # 등록 키의 두 축 해당 여부는 규칙의 조건부 선언(max_price_score_by_500m·
        # multiplier_by_notice)과 정확히 맞물려야 합니다.
        for rule_id, (above_500m, above_notice), _zone in pps_flat_zone_entries():
            rule = _rule(rule_id)
            assert rule.contract_regime is None, rule_id
            assert (rule.max_price_score_by_500m is not None) == (above_500m is not None), rule_id
            assert (rule.multiplier_by_notice is not None) == (above_notice is not None), rule_id

    def test_excluded_rules_have_no_flat_data(self) -> None:
        # 별표 6 보험(ATTACH_02), 일반 띠 3개, 기술용역은 평탄 문장이 없거나 귀속 미확인이라
        # 데이터를 넣지 않습니다.
        excluded = [
            ("SERVC_QUAL_PRE_20230501_ATTACH_02", True, None),
            ("SERVC_QUAL_PRE_20250901_ATTACH_02", False, None),
            ("SERVC_QUAL_POST_20260526_ATTACH_02", True, None),
            ("SERVC_QUAL_POST_20260526_ATTACH_12", None, None),
            ("SERVC_QUAL_POST_20260526_ATTACH_13", None, None),
            ("SERVC_QUAL_POST_20260526_ATTACH_14", None, None),
            ("SERVC_TECH_QUAL_ANNOUNCEMENT_LWLT", None, None),
        ]
        for rule_id, above_500m, above_notice in excluded:
            zone = pps_flat_zone_for(rule_id, above_500m=above_500m, above_notice=above_notice)
            assert zone is None, rule_id

    def test_unknown_rule_and_unknown_key_have_no_zone(self) -> None:
        assert (
            pps_flat_zone_for(
                "SERVC_LOCAL_INCHEON_20251224_ATTACH_01", above_500m=False, above_notice=None
            )
            is None
        )
        # 시설분야(ATTACH_01)는 k 가 조건이 아니므로 고시 축 키를 주면 맞지 않습니다.
        assert (
            pps_flat_zone_for(
                "SERVC_QUAL_PRE_20250901_ATTACH_01", above_500m=False, above_notice=False
            )
            is None
        )

    def test_representative_printed_values(self) -> None:
        cases = [
            ("SERVC_QUAL_PRE_20250901_ATTACH_01", True, None, "0.94", "45"),
            ("SERVC_QUAL_PRE_20250901_ATTACH_01", False, None, "0.94", "55"),
            ("SERVC_QUAL_PRE_20250901_ATTACH_05", True, True, "0.955", "45"),
            ("SERVC_QUAL_PRE_20250901_ATTACH_05", False, False, "0.9175", "55"),
            ("SERVC_QUAL_PRE_20250901_ATTACH_06", None, None, "0.9175", "55"),
            ("SERVC_QUAL_PRE_20250901_ATTACH_16", None, True, "0.955", "55"),
            ("SERVC_QUAL_POST_20260526_ATTACH_05", True, True, "0.975", "45"),
            ("SERVC_QUAL_POST_20260526_ATTACH_05", False, False, "0.9375", "55"),
            ("SERVC_QUAL_POST_20260526_ATTACH_07", False, None, "0.975", "55"),
            ("SERVC_QUAL_POST_20260727_ATTACH_03", True, None, "0.96", "48"),
            ("SERVC_QUAL_POST_20260727_ATTACH_04", False, None, "0.96", "58"),
        ]
        for rule_id, above_500m, above_notice, ratio, score in cases:
            zone = _zone(rule_id, above_500m, above_notice)
            assert zone.flat_ratio == Decimal(ratio), rule_id
            assert zone.flat_score == Decimal(score), rule_id


class TestPpsAxisSide:
    """조건부 축 값이 어느 쪽(이상=True)인지 판정."""

    def test_maps_declared_values_to_sides(self) -> None:
        assert pps_axis_side((Decimal("70"), Decimal("60")), Decimal("60")) is True
        assert pps_axis_side((Decimal("70"), Decimal("60")), Decimal("70")) is False
        assert pps_axis_side((Decimal("4"), Decimal("2")), Decimal("2")) is True
        assert pps_axis_side((Decimal("4"), Decimal("2")), Decimal("4")) is False

    def test_unconditional_or_unknown_value_is_none(self) -> None:
        assert pps_axis_side(None, Decimal("60")) is None
        assert pps_axis_side((Decimal("70"), Decimal("60")), None) is None
        # 선언 어느 쪽과도 다른 값이면 평탄을 적용하지 않습니다.
        assert pps_axis_side((Decimal("70"), Decimal("60")), Decimal("65")) is None


class TestPpsManualScoreZone:
    """별표9 수요기관 지정형은 B 가 공고 입력값이라 평탄 점수를 조회 시 산출합니다."""

    RULE_ID = "SERVC_QUAL_PRE_20250901_ATTACH_17"

    def test_derived_score_tracks_manual_b(self) -> None:
        # 고시 미만은 k=4·91.75%, 고시 이상은 k=2·95.5% 이고 두 쪽 모두 감점폭이 15 입니다.
        cases = [
            ("4", False, "0.9175"),
            ("2", True, "0.955"),
        ]
        for multiplier, above_notice, ratio in cases:
            for b, expected in (("60", "45"), ("65", "50"), ("70", "55")):
                zone = pps_flat_zone_for(
                    self.RULE_ID,
                    above_500m=None,
                    above_notice=above_notice,
                    max_price_score=Decimal(b),
                    multiplier=Decimal(multiplier),
                    base_rate=Decimal("0.88"),
                )
                assert zone is not None
                assert zone.flat_ratio == Decimal(ratio)
                assert zone.flat_score == Decimal(expected), (b, multiplier)

    def test_derived_score_requires_b_and_k(self) -> None:
        assert pps_flat_zone_for(self.RULE_ID, above_500m=None, above_notice=False) is None
        assert (
            pps_flat_zone_for(
                self.RULE_ID,
                above_500m=None,
                above_notice=False,
                max_price_score=Decimal("60"),
            )
            is None
        )


# =============================================================================
# 2. 대표 규칙 점수·통과 구간
# =============================================================================


def _score_at(
    rule_id: str,
    above_500m: bool | None,
    above_notice: bool | None,
    x: str,
    *,
    b: str,
    k: str,
    base: str,
) -> PriceScoreResult:
    zone = _zone(rule_id, above_500m, above_notice)
    bid = (PRED * Decimal(x)).quantize(Decimal("1"))
    return calculate_price_score(
        bid_price=bid,
        pred_price=PRED,
        base_rate=Decimal(base),
        max_price_score=Decimal(b),
        multiplier=Decimal(k),
        flat_ratio=zone.flat_ratio,
        flat_score=zone.flat_score,
    )


class TestPpsFlatZoneScoring:
    """개정 후 SW 비대상 5억 미만·고시 미만 구간(B 70, k 4, 기준 90, 평탄 93.75% -> 55)."""

    RULE_ID = "SERVC_QUAL_POST_20260526_ATTACH_05"

    def test_score_pinned_above_flat_ratio(self) -> None:
        zone = _zone(self.RULE_ID, above_500m=False, above_notice=False)
        assert zone.flat_ratio == Decimal("0.9375")
        assert zone.flat_score == Decimal("55")
        at_ratio = _score_at(self.RULE_ID, False, False, "0.9375", b="70", k="4", base="0.90")
        assert at_ratio.raw_score == Decimal("55")
        assert at_ratio.score == Decimal("55")
        above = _score_at(self.RULE_ID, False, False, "0.98", b="70", k="4", base="0.90")
        assert above.raw_score < zone.flat_score
        assert above.score == Decimal("55")
        assert above.flat_ratio == zone.flat_ratio
        assert above.flat_score == zone.flat_score

    def test_score_below_flat_ratio_is_unchanged_formula(self) -> None:
        below = _score_at(self.RULE_ID, False, False, "0.93", b="70", k="4", base="0.90")
        assert below.score == below.raw_score == Decimal("58")
        assert below.flat_ratio is None
        assert below.flat_score is None

    def test_pass_range_extends_when_flat_meets_requirement(self) -> None:
        # T 85, Q 45 -> N 40. 평탄 55 가 N 을 충족하고 산식 구간과 이어져 상한이 1 까지 넓어집니다.
        zone = _zone(self.RULE_ID, above_500m=False, above_notice=False)
        result = invert_pass_bid_range(
            pass_threshold=Decimal("85"),
            non_price_score=Decimal("45"),
            base_rate=Decimal("0.90"),
            max_price_score=Decimal("70"),
            multiplier=Decimal("4"),
            pred_price=PRED,
            flat_ratio=zone.flat_ratio,
            flat_score=zone.flat_score,
        )
        assert result.is_feasible is True
        assert result.ratio_high == Decimal("1")
        assert result.ratio_grid_high == Decimal("1.0000")

    def test_pass_range_not_extended_when_flat_below_requirement(self) -> None:
        # T 96, Q 40 -> N 56 이면 평탄 55 로는 부족하고 산식 상한도 평탄 시작 아래에서 끝납니다.
        zone = _zone(self.RULE_ID, above_500m=False, above_notice=False)
        result = invert_pass_bid_range(
            pass_threshold=Decimal("96"),
            non_price_score=Decimal("40"),
            base_rate=Decimal("0.90"),
            max_price_score=Decimal("70"),
            multiplier=Decimal("4"),
            pred_price=PRED,
            flat_ratio=zone.flat_ratio,
            flat_score=zone.flat_score,
        )
        assert result.ratio_high == Decimal("0.935")
        assert result.ratio_grid_high == Decimal("0.9350")

    def test_pass_range_below_flat_is_same_without_flat_args(self) -> None:
        common = {
            "pass_threshold": Decimal("96"),
            "non_price_score": Decimal("40"),
            "base_rate": Decimal("0.90"),
            "max_price_score": Decimal("70"),
            "multiplier": Decimal("4"),
            "pred_price": PRED,
        }
        zone = _zone(self.RULE_ID, above_500m=False, above_notice=False)
        with_flat = invert_pass_bid_range(
            **common, flat_ratio=zone.flat_ratio, flat_score=zone.flat_score
        )
        without = invert_pass_bid_range(**common)
        assert with_flat.ratio_low == without.ratio_low
        assert with_flat.amount_low == without.amount_low


# =============================================================================
# 3. API 끝단 (규칙 판별 mock 없음)
# =============================================================================


@pytest.fixture
def as_user():
    def _set_user(user_id: int) -> None:
        app.dependency_overrides[require_current_user] = lambda: SimpleNamespace(id=user_id)

    yield _set_user
    app.dependency_overrides.pop(require_current_user, None)


@pytest.fixture(autouse=True)
def auto_stub_prediction(monkeypatch):
    """실물 예측 모델 대신 고정 응답을 씁니다. 규칙 판별·점수 계산은 실제 코드가 수행합니다."""

    def _fake_predict(payload, request, db):
        return PredictPriceResponse(
            status="success",
            optimal_price=400_000_000,
            prediction_rate=88.0,
            model_name="테스트 모델",
            model_id=payload.selected_model or "default-model",
            requested_model=payload.selected_model or "default-model",
            fallback_used=False,
            fallback_reason=None,
            message="테스트용 예측 대역 응답",
        )

    monkeypatch.setattr(evaluations, "predict_price_api", _fake_predict)


def _create_pps_bid(db, *, method_name: str, presmpt_prce: int, lwlt_rate: str) -> BidAnnouncement:
    """조달청 일반용역 적격심사 공고를 만들어 실제 규칙 판별 경로를 엽니다."""
    bid = BidAnnouncement(
        bid_ntce_nm="조달청 평탄 끝단 테스트 공고",
        bid_ntce_no="PPS-FLAT-ZONE-001",
        bid_ntce_ord="000",
        ntce_instt_nm="테스트 공고기관",
        dminstt_nm="테스트 수요기관",
        base_amount=presmpt_prce,
        presmpt_prce=presmpt_prce,
        bid_ntce_dt=utcnow(),
        bid_clse_dt=utcnow(),
        openg_dt=utcnow(),
        category="Servc",
        raw_data={
            "prearngPrceDcsnMthdNm": "복수예가",
            "sucsfbidMthdNm": method_name,
            "sucsfbidLwltRate": lwlt_rate,
            "srvceDivNm": "일반용역",
            "totPrdprcNum": "12",
            "drwtPrdprcNum": "3",
        },
    )
    db.add(bid)
    db.commit()
    db.refresh(bid)
    return bid


# (rule_id, 낙찰방법명, 추정가격, 하한율, 투찰금액, 평탄비율, 평탄점수)
PPS_API_CASES = [
    (
        "SERVC_QUAL_POST_20260526_ATTACH_01",
        "시설분야용역 적격심사 추정가격 5억원 미만",
        400_000_000,
        "89.995",
        388_000_000,
        "0.96",
        "55",
    ),
    (
        "SERVC_QUAL_POST_20260526_ATTACH_05",
        "소프트웨어용역(중소기업자간 경쟁제품 비대상) 추정가격 고시금액미만",
        48_900_000,
        "86.245",
        47_433_000,
        "0.9375",
        "55",
    ),
]


class TestPpsFlatZoneEndToEndApi:
    """TestClient 로 평가 API 를 호출해 평탄이 응답까지 이어지는지 확인합니다."""

    @pytest.mark.parametrize(
        (
            "rule_id",
            "method_name",
            "presmpt_prce",
            "lwlt_rate",
            "candidate",
            "flat_ratio",
            "flat_score",
        ),
        PPS_API_CASES,
    )
    def test_pps_flat_zone_applied_in_response(
        self,
        client,
        isolated_db,
        as_user,
        rule_id: str,
        method_name: str,
        presmpt_prce: int,
        lwlt_rate: str,
        candidate: int,
        flat_ratio: str,
        flat_score: str,
    ) -> None:
        as_user(10)
        bid = _create_pps_bid(
            isolated_db, method_name=method_name, presmpt_prce=presmpt_prce, lwlt_rate=lwlt_rate
        )
        ratio = Decimal("0.97")
        assert ratio > Decimal(flat_ratio)
        response = client.post(
            ANALYZE_URL,
            json={
                "bid_id": bid.id,
                "candidate_bid_amount": candidate,
                "qualification_input": {"disqualification": False, "quant_items": {}},
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
        # 이 지점의 산식값은 평탄점수보다 낮으므로, 평탄이 없으면 응답 점수가 산식값이 됩니다.
        b = Decimal(table["max_price_score"])
        k = Decimal(table["multiplier"])
        base_rate = Decimal(str(body["base_rate"])) / Decimal("100")
        algebraic = b - k * abs(base_rate - ratio) * Decimal("100")
        assert algebraic < Decimal(flat_score)
        assert base["price_score"] == pytest.approx(float(Decimal(flat_score)))

    def test_predictions_lookup_uses_effective_axes(self, isolated_db) -> None:
        # /predictions 의 평탄 조회도 실제 적용한 B·k 값의 두 축으로 같은 구간을 고릅니다.
        bid = _create_pps_bid(
            isolated_db,
            method_name="소프트웨어용역(중소기업자간 경쟁제품 비대상) 추정가격 고시금액미만",
            presmpt_prce=48_900_000,
            lwlt_rate="86.245",
        )
        rule = _rule("SERVC_QUAL_POST_20260526_ATTACH_05")
        zone = _flat_zone_for_bid(bid, rule, max_price_score=Decimal("70"), multiplier=Decimal("4"))
        assert zone is not None
        assert zone.flat_ratio == Decimal("0.9375")
        assert zone.flat_score == Decimal("55")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))

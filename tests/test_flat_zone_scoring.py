"""
tests/test_flat_zone_scoring.py

적격심사 별표 원문의 평탄 구간 규정이 가격점수 계산·통과 구간 역산·보정 탐색에
반영되는지 검증합니다.

핵심 계약:
1. 평탄 데이터가 있으면 x >= flat_ratio 에서 점수가 flat_score 로 고정된다.
2. 평탄 데이터가 없으면(조달청 규칙 등) 결과가 기존과 완전히 같다.
3. 통과 구간 상한은 flat_score 가 필요점수를 충족할 때 예정가격(비율 1)까지 넓어진다.
4. 모든 평탄 데이터에 원문 출처가 있다.
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest

from src.app.api.v1 import evaluations
from src.app.api.v1.evaluations import _rule_score_table_payload, require_current_user
from src.app.core.timeutil import utcnow
from src.app.main import app
from src.app.models.bids import BidAnnouncement
from src.app.models.demand_institutions import G2BDemandInstitution
from src.app.schemas.predictions import PredictPriceResponse
from src.app.services.evaluation_flat_zones import (
    FlatZone,
    flat_zone_entries,
    flat_zone_for,
    pps_flat_zone_for,
)
from src.app.services.evaluation_rules import LOCAL_RULES, resolve_score_params
from src.app.services.evaluation_scoring import (
    calculate_price_score,
    resolve_price_compensation,
)
from src.app.services.price_score_verification import invert_pass_bid_range

PRED = Decimal("10000")
ANALYZE_URL = "/api/v1/evaluations/analyze"


def _rule_by_id(rule_id: str):
    return next(rule for rule in LOCAL_RULES if rule.rule_id == rule_id)


def _scored(x: str, zone: FlatZone | None, *, base: str = "0.88", b: str = "90", k: str = "20"):
    bid = (PRED * Decimal(x)).quantize(Decimal("1"))
    return calculate_price_score(
        bid_price=bid,
        pred_price=PRED,
        base_rate=Decimal(base),
        max_price_score=Decimal(b),
        multiplier=Decimal(k),
        flat_ratio=zone.flat_ratio if zone is not None else None,
        flat_score=zone.flat_score if zone is not None else None,
    )


class TestFlatZoneData:
    """평탄 데이터 자체의 출처·형태 검증."""

    def test_every_entry_has_source_citation(self) -> None:
        entries = flat_zone_entries()
        assert entries
        for rule_id, _upper, zone in entries:
            assert zone.source.strip(), rule_id
            assert "docs/analysis/" in zone.source, rule_id
            assert zone.flat_ratio > Decimal("0")
            assert zone.flat_score >= Decimal("0")

    def test_flat_ratio_is_above_base_rate(self) -> None:
        for rule_id, _upper, zone in flat_zone_entries():
            assert zone.flat_ratio > Decimal("0.88"), (rule_id, zone.flat_ratio)

    def test_major_sido_rules_have_flat_data(self) -> None:
        cases = {
            "SERVC_LOCAL_INCHEON_20251224_ATTACH_01": Decimal("200000000"),
            "SERVC_LOCAL_JEJU_20240101_ATTACH_01": Decimal("200000000"),
            "SERVC_LOCAL_GANGWON_20230611_ATTACH_01": Decimal("200000000"),
            "SERVC_LOCAL_ULSAN_20220810_ATTACH_01": Decimal("200000000"),
            "SERVC_LOCAL_CB_20231020_ATTACH_01": Decimal("200000000"),
            "SERVC_LOCAL_GN_20230105_ATTACH_01": Decimal("200000000"),
            "SERVC_LOCAL_JNGJ_20260716_ATTACH_06": Decimal("200000000"),
            "SERVC_LOCAL_GG_20250808_ATTACH_1_6": Decimal("200000000"),
        }
        for rule_id, upper in cases.items():
            zone = flat_zone_for(rule_id, upper)
            assert zone is not None, rule_id

    def test_traffic_rule_has_no_flat_data(self) -> None:
        # 조달청 별표 6 보험(ATTACH_02)은 원문에 평탄 문장이 없어 두 축 어느 쪽으로도 없습니다.
        assert (
            pps_flat_zone_for(
                "SERVC_QUAL_PRE_20250901_ATTACH_02", above_500m=True, above_notice=None
            )
            is None
        )
        assert (
            pps_flat_zone_for(
                "SERVC_QUAL_POST_20260526_ATTACH_02", above_500m=False, above_notice=None
            )
            is None
        )

    def test_unknown_rule_has_no_flat_data(self) -> None:
        assert flat_zone_for("SERVC_LOCAL_UNKNOWN", None) is None

    def test_upper_bound_accepts_int_and_str(self) -> None:
        by_int = flat_zone_for("SERVC_LOCAL_INCHEON_20251224_ATTACH_01", 3000000000)
        by_str = flat_zone_for("SERVC_LOCAL_INCHEON_20251224_ATTACH_01", "3000000000")
        by_none = flat_zone_for("SERVC_LOCAL_INCHEON_20251224_ATTACH_01", None)
        assert by_int is not None
        assert by_str is not None
        assert by_int == by_str
        assert by_int.flat_ratio == Decimal("0.98")
        # 원문 평탄 단서는 30억원 미만 10억원 이상에만 걸려 30억원 이상 구간에는 평탄이 없다.
        assert by_none is None


class TestCalculatePriceScoreFlat:
    """평탄 반영 시 점수 고정 동작."""

    def test_incheon_under_2eok_flat_pins_at_85(self) -> None:
        # 인천 2억원 미만: B 90, k 20, 기준 88, 88.25% 이상 85점
        zone = flat_zone_for("SERVC_LOCAL_INCHEON_20251224_ATTACH_01", Decimal("200000000"))
        assert zone is not None
        assert zone.flat_ratio == Decimal("0.8825")
        assert zone.flat_score == Decimal("85")
        # x = 0.8825 는 산식값과 평탄값이 같다
        assert _scored("0.8825", zone).score == Decimal("85.000")
        # flat_ratio 위에서는 산식이 크게 낮아져도 85 로 고정
        assert _scored("0.90", zone).score == Decimal("85")
        assert _scored("0.95", zone).score == Decimal("85")
        # 평탄 적용 전 산식값은 raw_score 로 남는다
        assert _scored("0.90", zone).raw_score == Decimal("50.000")

    def test_flat_does_not_apply_below_ratio(self) -> None:
        zone = flat_zone_for("SERVC_LOCAL_INCHEON_20251224_ATTACH_01", Decimal("200000000"))
        assert zone is not None
        below = _scored("0.8824", zone)
        assert below.score == below.raw_score == Decimal("85.200")
        at_base = _scored("0.88", zone)
        assert at_base.score == Decimal("90.000")

    def test_full_range_beyond_flat_ratio_is_pinned(self) -> None:
        # x = 0.99, 1.00 도 85 로 고정
        zone = flat_zone_for("SERVC_LOCAL_INCHEON_20251224_ATTACH_01", Decimal("200000000"))
        assert zone is not None
        assert _scored("0.99", zone).score == Decimal("85")
        assert _scored("1.00", zone).score == Decimal("85")

    @pytest.mark.parametrize(
        ("rule_id", "upper", "ratio", "score"),
        [
            ("SERVC_LOCAL_GN_20230105_ATTACH_01", Decimal("200000000"), "0.8825", "85"),
            ("SERVC_LOCAL_JNGJ_20260716_ATTACH_06", Decimal("200000000"), "0.8825", "85"),
            ("SERVC_LOCAL_GG_20250808_ATTACH_1_6", Decimal("200000000"), "0.8825", "85"),
            ("SERVC_LOCAL_GB_20260108_ATTACH_01", Decimal("500000000"), "0.8825", "65"),
            ("SERVC_LOCAL_DAEGU_20260511_ATTACH_01", None, "0.8825", "45"),
        ],
    )
    def test_sido_printed_flat_scores(
        self, rule_id: str, upper: Decimal | None, ratio: str, score: str
    ) -> None:
        zone = flat_zone_for(rule_id, upper)
        assert zone is not None, rule_id
        assert zone.flat_ratio == Decimal(ratio), rule_id
        assert zone.flat_score == Decimal(score), rule_id

    def test_matches_naive_when_no_flat(self) -> None:
        zone = flat_zone_for("SERVC_LOCAL_INCHEON_20251224_ATTACH_01", Decimal("200000000"))
        assert zone is not None
        for x in ("0.8825", "0.90", "0.95"):
            with_flat = _scored(x, zone)
            without = _scored(x, None)
            if Decimal(x) >= zone.flat_ratio:
                assert without.score == without.raw_score
            assert with_flat.raw_score == without.raw_score


class TestScoreTablePayloadExposesFlat:
    """응답 score_table 이 평탄 필드를 노출하는지 검증."""

    def test_flat_fields_exposed_for_local_rule(self) -> None:
        rule = _rule_by_id("SERVC_LOCAL_INCHEON_20251224_ATTACH_01")
        resolution = resolve_score_params(rule, Decimal("150000000"), None, None)
        payload = _rule_score_table_payload(rule, [], [], resolution)
        assert payload.flat_ratio == "0.8825"
        assert payload.flat_score == "85"

    def test_flat_fields_null_when_no_flat_data(self) -> None:
        # 경기 별표 1-5(보험)는 원문에 평탄 문장이 없는 규칙이다.
        rule = _rule_by_id("SERVC_LOCAL_GG_20250808_ATTACH_1_5")
        resolution = resolve_score_params(rule, Decimal("300000000"), None, None)
        payload = _rule_score_table_payload(rule, [], [], resolution)
        assert payload.flat_ratio is None
        assert payload.flat_score is None

    def test_flat_fields_null_without_resolution(self) -> None:
        rule = _rule_by_id("SERVC_LOCAL_INCHEON_20251224_ATTACH_01")
        payload = _rule_score_table_payload(rule, [], [], None)
        assert payload.flat_ratio is None
        assert payload.flat_score is None


class TestTrafficRuleUnchanged:
    """평탄 데이터가 없는 규칙은 기존 동작과 완전히 같다."""

    def test_calculate_price_score_unchanged_without_flat_args(self) -> None:
        zone = flat_zone_for("SERVC_QUAL_PRE_20250901_ATTACH_01", None)
        assert zone is None
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
        assert baseline.score == asserted.score == Decimal("26.0000")
        assert asserted.flat_ratio is None
        assert asserted.flat_score is None

    def test_invert_pass_range_unchanged_without_flat(self) -> None:
        common = {
            "pass_threshold": Decimal("95"),
            "non_price_score": Decimal("10"),
            "base_rate": Decimal("0.88"),
            "max_price_score": Decimal("90"),
            "multiplier": Decimal("20"),
            "pred_price": Decimal("1000000000"),
        }
        baseline = invert_pass_bid_range(**common)
        asserted = invert_pass_bid_range(**common, flat_ratio=None, flat_score=None)
        assert baseline.ratio_high == asserted.ratio_high
        assert baseline.amount_high == asserted.amount_high


class TestInvertPassBidRangeFlat:
    """평탄이 통과 구간 상한을 넓히는지 검증."""

    def test_upper_extends_to_pred_price_when_flat_meets_requirement(self) -> None:
        # B 90, k 20, 기준 88, T 95, Q 10 -> N 85, 평탄 88.25% -> 85점 (N 충족)
        result = invert_pass_bid_range(
            pass_threshold=Decimal("95"),
            non_price_score=Decimal("10"),
            base_rate=Decimal("0.88"),
            max_price_score=Decimal("90"),
            multiplier=Decimal("20"),
            pred_price=Decimal("1000000000"),
            flat_ratio=Decimal("0.8825"),
            flat_score=Decimal("85"),
        )
        assert result.is_feasible is True
        assert result.ratio_high == Decimal("1")
        assert result.ratio_grid_high == Decimal("1.0000")
        assert result.amount_high == Decimal("1000000000")

    def test_upper_not_extended_when_flat_below_requirement(self) -> None:
        # 같은 조건에서 N 86 이면 평탄 85 로는 부족 -> 산식 허용 상한 유지
        result = invert_pass_bid_range(
            pass_threshold=Decimal("96"),
            non_price_score=Decimal("10"),
            base_rate=Decimal("0.88"),
            max_price_score=Decimal("90"),
            multiplier=Decimal("20"),
            pred_price=Decimal("1000000000"),
            flat_ratio=Decimal("0.8825"),
            flat_score=Decimal("85"),
        )
        assert result.ratio_high == Decimal("0.882")
        assert result.amount_high < Decimal("1000000000")

    def test_lower_bound_is_not_affected_by_flat(self) -> None:
        # 평탄은 기준비율 위쪽이므로 하한은 산식 허용차 그대로다
        with_flat = invert_pass_bid_range(
            pass_threshold=Decimal("95"),
            non_price_score=Decimal("10"),
            base_rate=Decimal("0.88"),
            max_price_score=Decimal("90"),
            multiplier=Decimal("20"),
            pred_price=Decimal("1000000000"),
            flat_ratio=Decimal("0.8825"),
            flat_score=Decimal("85"),
        )
        without = invert_pass_bid_range(
            pass_threshold=Decimal("95"),
            non_price_score=Decimal("10"),
            base_rate=Decimal("0.88"),
            max_price_score=Decimal("90"),
            multiplier=Decimal("20"),
            pred_price=Decimal("1000000000"),
        )
        assert with_flat.ratio_low == without.ratio_low
        assert with_flat.amount_low == without.amount_low


class TestResolvePriceCompensationFlat:
    """보정 탐색이 평탄을 반영하는지 검증."""

    def test_high_lwlt_floor_uses_flat_score(self) -> None:
        # 하한율 90% (기준 88% 위, 평탄 88.25% 위) -> 최저 투찰금액 점수가 평탄값 85
        # N 80 이면 평탄 덕분에 already_sufficient, 평탄이 없으면 도달 불가
        kwargs = {
            "pass_threshold": Decimal("95"),
            "non_price_score": Decimal("15"),
            "base_rate": Decimal("0.88"),
            "max_price_score": Decimal("90"),
            "multiplier": Decimal("20"),
            "announcement_lwlt_rate": Decimal("90"),
            "reference_pred_price": Decimal("100000000"),
        }
        without_flat = resolve_price_compensation(**kwargs)
        with_flat = resolve_price_compensation(
            **kwargs, flat_ratio=Decimal("0.8825"), flat_score=Decimal("85")
        )
        assert without_flat.floor_price_score == Decimal("50.0000")
        assert without_flat.score_status == "impossible"
        assert with_flat.floor_price_score == Decimal("85")
        assert with_flat.score_status == "already_sufficient"

    def test_compensation_unchanged_without_flat(self) -> None:
        kwargs = {
            "pass_threshold": Decimal("95"),
            "non_price_score": Decimal("25"),
            "base_rate": Decimal("0.88"),
            "max_price_score": Decimal("90"),
            "multiplier": Decimal("20"),
            "announcement_lwlt_rate": Decimal("87.995"),
            "reference_pred_price": Decimal("100000000"),
        }
        baseline = resolve_price_compensation(**kwargs)
        asserted = resolve_price_compensation(**kwargs, flat_ratio=None, flat_score=None)
        assert baseline.score_status == asserted.score_status
        assert baseline.score_gap == asserted.score_gap
        assert baseline.floor_price_score == asserted.floor_price_score


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


def _create_local_bid_for(
    db, *, institution_name: str, method_name: str, presmpt_prce: int
) -> BidAnnouncement:
    """시·도 수요기관과 지방계약 공고를 만들어 LOCAL 규칙 판별 경로를 엽니다."""
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
    data = {
        "prearngPrceDcsnMthdNm": "복수예가",
        "sucsfbidMthdNm": method_name,
        "sucsfbidLwltRate": "87.995",
        "srvceDivNm": "일반용역",
        "cntrctCnclsMthdNm": "지방자치단체 제한경쟁",
        "dminsttCd": "1234",
        "totPrdprcNum": "12",
        "drwtPrdprcNum": "3",
    }
    bid = BidAnnouncement(
        bid_ntce_nm="지방계약 평탄 끝단 테스트 공고",
        bid_ntce_no="EVAL-FLAT-ZONE-001",
        bid_ntce_ord="000",
        ntce_instt_nm="테스트 공고기관",
        dminstt_nm=f"{institution_name} 본청",
        base_amount=presmpt_prce,
        presmpt_prce=presmpt_prce,
        bid_ntce_dt=utcnow(),
        bid_clse_dt=utcnow(),
        openg_dt=utcnow(),
        category="Servc",
        raw_data=data,
    )
    db.add(bid)
    db.commit()
    db.refresh(bid)
    return bid


# 시·도마다 평탄 데이터가 연결된 대표 규칙 하나. (시·도, 세부유형, 추정가격, rule_id, 평탄비율, 평탄점수)
SIDO_FLAT_CASES = [
    (
        "인천광역시",
        "GENERAL",
        150_000_000,
        "SERVC_LOCAL_INCHEON_20251224_ATTACH_01",
        "0.8825",
        "85",
    ),
    (
        "제주특별자치도",
        "GENERAL",
        150_000_000,
        "SERVC_LOCAL_JEJU_20240101_ATTACH_01",
        "0.8825",
        "85",
    ),
    (
        "강원특별자치도",
        "GENERAL",
        150_000_000,
        "SERVC_LOCAL_GANGWON_20230611_ATTACH_01",
        "0.8825",
        "85",
    ),
    (
        "세종특별자치시",
        "FACILITY",
        300_000_000,
        "SERVC_LOCAL_SEJONG_20251201_ATTACH_02",
        "0.8825",
        "55",
    ),
    ("경상북도", "SIMPLE_LABOR", 300_000_000, "SERVC_LOCAL_GB_20260108_ATTACH_01", "0.8825", "65"),
    ("울산광역시", "GENERAL", 150_000_000, "SERVC_LOCAL_ULSAN_20220810_ATTACH_01", "0.8825", "85"),
    ("충청북도", "GENERAL", 150_000_000, "SERVC_LOCAL_CB_20231020_ATTACH_01", "0.8825", "85"),
    (
        "전남광주통합특별시",
        "FACILITY",
        150_000_000,
        "SERVC_LOCAL_JNGJ_20260716_ATTACH_01",
        "0.8825",
        "85",
    ),
    ("경상남도", "GENERAL", 150_000_000, "SERVC_LOCAL_GN_20230105_ATTACH_01", "0.8825", "85"),
    (
        "대구광역시",
        "SIMPLE_LABOR",
        300_000_000,
        "SERVC_LOCAL_DAEGU_20260511_ATTACH_01",
        "0.8825",
        "45",
    ),
    ("경기도", "SW", 150_000_000, "SERVC_LOCAL_GG_20250808_ATTACH_1_2", "0.8825", "85"),
]


class TestFlatZoneLinkedRuleIds:
    """평탄 데이터가 참조하는 rule_id 가 main LOCAL_RULES 와 그 구간에 실제로 존재하는지 고정."""

    def test_every_flat_rule_id_exists_in_local_rules(self) -> None:
        by_id = {rule.rule_id: rule for rule in LOCAL_RULES}
        assert flat_zone_entries()
        for rule_id, upper_bound, _zone in flat_zone_entries():
            rule = by_id.get(rule_id)
            assert rule is not None, f"LOCAL_RULES 에 없는 평탄 rule_id: {rule_id}"
            assert rule.contract_regime == "LOCAL", rule_id
            bounds = {band.upper_bound for band in (rule.price_bands or ())}
            assert upper_bound in bounds, f"{rule_id} 의 가격 구간에 없는 평탄 키: {upper_bound}"


class TestFlatZoneEndToEndApi:
    """시·도별 끝단 API 시험. resolve 를 mock 하지 않고 평탄이 응답까지 이어지는지 본다."""

    @pytest.mark.parametrize(
        ("sido_name", "service_type", "presmpt_prce", "rule_id", "flat_ratio", "flat_score"),
        SIDO_FLAT_CASES,
    )
    def test_sido_flat_zone_applied_in_response(
        self,
        client,
        isolated_db,
        as_user,
        sido_name: str,
        service_type: str,
        presmpt_prce: int,
        rule_id: str,
        flat_ratio: str,
        flat_score: str,
    ) -> None:
        as_user(10)
        bid = _create_local_bid_for(
            isolated_db,
            institution_name=sido_name,
            method_name="용역 적격심사",
            presmpt_prce=presmpt_prce,
        )
        # 기준 시나리오(예정가격 = 추정가격)에서 x 가 평탄 시작 비율을 한참 넘도록 투찰한다.
        # 이 지점에서 산식값은 평탄점수보다 확실히 낮으므로, 평탄이 실제로 반영됐는지 갈린다.
        ratio = Decimal("0.95")
        assert ratio > Decimal(flat_ratio)
        candidate = int((Decimal(presmpt_prce) * ratio).quantize(Decimal("1")))
        response = client.post(
            ANALYZE_URL,
            json={
                "bid_id": bid.id,
                "selected_model": "requested-evaluation-model",
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
        assert body["blocked"] is False
        assert body["rule_id"] == rule_id

        table = body["score_table"]
        assert table["flat_ratio"] == flat_ratio
        assert table["flat_score"] == flat_score

        base = next(row for row in body["scenario_results"] if row["scenario_name"] == "기준")
        assert base["bid_to_estimated_ratio"] == pytest.approx(float(ratio))
        # 평탄이 없으면 이 지점의 산식값은 음수까지 내려가므로, 산식값과 평탄점수가 확실히 갈린다.
        b = Decimal(table["max_price_score"])
        k = Decimal(table["multiplier"])
        base_rate = Decimal(str(body["base_rate"])) / Decimal("100")
        algebraic = b - k * abs(base_rate - ratio) * Decimal("100")
        assert algebraic < Decimal(flat_score)
        # 반환 점수는 산식값이 아니라 평탄 고정 점수여야 한다.
        assert base["price_score"] == pytest.approx(float(Decimal(flat_score)))

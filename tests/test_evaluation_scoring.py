"""
tests/test_evaluation_scoring.py

일반용역 적격심사 규칙 레지스트리 및 결정론적 점수 계산 단위 테스트.
DB 세션, HTTP 요청, 파일 I/O, 시스템 시각 대역 없이 순수 함수를 직접 검증합니다.
"""

from decimal import Decimal

import pytest

from src.app.services.evaluation_rules import (
    BLOCK_CODE_MANUAL_EVALUATION,
    BLOCK_CODE_NON_PRED_PRICE,
    BLOCK_CODE_NOT_SERVC,
    BLOCK_CODE_RULE_NOT_FOUND,
    POST_20260526_RULES,
    get_rule_by_id,
    list_all_rules,
    resolve_evaluation_rule,
    resolve_evaluation_rule_from_raw_data,
)
from src.app.services.evaluation_scoring import (
    calculate_min_bid_amount,
    calculate_price_score,
    compute_price_ratio,
    evaluate_qualification,
    format_decimal_plain,
    generate_pred_price_scenarios,
    invert_lowest_bid_rate,
    resolve_price_compensation,
)


class TestEvaluationRulesRegistry:
    """별표 14종 선언형 등록 및 정본 검증."""

    def test_post_20260526_rules_count(self) -> None:
        rules = list_all_rules()
        assert len(rules) == 14

    def test_insurance_rule_rate_is_canonical_47_995(self) -> None:
        rule = get_rule_by_id("SERVC_QUAL_POST_20260526_ATTACH_02")
        assert rule is not None
        assert rule.service_type == "INSURANCE"
        assert rule.lwlt_rate == Decimal("47.995")
        assert rule.sample_count == 195

    def test_facility_rule_rate_is_89_995(self) -> None:
        rule = get_rule_by_id("SERVC_QUAL_POST_20260526_ATTACH_01")
        assert rule is not None
        assert rule.service_type == "FACILITY"
        assert rule.lwlt_rate == Decimal("89.995")
        assert rule.sample_count == 213

    def test_all_14_rules_have_correct_rates_and_metadata(self) -> None:
        expected_rates = {
            "SERVC_QUAL_POST_20260526_ATTACH_01": Decimal("89.995"),
            "SERVC_QUAL_POST_20260526_ATTACH_02": Decimal("47.995"),
            "SERVC_QUAL_POST_20260526_ATTACH_03": Decimal("87.995"),
            "SERVC_QUAL_POST_20260526_ATTACH_04": Decimal("87.995"),
            "SERVC_QUAL_POST_20260526_ATTACH_05": Decimal("86.245"),
            "SERVC_QUAL_POST_20260526_ATTACH_06": Decimal("86.245"),
            "SERVC_QUAL_POST_20260526_ATTACH_07": Decimal("82.495"),
            "SERVC_QUAL_POST_20260526_ATTACH_08": Decimal("86.245"),
            "SERVC_QUAL_POST_20260526_ATTACH_09": Decimal("82.495"),
            "SERVC_QUAL_POST_20260526_ATTACH_10": Decimal("86.245"),
            "SERVC_QUAL_POST_20260526_ATTACH_11": Decimal("82.495"),
            "SERVC_QUAL_POST_20260526_ATTACH_12": Decimal("87.745"),
            "SERVC_QUAL_POST_20260526_ATTACH_13": Decimal("86.745"),
            "SERVC_QUAL_POST_20260526_ATTACH_14": Decimal("82.995"),
        }

        for rule in POST_20260526_RULES:
            assert rule.rule_id in expected_rates
            assert rule.lwlt_rate == expected_rates[rule.rule_id]
            assert rule.effective_date == "2026-05-26"
            assert len(rule.patterns) > 0


class TestRuleResolutionAndBlocking:
    """공고 판별 순서, 4대 차단 조건 및 하한율 우선순위 검증."""

    def test_block_when_not_servc_category(self) -> None:
        res = resolve_evaluation_rule(
            category="Thng",
            prearng_prce_dcsn_mthd_nm="복수예가",
            sucsfbid_mthd_nm="적격심사제(시설분야용역 적격심사 추정가격 5억원 미만)",
            sucsfbid_lwlt_rate="89.995",
        )
        assert res.is_blocked is True
        assert res.block_reason_code == BLOCK_CODE_NOT_SERVC
        assert res.rule is None

    def test_block_when_non_pred_price(self) -> None:
        res = resolve_evaluation_rule(
            category="Servc",
            prearng_prce_dcsn_mthd_nm="비예가",
            sucsfbid_mthd_nm="적격심사제(시설분야용역 적격심사 추정가격 5억원 미만)",
            sucsfbid_lwlt_rate="89.995",
        )
        assert res.is_blocked is True
        assert res.block_reason_code == BLOCK_CODE_NON_PRED_PRICE
        assert res.rule is None

    def test_block_when_manual_evaluation(self) -> None:
        res = resolve_evaluation_rule(
            category="Servc",
            prearng_prce_dcsn_mthd_nm="복수예가",
            sucsfbid_mthd_nm="적격심사제-관리규정외 수기심사(총점입력)",
            sucsfbid_lwlt_rate="87.745",
        )
        assert res.is_blocked is True
        assert res.block_reason_code == BLOCK_CODE_MANUAL_EVALUATION
        assert res.rule is None

    def test_block_when_rule_not_found(self) -> None:
        res = resolve_evaluation_rule(
            category="Servc",
            prearng_prce_dcsn_mthd_nm="복수예가",
            sucsfbid_mthd_nm="알수없는특수용역적격심사방식",
            sucsfbid_lwlt_rate="85.000",
        )
        assert res.is_blocked is True
        assert res.block_reason_code == BLOCK_CODE_RULE_NOT_FOUND
        assert res.rule is None

    def test_priority_1_and_warning_when_rate_missing(self) -> None:
        # 하한율 결측 시 별표 기본값 사용 및 기본값 경고 생성
        res = resolve_evaluation_rule(
            category="Servc",
            prearng_prce_dcsn_mthd_nm="복수예가",
            sucsfbid_mthd_nm="적격심사제(시설분야용역 적격심사 추정가격 5억원 미만)",
            sucsfbid_lwlt_rate=None,
        )
        assert res.is_blocked is False
        assert res.rule is not None
        assert res.effective_lwlt_rate == Decimal("89.995")
        assert res.rate_source == "RULE_DEFAULT"
        assert any("기본값" in w for w in res.warnings)

    def test_priority_2_and_warning_when_rate_mismatches(self) -> None:
        # 공고값과 별표 기본값 불일치 시 공고값 최우선 및 불일치 경고 생성
        res = resolve_evaluation_rule(
            category="Servc",
            prearng_prce_dcsn_mthd_nm="복수예가",
            sucsfbid_mthd_nm="적격심사제(시설분야용역 적격심사 추정가격 5억원 미만)",
            sucsfbid_lwlt_rate=Decimal("88.500"),
        )
        assert res.is_blocked is False
        assert res.effective_lwlt_rate == Decimal("88.500")
        assert res.rate_source == "ANNOUNCEMENT"
        assert any("일치하지 않아" in w for w in res.warnings)

    def test_priority_3_matching_rate_announcement(self) -> None:
        # 공고값과 별표 기본값 일치 시 공고값 사용 및 경고 없음
        res = resolve_evaluation_rule(
            category="Servc",
            prearng_prce_dcsn_mthd_nm="복수예가",
            sucsfbid_mthd_nm="적격심사제(추정가격 2억원 미만인 용역)",
            sucsfbid_lwlt_rate=Decimal("87.745"),
        )
        assert res.is_blocked is False
        assert res.effective_lwlt_rate == Decimal("87.745")
        assert res.rate_source == "ANNOUNCEMENT"
        assert len(res.warnings) == 0

    def test_resolve_from_raw_data_dict(self) -> None:
        raw_data = {
            "prearngPrceDcsnMthdNm": "복수예가",
            "sucsfbidMthdNm": "보험용역 적격심사 추정가격 5억원미만",
            "sucsfbidLwltRate": "47.995",
        }
        res = resolve_evaluation_rule_from_raw_data(
            category="Servc",
            raw_data=raw_data,
        )
        assert res.is_blocked is False
        assert res.rule is not None
        assert res.rule.service_type == "INSURANCE"
        assert res.effective_lwlt_rate == Decimal("47.995")


class TestDeterministicPricingMath:
    """소수점 넷째 자리 확정, Decimal ROUND_HALF_UP 및 가격점수 검증."""

    def test_ratio_canonical_example_407448800_divided_by_500000000(self) -> None:
        # 참고 자료 실측 예시 고정 테스트: 407,448,800 / 500,000,000 = 0.8148976 -> 0.8149
        bid = Decimal("407448800")
        pred = Decimal("500000000")
        ratio = compute_price_ratio(bid, pred)
        assert ratio == Decimal("0.8149")

    def test_compute_price_ratio_invalid_pred_price(self) -> None:
        with pytest.raises(ValueError):
            compute_price_ratio(Decimal("100"), Decimal("0"))

    def test_calculate_price_score_formula(self) -> None:
        # P = B - k * |(기준비율 - x) * 100|
        # x = 0.8149, 기준비율 = 0.88, B = 20, k = 2
        # (0.88 - 0.8149) * 100 = 6.51 -> 2 * 6.51 = 13.02
        # P = 20 - 13.02 = 6.98
        res = calculate_price_score(
            bid_price=Decimal("407448800"),
            pred_price=Decimal("500000000"),
            base_rate=Decimal("0.88"),
            max_price_score=Decimal("20"),
            multiplier=Decimal("2"),
        )
        assert res.price_ratio == Decimal("0.8149")
        assert res.score == Decimal("6.98")

    def test_calculate_price_score_with_percentage_base_rate(self) -> None:
        # base_rate 가 90 (%) 형태로 주어졌을 때 자동 정규화 동작 검증
        res = calculate_price_score(
            bid_price=Decimal("450000000"),
            pred_price=Decimal("500000000"),  # 0.9000
            base_rate=Decimal("90"),
            max_price_score=Decimal("30"),
            multiplier=Decimal("2"),
        )
        assert res.price_ratio == Decimal("0.9000")
        assert res.score == Decimal("30.0000")


class TestAValueMinBidAmount:
    """최저 투찰금액 산출 검증.

    A값 분기는 공사 적격심사 별표 전용이며 용역 적격심사에는 쓰지 않는다.
    용역 평가 경로는 항상 A값 없는 분기(예정가격 * 하한율)를 쓴다.
    """

    def test_min_bid_amount_without_a_value(self) -> None:
        # 최저 투찰금액 = 예정가격 * 하한율
        # 예정가격 100,000,000, 하한율 87.745% (0.87745) -> 87,745,000원
        res = calculate_min_bid_amount(
            pred_price=Decimal("100000000"),
            lwlt_rate=Decimal("87.745"),
            a_value=None,
        )
        assert res.has_a_value is False
        assert res.min_bid_amount == Decimal("87745000")

    def test_min_bid_amount_with_a_value(self) -> None:
        # 최저 투찰금액 = (예정가격 - A값) * 하한율 + A값
        # 예정가격 100,000,000, A값 10,000,000, 하한율 87.745%
        # (90,000,000 * 0.87745) + 10,000,000 = 78,970,500 + 10,000,000 = 88,970,500원
        res = calculate_min_bid_amount(
            pred_price=Decimal("100000000"),
            lwlt_rate=Decimal("87.745"),
            a_value=Decimal("10000000"),
        )
        assert res.has_a_value is True
        assert res.min_bid_amount == Decimal("88970500")


class TestInvertLowestBidRate:
    """최저 투찰률 역산 및 실질 구속 하한 판별 검증."""

    def test_invert_rate_when_announcement_rate_binds(self) -> None:
        # P_req = T - Q = 95 - 80 = 15
        # B = 20, k = 2, 기준비율 = 0.90
        # (20 - 15) / (100 * 2) = 5 / 200 = 0.025
        # 역산 투찰률 = 0.90 - 0.025 = 0.875 (87.5%)
        # 공고 하한율이 89.995% 이면, 87.5% < 89.995% 이므로 공고 하한율이 실질 구속 하한
        res = invert_lowest_bid_rate(
            pass_threshold=Decimal("95"),
            non_price_score=Decimal("80"),
            base_rate=Decimal("0.90"),
            max_price_score=Decimal("20"),
            multiplier=Decimal("2"),
            announcement_lwlt_rate=Decimal("89.995"),
        )
        assert res.calculated_rate_pct == Decimal("87.5")
        assert res.effective_rate_pct == Decimal("89.995")
        assert res.binding_constraint == "ANNOUNCEMENT_LWLT_RATE"
        assert res.binding_constraint_kr == "공고 낙찰하한율"
        assert res.can_pass is True

    def test_invert_rate_when_calculated_score_rate_binds(self) -> None:
        # 정량점수가 낮아 가격점수를 더 많이 받아야 하는 상황
        # P_req = 95 - 76 = 19
        # B = 20, k = 2, 기준비율 = 0.90
        # (20 - 19) / 200 = 1 / 200 = 0.005
        # 역산 투찰률 = 0.90 - 0.005 = 0.895 (89.5%)
        # 공고 하한율이 87.745% 이면, 89.5% > 87.745% 이므로 역산 투찰률이 실질 구속 하한
        res = invert_lowest_bid_rate(
            pass_threshold=Decimal("95"),
            non_price_score=Decimal("76"),
            base_rate=Decimal("0.90"),
            max_price_score=Decimal("20"),
            multiplier=Decimal("2"),
            announcement_lwlt_rate=Decimal("87.745"),
        )
        assert res.calculated_rate_pct == Decimal("89.5")
        assert res.effective_rate_pct == Decimal("89.5")
        assert res.binding_constraint == "CALCULATED_SCORE_RATE"
        assert res.binding_constraint_kr == "점수 역산 최저 투찰률"
        assert res.can_pass is True

    def test_invert_rate_when_impossible_to_pass(self) -> None:
        # Q = 70, T = 95, B = 20 -> P_req = 25 > B -> 만점으로도 탈락
        res = invert_lowest_bid_rate(
            pass_threshold=Decimal("95"),
            non_price_score=Decimal("70"),
            base_rate=Decimal("0.90"),
            max_price_score=Decimal("20"),
            multiplier=Decimal("2"),
            announcement_lwlt_rate=Decimal("87.745"),
        )
        assert res.can_pass is False
        assert any("도달할 수 없습니다" in w for w in res.warnings)


class TestPredPriceScenarios:
    """복수예비가격 시나리오 (기초금액 기준 +-범위) 검증."""

    def test_national_contract_default_2_percent(self) -> None:
        base = Decimal("100000000")
        res = generate_pred_price_scenarios(base_amount=base, is_local_contract=False)
        assert res.range_rate == Decimal("0.02")
        assert res.range_source == "NATIONAL_DEFAULT"
        assert res.scenario_lower == Decimal("98000000")
        assert res.scenario_base == Decimal("100000000")
        assert res.scenario_upper == Decimal("102000000")

    def test_local_contract_default_3_percent(self) -> None:
        base = Decimal("100000000")
        res = generate_pred_price_scenarios(base_amount=base, is_local_contract=True)
        assert res.range_rate == Decimal("0.03")
        assert res.range_source == "LOCAL_DEFAULT"
        assert res.scenario_lower == Decimal("97000000")
        assert res.scenario_base == Decimal("100000000")
        assert res.scenario_upper == Decimal("103000000")

    def test_custom_announcement_range_rate(self) -> None:
        base = Decimal("100000000")
        res = generate_pred_price_scenarios(
            base_amount=base,
            range_rate=Decimal("0.025"),
        )
        assert res.range_rate == Decimal("0.025")
        assert res.range_source == "ANNOUNCEMENT"
        assert res.scenario_lower == Decimal("97500000")
        assert res.scenario_base == Decimal("100000000")
        assert res.scenario_upper == Decimal("102500000")


class TestQualificationEvaluation:
    """종합점수 및 적격 판정 3대 조건 검증."""

    def test_all_conditions_satisfied(self) -> None:
        res = evaluate_qualification(
            bid_price=Decimal("90000000"),
            pred_price=Decimal("100000000"),
            pass_threshold=Decimal("95"),
            price_score=Decimal("20"),
            performance_score=Decimal("70"),
            labor_condition_score=Decimal("5"),
            reputation_score=Decimal("0"),
            has_disqualification=False,
        )
        assert res.is_qualified is True
        assert res.total_score == Decimal("95")
        assert res.non_price_score == Decimal("75")
        assert res.condition_no_disqualification is True
        assert res.condition_bid_price_valid is True
        assert res.condition_total_score_valid is True

    def test_disqualified_when_labor_condition_is_zero(self) -> None:
        # 근로조건 이행계획이 0점일 때 경고 생성
        res = evaluate_qualification(
            bid_price=Decimal("90000000"),
            pred_price=Decimal("100000000"),
            pass_threshold=Decimal("95"),
            price_score=Decimal("20"),
            performance_score=Decimal("75"),
            labor_condition_score=Decimal("0"),
            reputation_score=Decimal("0"),
            has_disqualification=False,
        )
        assert any("근로조건 이행계획 점수가 0점" in w for w in res.warnings)

    def test_disqualified_when_bid_price_exceeds_pred_price(self) -> None:
        res = evaluate_qualification(
            bid_price=Decimal("100000001"),
            pred_price=Decimal("100000000"),
            pass_threshold=Decimal("95"),
            price_score=Decimal("20"),
            performance_score=Decimal("75"),
            labor_condition_score=Decimal("5"),
            has_disqualification=False,
        )
        assert res.is_qualified is False
        assert res.condition_bid_price_valid is False
        assert any("초과하여" in w for w in res.warnings)

    def test_disqualified_when_has_disqualification(self) -> None:
        res = evaluate_qualification(
            bid_price=Decimal("90000000"),
            pred_price=Decimal("100000000"),
            pass_threshold=Decimal("95"),
            price_score=Decimal("20"),
            performance_score=Decimal("75"),
            labor_condition_score=Decimal("5"),
            has_disqualification=True,
        )
        assert res.is_qualified is False
        assert res.condition_no_disqualification is False
        assert any("결격사유가 존재" in w for w in res.warnings)

    def test_disqualified_when_score_below_threshold(self) -> None:
        res = evaluate_qualification(
            bid_price=Decimal("90000000"),
            pred_price=Decimal("100000000"),
            pass_threshold=Decimal("95"),
            price_score=Decimal("15"),
            performance_score=Decimal("70"),
            labor_condition_score=Decimal("5"),
            has_disqualification=False,
        )
        assert res.is_qualified is False
        assert res.condition_total_score_valid is False
        assert any("통과점수" in w for w in res.warnings)


class TestPriceCompensation:
    """정량점수 부족분의 입찰가격 보완 판정과 설계 검산(T1~T11) 고정."""

    def test_t1_already_sufficient_across_three_scenarios(self) -> None:
        # T=95, Q=75 -> P_req=20, B=20, 하한 89.995, 기준 0.90
        # P_floor = 20 이므로 P_req <= P_floor 로 최저 투찰금액에서 이미 충분하다.
        res = resolve_price_compensation(
            pass_threshold=Decimal("95"),
            non_price_score=Decimal("75"),
            base_rate=Decimal("0.90"),
            max_price_score=Decimal("20"),
            multiplier=Decimal("2"),
            announcement_lwlt_rate=Decimal("89.995"),
            reference_pred_price=Decimal("500000000"),
            scenarios=(
                ("하단", "LOWER", Decimal("490000000")),
                ("기준", "BASE", Decimal("500000000")),
                ("상단", "UPPER", Decimal("510000000")),
            ),
        )
        assert res.score_status == "already_sufficient"
        assert res.score_gap == Decimal("0")
        assert res.score_slack == Decimal("0")
        assert res.score_floor_amount == Decimal("449975000")
        assert res.floor_price_score == Decimal("20")
        assert res.effective_rate_percent == Decimal("90")
        assert [row.complement_bid_amount for row in res.scenarios] == [
            Decimal("440975500"),
            Decimal("449975000"),
            Decimal("458974500"),
        ]
        assert [row.verified_price_ratio for row in res.scenarios] == [
            Decimal("0.9000"),
            Decimal("0.9000"),
            Decimal("0.9000"),
        ]
        assert [row.verified_price_score for row in res.scenarios] == [
            Decimal("20"),
            Decimal("20"),
            Decimal("20"),
        ]
        assert [row.bid_rate_percent for row in res.scenarios] == [
            Decimal("89.995"),
            Decimal("89.995"),
            Decimal("89.995"),
        ]
        assert all(row.row_status == "already_sufficient" for row in res.scenarios)
        assert all(row.ratio_steps_raised == 0 for row in res.scenarios)
        assert all(row.meets_p_req is True for row in res.scenarios)

    def test_t2_score_slack_when_non_price_score_is_higher(self) -> None:
        # T1 에서 Q=83 -> P_req=12 이므로 P_floor 20 대비 여유가 8점이다.
        res = resolve_price_compensation(
            pass_threshold=Decimal("95"),
            non_price_score=Decimal("83"),
            base_rate=Decimal("0.90"),
            max_price_score=Decimal("20"),
            multiplier=Decimal("2"),
            announcement_lwlt_rate=Decimal("89.995"),
            reference_pred_price=Decimal("500000000"),
        )
        assert res.score_status == "already_sufficient"
        assert res.score_gap == Decimal("0")
        assert res.score_slack == Decimal("8")
        assert res.effective_rate_percent == Decimal("89.995")
        assert res.binding_constraint == "ANNOUNCEMENT_LWLT_RATE"

    def test_t3_compensation_amount_on_exact_boundary(self) -> None:
        # T=95, Q=70 -> P_req=25, B=30, k=2, 하한 86.745, 기준 0.90
        # 낮은 근 = 0.90 - 5/200 = 0.875, 경계비율 0.87495 의 올림 금액이 채택된다.
        res = resolve_price_compensation(
            pass_threshold=Decimal("95"),
            non_price_score=Decimal("70"),
            base_rate=Decimal("0.90"),
            max_price_score=Decimal("30"),
            multiplier=Decimal("2"),
            announcement_lwlt_rate=Decimal("86.745"),
            reference_pred_price=Decimal("100000000"),
            scenarios=(
                ("기준", "BASE", Decimal("100000000")),
                ("하단", "LOWER", Decimal("99999999")),
            ),
        )
        assert res.score_status == "compensate"
        assert res.floor_price_score == Decimal("23.5")
        assert res.score_gap == Decimal("1.5")
        assert res.score_floor_amount == Decimal("86745000")
        assert res.effective_rate_percent == Decimal("87.5")
        assert res.binding_constraint == "CALCULATED_SCORE_RATE"
        base_row = res.scenarios[0]
        assert base_row.complement_bid_amount == Decimal("87495000")
        assert base_row.verified_price_ratio == Decimal("0.8750")
        assert base_row.verified_price_score == Decimal("25")
        assert base_row.bid_rate_percent == Decimal("87.495")
        assert base_row.ratio_steps_raised == 0
        assert base_row.meets_p_req is True
        # 예정가격이 1원 낮아도 같은 4자리 격자에 들어가 같은 금액이 최저가 된다.
        assert res.scenarios[1].complement_bid_amount == Decimal("87495000")

    def test_t4_compensation_steps_up_one_grid(self) -> None:
        # T3 에서 Q=69.998 -> P_req=25.002, 낮은 근 0.87501 의 올림 격자는 0.8751 이다.
        res = resolve_price_compensation(
            pass_threshold=Decimal("95"),
            non_price_score=Decimal("69.998"),
            base_rate=Decimal("0.90"),
            max_price_score=Decimal("30"),
            multiplier=Decimal("2"),
            announcement_lwlt_rate=Decimal("86.745"),
            reference_pred_price=Decimal("100000000"),
        )
        assert res.score_status == "compensate"
        assert res.p_req == Decimal("25.002")
        assert res.scenarios == ()
        probe = calculate_price_score(
            bid_price=Decimal("87504999"),
            pred_price=Decimal("100000000"),
            base_rate=Decimal("0.90"),
            max_price_score=Decimal("30"),
            multiplier=Decimal("2"),
        )
        assert probe.score < Decimal("25.002")

    def test_t4_row_values_are_pinned(self) -> None:
        res = resolve_price_compensation(
            pass_threshold=Decimal("95"),
            non_price_score=Decimal("69.998"),
            base_rate=Decimal("0.90"),
            max_price_score=Decimal("30"),
            multiplier=Decimal("2"),
            announcement_lwlt_rate=Decimal("86.745"),
            scenarios=(("기준", "BASE", Decimal("100000000")),),
        )
        row = res.scenarios[0]
        assert row.complement_bid_amount == Decimal("87505000")
        assert row.verified_price_ratio == Decimal("0.8751")
        assert row.ratio_steps_raised == 1

    def test_t5_impossible_when_floor_ratio_exceeds_base_rate(self) -> None:
        # 하한율 90.005 는 기준비율 0.90 보다 높아 x_floor 0.9001 > 0.90 이고 P_floor 19.98 < P_req 20.
        res = resolve_price_compensation(
            pass_threshold=Decimal("95"),
            non_price_score=Decimal("75"),
            base_rate=Decimal("0.90"),
            max_price_score=Decimal("20"),
            multiplier=Decimal("2"),
            announcement_lwlt_rate=Decimal("90.005"),
            scenarios=(("기준", "BASE", Decimal("100000000")),),
        )
        assert res.score_status == "impossible"
        assert res.score_gap == Decimal("0.02")
        assert res.floor_price_score == Decimal("19.98")
        row = res.scenarios[0]
        assert row.complement_bid_amount is None
        assert row.verified_price_ratio is None
        assert row.verified_price_score is None
        assert row.bid_rate_percent is None
        assert row.row_status == "impossible"
        assert row.meets_p_req is False

    def test_t6_impossible_when_won_unit_cannot_reach_required_score(self) -> None:
        # 예정가격 3,333원, 하한율 80%: 원 단위로 올려도 19.97 점에 닿지 않는다.
        res = resolve_price_compensation(
            pass_threshold=Decimal("95"),
            non_price_score=Decimal("75.03"),
            base_rate=Decimal("0.90"),
            max_price_score=Decimal("20"),
            multiplier=Decimal("2"),
            announcement_lwlt_rate=Decimal("80"),
            scenarios=(("기준", "BASE", Decimal("3333")),),
        )
        assert res.score_status == "impossible"
        assert res.p_req == Decimal("19.97")
        assert res.score_gap == Decimal("0.01")
        assert res.scenarios[0].complement_bid_amount is None
        assert res.scenarios[0].row_status == "impossible"

    def test_t7_impossible_when_p_req_exceeds_max_price_score(self) -> None:
        # Q=72, T=95 -> P_req=23 > B=20 이므로 만점으로도 도달할 수 없다.
        res = resolve_price_compensation(
            pass_threshold=Decimal("95"),
            non_price_score=Decimal("72"),
            base_rate=Decimal("0.90"),
            max_price_score=Decimal("20"),
            multiplier=Decimal("2"),
            announcement_lwlt_rate=Decimal("89.995"),
            reference_pred_price=Decimal("500000000"),
            scenarios=(("기준", "BASE", Decimal("500000000")),),
        )
        assert res.score_status == "impossible"
        assert res.score_gap == Decimal("3")
        assert res.scenarios[0].complement_bid_amount is None
        assert res.scenarios[0].meets_p_req is False

    def test_t8_k4_scenarios_and_forward_verification(self) -> None:
        # T=95, Q=29 -> P_req=66, B=70, k=4, 하한 86.745, 기준 0.88
        # 낮은 근 = 0.88 - 4/400 = 0.87, 경계비율 0.86995 의 올림 금액이 채택된다.
        res = resolve_price_compensation(
            pass_threshold=Decimal("95"),
            non_price_score=Decimal("29"),
            base_rate=Decimal("0.88"),
            max_price_score=Decimal("70"),
            multiplier=Decimal("4"),
            announcement_lwlt_rate=Decimal("86.745"),
            scenarios=(
                ("낙찰예상", "BASE", Decimal("333333333")),
                ("소액", "LOWER", Decimal("100000000")),
                ("중간", "MID", Decimal("123456789")),
                ("대액", "UPPER", Decimal("500000000")),
            ),
        )
        assert res.score_status == "compensate"
        assert res.scenarios[0].verified_price_ratio == Decimal("0.8700")
        assert res.scenarios[0].verified_price_score == Decimal("66")
        assert res.scenarios[0].ratio_steps_raised == 0
        assert [row.complement_bid_amount for row in res.scenarios] == [
            Decimal("289983334"),
            Decimal("86995000"),
            Decimal("107401234"),
            Decimal("434975000"),
        ]
        one_won_below = calculate_price_score(
            bid_price=Decimal("289983333"),
            pred_price=Decimal("333333333"),
            base_rate=Decimal("0.88"),
            max_price_score=Decimal("70"),
            multiplier=Decimal("4"),
        )
        assert one_won_below.price_ratio == Decimal("0.8699")
        assert one_won_below.score == Decimal("65.96")

    def test_t9_rate_only_when_no_reference_and_no_scenarios(self) -> None:
        res = resolve_price_compensation(
            pass_threshold=Decimal("95"),
            non_price_score=Decimal("70"),
            base_rate=Decimal("0.90"),
            max_price_score=Decimal("30"),
            multiplier=Decimal("2"),
            announcement_lwlt_rate=Decimal("89.995"),
        )
        assert res.amount_status == "rate_only"
        assert res.floor_score_basis == "algebraic"
        assert res.scenarios == ()
        assert res.score_floor_amount is None
        assert res.floor_price_score == Decimal("29.99")
        assert res.score_status == "already_sufficient"

    def test_t10_global_status_follows_worst_scenario_row(self) -> None:
        # 3,333원 행은 도달 불가, 100,000,000원 행은 보완 가능하므로 전역은 불가다.
        res = resolve_price_compensation(
            pass_threshold=Decimal("95"),
            non_price_score=Decimal("75.03"),
            base_rate=Decimal("0.90"),
            max_price_score=Decimal("20"),
            multiplier=Decimal("2"),
            announcement_lwlt_rate=Decimal("80"),
            scenarios=(
                ("소액", "LOWER", Decimal("3333")),
                ("기준", "BASE", Decimal("100000000")),
            ),
        )
        assert res.score_status == "impossible"
        assert res.amount_status == "verified"
        assert res.floor_score_basis == "forward_verified"
        assert [row.row_status for row in res.scenarios] == ["impossible", "compensate"]

    def test_t11_format_decimal_plain(self) -> None:
        assert format_decimal_plain(Decimal("20.00")) == "20"
        assert format_decimal_plain(Decimal("89.9950")) == "89.995"
        assert format_decimal_plain(Decimal("1.50")) == "1.5"
        assert format_decimal_plain(Decimal("0")) == "0"

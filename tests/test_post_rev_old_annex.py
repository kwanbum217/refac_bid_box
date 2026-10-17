"""개정 후(2026-05-26 이후) 공고가 쓰는 임대차·수리ㆍ점검·수요기관 지정형 표기 매칭 계약 테스트.

제2026-260호 개정 전문(국가법령정보센터)과 제2026-390호 개정 전문·분야별 낙찰하한율
안내(조달청 고시)에 별표 7(수리ㆍ점검용역)·8(임대차)·9(수요기관 지정형)이 실재함을
원문으로 확인하고, 그 원문 값으로 개정 후 두 벌에 규칙 6종을 넣었습니다. 이 파일은

(a) 세 표기 공고가 그 규칙으로 계산되고,
(b) 2026-05-26 이전 공고는 개정 전 규칙 그대로이며,
(c) 새 값이 개정 전 규칙에서 그대로 옮겨지지 않았음

을 고정합니다. 원문 출처와 근거 표는 docs/analysis/post_rev_old_annex_apply_20261017.md 입니다.
"""

from datetime import date
from decimal import Decimal

import pytest

from src.app.services.evaluation_rules import (
    POST_20260526_RULES,
    POST_20260727_RULES,
    PRE_20250901_RULES,
    RuleResolutionResult,
    get_rule_by_id,
    match_rule_by_mthd_nm,
    resolve_evaluation_rule,
    resolve_evaluation_rule_from_raw_data,
    resolve_score_params,
)

# 낙찰방법명 표기는 DB(bid_announcements.raw_data.sucsfbidMthdNm)에서 그대로 옮겼습니다.
# 수요기관 지정형만 "적격심사제-수요기관 지정형 적격심사"와 "추정가격" 사이가 두 칸입니다.
REPAIR_METHOD_UNDER = "적격심사제-수리ㆍ점검용역 적격심사 고시금액 미만"
REPAIR_METHOD_UNDER_PRICE = "적격심사제-수리ㆍ점검용역 적격심사 추정가격 고시금액 미만"
REPAIR_METHOD_OVER_PRICE = "적격심사제-수리ㆍ점검용역 적격심사 5억원 미만 고시금액 이상"
REPAIR_METHOD_OVER = "적격심사제-수리ㆍ점검용역 적격심사 5억원 이상"
LEASE_METHOD_UNDER = "적격심사제-임대차 적격심사 추정가격 고시금액 미만"
LEASE_METHOD_OVER = "적격심사제-임대차 적격심사 추정가격 고시금액 이상"
DEMAND_METHOD_UNDER = "적격심사제-수요기관 지정형 적격심사  추정가격 고시금액 미만"
DEMAND_METHOD_OVER = "적격심사제-수요기관 지정형 적격심사  추정가격 고시금액 이상"

ATTACH_15 = "SERVC_QUAL_POST_20260526_ATTACH_15"
ATTACH_16 = "SERVC_QUAL_POST_20260526_ATTACH_16"
ATTACH_17 = "SERVC_QUAL_POST_20260526_ATTACH_17"
ATTACH_18 = "SERVC_QUAL_POST_20260526_ATTACH_18"
ATTACH_19 = "SERVC_QUAL_POST_20260526_ATTACH_19"
ATTACH_20 = "SERVC_QUAL_POST_20260526_ATTACH_20"

PRE_REPAIR = "SERVC_QUAL_PRE_20250901_ATTACH_15"
PRE_LEASE = "SERVC_QUAL_PRE_20250901_ATTACH_16"
PRE_DEMAND = "SERVC_QUAL_PRE_20250901_ATTACH_17"

# 원문이 고시금액 미만·이상 두 행으로 나눈 별표 7~9 의 규칙과 그 낙찰하한율입니다.
# 개정 전 한 벌이 쓰던 단일 84.245% 와 다릅니다.
POST_NEW_RULE_CASES = (
    (ATTACH_15, "86.245", PRE_REPAIR),
    (ATTACH_16, "82.495", PRE_REPAIR),
    (ATTACH_17, "86.245", PRE_LEASE),
    (ATTACH_18, "82.495", PRE_LEASE),
    (ATTACH_19, "86.245", PRE_DEMAND),
    (ATTACH_20, "82.495", PRE_DEMAND),
)

# DB 실측 표기 8종과 그 표기가 풀려야 하는 개정 후 규칙입니다.
DB_NOTATION_CASES = (
    (REPAIR_METHOD_UNDER, "86.245", ATTACH_15),
    (REPAIR_METHOD_UNDER_PRICE, "86.245", ATTACH_15),
    (REPAIR_METHOD_OVER_PRICE, "82.495", ATTACH_16),
    (REPAIR_METHOD_OVER, "82.495", ATTACH_16),
    (LEASE_METHOD_UNDER, "86.245", ATTACH_17),
    (LEASE_METHOD_OVER, "82.495", ATTACH_18),
    (DEMAND_METHOD_UNDER, "86.245", ATTACH_19),
    (DEMAND_METHOD_OVER, "82.495", ATTACH_20),
)

# 개정 전 벌도 같은 표기를 자기 별표로 풀어야 합니다. 라우팅이 뒤집히지 않았음을 봅니다.
PRE_RULE_BY_METHOD = (
    (REPAIR_METHOD_UNDER, PRE_REPAIR),
    (REPAIR_METHOD_UNDER_PRICE, PRE_REPAIR),
    (REPAIR_METHOD_OVER_PRICE, PRE_REPAIR),
    (REPAIR_METHOD_OVER, PRE_REPAIR),
    (LEASE_METHOD_UNDER, PRE_LEASE),
    (LEASE_METHOD_OVER, PRE_LEASE),
    (DEMAND_METHOD_UNDER, PRE_DEMAND),
    (DEMAND_METHOD_OVER, PRE_DEMAND),
)


def _resolve(method_name: str, bid_ntce_dt: date | str, rate: str | None) -> RuleResolutionResult:
    return resolve_evaluation_rule(
        category="Servc",
        prearng_prce_dcsn_mthd_nm="복수예가",
        sucsfbid_mthd_nm=method_name,
        sucsfbid_lwlt_rate=rate,
        bid_ntce_dt=bid_ntce_dt,
    )


class TestOriginalTextDeclarations:
    """개정 후 별표 7~9 규칙의 선언 값이 원문과 같은지 고정한다."""

    @pytest.mark.parametrize("rule_id, rate, pre_rule_id", POST_NEW_RULE_CASES)
    def test_declared_values(self, rule_id: str, rate: str, pre_rule_id: str) -> None:
        rule = get_rule_by_id(rule_id, POST_20260526_RULES)

        assert rule is not None, rule_id
        assert rule.pass_threshold == Decimal("85"), rule_id
        assert rule.lwlt_rate == Decimal(rate), rule_id
        assert rule.base_rate == Decimal("0.90"), rule_id
        assert rule.effective_date == "2026-05-26", rule_id
        assert rule.lwlt_rate != Decimal("84.245"), rule_id
        assert rule.score_table_source is not None, rule_id
        assert "별표" in rule.score_table_source, rule_id
        assert "제2026-260호" in rule.score_table_source, rule_id

    def test_values_were_not_copied_from_the_pre_regime(self) -> None:
        """개정 전 벌과 값이 다르다는 사실을 고정한다. 원문 확인 없이 옮기면 여기서 걸린다."""
        pre_rule_ids = (PRE_REPAIR, PRE_LEASE, PRE_DEMAND)
        pre_rules = [get_rule_by_id(rule_id, PRE_20250901_RULES) for rule_id in pre_rule_ids]

        for pre_rule in pre_rules:
            assert pre_rule is not None
            # 기준값은 개정 전 0.88 에서 개정 후 0.90 으로 올랐습니다.
            assert pre_rule.base_rate == Decimal("0.88"), pre_rule.rule_id
            # 낙찰하한율은 개정 전 단일 84.245% 였습니다.
            assert pre_rule.lwlt_rate == Decimal("84.245"), pre_rule.rule_id

        post_rules = [
            get_rule_by_id(rule_id, POST_20260526_RULES) for rule_id, _, _ in POST_NEW_RULE_CASES
        ]
        for post_rule in post_rules:
            assert post_rule is not None
            assert post_rule.base_rate != Decimal("0.88"), post_rule.rule_id
            assert post_rule.lwlt_rate in {Decimal("86.245"), Decimal("82.495")}, post_rule.rule_id

    def test_price_ceiling_shapes(self) -> None:
        """별표 7 은 5억원 기준 조건부, 별표 8 은 70 단일, 별표 9 는 수요기관 선택이다."""
        repair_under = get_rule_by_id(ATTACH_15, POST_20260526_RULES)
        repair_over = get_rule_by_id(ATTACH_16, POST_20260526_RULES)
        lease_under = get_rule_by_id(ATTACH_17, POST_20260526_RULES)
        lease_over = get_rule_by_id(ATTACH_18, POST_20260526_RULES)
        demand_under = get_rule_by_id(ATTACH_19, POST_20260526_RULES)
        demand_over = get_rule_by_id(ATTACH_20, POST_20260526_RULES)

        for rule in (repair_under, repair_over):
            assert rule is not None
            assert rule.max_price_score is None
            assert rule.max_price_score_by_500m == (Decimal("70"), Decimal("60"))

        for rule in (lease_under, lease_over):
            assert rule is not None
            assert rule.max_price_score == Decimal("70")
            assert rule.max_price_score_by_500m is None

        # 별표 9 는 수요기관이 60~70 범위에서 고르므로 배점한도를 만들지 않습니다.
        for rule in (demand_under, demand_over):
            assert rule is not None
            assert rule.max_price_score is None
            assert rule.max_price_score_by_500m is None

    @pytest.mark.parametrize("rule_id, rate, pre_rule_id", POST_NEW_RULE_CASES)
    def test_multiplier_is_conditional_on_the_notice_amount(
        self, rule_id: str, rate: str, pre_rule_id: str
    ) -> None:
        """별표 7~9 는 모두 계수가 고시금액 미만 4 / 이상 2 로 갈린다."""
        rule = get_rule_by_id(rule_id, POST_20260526_RULES)

        assert rule is not None
        assert rule.multiplier is None
        assert rule.multiplier_by_notice == (Decimal("4"), Decimal("2"))


class TestNotationMatching:
    """개정 후 표기 공고가 개정 후 규칙으로 계산되는지 검증한다."""

    @pytest.mark.parametrize("bid_ntce_dt", ["2026-06-10", "2026-08-10", date(2026, 7, 27)])
    @pytest.mark.parametrize("method_name, rate, rule_id", DB_NOTATION_CASES)
    def test_notation_matches_post_rule(
        self, method_name: str, rate: str, rule_id: str, bid_ntce_dt: date | str
    ) -> None:
        result = _resolve(method_name, bid_ntce_dt, rate)

        assert result.is_blocked is False, (method_name, result.block_reason_code)
        assert result.rule is not None
        assert result.rule.rule_id == rule_id
        # 공고가 인쇄한 하한율이 규칙 대표값보다 우선합니다.
        assert result.effective_lwlt_rate == Decimal(rate)
        assert result.rate_source == "ANNOUNCEMENT"

    @pytest.mark.parametrize("bid_ntce_dt", ["2026-06-10", date(2026, 7, 27)])
    @pytest.mark.parametrize("method_name, rate, rule_id", DB_NOTATION_CASES)
    def test_rule_default_rate_when_announcement_has_none(
        self, method_name: str, rate: str, rule_id: str, bid_ntce_dt: date | str
    ) -> None:
        """공고에 하한율이 없으면 규칙이 원문에서 확정한 대표값을 쓴다."""
        result = _resolve(method_name, bid_ntce_dt, None)

        assert result.is_blocked is False, result.block_reason_code
        assert result.rule is not None
        assert result.rule.rule_id == rule_id
        assert result.effective_lwlt_rate == Decimal(rate)
        assert result.rate_source == "RULE_DEFAULT"

    @pytest.mark.parametrize("method_name, rate, rule_id", DB_NOTATION_CASES)
    def test_raw_data_entry_point_matches_the_same_rule(
        self, method_name: str, rate: str, rule_id: str
    ) -> None:
        result = resolve_evaluation_rule_from_raw_data(
            category="Servc",
            raw_data={
                "prearngPrceDcsnMthdNm": "복수예가",
                "sucsfbidMthdNm": method_name,
                "sucsfbidLwltRate": rate,
                "bidNtceDt": "2026-06-10",
            },
        )

        assert result.is_blocked is False, result.block_reason_code
        assert result.rule is not None
        assert result.rule.rule_id == rule_id

    def test_demand_agency_pattern_keeps_the_double_space(self) -> None:
        """DB 표기의 이중 공백을 원문 패턴에 그대로 남긴다."""
        rule = get_rule_by_id(ATTACH_19, POST_20260526_RULES)

        assert rule is not None
        assert DEMAND_METHOD_UNDER.endswith("수요기관 지정형 적격심사  추정가격 고시금액 미만")
        assert "수요기관 지정형 적격심사  추정가격 고시금액 미만" in rule.patterns
        assert any("  " in pattern for pattern in rule.patterns)

    def test_middle_dot_is_the_hangul_letter_araeae(self) -> None:
        """가운뎃점은 U+318D 다. U+00B7 로 적으면 가운뎃점이 든 표기가 매칭되지 않는다."""
        rule = get_rule_by_id(ATTACH_15, POST_20260526_RULES)

        assert rule is not None
        joined = "".join(rule.patterns)
        assert "\u318d" in joined
        assert "\u00b7" not in joined


class TestScoreParameterResolution:
    """규칙이 선언한 조건부 B·k 가 공고 값으로 풀리는지 검증한다."""

    @pytest.mark.parametrize(
        "rule_id, method_name, estimated_price, expected_b, expected_k",
        [
            (ATTACH_15, REPAIR_METHOD_UNDER, 200_000_000, Decimal("70"), Decimal("4")),
            (ATTACH_16, REPAIR_METHOD_OVER_PRICE, 300_000_000, Decimal("70"), Decimal("2")),
            (ATTACH_16, REPAIR_METHOD_OVER, 700_000_000, Decimal("60"), Decimal("2")),
            (ATTACH_17, LEASE_METHOD_UNDER, 150_000_000, Decimal("70"), Decimal("4")),
            (ATTACH_18, LEASE_METHOD_OVER, 900_000_000, Decimal("70"), Decimal("2")),
            (ATTACH_19, DEMAND_METHOD_UNDER, 120_000_000, None, Decimal("4")),
            (ATTACH_20, DEMAND_METHOD_OVER, 1_000_000_000, None, Decimal("2")),
        ],
    )
    def test_conditional_axes(
        self,
        rule_id: str,
        method_name: str,
        estimated_price: int,
        expected_b: Decimal | None,
        expected_k: Decimal | None,
    ) -> None:
        rule = get_rule_by_id(rule_id, POST_20260526_RULES)

        assert rule is not None
        resolution = resolve_score_params(rule, estimated_price, "2026-06-10", method_name)

        assert resolution.max_price_score == expected_b, rule_id
        assert resolution.multiplier == expected_k, rule_id
        assert resolution.pass_threshold == Decimal("85"), rule_id
        assert resolution.warnings == (), rule_id


class TestPreRegimeIsUnchanged:
    """2026-05-26 이전 공고는 개정 전 규칙 그대로인지 검증한다."""

    @pytest.mark.parametrize("bid_ntce_dt", ["2025-10-20", "2026-03-02", date(2026, 5, 25)])
    @pytest.mark.parametrize("method_name, pre_rule_id", PRE_RULE_BY_METHOD)
    def test_pre_announcement_matches_the_pre_rule(
        self, method_name: str, pre_rule_id: str, bid_ntce_dt: date | str
    ) -> None:
        result = _resolve(method_name, bid_ntce_dt, "84.245")

        assert result.is_blocked is False, (method_name, result.block_reason_code)
        assert result.rule is not None
        assert result.rule.rule_id == pre_rule_id

    def test_regime_boundary_is_still_2026_05_26(self) -> None:
        before = _resolve(LEASE_METHOD_UNDER, "2026-05-25 23:59:59", "84.245")
        after = _resolve(LEASE_METHOD_UNDER, "2026-05-26 00:00:00", "86.245")

        assert before.rule is not None
        assert before.rule.rule_id == PRE_LEASE
        assert after.rule is not None
        assert after.rule.rule_id == ATTACH_17

    @pytest.mark.parametrize("method_name, pre_rule_id", PRE_RULE_BY_METHOD)
    def test_pre_bundle_matching_is_not_widened(self, method_name: str, pre_rule_id: str) -> None:
        """개정 전 벌은 같은 표기를 자기 별표로 풀고, 개정 후 규칙으로 새지 않는다."""
        matched = match_rule_by_mthd_nm(method_name, rules=PRE_20250901_RULES)

        assert matched is not None, method_name
        assert matched.rule_id == pre_rule_id


class TestPostRegimeBundles:
    """개정 후 두 벌이 새 규칙을 함께 담고, 390 벌은 260 벌 객체를 재사용하는지 검증한다."""

    @pytest.mark.parametrize("rule_id, rate, pre_rule_id", POST_NEW_RULE_CASES)
    def test_both_post_bundles_carry_the_rule(
        self, rule_id: str, rate: str, pre_rule_id: str
    ) -> None:
        first = get_rule_by_id(rule_id, POST_20260526_RULES)
        second = get_rule_by_id(rule_id, POST_20260727_RULES)

        assert first is not None, rule_id
        assert second is not None, rule_id
        # 제2026-390호 원문이 세 별표 값을 바꾸지 않아 같은 객체를 재사용합니다.
        assert second is first, rule_id

    def test_post_registry_has_twenty_rules(self) -> None:
        """별표 1~9 를 담은 규칙 20종. 개정 전 14종에 별표 7~9 의 규칙 6종이 늘었습니다."""
        assert len(POST_20260526_RULES) == 20
        assert len(POST_20260727_RULES) == 20
        assert len({rule.rule_id for rule in POST_20260526_RULES}) == 20
        assert len({rule.rule_id for rule in POST_20260727_RULES}) == 20

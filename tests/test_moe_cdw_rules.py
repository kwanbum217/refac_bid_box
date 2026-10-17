"""환경부고시 「건설폐기물처리용역 적격업체 평가기준」 [별표] 제1~4호 규칙 계약 테스트.

낙찰방법명에 추정가격 띠만 적힌 폐기물처리용역 적격심사 공고 6종이 새 규칙으로
계산되는지, 시행일 경계에서 판이 갈리는지, 비폐기물·시·도 규칙 공고 판정이 그대로인지
고정합니다. 원문 출처와 값 표는 docs/analysis/moe_cdw_rules_apply_20261017.md 입니다.
"""

from decimal import Decimal

import pytest

from src.app.services.evaluation_rules import (
    MOE_CDW_RULES,
    POST_20260526_RULES,
    POST_20260727_RULES,
    PRE_20230501_RULES,
    PRE_20250901_RULES,
    RuleResolutionResult,
    match_rule_by_mthd_nm,
    resolve_evaluation_rule,
    resolve_evaluation_rule_from_raw_data,
    resolve_score_params,
)

BANDS = (
    (
        "적격심사제-추정가격 2억원 미만인 용역",
        "87.745",
        Decimal("70"),
        Decimal("20"),
        Decimal("95"),
    ),
    (
        "적격심사제-추정가격 5억원 미만 2억원 이상인 용역",
        "86.745",
        Decimal("60"),
        Decimal("4"),
        Decimal("95"),
    ),
    (
        "적격심사제-추정가격 15억원 미만 5억원 이상인 용역",
        "85.495",
        Decimal("50"),
        Decimal("2"),
        Decimal("95"),
    ),
    (
        "적격심사제-추정가격 30억원 미만 15억원 이상인 용역",
        "82.995",
        Decimal("30"),
        Decimal("1"),
        Decimal("95"),
    ),
    (
        "적격심사제-추정가격 100억원 미만 30억원 이상인 용역",
        "77.995",
        Decimal("30"),
        Decimal("1"),
        Decimal("90"),
    ),
    (
        "적격심사제-추정가격 100억원 이상인 용역",
        "72.995",
        Decimal("30"),
        Decimal("1"),
        Decimal("85"),
    ),
)


def _resolve(method_name: str, bid_ntce_dt, rate=None) -> RuleResolutionResult:
    return resolve_evaluation_rule(
        category="Servc",
        prearng_prce_dcsn_mthd_nm="복수예가",
        sucsfbid_mthd_nm=method_name,
        sucsfbid_lwlt_rate=rate,
        bid_ntce_dt=bid_ntce_dt,
    )


class TestMoeCdwDeclarations:
    def test_rule_count(self) -> None:
        assert len(MOE_CDW_RULES) == 6

    def test_values(self) -> None:
        for method_name, rate, b, k, t in BANDS:
            rule = match_rule_by_mthd_nm(method_name)
            assert rule is not None
            assert rule.service_type == "WASTE_MOE"
            assert rule.lwlt_rate == Decimal(rate)
            assert rule.max_price_score == b
            assert rule.multiplier == k
            assert rule.pass_threshold == t
            assert rule.base_rate == Decimal("0.90")
            assert rule.effective_date == "2025-01-02"
            assert "별표" in (rule.score_table_source or "")


class TestMoeCdwMatching:
    @pytest.mark.parametrize("method_name, rate, b, k, t", BANDS)
    def test_band_matches_moe_rule(self, method_name, rate, b, k, t) -> None:
        result = _resolve(method_name, "2026-06-10", rate)
        assert result.is_blocked is False, result.block_reason_code
        assert result.rule is not None
        assert result.rule.service_type == "WASTE_MOE"
        assert result.effective_lwlt_rate == Decimal(rate)

    @pytest.mark.parametrize("method_name, rate, b, k, t", BANDS)
    def test_default_rate_when_missing(self, method_name, rate, b, k, t) -> None:
        result = _resolve(method_name, "2026-06-10", None)
        assert result.is_blocked is False, result.block_reason_code
        assert result.rule is not None
        assert result.effective_lwlt_rate == Decimal(rate)
        assert result.rate_source == "RULE_DEFAULT"

    @pytest.mark.parametrize("method_name, rate, b, k, t", BANDS)
    def test_raw_data_entry(self, method_name, rate, b, k, t) -> None:
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
        assert result.rule.service_type == "WASTE_MOE"

    def test_regime_boundary(self) -> None:
        method_name = "적격심사제-추정가격 2억원 미만인 용역"
        before = _resolve(method_name, "2025-01-01", "87.745")
        after = _resolve(method_name, "2025-01-02", "87.745")
        assert before.is_blocked is True
        assert before.block_reason_code == "RULE_REGIME_MISMATCH"
        assert after.is_blocked is False
        assert after.rule is not None

    def test_score_params(self) -> None:
        method_name = "적격심사제-추정가격 2억원 미만인 용역"
        rule = match_rule_by_mthd_nm(method_name)
        assert rule is not None
        res = resolve_score_params(rule, 100_000_000, "2026-06-10", method_name)
        assert res.max_price_score == Decimal("70")
        assert res.multiplier == Decimal("20")
        assert res.pass_threshold == Decimal("95")


class TestMoeCdwNonRegression:
    def test_post_bundle_carries_moe(self) -> None:
        assert any(r.service_type == "WASTE_MOE" for r in POST_20260526_RULES)
        assert any(r.service_type == "WASTE_MOE" for r in POST_20260727_RULES)

    def test_pre_bundle_carries_moe(self) -> None:
        assert any(r.service_type == "WASTE_MOE" for r in PRE_20250901_RULES)
        assert any(r.service_type == "WASTE_MOE" for r in PRE_20230501_RULES)

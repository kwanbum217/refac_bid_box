"""일반용역 적격심사 개정 전 규칙(제2023-53호·제2025-257호)과 공고일 시행일 구간 라우팅 계약 테스트."""

from datetime import date, datetime
from decimal import Decimal

import pytest

from src.app.services.evaluation_rules import (
    BLOCK_CODE_RULE_NOT_FOUND,
    BLOCK_CODE_RULE_REGIME_MISMATCH,
    POST_20260526_RULES,
    PRE_20230501_RULES,
    PRE_20250901_RULES,
    PRE_20260526_RULES,
    RuleResolutionResult,
    match_rule_by_mthd_nm,
    resolve_evaluation_rule,
    resolve_evaluation_rule_from_raw_data,
)

FACILITY_METHOD = "적격심사제-시설분야용역 적격심사 추정가격 5억원 미만"
POST_FACILITY_RULE_ID = "SERVC_QUAL_POST_20260526_ATTACH_01"
PRE_20250901_FACILITY_RULE_ID = "SERVC_QUAL_PRE_20250901_ATTACH_01"
PRE_20230501_FACILITY_RULE_ID = "SERVC_QUAL_PRE_20230501_ATTACH_01"
HIGH_BASE_RATE_SERVICE_TYPES = {"FACILITY", "PASSENGER_TRANSPORT", "SW_SME"}
GENERAL_BAND_METHODS = (
    "적격심사제-추정가격 2억원 미만인 용역",
    "적격심사제-추정가격 5억원 미만 2억원 이상인 용역",
    "적격심사제-추정가격 30억원 미만 15억원 이상인 용역",
)
SUBDIVIDED_BAND_METHODS = (
    "적격심사제-추정가격 15억원 미만 5억원 이상인 용역",
    "적격심사제-추정가격 2억미만 1억이상",
    "적격심사제-추정가격 1억미만",
    "적격심사제-추정가격 2억이상",
    "적격심사제-추정가격 100억원 미만 30억원 이상인 용역",
    "적격심사제-추정가격 100억원 이상인 용역",
)


def _resolve(
    announcement_method: str,
    bid_ntce_dt: date | str | None = None,
    rate: str | None = None,
) -> RuleResolutionResult:
    return resolve_evaluation_rule(
        category="Servc",
        prearng_prce_dcsn_mthd_nm="복수예가",
        sucsfbid_mthd_nm=announcement_method,
        sucsfbid_lwlt_rate=rate,
        bid_ntce_dt=bid_ntce_dt,
    )


class TestAnnouncementDateRegimeRouting:
    """공고일로 규칙 벌을 고르는 시행일 구간 경계 검증."""

    @pytest.mark.parametrize(
        ("bid_ntce_dt", "rate", "expected_rule_id"),
        [
            ("2026-05-25 23:59:59", "87.995", PRE_20250901_FACILITY_RULE_ID),
            ("2026-05-26 00:00:00", "89.995", POST_FACILITY_RULE_ID),
            (date(2026, 5, 25), "87.995", PRE_20250901_FACILITY_RULE_ID),
            (date(2026, 5, 26), "89.995", POST_FACILITY_RULE_ID),
        ],
    )
    def test_post_regime_boundary_2026_05_26(
        self,
        bid_ntce_dt: date | str,
        rate: str,
        expected_rule_id: str,
    ) -> None:
        result = _resolve(FACILITY_METHOD, bid_ntce_dt=bid_ntce_dt, rate=rate)

        assert result.is_blocked is False
        assert result.rule is not None
        assert result.rule.rule_id == expected_rule_id

    @pytest.mark.parametrize(
        ("bid_ntce_dt", "expected_rule_id"),
        [
            ("2025-08-31 23:59:59", PRE_20230501_FACILITY_RULE_ID),
            ("2025-09-01 00:00:00", PRE_20250901_FACILITY_RULE_ID),
            (date(2025, 8, 31), PRE_20230501_FACILITY_RULE_ID),
            (datetime(2025, 9, 1, 9, 0), PRE_20250901_FACILITY_RULE_ID),
        ],
    )
    def test_pre_20250901_regime_boundary(
        self,
        bid_ntce_dt: date | str | datetime,
        expected_rule_id: str,
    ) -> None:
        result = _resolve(FACILITY_METHOD, bid_ntce_dt=bid_ntce_dt, rate="87.995")

        assert result.is_blocked is False
        assert result.rule is not None
        assert result.rule.rule_id == expected_rule_id

    def test_2023_05_01_boundary_is_inclusive(self) -> None:
        on_boundary = _resolve(FACILITY_METHOD, bid_ntce_dt="2023-05-01", rate="87.995")
        assert on_boundary.is_blocked is False
        assert on_boundary.rule is not None
        assert on_boundary.rule.rule_id == PRE_20230501_FACILITY_RULE_ID

        before_boundary = _resolve(FACILITY_METHOD, bid_ntce_dt="2023-04-30", rate="87.995")
        assert before_boundary.is_blocked is True
        assert before_boundary.block_reason_code == BLOCK_CODE_RULE_REGIME_MISMATCH
        assert before_boundary.rule is not None
        assert before_boundary.rule.rule_id == PRE_20230501_FACILITY_RULE_ID
        assert before_boundary.effective_lwlt_rate is None
        assert "2023-04-30" in (before_boundary.block_reason_message or "")

    def test_default_call_without_announcement_date_keeps_post_bundle(self) -> None:
        result = _resolve(FACILITY_METHOD, rate="89.995")

        assert result.is_blocked is False
        assert result.rule is not None
        assert result.rule.rule_id == POST_FACILITY_RULE_ID

    def test_raw_data_adapter_routes_by_announcement_date(self) -> None:
        def _raw(bid_ntce_dt: str) -> dict[str, str]:
            return {
                "prearngPrceDcsnMthdNm": "복수예가",
                "sucsfbidMthdNm": FACILITY_METHOD,
                "sucsfbidLwltRate": "87.995",
                "bidNtceDt": bid_ntce_dt,
            }

        latest = resolve_evaluation_rule_from_raw_data("Servc", _raw("2026-02-10 10:00:00"))
        earlier = resolve_evaluation_rule_from_raw_data("Servc", _raw("2025-03-15 10:00:00"))

        assert latest.is_blocked is False
        assert latest.rule is not None
        assert latest.rule.rule_id == PRE_20250901_FACILITY_RULE_ID
        assert earlier.is_blocked is False
        assert earlier.rule is not None
        assert earlier.rule.rule_id == PRE_20230501_FACILITY_RULE_ID


class TestPreRulesDeclaration:
    """개정 전 두 벌의 선언 내용과 현행 규칙과의 분리 검증."""

    def test_bundles_have_fourteen_rules_and_unique_ids(self) -> None:
        assert len(PRE_20230501_RULES) == 14
        assert len(PRE_20250901_RULES) == 14
        assert PRE_20260526_RULES == PRE_20230501_RULES + PRE_20250901_RULES
        rule_ids = [rule.rule_id for rule in PRE_20260526_RULES]
        assert len(rule_ids) == len(set(rule_ids))

    def test_effective_dates_are_fixed_per_bundle(self) -> None:
        assert {rule.effective_date for rule in PRE_20230501_RULES} == {"2023-05-01"}
        assert {rule.effective_date for rule in PRE_20250901_RULES} == {"2025-09-01"}

    @pytest.mark.parametrize("rules", [PRE_20230501_RULES, PRE_20250901_RULES])
    def test_base_rate_follows_verified_formula(
        self,
        rules: tuple,
    ) -> None:
        for rule in rules:
            expected = (
                Decimal("0.91")
                if rule.service_type in HIGH_BASE_RATE_SERVICE_TYPES
                else Decimal("0.88")
            )
            assert rule.base_rate == expected, rule.rule_id

    @pytest.mark.parametrize("rules", [PRE_20230501_RULES, PRE_20250901_RULES])
    def test_unverified_bands_are_not_declared(self, rules: tuple) -> None:
        for method in GENERAL_BAND_METHODS + SUBDIVIDED_BAND_METHODS:
            assert match_rule_by_mthd_nm(method, rules=rules) is None, method

    @pytest.mark.parametrize("rules", [PRE_20230501_RULES, PRE_20250901_RULES])
    def test_pre_only_attachments_are_declared(self, rules: tuple) -> None:
        expected_types = {
            "수리ㆍ점검용역 적격심사 고시금액 미만": "REPAIR_INSPECTION",
            "임대차 적격심사 추정가격 고시금액 미만": "LEASE",
            "수요기관 지정형 적격심사  추정가격 고시금액 미만": "DEMAND_AGENCY",
        }
        for method, service_type in expected_types.items():
            rule = match_rule_by_mthd_nm(f"적격심사제-{method}", rules=rules)
            assert rule is not None, method
            assert rule.service_type == service_type


class TestPreRegimeResolution:
    """개정 전 구간 공고가 차단 없이 계산되고 하한율 우선순위가 유지되는지 검증."""

    @pytest.mark.parametrize(
        ("bid_ntce_dt", "expected_rule_id"),
        [
            ("2025-09-01", PRE_20250901_FACILITY_RULE_ID),
            ("2026-01-15", PRE_20250901_FACILITY_RULE_ID),
            ("2025-08-31", PRE_20230501_FACILITY_RULE_ID),
            ("2023-05-01", PRE_20230501_FACILITY_RULE_ID),
        ],
    )
    def test_pre_announcement_passes_without_regime_mismatch(
        self,
        bid_ntce_dt: str,
        expected_rule_id: str,
    ) -> None:
        result = _resolve(FACILITY_METHOD, bid_ntce_dt=bid_ntce_dt, rate="87.995")

        assert result.is_blocked is False
        assert result.block_reason_code is None
        assert result.rule is not None
        assert result.rule.rule_id == expected_rule_id
        assert result.effective_lwlt_rate == Decimal("87.995")
        assert result.rate_source == "ANNOUNCEMENT"
        assert result.warnings == []

    def test_pre_rule_default_rate_is_used_when_announcement_rate_is_missing(self) -> None:
        result = _resolve(FACILITY_METHOD, bid_ntce_dt="2025-10-01", rate=None)

        assert result.is_blocked is False
        assert result.rule is not None
        assert result.rule.rule_id == PRE_20250901_FACILITY_RULE_ID
        assert result.effective_lwlt_rate == Decimal("87.995")
        assert result.rate_source == "RULE_DEFAULT"
        assert any("기본값" in warning for warning in result.warnings)

    def test_pre_announcement_rate_wins_when_it_differs_from_pre_default(self) -> None:
        result = _resolve(FACILITY_METHOD, bid_ntce_dt="2025-10-01", rate="88.500")

        assert result.is_blocked is False
        assert result.effective_lwlt_rate == Decimal("88.500")
        assert result.rate_source == "ANNOUNCEMENT"
        assert any("일치하지 않아" in warning for warning in result.warnings)

    @pytest.mark.parametrize("bid_ntce_dt", ["2025-08-27", "2025-10-01", "2026-05-25"])
    @pytest.mark.parametrize("method", GENERAL_BAND_METHODS)
    def test_pre_period_general_band_is_blocked_by_regime_mismatch(
        self,
        method: str,
        bid_ntce_dt: str,
    ) -> None:
        result = _resolve(method, bid_ntce_dt=bid_ntce_dt, rate="87.745")

        assert result.is_blocked is True
        assert result.block_reason_code == BLOCK_CODE_RULE_REGIME_MISMATCH
        assert result.rule is not None
        assert result.rule.rule_id.startswith("SERVC_QUAL_POST_20260526_")
        assert result.effective_lwlt_rate is None
        assert result.rate_source is None

    @pytest.mark.parametrize("bid_ntce_dt", ["2025-08-27", "2025-10-01", "2026-05-25"])
    @pytest.mark.parametrize("method", SUBDIVIDED_BAND_METHODS)
    def test_pre_period_subdivided_band_is_rule_not_found(
        self,
        method: str,
        bid_ntce_dt: str,
    ) -> None:
        result = _resolve(method, bid_ntce_dt=bid_ntce_dt, rate="85.495")

        assert result.is_blocked is True
        assert result.block_reason_code == BLOCK_CODE_RULE_NOT_FOUND
        assert result.rule is None

    def test_post_period_does_not_gain_pre_only_attachments(self) -> None:
        result = _resolve(
            "적격심사제-수리ㆍ점검용역 적격심사 고시금액 미만", bid_ntce_dt="2026-06-01"
        )

        assert result.is_blocked is True
        assert result.block_reason_code == BLOCK_CODE_RULE_NOT_FOUND


class TestPostRegimeRegression:
    """2026-05-26 이후 공고의 규칙 선택과 값이 그대로인지 검증."""

    def test_all_post_rules_keep_rule_id_lwlt_rate_and_base_rate(self) -> None:
        for rule in POST_20260526_RULES:
            announcement_method = f"적격심사제-{rule.patterns[0]}"
            result = _resolve(
                announcement_method, bid_ntce_dt="2026-06-01", rate=str(rule.lwlt_rate)
            )

            assert result.is_blocked is False, rule.rule_id
            assert result.rule is not None
            assert result.rule.rule_id == rule.rule_id
            assert result.rule.lwlt_rate == rule.lwlt_rate
            assert result.rule.base_rate == rule.base_rate
            assert result.effective_lwlt_rate == rule.lwlt_rate
            assert result.rate_source == "ANNOUNCEMENT"

    def test_post_registry_is_untouched(self) -> None:
        assert len(POST_20260526_RULES) == 14
        assert {rule.effective_date for rule in POST_20260526_RULES} == {"2026-05-26"}


class TestExplicitRulesCalls:
    """rules 를 명시한 호출이 라우팅 없이 주어진 벌을 그대로 쓰는지 검증."""

    def test_explicit_post_rules_keep_regime_mismatch_for_pre_announcement(self) -> None:
        result = resolve_evaluation_rule(
            category="Servc",
            prearng_prce_dcsn_mthd_nm="복수예가",
            sucsfbid_mthd_nm=FACILITY_METHOD,
            sucsfbid_lwlt_rate="87.995",
            rules=POST_20260526_RULES,
            bid_ntce_dt="2025-08-27",
        )

        assert result.is_blocked is True
        assert result.block_reason_code == BLOCK_CODE_RULE_REGIME_MISMATCH
        assert result.rule is not None
        assert result.rule.rule_id == POST_FACILITY_RULE_ID
        assert result.effective_lwlt_rate is None

    @pytest.mark.parametrize(
        ("rules", "expected_rule_id"),
        [
            (PRE_20230501_RULES, PRE_20230501_FACILITY_RULE_ID),
            (PRE_20250901_RULES, PRE_20250901_FACILITY_RULE_ID),
        ],
    )
    def test_explicit_pre_rules_are_honored(self, rules: tuple, expected_rule_id: str) -> None:
        result = resolve_evaluation_rule(
            category="Servc",
            prearng_prce_dcsn_mthd_nm="복수예가",
            sucsfbid_mthd_nm=FACILITY_METHOD,
            sucsfbid_lwlt_rate="87.995",
            rules=rules,
            bid_ntce_dt="2025-10-01",
        )

        assert result.is_blocked is False
        assert result.rule is not None
        assert result.rule.rule_id == expected_rule_id

    def test_match_rule_by_mthd_nm_default_stays_post_bundle(self) -> None:
        method = "적격심사제-수리ㆍ점검용역 적격심사 고시금액 미만"

        assert match_rule_by_mthd_nm(method) is None
        matched = match_rule_by_mthd_nm(method, rules=PRE_20250901_RULES)
        assert matched is not None
        assert matched.rule_id == "SERVC_QUAL_PRE_20250901_ATTACH_15"

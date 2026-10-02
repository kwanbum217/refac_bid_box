"""일반용역 적격심사 개정 전 규칙(제2023-53호·제2025-257호)과 공고일 시행일 구간 라우팅 계약 테스트."""

from datetime import date, datetime
from decimal import Decimal

import pytest

from src.app.services.evaluation_rules import (
    BLOCK_CODE_RULE_NOT_FOUND,
    BLOCK_CODE_RULE_REGIME_MISMATCH,
    POST_20260526_RULES,
    POST_20260727_RULES,
    PRE_20230501_RULES,
    PRE_20250901_RULES,
    PRE_20260526_RULES,
    RuleResolutionResult,
    match_rule_by_mthd_nm,
    resolve_evaluation_rule,
    resolve_evaluation_rule_from_raw_data,
)

FACILITY_METHOD = "적격심사제-시설분야용역 적격심사 추정가격 5억원 미만"
INSURANCE_METHOD = "적격심사제-보험용역 적격심사 추정가격 5억원미만"
PASSENGER_METHOD = "적격심사제-여객 육상운송용역 적격심사 추정가격 5억원미만"
SW_SME_METHOD = "적격심사제-소프트웨어용역(중소기업자간 경쟁제품 대상) 적격심사 추정가격 5억원 미만"
POST_FACILITY_RULE_ID = "SERVC_QUAL_POST_20260526_ATTACH_01"
POST_INSURANCE_RULE_ID = "SERVC_QUAL_POST_20260526_ATTACH_02"
POST_PASSENGER_RULE_ID = "SERVC_QUAL_POST_20260526_ATTACH_03"
POST_SW_SME_RULE_ID = "SERVC_QUAL_POST_20260526_ATTACH_04"
POST_20260727_PASSENGER_RULE_ID = "SERVC_QUAL_POST_20260727_ATTACH_03"
POST_20260727_SW_SME_RULE_ID = "SERVC_QUAL_POST_20260727_ATTACH_04"
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


class TestPostRegimeRouting20260727:
    """제2026-390호(2026-07-27 시행) 구간 라우팅과 기준비율 검증."""

    def test_260_bundle_rates_at_2026_06_01(self) -> None:
        facility = _resolve(FACILITY_METHOD, bid_ntce_dt="2026-06-01", rate="89.995")
        assert facility.is_blocked is False
        assert facility.rule is not None
        assert facility.rule.rule_id == POST_FACILITY_RULE_ID
        assert facility.rule.base_rate == Decimal("0.93")
        assert facility.effective_lwlt_rate == Decimal("89.995")

        insurance = _resolve(INSURANCE_METHOD, bid_ntce_dt="2026-06-01", rate="47.995")
        assert insurance.rule is not None
        assert insurance.rule.rule_id == POST_INSURANCE_RULE_ID
        assert insurance.rule.base_rate == Decimal("0.88")
        assert insurance.effective_lwlt_rate == Decimal("47.995")

        passenger = _resolve(PASSENGER_METHOD, bid_ntce_dt="2026-06-01", rate="87.995")
        assert passenger.rule is not None
        assert passenger.rule.rule_id == POST_PASSENGER_RULE_ID
        assert passenger.rule.base_rate == Decimal("0.91")
        assert passenger.effective_lwlt_rate == Decimal("87.995")

        sw_sme = _resolve(SW_SME_METHOD, bid_ntce_dt="2026-06-01", rate="87.995")
        assert sw_sme.rule is not None
        assert sw_sme.rule.rule_id == POST_SW_SME_RULE_ID
        assert sw_sme.rule.base_rate == Decimal("0.91")
        assert sw_sme.effective_lwlt_rate == Decimal("87.995")

    def test_2026_07_27_boundary_upgrades_passenger_and_sw_sme(self) -> None:
        before = _resolve(PASSENGER_METHOD, bid_ntce_dt="2026-07-26", rate="87.995")
        assert before.is_blocked is False
        assert before.rule is not None
        assert before.rule.rule_id == POST_PASSENGER_RULE_ID
        assert before.rule.base_rate == Decimal("0.91")
        assert before.effective_lwlt_rate == Decimal("87.995")

        on = _resolve(PASSENGER_METHOD, bid_ntce_dt="2026-07-27", rate="89.995")
        assert on.is_blocked is False
        assert on.rule is not None
        assert on.rule.rule_id == POST_20260727_PASSENGER_RULE_ID
        assert on.rule.base_rate == Decimal("0.93")
        assert on.effective_lwlt_rate == Decimal("89.995")

        sw_sme = _resolve(SW_SME_METHOD, bid_ntce_dt="2026-07-27", rate="89.995")
        assert sw_sme.rule is not None
        assert sw_sme.rule.rule_id == POST_20260727_SW_SME_RULE_ID
        assert sw_sme.rule.base_rate == Decimal("0.93")
        assert sw_sme.effective_lwlt_rate == Decimal("89.995")

        facility = _resolve(FACILITY_METHOD, bid_ntce_dt="2026-07-27", rate="89.995")
        assert facility.rule is not None
        assert facility.rule.rule_id == POST_FACILITY_RULE_ID
        assert facility.rule.base_rate == Decimal("0.93")

    def test_default_call_without_announcement_date_uses_2026_07_27_bundle(self) -> None:
        sw_sme = _resolve(SW_SME_METHOD, rate="89.995")
        assert sw_sme.is_blocked is False
        assert sw_sme.rule is not None
        assert sw_sme.rule.rule_id == POST_20260727_SW_SME_RULE_ID
        assert sw_sme.rule.base_rate == Decimal("0.93")

        passenger = _resolve(PASSENGER_METHOD, rate="89.995")
        assert passenger.rule is not None
        assert passenger.rule.rule_id == POST_20260727_PASSENGER_RULE_ID

        facility = _resolve(FACILITY_METHOD, rate="89.995")
        assert facility.rule is not None
        assert facility.rule.rule_id == POST_FACILITY_RULE_ID


class TestPost20260727Declaration:
    """제2026-390호 벌의 선언 내용과 제2026-260호 벌 객체 재사용 검증."""

    def test_bundle_has_fourteen_unique_ids(self) -> None:
        assert len(POST_20260727_RULES) == 14
        rule_ids = [rule.rule_id for rule in POST_20260727_RULES]
        assert len(rule_ids) == len(set(rule_ids))
        assert rule_ids == [
            "SERVC_QUAL_POST_20260526_ATTACH_01",
            "SERVC_QUAL_POST_20260526_ATTACH_02",
            POST_20260727_PASSENGER_RULE_ID,
            POST_20260727_SW_SME_RULE_ID,
            *[f"SERVC_QUAL_POST_20260526_ATTACH_{index:02d}" for index in range(5, 15)],
        ]

    def test_only_passenger_and_sw_sme_are_new_objects(self) -> None:
        assert POST_20260727_RULES[0] is POST_20260526_RULES[0]
        assert POST_20260727_RULES[1] is POST_20260526_RULES[1]
        for reused, original in zip(POST_20260727_RULES[4:], POST_20260526_RULES[4:], strict=True):
            assert reused is original
        rule_ids = {rule.rule_id for rule in POST_20260727_RULES}
        assert POST_PASSENGER_RULE_ID not in rule_ids
        assert POST_SW_SME_RULE_ID not in rule_ids

    def test_upgraded_rules_cite_390_notice(self) -> None:
        upgraded = {rule.rule_id: rule for rule in POST_20260727_RULES}
        for rule_id in (POST_20260727_PASSENGER_RULE_ID, POST_20260727_SW_SME_RULE_ID):
            rule = upgraded[rule_id]
            assert rule.effective_date == "2026-07-27"
            assert rule.base_rate == Decimal("0.93")
            assert rule.lwlt_rate == Decimal("89.995")
            assert "제2026-390호" in rule.source

    def test_260_upgraded_rules_cite_260_notice(self) -> None:
        for rule in POST_20260526_RULES[:4]:
            assert "제2026-260호" in rule.source


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


class TestScoreTableDeclaration:
    """개정 3세대 42건의 배점표(B·k·T) 판정: 확정값만 실리고 미확정은 None."""

    def test_all_rules_carry_a_declaration_source(self) -> None:
        """42건 전부가 출처 또는 미확인 사유를 남긴다."""
        rules = PRE_20230501_RULES + PRE_20250901_RULES + POST_20260526_RULES
        assert len(rules) == 42
        for rule in rules:
            assert rule.score_table_source, rule.rule_id
            assert rule.score_table_source.strip() != ""

    def test_pre_20230501_matches_original_attachments(self) -> None:
        """제2023-53호 판은 원문 별표에서 확인한 값이 같은 구조의 2025-09-01 판 선언과 같다."""
        pre_2025 = {rule.rule_id.split("_ATTACH_")[1]: rule for rule in PRE_20250901_RULES}
        for rule in PRE_20230501_RULES:
            counterpart = pre_2025[rule.rule_id.split("_ATTACH_")[1]]
            assert rule.max_price_score == counterpart.max_price_score, rule.rule_id
            assert rule.multiplier == counterpart.multiplier, rule.rule_id
            assert rule.pass_threshold == counterpart.pass_threshold, rule.rule_id
            assert rule.base_rate == counterpart.base_rate, rule.rule_id
            source = rule.score_table_source or ""
            assert "servc_2023_53_original_attachments_20261003.md:17," in source
            assert "제2023-53호 원문" in source
            assert ("조사 범위 " + "밖") not in source
            assert "동일 추정" not in source

    def test_pre_20230501_original_values(self) -> None:
        """원문 별표 수식의 k 와 배점한도 단일값을 규칙별로 고정한다."""
        by_id = {rule.rule_id.split("_ATTACH_")[1]: rule for rule in PRE_20230501_RULES}
        expected = {
            "01": (None, Decimal("5"), Decimal("85")),
            "02": (None, Decimal("0.375"), Decimal("85")),
            "03": (None, Decimal("4"), Decimal("88")),
            "04": (None, Decimal("4"), Decimal("88")),
            "05": (None, None, Decimal("85")),
            "06": (Decimal("70"), Decimal("4"), Decimal("85")),
            "07": (None, Decimal("2"), Decimal("85")),
            "08": (Decimal("70"), Decimal("4"), Decimal("85")),
            "09": (None, Decimal("2"), Decimal("85")),
            "10": (Decimal("70"), Decimal("4"), Decimal("85")),
            "11": (None, Decimal("2"), Decimal("85")),
            "15": (None, None, Decimal("85")),
            "16": (Decimal("70"), None, Decimal("85")),
            "17": (None, None, Decimal("85")),
        }
        assert set(by_id) == set(expected)
        for suffix, values in expected.items():
            rule = by_id[suffix]
            assert (rule.max_price_score, rule.multiplier, rule.pass_threshold) == values, suffix

    def test_pre_20250901_confirmed_values(self) -> None:
        """제2025-257호·제2026-15호 판의 확정 배점표."""
        by_id = {rule.rule_id: rule for rule in PRE_20250901_RULES}
        academic_under = by_id["SERVC_QUAL_PRE_20250901_ATTACH_06"]
        assert academic_under.max_price_score == Decimal("70")
        assert academic_under.multiplier == Decimal("4")
        assert academic_under.pass_threshold == Decimal("85")

        insurance = by_id["SERVC_QUAL_PRE_20250901_ATTACH_02"]
        assert insurance.max_price_score is None
        assert insurance.multiplier == Decimal("0.375")
        assert insurance.pass_threshold == Decimal("85")

        lease = by_id["SERVC_QUAL_PRE_20250901_ATTACH_16"]
        assert lease.max_price_score == Decimal("70")
        assert lease.multiplier is None

    def test_four_rules_are_declared_by_revision_generation(self) -> None:
        """시설·여객·SW 대상·비대상은 개정 세대별로 k·T를 확정한다."""
        expected = {
            "ATTACH_01": ("5", "85", {"PRE": "163", "POST": "103"}),
            "ATTACH_03": ("4", "88", {"PRE": "167", "POST": "107"}),
            "ATTACH_04": ("4", "88", {"PRE": "165", "POST": "105"}),
            "ATTACH_05": (None, "85", {"PRE": "164", "POST": "104"}),
        }
        for rules, regime, source_path in (
            (
                PRE_20250901_RULES,
                "PRE",
                "docs/analysis/servc_pre_rules_2025_2026_tables_20260929.md",
            ),
            (
                POST_20260526_RULES,
                "POST",
                "docs/analysis/servc_post_rules_audit_20260929.md",
            ),
        ):
            by_suffix = {"_".join(rule.rule_id.rsplit("_", 2)[-2:]): rule for rule in rules}
            for suffix, (multiplier, threshold, source_rows) in expected.items():
                rule = by_suffix[suffix]
                assert rule.max_price_score is None
                assert rule.multiplier == (Decimal(multiplier) if multiplier is not None else None)
                assert rule.pass_threshold == Decimal(threshold)
                assert f"{source_path}:{source_rows[regime]}" in (rule.score_table_source or "")
                assert "174" in (rule.score_table_source or "")
                assert ("문서 간 " + "불일치") not in (rule.score_table_source or "")

    def test_unconfirmed_fields_explain_price_and_notice_amount_bands(self) -> None:
        """미확정 필드는 개정 세대 차이가 아니라 단일값으로 합칠 수 없는 조건 축을 설명한다."""
        for rules in (PRE_20250901_RULES, POST_20260526_RULES):
            by_id = {rule.rule_id.rsplit("_", 1)[-1]: rule for rule in rules}
            for suffix in ("01", "03", "04", "05"):
                source = by_id[suffix].score_table_source or ""
                assert ("문서 간 " + "불일치") not in source
                assert "B는 추정가격 5억원" in source
            non_target = by_id["05"]
            assert non_target.multiplier is None
            assert "k는 고시금액 미만 4/이상 2" in (non_target.score_table_source or "")

    def test_score_table_threshold_exception_matches_multiplier_rules(self) -> None:
        """여객·SW 대상만 T=88이며 나머지 규칙은 T=85이다."""
        for rules in (PRE_20250901_RULES, POST_20260526_RULES):
            for rule in rules:
                if rule.pass_threshold is None:
                    continue
                expected = (
                    Decimal("88")
                    if rule.rule_id.endswith(("ATTACH_03", "ATTACH_04"))
                    else Decimal("85")
                )
                assert rule.pass_threshold == expected, rule.rule_id

    def test_post_confirmed_values_and_unmapped_bands(self) -> None:
        """제2026-260호 판의 확정값과 일반 띠 미확인."""
        by_id = {rule.rule_id: rule for rule in POST_20260526_RULES}
        academic_under = by_id["SERVC_QUAL_POST_20260526_ATTACH_06"]
        assert academic_under.max_price_score == Decimal("70")
        assert academic_under.multiplier == Decimal("4")
        assert academic_under.pass_threshold == Decimal("85")

        facility = by_id["SERVC_QUAL_POST_20260526_ATTACH_01"]
        assert facility.max_price_score is None
        assert facility.multiplier == Decimal("5")
        assert facility.pass_threshold == Decimal("85")
        for index in (12, 13, 14):
            rule = by_id[f"SERVC_QUAL_POST_20260526_ATTACH_{index:02d}"]
            assert rule.max_price_score is None
            assert rule.multiplier is None
            assert rule.pass_threshold is None

    def test_confirmed_values_cite_a_document_path(self) -> None:
        """값을 실은 규칙은 근거 문서 경로가 사유 문자열에 남는다."""
        for rules in (PRE_20250901_RULES, POST_20260526_RULES):
            for rule in rules:
                if (
                    rule.max_price_score is None
                    and rule.multiplier is None
                    and rule.pass_threshold is None
                ):
                    continue
                assert "docs/analysis/" in (rule.score_table_source or ""), rule.rule_id

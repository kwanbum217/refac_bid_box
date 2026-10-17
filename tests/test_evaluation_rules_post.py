"""개정 후(제2026-260호·제2026-390호) 일반용역 적격심사 별표 레지스트리 계약 테스트.

개정 후 두 벌의 선언 내용, 390 벌의 260 벌 객체 재사용, 그리고 선언한 식별 문자열이
전부 자기 규칙으로 되돌아오는지(다른 규칙에 빼앗기지 않는지)를 고정합니다. 별표 7~9 의
원문 대조 근거는 docs/analysis/post_rev_old_annex_apply_20261017.md 입니다.
"""

from decimal import Decimal

import pytest

from src.app.services.evaluation_rules import (
    POST_20260526_RULES,
    POST_20260727_RULES,
    EvaluationRule,
    match_rule_by_mthd_nm,
)

# 제2026-260호 원문 별표별 기준비율(감사 문서 3.3절)과 낙찰하한율·통과점수입니다.
# 별표 7~9 는 제2026-390호 분야별 낙찰하한율 안내에서도 같은 값입니다.
EXPECTED_260 = {
    "01": (Decimal("0.93"), Decimal("89.995"), Decimal("85")),
    "02": (Decimal("0.88"), Decimal("47.995"), Decimal("85")),
    "03": (Decimal("0.91"), Decimal("87.995"), Decimal("88")),
    "04": (Decimal("0.91"), Decimal("87.995"), Decimal("88")),
    "05": (Decimal("0.90"), Decimal("86.245"), Decimal("85")),
    "06": (Decimal("0.90"), Decimal("86.245"), Decimal("85")),
    "07": (Decimal("0.90"), Decimal("82.495"), Decimal("85")),
    "08": (Decimal("0.90"), Decimal("86.245"), Decimal("85")),
    "09": (Decimal("0.90"), Decimal("82.495"), Decimal("85")),
    "10": (Decimal("0.90"), Decimal("86.245"), Decimal("85")),
    "11": (Decimal("0.90"), Decimal("82.495"), Decimal("85")),
    "12": (Decimal("0.90"), Decimal("87.745"), None),
    "13": (Decimal("0.90"), Decimal("86.745"), None),
    "14": (Decimal("0.90"), Decimal("82.995"), None),
    "15": (Decimal("0.90"), Decimal("86.245"), Decimal("85")),
    "16": (Decimal("0.90"), Decimal("82.495"), Decimal("85")),
    "17": (Decimal("0.90"), Decimal("86.245"), Decimal("85")),
    "18": (Decimal("0.90"), Decimal("82.495"), Decimal("85")),
    "19": (Decimal("0.90"), Decimal("86.245"), Decimal("85")),
    "20": (Decimal("0.90"), Decimal("82.495"), Decimal("85")),
}

# 제2026-390호 개정 전문의 별표별 계산식 기준값입니다. 여객·SW(대상)만 기준비율과
# 낙찰하한율이 오르고 나머지는 제2026-260호 값 그대로입니다.
EXPECTED_390_OVERRIDES = {
    "03": (Decimal("0.93"), Decimal("89.995"), Decimal("88")),
    "04": (Decimal("0.93"), Decimal("89.995"), Decimal("88")),
}

PASSENGER_RULE_ID = "SERVC_QUAL_POST_20260727_ATTACH_03"
SW_SME_RULE_ID = "SERVC_QUAL_POST_20260727_ATTACH_04"


def _by_attachment(rules: tuple[EvaluationRule, ...]) -> dict[str, EvaluationRule]:
    return {rule.rule_id.rsplit("_ATTACH_", 1)[1]: rule for rule in rules}


class TestPostRegistryShape:
    """개정 후 두 벌의 크기·식별자·시행일 계약."""

    def test_bundle_sizes_and_unique_ids(self) -> None:
        assert len(POST_20260526_RULES) == 20
        assert len(POST_20260727_RULES) == 20
        for rules in (POST_20260526_RULES, POST_20260727_RULES):
            rule_ids = [rule.rule_id for rule in rules]
            assert len(rule_ids) == len(set(rule_ids))

    def test_20260526_bundle_is_all_260(self) -> None:
        assert {rule.effective_date for rule in POST_20260526_RULES} == {"2026-05-26"}
        assert all(
            rule.rule_id.startswith("SERVC_QUAL_POST_20260526_ATTACH_")
            for rule in POST_20260526_RULES
        )

    def test_20260727_bundle_effective_dates(self) -> None:
        for rule in POST_20260727_RULES:
            assert rule.effective_date in {"2026-05-26", "2026-07-27"}, rule.rule_id

    def test_only_passenger_and_sw_sme_are_new_objects(self) -> None:
        """제2026-390호는 두 별표만 새 객체이고 나머지는 제2026-260호 객체를 재사용한다."""
        by_id_260 = {rule.rule_id: rule for rule in POST_20260526_RULES}
        for rule in POST_20260727_RULES:
            if rule.rule_id in {PASSENGER_RULE_ID, SW_SME_RULE_ID}:
                continue
            assert by_id_260[rule.rule_id] is rule, rule.rule_id

        # 여객·SW(대상)은 기준비율·낙찰하한율이 올라 제2026-390호 전용 객체로 다시 섰습니다.
        assert POST_20260727_RULES[2].rule_id == PASSENGER_RULE_ID
        assert POST_20260727_RULES[3].rule_id == SW_SME_RULE_ID
        assert POST_20260727_RULES[2] is not POST_20260526_RULES[2]
        assert POST_20260727_RULES[3] is not POST_20260526_RULES[3]


class TestPostDeclaredValues:
    """원문에서 확인한 기준비율·낙찰하한율·통과점수를 규칙별로 고정한다."""

    @pytest.mark.parametrize("attachment", sorted(EXPECTED_260))
    def test_20260526_values(self, attachment: str) -> None:
        rule = _by_attachment(POST_20260526_RULES)[attachment]
        base_rate, lwlt_rate, pass_threshold = EXPECTED_260[attachment]

        assert rule.base_rate == base_rate, rule.rule_id
        assert rule.lwlt_rate == lwlt_rate, rule.rule_id
        assert rule.pass_threshold == pass_threshold, rule.rule_id

    @pytest.mark.parametrize("attachment", sorted(EXPECTED_260))
    def test_20260727_values(self, attachment: str) -> None:
        rule = _by_attachment(POST_20260727_RULES)[attachment]
        expected = EXPECTED_390_OVERRIDES.get(attachment, EXPECTED_260[attachment])

        assert rule.base_rate == expected[0], rule.rule_id
        assert rule.lwlt_rate == expected[1], rule.rule_id
        assert rule.pass_threshold == expected[2], rule.rule_id

    def test_every_rule_declares_a_score_table_source(self) -> None:
        for rules in (POST_20260526_RULES, POST_20260727_RULES):
            for rule in rules:
                assert rule.score_table_source, rule.rule_id
                assert rule.score_table_source.strip() != "", rule.rule_id

    def test_star_table_7_8_9_rules_have_no_reason_placeholder(self) -> None:
        """별표 7~9 는 원문으로 값이 확정됐으므로 미확인 사유가 붙지 않는다."""
        for attachment in ("15", "16", "17", "18", "19", "20"):
            rule = _by_attachment(POST_20260526_RULES)[attachment]
            source = rule.score_table_source or ""
            assert "미확인" not in source, rule.rule_id
            assert "별표" in source, rule.rule_id


class TestPatternRoundTrip:
    """선언한 식별 문자열이 전부 자기 규칙으로 되돌아오는지 검증한다."""

    @pytest.mark.parametrize("rules", [POST_20260526_RULES, POST_20260727_RULES])
    def test_every_pattern_maps_to_its_own_rule(self, rules: tuple[EvaluationRule, ...]) -> None:
        for rule in rules:
            assert rule.patterns, rule.rule_id
            for pattern in rule.patterns:
                method_name = f"적격심사제-{pattern}"
                matched = match_rule_by_mthd_nm(method_name, rules=rules)
                assert matched is not None, (rule.rule_id, pattern)
                assert matched.rule_id == rule.rule_id, (rule.rule_id, pattern)

    def test_empty_or_blank_method_name_matches_nothing(self) -> None:
        for rules in (POST_20260526_RULES, POST_20260727_RULES):
            assert match_rule_by_mthd_nm("", rules=rules) is None
            assert match_rule_by_mthd_nm("   ", rules=rules) is None

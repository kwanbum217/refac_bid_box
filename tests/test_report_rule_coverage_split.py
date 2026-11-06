"""규칙 커버리지 원장 BLOCKED 분리 집계 시험 (DB 없이).

차단(BLOCKED)을 사용자 입력 필요(manual_input)와 자동 계산 불가(not_computable)로
나누는 상수·분류·원장 집계를 고정 입력으로 검사합니다.
"""

from __future__ import annotations

from decimal import Decimal

from scripts import report_rule_coverage as ledger_script
from src.app.services.evaluation_rules import (
    RULE_SCOPE_ALL,
    EvaluationRule,
    RuleResolutionResult,
)

EXPECTED_MANUAL_CODES = {
    "MANUAL_EVALUATION",
    "LOCAL_RULE_NOT_FOUND",
    "LOCAL_SERVICE_TYPE_UNRESOLVED",
}


def _rule(rule_id: str, scope: str, **kwargs) -> EvaluationRule:
    return EvaluationRule(
        rule_id=rule_id,
        service_type="GENERAL",
        table_name="시험 별표",
        description="시험용",
        effective_date="2020-01-01",
        source="시험",
        patterns=(),
        lwlt_rate=Decimal("80"),
        institution_scope=scope,
        **kwargs,
    )


def _pps_rule(rule_id: str = "R_PPS") -> EvaluationRule:
    return _rule(rule_id, RULE_SCOPE_ALL)


def _record(
    code: str, name: str | None, result: RuleResolutionResult | None, error_type: str | None = None
) -> dict:
    return {
        "dminstt_cd": code,
        "dminstt_nm": name,
        "jurisdiction": None,
        "contract_regime": None,
        "result": result,
        "error_type": error_type,
    }


def _blocked(block_code: str) -> RuleResolutionResult:
    return RuleResolutionResult(is_blocked=True, block_reason_code=block_code)


def _fixed_records() -> list[dict]:
    return [
        _record("A", "기관A", _blocked("MANUAL_EVALUATION")),
        _record("A", "기관A", _blocked("MANUAL_EVALUATION")),
        _record("A", "기관A", _blocked("NON_PRED_PRICE")),
        _record("A", "기관A", RuleResolutionResult(is_blocked=False, rule=_pps_rule())),
        _record("B", "기관B", _blocked("LOCAL_RULE_NOT_FOUND")),
        _record("B", "기관B", _blocked("LOCAL_SERVICE_TYPE_UNRESOLVED")),
        _record("B", "기관B", _blocked("RULE_REGIME_MISMATCH")),
        _record("B", "기관B", _blocked("RULE_NOT_FOUND")),
        _record("B", "기관B", None, "ValueError"),
        _record("B", "기관B", RuleResolutionResult(is_blocked=False, rule=_pps_rule())),
    ]


def _build(records: list[dict], min_announcements: int = 1) -> dict:
    return ledger_script.build_ledger(
        records,
        filter_meta={"months": 12},
        min_announcements=min_announcements,
        generated_at="2026-11-06",
    )


def test_manual_input_codes_match_documented_basis() -> None:
    assert ledger_script.MANUAL_INPUT_BLOCK_CODES == EXPECTED_MANUAL_CODES
    assert ledger_script.BLOCKED_CATEGORIES == (
        ledger_script.BLOCKED_CATEGORY_MANUAL_INPUT,
        ledger_script.BLOCKED_CATEGORY_NOT_COMPUTABLE,
    )


def test_blocked_category_splits_manual_input_from_not_computable() -> None:
    for code in EXPECTED_MANUAL_CODES:
        assert ledger_script.blocked_category(code) == ledger_script.BLOCKED_CATEGORY_MANUAL_INPUT
    for code in ("NON_PRED_PRICE", "RULE_NOT_FOUND", "RULE_REGIME_MISMATCH", None):
        assert ledger_script.blocked_category(code) == ledger_script.BLOCKED_CATEGORY_NOT_COMPUTABLE


def test_totals_blocked_breakdown_splits_codes() -> None:
    ledger = _build(_fixed_records())
    breakdown = ledger["totals"]["blocked_breakdown"]

    assert list(breakdown) == list(ledger_script.BLOCKED_CATEGORIES)
    assert breakdown[ledger_script.BLOCKED_CATEGORY_MANUAL_INPUT] == {
        "announcements": 4,
        "codes": {
            "MANUAL_EVALUATION": 2,
            "LOCAL_RULE_NOT_FOUND": 1,
            "LOCAL_SERVICE_TYPE_UNRESOLVED": 1,
        },
    }
    assert breakdown[ledger_script.BLOCKED_CATEGORY_NOT_COMPUTABLE] == {
        "announcements": 3,
        "codes": {"NON_PRED_PRICE": 1, "RULE_REGIME_MISMATCH": 1, "RULE_NOT_FOUND": 1},
    }
    assert (
        sum(item["announcements"] for item in breakdown.values())
        == ledger["totals"]["applied_scope"][ledger_script.LEDGER_SCOPE_BLOCKED]["announcements"]
    )
    assert "ValueError" not in breakdown[ledger_script.BLOCKED_CATEGORY_NOT_COMPUTABLE]["codes"]


def test_institution_blocked_breakdown_is_separate_field() -> None:
    ledger = _build(_fixed_records())
    by_code = {item["dminstt_cd"]: item for item in ledger["institutions"]}

    assert by_code["A"]["blocked_breakdown"] == {
        "manual_input": {"announcements": 2, "codes": {"MANUAL_EVALUATION": 2}},
        "not_computable": {"announcements": 1, "codes": {"NON_PRED_PRICE": 1}},
    }
    assert by_code["B"]["blocked_breakdown"] == {
        "manual_input": {
            "announcements": 2,
            "codes": {"LOCAL_RULE_NOT_FOUND": 1, "LOCAL_SERVICE_TYPE_UNRESOLVED": 1},
        },
        "not_computable": {
            "announcements": 2,
            "codes": {"RULE_REGIME_MISMATCH": 1, "RULE_NOT_FOUND": 1},
        },
    }
    assert "blocked_breakdown" not in by_code["A"]["scope_counts"]
    assert by_code["A"]["scope_counts"] == {
        ledger_script.LEDGER_SCOPE_BLOCKED: 3,
        ledger_script.LEDGER_SCOPE_PPS_DEFAULT: 1,
    }


def test_broken_down_codes_are_subset_of_block_codes() -> None:
    ledger = _build(_fixed_records())
    for item in ledger["institutions"]:
        for summary in item["blocked_breakdown"].values():
            assert sum(summary["codes"].values()) == summary["announcements"]
            for code, count in summary["codes"].items():
                assert item["block_codes"][code] == count


def test_totals_breakdown_includes_tail_institutions() -> None:
    records = [
        _record("A", "기관A", RuleResolutionResult(is_blocked=False, rule=_pps_rule())),
        _record("A", "기관A", RuleResolutionResult(is_blocked=False, rule=_pps_rule())),
        _record("B", "기관B", _blocked("MANUAL_EVALUATION")),
        _record("C", "기관C", None, "ValueError"),
    ]
    ledger = _build(records, min_announcements=2)

    assert [item["dminstt_cd"] for item in ledger["institutions"]] == ["A"]
    assert ledger["tail"]["institutions"] == 2
    manual = ledger["totals"]["blocked_breakdown"][ledger_script.BLOCKED_CATEGORY_MANUAL_INPUT]
    assert manual == {"announcements": 1, "codes": {"MANUAL_EVALUATION": 1}}
    assert ledger["institutions"][0]["blocked_breakdown"] == {
        "manual_input": {"announcements": 0, "codes": {}},
        "not_computable": {"announcements": 0, "codes": {}},
    }


def test_existing_blocked_fields_keep_their_meaning() -> None:
    ledger = _build(_fixed_records())
    totals = ledger["totals"]

    assert totals["applied_scope"][ledger_script.LEDGER_SCOPE_BLOCKED] == {
        "announcements": 7,
        "ratio": 0.7,
    }
    assert totals["applied_scope"][ledger_script.LEDGER_SCOPE_ERROR] == {
        "announcements": 1,
        "ratio": 0.1,
    }
    by_code = {item["dminstt_cd"]: item for item in ledger["institutions"]}
    assert by_code["A"]["block_codes"] == {"MANUAL_EVALUATION": 2, "NON_PRED_PRICE": 1}
    assert by_code["B"]["block_codes"] == {
        "LOCAL_RULE_NOT_FOUND": 1,
        "LOCAL_SERVICE_TYPE_UNRESOLVED": 1,
        "RULE_REGIME_MISMATCH": 1,
        "RULE_NOT_FOUND": 1,
        "ValueError": 1,
    }

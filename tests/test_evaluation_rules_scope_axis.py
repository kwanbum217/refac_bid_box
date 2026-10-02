from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.app.api.v1.evaluations import _is_local_contract, _save_snapshot_async
from src.app.services.evaluation_rules import (
    BLOCK_CODE_RULE_SCOPE_AMBIGUOUS,
    POST_20260727_RULES,
    PRE_20230501_RULES,
    PRE_20250901_RULES,
    RULE_SCOPE_ALL,
    RULE_SCOPE_INSTITUTION,
    RULE_SCOPE_REGION,
    EvaluationRule,
    extract_contract_regime,
    resolve_evaluation_rule,
    resolve_evaluation_rule_from_raw_data,
)

METHOD = "적격심사제-보험용역 적격심사 추정가격 5억원미만"
BASE = next(rule for rule in POST_20260727_RULES if rule.service_type == "INSURANCE")


def _resolve(rules: tuple[EvaluationRule, ...], **kwargs: object):
    return resolve_evaluation_rule(
        category="Servc",
        prearng_prce_dcsn_mthd_nm="복수예가",
        sucsfbid_mthd_nm=METHOD,
        rules=rules,
        **kwargs,
    )


def test_registered_rules_default_to_common_and_unknown_regime() -> None:
    rules = PRE_20230501_RULES + PRE_20250901_RULES + POST_20260727_RULES
    assert rules
    assert all(rule.institution_scope == RULE_SCOPE_ALL for rule in rules)
    assert all(rule.contract_regime is None for rule in rules)


def test_matching_institution_rule_wins_over_common_rule() -> None:
    scoped = replace(
        BASE, rule_id="INST", institution_scope=RULE_SCOPE_INSTITUTION, institution_code="123"
    )
    result = _resolve((BASE, scoped), institution_code="123")
    assert result.rule == scoped
    assert result.scope_stage == RULE_SCOPE_INSTITUTION


def test_institution_precedes_region_and_region_precedes_common() -> None:
    regional = replace(
        BASE, rule_id="REGION", institution_scope=RULE_SCOPE_REGION, region_code="11"
    )
    institutional = replace(
        BASE, rule_id="INST", institution_scope=RULE_SCOPE_INSTITUTION, institution_code="123"
    )
    result = _resolve((BASE, regional, institutional), institution_code="123", region_code="11")
    assert result.rule == institutional
    assert result.scope_stage == RULE_SCOPE_INSTITUTION
    regional_result = _resolve((BASE, regional), region_code="11")
    assert regional_result.rule == regional
    assert regional_result.scope_stage == RULE_SCOPE_REGION


def test_institution_mismatch_falls_back_to_common() -> None:
    scoped = replace(
        BASE, rule_id="INST", institution_scope=RULE_SCOPE_INSTITUTION, institution_code="123"
    )
    result = _resolve((BASE, scoped), institution_code="456")
    assert result.rule == BASE
    assert result.scope_stage == RULE_SCOPE_ALL


def test_region_rule_without_announcement_region_falls_back() -> None:
    regional = replace(
        BASE, rule_id="REGION", institution_scope=RULE_SCOPE_REGION, region_code="11"
    )
    result = _resolve((BASE, regional), region_code=None)
    assert result.rule == BASE
    assert result.scope_stage == RULE_SCOPE_ALL


def test_two_matching_rules_at_same_scope_block_as_ambiguous() -> None:
    first = replace(
        BASE, rule_id="INST_1", institution_scope=RULE_SCOPE_INSTITUTION, institution_code="123"
    )
    second = replace(
        BASE, rule_id="INST_2", institution_scope=RULE_SCOPE_INSTITUTION, institution_code="123"
    )
    result = _resolve((BASE, first, second), institution_code="123")
    assert result.is_blocked
    assert result.block_reason_code == BLOCK_CODE_RULE_SCOPE_AMBIGUOUS
    assert result.institution_code == "123"


@pytest.mark.parametrize("method", ["제한경쟁", "수의계약", "일반경쟁", "지명경쟁", None])
def test_contract_regime_is_local_only_when_local_marker_exists(method: str | None) -> None:
    assert extract_contract_regime({"cntrctCnclsMthdNm": method}) is None
    bid = SimpleNamespace(raw_data={"cntrctCnclsMthdNm": method}, cntrct_mthd_nm=None)
    assert _is_local_contract(bid) is False


def test_contract_regime_local_extraction_and_local_contract_equivalence() -> None:
    raw = {"cntrctCnclsMthdNm": "지방자치단체 제한경쟁"}
    assert extract_contract_regime(raw) == "LOCAL"
    bid = SimpleNamespace(raw_data=raw, cntrct_mthd_nm=None)
    assert _is_local_contract(bid) is (extract_contract_regime(raw) == "LOCAL")


def test_regime_specific_rule_is_excluded_when_announcement_regime_is_unknown() -> None:
    local = replace(BASE, rule_id="LOCAL", contract_regime="LOCAL")
    result = _resolve((BASE, local), contract_regime=None)
    assert result.rule == BASE


@pytest.mark.parametrize(
    "changes",
    [
        {"institution_scope": "OTHER"},
        {"institution_scope": RULE_SCOPE_INSTITUTION},
        {"institution_scope": RULE_SCOPE_REGION},
    ],
)
def test_invalid_scope_declarations_are_rejected(changes: dict[str, str]) -> None:
    with pytest.raises(ValueError):
        replace(BASE, **changes)


def test_raw_data_context_uses_institution_fallback_and_keeps_region_unknown() -> None:
    result = resolve_evaluation_rule_from_raw_data(
        category="Servc",
        raw_data={"sucsfbidMthdNm": METHOD, "dminsttCd": " 123 "},
        institution_name_fallback="테스트 기관",
        cntrct_mthd_nm="수의계약",
    )
    assert result.institution_code == "123"
    assert result.institution_name == "테스트 기관"
    assert result.region_code is None
    assert result.region_name is None
    assert result.contract_regime is None


def test_snapshot_save_persists_context_and_defaults_to_null() -> None:
    class Session:
        def __init__(self) -> None:
            self.objects: list[object] = []

        def add(self, value: object) -> None:
            self.objects.append(value)

        def flush(self) -> None:
            self.objects[0].id = 1  # type: ignore[attr-defined]

        def commit(self) -> None:
            pass

        def refresh(self, value: object) -> None:
            pass

        def rollback(self) -> None:
            pass

    def save(**context: object):
        session = Session()
        snapshot = _save_snapshot_async(
            db=session,
            user_id=1,
            bid_id=1,
            rule_id="RULE",
            model_id="MODEL",
            model_version="1",
            input_json={},
            result_json={},
            evidence_items=[],
            **context,
        )
        assert snapshot is not None
        return snapshot

    snapshot = save(
        contract_regime="LOCAL",
        institution_code="123",
        institution_name="기관",
        region_code="11",
        region_name="서울",
    )
    assert snapshot.contract_regime == "LOCAL"
    assert snapshot.institution_code == "123"
    assert snapshot.institution_name == "기관"
    assert snapshot.region_code == "11"
    assert snapshot.region_name == "서울"
    omitted = save()
    assert omitted.contract_regime is None
    assert omitted.institution_code is None
    assert omitted.institution_name is None
    assert omitted.region_code is None
    assert omitted.region_name is None


def test_migration_is_single_head_and_follows_expected_revision() -> None:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    heads = ScriptDirectory.from_config(Config("alembic.ini")).get_heads()
    assert len(heads) == 1
    assert heads[0] == "a2c7e9f1b4d6"
    migration = Path(
        "migrations/versions/a2c7e9f1b4d6_add_snapshot_rule_scope_context.py"
    ).read_text(encoding="utf-8")
    assert 'down_revision: str | Sequence[str] | None = "9d4e2b7a1c63"' in migration

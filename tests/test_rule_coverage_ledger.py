"""적격심사 규칙 커버리지 원장 시험 (DB 없이).

(1) 순수 계산 함수: 가짜 행과 가짜 판정 결과로 INSTITUTION/REGION/PPS_DEFAULT/BLOCKED/ERROR
    분류, min-announcements tail 집계, 이름 표기 대표값, investigation 보존을 고정합니다.
(2) 원장 정합: 커밋된 data/reference/rule_coverage_ledger.yaml 의 schema·합계와 명세
    status 대조, regions rule_id 가 코드 규칙 집합에 들어가는지 확인합니다.
(3) argparse 옵션과 --check 무쓰기 동작을 확인합니다.

DB·.env 를 쓰지 않습니다. 전량 시험은 -m 'not data_assets' 로 돌립니다.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from scripts import report_rule_coverage as ledger_script
from src.app.services import evaluation_rules as rules_module
from src.app.services.evaluation_rules import (
    INSTITUTION_RULES,
    RULE_SCOPE_ALL,
    RULE_SCOPE_INSTITUTION,
    RULE_SCOPE_REGION,
    EvaluationRule,
    RuleResolutionResult,
)

LEDGER_PATH = Path(ledger_script.DEFAULT_OUTPUT)
SPEC_PATH = Path(ledger_script.INSTITUTION_RULES_PATH)
MANIFEST_PATH = Path(ledger_script.MANIFEST_PATH)

ANY_STATUS = {"confirmed", "partial", "unresolved"}


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


def _institution_rule(rule_id: str) -> EvaluationRule:
    return _rule(rule_id, RULE_SCOPE_INSTITUTION, institution_name="시험기관")


def _region_rule(rule_id: str, region_name: str) -> EvaluationRule:
    return _rule(rule_id, RULE_SCOPE_REGION, region_code="11", region_name=region_name)


def _pps_rule(rule_id: str) -> EvaluationRule:
    return _rule(rule_id, RULE_SCOPE_ALL)


# --------------------------------------------------------------------------- #
# (1) 분류
# --------------------------------------------------------------------------- #


def test_classify_result_maps_each_scope() -> None:
    institution = ledger_script.classify_result(
        RuleResolutionResult(is_blocked=False, rule=_institution_rule("R_INST"))
    )
    assert institution.applied_scope == ledger_script.LEDGER_SCOPE_INSTITUTION
    assert institution.rule_id == "R_INST"

    region = ledger_script.classify_result(
        RuleResolutionResult(is_blocked=False, rule=_region_rule("R_REG", "서울특별시"))
    )
    assert region.applied_scope == ledger_script.LEDGER_SCOPE_REGION
    assert region.region_name == "서울특별시"

    pps = ledger_script.classify_result(
        RuleResolutionResult(is_blocked=False, rule=_pps_rule("R_PPS"))
    )
    assert pps.applied_scope == ledger_script.LEDGER_SCOPE_PPS_DEFAULT

    blocked = ledger_script.classify_result(
        RuleResolutionResult(is_blocked=True, block_reason_code="RULE_NOT_FOUND")
    )
    assert blocked.applied_scope == ledger_script.LEDGER_SCOPE_BLOCKED
    assert blocked.block_code == "RULE_NOT_FOUND"

    error = ledger_script.classify_result(None, "ValueError")
    assert error.applied_scope == ledger_script.LEDGER_SCOPE_ERROR
    assert error.error_type == "ValueError"


def test_classify_result_blocked_wins_over_rule_scope() -> None:
    """규칙이 붙은 채 차단되는 RULE_REGIME_MISMATCH 경로는 BLOCKED 로 분류한다."""
    result = RuleResolutionResult(
        is_blocked=True,
        block_reason_code="RULE_REGIME_MISMATCH",
        rule=_institution_rule("R_INST"),
    )
    outcome = ledger_script.classify_result(result)
    assert outcome.applied_scope == ledger_script.LEDGER_SCOPE_BLOCKED
    assert outcome.block_code == "RULE_REGIME_MISMATCH"
    assert outcome.rule_id is None


# --------------------------------------------------------------------------- #
# (1) 순수 계산 함수: 원장 집계
# --------------------------------------------------------------------------- #


def test_build_ledger_classifies_and_aggregates_tail_and_regions() -> None:
    records = [
        _record(
            "A", "기관A", RuleResolutionResult(is_blocked=False, rule=_institution_rule("R_A"))
        ),
        _record(
            "A", "기관A", RuleResolutionResult(is_blocked=False, rule=_institution_rule("R_A"))
        ),
        _record(
            "A", "기관A", RuleResolutionResult(is_blocked=False, rule=_institution_rule("R_A"))
        ),
        _record("B", "기관B", RuleResolutionResult(is_blocked=False, rule=_pps_rule("R_B"))),
        _record(
            "C",
            "기관C",
            RuleResolutionResult(is_blocked=False, rule=_region_rule("R_L", "서울특별시")),
        ),
        _record(
            "C",
            "기관C",
            RuleResolutionResult(is_blocked=False, rule=_region_rule("R_L", "서울특별시")),
        ),
    ]
    ledger = ledger_script.build_ledger(
        records,
        filter_meta={"months": 12},
        min_announcements=2,
        generated_at="2026-10-14",
    )

    assert ledger["schema"] == ledger_script.SCHEMA
    assert ledger["generated_by"] == ledger_script.GENERATED_BY
    assert ledger["totals"]["announcements"] == 6
    assert sum(item["announcements"] for item in ledger["totals"]["applied_scope"].values()) == 6
    assert (
        ledger["totals"]["applied_scope"][ledger_script.LEDGER_SCOPE_INSTITUTION]["announcements"]
        == 3
    )
    assert (
        ledger["totals"]["applied_scope"][ledger_script.LEDGER_SCOPE_REGION]["announcements"] == 2
    )
    assert (
        ledger["totals"]["applied_scope"][ledger_script.LEDGER_SCOPE_PPS_DEFAULT]["announcements"]
        == 1
    )

    assert [item["dminstt_cd"] for item in ledger["institutions"]] == ["A"]
    entry = ledger["institutions"][0]
    assert entry["applied_scope"] == ledger_script.LEDGER_SCOPE_INSTITUTION
    assert entry["scope_counts"] == {ledger_script.LEDGER_SCOPE_INSTITUTION: 3}
    assert entry["rule_ids"] == ["R_A"]
    assert entry["block_codes"] == {}
    assert entry["investigation"] is None

    assert ledger["tail"] == {
        "institutions": 1,
        "announcements": 1,
        "applied_scope": {ledger_script.LEDGER_SCOPE_PPS_DEFAULT: 1},
    }
    assert ledger["totals"]["institutions"] == 2

    assert ledger["regions"] == [
        {"region_name": "서울특별시", "rule_ids": ["R_L"], "announcements": 2}
    ]


def test_build_ledger_counts_block_codes_and_errors() -> None:
    records = [
        _record(
            "A",
            "기관A",
            RuleResolutionResult(is_blocked=True, block_reason_code="RULE_NOT_FOUND"),
        ),
        _record(
            "A",
            "기관A",
            RuleResolutionResult(is_blocked=True, block_reason_code="RULE_NOT_FOUND"),
        ),
        _record("A", "기관A", None, "ValueError"),
    ]
    ledger = ledger_script.build_ledger(
        records,
        filter_meta={},
        min_announcements=1,
        generated_at="2026-10-14",
    )
    entry = ledger["institutions"][0]
    assert entry["applied_scope"] == ledger_script.LEDGER_SCOPE_BLOCKED
    assert entry["block_codes"] == {"RULE_NOT_FOUND": 2, "ValueError": 1}
    assert ledger["totals"]["applied_scope"][ledger_script.LEDGER_SCOPE_ERROR]["announcements"] == 1


def test_build_ledger_representative_name_and_variants() -> None:
    records = [
        _record("A", "가", RuleResolutionResult(is_blocked=False, rule=_pps_rule("R"))),
        _record("A", "가", RuleResolutionResult(is_blocked=False, rule=_pps_rule("R"))),
        _record("A", "나", RuleResolutionResult(is_blocked=False, rule=_pps_rule("R"))),
        _record("A", "다", RuleResolutionResult(is_blocked=False, rule=_pps_rule("R"))),
    ]
    ledger = ledger_script.build_ledger(
        records, filter_meta={}, min_announcements=1, generated_at="2026-10-14"
    )
    entry = ledger["institutions"][0]
    assert entry["dminstt_nm"] == "가"
    assert sorted(entry["name_variants"]) == ["나", "다"]


def test_build_ledger_caps_name_variants_at_five() -> None:
    names = ["대표", *[f"표기{i}" for i in range(1, 9)]]
    records = [
        _record("A", name, RuleResolutionResult(is_blocked=False, rule=_pps_rule("R")))
        for name in names
    ]
    ledger = ledger_script.build_ledger(
        records, filter_meta={}, min_announcements=1, generated_at="2026-10-14"
    )
    entry = ledger["institutions"][0]
    assert entry["dminstt_nm"] == "대표"
    assert len(entry["name_variants"]) == 5


def test_build_ledger_registry_status_lookup() -> None:
    registry = ledger_script.RegistryIndex(
        by_name={"한국토지주택공사": "unresolved", "시험기관": "confirmed"},
        by_rule_id={"R_A": "confirmed"},
    )
    records = [
        _record(
            "A", "시험기관", RuleResolutionResult(is_blocked=False, rule=_institution_rule("R_A"))
        ),
        _record(
            "B", "한국토지주택공사", RuleResolutionResult(is_blocked=False, rule=_pps_rule("R_B"))
        ),
        _record("C", "무명기관", RuleResolutionResult(is_blocked=False, rule=_pps_rule("R_C"))),
    ]
    ledger = ledger_script.build_ledger(
        records,
        filter_meta={},
        min_announcements=1,
        generated_at="2026-10-14",
        registry_index=registry,
    )
    statuses = {item["dminstt_cd"]: item["registry_status"] for item in ledger["institutions"]}
    assert statuses == {"A": "confirmed", "B": "unresolved", "C": "unregistered"}


def test_build_ledger_preserves_existing_investigation() -> None:
    investigation = {
        "recommendation": "조사 필요",
        "doc": None,
        "date": "2026-10-13",
        "note": "사람이 채운 값",
    }
    existing = {
        "institutions": [
            {"dminstt_cd": "A", "investigation": investigation},
            {"dminstt_cd": "Z", "investigation": {"recommendation": "무시됨"}},
        ]
    }
    records = [
        _record("A", "기관A", RuleResolutionResult(is_blocked=False, rule=_pps_rule("R_A"))),
        _record("B", "기관B", RuleResolutionResult(is_blocked=False, rule=_pps_rule("R_B"))),
    ]
    ledger = ledger_script.build_ledger(
        records,
        filter_meta={},
        min_announcements=1,
        generated_at="2026-10-14",
        existing_ledger=existing,
    )
    by_code = {item["dminstt_cd"]: item for item in ledger["institutions"]}
    assert by_code["A"]["investigation"] == investigation
    assert by_code["B"]["investigation"] is None


# --------------------------------------------------------------------------- #
# (3) argparse 와 --check
# --------------------------------------------------------------------------- #


def test_parse_args_defaults() -> None:
    args = ledger_script.parse_args([])
    assert args.months == 12
    assert args.category == "Servc"
    assert args.method_code == "낙030001"
    assert args.min_announcements == 5
    assert args.output == ledger_script.DEFAULT_OUTPUT
    assert args.check is False


def test_parse_args_overrides() -> None:
    args = ledger_script.parse_args(
        ["--months", "6", "--method-code", "", "--min-announcements", "3", "--check"]
    )
    assert args.months == 6
    assert args.method_code == ""
    assert args.min_announcements == 3
    assert args.check is True


def test_check_does_not_write(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(ledger_script, "collect_records", lambda **kwargs: [])
    monkeypatch.setattr(
        ledger_script, "load_registry_index", lambda *a, **k: ledger_script.RegistryIndex()
    )
    monkeypatch.setattr(ledger_script, "load_manifest_sources", lambda *a, **k: {})

    output = tmp_path / "ledger.yaml"
    assert ledger_script.main(["--check", "--output", str(output)]) == 0
    assert not output.exists()

    assert ledger_script.main(["--output", str(output)]) == 0
    written = output.read_text(encoding="utf-8")
    assert ledger_script.main(["--check", "--output", str(output)]) == 0
    assert output.read_text(encoding="utf-8") == written


def test_diff_ledgers_ignores_volatile_fields() -> None:
    left = {
        "generated_at": "2026-01-01",
        "filter": {"window_from": "2025-01-01"},
        "totals": {"announcements": 1},
    }
    right = {
        "generated_at": "2026-10-14",
        "filter": {"window_from": "2025-10-14"},
        "totals": {"announcements": 2},
    }
    differences = ledger_script.diff_ledgers(left, right)
    assert differences == [("totals.announcements", 1, 2)]


# --------------------------------------------------------------------------- #
# (2) 커밋된 원장 정합
# --------------------------------------------------------------------------- #


def _ledger() -> dict:
    return yaml.safe_load(LEDGER_PATH.read_text(encoding="utf-8"))


def _spec() -> dict:
    return yaml.safe_load(SPEC_PATH.read_text(encoding="utf-8"))


def _spec_status_by_name() -> dict[str, str]:
    statuses: dict[str, str] = {}
    for entry in _spec()["institutions"]:
        for name in [entry["institution_name"], *(entry.get("name_aliases") or [])]:
            statuses.setdefault(name.strip(), entry["status"])
    return statuses


def _spec_status_by_institution_name() -> dict[str, str]:
    return {entry["institution_name"]: entry["status"] for entry in _spec()["institutions"]}


def _all_rule_ids() -> set[str]:
    ids: set[str] = set()
    for name in dir(rules_module):
        value = getattr(rules_module, name)
        if isinstance(value, EvaluationRule):
            ids.add(value.rule_id)
        elif (
            isinstance(value, tuple) and value and all(isinstance(x, EvaluationRule) for x in value)
        ):
            ids.update(rule.rule_id for rule in value)
    return ids


def test_committed_ledger_schema_and_filter() -> None:
    ledger = _ledger()
    assert ledger["schema"] == ledger_script.SCHEMA
    assert ledger["generated_by"] == ledger_script.GENERATED_BY
    assert set(ledger["filter"]) == {
        "months",
        "category",
        "method_code",
        "window_from",
        "window_to",
        "min_announcements",
    }


def test_committed_ledger_totals_are_self_consistent() -> None:
    ledger = _ledger()
    totals = ledger["totals"]
    scope_sum = sum(item["announcements"] for item in totals["applied_scope"].values())
    assert scope_sum == totals["announcements"]

    body_announcements = sum(item["announcements"] for item in ledger["institutions"])
    region_announcements = sum(item["announcements"] for item in ledger["regions"])
    assert (
        body_announcements + region_announcements + ledger["tail"]["announcements"]
        == (totals["announcements"])
    )
    assert totals["institutions"] == len(ledger["institutions"]) + ledger["tail"]["institutions"]

    for item in ledger["institutions"]:
        assert sum(item["scope_counts"].values()) == item["announcements"]
        assert item["announcements"] >= ledger["filter"]["min_announcements"]


def test_committed_ledger_region_rule_ids_are_registered() -> None:
    registered = _all_rule_ids()
    for region in _ledger()["regions"]:
        assert region["rule_ids"], region["region_name"]
        for rule_id in region["rule_ids"]:
            assert rule_id in registered, rule_id


def test_committed_ledger_registry_status_matches_spec() -> None:
    """명세 status 가 바뀌었는데 원장을 갱신하지 않으면 실패한다."""
    status_by_name = _spec_status_by_name()
    status_by_institution = _spec_status_by_institution_name()
    rule_to_institution = {rule.rule_id: rule.institution_name for rule in INSTITUTION_RULES}

    checked = 0
    for item in _ledger()["institutions"]:
        status = item["registry_status"]
        candidates: set[str] = set()
        for rule_id in item["rule_ids"]:
            institution_name = rule_to_institution.get(rule_id)
            if institution_name in status_by_institution:
                candidates.add(status_by_institution[institution_name])
        if item["dminstt_nm"] in status_by_name:
            candidates.add(status_by_name[item["dminstt_nm"]])

        if status in ANY_STATUS:
            checked += 1
            assert status in candidates, (
                item["dminstt_cd"],
                item["dminstt_nm"],
                status,
                candidates,
            )
        else:
            assert status == "unregistered"
            assert not candidates, (item["dminstt_cd"], status, candidates)
    assert checked > 0


def test_committed_ledger_scopes_are_known() -> None:
    ledger = _ledger()
    for item in ledger["institutions"]:
        assert item["applied_scope"] in ledger_script.LEDGER_SCOPES
        assert set(item["scope_counts"]) <= set(ledger_script.LEDGER_SCOPES)
    assert set(ledger["totals"]["applied_scope"]) == set(ledger_script.LEDGER_SCOPES)
    assert set(ledger["tail"]["applied_scope"]) <= set(ledger_script.LEDGER_SCOPES)


def test_committed_ledger_manifest_sources_shape() -> None:
    for item in _ledger()["institutions"]:
        sources = item["manifest_sources"]
        if sources is None:
            continue
        assert isinstance(sources, list)
        assert sources
        for source in sources:
            assert set(source) == {"source", "files"}
            assert isinstance(source["files"], int)


def test_manifest_index_matches_committed_manifest() -> None:
    index = ledger_script.load_manifest_sources(MANIFEST_PATH)
    assert index
    for sources in index.values():
        assert sources
        for source in sources:
            assert set(source) == {"source", "files"}


# --------------------------------------------------------------------------- #
# (2) 커밋된 원장 investigation: ICA·ICB 후보 14곳
# --------------------------------------------------------------------------- #

CANDIDATE_LEDGER_PATHS: tuple[str, ...] = (
    "data/reference/institution_rules_candidates_a_20261014.yaml",
    "data/reference/institution_rules_candidates_b_20261014.yaml",
)

# (dminstt_cd, 후보 institution_name, 후보 YAML 상대 경로)
INVESTIGATION_TARGETS: tuple[tuple[str, str, str], ...] = (
    ("B550234", "국방과학연구소", CANDIDATE_LEDGER_PATHS[0]),
    ("B552584", "한국환경공단", CANDIDATE_LEDGER_PATHS[0]),
    ("B553968", "한국어촌어항공단", CANDIDATE_LEDGER_PATHS[0]),
    ("B555210", "국가유산진흥원", CANDIDATE_LEDGER_PATHS[0]),
    ("B554644", "한국광해광업공단", CANDIDATE_LEDGER_PATHS[0]),
    ("B553931", "해양환경공단", CANDIDATE_LEDGER_PATHS[0]),
    ("B553023", "한국원자력환경공단", CANDIDATE_LEDGER_PATHS[0]),
    ("1400000", "산림청", CANDIDATE_LEDGER_PATHS[1]),
    ("ZD00303", "국방부", CANDIDATE_LEDGER_PATHS[1]),
    ("ZD00001", "국방부", CANDIDATE_LEDGER_PATHS[1]),
    ("1290476", "국방부", CANDIDATE_LEDGER_PATHS[1]),
    ("B551178", "한국공항공사", CANDIDATE_LEDGER_PATHS[1]),
    ("1192000", "해양수산부", CANDIDATE_LEDGER_PATHS[1]),
    ("Z000152", "한국농수산식품유통공사", CANDIDATE_LEDGER_PATHS[1]),
    ("B550928", "국민건강보험공단", CANDIDATE_LEDGER_PATHS[1]),
    ("B551220", "부산항만공사", CANDIDATE_LEDGER_PATHS[1]),
)


def _candidate_by_name() -> dict[str, dict]:
    index: dict[str, dict] = {}
    for path in CANDIDATE_LEDGER_PATHS:
        payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        for entry in payload["institutions"]:
            index[entry["institution_name"]] = {**entry, "source": path}
    return index


def test_committed_ledger_investigation_targets() -> None:
    """후보 14곳의 조사 결론이 대응 16행에만 적히고 나머지 행은 null 이다.

    기관명이 dminstt_nm 과 같은 13행과, 이름 행이 없는 국방부의 별칭 3행만 채운다.
    같은 후보의 다른 별칭 행(김포공항·지방청·지방산림청·환경본부 등)은 null 이다.
    """
    candidates = _candidate_by_name()
    by_code = {item["dminstt_cd"]: item for item in _ledger()["institutions"]}

    for code, candidate_name, source in INVESTIGATION_TARGETS:
        candidate = candidates[candidate_name]
        investigation = by_code[code]["investigation"]
        assert investigation is not None, code
        assert investigation["recommendation"] == candidate["recommendation"], code
        assert investigation["status"] == candidate["status"], code
        assert investigation["doc"] == candidate["standard"], code
        assert investigation["date"] == "2026-10-14", code
        assert investigation["source"] == source, code
        assert investigation["note"], code

    targets = {code for code, _name, _source in INVESTIGATION_TARGETS}
    for item in _ledger()["institutions"]:
        if item["dminstt_cd"] not in targets:
            assert item["investigation"] is None, item["dminstt_cd"]

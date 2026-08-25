"""
tests/test_validate_llm_quality_fixture.py

LLM 품질 평가 fixture 검증기 (scripts/validate_llm_quality_fixture.py) 단위 테스트.
- 정상 fixture 통과 및 ChromaDB 실재 검증
- 실재하지 않는 expected_evidence_ids 검출
- 필수 필드 누락 검출
- ID 중복 검출
- context_sufficient 문항 수 하한 미달 검출
- 자기모순 금지 규칙 누락 검출 (semantic_forbidden_claims)
- 복합 numeric 팩트 검출 (한 expected_facts 에 낙찰금액과 낙찰률 동시 언급)
- forbidden_literals 검증 (알려진 내부 코드 누락 검출)
- semantic_forbidden_claims 검증
- CLI 종료 코드 및 --quiet 동작 검증
"""

import copy
import json
import subprocess  # nosec B404
import sys
from pathlib import Path
from typing import Any

import pytest

from scripts.validate_llm_quality_fixture import (
    DEFAULT_MIN_CONTEXT_SUFFICIENT,
    validate_fixture_data,
)

FIXTURE_PATH = Path("data/eval/llm_quality_fixture_v1.json")


@pytest.fixture
def valid_fixture_dict() -> dict[str, Any]:
    """정본 fixture 파일을 로드하여 테스트 기본 데이터로 제공합니다."""
    assert FIXTURE_PATH.exists(), f"정본 fixture 파일이 존재해야 합니다: {FIXTURE_PATH}"
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def test_canonical_fixture_passes(valid_fixture_dict: dict[str, Any]):
    """실제 정본 fixture 파일이 스키마 및 KB 실재성 검증을 완벽히 통과하는지 확인합니다."""
    is_valid, errors, stats = validate_fixture_data(valid_fixture_dict, check_kb_existence=True)
    assert is_valid is True, f"검증 오류 발생: {errors}"
    assert len(errors) == 0
    assert stats["total_items"] >= 15
    assert stats["context_sufficient_count"] >= DEFAULT_MIN_CONTEXT_SUFFICIENT
    assert stats["refusal_expected_count"] >= 1


def test_non_existent_evidence_id_detected(valid_fixture_dict: dict[str, Any]):
    """ChromaDB 에 실재하지 않는 가상의 evidence ID 가 포함되면 검출되는지 확인합니다."""
    tampered = copy.deepcopy(valid_fixture_dict)
    # 실재하지 않는 가상 ID 주입
    tampered["items"][0]["expected_evidence_ids"] = ["bid_non_existent_99999999"]

    is_valid, errors, stats = validate_fixture_data(tampered, check_kb_existence=True)
    if "건너뜀" not in stats.get("kb_verification_status", ""):
        assert is_valid is False
        assert any("실재하지 않는" in err for err in errors)


def test_missing_required_field_detected(valid_fixture_dict: dict[str, Any]):
    """필수 필드가 누락된 경우 검증이 실패하고 에러 메시지를 반환하는지 확인합니다."""
    tampered = copy.deepcopy(valid_fixture_dict)
    # q01 문항에서 scoring_rubric 필드 제거
    del tampered["items"][0]["scoring_rubric"]

    is_valid, errors, _ = validate_fixture_data(tampered)
    assert is_valid is False
    assert any("scoring_rubric" in err for err in errors)


def test_duplicate_id_detected(valid_fixture_dict: dict[str, Any]):
    """문항 ID 가 중복된 경우 검증이 실패하는지 확인합니다."""
    tampered = copy.deepcopy(valid_fixture_dict)
    # q02 의 ID 를 q01 로 중복 설정
    tampered["items"][1]["id"] = "q01"

    is_valid, errors, _ = validate_fixture_data(tampered)
    assert is_valid is False
    assert any("중복된 문항 ID" in err for err in errors)


def test_min_context_sufficient_threshold_detected(valid_fixture_dict: dict[str, Any]):
    """context_sufficient=True 문항 수가 하한(15개) 미만인 경우 검증이 실패하는지 확인합니다."""
    tampered = copy.deepcopy(valid_fixture_dict)
    # context_sufficient=True 인 문항들을 모두 False 로 변경하여 하한 미달 유발
    for item in tampered["items"]:
        item["context_sufficient"] = False
        item["refusal_expected"] = True

    is_valid, errors, _ = validate_fixture_data(tampered, min_context_sufficient=15)
    assert is_valid is False
    assert any("미달합니다" in err for err in errors)


def test_missing_self_contradiction_rule_detected(valid_fixture_dict: dict[str, Any]):
    """semantic_forbidden_claims 에 '자기모순' 유형이 전혀 없는 경우 검증이 실패하는지 확인합니다."""
    tampered = copy.deepcopy(valid_fixture_dict)
    for item in tampered["items"]:
        item["semantic_forbidden_claims"] = ["단순 일반 규칙"]

    is_valid, errors, _ = validate_fixture_data(tampered)
    assert is_valid is False
    assert any("자기모순" in err for err in errors)


def test_compound_numeric_fact_detected(valid_fixture_dict: dict[str, Any]):
    """복합 numeric 팩트(한 expected_facts 에 낙찰금액과 낙찰률 동시 언급) 가 검출되는지 확인합니다."""
    tampered = copy.deepcopy(valid_fixture_dict)
    # q01 의 첫 번째 numeric 팩트를 복합 팩트로 변경
    tampered["items"][0]["expected_facts"][3] = {
        "statement": "낙찰금액은 46,602,100원이며 낙찰률은 88.5100% 임",
        "fact_type": "numeric",
        "expected_value": "46602100",
        "unit": "원",
        "tolerance": 0.01,
        "verification_criterion": "낙찰금액 46,602,100원 및 낙찰률 88.5100% 명시",
    }

    is_valid, errors, _ = validate_fixture_data(tampered)
    assert is_valid is False
    assert any("복합 numeric 팩트" in err for err in errors)
    assert any("원자 단위로 분해" in err for err in errors)


def test_forbidden_literals_missing_known_codes_detected(valid_fixture_dict: dict[str, Any]):
    """forbidden_literals 에 알려진 내부 코드(Servc, Thng, Cnstwk, Frgcpt) 가 누락되면 검출되는지 확인합니다."""
    tampered = copy.deepcopy(valid_fixture_dict)
    # q01 의 forbidden_literals 에서 Servc 제거
    tampered["items"][0]["forbidden_literals"] = ["Thng", "Cnstwk", "Frgcpt"]

    is_valid, errors, _ = validate_fixture_data(tampered)
    assert is_valid is False
    assert any("누락되었습니다" in err for err in errors)
    assert any("Servc" in err for err in errors)


def test_forbidden_literals_unknown_code_detected(valid_fixture_dict: dict[str, Any]):
    """forbidden_literals 에 알려지지 않은 코드가 있으면 검출되는지 확인합니다."""
    tampered = copy.deepcopy(valid_fixture_dict)
    # q01 의 forbidden_literals 에 알 수 없는 코드 추가
    tampered["items"][0]["forbidden_literals"] = [
        "Servc",
        "Thng",
        "Cnstwk",
        "Frgcpt",
        "UnknownCode",
    ]

    is_valid, errors, _ = validate_fixture_data(tampered)
    assert is_valid is False
    assert any("알려진 내부 코드" in err for err in errors)
    assert any("UnknownCode" in err for err in errors)


def test_semantic_forbidden_claims_empty_detected(valid_fixture_dict: dict[str, Any]):
    """semantic_forbidden_claims 가 비어있으면 검출되는지 확인합니다."""
    tampered = copy.deepcopy(valid_fixture_dict)
    tampered["items"][0]["semantic_forbidden_claims"] = []

    is_valid, errors, _ = validate_fixture_data(tampered)
    assert is_valid is False
    assert any("비어있습니다" in err for err in errors)


def test_numeric_fact_missing_required_fields_detected(valid_fixture_dict: dict[str, Any]):
    """numeric 타입 expected_facts 에 expected_value, unit, tolerance 중 하나라도 없으면 검출되는지 확인합니다."""
    tampered = copy.deepcopy(valid_fixture_dict)
    # q01 의 numeric 팩트에서 unit 제거
    del tampered["items"][0]["expected_facts"][3]["unit"]

    is_valid, errors, _ = validate_fixture_data(tampered)
    assert is_valid is False
    assert any("numeric 타입" in err for err in errors)
    assert any("unit" in err for err in errors)


def test_cli_execution_success(tmp_path: Path):
    """CLI 실행 시 정상 파일에 대해 exit code 0을 반환하는지 확인합니다."""
    cmd = [sys.executable, "scripts/validate_llm_quality_fixture.py", str(FIXTURE_PATH), "--quiet"]
    res = subprocess.run(cmd, capture_output=True, text=True, check=False)  # noqa: S603
    assert res.returncode == 0
    assert res.stdout == ""


def test_cli_execution_failure_on_invalid_file(tmp_path: Path):
    """CLI 실행 시 유효하지 않은 fixture 에 대해 exit code 1을 반환하는지 확인합니다."""
    bad_fixture = tmp_path / "bad_fixture.json"
    bad_fixture.write_text(json.dumps({"items": [{"id": "q01"}]}), encoding="utf-8")

    cmd = [sys.executable, "scripts/validate_llm_quality_fixture.py", str(bad_fixture), "--quiet"]
    res = subprocess.run(cmd, capture_output=True, text=True, check=False)  # noqa: S603
    assert res.returncode == 1


def test_cli_execution_missing_file():
    """CLI 실행 시 존재하지 않는 파일에 대해 exit code 2를 반환하는지 확인합니다."""
    cmd = [
        sys.executable,
        "scripts/validate_llm_quality_fixture.py",
        "non_existent_file.json",
        "--quiet",
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=False)  # noqa: S603
    assert res.returncode == 2

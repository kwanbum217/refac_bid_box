"""
tests/test_validate_llm_quality_fixture.py

LLM 품질 평가 fixture 검증기 (scripts/validate_llm_quality_fixture.py) 단위 테스트.
- 정상 fixture 통과 및 경량 evidence manifest 대조 검증
- manifest 파일 부재 시 fail-closed 검증 실패
- 명시적 옵트아웃(--skip-manifest-check / check_manifest=False) 시 정상 통과
- fixture 에만 있고 manifest 에 없는 근거 ID 검출
- manifest 필수 필드 누락 검출
- manifest 내 중복 evidence_id 검출
- manifest 해시 형식 불일치 검출
- 실재하지 않는 expected_evidence_ids 검출 (ChromaDB 연동 시)
- 필수 필드 누락 검출
- ID 중복 검출
- context_sufficient 문항 수 하한 미달 검출
- 자기모순 금지 규칙 누락 검출 (semantic_forbidden_claims)
- 복합 numeric 팩트 검출 (한 expected_facts 에 낙찰금액과 낙찰률 동시 언급)
- forbidden_literals 검증 (알려진 내부 코드 누락/불일치 검출)
- semantic_forbidden_claims 검증
- CLI 종료 코드 및 --quiet / --manifest-path / --skip-manifest-check 동작 검증
"""

import copy
import hashlib
import json
import subprocess  # nosec B404
import sys
from pathlib import Path
from typing import Any

import pytest

from scripts.validate_llm_quality_fixture import (
    DEFAULT_MIN_CONTEXT_SUFFICIENT,
    validate_fixture_data,
    validate_manifest_data,
)

FIXTURE_PATH = Path("data/eval/llm_quality_fixture_v1.json")


@pytest.fixture
def valid_fixture_dict() -> dict[str, Any]:
    """정본 fixture 파일을 로드하여 테스트 기본 데이터로 제공합니다."""
    assert FIXTURE_PATH.exists(), f"정본 fixture 파일이 존재해야 합니다: {FIXTURE_PATH}"
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


@pytest.fixture
def valid_manifest_dict(valid_fixture_dict: dict[str, Any]) -> dict[str, Any]:
    """정본 fixture 의 모든 expected_evidence_ids 를 포함하는 정상 manifest 딕셔너리를 생성합니다."""
    all_evidence_ids: set[str] = set()
    for item in valid_fixture_dict.get("items", []):
        for ev_id in item.get("expected_evidence_ids") or []:
            if isinstance(ev_id, str) and ev_id.strip():
                all_evidence_ids.add(ev_id.strip())

    entries = []
    for ev_id in sorted(all_evidence_ids):
        fake_doc = f"테스트 문서 내용 for {ev_id}"
        digest = hashlib.sha256(fake_doc.encode("utf-8")).hexdigest()
        entries.append(
            {
                "evidence_id": ev_id,
                "content_hash": f"sha256:{digest}",
                "doc_length": len(fake_doc),
            }
        )

    return {
        "schema_version": "1.0.0",
        "created_at": "2026-08-25T13:00:00Z",
        "collection_name": "bidding_kb",
        "total_collection_documents": 512348,
        "item_count": len(entries),
        "entries": entries,
    }


@pytest.fixture
def valid_manifest_file(tmp_path: Path, valid_manifest_dict: dict[str, Any]) -> Path:
    """정상 manifest 파일을 tmp_path 에 작성하여 경로를 반환합니다."""
    manifest_path = tmp_path / "valid_manifest.json"
    manifest_path.write_text(
        json.dumps(valid_manifest_dict, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return manifest_path


def test_canonical_fixture_passes_with_valid_manifest(
    valid_fixture_dict: dict[str, Any], valid_manifest_file: Path
):
    """정상 fixture 와 정상 manifest 가 주어졌을 때 검증을 완벽히 통과하는지 확인합니다."""
    is_valid, errors, stats = validate_fixture_data(
        valid_fixture_dict,
        check_kb_existence=True,
        manifest_path=valid_manifest_file,
        check_manifest=True,
    )
    assert is_valid is True, f"검증 오류 발생: {errors}"
    assert len(errors) == 0
    assert stats["total_items"] >= 15
    assert stats["context_sufficient_count"] >= DEFAULT_MIN_CONTEXT_SUFFICIENT
    assert stats["refusal_expected_count"] >= 1
    assert "대조 완료" in stats["manifest_verification_status"]


def test_missing_manifest_fails_closed(valid_fixture_dict: dict[str, Any], tmp_path: Path):
    """manifest 파일이 존재하지 않으면 검증이 fail-closed 로 실패하는지 확인합니다."""
    non_existent_manifest = tmp_path / "non_existent_manifest.json"
    is_valid, errors, stats = validate_fixture_data(
        valid_fixture_dict,
        check_kb_existence=True,
        manifest_path=non_existent_manifest,
        check_manifest=True,
    )
    assert is_valid is False
    assert any("경량 evidence manifest 파일" in err for err in errors)
    assert any("fail-closed" in err for err in errors)
    assert "fail-closed" in stats["manifest_verification_status"]


def test_optout_manifest_check_passes(valid_fixture_dict: dict[str, Any]):
    """check_manifest=False 옵트아웃 시 manifest 파일이 없어도 통과하는지 확인합니다."""
    is_valid, errors, stats = validate_fixture_data(
        valid_fixture_dict,
        check_kb_existence=True,
        manifest_path=None,
        check_manifest=False,
    )
    assert is_valid is True, f"검증 오류 발생: {errors}"
    assert len(errors) == 0
    assert stats["manifest_verification_status"] == "옵트아웃으로 건너뜀"


def test_missing_evidence_in_manifest_detected(
    valid_fixture_dict: dict[str, Any], valid_manifest_dict: dict[str, Any], tmp_path: Path
):
    """fixture 에는 존재하지만 manifest 에는 누락된 근거 ID 가 있으면 검출되는지 확인합니다."""
    tampered_manifest = copy.deepcopy(valid_manifest_dict)
    # 첫 번째 근거 ID 제거
    removed_entry = tampered_manifest["entries"].pop(0)
    removed_id = removed_entry["evidence_id"]

    manifest_file = tmp_path / "missing_evidence_manifest.json"
    manifest_file.write_text(
        json.dumps(tampered_manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    is_valid, errors, _ = validate_fixture_data(
        valid_fixture_dict,
        manifest_path=manifest_file,
        check_manifest=True,
    )
    assert is_valid is False
    assert any("evidence manifest 에 존재하지 않는 expected_evidence_ids" in err for err in errors)
    assert any(removed_id in err for err in errors)


def test_manifest_missing_required_field_detected(valid_manifest_dict: dict[str, Any]):
    """manifest 자체의 필수 필드가 누락된 경우 검출되는지 확인합니다."""
    tampered = copy.deepcopy(valid_manifest_dict)
    del tampered["collection_name"]

    is_valid, errors, _ = validate_manifest_data(tampered)
    assert is_valid is False
    assert any("collection_name" in err for err in errors)


def test_manifest_duplicate_evidence_id_detected(valid_manifest_dict: dict[str, Any]):
    """manifest 내에 중복된 evidence_id 가 있을 때 검출되는지 확인합니다."""
    tampered = copy.deepcopy(valid_manifest_dict)
    if len(tampered["entries"]) >= 2:
        tampered["entries"][1]["evidence_id"] = tampered["entries"][0]["evidence_id"]

    is_valid, errors, _ = validate_manifest_data(tampered)
    assert is_valid is False
    assert any("중복된 evidence_id" in err for err in errors)


def test_manifest_invalid_hash_format_detected(valid_manifest_dict: dict[str, Any]):
    """manifest content_hash 가 올바른 sha256 형식이 아닌 경우 검출되는지 확인합니다."""
    tampered = copy.deepcopy(valid_manifest_dict)
    tampered["entries"][0]["content_hash"] = "invalid_hash_1234"

    is_valid, errors, _ = validate_manifest_data(tampered)
    assert is_valid is False
    assert any("SHA-256 형식" in err for err in errors)


def test_non_existent_evidence_id_detected(valid_fixture_dict: dict[str, Any]):
    """ChromaDB 에 실재하지 않는 가상의 evidence ID 가 포함되면 검출되는지 확인합니다."""
    tampered = copy.deepcopy(valid_fixture_dict)
    tampered["items"][0]["expected_evidence_ids"] = ["bid_non_existent_99999999"]

    is_valid, errors, stats = validate_fixture_data(
        tampered, check_kb_existence=True, check_manifest=False
    )
    if "건너뜀" not in stats.get("kb_verification_status", ""):
        assert is_valid is False
        assert any("실재하지 않는" in err for err in errors)


def test_missing_required_field_detected(valid_fixture_dict: dict[str, Any]):
    """필수 필드가 누락된 경우 검증이 실패하고 에러 메시지를 반환하는지 확인합니다."""
    tampered = copy.deepcopy(valid_fixture_dict)
    del tampered["items"][0]["scoring_rubric"]

    is_valid, errors, _ = validate_fixture_data(tampered, check_manifest=False)
    assert is_valid is False
    assert any("scoring_rubric" in err for err in errors)


def test_duplicate_id_detected(valid_fixture_dict: dict[str, Any]):
    """문항 ID 가 중복된 경우 검증이 실패하는지 확인합니다."""
    tampered = copy.deepcopy(valid_fixture_dict)
    tampered["items"][1]["id"] = "q01"

    is_valid, errors, _ = validate_fixture_data(tampered, check_manifest=False)
    assert is_valid is False
    assert any("중복된 문항 ID" in err for err in errors)


def test_min_context_sufficient_threshold_detected(valid_fixture_dict: dict[str, Any]):
    """context_sufficient=True 문항 수가 하한(15개) 미만인 경우 검증이 실패하는지 확인합니다."""
    tampered = copy.deepcopy(valid_fixture_dict)
    for item in tampered["items"]:
        item["context_sufficient"] = False
        item["refusal_expected"] = True

    is_valid, errors, _ = validate_fixture_data(
        tampered, min_context_sufficient=15, check_manifest=False
    )
    assert is_valid is False
    assert any("미달합니다" in err for err in errors)


def test_missing_self_contradiction_rule_detected(valid_fixture_dict: dict[str, Any]):
    """semantic_forbidden_claims 에 '자기모순' 유형이 전혀 없는 경우 검증이 실패하는지 확인합니다."""
    tampered = copy.deepcopy(valid_fixture_dict)
    for item in tampered["items"]:
        item["semantic_forbidden_claims"] = ["단순 일반 규칙"]

    is_valid, errors, _ = validate_fixture_data(tampered, check_manifest=False)
    assert is_valid is False
    assert any("자기모순" in err for err in errors)


def test_compound_numeric_fact_detected(valid_fixture_dict: dict[str, Any]):
    """복합 numeric 팩트(한 expected_facts 에 낙찰금액과 낙찰률 동시 언급) 가 검출되는지 확인합니다."""
    tampered = copy.deepcopy(valid_fixture_dict)
    tampered["items"][0]["expected_facts"][3] = {
        "statement": "낙찰금액은 46,602,100원이며 낙찰률은 88.5100% 임",
        "fact_type": "numeric",
        "expected_value": "46602100",
        "unit": "원",
        "tolerance": 0.01,
        "verification_criterion": "낙찰금액 46,602,100원 및 낙찰률 88.5100% 명시",
    }

    is_valid, errors, _ = validate_fixture_data(tampered, check_manifest=False)
    assert is_valid is False
    assert any("복합 numeric 팩트" in err for err in errors)
    assert any("원자 단위로 분해" in err for err in errors)


def test_forbidden_literals_missing_known_codes_detected(valid_fixture_dict: dict[str, Any]):
    """forbidden_literals 에 알려진 내부 코드(Servc, Thng, Cnstwk, Frgcpt) 가 누락되면 검출되는지 확인합니다."""
    tampered = copy.deepcopy(valid_fixture_dict)
    tampered["items"][0]["forbidden_literals"] = ["Thng", "Cnstwk", "Frgcpt"]

    is_valid, errors, _ = validate_fixture_data(tampered, check_manifest=False)
    assert is_valid is False
    assert any("누락되었습니다" in err for err in errors)
    assert any("Servc" in err for err in errors)


def test_forbidden_literals_unknown_code_detected(valid_fixture_dict: dict[str, Any]):
    """forbidden_literals 에 알려지지 않은 코드가 있으면 검출되는지 확인합니다."""
    tampered = copy.deepcopy(valid_fixture_dict)
    tampered["items"][0]["forbidden_literals"] = [
        "Servc",
        "Thng",
        "Cnstwk",
        "Frgcpt",
        "UnknownCode",
    ]

    is_valid, errors, _ = validate_fixture_data(tampered, check_manifest=False)
    assert is_valid is False
    assert any("알려진 내부 코드" in err for err in errors)
    assert any("UnknownCode" in err for err in errors)


def test_semantic_forbidden_claims_empty_detected(valid_fixture_dict: dict[str, Any]):
    """semantic_forbidden_claims 가 비어있으면 검출되는지 확인합니다."""
    tampered = copy.deepcopy(valid_fixture_dict)
    tampered["items"][0]["semantic_forbidden_claims"] = []

    is_valid, errors, _ = validate_fixture_data(tampered, check_manifest=False)
    assert is_valid is False
    assert any("비어있습니다" in err for err in errors)


def test_numeric_fact_missing_required_fields_detected(valid_fixture_dict: dict[str, Any]):
    """numeric 타입 expected_facts 에 expected_value, unit, tolerance 중 하나라도 없으면 검출되는지 확인합니다."""
    tampered = copy.deepcopy(valid_fixture_dict)
    del tampered["items"][0]["expected_facts"][3]["unit"]

    is_valid, errors, _ = validate_fixture_data(tampered, check_manifest=False)
    assert is_valid is False
    assert any("numeric 타입" in err for err in errors)
    assert any("unit" in err for err in errors)


def test_cli_execution_with_valid_manifest(valid_manifest_file: Path):
    """CLI 실행 시 정상 manifest 파일과 함께 exit code 0을 반환하는지 확인합니다."""
    cmd = [
        sys.executable,
        "scripts/validate_llm_quality_fixture.py",
        str(FIXTURE_PATH),
        "--manifest-path",
        str(valid_manifest_file),
        "--quiet",
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=False)  # noqa: S603
    assert res.returncode == 0
    assert res.stdout == ""


def test_cli_execution_fail_closed_without_manifest():
    """CLI 실행 시 manifest 가 없으면 기본값으로 exit code 1 (fail-closed)을 반환하는지 확인합니다."""
    cmd = [
        sys.executable,
        "scripts/validate_llm_quality_fixture.py",
        str(FIXTURE_PATH),
        "--manifest-path",
        "data/eval/non_existent_manifest.json",
        "--quiet",
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=False)  # noqa: S603
    assert res.returncode == 1


def test_cli_execution_optout_succeeds():
    """CLI 실행 시 --skip-manifest-check 플래그를 주면 manifest 없이도 exit code 0을 반환하는지 확인합니다."""
    cmd = [
        sys.executable,
        "scripts/validate_llm_quality_fixture.py",
        str(FIXTURE_PATH),
        "--skip-manifest-check",
        "--quiet",
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=False)  # noqa: S603
    assert res.returncode == 0
    assert res.stdout == ""


def test_cli_execution_failure_on_invalid_file(tmp_path: Path):
    """CLI 실행 시 유효하지 않은 fixture 에 대해 exit code 1을 반환하는지 확인합니다."""
    bad_fixture = tmp_path / "bad_fixture.json"
    bad_fixture.write_text(json.dumps({"items": [{"id": "q01"}]}), encoding="utf-8")

    cmd = [
        sys.executable,
        "scripts/validate_llm_quality_fixture.py",
        str(bad_fixture),
        "--skip-manifest-check",
        "--quiet",
    ]
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

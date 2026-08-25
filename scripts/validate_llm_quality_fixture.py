"""
scripts/validate_llm_quality_fixture.py

LLM 품질 평가 fixture (data/eval/llm_quality_fixture_v1.json) 스키마 및 무결성 검증기.
표준 라이브러리만을 사용하여 필수 필드 누락, 타입 불일치, ID 중복, context_sufficient
문항 수 하한 미달, 채점 가능성, 자기모순 금지 규칙, 복합 numeric 팩트 검출,
경량 evidence manifest(data/eval/llm_quality_evidence_manifest.json) 대조 (fail-closed),
그리고 로컬 ChromaDB bidding_kb 실재 근거 ID 존재성을 엄격히 검증합니다.

규약:
- 종료 코드 0: 검증 통과
- 종료 코드 1: 스키마/무결성/실재근거/manifest 위반 검출
- 종료 코드 2: 파일 미존재/인자 오류/JSON 파싱 실패
- --quiet 플래그 지원 (통과 시 출력 억제)
- --skip-manifest-check 플래그 지원 (과도기 전용 명시적 옵트아웃, 기본값: 검증 활성화)
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any

REQUIRED_FIELDS = (
    "id",
    "question",
    "context_sufficient",
    "expected_evidence_ids",
    "expected_facts",
    "forbidden_literals",
    "semantic_forbidden_claims",
    "citation_required",
    "refusal_expected",
    "numeric_tolerance",
    "scoring_rubric",
)

DEFAULT_MIN_CONTEXT_SUFFICIENT = 15
DEFAULT_MANIFEST_PATH = Path("data/eval/llm_quality_evidence_manifest.json")
DEFAULT_COLLECTION_NAME = "bidding_kb"

# manifest 스키마 필수 필드
MANIFEST_REQUIRED_FIELDS = (
    "schema_version",
    "created_at",
    "collection_name",
    "total_collection_documents",
    "entries",
)

MANIFEST_ENTRY_REQUIRED_FIELDS = (
    "evidence_id",
    "content_hash",
)

MANIFEST_HASH_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")

# 내부 영문 코드 패턴 (forbidden_literals 에서 기대되는 값들)
KNOWN_INTERNAL_CODES = frozenset({"Servc", "Thng", "Cnstwk", "Frgcpt"})

# 복합 numeric 팩트 검출용 패턴: 한 statement 에 낙찰금액과 낙찰률이 둘 다 언급된 경우
COMPOUND_NUMERIC_PATTERN = re.compile(r"낙찰금액.*낙찰률|낙찰률.*낙찰금액")


def find_chroma_sqlite_path() -> Path | None:
    """ChromaDB sqlite 파일 경로를 탐색합니다 (표준 라이브러리 전용)."""
    # 1. .env 파일 파싱
    env_path = Path(".env")
    if env_path.exists():
        try:
            for line in env_path.read_text(encoding="utf-8").splitlines():
                if line.startswith("CHROMA_DB_PATH="):
                    val = line.split("=", 1)[1].strip().strip('"').strip("'")
                    cand = Path(val) / "chroma.sqlite3"
                    if cand.exists() and cand.stat().st_size > 1000000:
                        return cand
        except OSError:
            pass

    # 2. 환경변수 확인
    env_var = os.environ.get("CHROMA_DB_PATH")
    if env_var:
        cand = Path(env_var) / "chroma.sqlite3"
        if cand.exists() and cand.stat().st_size > 1000000:
            return cand

    # 3. 로컬 및 알려진 상대 경로 탐색
    repo_root = Path(__file__).resolve().parent.parent
    for rel_cand in [
        Path("chroma_db/chroma.sqlite3"),
        Path("../chroma_db/chroma.sqlite3"),
        repo_root / "chroma_db" / "chroma.sqlite3",
    ]:
        if rel_cand.exists() and rel_cand.stat().st_size > 1000000:
            return rel_cand

    return None


def verify_evidence_ids_in_kb(
    evidence_ids: set[str],
    collection_name: str = DEFAULT_COLLECTION_NAME,
) -> tuple[bool, list[str], str]:
    """ChromaDB sqlite 데이터베이스에서 expected_evidence_ids 의 실재 여부를 검증합니다.

    Returns:
        (kb_available, missing_ids, status_message)
    """
    db_path = find_chroma_sqlite_path()
    if not db_path:
        return False, [], "ChromaDB 파일 미존재로 실재 검증 건너뜀"

    if not evidence_ids:
        return True, [], f"ChromaDB 연동 완료 ({db_path})"

    try:
        conn = sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True)
    except Exception:
        try:
            conn = sqlite3.connect(str(db_path))
        except Exception as exc:
            return False, [], f"ChromaDB 연결 실패로 실재 검증 건너뜀 ({exc})"

    try:
        cur = conn.cursor()
        ev_id_list = sorted(evidence_ids)
        placeholders = ", ".join("?" for _ in ev_id_list)
        batch_query = (
            f"SELECT DISTINCT e.embedding_id "  # noqa: S608
            f"FROM embeddings e "
            f"JOIN segments s ON s.id = e.segment_id "
            f"JOIN collections col ON col.id = s.collection "
            f"WHERE col.name = ? AND e.embedding_id IN ({placeholders})"  # nosec B608
        )
        cur.execute(batch_query, [collection_name, *ev_id_list])
        found = {str(row[0]) for row in cur.fetchall()}
        conn.close()

        missing = sorted(evidence_ids - found)
        return (
            True,
            missing,
            f"ChromaDB {collection_name} 실재 확인 ({len(found)}/{len(evidence_ids)} 건 일치)",
        )
    except Exception as exc:
        with contextlib.suppress(Exception):
            conn.close()
        return False, [], f"ChromaDB 조회 실패로 실재 검증 건너뜀 ({exc})"


def validate_manifest_data(manifest_data: Any) -> tuple[bool, list[str], dict[str, Any]]:
    """경량 evidence manifest 데이터 구조 및 무결성을 검증합니다.

    Returns:
        (is_valid, errors, manifest_map)
    """
    errors: list[str] = []
    manifest_map: dict[str, Any] = {}

    if not isinstance(manifest_data, dict):
        errors.append("manifest 루트 데이터는 JSON 객체(dict)여야 합니다.")
        return False, errors, manifest_map

    # 1. 최상위 필수 필드 검사
    for field_name in MANIFEST_REQUIRED_FIELDS:
        if field_name not in manifest_data:
            errors.append(f"manifest 필수 필드 '{field_name}' 누락")

    if errors:
        return False, errors, manifest_map

    if (
        not isinstance(manifest_data["schema_version"], str)
        or not manifest_data["schema_version"].strip()
    ):
        errors.append("manifest 'schema_version'은 비어있지 않은 문자열이어야 합니다.")

    if not isinstance(manifest_data["created_at"], str) or not manifest_data["created_at"].strip():
        errors.append("manifest 'created_at'은 비어있지 않은 문자열이어야 합니다.")

    if (
        not isinstance(manifest_data["collection_name"], str)
        or not manifest_data["collection_name"].strip()
    ):
        errors.append("manifest 'collection_name'은 비어있지 않은 문자열이어야 합니다.")

    if (
        not isinstance(manifest_data["total_collection_documents"], int)
        or manifest_data["total_collection_documents"] < 0
    ):
        errors.append("manifest 'total_collection_documents'는 0 이상의 정수여야 합니다.")

    entries = manifest_data.get("entries")
    if not isinstance(entries, list):
        errors.append("manifest 'entries'는 리스트여야 합니다.")
        return False, errors, manifest_map

    seen_ids: set[str] = set()
    duplicate_ids: set[str] = set()

    for idx, entry in enumerate(entries):
        if not isinstance(entry, dict):
            errors.append(f"manifest entry[{idx}]가 객체(dict)가 아닙니다.")
            continue

        for e_field in MANIFEST_ENTRY_REQUIRED_FIELDS:
            if e_field not in entry:
                errors.append(f"manifest entry[{idx}] 필수 필드 '{e_field}' 누락")

        ev_id = entry.get("evidence_id")
        if not isinstance(ev_id, str) or not ev_id.strip():
            errors.append(
                f"manifest entry[{idx}] 'evidence_id'는 비어있지 않은 문자열이어야 합니다."
            )
        else:
            if ev_id in seen_ids:
                duplicate_ids.add(ev_id)
            seen_ids.add(ev_id)
            manifest_map[ev_id] = entry

        content_hash = entry.get("content_hash")
        if not isinstance(content_hash, str) or not MANIFEST_HASH_PATTERN.match(content_hash):
            errors.append(
                f"manifest entry[{idx}] (ID: '{ev_id}'): content_hash '{content_hash}' 가 "
                f"올바른 SHA-256 형식('sha256:<64자리 16진수>')이 아닙니다."
            )

    if duplicate_ids:
        errors.append(f"manifest 내에 중복된 evidence_id 가 존재합니다: {sorted(duplicate_ids)}")

    return (len(errors) == 0), errors, manifest_map


def validate_item_schema(item: dict[str, Any], index: int) -> list[str]:
    """개별 문항의 필드 존재성, 타입 및 채점 가능성을 검증합니다."""
    errors: list[str] = []
    item_id = item.get("id", f"[index_{index}]")

    # 1. 필수 필드 누락 검사
    for field_name in REQUIRED_FIELDS:
        if field_name not in item:
            errors.append(f"문항 '{item_id}' (인덱스 {index}): 필수 필드 '{field_name}' 누락")

    if errors:
        return errors

    # 2. 타입 및 값 검증
    if not isinstance(item["id"], str) or not item["id"].strip():
        errors.append(f"문항 인덱스 {index}: 'id'는 비어있지 않은 문자열이어야 합니다.")

    if not isinstance(item["question"], str) or not item["question"].strip():
        errors.append(f"문항 '{item_id}': 'question'은 비어있지 않은 문자열이어야 합니다.")

    if not isinstance(item["context_sufficient"], bool):
        errors.append(f"문항 '{item_id}': 'context_sufficient'는 불리언이어야 합니다.")

    if not isinstance(item["citation_required"], bool):
        errors.append(f"문항 '{item_id}': 'citation_required'는 불리언이어야 합니다.")

    if not isinstance(item["refusal_expected"], bool):
        errors.append(f"문항 '{item_id}': 'refusal_expected'는 불리언이어야 합니다.")

    if not isinstance(item["expected_evidence_ids"], list):
        errors.append(f"문항 '{item_id}': 'expected_evidence_ids'는 문자열 리스트여야 합니다.")
    else:
        for ev_id in item["expected_evidence_ids"]:
            if not isinstance(ev_id, str):
                errors.append(f"문항 '{item_id}': evidence_id '{ev_id}'는 문자열이어야 합니다.")

    # forbidden_literals 검증
    if not isinstance(item["forbidden_literals"], list):
        errors.append(f"문항 '{item_id}': 'forbidden_literals'는 문자열 리스트여야 합니다.")
    else:
        for literal in item["forbidden_literals"]:
            if not isinstance(literal, str):
                errors.append(
                    f"문항 '{item_id}': forbidden_literal '{literal}'는 문자열이어야 합니다."
                )
            elif literal not in KNOWN_INTERNAL_CODES:
                errors.append(
                    f"문항 '{item_id}': forbidden_literal '{literal}'은(는) 알려진 내부 코드({sorted(KNOWN_INTERNAL_CODES)})에 없습니다."
                )
        # 알려진 내부 코드가 모두 포함되어 있는지 확인
        missing_codes = KNOWN_INTERNAL_CODES - set(item["forbidden_literals"])
        if missing_codes:
            errors.append(
                f"문항 '{item_id}': forbidden_literals 에 알려진 내부 코드 {sorted(missing_codes)} 가 누락되었습니다."
            )

    # semantic_forbidden_claims 검증
    if not isinstance(item["semantic_forbidden_claims"], list):
        errors.append(f"문항 '{item_id}': 'semantic_forbidden_claims'는 문자열 리스트여야 합니다.")
    else:
        for claim in item["semantic_forbidden_claims"]:
            if not isinstance(claim, str) or not claim.strip():
                errors.append(
                    f"문항 '{item_id}': semantic_forbidden_claims 원소가 비어있거나 문자열이 아닙니다."
                )
        if len(item["semantic_forbidden_claims"]) == 0:
            errors.append(f"문항 '{item_id}': 'semantic_forbidden_claims' 리스트가 비어있습니다.")

    if not (isinstance(item["scoring_rubric"], (str, dict)) and item["scoring_rubric"]):
        errors.append(
            f"문항 '{item_id}': 'scoring_rubric'은 비어있지 않은 문자열 또는 딕셔너리여야 합니다."
        )

    num_tol = item["numeric_tolerance"]
    if num_tol is not None and not isinstance(num_tol, (int, float, dict)):
        errors.append(
            f"문항 '{item_id}': 'numeric_tolerance'는 숫자, dict 또는 None 이어야 합니다."
        )

    # expected_facts 채점 가능성 검사 + 복합 numeric 팩트 검출
    facts = item["expected_facts"]
    if not isinstance(facts, list):
        errors.append(f"문항 '{item_id}': 'expected_facts'는 리스트여야 합니다.")
    elif item["context_sufficient"] and len(facts) == 0:
        errors.append(
            f"문항 '{item_id}': context_sufficient=True 인 문항의 expected_facts 가 비어있습니다."
        )
    elif isinstance(facts, list):
        for f_idx, fact in enumerate(facts):
            if isinstance(fact, str):
                if not fact.strip():
                    errors.append(
                        f"문항 '{item_id}': expected_facts[{f_idx}] 문자열이 비어있습니다."
                    )
            elif isinstance(fact, dict):
                if "statement" not in fact or not str(fact.get("statement", "")).strip():
                    errors.append(
                        f"문항 '{item_id}': expected_facts[{f_idx}] 에 유효한 'statement'가 없습니다."
                    )
                if "verification_criterion" not in fact:
                    errors.append(
                        f"문항 '{item_id}': expected_facts[{f_idx}] 에 'verification_criterion'이 없습니다."
                    )
                if "fact_type" not in fact:
                    errors.append(
                        f"문항 '{item_id}': expected_facts[{f_idx}] 에 'fact_type'이 없습니다."
                    )
                else:
                    fact_type = fact["fact_type"]
                    if fact_type not in ("proposition", "numeric", "refusal"):
                        errors.append(
                            f"문항 '{item_id}': expected_facts[{f_idx}] 의 fact_type 이 'proposition', 'numeric', 'refusal' 중 하나가 아닙니다: {fact_type}"
                        )
                    if fact_type == "numeric":
                        if "expected_value" not in fact or fact["expected_value"] is None:
                            errors.append(
                                f"문항 '{item_id}': numeric 타입 expected_facts[{f_idx}] 에 'expected_value'가 필요합니다."
                            )
                        if "unit" not in fact or fact["unit"] is None:
                            errors.append(
                                f"문항 '{item_id}': numeric 타입 expected_facts[{f_idx}] 에 'unit'이 필요합니다."
                            )
                        if "tolerance" not in fact or fact["tolerance"] is None:
                            errors.append(
                                f"문항 '{item_id}': numeric 타입 expected_facts[{f_idx}] 에 'tolerance'가 필요합니다."
                            )
                        # 복합 numeric 팩트 검출: statement 에 낙찰금액과 낙찰률이 둘 다 있으면 오류
                        statement = str(fact.get("statement", ""))
                        if COMPOUND_NUMERIC_PATTERN.search(statement):
                            errors.append(
                                f"문항 '{item_id}': expected_facts[{f_idx}] 는 복합 numeric 팩트입니다(낙찰금액과 낙찰률 동시 언급). 원자 단위로 분해해야 합니다. statement: {statement}"
                            )
            else:
                errors.append(
                    f"문항 '{item_id}': expected_facts[{f_idx}] 은 dict 또는 str 이어야 합니다."
                )

    # 3. 논리 정합성 검사
    if item["context_sufficient"]:
        if len(item.get("expected_evidence_ids", [])) == 0:
            errors.append(
                f"문항 '{item_id}': context_sufficient=True 인 문항은 expected_evidence_ids 가 1개 이상 필요합니다."
            )
        if item["refusal_expected"]:
            errors.append(
                f"문항 '{item_id}': context_sufficient=True 인 문항에 refusal_expected=True 가 지정되었습니다."
            )
    else:
        if not item["refusal_expected"]:
            errors.append(
                f"문항 '{item_id}': context_sufficient=False 인 문항은 refusal_expected=True 여야 합니다."
            )

    return errors


def validate_fixture_data(
    data: Any,
    min_context_sufficient: int = DEFAULT_MIN_CONTEXT_SUFFICIENT,
    check_kb_existence: bool = True,
    manifest_path: Path | str | None = DEFAULT_MANIFEST_PATH,
    check_manifest: bool = True,
    collection_name: str = DEFAULT_COLLECTION_NAME,
) -> tuple[bool, list[str], dict[str, Any]]:
    """전체 fixture 데이터 구조, 집합 무결성, manifest 대조(fail-closed) 및 KB 근거 실재성을 검증합니다."""
    errors: list[str] = []

    if isinstance(data, dict):
        items = data.get("items")
        if not isinstance(items, list):
            errors.append("최상위 JSON 객체에 'items' 배열이 누락되었거나 유효하지 않습니다.")
            return False, errors, {}
    elif isinstance(data, list):
        items = data
    else:
        errors.append("최상위 JSON 데이터는 객체(dict with 'items') 또는 리스트여야 합니다.")
        return False, errors, {}

    if len(items) == 0:
        errors.append("문항 목록(items)이 비어있습니다.")
        return False, errors, {}

    seen_ids: set[str] = set()
    duplicate_ids: set[str] = set()
    all_evidence_ids: set[str] = set()
    context_sufficient_count = 0
    refusal_count = 0
    has_self_contradiction_rule = False

    for idx, raw_item in enumerate(items):
        if not isinstance(raw_item, dict):
            errors.append(f"인덱스 {idx}의 항목이 JSON 객체(dict)가 아닙니다.")
            continue

        item_id = raw_item.get("id")
        if isinstance(item_id, str) and item_id:
            if item_id in seen_ids:
                duplicate_ids.add(item_id)
            seen_ids.add(item_id)

        item_errors = validate_item_schema(raw_item, idx)
        errors.extend(item_errors)

        if raw_item.get("context_sufficient") is True:
            context_sufficient_count += 1
            for ev_id in raw_item.get("expected_evidence_ids") or []:
                if isinstance(ev_id, str) and ev_id.strip():
                    all_evidence_ids.add(ev_id.strip())

        if raw_item.get("refusal_expected") is True:
            refusal_count += 1

        # 자기모순 규칙은 semantic_forbidden_claims 에서 확인
        semantic_claims = raw_item.get("semantic_forbidden_claims") or []
        if isinstance(semantic_claims, list):
            for pattern in semantic_claims:
                if isinstance(pattern, str) and (
                    "자기모순" in pattern or ("없" in pattern and "비교" in pattern)
                ):
                    has_self_contradiction_rule = True

    if duplicate_ids:
        errors.append(f"중복된 문항 ID가 발견되었습니다: {sorted(duplicate_ids)}")

    if context_sufficient_count < min_context_sufficient:
        errors.append(
            f"context_sufficient=True 문항 수({context_sufficient_count})가 "
            f"요구 기준({min_context_sufficient})에 미달합니다."
        )

    if not has_self_contradiction_rule:
        errors.append(
            "semantic_forbidden_claims 에 관측된 '자기모순' 유형(데이터 부재 주장 후 비교 수행) 제재 규칙이 누락되었습니다."
        )

    # 4. 경량 evidence manifest 대조 검증 (fail-closed)
    manifest_status = "미수행"
    if check_manifest:
        if manifest_path is None:
            errors.append(
                "manifest 검증이 활성화되었으나 manifest_path 가 지정되지 않았습니다. (fail-closed)"
            )
            manifest_status = "경로 미제공으로 검증 실패"
        else:
            mpath = Path(manifest_path)
            if not mpath.exists() or not mpath.is_file():
                errors.append(
                    f"경량 evidence manifest 파일('{mpath}')이 존재하지 않습니다. (fail-closed)"
                )
                manifest_status = f"파일 미존재('{mpath}')로 검증 실패 (fail-closed)"
            else:
                try:
                    mcontent = mpath.read_text(encoding="utf-8")
                    mdata = json.loads(mcontent)
                    m_valid, m_errors, m_map = validate_manifest_data(mdata)
                    if not m_valid:
                        for merr in m_errors:
                            errors.append(f"manifest 무결성 오류: {merr}")
                        manifest_status = f"manifest 무결성 위반 ({len(m_errors)}건)"
                    else:
                        missing_in_manifest = sorted(all_evidence_ids - set(m_map.keys()))
                        if missing_in_manifest:
                            errors.append(
                                f"evidence manifest 에 존재하지 않는 expected_evidence_ids 발견: {missing_in_manifest}"
                            )
                            manifest_status = f"근거 ID 불일치 (누락 {len(missing_in_manifest)}건)"
                        else:
                            manifest_status = f"manifest 대조 완료 ({len(all_evidence_ids)}/{len(m_map)} 건 일치, '{mpath}')"
                except (json.JSONDecodeError, OSError) as exc:
                    errors.append(f"evidence manifest 파일('{mpath}') 파싱/읽기 실패 ({exc})")
                    manifest_status = f"파일 읽기/파싱 실패 ({exc})"
    else:
        manifest_status = "옵트아웃으로 건너뜀"

    # 5. ChromaDB 실재 근거 존재성 검증 (로컬/서버에 ChromaDB 가 있는 경우)
    kb_status = "미수행"
    if check_kb_existence and all_evidence_ids:
        kb_available, missing_ids, kb_status = verify_evidence_ids_in_kb(
            all_evidence_ids, collection_name=collection_name
        )
        if kb_available and missing_ids:
            errors.append(
                f"ChromaDB {collection_name} 에 실재하지 않는 expected_evidence_ids 발견: {missing_ids}"
            )

    stats = {
        "total_items": len(items),
        "context_sufficient_count": context_sufficient_count,
        "refusal_expected_count": refusal_count,
        "unique_ids_count": len(seen_ids),
        "total_evidence_ids_count": len(all_evidence_ids),
        "manifest_verification_status": manifest_status,
        "kb_verification_status": kb_status,
    }

    return (len(errors) == 0), errors, stats


def validate_file(
    file_path: Path | str,
    min_context_sufficient: int = DEFAULT_MIN_CONTEXT_SUFFICIENT,
    quiet: bool = False,
    manifest_path: Path | str | None = DEFAULT_MANIFEST_PATH,
    check_manifest: bool = True,
    collection_name: str = DEFAULT_COLLECTION_NAME,
) -> int:
    """파일을 읽어 검증하고 규약에 따른 종료 코드를 반환합니다."""
    path = Path(file_path)
    if not path.exists() or not path.is_file():
        if not quiet:
            print(f"오류: 파일 '{path}' 을(를) 찾을 수 없습니다.", file=sys.stderr)
        return 2

    try:
        content = path.read_text(encoding="utf-8")
        data = json.loads(content)
    except (json.JSONDecodeError, OSError) as exc:
        if not quiet:
            print(f"오류: 파일 '{path}' 파싱 실패 ({exc})", file=sys.stderr)
        return 2

    is_valid, errors, stats = validate_fixture_data(
        data,
        min_context_sufficient=min_context_sufficient,
        check_kb_existence=True,
        manifest_path=manifest_path,
        check_manifest=check_manifest,
        collection_name=collection_name,
    )

    if not is_valid:
        if not quiet:
            print(
                f"[FAIL] LLM 품질 평가 fixture 검증 실패 ({len(errors)}건의 위반):", file=sys.stderr
            )
            for err in errors:
                print(f"  - {err}", file=sys.stderr)
        return 1

    if not quiet:
        print("[PASS] LLM 품질 평가 fixture 검증 성공")
        print(f"  - 전체 문항 수: {stats['total_items']}")
        print(
            f"  - 컨텍스트 충족 문항: {stats['context_sufficient_count']} (기준 >= {min_context_sufficient})"
        )
        print(f"  - 거절 기대 문항: {stats['refusal_expected_count']}")
        print(f"  - 고유 ID 수: {stats['unique_ids_count']}")
        print(f"  - Manifest 대조 검증: {stats['manifest_verification_status']}")
        print(f"  - 지식베이스 실재 검증: {stats['kb_verification_status']}")

    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="LLM 품질 평가 fixture 스키마, 채점 가능성 및 KB 실재성 검증 도구"
    )
    parser.add_argument(
        "file",
        nargs="?",
        default="data/eval/llm_quality_fixture_v1.json",
        help="검증할 fixture JSON 파일 경로 (기본값: data/eval/llm_quality_fixture_v1.json)",
    )
    parser.add_argument(
        "--min-context-sufficient",
        type=int,
        default=DEFAULT_MIN_CONTEXT_SUFFICIENT,
        help=f"요구되는 최소 context_sufficient 문항 수 (기본값: {DEFAULT_MIN_CONTEXT_SUFFICIENT})",
    )
    parser.add_argument(
        "--manifest-path",
        default=str(DEFAULT_MANIFEST_PATH),
        help=f"대조할 경량 evidence manifest 경로 (기본값: {DEFAULT_MANIFEST_PATH})",
    )
    parser.add_argument(
        "--collection",
        default=DEFAULT_COLLECTION_NAME,
        help=f"조회할 ChromaDB 컬렉션 이름 (기본값: {DEFAULT_COLLECTION_NAME})",
    )
    parser.add_argument(
        "--skip-manifest-check",
        action="store_true",
        default=False,
        help="manifest 검증을 건너뜁니다 (과도기 전용 명시적 옵트아웃, 기본값: 검증 활성화).",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="정상 통과 시 출력을 억제합니다 (종료 코드 0 유지).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    check_manifest = not args.skip_manifest_check
    return validate_file(
        file_path=args.file,
        min_context_sufficient=args.min_context_sufficient,
        quiet=args.quiet,
        manifest_path=args.manifest_path,
        check_manifest=check_manifest,
        collection_name=args.collection,
    )


if __name__ == "__main__":
    sys.exit(main())

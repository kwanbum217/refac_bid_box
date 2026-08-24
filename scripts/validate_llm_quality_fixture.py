"""
scripts/validate_llm_quality_fixture.py

LLM 품질 평가 fixture (data/eval/llm_quality_fixture_v1.json) 스키마 및 무결성 검증기.
표준 라이브러리만을 사용하여 필수 필드 누락, 타입 불일치, ID 중복, context_sufficient
문항 수 하한 미달, 채점 가능성 및 자기모순 금지 규칙을 엄격히 검증합니다.

규약:
- 종료 코드 0: 검증 통과
- 종료 코드 1: 스키마/무결성 위반 검출
- 종료 코드 2: 파일 미존재/인자 오류/JSON 파싱 실패
- --quiet 플래그 지원 (통과 시 출력 억제)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REQUIRED_FIELDS = (
    "id",
    "question",
    "context_sufficient",
    "expected_evidence_ids",
    "expected_facts",
    "must_not_claim",
    "citation_required",
    "refusal_expected",
    "numeric_tolerance",
    "scoring_rubric",
)

DEFAULT_MIN_CONTEXT_SUFFICIENT = 15


class ValidationError(Exception):
    """Fixture 스키마 또는 도메인 무결성 위반 예외."""


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

    if not isinstance(item["must_not_claim"], list):
        errors.append(f"문항 '{item_id}': 'must_not_claim'은 문자열 리스트여야 합니다.")
    elif len(item["must_not_claim"]) == 0:
        errors.append(f"문항 '{item_id}': 'must_not_claim' 리스트가 비어있습니다.")

    if not (isinstance(item["scoring_rubric"], (str, dict)) and item["scoring_rubric"]):
        errors.append(
            f"문항 '{item_id}': 'scoring_rubric'은 비어있지 않은 문자열 또는 딕셔너리여야 합니다."
        )

    # numeric_tolerance 타입 검사 (None, int, float, dict 허용)
    num_tol = item["numeric_tolerance"]
    if num_tol is not None and not isinstance(num_tol, (int, float, dict)):
        errors.append(
            f"문항 '{item_id}': 'numeric_tolerance'는 숫자, dict 또는 None 이어야 합니다."
        )

    # expected_facts 채점 가능성 검사
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
) -> tuple[bool, list[str], dict[str, Any]]:
    """전체 fixture 데이터 구조 및 집합 무결성을 검증합니다."""
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
        if raw_item.get("refusal_expected") is True:
            refusal_count += 1

        # 자기모순 금지 문구 포함 여부 검사
        must_not = raw_item.get("must_not_claim") or []
        if isinstance(must_not, list):
            for pattern in must_not:
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
            "must_not_claim 에 관측된 '자기모순' 유형(데이터 부재 주장 후 비교 수행) 제재 규칙이 누락되었습니다."
        )

    stats = {
        "total_items": len(items),
        "context_sufficient_count": context_sufficient_count,
        "refusal_expected_count": refusal_count,
        "unique_ids_count": len(seen_ids),
    }

    return (len(errors) == 0), errors, stats


def validate_file(
    file_path: Path | str,
    min_context_sufficient: int = DEFAULT_MIN_CONTEXT_SUFFICIENT,
    quiet: bool = False,
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
        data, min_context_sufficient=min_context_sufficient
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

    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="LLM 품질 평가 fixture 스키마 및 채점 가능성 검증 도구"
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
        "--quiet",
        action="store_true",
        help="정상 통과 시 출력을 억제합니다 (종료 코드 0 유지).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    return validate_file(
        file_path=args.file,
        min_context_sufficient=args.min_context_sufficient,
        quiet=args.quiet,
    )


if __name__ == "__main__":
    sys.exit(main())

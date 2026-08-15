"""
scripts/validate_review_report.py

ORCA_REVIEW_DONE_V2 리뷰 보고가 계약 조건을 만족하는지 기계로 판정합니다.

조건은 docs/ops/orca_task_capsule_v2.md 4.1.2 절의 네 항목입니다. 조항만 두고
손으로 대조하면 놓칩니다. 2026-08-15 감도 시험에서 Reviewer 한 대가 조건 3 을
어겼고 코디네이터가 우연히 발견했습니다.

사용 예:
    uv run python scripts/validate_review_report.py \
        --capsule <capsule.yaml> --report <review_report.json>
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

# Capsule 의 review_checklist 항목에서 뽑아야 하는 필드
CHECKLIST_ITEM_FIELDS = ("id", "question", "defect_when")

# 결함을 시사하는 answer 로 인정하는 표기. 모델이 대소문자나 한국어를 섞어 씁니다.
_YES = {"yes", "y", "true", "예", "있음"}
_NO = {"no", "n", "false", "아니오", "아니요", "없음"}


def _normalize_answer(value: Any) -> str | None:
    """answer 를 yes/no 로 정규화합니다. 판단 불가면 None."""
    if not isinstance(value, str):
        return None
    token = value.strip().lower()
    if token in _YES:
        return "yes"
    if token in _NO:
        return "no"
    return None


def parse_checklist(capsule_text: str) -> list[dict[str, str]]:
    """Capsule 의 review_checklist 를 읽습니다.

    PyYAML 을 새로 추가하지 않기 위해 필요한 필드만 정규식으로 뽑습니다.
    중첩이 얕고 형식이 고정돼 있어 이 범위에서는 충분합니다.
    """
    lines = capsule_text.splitlines()
    start_idx = -1
    for idx, line in enumerate(lines):
        if re.match(r"^review_checklist:\s*(?:#.*)?$", line):
            start_idx = idx
            break
    if start_idx == -1:
        return []

    items: list[dict[str, str]] = []
    current: dict[str, str] = {}
    current_folded_key: str | None = None
    current_folded_lines: list[str] = []

    def flush_folded() -> None:
        nonlocal current_folded_key, current_folded_lines
        if current_folded_key:
            joined = " ".join(s.strip() for s in current_folded_lines if s.strip()).strip()
            current[current_folded_key] = joined
            current_folded_key = None
            current_folded_lines = []

    for raw in lines[start_idx + 1 :]:
        if raw and not raw[0].isspace():
            if raw.startswith("#"):
                continue  # 0열 주석
            break  # 다음 최상위 키

        line = raw.strip()
        if not line or line.startswith("#"):
            continue

        if line.startswith("- "):
            flush_folded()
            if current:
                items.append(current)
                current = {}
            line = line[2:].strip()

        match = re.match(r"^([a-z_]+):\s*(.*)$", line)
        if match:
            flush_folded()
            key = match.group(1)
            raw_val = match.group(2).strip()
            clean_val = re.sub(r"\s+#.*$", "", raw_val).strip()
            if clean_val in (">", "|", ">-", "|-"):
                current_folded_key = key
                current_folded_lines = []
            else:
                val = clean_val.strip("\"'")
                current[key] = val
        elif current_folded_key:
            current_folded_lines.append(line)

    flush_folded()
    if current:
        items.append(current)

    return [item for item in items if item.get("id")]


def _matches_id(target_id: str, value: Any) -> bool:
    """단일 값 또는 컬렉션이 target_id 와 정확히 또는 단어 경계 기준으로 일치하는지 확인합니다."""
    if not value:
        return False
    if isinstance(value, str):
        if value.strip() == target_id:
            return True
        return bool(re.search(rf"\b{re.escape(target_id)}\b", value))
    if isinstance(value, (list, tuple, set)):
        return any(_matches_id(target_id, v) for v in value)
    return False


def _issue_matches_id(issue: Any, target_id: str) -> bool:
    """개별 blocking issue 항목에서 target_id 존재 여부를 판별합니다."""
    if isinstance(issue, str):
        return _matches_id(target_id, issue)
    if isinstance(issue, dict):
        for key in ("id", "ids", "checklist_id", "checklist_ids", "title", "name", "defect_id"):
            if key in issue and _matches_id(target_id, issue[key]):
                return True
        if "description" in issue:
            return _matches_id(target_id, issue["description"])
        return False
    if isinstance(issue, (list, tuple, set)):
        return any(_issue_matches_id(sub, target_id) for sub in issue)
    return False


def _blocking_contains_id(blocking: Any, target_id: str) -> bool:
    """blocking_issues 전체에서 target_id 존재 여부를 대조합니다."""
    if isinstance(blocking, list):
        return any(_issue_matches_id(issue, target_id) for issue in blocking)
    return _issue_matches_id(blocking, target_id)


def evaluate(checklist: list[dict[str, str]], report: dict[str, Any]) -> dict[str, Any]:
    """네 조건을 판정하고 실효 verdict 를 냅니다."""
    results = report.get("checklist_results") or []
    by_id = {str(r.get("id")): r for r in results if isinstance(r, dict)}
    blocking = report.get("blocking_issues") or []

    violations: list[str] = []

    # 조건 1: 모든 id 에 대응 항목이 있다
    missing = [item["id"] for item in checklist if item["id"] not in by_id]
    if missing:
        violations.append(f"조건1 위반: checklist_results 에 없는 id {missing}")

    # 조건 2: 각 항목이 answer 와 evidence 를 가진다
    for item in checklist:
        entry = by_id.get(item["id"])
        if entry is None:
            continue
        if _normalize_answer(entry.get("answer")) is None:
            violations.append(
                f"조건2 위반: {item['id']} 의 answer 를 yes/no 로 읽을 수 없음"
                f" ({entry.get('answer')!r})"
            )
        if not str(entry.get("evidence") or "").strip():
            violations.append(f"조건2 위반: {item['id']} 에 evidence 없음")

    # 조건 3: 결함을 시사하는 answer 에는 대응 blocking_issues 가 있다
    defects: list[str] = []
    for item in checklist:
        entry = by_id.get(item["id"])
        polarity = _normalize_answer(item.get("defect_when"))
        if entry is None or polarity is None:
            if entry is not None and polarity is None:
                violations.append(
                    f"조건3 판정 불가: {item['id']} 에 defect_when 이 없어 극성을 알 수 없음"
                )
            continue
        if _normalize_answer(entry.get("answer")) == polarity:
            defects.append(item["id"])
            if not _blocking_contains_id(blocking, item["id"]):
                violations.append(f"조건3 위반: {item['id']} 이 결함인데 blocking_issues 에 없음")

    # 조건 4: pass 인데 checklist_results 가 비면 insufficient_context
    declared = str(report.get("verdict") or "").strip()
    effective = declared
    if declared == "pass" and not results:
        effective = "insufficient_context"
        violations.append("조건4 적용: pass 인데 checklist_results 가 비어 실효 판정을 격하")
    if declared == "pass" and defects:
        effective = "fail"
        violations.append(
            f"조건4 적용: 결함 {defects} 을 확인했는데 pass 를 선언해 실효 판정을 fail 로 정정"
        )

    return {
        "checklist_count": len(checklist),
        "results_count": len(results),
        "defect_ids": defects,
        "blocking_count": len(blocking) if isinstance(blocking, list) else 1,
        "declared_verdict": declared,
        "effective_verdict": effective,
        "violations": violations,
        "ok": not violations,
    }


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="ORCA_REVIEW_DONE_V2 리뷰 보고의 계약 조건을 판정합니다."
    )
    parser.add_argument("--capsule", required=True, help="review_checklist 를 담은 Capsule 경로")
    parser.add_argument("--report", required=True, help="리뷰 보고 JSON 경로")
    parser.add_argument("--json", action="store_true", help="판정 결과를 JSON 으로 출력")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    capsule_path = Path(args.capsule)
    report_path = Path(args.report)

    for path in (capsule_path, report_path):
        if not path.exists():
            print(f"파일 없음: {path}", file=sys.stderr)
            return 2

    checklist = parse_checklist(capsule_path.read_text(encoding="utf-8"))
    if not checklist:
        print(
            f"경고: {capsule_path} 에서 review_checklist 를 찾지 못했습니다. "
            "체크리스트 없는 리뷰는 조건 1~3 을 판정할 수 없습니다.",
            file=sys.stderr,
        )

    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"보고 JSON 파싱 실패: {exc}", file=sys.stderr)
        return 2

    verdict = evaluate(checklist, report)

    if args.json:
        print(json.dumps(verdict, ensure_ascii=False, indent=2))
    else:
        print("ORCA_REVIEW_DONE_V2 계약 판정")
        print("-" * 66)
        print(f"체크리스트 항목      {verdict['checklist_count']}")
        print(f"보고된 항목          {verdict['results_count']}")
        print(f"결함 확인 항목       {verdict['defect_ids'] or '없음'}")
        print(f"blocking_issues      {verdict['blocking_count']}건")
        print(f"선언 verdict         {verdict['declared_verdict'] or '(없음)'}")
        print(f"실효 verdict         {verdict['effective_verdict'] or '(없음)'}")
        print("-" * 66)
        if verdict["violations"]:
            for line in verdict["violations"]:
                print(f"  {line}")
            print("-" * 66)
            print("판정: 계약 위반. 리뷰를 받지 말고 재실행하십시오.")
        else:
            print("판정: 계약 만족.")

    return 0 if verdict["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""빌더 Capsule 의 review_checklist 를 그대로 옮겨 리뷰 Intent 를 만듭니다.

Level 1 게이트 5(`scripts/validate_review_report.py`)는 **빌더 Capsule** 의
`review_checklist` 를 정본으로 삼아 id 누락과 `defect_when` 극성을 판정합니다.
리뷰 Intent 에 질문을 다시 쓰면 id 나 극성이 어긋나 검토 내용이 옳아도 게이트가
실패합니다. 그래서 체크리스트는 손으로 옮기지 않고 이 도구로 복사합니다.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml


def load_checklist(capsule_path: Path) -> list[dict]:
    data = yaml.safe_load(capsule_path.read_text(encoding="utf-8")) or {}
    checklist = data.get("review_checklist") or []
    if not checklist:
        raise SystemExit(f"빌더 Capsule 에 review_checklist 가 없습니다: {capsule_path}")
    return checklist


def render(checklist: list[dict], extra: list[dict]) -> str:
    lines = ["review_checklist:"]
    for item in list(checklist) + list(extra):
        lines.append(f"  - id: {item['id']}")
        # json.dumps 의 큰따옴표 이스케이프는 YAML 의 double-quoted scalar 와 호환됩니다.
        lines.append(f"    question: {json.dumps(item['question'], ensure_ascii=False)}")
        lines.append(f'    defect_when: "{item["defect_when"]}"')
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capsule", required=True, help="빌더 Capsule YAML 경로")
    parser.add_argument("--intent", required=True, help="교체할 리뷰 Intent YAML 경로")
    parser.add_argument(
        "--extra",
        default=None,
        help="리뷰어 전용 추가 항목 YAML 경로 (review_checklist 키를 가진 파일)",
    )
    args = parser.parse_args()

    checklist = load_checklist(Path(args.capsule))
    extra: list[dict] = []
    if args.extra:
        extra = (yaml.safe_load(Path(args.extra).read_text(encoding="utf-8")) or {}).get(
            "review_checklist"
        ) or []

    intent_path = Path(args.intent)
    text = intent_path.read_text(encoding="utf-8")
    start = text.index("review_checklist:")
    end = text.index("report_path:")
    intent_path.write_text(text[:start] + render(checklist, extra) + text[end:], encoding="utf-8")
    ids = [item["id"] for item in checklist] + [item["id"] for item in extra]
    print(f"리뷰 Intent 체크리스트를 빌더 Capsule 기준으로 교체했습니다: {ids}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

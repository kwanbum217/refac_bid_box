"""scripts/check_chat_gold_measurer_split.py

챗봇 점검 정답과 측정기를 같은 브랜치에서 함께 고치지 못하게 막습니다.

점검 점수는 정답 JSON(`data/benchmarks/chat_user_questions_*.json`)과 측정기
(`scripts/measure_chat_user_questions.py`)의 합으로 나옵니다. 한 브랜치에서 둘을
함께 고치면 측정기가 만점을 받아도 그 점수는 품질 근거가 될 수 없습니다. 정답을
측정기에 맞추거나 측정기를 정답에 맞춰 점수를 조정했는지 diff 만으로 구분할 수
없기 때문입니다.

이 스크립트는 경로 목록만 판정합니다. git 을 직접 호출하지 않으므로 호출하는
쪽이 `git diff --name-only main...HEAD` 같은 명령의 출력을 넘깁니다. 두 종류 중
한쪽만 바뀌면 통과, 두 종류가 모두 바뀌면 결함입니다. 이미 병합된 과거 커밋은
되돌리지 않으며 앞으로의 브랜치 diff 만 막습니다.

사용 예:

    git diff --name-only main...HEAD | python3 scripts/check_chat_gold_measurer_split.py
    python3 scripts/check_chat_gold_measurer_split.py scripts/measure_chat_user_questions.py

종료 코드는 통과 0, 결함 1 입니다.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

MEASURER_PATH = "scripts/measure_chat_user_questions.py"
GOLD_PATH_PREFIX = "data/benchmarks/chat_user_questions_"

STATUS_OK = "pass"
STATUS_DEFECT = "defect"


@dataclass(frozen=True)
class SplitVerdict:
    """경로 목록 판정 결과입니다. 두 종류가 모두 있으면 결함입니다."""

    measurer_paths: tuple[str, ...]
    gold_paths: tuple[str, ...]

    @property
    def is_defect(self) -> bool:
        return bool(self.measurer_paths and self.gold_paths)

    @property
    def status(self) -> str:
        return STATUS_DEFECT if self.is_defect else STATUS_OK

    def describe(self) -> str:
        if not self.is_defect:
            return "통과: 챗봇 점검 정답과 측정기를 한 브랜치에서 함께 고치지 않았습니다."
        lines = [
            "결함: 챗봇 점검 정답과 측정기가 한 브랜치에서 함께 바뀌었습니다.",
            "측정기가 만점이어도 정답을 같은 커밋에서 고친 점수는 품질 근거로 받지 않습니다.",
            "측정기:",
            *(f"  - {path}" for path in self.measurer_paths),
            "정답:",
            *(f"  - {path}" for path in self.gold_paths),
        ]
        return "\n".join(lines)


def normalize_path(path: str) -> str:
    """저장소 기준 상대 경로로 비교할 수 있게 앞뒤 공백과 `./` 를 정리합니다."""
    normalized = path.strip().replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def judge_paths(paths: Iterable[str]) -> SplitVerdict:
    """변경 경로 목록에서 측정기와 정답 경로를 찾아 통과/결함을 판정합니다."""
    measurer_paths: list[str] = []
    gold_paths: list[str] = []
    for raw_path in paths:
        path = normalize_path(raw_path)
        if not path:
            continue
        if path == MEASURER_PATH:
            measurer_paths.append(path)
        elif path.startswith(GOLD_PATH_PREFIX):
            gold_paths.append(path)
    return SplitVerdict(
        measurer_paths=tuple(dict.fromkeys(measurer_paths)),
        gold_paths=tuple(dict.fromkeys(gold_paths)),
    )


def _read_paths(cli_paths: Sequence[str]) -> list[str]:
    if cli_paths:
        return list(cli_paths)
    if sys.stdin.isatty():
        raise SystemExit(
            "경로 목록이 없습니다. 인자로 넘기거나 표준 입력으로 한 줄에 하나씩 넘기십시오."
        )
    return sys.stdin.read().splitlines()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="챗봇 점검 정답과 측정기의 같은 브랜치 동시 수정 검사",
    )
    parser.add_argument(
        "paths",
        nargs="*",
        help="저장소 기준 변경 경로 목록. 생략하면 표준 입력에서 한 줄에 하나씩 읽습니다.",
    )
    args = parser.parse_args(argv)

    verdict = judge_paths(_read_paths(args.paths))
    if verdict.is_defect:
        sys.stderr.write(f"{verdict.describe()}\n")
        return 1
    sys.stdout.write(f"{verdict.describe()}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

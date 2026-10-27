"""tests/test_chat_gold_measurer_split.py

챗봇 점검 정답 JSON 과 측정기를 한 브랜치에서 함께 고치면 실패하는 검사입니다.

판정 함수는 git 을 모르는 순수 함수입니다. 가짜 경로 목록으로 결함과 통과를 먼저
고정하고, 이어서 현재 브랜치의 실제 `git diff --name-only main...HEAD` 결과를 같은
함수에 넣습니다. 브랜치가 정답과 측정기를 함께 바꾸면 이 테스트가 실패해 측정기가
만점이어도 그 점수를 품질 근거로 쓸 수 없게 합니다. main 자체에서는 diff 가 비어
통과합니다.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts import check_chat_gold_measurer_split as split_check

MEASURER = "scripts/measure_chat_user_questions.py"
GOLD = "data/benchmarks/chat_user_questions_v1.json"
GOLD_PATHS = (
    "data/benchmarks/chat_user_questions_v1.json",
    "data/benchmarks/chat_user_questions_blind_v1.json",
    "data/benchmarks/chat_user_questions_v2.json",
)
BASE_REF = "main"


def _git_command() -> str:
    git = shutil.which("git")
    if git is None:
        pytest.skip("git 실행 파일을 찾지 못해 브랜치 diff 검사를 건너뜁니다.")
    return git


def _branch_diff_paths() -> list[str]:
    git = _git_command()
    probe = subprocess.run(  # noqa: S603
        [git, "rev-parse", "--verify", "--quiet", f"{BASE_REF}^{{commit}}"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if probe.returncode != 0:
        pytest.skip(f"{BASE_REF} 기준 커밋을 찾지 못해 브랜치 diff 검사를 건너뜁니다.")
    diff = subprocess.run(  # noqa: S603
        [git, "diff", "--name-only", f"{BASE_REF}...HEAD"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert diff.returncode == 0, f"브랜치 diff 를 읽지 못했습니다: {diff.stderr[-400:]}"
    return diff.stdout.splitlines()


@pytest.mark.parametrize("gold_path", GOLD_PATHS)
def test_defect_when_gold_and_measurer_changed_together(gold_path: str):
    verdict = split_check.judge_paths([MEASURER, gold_path])

    assert verdict.is_defect is True
    assert verdict.status == split_check.STATUS_DEFECT
    assert verdict.measurer_paths == (MEASURER,)
    assert verdict.gold_paths == (gold_path,)


def test_defect_when_both_present_with_other_changes():
    verdict = split_check.judge_paths(
        [
            "tests/test_chat_gold_measurer_split.py",
            GOLD,
            "src/app/api/v1/chatbot.py",
            MEASURER,
        ]
    )

    assert verdict.is_defect is True


def test_pass_when_only_measurer_changed():
    verdict = split_check.judge_paths([MEASURER, "tests/test_chat_gold_measurer_split.py"])

    assert verdict.is_defect is False
    assert verdict.status == split_check.STATUS_OK


def test_pass_when_only_gold_changed():
    verdict = split_check.judge_paths([GOLD, "tests/test_chat_gold_measurer_split.py"])

    assert verdict.is_defect is False
    assert verdict.status == split_check.STATUS_OK


def test_pass_for_unrelated_paths_including_this_guard():
    verdict = split_check.judge_paths(
        [
            "scripts/check_chat_gold_measurer_split.py",
            "tests/test_chat_gold_measurer_split.py",
            "data/benchmarks/blind_fixture_v2_e2b_20260914.json",
        ]
    )

    assert verdict.is_defect is False


def test_pass_for_empty_path_list():
    verdict = split_check.judge_paths([])

    assert verdict.is_defect is False
    assert verdict.measurer_paths == ()
    assert verdict.gold_paths == ()


def test_normalizes_dot_slash_whitespace_and_duplicates():
    verdict = split_check.judge_paths(
        [
            f"  ./{MEASURER}  ",
            MEASURER,
            f"./{GOLD}",
            GOLD,
        ]
    )

    assert verdict.measurer_paths == (MEASURER,)
    assert verdict.gold_paths == (GOLD,)
    assert verdict.is_defect is True


def test_current_branch_diff_does_not_change_gold_and_measurer_together():
    verdict = split_check.judge_paths(_branch_diff_paths())

    assert verdict.is_defect is False, (
        f"{BASE_REF}...HEAD 가 챗봇 점검 정답과 측정기를 함께 바꿨습니다. "
        "측정기가 만점이어도 이 브랜치의 점수는 품질 근거로 받지 않습니다.\n"
        f"{verdict.describe()}"
    )


def test_cli_exit_codes():
    script = PROJECT_ROOT / "scripts" / "check_chat_gold_measurer_split.py"

    passed = subprocess.run(  # noqa: S603
        [sys.executable, str(script), MEASURER],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    defect = subprocess.run(  # noqa: S603
        [sys.executable, str(script), MEASURER, GOLD],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert passed.returncode == 0, passed.stderr[-400:]
    assert defect.returncode == 1, defect.stderr[-400:]
    assert "결함" in defect.stderr

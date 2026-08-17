from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch

from scripts.orca_level1_gate import (
    format_failed_nodes,
    format_human_output,
    get_git_changed_files,
    parse_arguments,
    parse_pytest_output,
    parse_validate_agent_rules_output,
    run_gate1_changed_files,
    run_gate2_scope,
    run_gate3_tests,
    run_gate4_rules,
    run_gate4b_lint,
    run_gate5_review_report,
    run_level1_gate,
)

GIT_BIN = shutil.which("git") or "/usr/bin/git"


def _init_git_repo(tmp_path: Path) -> tuple[Path, str, str]:
    """테스트용 임시 git 저장소를 생성합니다.

    main 과 feature 브랜치가 서로 다른 신규/수정 파일을 가지도록 구성합니다.
    """
    repo = tmp_path / "repo"
    repo.mkdir()

    subprocess.run(  # noqa: S603
        [GIT_BIN, "init", "-b", "main"],
        cwd=str(repo),
        check=True,
        capture_output=True,
    )
    subprocess.run(  # noqa: S603
        [GIT_BIN, "config", "user.email", "test@example.com"],
        cwd=str(repo),
        check=True,
        capture_output=True,
    )
    subprocess.run(  # noqa: S603
        [GIT_BIN, "config", "user.name", "Test"],
        cwd=str(repo),
        check=True,
        capture_output=True,
    )

    # 1. Base 커밋 생성
    scripts_dir = repo / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "validate_agent_rules.py").write_text(
        "print('검증 통과: 12/12 건.')\n", encoding="utf-8"
    )
    (repo / "base.txt").write_text("base content\n", encoding="utf-8")
    (repo / "common.txt").write_text("common line 1\n", encoding="utf-8")
    subprocess.run(  # noqa: S603
        [GIT_BIN, "add", "."],
        cwd=str(repo),
        check=True,
        capture_output=True,
    )
    subprocess.run(  # noqa: S603
        [GIT_BIN, "commit", "-m", "chore: initial base commit"],
        cwd=str(repo),
        check=True,
        capture_output=True,
    )

    # 2. 작업 브랜치 생성 및 변경
    branch = "feature-branch"
    subprocess.run(  # noqa: S603
        [GIT_BIN, "checkout", "-b", branch],
        cwd=str(repo),
        check=True,
        capture_output=True,
    )
    (repo / "common.txt").write_text("common line 1\nmodified line 2\n", encoding="utf-8")
    (repo / "unique_new.txt").write_text("new file on branch\n", encoding="utf-8")
    subprocess.run(  # noqa: S603
        [GIT_BIN, "add", "."],
        cwd=str(repo),
        check=True,
        capture_output=True,
    )
    subprocess.run(  # noqa: S603
        [GIT_BIN, "commit", "-m", "feat: branch changes"],
        cwd=str(repo),
        check=True,
        capture_output=True,
    )

    # 3. main 브랜치에도 별도 커밋 추가
    subprocess.run(  # noqa: S603
        [GIT_BIN, "checkout", "main"],
        cwd=str(repo),
        check=True,
        capture_output=True,
    )
    (repo / "main_only.txt").write_text("main exclusive\n", encoding="utf-8")
    subprocess.run(  # noqa: S603
        [GIT_BIN, "add", "."],
        cwd=str(repo),
        check=True,
        capture_output=True,
    )
    subprocess.run(  # noqa: S603
        [GIT_BIN, "commit", "-m", "chore: main extra commit"],
        cwd=str(repo),
        check=True,
        capture_output=True,
    )

    return repo, "main", branch


def test_git_changed_files_distinguishes_changed_and_unique_new(tmp_path: Path):
    """(1) changed_files(merge-base diff)와 unique_new_files(차집합)의 구분을 검증합니다."""
    repo, base, branch = _init_git_repo(tmp_path)

    changed, unique = get_git_changed_files(repo, base, branch)

    # common.txt 는 수정되었으므로 changed 에 포함되지만 base 에도 있으므로 unique 엔 없음
    assert "common.txt" in changed
    assert "unique_new.txt" in changed
    assert "unique_new.txt" in unique
    assert "common.txt" not in unique
    assert "main_only.txt" not in unique

    # 게이트 1 실행 결과 확인
    g1 = run_gate1_changed_files(repo, base, branch)
    assert g1.status == "pass"
    assert g1.raw_data["changed_files"] == changed
    assert g1.raw_data["unique_new_files"] == unique


def test_gate2_detects_scope_excess(tmp_path: Path):
    """(2) Capsule allowed_write_files 초과 파일이 정확히 검출되는지 검증합니다."""
    capsule = tmp_path / "capsule.yaml"
    capsule.write_text(
        """schema: ORCA_TASK_CAPSULE_V2
version: "2.1.0"
mode: worker
task_id: "task_test"
allowed_write_files:
  - "scripts/allowed.py"
  - "tests/..."
""",
        encoding="utf-8",
    )

    # 허용 범위 내 변경
    g_pass = run_gate2_scope(["scripts/allowed.py", "tests/test_foo.py"], capsule)
    assert g_pass.status == "pass"
    assert g_pass.raw_data["excess_files"] == []

    # 허용 범위 외 변경 포함
    g_fail = run_gate2_scope(
        ["scripts/allowed.py", "src/ml/unauthorized.py", "README.md"],
        capsule,
    )
    assert g_fail.status == "fail"
    assert "src/ml/unauthorized.py" in g_fail.raw_data["excess_files"]
    assert "README.md" in g_fail.raw_data["excess_files"]
    assert "scripts/allowed.py" not in g_fail.raw_data["excess_files"]


def test_gate2_skipped_when_capsule_not_specified():
    """(3) Capsule 미지정 시 게이트 2가 skipped 처리되며 pass 로 계산되지 않음을 검증합니다."""
    g = run_gate2_scope(["any_file.py"], None)
    assert g.status == "skipped"
    assert g.raw_data["excess_files"] == []


def test_pytest_output_parser_and_node_truncation():
    """(4) pytest 실패 시 요약 줄과 실패 노드(최대 5개 + 외 N건) 파싱을 검증합니다."""
    pytest_fail_output = """
.F..F.F.F.F.F.F.                                                      [100%]
=================================== FAILURES ===================================
__________________________________ test_fail1 __________________________________
FAILED tests/test_demo.py::test_one - AssertionError: 1 != 2
FAILED tests/test_demo.py::test_two - AssertionError: 2 != 3
FAILED tests/test_demo.py::test_three - AssertionError: 3 != 4
FAILED tests/test_demo.py::test_four - AssertionError: 4 != 5
FAILED tests/test_demo.py::test_five - AssertionError: 5 != 6
FAILED tests/test_demo.py::test_six - AssertionError: 6 != 7
FAILED tests/test_demo.py::test_seven - AssertionError: 7 != 8
=========================== 7 failed, 9 passed in 0.12s ===========================
"""
    summary, failed_nodes = parse_pytest_output(pytest_fail_output, "")
    assert summary == "7 failed, 9 passed in 0.12s"
    assert len(failed_nodes) == 7
    assert failed_nodes[0] == "tests/test_demo.py::test_one"

    formatted = format_failed_nodes(failed_nodes, max_show=5)
    assert "tests/test_demo.py::test_one" in formatted
    assert "tests/test_demo.py::test_five" in formatted
    assert "(외 2건)" in formatted
    assert "tests/test_demo.py::test_six" not in formatted


def test_gate3_handles_test_failure_exit_code_and_skipped():
    """(4) Gate 3 실행 시 실패 및 미지정(skipped)을 검증합니다."""
    # 1. 미지정 시 skipped
    g_skip = run_gate3_tests([], Path("."))
    assert g_skip.status == "skipped"

    # 2. 실행 실패 모의
    with patch("scripts.orca_level1_gate.run_command_safe") as mock_cmd:
        mock_cmd.return_value = (
            1,
            "FAILED tests/test_a.py::test_bad\n1 failed in 0.01s",
            "",
            False,
        )
        g_fail = run_gate3_tests(["tests/test_a.py"], Path("."))
        assert g_fail.status == "fail"
        assert g_fail.raw_data["results"][0]["failed_nodes"] == ["tests/test_a.py::test_bad"]


def test_human_output_never_exceeds_max_chars(tmp_path: Path):
    """(5) 대량의 출력이 발생해도 사람이 읽는 출력이 --max-chars 이하로 절단됨을 검증합니다."""
    repo, base, branch = _init_git_repo(tmp_path)

    # 100자 상한으로 실행
    _code, output = run_level1_gate(
        base=base,
        branch=branch,
        repo=repo,
        max_chars=100,
        as_json=False,
    )
    assert len(output) <= 100
    assert output.endswith("...(잘림)")


def test_timeout_reported_as_tool_error(tmp_path: Path):
    """(6) subprocess 타임아웃 발생 시 도구 오류(종료 코드 2)로 처리됨을 검증합니다."""
    repo, base, branch = _init_git_repo(tmp_path)

    with patch("scripts.orca_level1_gate.run_command_safe") as mock_cmd:
        # 타임아웃 플래그 True 반환 모의
        mock_cmd.return_value = (-1, "", "Command timed out", True)

        code, output = run_level1_gate(
            base=base,
            branch=branch,
            repo=repo,
            as_json=False,
        )
        assert code == 2
        assert "타임아웃" in output or "도구 오류" in output


def test_json_output_is_valid_and_contains_all_gate_keys(tmp_path: Path):
    """(7) --json 출력이 유효한 JSON 이고 5개 게이트 상태를 모두 담고 있음을 검증합니다."""
    repo, base, branch = _init_git_repo(tmp_path)

    code, output = run_level1_gate(
        base=base,
        branch=branch,
        repo=repo,
        as_json=True,
    )
    assert code == 0
    data = json.loads(output)
    assert data["verdict"] == "pass"
    assert data["exit_code"] == 0
    assert "summary" in data
    assert data["summary"]["total"] == 6
    assert data["summary"]["passed"] >= 1

    gates = data["gates"]
    assert "gate1_changed_files" in gates
    assert "gate2_scope" in gates
    assert "gate3_tests" in gates
    assert "gate4_rules" in gates
    assert "gate5_review_report" in gates
    assert gates["gate1_changed_files"]["status"] == "pass"
    assert gates["gate2_scope"]["status"] == "skipped"


def test_validate_agent_rules_output_parser():
    """Gate 4 validate_agent_rules 출력 파서 동작을 검증합니다."""
    stdout = """
============================================================
다중 에이전트 규칙 정합성 검증 (pre-commit / v2)
============================================================
[PASS] CLAUDE.md thin pointer
------------------------------------------------------------
검증 통과: 12/12 건.
"""
    summary = parse_validate_agent_rules_output(stdout, "")
    assert summary == "검증 통과: 12/12 건."


def test_gate4_rules_execution(tmp_path: Path):
    """Gate 4 validate_agent_rules 실행 성공/실패 동작을 검증합니다."""
    repo = tmp_path / "fake_repo"
    repo.mkdir()
    scripts_dir = repo / "scripts"
    scripts_dir.mkdir()
    script = scripts_dir / "validate_agent_rules.py"
    script.write_text("print('검증 통과: 12/12 건.')\n", encoding="utf-8")

    g_pass = run_gate4_rules(repo)
    assert g_pass.status == "pass"
    assert g_pass.summary == "검증 통과: 12/12 건."


def test_gate5_review_report_pass_and_fail(tmp_path: Path):
    """Gate 5 리뷰 보고서 통과 및 실패 케이스를 검증합니다."""
    capsule = tmp_path / "capsule.yaml"
    capsule.write_text(
        """schema: ORCA_TASK_CAPSULE_V2
review_checklist:
  - id: check_1
    question: "위반이 없는가?"
    defect_when: "no"
""",
        encoding="utf-8",
    )

    pass_report = tmp_path / "pass_report.json"
    pass_report.write_text(
        json.dumps(
            {
                "verdict": "pass",
                "checklist_results": [{"id": "check_1", "answer": "yes", "evidence": "good"}],
                "blocking_issues": [],
            }
        ),
        encoding="utf-8",
    )

    fail_report = tmp_path / "fail_report.json"
    fail_report.write_text(
        json.dumps(
            {
                "verdict": "pass",
                "checklist_results": [
                    {"id": "check_1", "answer": "no", "evidence": "defect found"}
                ],
                "blocking_issues": [],
            }
        ),
        encoding="utf-8",
    )

    g_pass = run_gate5_review_report(pass_report, capsule)
    assert g_pass.status == "pass"

    g_fail = run_gate5_review_report(fail_report, capsule)
    assert g_fail.status == "fail"


def test_cli_argument_parsing():
    """CLI 인자 파싱 및 기본값을 검증합니다."""
    args = parse_arguments(
        [
            "--base",
            "origin/main",
            "--branch",
            "my-feat",
            "--tests",
            "tests/test_a.py",
            "--tests",
            "tests/test_b.py",
            "--max-chars",
            "1500",
            "--json",
        ]
    )
    assert args.base == "origin/main"
    assert args.branch == "my-feat"
    assert args.tests == ["tests/test_a.py", "tests/test_b.py"]
    assert args.max_chars == 1500
    assert args.json is True


def test_format_human_output_structure():
    """사람용 텍스트 출력 형식을 검증합니다."""
    from scripts.orca_level1_gate import GateResult

    gates = [
        GateResult("게이트 1", "pass", "1건 변경"),
        GateResult("게이트 2", "skipped", "미지정"),
        GateResult("게이트 3", "fail", "1건 실패", details=["실패 상세"]),
    ]
    out = format_human_output(gates, "fail", 1, 1, 1)
    assert "[PASS]     게이트 1" in out
    assert "[SKIPPED]  게이트 2" in out
    assert "[FAIL]     게이트 3" in out
    assert "최종 판정: FAIL (통과 1 / 건너뜀 1 / 실패 1)" in out


def test_gate4b_lint_detects_repo_wide_violation(tmp_path: Path):
    """게이트 4b 는 워커가 지정하지 않은 경로의 위반도 잡아야 합니다."""
    repo = tmp_path / "lint_repo"
    (repo / "tests").mkdir(parents=True)
    (repo / "pyproject.toml").write_text(
        '[tool.ruff]\nline-length = 120\n[tool.ruff.lint]\nselect = ["F"]\n',
        encoding="utf-8",
    )
    (repo / "src.py").write_text("x = 1\n", encoding="utf-8")
    # 워커가 src 만 검사했다면 놓쳤을 위치에 미사용 import 를 둔다
    (repo / "tests" / "test_x.py").write_text("import json\n", encoding="utf-8")

    g_fail = run_gate4b_lint(repo)
    assert g_fail.status == "fail"
    assert any("test_x.py" in line for line in g_fail.details)

    (repo / "tests" / "test_x.py").write_text("x = 2\n", encoding="utf-8")
    g_pass = run_gate4b_lint(repo)
    assert g_pass.status == "pass"

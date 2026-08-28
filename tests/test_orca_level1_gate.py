from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.orca_contract import verify_verification_truth
from scripts.orca_level1_gate import (
    format_failed_nodes,
    format_human_output,
    get_git_changed_files,
    parse_arguments,
    parse_pytest_output,
    parse_validate_agent_rules_output,
    parse_verification_command,
    required_capabilities,
    requires_test_verification,
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

    changed, unique, renames = get_git_changed_files(repo, base, branch)
    assert renames == []

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
    """(7) --json 출력이 유효한 JSON 이고 6개 게이트 상태를 모두 담고 있음을 검증합니다."""
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
    assert "gate4b_lint" in gates
    assert "gate5_review_report" in gates
    assert gates["gate1_changed_files"]["status"] == "pass"
    assert gates["gate2_scope"]["status"] == "skipped"

    # 키가 실제 게이트를 가리키는지 확인합니다. 키 목록이 append 순서보다
    # 짧으면 뒤 게이트가 한 칸씩 밀려 gate_6 으로 흘러나갑니다.
    assert data["summary"]["total"] == len(gates)
    assert not [k for k in gates if k.startswith("gate_")], sorted(gates)
    assert gates["gate4_rules"]["name"] == "게이트 4 규칙 검증"
    assert gates["gate4b_lint"]["name"] == "게이트 4b 린터"
    assert gates["gate5_review_report"]["name"] == "게이트 5 리뷰 보고"


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


def test_strict_mode_treats_skipped_gates_as_failure(tmp_path: Path):
    """건너뛴 게이트는 검증하지 않았다는 뜻이므로 --strict 에서 통과가 아닙니다.

    Capsule, 테스트, 리뷰 보고를 전부 생략하면 3개 게이트가 skipped 인데
    기본 모드는 이를 통과로 계산합니다. 병합 판정에는 --strict 를 씁니다.
    """
    repo, base, branch = _init_git_repo(tmp_path)

    code, output = run_level1_gate(base=base, branch=branch, repo=repo, as_json=True)
    data = json.loads(output)
    assert code == 0
    assert data["verdict"] == "pass"
    assert data["summary"]["skipped"] >= 1

    strict_code, strict_output = run_level1_gate(
        base=base, branch=branch, repo=repo, as_json=True, strict=True
    )
    strict_data = json.loads(strict_output)
    assert strict_code == 1
    assert strict_data["verdict"] == "fail"
    assert strict_data["summary"]["failed"] == 0
    assert strict_data["summary"]["skipped"] == data["summary"]["skipped"]


def _write_passing_test(repo: Path) -> None:
    """임시 저장소에 항상 통과하는 pytest 파일을 만듭니다."""
    tests_dir = repo / "tests"
    tests_dir.mkdir(exist_ok=True)
    (tests_dir / "test_ok.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")


def _write_capsule(tmp_path: Path, write_files: list[str]) -> Path:
    """allowed_write_files 만 지정한 최소 Capsule 을 만듭니다."""
    lines = ["schema: ORCA_TASK_CAPSULE_V2", "allowed_write_files:"]
    lines += [f'  - "{entry}"' for entry in write_files]
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "capsule.yaml"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_gate5_is_not_required_when_review_report_absent(tmp_path: Path):
    """리뷰 보고를 넘기지 않은 호출에서 게이트 5 는 적용 대상이 아닙니다.

    finalize 는 Level 1 을 먼저 돌리고 리뷰어를 그 뒤에 돌리므로, 이 시점에
    보고서는 존재할 수 없습니다. 이를 필수 건너뜀으로 세면 --strict 가 어떤
    입력에도 fail 을 냅니다.
    """
    capsule = _write_capsule(tmp_path, ["src/a.py"])

    result = run_gate5_review_report(None, capsule)
    assert result.status == "skipped"
    assert result.required is False


def test_strict_passes_when_only_non_required_gate_is_skipped(tmp_path: Path):
    """필수 게이트가 전부 검증되면 게이트 5 건너뜀만으로 strict 가 실패하지 않습니다.

    이것이 finalize --strict 가 어떤 입력에도 exit 1 을 내던 조합 회귀의
    재발 방지 테스트입니다.
    """
    repo, base, branch = _init_git_repo(tmp_path)
    capsule = _write_capsule(tmp_path, ["docs/note.md", "common.txt", "unique_new.txt"])
    _write_passing_test(repo)

    code, output = run_level1_gate(
        base=base,
        branch=branch,
        repo=repo,
        capsule=capsule,
        tests=["tests/test_ok.py -q"],
        as_json=True,
        strict=True,
    )
    data = json.loads(output)
    assert data["gates"]["gate3_tests"]["status"] == "pass"
    assert data["gates"]["gate5_review_report"]["status"] == "skipped"
    assert data["gates"]["gate5_review_report"]["required"] is False
    assert data["summary"]["blocking_skipped"] == []
    assert data["verdict"] == "pass"
    assert code == 0


def test_strict_still_fails_when_code_capsule_runs_no_tests(tmp_path: Path):
    """코드를 고치는 Task 가 테스트 없이 strict 를 통과하면 원래의 fail-open 입니다."""
    repo, base, branch = _init_git_repo(tmp_path)
    capsule = _write_capsule(tmp_path, ["src/a.py", "common.txt", "unique_new.txt"])

    code, output = run_level1_gate(
        base=base,
        branch=branch,
        repo=repo,
        capsule=capsule,
        as_json=True,
        strict=True,
    )
    data = json.loads(output)
    assert data["gates"]["gate3_tests"]["status"] == "skipped"
    assert data["gates"]["gate3_tests"]["required"] is True
    assert "게이트 3 테스트" in data["summary"]["blocking_skipped"]
    assert data["verdict"] == "fail"
    assert code == 1


def test_requires_test_verification_exempts_only_documents():
    """코드 확장자를 나열하면 목록에 없는 형식이 조용히 면제됩니다.

    2026-08-19 까지 `.py` 만 코드로 보아 `.ts`, `.tsx`, Dockerfile 변경이
    테스트 없이 strict 를 통과했습니다. 기본은 검증 필요이고 문서만 바뀐 것이
    증명될 때만 면제합니다.
    """
    assert requires_test_verification(["src/a.py"]) is True
    assert requires_test_verification(["frontend/src/page.tsx"]) is True
    assert requires_test_verification(["frontend/src/api.ts"]) is True
    assert requires_test_verification(["frontend/Dockerfile"]) is True
    assert requires_test_verification(["config/settings.json"]) is True

    assert requires_test_verification(["docs/a.md"]) is False
    assert requires_test_verification(["README.rst", "docs/b.adoc"]) is False

    # 하나라도 문서가 아니면 필수입니다.
    assert requires_test_verification(["docs/a.md", "src/a.py"]) is True

    # 변경이 없으면 검증할 대상도 없습니다. 무작업 완료는 commit_count 검사가 막습니다.
    assert requires_test_verification([]) is False


def test_frontend_change_without_tests_fails_strict(tmp_path: Path):
    """프론트엔드 코드를 고치고 테스트를 하나도 돌리지 않으면 strict 는 통과가 아닙니다."""
    repo, base, branch = _init_git_repo(tmp_path)
    # 이 임시 저장소의 실제 변경 파일은 .txt 이므로 문서 면제 대상이 아닙니다.
    capsule = _write_capsule(tmp_path, ["common.txt", "unique_new.txt"])

    code, output = run_level1_gate(
        base=base, branch=branch, repo=repo, capsule=capsule, as_json=True, strict=True
    )
    data = json.loads(output)
    assert data["gates"]["gate3_tests"]["required"] is True
    assert "게이트 3 테스트" in data["summary"]["blocking_skipped"]
    assert code == 1


def test_gate5_requires_capsule_when_review_report_given(tmp_path: Path):
    """보고서를 명시했는데 Capsule 이 없으면 N/A 가 아니라 호출 오류입니다.

    N/A 로 처리하면 리뷰를 요구한 호출이 조용히 검증 없이 통과합니다.
    """
    from scripts.orca_level1_gate import GateToolError

    report = tmp_path / "review.json"
    report.write_text(json.dumps({"verdict": "pass"}), encoding="utf-8")

    with pytest.raises(GateToolError, match="capsule"):
        run_gate5_review_report(report, None)

    # 보고서를 아예 안 준 호출은 종전대로 적용 대상이 아닙니다.
    assert run_gate5_review_report(None, None).required is False


# ---------------------------------------------------------------------------
# 검증 명령 일반화와 rename 판정 (2026-08-19)
# ---------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> None:
    subprocess.run(  # noqa: S603
        [GIT_BIN, *args], cwd=str(repo), check=True, capture_output=True
    )


def test_rename_to_document_suffix_does_not_exempt_verification(tmp_path: Path):
    """코드 파일을 문서 확장자로 옮긴 변경이 문서 전용 면제를 받으면 안 됩니다.

    --name-only 는 rename 의 새 경로만 알려 주므로 `a.py` -> `docs.md` 가
    문서 변경으로 보였습니다. 원본 경로까지 판정에 넣습니다.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    (repo / "a.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    _git(repo, "add", "a.py")
    _git(repo, "commit", "-m", "base")
    _git(repo, "checkout", "-b", "feature")
    _git(repo, "mv", "a.py", "docs.md")
    _git(repo, "commit", "-m", "rename")

    changed, _unique, renames = get_git_changed_files(repo, "main", "feature")
    assert changed == ["docs.md"]
    assert renames == ["a.py"]

    # 새 경로만 보면 면제되지만, 원본을 함께 보면 backend 검증이 필요합니다.
    assert requires_test_verification(changed) is False
    assert required_capabilities(changed + renames) == {"backend_pytest"}

    g1 = run_gate1_changed_files(repo, "main", "feature")
    assert g1.raw_data["rename_sources"] == ["a.py"]


def test_required_capabilities_separates_change_kinds():
    """영역 하나로 묶으면 그 영역의 아무 명령이나 하나로 덮인 것이 됩니다."""
    assert required_capabilities(["src/a.py"]) == {"backend_pytest"}
    assert required_capabilities(["frontend/src/App.tsx"]) == {"frontend_test", "frontend_build"}
    assert required_capabilities(["frontend/README.md"]) == set()

    # infra 변경을 backend pytest 가 덮으면 안 됩니다.
    assert required_capabilities(["Dockerfile"]) == {"docker_build:."}
    # 빌드 컨텍스트를 정하는 파일이라 잘못 고치면 pytest 는 통과하고 빌드만 깨집니다.
    assert required_capabilities([".dockerignore"]) == {"docker_build:."}

    # 컨텍스트가 다르면 다른 능력입니다. 루트 .dockerignore 가 frontend/ 를
    # 제외하므로 `docker build .` 은 frontend/Dockerfile 을 읽지도 않습니다.
    assert required_capabilities(["frontend/Dockerfile"]) == {"docker_build:frontend"}
    assert required_capabilities(["frontend/.dockerignore"]) == {"docker_build:frontend"}
    assert required_capabilities(["frontend/Dockerfile"]) == {"docker_build:frontend"}
    assert required_capabilities(["docker-compose.yml"]) == {"compose_config"}
    assert required_capabilities(["docker-compose.restore.yml"]) == {"compose_config"}

    # 워크플로우는 pytest 가 검증하지 않습니다. actionlint 가 덮습니다.
    assert required_capabilities([".github/workflows/ci.yml"]) == {"workflow_lint"}
    assert required_capabilities([".github/workflows/x.yaml"]) == {"workflow_lint"}
    # .github 아래라도 워크플로우가 아니면 해당 없음입니다.
    assert required_capabilities([".github/dependabot.yml"]) == {"backend_pytest"}

    assert required_capabilities(["src/a.py", "frontend/src/App.tsx"]) == {
        "backend_pytest",
        "frontend_test",
        "frontend_build",
    }


def test_parse_verification_command_allows_only_known_runners():
    """Capsule 문자열을 셸에 넘기면 임의 명령 실행 통로가 됩니다."""
    pytest_cmd = parse_verification_command("uv run pytest tests/test_x.py -q")
    assert pytest_cmd.argv == ["uv", "run", "pytest", "tests/test_x.py", "-q"]
    assert pytest_cmd.provides == frozenset({"backend_pytest"})

    npm_cmd = parse_verification_command("npm --prefix frontend run build")
    assert npm_cmd.argv == ["npm", "run", "build"]
    assert npm_cmd.cwd == "frontend"
    assert npm_cmd.provides == frozenset({"frontend_build"})

    assert parse_verification_command("uv run actionlint").provides == frozenset({"workflow_lint"})

    docker_cmd = parse_verification_command("docker build -t x .")
    assert docker_cmd.provides == frozenset({"docker_build:."})
    assert parse_verification_command("docker build -t y ./frontend").provides == frozenset(
        {"docker_build:frontend"}
    )
    # 마지막 토큰을 그냥 쓰면 태그를 컨텍스트로 읽습니다.
    assert parse_verification_command(
        "docker build --build-arg A=1 -t y ./frontend"
    ).provides == frozenset({"docker_build:frontend"})
    assert parse_verification_command("docker compose config -q").provides == frozenset(
        {"compose_config"}
    )

    # 게이트 4 가 이미 수행하므로 실행하지 않고 인식만 합니다.
    assert parse_verification_command("python3 scripts/validate_agent_rules.py --quiet").argv == []

    for rejected in (
        "rm -rf /",
        "bash -c 'curl example.com'",
        "npm run build && rm -rf .",
        "npm install",
        "npm --prefix ../../etc run build",
        "docker run --rm alpine sh",
        "docker compose up -d",
        "docker build -t x",
        "docker build -t x . extra",
        "docker build -t x ../outside",
    ):
        with pytest.raises(ValueError):
            parse_verification_command(rejected)


def test_gate3_blocks_frontend_change_verified_only_by_backend_pytest():
    """무관한 backend pytest 통과로 frontend 변경이 게이트를 넘으면 안 됩니다."""
    with patch("scripts.orca_level1_gate.run_command_safe") as mock_cmd:
        mock_cmd.return_value = (0, "3 passed in 0.10s", "", False)
        g = run_gate3_tests(
            [],
            Path("."),
            commands=["uv run pytest tests/ -q"],
            capabilities={"backend_pytest", "frontend_test"},
        )

    assert g.status == "skipped"
    assert g.required is True
    assert g.raw_data["uncovered_capabilities"] == ["frontend_test"]


def test_gate3_passes_when_every_required_domain_is_covered(tmp_path: Path):
    (tmp_path / "frontend").mkdir()
    with patch("scripts.orca_level1_gate.run_command_safe") as mock_cmd:
        mock_cmd.return_value = (0, "ok", "", False)
        g = run_gate3_tests(
            [],
            tmp_path,
            commands=["uv run pytest tests/ -q", "npm --prefix frontend run test"],
            capabilities={"backend_pytest", "frontend_test"},
        )

    assert g.status == "pass"
    assert g.raw_data["uncovered_capabilities"] == []
    assert len(g.raw_data["results"]) == 2


def test_gate3_rejects_unknown_verification_command():
    """인식하지 못한 명령을 조용히 버리면 검증한 적 없는 Task 가 통과합니다."""
    g = run_gate3_tests([], Path("."), commands=["make lint"], capabilities={"backend_pytest"})
    assert g.status == "fail"
    assert g.raw_data["invalid_commands"]


def test_frontend_lint_alone_does_not_cover_test_and_build():
    """영역이 아니라 능력으로 봐야 lint 하나가 test 와 build 를 대신하지 못합니다."""
    assert parse_verification_command("npm --prefix frontend run lint").provides == frozenset()

    with patch("scripts.orca_level1_gate.run_command_safe") as mock_cmd:
        mock_cmd.return_value = (0, "lint ok", "", False)
        g = run_gate3_tests(
            [],
            Path("."),
            commands=["npm --prefix frontend run lint"],
            capabilities={"frontend_test", "frontend_build"},
        )

    assert g.status == "skipped"
    assert g.required is True
    assert g.raw_data["uncovered_capabilities"] == ["frontend_build", "frontend_test"]


def test_dockerfile_change_is_not_covered_by_backend_pytest():
    """infra 변경을 무관한 backend pytest 통과로 넘기면 안 됩니다."""
    with patch("scripts.orca_level1_gate.run_command_safe") as mock_cmd:
        mock_cmd.return_value = (0, "5 passed in 1s", "", False)
        g = run_gate3_tests(
            [],
            Path("."),
            commands=["uv run pytest tests/ -q"],
            capabilities=required_capabilities(["Dockerfile"]),
        )

    assert g.status == "skipped"
    assert g.raw_data["uncovered_capabilities"] == ["docker_build:."]


def test_workflow_change_is_not_covered_by_backend_pytest():
    """워크플로우 변경을 pytest 통과로 넘기면 안 됩니다."""
    with patch("scripts.orca_level1_gate.run_command_safe") as mock_cmd:
        mock_cmd.return_value = (0, "5 passed in 1s", "", False)
        g = run_gate3_tests(
            [],
            Path("."),
            commands=["uv run pytest tests/ -q"],
            capabilities=required_capabilities([".github/workflows/ci.yml"]),
        )

    assert g.status == "skipped"
    assert g.raw_data["uncovered_capabilities"] == ["workflow_lint"]


def test_root_docker_build_does_not_cover_frontend_dockerfile():
    """루트 .dockerignore 가 frontend/ 를 제외하므로 루트 빌드는 그 파일을 읽지 않습니다."""
    with patch("scripts.orca_level1_gate.run_command_safe") as mock_cmd:
        mock_cmd.return_value = (0, "Successfully built", "", False)
        g = run_gate3_tests(
            [],
            Path("."),
            commands=["docker build -t refac-bid-box-root:orca-gate ."],
            capabilities=required_capabilities(["frontend/Dockerfile"]),
        )

    assert g.status == "skipped"
    assert g.raw_data["uncovered_capabilities"] == ["docker_build:frontend"]

    with patch("scripts.orca_level1_gate.run_command_safe") as mock_cmd:
        mock_cmd.return_value = (0, "Successfully built", "", False)
        g_ok = run_gate3_tests(
            [],
            Path("."),
            commands=["docker build -t refac-bid-box-frontend:orca-gate frontend"],
            capabilities=required_capabilities(["frontend/Dockerfile"]),
        )

    assert g_ok.status == "pass"


# ---------------------------------------------------------------------------
# 건수 불일치 게이트 실패 전파 회귀 테스트
# ---------------------------------------------------------------------------


def test_count_mismatch_propagates_to_gate6_failure(tmp_path: Path):
    """건수 불일치가 gate6 (worker_done 보고) 실패로 전파됩니다.

    verify_verification_truth 가 건수 불일치를 violations 로 반환하면
    summarize_worker_report 가 이를 violations 에 포함시키고
    gate6 가 fail 로 판정합니다. 이 경로의 회귀를 고정합니다.
    """
    # 실제 43 passed 인데 보고서가 500 passed 라고 기재한 경우
    actual_output = "43 passed in 1.0s"
    verification = [
        {
            "command": "uv run pytest tests/ -q",
            "result": "500 passed in 9.9s",
        }
    ]

    with patch("scripts.orca_contract.subprocess.run") as mock_run:

        class _Proc:
            returncode = 0
            stdout = actual_output
            stderr = ""

        mock_run.return_value = _Proc()
        ok, violations, details = verify_verification_truth(str(tmp_path), verification)

    # Level 1 게이트 기준: violations 가 있으면 fail
    assert not ok, "건수 불일치가 있으면 verify_verification_truth 는 False 여야 합니다"
    assert len(violations) >= 1
    assert any("건수 불일치" in v or "passed" in v.lower() for v in violations)
    assert details[0]["status"] == "fail"
    assert details[0]["count_match"] is False

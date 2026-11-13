"""cmd 토큰 A/B 하니스 시험. subprocess 를 대역으로 바꿔 cmd 와 git 을 부르지 않습니다."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import token_ab_cmd as harness


class FakeResult:
    def __init__(self, stdout: str = "", returncode: int = 0, stderr: str = "") -> None:
        self.stdout = stdout
        self.returncode = returncode
        self.stderr = stderr


class FakeRunner:
    """호출을 기록하고 준비된 응답을 돌려주는 subprocess.run 대역."""

    def __init__(self, responses: dict[str, FakeResult] | None = None) -> None:
        self.calls: list[list[str]] = []
        self.responses = responses or {}

    def __call__(self, args, **kwargs):
        self.calls.append(list(args))
        key = args[0]
        return self.responses.get(key, FakeResult())

    def subcommands(self) -> list[list[str]]:
        return self.calls


def test_condition_extra_args_for_four_conditions():
    ponytail = ".claude/skills/ponytail"
    assert harness.condition_extra_args("baseline", ponytail) == []
    assert harness.condition_extra_args("no_skills", ponytail) == ["--no-skills"]
    assert harness.condition_extra_args("ponytail", ponytail) == ["--skill", ponytail]
    assert harness.condition_extra_args("ponytail_no_skills", ponytail) == [
        "--no-skills",
        "--skill",
        ponytail,
    ]

    baseline = harness.build_cmd_args(
        "do it", model="m", effort=None, max_turns=5, condition="baseline", ponytail_dir=None
    )
    ponytail_args = harness.build_cmd_args(
        "do it",
        model="m",
        effort="high",
        max_turns=5,
        condition="ponytail",
        ponytail_dir=ponytail,
    )
    assert baseline[:3] == ["cmd", "-p", "do it"]
    assert "--no-skills" not in baseline
    assert "--effort" not in baseline
    assert ponytail_args[-3:] == ["--skill", ponytail, "--no-session"]
    for arg in ("--output-format", "json", "--max-turns", "5", "--trust", "--yolo"):
        assert arg in baseline
    assert baseline[-1] == "--no-session"
    assert Path(ponytail).as_posix() in ponytail_args


def test_condition_args_require_ponytail_dir():
    with pytest.raises(ValueError):
        harness.parse_conditions("ponytail", None)


def test_parse_result_usage_reads_last_result_line():
    lines = [
        {"type": "assistant", "text": "working"},
        {
            "type": "result",
            "usage": {
                "inputTokens": 10,
                "outputTokens": 20,
                "cacheReadTokens": 30,
                "cacheWriteTokens": 40,
            },
            "durationMs": 1234,
            "stopReason": "end_turn",
        },
    ]
    text = "\n".join(json.dumps(line) for line in lines)
    usage = harness.parse_result_usage(text)
    assert usage is not None
    assert usage["total_tokens"] == 100
    assert usage["input_tokens"] == 10
    assert usage["cache_write_tokens"] == 40
    assert usage["duration_ms"] == 1234
    assert usage["stop_reason"] == "end_turn"


def test_parse_result_usage_returns_none_without_result_line():
    assert harness.parse_result_usage('{"type": "assistant"}') is None
    assert harness.parse_result_usage("") is None


def test_sum_added_lines_sums_numstat():
    numstat = "12\t3\tsrc/a.py\n7\t0\tsrc/b.py\n-\t-\tdata/blob.bin\n"
    assert harness.sum_added_lines(numstat) == 19


def test_parse_pytest_summary():
    assert harness.parse_pytest_summary("===== 7 passed, 2 failed in 1.2s =====") == (7, 2)
    assert harness.parse_pytest_summary("3 passed in 0.1s") == (3, 0)
    assert harness.parse_pytest_summary("no tests ran") == (0, 0)


def test_permutation_is_reproducible_with_seed():
    diffs = [120.0, -30.0, 45.0, 80.0, -10.0, 60.0]
    first = harness.paired_permutation_pvalue(diffs, seed=42, n_perm=500)
    second = harness.paired_permutation_pvalue(diffs, seed=42, n_perm=500)
    other = harness.paired_permutation_pvalue(diffs, seed=7, n_perm=500)
    assert first == second
    assert 0.0 < first <= 1.0
    assert first != other


def test_summarize_pairs_by_task_and_rep():
    records = [
        {
            "condition": "baseline",
            "task": "a",
            "rep": 1,
            "valid": True,
            "input_tokens": 1,
            "output_tokens": 1,
            "cache_read_tokens": 0,
            "cache_write_tokens": 0,
            "total_tokens": 100,
            "duration_ms": 1,
            "added_lines": 10,
            "tests_passed": 1,
            "tests_failed": 0,
        },
        {
            "condition": "ponytail",
            "task": "a",
            "rep": 1,
            "valid": True,
            "input_tokens": 1,
            "output_tokens": 1,
            "cache_read_tokens": 0,
            "cache_write_tokens": 0,
            "total_tokens": 40,
            "duration_ms": 1,
            "added_lines": 4,
            "tests_passed": 1,
            "tests_failed": 0,
        },
        {
            "condition": "ponytail",
            "task": "a",
            "rep": 2,
            "valid": True,
            "input_tokens": 1,
            "output_tokens": 1,
            "cache_read_tokens": 0,
            "cache_write_tokens": 0,
            "total_tokens": 999,
            "duration_ms": 1,
            "added_lines": 999,
            "tests_passed": 0,
            "tests_failed": 1,
        },
    ]
    summary = harness.summarize(records, conditions=["baseline", "ponytail"], seed=42, n_perm=100)
    comparison = summary["comparisons"]["ponytail"]
    assert comparison["total_tokens"]["pairs"] == 1
    assert comparison["total_tokens"]["mean_diff"] == -60
    assert comparison["added_lines"]["pairs"] == 1
    assert comparison["added_lines"]["mean_diff"] == -6
    assert summary["conditions"]["ponytail"]["mean_total_tokens"] == (40 + 999) / 2


def test_run_once_parses_usage_and_cleans_worktree(tmp_path: Path):
    ndjson = "\n".join(
        [
            json.dumps({"type": "assistant"}),
            json.dumps(
                {
                    "type": "result",
                    "usage": {
                        "inputTokens": 5,
                        "outputTokens": 6,
                        "cacheReadTokens": 7,
                        "cacheWriteTokens": 8,
                    },
                    "durationMs": 99,
                    "stopReason": "end_turn",
                }
            ),
        ]
    )

    class Routed(FakeRunner):
        def __call__(self, args, **kwargs):
            self.calls.append(list(args))
            if args[0] == "git":
                if "--git-dir" in args:
                    return FakeResult(stdout="/repo/.git/worktrees/00-a-baseline-r1")
                if "--git-common-dir" in args:
                    return FakeResult(stdout="/repo/.git")
                if "rev-parse" in args:
                    return FakeResult(stdout="/repo/.git")
                if "--numstat" in args:
                    return FakeResult(stdout="4\t0\tsrc/a.py\n")
                if "show" in args:
                    return FakeResult(stdout="def test_hidden():\n    assert True\n")
                return FakeResult()
            if args[0] == "cmd":
                return FakeResult(stdout=ndjson)
            if args[0] == "uv":
                return FakeResult(stdout="===== 2 passed in 0.1s =====")
            return FakeResult()

    routed = Routed()
    spec = {
        "run_id": "00-a-baseline-r1",
        "condition": "baseline",
        "rep": 1,
        "task": {
            "name": "a",
            "base_commit": "abc123",
            "prompt": "do it",
            "hidden_tests": [{"path": "tests/test_hidden.py", "source_commit": "def456"}],
            "test_command": "uv run pytest tests/test_hidden.py -q",
        },
    }
    record = harness.run_once(
        spec,
        out_dir=tmp_path,
        model="m",
        effort=None,
        max_turns=5,
        ponytail_dir=None,
        runner=routed,
    )
    assert record["valid"] is True
    assert record["total_tokens"] == 26
    assert record["added_lines"] == 4
    assert record["tests_passed"] == 2
    assert (tmp_path / "runs" / "00-a-baseline-r1.ndjson").exists()
    assert any("worktree" in call and "remove" in call for call in routed.calls)


def test_run_once_marks_invalid_when_result_missing(tmp_path: Path):
    class Routed(FakeRunner):
        def __call__(self, args, **kwargs):
            if args[0] == "git":
                self.calls.append(list(args))
                if "--git-dir" in args:
                    return FakeResult(stdout="/repo/.git/worktrees/00-a-baseline-r1")
                if "--git-common-dir" in args:
                    return FakeResult(stdout="/repo/.git")
                return FakeResult()
            return super().__call__(args, **kwargs)

    routed = Routed({"cmd": FakeResult(stdout='{"type": "assistant"}\n')})
    spec = {
        "run_id": "00-a-baseline-r1",
        "condition": "baseline",
        "rep": 1,
        "task": {
            "name": "a",
            "base_commit": "abc",
            "prompt": "p",
            "hidden_tests": [],
            "test_command": "uv run pytest",
        },
    }
    record = harness.run_once(
        spec,
        out_dir=tmp_path,
        model="m",
        effort=None,
        max_turns=5,
        ponytail_dir=None,
        runner=routed,
    )
    assert record["valid"] is False
    assert record["total_tokens"] == 0


def test_run_once_skips_cmd_when_policy_not_placed(tmp_path: Path, monkeypatch):
    class Routed(FakeRunner):
        def __call__(self, args, **kwargs):
            self.calls.append(list(args))
            if args[0] == "git":
                return FakeResult()
            return super().__call__(args, **kwargs)

    routed = Routed()
    monkeypatch.setattr(harness, "deploy_worker_settings", lambda *a, **k: None)
    spec = {
        "run_id": "00-a-baseline-r1",
        "condition": "baseline",
        "rep": 1,
        "task": {
            "name": "a",
            "base_commit": "abc",
            "prompt": "p",
            "hidden_tests": [],
            "test_command": "uv run pytest",
        },
    }
    record = harness.run_once(
        spec,
        out_dir=tmp_path,
        model="m",
        effort=None,
        max_turns=5,
        ponytail_dir=None,
        runner=routed,
    )
    assert record["valid"] is False
    assert not any(call[0] == "cmd" for call in routed.calls)
    assert any("worktree" in call and "remove" in call for call in routed.calls)


def test_dry_run_does_not_call_subprocess(tmp_path: Path, monkeypatch, capsys):
    calls: list[list[str]] = []

    def forbidden(args, **kwargs):
        calls.append(list(args))
        raise AssertionError("dry-run 에서 subprocess 를 불렀습니다")

    monkeypatch.setattr(harness.subprocess, "run", forbidden)
    tasks_path = tmp_path / "tasks.json"
    tasks_path.write_text(
        json.dumps(
            [
                {
                    "name": "a",
                    "base_commit": "abc",
                    "prompt": "p",
                    "hidden_tests": [],
                    "test_command": "uv run pytest",
                }
            ]
        ),
        encoding="utf-8",
    )
    out_dir = tmp_path / "out"
    exit_code = harness.main(
        [
            "--tasks",
            str(tasks_path),
            "--conditions",
            "baseline,no_skills",
            "--reps",
            "2",
            "--out-dir",
            str(out_dir),
            "--dry-run",
        ]
    )
    assert exit_code == 0
    assert calls == []
    printed = capsys.readouterr().out
    assert "runs: 4" in printed
    assert "run_id=00-a-baseline-r1" in printed
    assert not out_dir.exists()

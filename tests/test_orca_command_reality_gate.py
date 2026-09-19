"""게이트 10 명령 실재성 검증 테스트.

2026-09-19 에 `docker compose up -d -e VAR=x app` 이 Level 1 게이트와 독립
리뷰를 모두 통과해 병합됐습니다. `docker compose up` 에 -e 옵션이 없어 A/B
측정 하니스가 실행되지 않는 상태였고, 이 게이트는 그 부류를 잡습니다.
"""

from __future__ import annotations

import shutil

import pytest

from scripts.orca_level1_gate import check_command_reality, run_gate10_command_reality

pytestmark = pytest.mark.skipif(
    shutil.which("docker") is None, reason="docker 실행기가 없어 도움말을 얻을 수 없습니다"
)


def _write(tmp_path, rel: str, text: str) -> str:
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return rel


def test_detects_nonexistent_flag(tmp_path):
    rel = _write(
        tmp_path,
        "docs/bad.md",
        "```bash\ndocker compose up -d --no-deps -e FOO=bar app\n```\n",
    )
    violations, _warnings, _skipped, checked = check_command_reality(tmp_path, [rel])
    assert checked == 1
    assert any("-e" in v for v in violations)


def test_accepts_valid_flags(tmp_path):
    rel = _write(
        tmp_path,
        "docs/good.md",
        "```bash\ndocker compose up -d --no-deps --force-recreate app\n```\n",
    )
    violations, _warnings, _skipped, checked = check_command_reality(tmp_path, [rel])
    assert checked == 1
    assert violations == []


def test_inline_code_backticks_do_not_create_false_flags(tmp_path):
    rel = _write(tmp_path, "docs/inline.md", "실행은 `docker compose config -q` 입니다.\n")
    violations, _warnings, _skipped, _checked = check_command_reality(tmp_path, [rel])
    assert violations == []


def test_flags_after_first_positional_are_not_checked(tmp_path):
    """`uv run pytest -q` 의 -q 는 pytest 옵션이므로 uv 도움말로 판정하지 않습니다."""
    rel = _write(tmp_path, "docs/uvrun.md", "```bash\nuv run pytest tests/ -q --tb=short\n```\n")
    violations, _warnings, _skipped, _checked = check_command_reality(tmp_path, [rel])
    assert violations == []


def test_missing_script_path_is_warning_not_violation(tmp_path):
    rel = _write(tmp_path, "docs/path.md", "실행: `uv run python scripts/nope.py --sql x`\n")
    violations, warnings, _skipped, _checked = check_command_reality(tmp_path, [rel])
    assert violations == []
    assert any("scripts/nope.py" in w for w in warnings)


def test_gate_fails_on_violation_and_passes_otherwise(tmp_path):
    bad = _write(tmp_path, "docs/bad.md", "```bash\ndocker compose up -e FOO=bar app\n```\n")
    result = run_gate10_command_reality(tmp_path, [bad])
    assert result.status == "fail"

    good = _write(tmp_path, "docs/good.md", "```bash\ndocker compose up -d app\n```\n")
    result = run_gate10_command_reality(tmp_path, [good])
    assert result.status == "pass"


def test_unrelated_files_are_ignored(tmp_path):
    rel = _write(tmp_path, "docs/note.txt", "docker compose up -e FOO=bar app\n")
    violations, _warnings, _skipped, checked = check_command_reality(tmp_path, [rel])
    assert checked == 0
    assert violations == []

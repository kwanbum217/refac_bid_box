"""게이트 10 명령 실재성 검증 테스트.

2026-09-19 에 `docker compose up -d -e VAR=x app` 이 Level 1 게이트와 독립
리뷰를 모두 통과해 병합됐습니다. `docker compose up` 에 -e 옵션이 없어 A/B
측정 하니스가 실행되지 않는 상태였고, 이 게이트는 그 부류를 잡습니다.
2026-09-21 에는 `uv run python scripts/<x>.py ... \\` 다음 줄의 없는 옵션이
같은 경로로 통과해, 저장소 파이썬 스크립트 호출의 옵션 검사를 더했습니다.
"""

from __future__ import annotations

import inspect
import shutil

import pytest

from scripts.orca_level1_gate import (
    check_command_reality,
    collect_script_options,
    run_gate10_command_reality,
)

# docker 도움말을 얻어야 판정할 수 있는 테스트에만 겁니다. 설정이 모듈 전역이면
# docker 가 없는 환경에서 파이썬 스크립트 검사 테스트까지 함께 건너뜁니다.
DOCKER_REQUIRED = pytest.mark.skipif(
    shutil.which("docker") is None, reason="docker 실행기가 없어 도움말을 얻을 수 없습니다"
)


def _write(tmp_path, rel: str, text: str) -> str:
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return rel


@DOCKER_REQUIRED
def test_detects_nonexistent_flag(tmp_path):
    rel = _write(
        tmp_path,
        "docs/bad.md",
        "```bash\ndocker compose up -d --no-deps -e FOO=bar app\n```\n",
    )
    violations, _warnings, _skipped, checked = check_command_reality(tmp_path, [rel])
    assert checked == 1
    assert any("-e" in v for v in violations)


@DOCKER_REQUIRED
def test_accepts_valid_flags(tmp_path):
    rel = _write(
        tmp_path,
        "docs/good.md",
        "```bash\ndocker compose up -d --no-deps --force-recreate app\n```\n",
    )
    violations, _warnings, _skipped, checked = check_command_reality(tmp_path, [rel])
    assert checked == 1
    assert violations == []


@DOCKER_REQUIRED
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


@DOCKER_REQUIRED
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


@DOCKER_REQUIRED
def test_ignore_marker_exempts_intentional_counterexample(tmp_path):
    """문서가 일부러 적는 반례는 표시로 검사에서 뺍니다."""
    rel = _write(
        tmp_path,
        "docs/counter.md",
        "<!-- command-reality-ignore -->\n`docker compose up -e FOO=bar app` 은 틀린 형태입니다.\n",
    )
    violations, _warnings, _skipped, _checked = check_command_reality(tmp_path, [rel])
    assert violations == []


script_head = "import argparse\n\n\ndef build():\n    parser = argparse.ArgumentParser()\n"


def _script(*option_lines: str) -> str:
    """argparse 옵션을 선언하는 가짜 스크립트 본문을 만듭니다."""
    body = "".join(f"    {line}\n" for line in option_lines)
    return script_head + body + "    return parser\n"


def test_line_continuation_missing_option_is_violation_on_start_line(tmp_path):
    """A.5 형태의 줄 이음 다음 줄 옵션을 시작 줄 번호와 함께 위반으로 잡습니다."""
    _write(
        tmp_path,
        "scripts/bench.py",
        _script(
            'parser.add_argument("--rounds", type=int)',
            'parser.add_argument("--output", default=None)',
        ),
    )
    rel = _write(
        tmp_path,
        "docs/repro.md",
        "```bash\nuv run python scripts/bench.py --rounds 3 \\\n"
        "    --json data/loop_lag.json\n```\n",
    )
    violations, warnings, _skipped, checked = check_command_reality(tmp_path, [rel])
    assert checked == 1
    assert violations == ["docs/repro.md:2 `scripts/bench.py` 에 없는 옵션: --json"]
    assert warnings == []


def test_line_continuation_declared_option_passes(tmp_path):
    """같은 명령이 선언된 옵션만 쓰면 통과합니다."""
    _write(
        tmp_path,
        "scripts/bench.py",
        _script(
            'parser.add_argument("--rounds", type=int)',
            'parser.add_argument("--output", default=None)',
        ),
    )
    rel = _write(
        tmp_path,
        "docs/repro.md",
        "```bash\nuv run python scripts/bench.py --rounds 3 \\\n"
        "    --output data/loop_lag.json\n```\n",
    )
    violations, warnings, _skipped, checked = check_command_reality(tmp_path, [rel])
    assert checked == 1
    assert violations == []
    assert warnings == []


def test_gate10_reports_python_script_counts(tmp_path):
    """게이트 10 raw_data 가 파이썬 스크립트 검사 수와 건너뜀 수를 남깁니다."""
    _write(tmp_path, "scripts/bench.py", _script('parser.add_argument("--rounds", type=int)'))
    rel = _write(tmp_path, "docs/repro.md", "uv run python scripts/bench.py --json x.json\n")
    result = run_gate10_command_reality(tmp_path, [rel])
    assert result.status == "fail"
    assert result.raw_data["python_script_checked"] == 1
    assert result.raw_data["python_script_skipped"] == 0


def test_python3_and_env_assignment_forms_are_checked(tmp_path):
    """python3 형태와 환경변수 대입 앞붙임 형태도 같은 검사를 받습니다."""
    _write(tmp_path, "scripts/bench.py", _script('parser.add_argument("--rounds", type=int)'))
    rel = _write(
        tmp_path,
        "docs/forms.md",
        "MYSQL_HOST=127.0.0.1 python3 scripts/bench.py --nope\npython scripts/bench.py --nope\n",
    )
    violations, _warnings, _skipped, checked = check_command_reality(tmp_path, [rel])
    assert checked == 2
    assert violations == [
        "docs/forms.md:1 `scripts/bench.py` 에 없는 옵션: --nope",
        "docs/forms.md:2 `scripts/bench.py` 에 없는 옵션: --nope",
    ]


def test_unique_prefix_abbreviation_passes_with_warning(tmp_path):
    """argparse 가 허용하는 고유 접두사 축약은 통과시키고 경고만 남깁니다."""
    _write(tmp_path, "scripts/bench.py", _script('parser.add_argument("--output", default=None)'))
    rel = _write(tmp_path, "docs/abbrev.md", "uv run python scripts/bench.py --out data/x.json\n")
    violations, warnings, _skipped, checked = check_command_reality(tmp_path, [rel])
    assert checked == 1
    assert violations == []
    assert len(warnings) == 1
    assert "--out" in warnings[0]


def test_ambiguous_prefix_is_violation(tmp_path):
    """접두사가 둘 이상을 가리키면 argparse 도 거부하므로 위반입니다."""
    _write(
        tmp_path,
        "scripts/bench.py",
        _script(
            'parser.add_argument("--output", default=None)',
            'parser.add_argument("--out-dir", default=None)',
        ),
    )
    rel = _write(tmp_path, "docs/ambig.md", "uv run python scripts/bench.py --out data/x.json\n")
    violations, _warnings, _skipped, _checked = check_command_reality(tmp_path, [rel])
    assert violations == ["docs/ambig.md:1 `scripts/bench.py` 에 없는 옵션: --out"]


def test_undecidable_option_sources_are_skipped_not_violations(tmp_path):
    """없는 스크립트, 구문 오류, add_subparsers, 비상수 이름은 건너뜁니다."""
    _write(
        tmp_path,
        "scripts/subparsers.py",
        "import argparse\n\n\ndef build():\n"
        "    parser = argparse.ArgumentParser()\n"
        '    parser.add_subparsers(dest="cmd")\n'
        "    return parser\n",
    )
    _write(
        tmp_path,
        "scripts/dynamic.py",
        'import argparse\n\n\nFLAG = "--rounds"\n\n\ndef build():\n'
        "    parser = argparse.ArgumentParser()\n"
        "    parser.add_argument(FLAG)\n"
        "    return parser\n",
    )
    _write(tmp_path, "scripts/broken.py", "import argparse\n\n\ndef build(:\n    return None\n")
    rel = _write(
        tmp_path,
        "docs/skip.md",
        "uv run python scripts/missing.py --json x\n"
        "uv run python scripts/subparsers.py --json x\n"
        "uv run python scripts/dynamic.py --json x\n"
        "uv run python scripts/broken.py --json x\n",
    )
    stats: dict[str, int] = {}
    violations, _warnings, _skipped, checked = check_command_reality(
        tmp_path, [rel], python_stats=stats
    )
    assert violations == []
    assert checked == 0
    assert stats["python_checked"] == 0
    assert stats["python_skipped"] == 4


def test_ignore_marker_skips_whole_joined_command(tmp_path):
    """표시가 명령 시작 줄 앞에 있으면 합쳐진 명령 전체를 건너뜁니다."""
    _write(
        tmp_path,
        "scripts/bench.py",
        _script(
            'parser.add_argument("--rounds", type=int)',
            'parser.add_argument("--output", default=None)',
        ),
    )
    before = _write(
        tmp_path,
        "docs/ignored_before.md",
        "<!-- command-reality-ignore -->\n"
        "uv run python scripts/bench.py --rounds 3 \\\n"
        "    --json data/x.json\n",
    )
    inline = _write(
        tmp_path,
        "docs/ignored_inline.md",
        "uv run python scripts/bench.py --json x.json  <!-- command-reality-ignore -->\n",
    )
    violations, _warnings, _skipped, checked = check_command_reality(tmp_path, [before, inline])
    assert violations == []
    assert checked == 0


def test_pipeline_tokens_after_separator_are_not_checked(tmp_path):
    """파이프 뒤 토큰은 다음 프로그램의 것이므로 이 스크립트 옵션으로 세지 않습니다."""
    _write(tmp_path, "scripts/bench.py", _script('parser.add_argument("--rounds", type=int)'))
    rel = _write(
        tmp_path,
        "docs/pipe.md",
        "python3 scripts/bench.py --rounds 3 | tail -25\n"
        "python3 scripts/bench.py --nope | tail -25\n",
    )
    violations, _warnings, _skipped, checked = check_command_reality(tmp_path, [rel])
    assert checked == 2
    assert violations == ["docs/pipe.md:2 `scripts/bench.py` 에 없는 옵션: --nope"]


def test_command_substitution_tokens_are_not_checked(tmp_path):
    """`$(...)` 안쪽 명령의 플래그는 이 스크립트 옵션으로 세지 않습니다."""
    _write(tmp_path, "scripts/bench.py", _script('parser.add_argument("--output", default=None)'))
    rel = _write(
        tmp_path,
        "docs/subst.md",
        "uv run python scripts/bench.py --output $(git rev-parse --short HEAD)/out.json\n"
        "uv run python scripts/bench.py --json $(date +%Y%m%d).json\n",
    )
    violations, _warnings, _skipped, checked = check_command_reality(tmp_path, [rel])
    assert checked == 2
    assert violations == ["docs/subst.md:2 `scripts/bench.py` 에 없는 옵션: --json"]


def test_inline_code_backtick_does_not_hide_the_last_option(tmp_path):
    """인라인 코드를 닫는 백틱은 명령 치환 시작이 아니라 장식입니다."""
    _write(tmp_path, "scripts/bench.py", _script('parser.add_argument("--rounds", type=int)'))
    rel = _write(
        tmp_path,
        "docs/inline_cmd.md",
        "`python3 scripts/bench.py --nope` 는 틀린 명령입니다.\n",
    )
    violations, _warnings, _skipped, checked = check_command_reality(tmp_path, [rel])
    assert checked == 1
    assert violations == ["docs/inline_cmd.md:1 `scripts/bench.py` 에 없는 옵션: --nope"]


def test_trailing_punctuation_is_not_an_option(tmp_path):
    """`--quiet:` 처럼 끝에 문장 부호가 붙은 토큰은 옵션이 아닙니다."""
    _write(tmp_path, "scripts/bench.py", _script('parser.add_argument("--quiet", type=int)'))
    rel = _write(tmp_path, "docs/punct.md", "python3 scripts/bench.py --quiet: 19/19 통과\n")
    violations, _warnings, _skipped, _checked = check_command_reality(tmp_path, [rel])
    assert violations == []


def test_arrow_token_is_not_an_option(tmp_path):
    """`->` 같은 기호 토큰은 옵션이 아닙니다."""
    _write(tmp_path, "scripts/bench.py", _script('parser.add_argument("--rounds", type=int)'))
    rel = _write(tmp_path, "docs/arrow.md", "python3 scripts/bench.py --rounds 3 -> 20/20 통과\n")
    violations, _warnings, _skipped, _checked = check_command_reality(tmp_path, [rel])
    assert violations == []


def test_option_collection_never_executes_the_script(tmp_path):
    """대상 스크립트를 실행하거나 import 하지 않고 ast 만 읽습니다."""
    _write(
        tmp_path,
        "scripts/side_effect.py",
        "import pathlib\n"
        "pathlib.Path(__file__).with_name('executed.flag').write_text('x', encoding='utf-8')\n"
        "raise RuntimeError('대상 스크립트가 실행됐습니다')\n",
    )
    rel = _write(tmp_path, "docs/side.md", "uv run python scripts/side_effect.py --json x\n")
    violations, _warnings, _skipped, _checked = check_command_reality(tmp_path, [rel])
    assert violations == []
    assert not (tmp_path / "scripts" / "executed.flag").exists()
    assert collect_script_options(tmp_path / "scripts" / "side_effect.py")[1] == "add_argument 없음"
    source = inspect.getsource(collect_script_options)
    assert all(token not in source for token in ("subprocess", "importlib", "runpy", "exec("))

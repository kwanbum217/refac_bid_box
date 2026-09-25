from __future__ import annotations

import json
import types
from pathlib import Path

import pytest

from scripts.orca_contract import parse_capsule_list
from scripts.orca_level1_gate import (
    CAP_BACKEND_MYPY,
    CAP_BACKEND_PYTEST,
    parse_verification_command,
    required_capabilities,
    run_gate2_scope,
)
from scripts.orca_taskctl import main

OBJECTIVE = "코디네이터 직접 작성 브랜치용 최소 Capsule 을 만든다"


def _run(
    tmp_path: Path,
    scope: list[str],
    slug: str = "demo",
    out: Path | None = None,
) -> tuple[int, Path]:
    """coordinator-capsule 을 실행하고 (종료 코드, 출력 경로) 를 돌려줍니다."""
    out_path = out if out is not None else tmp_path / "capsule.yaml"
    argv = ["coordinator-capsule", "--slug", slug, "--objective", OBJECTIVE]
    for item in scope:
        argv += ["--scope", item]
    argv += ["--out", str(out_path), "--json"]
    return main(argv), out_path


def test_allowed_write_files_equal_scope(tmp_path: Path, capsys: pytest.CaptureFixture):
    """(a) 생성 Capsule 의 allowed_write_files 가 --scope 와 정확히 같다."""
    scope = ["scripts/orca_taskctl.py", "tests/test_orca_taskctl_coordinator_capsule.py"]
    code, out_path = _run(tmp_path, scope)
    assert code == 0

    capsule_text = out_path.read_text(encoding="utf-8")
    assert parse_capsule_list(capsule_text, "allowed_write_files") == scope

    payload = json.loads(capsys.readouterr().out)
    assert payload["capsule_path"] == str(out_path)
    assert payload["task_id"] == "coord_demo"
    assert payload["allowed_write_files"] == scope
    assert payload["verification_commands"] == parse_capsule_list(
        capsule_text, "verification_commands"
    )


def test_gate2_scope_pass_and_fail(tmp_path: Path):
    """(b) 같은 Capsule 로 게이트 2 가 범위 안은 pass, 범위 밖은 fail."""
    scope = ["scripts/orca_taskctl.py"]
    code, out_path = _run(tmp_path, scope)
    assert code == 0

    inside = run_gate2_scope(["scripts/orca_taskctl.py"], out_path)
    assert inside.status == "pass"

    outside = run_gate2_scope(["scripts/orca_taskctl.py", "src/ml/features.py"], out_path)
    assert outside.status == "fail"


def test_verification_covers_src_capabilities(tmp_path: Path):
    """(c) src/ 아래 .py 를 scope 로 주면 게이트 3 능력을 덮는 명령이 붙는다."""
    scope = ["src/ml/demo_feature.py"]
    code, out_path = _run(tmp_path, scope)
    assert code == 0

    commands = parse_capsule_list(out_path.read_text(encoding="utf-8"), "verification_commands")
    covered: set[str] = set()
    for command in commands:
        covered |= set(parse_verification_command(command).provides)

    required = required_capabilities(scope)
    assert {CAP_BACKEND_PYTEST, CAP_BACKEND_MYPY} <= required
    assert required <= covered


def test_invalid_slug_rejected(tmp_path: Path):
    """(d) 영문 소문자·숫자·하이픈이 아닌 slug 는 종료 코드 2."""
    code, out_path = _run(tmp_path, ["scripts/orca_taskctl.py"], slug="Bad_Slug")
    assert code == 2
    assert not out_path.exists()


def test_absolute_scope_rejected(tmp_path: Path):
    """(d) 절대 경로 scope 는 종료 코드 2."""
    code, out_path = _run(tmp_path, ["/etc/passwd"])
    assert code == 2
    assert not out_path.exists()


def test_parent_traversal_scope_rejected(tmp_path: Path):
    """(d) 상위 디렉터리 탐색(..) scope 는 종료 코드 2."""
    code, out_path = _run(tmp_path, ["../outside.py"])
    assert code == 2
    assert not out_path.exists()


def test_existing_out_file_rejected(tmp_path: Path):
    """(d) --out 파일이 이미 있으면 덮어쓰지 않고 종료 코드 2."""
    out_path = tmp_path / "capsule.yaml"
    out_path.write_text("기존 내용", encoding="utf-8")

    code, _ = _run(tmp_path, ["scripts/orca_taskctl.py"], out=out_path)
    assert code == 2
    assert out_path.read_text(encoding="utf-8") == "기존 내용"


def test_does_not_invoke_orca_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """(e) coordinator-capsule 은 orca CLI 나 외부 프로세스를 호출하지 않는다."""
    calls: list[tuple[object, ...]] = []

    def _blocked(*args: object, **kwargs: object) -> None:
        calls.append(args)
        raise AssertionError("orca CLI 또는 외부 프로세스를 호출하면 안 됩니다")

    fake_subprocess = types.SimpleNamespace(run=_blocked, Popen=_blocked)
    monkeypatch.setattr("scripts.orca_taskctl.subprocess", fake_subprocess)

    code, out_path = _run(tmp_path, ["scripts/orca_taskctl.py"])
    assert code == 0
    assert calls == []
    assert out_path.exists()

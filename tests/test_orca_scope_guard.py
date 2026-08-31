from __future__ import annotations

import json
from pathlib import Path

from scripts.orca_scope_guard import check_scope, main


def test_scope_guard_no_capsule_allows_normal_dev(tmp_path: Path):
    """Capsule 설정이 없는 일반 개발 커밋은 통과해야 합니다."""
    code = check_scope(repo=tmp_path)
    assert code == 0


def test_scope_guard_capsule_missing_fails_closed(tmp_path: Path, monkeypatch):
    """Capsule 경로가 설정되었으나 파일이 없으면 fail-closed 로 거부해야 합니다."""
    monkeypatch.setattr(
        "scripts.orca_scope_guard.get_git_config_capsule",
        lambda repo: str(tmp_path / "nonexistent_capsule.yaml"),
    )
    code = check_scope(repo=tmp_path)
    assert code == 1


def test_scope_guard_capsule_unparseable_fails_closed(tmp_path: Path, monkeypatch):
    """Capsule 파일이 손상되어 파싱할 수 없으면 fail-closed 로 거부해야 합니다."""
    bad_cap = tmp_path / "bad_capsule.yaml"
    bad_cap.write_text("invalid:\n  - [unclosed", encoding="utf-8")
    monkeypatch.setattr(
        "scripts.orca_scope_guard.get_git_config_capsule",
        lambda repo: str(bad_cap),
    )
    code = check_scope(repo=tmp_path)
    assert code == 1


def test_scope_guard_readonly_task_rejects_staged_files(tmp_path: Path, monkeypatch):
    """allowed_write_files 가 비어 있는 읽기 전용 Task 는 staged 파일이 있으면 거부해야 합니다."""
    cap = tmp_path / "readonly_capsule.yaml"
    cap.write_text(
        "schema: ORCA_TASK_CAPSULE_V2\n"
        'version: "2.1.0"\n'
        "allowed_read_files:\n"
        '  - "src/..."\n'
        "allowed_write_files:\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "scripts.orca_scope_guard.get_git_config_capsule",
        lambda repo: str(cap),
    )
    monkeypatch.setattr(
        "scripts.orca_scope_guard.get_staged_files",
        lambda repo: ["src/app.py"],
    )

    code = check_scope(repo=tmp_path)
    assert code == 1


def test_scope_guard_out_of_scope_staged_files_rejected(tmp_path: Path, monkeypatch):
    """allowed_write_files 범위를 벗어난 staged 파일은 거부되어야 합니다."""
    cap = tmp_path / "capsule.yaml"
    cap.write_text(
        "schema: ORCA_TASK_CAPSULE_V2\n"
        'version: "2.1.0"\n'
        "allowed_read_files:\n"
        '  - "src/..."\n'
        "allowed_write_files:\n"
        '  - "src/app.py"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "scripts.orca_scope_guard.get_git_config_capsule",
        lambda repo: str(cap),
    )
    monkeypatch.setattr(
        "scripts.orca_scope_guard.get_staged_files",
        lambda repo: ["src/app.py", "scripts/leak.py"],
    )

    code = check_scope(repo=tmp_path)
    assert code == 1


def test_scope_guard_in_scope_staged_files_allowed(tmp_path: Path, monkeypatch):
    """allowed_write_files 범위 내의 staged 파일은 통과해야 합니다."""
    cap = tmp_path / "capsule.yaml"
    cap.write_text(
        "schema: ORCA_TASK_CAPSULE_V2\n"
        'version: "2.1.0"\n'
        "allowed_read_files:\n"
        '  - "src/..."\n'
        "allowed_write_files:\n"
        '  - "src/app.py"\n'
        '  - "tests/..."\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "scripts.orca_scope_guard.get_git_config_capsule",
        lambda repo: str(cap),
    )
    monkeypatch.setattr(
        "scripts.orca_scope_guard.get_staged_files",
        lambda repo: ["src/app.py", "tests/test_app.py"],
    )

    code = check_scope(repo=tmp_path)
    assert code == 0


def test_scope_guard_json_output(tmp_path: Path, monkeypatch, capsys):
    """--json 플래그 시 구조화된 JSON 과 origin 필드를 출력해야 합니다."""
    cap = tmp_path / "capsule.yaml"
    cap.write_text(
        'schema: ORCA_TASK_CAPSULE_V2\nversion: "2.1.0"\nallowed_write_files:\n  - "src/app.py"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "scripts.orca_scope_guard.get_staged_files",
        lambda repo: ["forbidden.txt"],
    )

    code = main(["--capsule", str(cap), "--repo", str(tmp_path), "--json"])
    assert code == 1
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["ok"] is False
    assert payload["origin"] == "worker_scope_violation"
    assert "forbidden.txt" in payload["violations"]

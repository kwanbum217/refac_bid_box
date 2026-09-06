from __future__ import annotations

import json
from pathlib import Path

from scripts.orca_worker_done_guard import (
    FROM_HANDLE_ENV_VAR,
    main,
    resolve_sender_identity,
    validate_worker_done,
)


def create_sample_capsule(
    path: Path,
    task_id: str = "task_sample",
    allowed_write: list[str] | None = None,
) -> None:
    if allowed_write is None:
        allowed_write = ["src/app.py"]
    write_lines = "\n".join(f'  - "{w}"' for w in allowed_write)
    content = (
        "schema: ORCA_TASK_CAPSULE_V2\n"
        'version: "2.1.0"\n'
        f'task_id: "{task_id}"\n'
        'role: "builder"\n'
        "allowed_read_files:\n"
        '  - "src/..."\n'
        f"allowed_write_files:\n{write_lines}\n"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def create_sample_report(
    path: Path,
    task_id: str = "task_sample",
    status: str = "succeeded",
    commit: str = "abc1234",
    commit_count: int = 1,
    changed_files: list[str] | None = None,
) -> None:
    if changed_files is None:
        changed_files = ["src/app.py"]
    payload = {
        "schema": "ORCA_WORKER_DONE_V2",
        "version": "2.1.0",
        "task_id": task_id,
        "status": status,
        "branch": "feat-branch",
        "commit": commit,
        "commit_count": commit_count,
        "changed_files": changed_files,
        "read_files": ["src/app.py"],
        "verification": [{"command": "pytest", "result": "1 passed"}],
        "verdict": "candidate",
        "blocking_issues": [],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def test_worker_done_guard_capsule_missing(tmp_path: Path):
    """Capsule 이 없으면 실패해야 합니다."""
    report = tmp_path / "worker_done.json"
    create_sample_report(report)
    ok, _violations, details = validate_worker_done(
        capsule_path=tmp_path / "nonexistent.yaml",
        report_path=report,
        repo=tmp_path,
    )
    assert not ok
    assert details["origin"] == "capsule_spec_error"


def test_worker_done_guard_report_missing(tmp_path: Path):
    """Report 가 없으면 실패해야 합니다."""
    cap = tmp_path / "capsule.yaml"
    create_sample_capsule(cap)
    ok, _violations, details = validate_worker_done(
        capsule_path=cap,
        report_path=tmp_path / "nonexistent.json",
        repo=tmp_path,
    )
    assert not ok
    assert details["origin"] == "worker_scope_violation"


def test_worker_done_guard_task_id_mismatch(tmp_path: Path):
    """Capsule 과 Report 의 task_id 가 다르면 거부해야 합니다."""
    cap = tmp_path / "capsule.yaml"
    report = tmp_path / "worker_done.json"
    create_sample_capsule(cap, task_id="task_A")
    create_sample_report(report, task_id="task_B")

    ok, violations, details = validate_worker_done(
        capsule_path=cap,
        report_path=report,
        repo=tmp_path,
    )
    assert not ok
    assert any("task_id 불일치" in v for v in violations)
    assert details["origin"] == "capsule_spec_error"


def test_worker_done_guard_zero_commit_on_write_task(tmp_path: Path):
    """쓰기 작업인데 commit_count 가 0 이면 거부해야 합니다."""
    cap = tmp_path / "capsule.yaml"
    report = tmp_path / "worker_done.json"
    create_sample_capsule(cap, allowed_write=["src/app.py"])
    create_sample_report(report, commit_count=0)

    ok, violations, _details = validate_worker_done(
        capsule_path=cap,
        report_path=report,
        repo=tmp_path,
    )
    assert not ok
    assert any("commit_count 가 0" in v for v in violations)


def test_worker_done_guard_out_of_scope_changed_files(tmp_path: Path, monkeypatch):
    """changed_files 가 allowed_write_files 범위를 벗어나면 거부해야 합니다."""
    cap = tmp_path / "capsule.yaml"
    report = tmp_path / "worker_done.json"
    create_sample_capsule(cap, allowed_write=["src/app.py"])
    create_sample_report(report, changed_files=["src/app.py", "scripts/unauthorized.py"])

    monkeypatch.setattr(
        "scripts.orca_worker_done_guard.verify_commit_exists",
        lambda repo, sha: (True, "OK"),
    )
    monkeypatch.setattr(
        "scripts.orca_worker_done_guard.verify_changed_files_match",
        lambda repo, base, branch, files: (True, "OK"),
    )

    ok, violations, details = validate_worker_done(
        capsule_path=cap,
        report_path=report,
        repo=tmp_path,
    )
    assert not ok
    assert any("허용된 쓰기 범위를 벗어난" in v for v in violations)
    assert details["origin"] == "worker_scope_violation"


def test_worker_done_guard_diff_mismatch(tmp_path: Path, monkeypatch):
    """changed_files 가 실제 git diff 와 다르면 거부해야 합니다."""
    cap = tmp_path / "capsule.yaml"
    report = tmp_path / "worker_done.json"
    create_sample_capsule(cap, allowed_write=["src/app.py"])
    create_sample_report(report, changed_files=["src/app.py"])

    monkeypatch.setattr(
        "scripts.orca_worker_done_guard.verify_commit_exists",
        lambda repo, sha: (True, "OK"),
    )
    monkeypatch.setattr(
        "scripts.orca_worker_done_guard.verify_changed_files_match",
        lambda repo, base, branch, files: (False, "changed_files 불일치"),
    )

    ok, violations, _details = validate_worker_done(
        capsule_path=cap,
        report_path=report,
        repo=tmp_path,
    )
    assert not ok
    assert any("git diff 와 changed_files 불일치" in v for v in violations)


def test_worker_done_guard_valid_pass(tmp_path: Path, monkeypatch):
    """모든 조건 충족 시 정상 통과해야 합니다."""
    cap = tmp_path / "capsule.yaml"
    report = tmp_path / "worker_done.json"
    create_sample_capsule(cap, allowed_write=["src/app.py"])
    create_sample_report(report, changed_files=["src/app.py"])

    monkeypatch.setattr(
        "scripts.orca_worker_done_guard.verify_commit_exists",
        lambda repo, sha: (True, "OK"),
    )
    monkeypatch.setattr(
        "scripts.orca_worker_done_guard.verify_changed_files_match",
        lambda repo, base, branch, files: (True, "OK"),
    )

    ok, violations, _details = validate_worker_done(
        capsule_path=cap,
        report_path=report,
        repo=tmp_path,
    )
    assert ok
    assert len(violations) == 0


def test_worker_done_guard_main_send(tmp_path: Path, monkeypatch, capsys):
    """--send 옵션 실행 시 orca orchestration send 가 호출되어야 합니다."""
    cap = tmp_path / "capsule.yaml"
    report = tmp_path / "worker_done.json"
    create_sample_capsule(cap, allowed_write=["src/app.py"])
    create_sample_report(report, changed_files=["src/app.py"])

    monkeypatch.setattr(
        "scripts.orca_worker_done_guard.verify_commit_exists",
        lambda repo, sha: (True, "OK"),
    )
    monkeypatch.setattr(
        "scripts.orca_worker_done_guard.verify_changed_files_match",
        lambda repo, base, branch, files: (True, "OK"),
    )
    captured_send: list[dict] = []
    monkeypatch.setattr(
        "scripts.orca_worker_done_guard.execute_orca_send",
        lambda **kwargs: (captured_send.append(kwargs), (0, "ok", ""))[1],
    )

    code = main(
        [
            "--capsule",
            str(cap),
            "--report",
            str(report),
            "--repo",
            str(tmp_path),
            "--send",
            "--from",
            "term_123",
            "--dispatch-id",
            "ctx_456",
            "--json",
        ]
    )
    assert code == 0
    assert len(captured_send) == 1
    assert captured_send[0]["from_handle"] == "term_123"
    assert captured_send[0]["dispatch_id"] == "ctx_456"


def _stub_valid_repo(monkeypatch) -> None:
    monkeypatch.setattr(
        "scripts.orca_worker_done_guard.verify_commit_exists",
        lambda repo, sha: (True, "OK"),
    )
    monkeypatch.setattr(
        "scripts.orca_worker_done_guard.verify_changed_files_match",
        lambda repo, base, branch, files: (True, "OK"),
    )


def _stub_send(monkeypatch, captured_send: list[dict]):
    monkeypatch.setattr(
        "scripts.orca_worker_done_guard.execute_orca_send",
        lambda **kwargs: (captured_send.append(kwargs), (0, "ok", ""))[1],
    )


def _valid_pair(tmp_path: Path):
    cap = tmp_path / "capsule.yaml"
    report = tmp_path / "worker_done.json"
    create_sample_capsule(cap, allowed_write=["src/app.py"])
    create_sample_report(report, changed_files=["src/app.py"])
    return cap, report


def test_worker_done_guard_from_resolved_from_env(tmp_path: Path, monkeypatch, capsys):
    """--from 미지정 시 ORCA_TERMINAL_HANDLE 에서 해소합니다."""
    cap, report = _valid_pair(tmp_path)
    _stub_valid_repo(monkeypatch)
    captured_send: list[dict] = []
    _stub_send(monkeypatch, captured_send)
    monkeypatch.setenv(FROM_HANDLE_ENV_VAR, "term_env_1")

    code = main(
        [
            "--capsule",
            str(cap),
            "--report",
            str(report),
            "--repo",
            str(tmp_path),
            "--send",
            "--dispatch-id",
            "ctx_456",
        ]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert len(captured_send) == 1
    assert captured_send[0]["from_handle"] == "term_env_1"
    assert FROM_HANDLE_ENV_VAR in out


def test_worker_done_guard_identity_fail_closed(tmp_path: Path, monkeypatch, capsys):
    """신원 해소 실패 시 전송을 시도하지 않고 오류로 종료합니다."""
    cap, report = _valid_pair(tmp_path)
    _stub_valid_repo(monkeypatch)
    captured_send: list[dict] = []
    _stub_send(monkeypatch, captured_send)
    monkeypatch.delenv(FROM_HANDLE_ENV_VAR, raising=False)

    code = main(
        [
            "--capsule",
            str(cap),
            "--report",
            str(report),
            "--repo",
            str(tmp_path),
            "--send",
            "--dispatch-id",
            "ctx_456",
        ]
    )
    err = capsys.readouterr().err
    assert code != 0
    assert len(captured_send) == 0
    assert "ORCA_TERMINAL_HANDLE" in err


def test_worker_done_guard_explicit_from_wins_over_env(tmp_path: Path, monkeypatch, capsys):
    """명시 지정값이 환경변수보다 우선합니다."""
    cap, report = _valid_pair(tmp_path)
    _stub_valid_repo(monkeypatch)
    captured_send: list[dict] = []
    _stub_send(monkeypatch, captured_send)
    monkeypatch.setenv(FROM_HANDLE_ENV_VAR, "term_env_1")

    code = main(
        [
            "--capsule",
            str(cap),
            "--report",
            str(report),
            "--repo",
            str(tmp_path),
            "--send",
            "--from",
            "term_explicit",
            "--dispatch-id",
            "ctx_456",
        ]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert captured_send[0]["from_handle"] == "term_explicit"
    assert FROM_HANDLE_ENV_VAR not in out


def test_worker_done_guard_dispatch_id_required_without_env_basis(
    tmp_path: Path, monkeypatch, capsys
):
    """dispatch-id 는 근거 있는 환경변수가 없으므로 인자 필수입니다."""
    resolved_from, _, _ = resolve_sender_identity(
        from_handle="term_explicit",
        dispatch_id="ctx_456",
        env={},
    )
    assert resolved_from == "term_explicit"

    cap, report = _valid_pair(tmp_path)
    _stub_valid_repo(monkeypatch)
    captured_send: list[dict] = []
    _stub_send(monkeypatch, captured_send)
    monkeypatch.setenv(FROM_HANDLE_ENV_VAR, "term_env_1")

    code = main(
        [
            "--capsule",
            str(cap),
            "--report",
            str(report),
            "--repo",
            str(tmp_path),
            "--send",
        ]
    )
    err = capsys.readouterr().err
    assert code != 0
    assert len(captured_send) == 0
    assert "--dispatch-id" in err

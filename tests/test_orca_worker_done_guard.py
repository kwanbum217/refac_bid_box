from __future__ import annotations

import json
from pathlib import Path

from scripts.orca_taskctl import (
    extract_dispatch_capability as taskctl_extract_capability,
)
from scripts.orca_taskctl import (
    record_dispatch_capability as taskctl_record_capability,
)
from scripts.orca_worker_done_guard import (
    FROM_HANDLE_ENV_VAR,
    dispatch_capability_file,
    execute_orca_send,
    main,
    mask_dispatch_capability,
    resolve_dispatch_capability,
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
            "--dispatch-capability",
            "dcap_explicit001",
            "--json",
        ]
    )
    assert code == 0
    assert len(captured_send) == 1
    assert captured_send[0]["from_handle"] == "term_123"
    assert captured_send[0]["dispatch_id"] == "ctx_456"
    assert captured_send[0]["dispatch_capability"] == "dcap_explicit001"


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
            "--dispatch-capability",
            "dcap_explicit002",
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
            "--dispatch-capability",
            "dcap_explicit003",
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


def test_worker_done_guard_send_forwards_dispatch_capability(monkeypatch):
    """--dispatch-capability 는 orca send 명령에 그대로 전달됩니다."""

    class _Proc:
        returncode = 0
        stdout = "ok"
        stderr = ""

    captured_cmd: list[list[str]] = []

    def _fake_run(cmd, **kwargs):
        captured_cmd.append(list(cmd))
        return _Proc()

    monkeypatch.setattr("scripts.orca_worker_done_guard.subprocess.run", _fake_run)

    code, _out, _err = execute_orca_send(
        task_id="task_sample",
        from_handle="term_123",
        dispatch_id="ctx_456",
        dispatch_capability="dcap_test",
    )
    assert code == 0
    assert "--dispatch-capability" in captured_cmd[0]
    assert captured_cmd[0][captured_cmd[0].index("--dispatch-capability") + 1] == "dcap_test"


def _write_capability_file(repo: Path, task_id: str, token: str) -> Path:
    cap_file = dispatch_capability_file(repo, task_id)
    cap_file.parent.mkdir(parents=True, exist_ok=True)
    cap_file.write_text(token + "\n", encoding="utf-8")
    return cap_file


def _send_args(cap: Path, report: Path, repo: Path) -> list[str]:
    return [
        "--capsule",
        str(cap),
        "--report",
        str(report),
        "--repo",
        str(repo),
        "--send",
        "--from",
        "term_123",
        "--dispatch-id",
        "ctx_456",
    ]


def test_worker_done_guard_capability_auto_resolved_from_file(tmp_path: Path, monkeypatch, capsys):
    """기록 파일이 있으면 --dispatch-capability 미지정 시 자동 해소됩니다."""
    cap, report = _valid_pair(tmp_path)
    _stub_valid_repo(monkeypatch)
    captured_send: list[dict] = []
    _stub_send(monkeypatch, captured_send)
    _write_capability_file(tmp_path, "task_sample", "dcap_fileToken001")

    code = main(_send_args(cap, report, tmp_path))
    assert code == 0
    assert len(captured_send) == 1
    assert captured_send[0]["dispatch_capability"] == "dcap_fileToken001"


def test_worker_done_guard_capability_fail_closed(tmp_path: Path, monkeypatch, capsys):
    """토큰을 구하지 못하면 전송하지 않고 실패합니다."""
    cap, report = _valid_pair(tmp_path)
    _stub_valid_repo(monkeypatch)
    captured_send: list[dict] = []
    _stub_send(monkeypatch, captured_send)

    code = main(_send_args(cap, report, tmp_path))
    err = capsys.readouterr().err
    assert code != 0
    assert len(captured_send) == 0
    assert "--dispatch-capability" in err


def test_worker_done_guard_explicit_capability_wins_over_file(tmp_path: Path, monkeypatch, capsys):
    """명시 인자가 기록 파일보다 우선합니다."""
    cap, report = _valid_pair(tmp_path)
    _stub_valid_repo(monkeypatch)
    captured_send: list[dict] = []
    _stub_send(monkeypatch, captured_send)
    _write_capability_file(tmp_path, "task_sample", "dcap_fileToken002")

    code = main([*_send_args(cap, report, tmp_path), "--dispatch-capability", "dcap_explicit999"])
    assert code == 0
    assert len(captured_send) == 1
    assert captured_send[0]["dispatch_capability"] == "dcap_explicit999"


def test_worker_done_guard_capability_not_logged(tmp_path: Path, monkeypatch, capsys):
    """토큰 전체가 표준출력이나 오류에 노출되지 않습니다."""
    cap, report = _valid_pair(tmp_path)
    _stub_valid_repo(monkeypatch)
    captured_send: list[dict] = []
    _stub_send(monkeypatch, captured_send)
    cap_value = "dcap_superSecretToken007"
    _write_capability_file(tmp_path, "task_sample", cap_value)
    assert mask_dispatch_capability(cap_value) != cap_value

    code = main([*_send_args(cap, report, tmp_path), "--json"])
    captured = capsys.readouterr()
    assert code == 0
    assert cap_value not in captured.out
    assert cap_value not in captured.err

    resolved, provenance = resolve_dispatch_capability(
        explicit=None, task_id="task_sample", repo=tmp_path
    )
    assert resolved == cap_value
    assert cap_value not in " ".join(provenance)


def test_dispatch_capability_extracted_from_preamble_text():
    """preamble 텍스트에서 dcap_ 토큰을 추출하고 없으면 None 입니다."""
    text = "worker_done 전송 시 --dispatch-capability dcap_abc123XYZ 를 붙이십시오."
    assert taskctl_extract_capability(text) == "dcap_abc123XYZ"
    assert taskctl_extract_capability("토큰이 없는 지시문") is None
    assert taskctl_extract_capability(None) is None


def test_dispatch_capability_recorded_per_task_under_orca(tmp_path: Path, capsys):
    """dispatch 시점에 워크트리 .orca 아래 task 별 파일로 기록되며 전체 토큰을 로그에 남기지 않습니다."""
    worktree = tmp_path / "wt"
    worktree.mkdir()
    cap_value = "dcap_recordMe001"
    dest = taskctl_record_capability(
        worktree, "task_sample", f"preamble ... {cap_value} ... 끝", None
    )
    assert dest is not None
    assert dest.read_text(encoding="utf-8").strip() == cap_value
    assert dest.relative_to(worktree).as_posix().startswith(".orca/")
    err = capsys.readouterr().err
    assert cap_value not in err

    assert taskctl_record_capability(worktree, "task_sample", "토큰 없음") is None

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts import orca_skill_receipt, orca_taskctl
from scripts.orca_skill_receipt import (
    RESOLUTION_COMMAND,
    get_canonical_skill_content,
    get_coordinator_handle,
    get_orca_app_version,
    issue_skill_receipt,
    verify_skill_receipt,
)


@pytest.fixture
def mock_orca_success(monkeypatch):
    """orca CLI 명령어 호출을 안전하게 모킹하여 실제 런타임 없이 성공 응답을 반환합니다."""
    monkeypatch.delenv("ORCA_TERMINAL_HANDLE", raising=False)
    monkeypatch.delenv("COORDINATOR_HANDLE", raising=False)
    monkeypatch.delenv("ORCA_HANDLE", raising=False)

    canonical_text = "# Mock Orchestration Skill\nCanonical instructions."
    canonical_sha = hashlib.sha256(canonical_text.encode("utf-8")).hexdigest()
    app_ver = "1.4.195"
    coord_handle = "term_mock_coordinator"

    def fake_run_cmd(cmd: list[str], timeout: int = 15) -> tuple[int, str, str]:
        cmd_str = " ".join(cmd)
        if "skills get orchestration" in cmd_str:
            return 0, canonical_text, ""
        if "status --json" in cmd_str:
            return 0, json.dumps({"result": {"runtime": {"appVersion": app_ver}}}), ""
        if "run-current --json" in cmd_str:
            return 0, json.dumps({"result": {"run": {"coordinator_handle": coord_handle}}}), ""
        if "task-create" in cmd_str:
            return 0, json.dumps({"result": {"task": {"id": "task_mock_created"}}}), ""
        return 0, "{}", ""

    monkeypatch.setattr(orca_skill_receipt, "_run_cmd", fake_run_cmd)
    return {
        "text": canonical_text,
        "sha256": canonical_sha,
        "app_version": app_ver,
        "coordinator_handle": coord_handle,
    }


def test_get_canonical_skill_content_success(mock_orca_success):
    content, digest = get_canonical_skill_content()
    assert content == mock_orca_success["text"]
    assert digest == mock_orca_success["sha256"]


def test_get_canonical_skill_content_failure(monkeypatch):
    def fake_fail(cmd, timeout=15):
        return 1, "", "skill not found"

    monkeypatch.setattr(orca_skill_receipt, "_run_cmd", fake_fail)
    with pytest.raises(RuntimeError, match="정본 스킬 조회 실패"):
        get_canonical_skill_content()


def test_get_orca_app_version_success(mock_orca_success):
    ver = get_orca_app_version()
    assert ver == mock_orca_success["app_version"]


def test_get_orca_app_version_corrupt_json(monkeypatch):
    monkeypatch.setattr(
        orca_skill_receipt, "_run_cmd", lambda cmd, timeout=15: (0, "{bad json", "")
    )
    with pytest.raises(RuntimeError, match="Orca status JSON 파싱 실패"):
        get_orca_app_version()


def test_get_coordinator_handle_from_env(monkeypatch):
    monkeypatch.setenv("ORCA_TERMINAL_HANDLE", "term_env_handle")
    assert get_coordinator_handle() == "term_env_handle"


def test_get_coordinator_handle_from_run(monkeypatch, mock_orca_success):
    monkeypatch.delenv("ORCA_TERMINAL_HANDLE", raising=False)
    monkeypatch.delenv("COORDINATOR_HANDLE", raising=False)
    monkeypatch.delenv("ORCA_HANDLE", raising=False)
    assert get_coordinator_handle() == mock_orca_success["coordinator_handle"]


def test_issue_skill_receipt_success(tmp_path: Path, mock_orca_success):
    receipt_file = tmp_path / "skill_receipt.json"
    res = issue_skill_receipt(receipt_path=receipt_file)
    assert res["ok"] is True
    assert receipt_file.exists()

    data = json.loads(receipt_file.read_text(encoding="utf-8"))
    assert data["schema"] == "ORCA_SKILL_RECEIPT_V1"
    assert data["canonical_command"] == "orca skills get orchestration"
    assert data["sha256"] == mock_orca_success["sha256"]
    assert data["app_version"] == mock_orca_success["app_version"]
    assert data["coordinator_handle"] == mock_orca_success["coordinator_handle"]
    assert "issued_at" in data
    assert "issued_at_iso" in data


def test_issue_skill_receipt_failure(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(orca_skill_receipt, "_run_cmd", lambda cmd, timeout=15: (-1, "", "timeout"))
    receipt_file = tmp_path / "skill_receipt.json"
    res = issue_skill_receipt(receipt_path=receipt_file)
    assert res["ok"] is False
    assert res["error"] == "receipt_issue_failed"
    assert res["fix_command"] == RESOLUTION_COMMAND
    assert not receipt_file.exists()


def test_verify_skill_receipt_success(tmp_path: Path, mock_orca_success):
    receipt_file = tmp_path / "skill_receipt.json"
    issue_skill_receipt(receipt_path=receipt_file)

    ver_res = verify_skill_receipt(receipt_path=receipt_file)
    assert ver_res["ok"] is True
    assert "유효" in ver_res["reason"]
    assert ver_res["coordinator_handle_check"] == "verified"


def test_verify_skill_receipt_missing_file_fails(tmp_path: Path):
    receipt_file = tmp_path / "non_existent.json"
    res = verify_skill_receipt(receipt_path=receipt_file)
    assert res["ok"] is False
    assert res["error"] == "receipt_missing"
    assert res["fix_command"] == RESOLUTION_COMMAND


def test_verify_skill_receipt_corrupt_json_fails(tmp_path: Path):
    receipt_file = tmp_path / "skill_receipt.json"
    receipt_file.write_text("{corrupt json", encoding="utf-8")
    res = verify_skill_receipt(receipt_path=receipt_file)
    assert res["ok"] is False
    assert res["error"] == "receipt_corrupt"
    assert res["fix_command"] == RESOLUTION_COMMAND


def test_verify_skill_receipt_invalid_schema_fails(tmp_path: Path):
    receipt_file = tmp_path / "skill_receipt.json"
    receipt_file.write_text(json.dumps({"schema": "WRONG_SCHEMA"}), encoding="utf-8")
    res = verify_skill_receipt(receipt_path=receipt_file)
    assert res["ok"] is False
    assert res["error"] == "receipt_invalid_schema"
    assert res["fix_command"] == RESOLUTION_COMMAND


def test_verify_skill_receipt_app_version_mismatch_fails(
    tmp_path: Path, mock_orca_success, monkeypatch
):
    receipt_file = tmp_path / "skill_receipt.json"
    issue_skill_receipt(receipt_path=receipt_file)

    # 모의 런타임 버전을 다르게 변경
    def fake_run_diff_version(cmd: list[str], timeout: int = 15) -> tuple[int, str, str]:
        cmd_str = " ".join(cmd)
        if "status --json" in cmd_str:
            return 0, json.dumps({"result": {"runtime": {"appVersion": "1.4.196"}}}), ""
        return mock_orca_success["text"], "", ""

    monkeypatch.setattr(orca_skill_receipt, "_run_cmd", fake_run_diff_version)
    res = verify_skill_receipt(receipt_path=receipt_file)
    assert res["ok"] is False
    assert res["error"] == "app_version_mismatch"
    assert res["fix_command"] == RESOLUTION_COMMAND
    assert "1.4.195" in res["reason"]
    assert "1.4.196" in res["reason"]


def test_verify_skill_receipt_sha256_mismatch_fails(tmp_path: Path, mock_orca_success, monkeypatch):
    receipt_file = tmp_path / "skill_receipt.json"
    issue_skill_receipt(receipt_path=receipt_file)

    # 모의 스킬 본문을 다르게 변경
    new_text = "# Modified Orchestration Skill\nNew contents."

    def fake_run_diff_skill(cmd: list[str], timeout: int = 15) -> tuple[int, str, str]:
        cmd_str = " ".join(cmd)
        if "skills get orchestration" in cmd_str:
            return 0, new_text, ""
        if "status --json" in cmd_str:
            return (
                0,
                json.dumps(
                    {"result": {"runtime": {"appVersion": mock_orca_success["app_version"]}}}
                ),
                "",
            )
        if "run-current --json" in cmd_str:
            return (
                0,
                json.dumps(
                    {
                        "result": {
                            "run": {"coordinator_handle": mock_orca_success["coordinator_handle"]}
                        }
                    }
                ),
                "",
            )
        return 0, "{}", ""

    monkeypatch.setattr(orca_skill_receipt, "_run_cmd", fake_run_diff_skill)
    res = verify_skill_receipt(receipt_path=receipt_file)
    assert res["ok"] is False
    assert res["error"] == "sha256_mismatch"
    assert res["fix_command"] == RESOLUTION_COMMAND


def test_verify_skill_receipt_coordinator_handle_mismatch_fails(tmp_path: Path, mock_orca_success):
    receipt_file = tmp_path / "skill_receipt.json"
    issue_skill_receipt(receipt_path=receipt_file)

    # 다른 핸들로 검증 시도
    res = verify_skill_receipt(receipt_path=receipt_file, current_handle="term_different_session")
    assert res["ok"] is False
    assert res["error"] == "coordinator_handle_mismatch"
    assert res["fix_command"] == RESOLUTION_COMMAND
    assert "재사용 거부" in res["reason"]


def test_verify_skill_receipt_coordinator_handle_unprobed_skips_cleanly(
    tmp_path: Path, mock_orca_success, monkeypatch
):
    receipt_file = tmp_path / "skill_receipt.json"
    issue_skill_receipt(receipt_path=receipt_file)

    monkeypatch.delenv("ORCA_TERMINAL_HANDLE", raising=False)
    monkeypatch.delenv("COORDINATOR_HANDLE", raising=False)
    monkeypatch.delenv("ORCA_HANDLE", raising=False)

    def fake_run_no_handle(cmd: list[str], timeout: int = 15) -> tuple[int, str, str]:
        cmd_str = " ".join(cmd)
        if "skills get orchestration" in cmd_str:
            return 0, mock_orca_success["text"], ""
        if "status --json" in cmd_str:
            return (
                0,
                json.dumps(
                    {"result": {"runtime": {"appVersion": mock_orca_success["app_version"]}}}
                ),
                "",
            )
        if "run-current --json" in cmd_str:
            return 1, "", "no active run"
        return 0, "{}", ""

    monkeypatch.setattr(orca_skill_receipt, "_run_cmd", fake_run_no_handle)
    res = verify_skill_receipt(receipt_path=receipt_file)
    assert res["ok"] is True
    assert res["coordinator_handle_check"] == "skipped_unprobed"


def test_taskctl_create_blocked_without_receipt(tmp_path: Path, monkeypatch):
    intent_file = tmp_path / "intent.yaml"
    intent_file.write_text("objective: Test\nscope:\n  - file.py\n", encoding="utf-8")

    # 영수증 검증이 실패하도록 모킹
    monkeypatch.setattr(
        orca_taskctl,
        "verify_skill_receipt",
        lambda: {
            "ok": False,
            "error": "receipt_missing",
            "reason": "영수증 없음",
            "fix_command": RESOLUTION_COMMAND,
        },
    )

    exit_code = orca_taskctl.main(
        [
            "create",
            "--intent",
            str(intent_file),
            "--capsule-dir",
            str(tmp_path / "capsules"),
            "--json",
        ]
    )
    assert exit_code == 4


def test_taskctl_create_skip_flag_bypasses(tmp_path: Path, monkeypatch):
    intent_file = tmp_path / "intent.yaml"
    intent_file.write_text("objective: Test\nscope:\n  - file.py\n", encoding="utf-8")

    # 영수증 검증 실패 모킹
    monkeypatch.setattr(
        orca_taskctl,
        "verify_skill_receipt",
        lambda: {"ok": False, "reason": "실패", "fix_command": RESOLUTION_COMMAND},
    )
    # task-create 모킹
    monkeypatch.setattr(
        orca_taskctl,
        "_run_command",
        lambda cmd, cwd=None, timeout=30: (
            0,
            json.dumps({"result": {"task": {"id": "task_123"}}}),
            "",
        ),
    )

    exit_code = orca_taskctl.main(
        [
            "create",
            "--intent",
            str(intent_file),
            "--capsule-dir",
            str(tmp_path / "capsules"),
            "--skip-skill-receipt",
            "--json",
        ]
    )
    assert exit_code == 0


def test_taskctl_dispatch_blocked_without_receipt(tmp_path: Path, monkeypatch):
    intent_file = tmp_path / "intent.yaml"
    intent_file.write_text("objective: Test\nscope:\n  - file.py\n", encoding="utf-8")

    monkeypatch.setattr(
        orca_taskctl,
        "verify_skill_receipt",
        lambda: {
            "ok": False,
            "error": "receipt_missing",
            "reason": "영수증 없음",
            "fix_command": RESOLUTION_COMMAND,
        },
    )

    exit_code = orca_taskctl.main(
        [
            "dispatch",
            "--intent",
            str(intent_file),
            "--capsule-dir",
            str(tmp_path / "capsules"),
            "--terminal",
            "term_123",
            "--json",
        ]
    )
    assert exit_code == 4


def test_taskctl_dispatch_skip_flag_bypasses(tmp_path: Path, monkeypatch):
    intent_file = tmp_path / "intent.yaml"
    intent_file.write_text("objective: Test\nscope:\n  - file.py\n", encoding="utf-8")

    monkeypatch.setattr(
        orca_taskctl,
        "verify_skill_receipt",
        lambda: {"ok": False, "reason": "실패", "fix_command": RESOLUTION_COMMAND},
    )

    exit_code = orca_taskctl.main(
        [
            "dispatch",
            "--intent",
            str(intent_file),
            "--capsule-dir",
            str(tmp_path / "capsules"),
            "--dry-run",
            "--skip-skill-receipt",
            "--json",
        ]
    )
    assert exit_code == 0


def test_subcommands_without_skill_gate(tmp_path: Path, monkeypatch):
    """expand, finalize, status 서브커맨드는 정본 스킬 영수증 검증 게이트를 타지 않아야 합니다."""
    intent_file = tmp_path / "intent.yaml"
    intent_file.write_text("objective: Test\nscope:\n  - file.py\n", encoding="utf-8")
    out_file = tmp_path / "capsule.yaml"

    # 영수증 검증이 호출되면 예외를 발생시키도록 모킹
    def explode():
        raise AssertionError("expand/finalize/status 에서 verify_skill_receipt 가 호출됨")

    monkeypatch.setattr(orca_taskctl, "verify_skill_receipt", explode)

    # expand 실행
    code_exp = orca_taskctl.main(
        [
            "expand",
            "--intent",
            str(intent_file),
            "--out",
            str(out_file),
            "--json",
        ]
    )
    assert code_exp == 0
    assert out_file.exists()


def test_session_start_hook_config():
    """.claude/settings.json 설정에 SessionStart 훅이 올바르게 구성되어 있는지 확인합니다."""
    settings_path = Path(__file__).resolve().parent.parent / ".claude" / "settings.json"
    assert settings_path.exists()

    data = json.loads(settings_path.read_text(encoding="utf-8"))
    assert "enabledPlugins" in data
    assert data["enabledPlugins"].get("code-review@claude-plugins-official") is True

    hooks = data.get("hooks", {})
    assert "SessionStart" in hooks
    session_hooks = hooks["SessionStart"]
    assert len(session_hooks) > 0

    found_command = False
    for group in session_hooks:
        hook_list = group.get("hooks", []) if isinstance(group, dict) else []
        for hook_entry in hook_list:
            cmd = hook_entry.get("command", "")
            if "scripts/orca_skill_receipt.py issue" in cmd and "|| true" in cmd:
                found_command = True
    assert found_command, (
        "SessionStart 훅에 'scripts/orca_skill_receipt.py issue || true' 명령이 포함되어야 합니다."
    )

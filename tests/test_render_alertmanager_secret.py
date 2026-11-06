"""tests/test_render_alertmanager_secret.py

Alertmanager critical·warning 비밀 파일 렌더링 테스트.

검증 항목:
1. critical·warning 두 키가 모두 있으면 두 파일이 각자의 값으로 생성됨.
2. warning 키만 비어 있으면 critical 값으로 warning 파일이 생성되고 경고가 출력됨.
3. 두 키가 모두 비어 있으면 기존과 같이 실패(False)하고 파일을 만들지 않음.
4. 두 파일의 권한이 0600 임.
5. warning 키만 있고 critical 키가 비어도 warning 파일은 생성됨.
6. 실제 docker/secrets/ 아래 파일을 만들거나 지우지 않음(임시 디렉터리만 사용).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from scripts.render_alertmanager_secret import render_alertmanager_secret

CRITICAL_URL = "https://example.invalid/slack/critical-canary"
WARNING_URL = "https://example.invalid/slack/warning-canary"


def _write_env(tmp_path: Path, name: str, critical: str, warning: str) -> Path:
    env_file = tmp_path / name
    env_file.write_text(
        f"ALERTMANAGER_SLACK_WEBHOOK_URL={critical}\n"
        f"ALERTMANAGER_SLACK_WARNING_WEBHOOK_URL={warning}\n",
        encoding="utf-8",
    )
    return env_file


def _secret_paths(tmp_path: Path) -> tuple[Path, Path]:
    secrets_dir = tmp_path / "secrets"
    return (
        secrets_dir / "alertmanager_slack_url",
        secrets_dir / "alertmanager_slack_warning_url",
    )


def test_both_keys_render_both_files(tmp_path: Path) -> None:
    env_file = _write_env(tmp_path, ".env.both", CRITICAL_URL, WARNING_URL)
    critical_path, warning_path = _secret_paths(tmp_path)

    success = render_alertmanager_secret(
        env_file_path=env_file,
        output_file_path=critical_path,
        warning_output_file_path=warning_path,
    )

    assert success, "두 키가 모두 있으면 True 를 반환해야 합니다."
    assert critical_path.read_text(encoding="utf-8").strip() == CRITICAL_URL
    assert warning_path.read_text(encoding="utf-8").strip() == WARNING_URL


def test_warning_defaults_to_critical_value(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    env_file = _write_env(tmp_path, ".env.critical_only", CRITICAL_URL, "")
    critical_path, warning_path = _secret_paths(tmp_path)

    success = render_alertmanager_secret(
        env_file_path=env_file,
        output_file_path=critical_path,
        warning_output_file_path=warning_path,
    )

    assert success, "critical 키로 warning 파일을 대체 생성했으므로 True 여야 합니다."
    assert critical_path.read_text(encoding="utf-8").strip() == CRITICAL_URL
    assert warning_path.read_text(encoding="utf-8").strip() == CRITICAL_URL

    captured = capsys.readouterr()
    assert "warning 전용 웹훅이 없어 critical 웹훅으로 대체했습니다" in captured.err
    assert CRITICAL_URL not in captured.out
    assert CRITICAL_URL not in captured.err


def test_both_keys_empty_creates_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    env_file = _write_env(tmp_path, ".env.empty", "", "")
    critical_path, warning_path = _secret_paths(tmp_path)

    success = render_alertmanager_secret(
        env_file_path=env_file,
        output_file_path=critical_path,
        warning_output_file_path=warning_path,
    )

    assert not success, "두 키가 모두 비어 있으면 False 를 반환해야 합니다."
    assert not critical_path.exists(), "critical 파일이 생성되면 안 됩니다."
    assert not warning_path.exists(), "warning 파일이 생성되면 안 됩니다."

    captured = capsys.readouterr()
    assert "비밀 파일을 생성하지 않습니다" in captured.out


def test_both_files_have_0600_permissions(tmp_path: Path) -> None:
    if os.name != "posix":
        pytest.skip("Windows 는 POSIX 권한 비트를 지원하지 않습니다.")

    env_file = _write_env(tmp_path, ".env.perm", CRITICAL_URL, WARNING_URL)
    critical_path, warning_path = _secret_paths(tmp_path)

    render_alertmanager_secret(
        env_file_path=env_file,
        output_file_path=critical_path,
        warning_output_file_path=warning_path,
    )

    critical_mode = oct(critical_path.stat().st_mode & 0o777)
    warning_mode = oct(warning_path.stat().st_mode & 0o777)
    assert critical_mode == "0o600", f"critical 파일 권한이 0600 이어야 합니다: {critical_mode}"
    assert warning_mode == "0o600", f"warning 파일 권한이 0600 이어야 합니다: {warning_mode}"


def test_warning_key_alone_still_renders_warning_file(tmp_path: Path) -> None:
    env_file = _write_env(tmp_path, ".env.warning_only", "", WARNING_URL)
    critical_path, warning_path = _secret_paths(tmp_path)

    render_alertmanager_secret(
        env_file_path=env_file,
        output_file_path=critical_path,
        warning_output_file_path=warning_path,
    )

    assert not critical_path.exists(), "critical 키가 비어 있으면 critical 파일을 만들지 않습니다."
    assert warning_path.read_text(encoding="utf-8").strip() == WARNING_URL


def test_warning_path_defaults_next_to_critical_output(tmp_path: Path) -> None:
    env_file = _write_env(tmp_path, ".env.sibling", CRITICAL_URL, WARNING_URL)
    critical_path, warning_path = _secret_paths(tmp_path)

    render_alertmanager_secret(env_file_path=env_file, output_file_path=critical_path)

    assert warning_path.read_text(encoding="utf-8").strip() == WARNING_URL

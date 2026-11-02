"""tests/test_backup_mysql_client_command.py

scripts/backup_recovery_core.mysql_client_command 의 비밀번호 전달 경로 회귀 테스트.

컨테이너 경로에서 docker exec 의 -e 인자에 비밀번호 값을 실으면 ps 로 노출된다.
변수 이름만 넘기고 값은 하위 프로세스 환경으로만 전달되는지 고정한다.
실제 .env 를 읽지 않고 가짜 비밀번호만 사용하며, docker 를 실행하지 않는다.
"""

from __future__ import annotations

import pytest

from scripts.backup_recovery_core import mysql_client_command

FAKE_PASSWORD = "fake-backup-pass"  # noqa: S105 # 시험 전용 가짜 비밀번호


def _db_config() -> dict[str, object]:
    return {
        "host": "db.local",
        "port": 3307,
        "user": "bidbox_backup",
        "password": FAKE_PASSWORD,
        "name": "procurement",
    }


def test_container_command_has_no_password_in_argv(monkeypatch: pytest.MonkeyPatch):
    """컨테이너 경로의 명령 인자 목록 어디에도 비밀번호 문자열이 남지 않아야 합니다."""
    monkeypatch.setenv("MYSQL_CLIENT_CONTAINER", "bidbox-mysql")

    cmd, _ = mysql_client_command("mysqldump", _db_config())

    assert all(FAKE_PASSWORD not in arg for arg in cmd)
    assert FAKE_PASSWORD not in " ".join(cmd)


def test_container_command_passes_env_name_only(monkeypatch: pytest.MonkeyPatch):
    """-e 다음 원소는 값이 붙지 않은 MYSQL_PWD 이고 그 뒤에 컨테이너 이름이 옵니다."""
    monkeypatch.setenv("MYSQL_CLIENT_CONTAINER", "bidbox-mysql")

    cmd, _ = mysql_client_command("mysqldump", _db_config())

    flag_index = cmd.index("-e")
    assert cmd[flag_index + 1] == "MYSQL_PWD"
    assert cmd[flag_index + 2] == "bidbox-mysql"
    assert cmd[:4] == ["docker", "exec", "-i", "-e"]
    assert cmd[4:] == [
        "MYSQL_PWD",
        "bidbox-mysql",
        "mysqldump",
        "-h",
        "127.0.0.1",
        "-P",
        "3306",
        "-u",
        "bidbox_backup",
        "--protocol=TCP",
    ]


def test_container_env_carries_password(monkeypatch: pytest.MonkeyPatch):
    """docker 클라이언트가 읽어 컨테이너로 넘길 수 있도록 env 에 MYSQL_PWD 가 있어야 합니다."""
    monkeypatch.setenv("MYSQL_CLIENT_CONTAINER", "bidbox-mysql")

    _, env = mysql_client_command("mysqldump", _db_config())

    assert env["MYSQL_PWD"] == FAKE_PASSWORD


def test_container_without_password_omits_env_flag(monkeypatch: pytest.MonkeyPatch):
    """비밀번호가 비어 있으면 -e 플래그를 붙이지 않습니다."""
    monkeypatch.setenv("MYSQL_CLIENT_CONTAINER", "bidbox-mysql")
    monkeypatch.delenv("MYSQL_PWD", raising=False)

    cmd, env = mysql_client_command("mysql", {**_db_config(), "password": ""})

    assert "-e" not in cmd
    assert "MYSQL_PWD" not in env


def test_host_path_keeps_previous_behavior(monkeypatch: pytest.MonkeyPatch):
    """컨테이너를 쓰지 않는 호스트 경로는 인자와 환경변수가 기존과 같아야 합니다."""
    monkeypatch.delenv("MYSQL_CLIENT_CONTAINER", raising=False)

    cmd, env = mysql_client_command("mysqldump", _db_config())

    assert cmd == [
        "mysqldump",
        "-h",
        "db.local",
        "-P",
        "3307",
        "-u",
        "bidbox_backup",
        "--protocol=TCP",
    ]
    assert env["MYSQL_PWD"] == FAKE_PASSWORD


def test_host_path_without_password_keeps_env_clean(monkeypatch: pytest.MonkeyPatch):
    """호스트 경로에서도 비밀번호가 비어 있으면 MYSQL_PWD 를 새로 넣지 않습니다."""
    monkeypatch.delenv("MYSQL_CLIENT_CONTAINER", raising=False)
    monkeypatch.delenv("MYSQL_PWD", raising=False)

    _, env = mysql_client_command("mysql", {**_db_config(), "password": ""})

    assert "MYSQL_PWD" not in env

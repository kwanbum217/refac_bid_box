"""tests/test_backup_db_account.py

백업 덤프 전용 최소 권한 계정 분리 사양 및 계약 검증 테스트.
- scripts/create_backup_db_user.sql 권한 무결성 및 쓰기 권한 배제
- scripts/backup_recovery_core.py 의 get_db_config 환경변수 우선 적용 및 fallback
- docker-compose.prod.yml 의 backup 서비스 전용 계정 환경변수 주입
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from scripts.backup_recovery_core import get_db_config

REPO_ROOT = Path(__file__).resolve().parents[1]
SQL_PATH = REPO_ROOT / "scripts" / "create_backup_db_user.sql"
COMPOSE_PATH = REPO_ROOT / "docker-compose.prod.yml"


def test_create_backup_db_user_sql_exists_and_grants_least_privileges():
    """계정 생성 SQL 이 존재하며 최소 권한(덤프용 읽기 + PROCESS)만 부여하는지 검증."""
    assert SQL_PATH.exists(), f"{SQL_PATH} 파일이 존재해야 합니다."
    sql_text = SQL_PATH.read_text(encoding="utf-8")

    # 1. CREATE USER 단언
    assert "CREATE USER IF NOT EXISTS" in sql_text
    assert "'bidbox_backup'@'%'" in sql_text
    assert "IDENTIFIED BY" in sql_text

    # 2. 필수 덤프 권한 단언 (SELECT, SHOW VIEW, TRIGGER, LOCK TABLES, EVENT)
    for priv in ("SELECT", "SHOW VIEW", "TRIGGER", "LOCK TABLES", "EVENT"):
        assert priv in sql_text, f"필수 덤프 권한 '{priv}' 가 SQL 에 포함되어야 합니다."

    # 3. mysqldump 8.0 호환 PROCESS 권한 단언
    assert "GRANT PROCESS ON *.*" in sql_text

    # 4. FLUSH PRIVILEGES 단언
    assert "FLUSH PRIVILEGES" in sql_text

    # 5. 쓰기 및 DDL 위험 권한 일체 배제 단언 (defect_when: yes 방어)
    forbidden_privs = (
        "INSERT",
        "UPDATE",
        "DELETE",
        "DROP",
        "ALTER",
        "CREATE TABLE",
        "ALL PRIVILEGES",
    )
    # 주석을 제외한 실제 SQL 문장에서 검사
    non_comment_lines = [
        line.strip()
        for line in sql_text.splitlines()
        if line.strip() and not line.strip().startswith("--")
    ]
    non_comment_sql = " ".join(non_comment_lines).upper()

    for priv in forbidden_privs:
        assert priv not in non_comment_sql, (
            f"위험 권한 '{priv}' 은 백업 전용 계정에 부여할 수 없습니다."
        )

    # 6. 실제 비밀번호 하드코딩 방어 (자리표시자 확인)
    assert "CHANGE_ME_BACKUP_PASSWORD" in sql_text


def test_get_db_config_prioritizes_backup_db_env(monkeypatch: pytest.MonkeyPatch):
    """BACKUP_DB_USER / BACKUP_DB_PASSWORD 환경변수가 설정되면 get_db_config 가 이를 우선 반환해야 합니다."""
    monkeypatch.setenv("BACKUP_DB_USER", "backup_custom_user")
    monkeypatch.setenv("BACKUP_DB_PASSWORD", "backup_custom_secret_pass")
    monkeypatch.setenv("DB_USER", "app_standard_user")
    monkeypatch.setenv("DB_PASSWORD", "app_standard_pass")

    cfg = get_db_config()
    assert cfg["user"] == "backup_custom_user"
    assert cfg["password"] == "backup_custom_secret_pass"  # noqa: S105


def test_get_db_config_falls_back_to_standard_db_user(monkeypatch: pytest.MonkeyPatch):
    """BACKUP_DB_USER / BACKUP_DB_PASSWORD 가 없으면 기존 DB_USER / DB_PASSWORD 로 fallback 되어야 합니다."""
    monkeypatch.delenv("BACKUP_DB_USER", raising=False)
    monkeypatch.delenv("BACKUP_DB_PASSWORD", raising=False)
    monkeypatch.setenv("DB_USER", "app_standard_user")
    monkeypatch.setenv("DB_PASSWORD", "app_standard_pass")

    cfg = get_db_config()
    assert cfg["user"] == "app_standard_user"
    assert cfg["password"] == "app_standard_pass"  # noqa: S105


def test_prod_compose_backup_service_enforces_backup_db_credentials():
    """docker-compose.prod.yml 의 backup 서비스가 BACKUP_DB_USER / BACKUP_DB_PASSWORD 를 필수로 요구해야 합니다."""
    with COMPOSE_PATH.open(encoding="utf-8") as file:
        compose = yaml.safe_load(file)

    backup = compose["services"]["backup"]
    raw_env = backup.get("environment", [])
    env_dict = (
        raw_env
        if isinstance(raw_env, dict)
        else {item.split("=", 1)[0]: item.split("=", 1)[1] for item in raw_env}
    )

    # 1. 필수 환경변수 표기 단언
    assert env_dict["BACKUP_DB_USER"] == "${BACKUP_DB_USER:?BACKUP_DB_USER must be set}"
    assert env_dict["BACKUP_DB_PASSWORD"] == "${BACKUP_DB_PASSWORD:?BACKUP_DB_PASSWORD must be set}"  # noqa: S105

    # 2. DATABASE_URL 에 백업 전용 계정 반영 단언
    db_url = env_dict["DATABASE_URL"]
    assert "${BACKUP_DB_USER:?BACKUP_DB_USER must be set}" in db_url
    assert "${BACKUP_DB_PASSWORD:?BACKUP_DB_PASSWORD must be set}" in db_url

    # 3. DB_USER / DB_PASSWORD 매핑 단언
    assert env_dict["DB_USER"] == "${BACKUP_DB_USER:?BACKUP_DB_USER must be set}"
    assert env_dict["DB_PASSWORD"] == "${BACKUP_DB_PASSWORD:?BACKUP_DB_PASSWORD must be set}"  # noqa: S105

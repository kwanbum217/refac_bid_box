"""
tests/test_orca_worker_env.py

scripts/orca_worker_env.py 의 단위 테스트.

실제 .env 값을 읽지 않고 tmp_path/monkeypatch 로 합성한 본문만 사용합니다.
값 검증은 결과 본문 안에서만 하고 실제 비밀값은 출력하지 않습니다.
"""

from __future__ import annotations

from scripts import orca_worker_env

SOURCE_ENV = (
    "\n".join(
        [
            "# 주 저장소 .env 합성본",
            "DATABASE_URL=mysql+pymysql://root:secret@127.0.0.1:3306/procurement",
            "DB_HOST=127.0.0.1",
            "DB_PORT=3306",
            "DB_USER=root",
            "DB_PASSWORD=secret",
            "DB_NAME=procurement",
            "SECRET_KEY=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "G2B_SERVICE_KEY=g2b-secret",
            "G2B_USRINFO_SERVICE_KEY=g2b-userinfo-secret",
            "GEMINI_API_KEY=gemini-secret",
            "MODEL_MANIFEST_SIGNING_KEY=manifest-secret",
            "MYSQL_ROOT_PASSWORD=mysql-root-secret",
            "GF_SECURITY_ADMIN_PASSWORD=grafana-secret",
            "ALERTMANAGER_SLACK_WEBHOOK_URL=https://hooks.example/alert",
            "MLOPS_WEBHOOK_URL=https://hooks.example/mlops",
        ]
    )
    + "\n"
)


def test_allowlist_and_forbidden_keys_are_disjoint():
    """허용 목록과 금지 키가 겹치면 안 됩니다."""
    allowed = set(orca_worker_env.ALLOWED_WORKER_ENV_KEYS)
    forbidden = set(orca_worker_env.FORBIDDEN_WORKER_ENV_KEYS)
    assert allowed.isdisjoint(forbidden)
    assert orca_worker_env.SECRET_KEY_NAME not in allowed


def test_build_minimal_env_drops_every_forbidden_key():
    """원본에 값이 있어도 금지 키는 결과에서 완전히 빠져야 합니다."""
    result = orca_worker_env.build_minimal_env(SOURCE_ENV)
    present = set(orca_worker_env.parse_env(result))
    for key in orca_worker_env.FORBIDDEN_WORKER_ENV_KEYS:
        assert key not in present
    assert "g2b-secret" not in result
    assert "gemini-secret" not in result
    assert "mysql-root-secret" not in result


def test_build_minimal_env_keeps_only_allowlisted_keys():
    """결과의 키 집합은 허용 목록 교집합에 SECRET_KEY 를 더한 것과 같아야 합니다."""
    result = orca_worker_env.build_minimal_env(SOURCE_ENV)
    present = set(orca_worker_env.parse_env(result))
    expected = set(orca_worker_env.ALLOWED_WORKER_ENV_KEYS) & set(
        orca_worker_env.parse_env(SOURCE_ENV)
    )
    assert present == expected | {orca_worker_env.SECRET_KEY_NAME}
    assert result.startswith(orca_worker_env.HEADER + "\n")


def test_build_minimal_env_regenerates_secret_key():
    """SECRET_KEY 는 원본 값을 복사하지 않고 매번 새로 만들어야 합니다."""
    first = orca_worker_env.parse_env(orca_worker_env.build_minimal_env(SOURCE_ENV))
    second = orca_worker_env.parse_env(orca_worker_env.build_minimal_env(SOURCE_ENV))
    assert (
        first[orca_worker_env.SECRET_KEY_NAME]
        != orca_worker_env.parse_env(SOURCE_ENV)["SECRET_KEY"]
    )
    assert first[orca_worker_env.SECRET_KEY_NAME] != second[orca_worker_env.SECRET_KEY_NAME]
    assert len(first[orca_worker_env.SECRET_KEY_NAME]) == 64
    int(first[orca_worker_env.SECRET_KEY_NAME], 16)


def test_build_minimal_env_accepts_explicit_secret_key():
    """주입한 SECRET_KEY 를 그대로 씁니다(결정론적 시험용)."""
    result = orca_worker_env.build_minimal_env(SOURCE_ENV, secret_key="f" * 64)
    assert f"{orca_worker_env.SECRET_KEY_NAME}={'f' * 64}" in result


def test_parse_env_handles_export_crlf_comments_and_inline_equals():
    """dotenv 문법 변형을 견고하게 읽어야 합니다."""
    text = "export DB_HOST=127.0.0.1\r\n# 주석\r\n\r\nKEY_WITH_EQUALS=a=b=c\r\nEMPTY=\r\n"
    values = orca_worker_env.parse_env(text)
    assert values["DB_HOST"] == "127.0.0.1"
    assert values["KEY_WITH_EQUALS"] == "a=b=c"
    assert values["EMPTY"] == ""


def test_forbidden_keys_in_ignores_empty_values():
    """값이 비어 있는 금지 키는 유출로 보지 않습니다."""
    assert orca_worker_env.forbidden_keys_in("GEMINI_API_KEY=\n") == []
    assert orca_worker_env.forbidden_keys_in("GEMINI_API_KEY=x\n") == ["GEMINI_API_KEY"]


def test_audit_worker_env_detects_forbidden_keys_and_copied_secret():
    """금지 키 잔존과 복사된 SECRET_KEY 를 모두 사유로 잡아야 합니다."""
    copied_secret = "b" * 64
    worker_text = f"{orca_worker_env.SECRET_KEY_NAME}={copied_secret}\nG2B_SERVICE_KEY=leak\n"
    repo_text = f"{orca_worker_env.SECRET_KEY_NAME}={copied_secret}\n"
    reasons = orca_worker_env.audit_worker_env(worker_text, repo_text)
    assert orca_worker_env.SECRET_KEY_NAME in reasons
    assert "G2B_SERVICE_KEY" in reasons


def test_audit_worker_env_accepts_fresh_minimal_env():
    """새로 만든 최소 .env 는 정리 대상이 아닙니다."""
    worker_text = orca_worker_env.build_minimal_env(SOURCE_ENV)
    assert orca_worker_env.audit_worker_env(worker_text, SOURCE_ENV) == []
    assert orca_worker_env.forbidden_keys_in(worker_text) == []

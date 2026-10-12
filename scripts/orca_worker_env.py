#!/usr/bin/env python3
"""워커 워크트리용 최소 .env 생성기.

주 저장소 .env 전체를 워커 워크트리로 복사하던 절차를 대체합니다. 외부 서비스
비밀값은 워커에게 넘기지 않고, 워커 작업에 필요하다는 근거가 확인된 키만 허용
목록으로 통과시킵니다. SECRET_KEY 는 원본 값을 복사하지 않고 워크트리마다 새로
만듭니다.

보안 규칙: .env 의 실제 값을 출력하거나 로그에 남기지 않습니다. 이 모듈은 키
이름만 다루고 값은 결과 본문 안에서만 옮깁니다.
"""

from __future__ import annotations

import secrets

SECRET_KEY_NAME = "SECRET_KEY"  # noqa: S105  # nosec B105 - 값이 아니라 키 이름 상수입니다

# 워커 .env 에 담는 최소 허용 목록입니다. 여기 없는 키는 원본에 값이 있어도
# 옮기지 않습니다. DB 접속 키만 예외로 허용하는 이유는 워커가 읽기 전용 조회
# (scripts/db_readonly_query.py)를 해야 하기 때문입니다. 같은 자격증명으로 쓰기도
# 가능한 잔여 위험은 docs/ops/orca_control_plane_tools.md 에 적습니다.
ALLOWED_WORKER_ENV_KEYS: tuple[str, ...] = (
    "DATABASE_URL",
    "DB_HOST",
    "DB_PORT",
    "DB_USER",
    "DB_PASSWORD",
    "DB_NAME",
)

# 워커에게 절대 넘기지 않는 외부 서비스 비밀값입니다. 허용 목록과 겹치지 않음을
# 시험이 고정합니다.
FORBIDDEN_WORKER_ENV_KEYS: tuple[str, ...] = (
    "G2B_SERVICE_KEY",
    "G2B_USRINFO_SERVICE_KEY",
    "GEMINI_API_KEY",
    "MODEL_MANIFEST_SIGNING_KEY",
    "MYSQL_ROOT_PASSWORD",
    "GF_SECURITY_ADMIN_PASSWORD",
    "ALERTMANAGER_SLACK_WEBHOOK_URL",
    "MLOPS_WEBHOOK_URL",
)

HEADER = "# 워커 워크트리 최소 .env (scripts/orca_worker_env.py 자동 생성)"


def generate_secret_key() -> str:
    """워크트리마다 새로 쓰는 SECRET_KEY 를 만듭니다."""
    return secrets.token_hex(32)


def parse_env(text: str) -> dict[str, str]:
    """dotenv 본문을 키-값 사전으로 읽습니다.

    주석과 빈 줄은 건너뛰고, `export KEY=VALUE` 접두와 CRLF 를 허용합니다.
    값은 첫 `=` 뒤 전체를 그대로 둡니다(값 안의 `=` 를 자르지 않음).
    """
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if not key:
            continue
        values[key] = value.strip()
    return values


def forbidden_keys_in(text: str) -> list[str]:
    """본문에 값이 담긴 금지 키 이름을 정렬해 돌려줍니다. 값은 반환하지 않습니다."""
    present = parse_env(text)
    return sorted(key for key in FORBIDDEN_WORKER_ENV_KEYS if present.get(key))


def audit_worker_env(worker_text: str, repo_text: str | None = None) -> list[str]:
    """기존 워커 .env 를 그대로 두면 안 되는 사유를 키 이름으로 돌려줍니다.

    두 가지를 봅니다. 값이 담긴 금지 키가 남아 있는지, SECRET_KEY 가 주 저장소
    값과 같은지(복사된 것인지)입니다. 주 저장소 본문을 주지 않으면 SECRET_KEY
    대조는 건너뜁니다.
    """
    worker = parse_env(worker_text)
    reasons = [key for key in FORBIDDEN_WORKER_ENV_KEYS if worker.get(key)]

    repo_secret = None
    if repo_text is not None:
        repo_secret = parse_env(repo_text).get(SECRET_KEY_NAME)
    if repo_secret and worker.get(SECRET_KEY_NAME) == repo_secret:
        reasons.append(SECRET_KEY_NAME)

    return sorted(set(reasons))


def build_minimal_env(source_text: str, *, secret_key: str | None = None) -> str:
    """원본 .env 에서 허용 목록 키만 뽑아 워커용 최소 .env 본문을 만듭니다.

    SECRET_KEY 는 원본 값을 절대 복사하지 않고 항상 새로 만듭니다. 원본에 값이
    있던 금지 키는 결과에서 완전히 빠집니다.
    """
    values = parse_env(source_text)
    lines = [HEADER]
    lines.extend(f"{key}={values[key]}" for key in ALLOWED_WORKER_ENV_KEYS if key in values)
    lines.append(f"{SECRET_KEY_NAME}={secret_key or generate_secret_key()}")
    return "\n".join(lines) + "\n"

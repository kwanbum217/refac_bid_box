#!/usr/bin/env python3
"""
scripts/render_alertmanager_secret.py

.env 의 ALERTMANAGER_SLACK_WEBHOOK_URL 을 읽어
docker/secrets/alertmanager_slack_url 파일로 생성합니다.

Alertmanager 는 설정 파일(alertmanager.yml) 내에서 환경변수 치환(${VAR})을
지원하지 않으므로 api_url_file 지시자를 통해 비밀값 파일을 직접 참조합니다.

보안 및 운영 불변조건:
1. 비밀값은 표준출력이나 로그에 절대 출력하지 않습니다.
2. 생성된 비밀 파일은 소유자 읽기/쓰기 전용 권한(0600)으로 제한합니다.
3. 값이 없거나 비어 있으면 파일을 생성하지 않고 안전하게 종료합니다.
4. Docker 가 부재 중인 마운트 대상을 디렉터리로 자동 생성한 경우 이를 정리합니다.
"""

from __future__ import annotations

import argparse
import contextlib
import os
import sys
from pathlib import Path


def _parse_env_file(env_file_path: Path) -> dict[str, str]:
    """간단한 .env 파서 (외부 의존성 없음)."""
    if not env_file_path.is_file():
        return {}

    env_vars: dict[str, str] = {}
    try:
        content = env_file_path.read_text(encoding="utf-8")
    except OSError:
        return {}

    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip()
        # 따옴표 제거
        if len(val) >= 2 and (
            (val.startswith('"') and val.endswith('"'))
            or (val.startswith("'") and val.endswith("'"))
        ):
            val = val[1:-1].strip()
        env_vars[key] = val
    return env_vars


def get_webhook_url(env_file_path: Path | None = None) -> str:
    """ALERTMANAGER_SLACK_WEBHOOK_URL 값을 조회합니다.

    .env 파일 조회를 우선하며 시스템 환경변수를 보조로 참조합니다.
    """
    if env_file_path is not None and env_file_path.is_file():
        parsed = _parse_env_file(env_file_path)
        if "ALERTMANAGER_SLACK_WEBHOOK_URL" in parsed:
            return parsed["ALERTMANAGER_SLACK_WEBHOOK_URL"].strip()

    # 기본 .env 파일 확인
    default_env = Path(__file__).resolve().parent.parent / ".env"
    if default_env.is_file():
        parsed = _parse_env_file(default_env)
        if "ALERTMANAGER_SLACK_WEBHOOK_URL" in parsed:
            return parsed["ALERTMANAGER_SLACK_WEBHOOK_URL"].strip()

    # 시스템 환경변수 확인
    return os.environ.get("ALERTMANAGER_SLACK_WEBHOOK_URL", "").strip()


def render_alertmanager_secret(
    env_file_path: Path | None = None,
    output_file_path: Path | None = None,
) -> bool:
    """비밀 파일을 렌더링합니다.

    Returns:
        bool: 파일이 생성되었으면 True, 값이 없어 생성되지 않았으면 False
    """
    project_root = Path(__file__).resolve().parent.parent
    if output_file_path is None:
        output_file_path = project_root / "docker" / "secrets" / "alertmanager_slack_url"

    webhook_url = get_webhook_url(env_file_path)

    # 도커가 바인드 마운트 대상 부재 시 디렉터리를 자동 생성하는 함정 방어
    if output_file_path.is_dir():
        try:
            output_file_path.rmdir()
        except OSError as err:
            sys.stderr.write(f"경고: 기존 디렉터리 정리 실패 ({output_file_path}): {err}\n")

    if not webhook_url:
        # 값이 없을 때는 파일을 생성하지 않고 안전하게 안내만 출력
        sys.stdout.write(
            "ALERTMANAGER_SLACK_WEBHOOK_URL 이 설정되지 않았거나 비어 있어 비밀 파일을 생성하지 않습니다.\n"
        )
        return False

    # 부모 디렉터리 생성 (0700 권한)
    secrets_dir = output_file_path.parent
    secrets_dir.mkdir(mode=0o700, parents=True, exist_ok=True)

    # 비밀 파일 쓰기 (개행 포함)
    output_file_path.write_text(webhook_url + "\n", encoding="utf-8")

    # 파일 권한 0600 (소유자 읽기/쓰기 전용)
    os.chmod(output_file_path, 0o600)

    # 비밀값 자체는 절대 출력하지 않고 성공 여부와 경로만 출력
    rel_path = output_file_path
    with contextlib.suppress(ValueError):
        rel_path = output_file_path.relative_to(project_root)

    sys.stdout.write(
        f"Alertmanager Slack 웹훅 비밀 파일이 생성되었습니다: {rel_path} (권한: 0600)\n"
    )
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Alertmanager Slack 웹훅 비밀 파일 생성 스크립트")
    parser.add_argument(
        "--env-file",
        type=Path,
        default=None,
        help=".env 파일 경로 (기본값: 프로젝트 루트 .env)",
    )
    parser.add_argument(
        "--output-file",
        type=Path,
        default=None,
        help="생성할 비밀 파일 경로 (기본값: docker/secrets/alertmanager_slack_url)",
    )

    args = parser.parse_args()
    render_alertmanager_secret(
        env_file_path=args.env_file,
        output_file_path=args.output_file,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

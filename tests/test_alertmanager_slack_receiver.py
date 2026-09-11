"""
tests/test_alertmanager_slack_receiver.py

Alertmanager Slack 수신기 및 비밀값 파일 주입 배선 테스트.

검증 항목:
1. docker/alertmanager.yml 이 유효한 YAML 구조이며 구문 오류가 없음.
2. 기본 수신기(default receiver)가 여전히 local-hold 로 유지됨.
3. severity=critical 알람만 slack-slo 로 라우팅되는 자식 라우트가 존재함.
4. timing 값(group_wait, group_interval, repeat_interval)이 원본대로 보존됨.
5. slack-slo 수신기가 api_url_file 을 사용하며 실제 URL 문자열이 파일 어디에도 없음.
6. Slack 메시지 템플릿에 알람명, SLO, severity, 발화시각, 대시보드 링크 등이 포함됨.
7. scripts/render_alertmanager_secret.py 가 값이 없을 때 파일을 생성하지 않음.
8. 렌더 스크립트가 값을 출력(stdout/stderr)에 절대 노출하지 않음.
9. 렌더 스크립트가 생성한 파일의 권한이 0600 으로 설정됨.
10. 도커가 생성한 빈 디렉터리 함정을 렌더 스크립트가 안전하게 방어함.
11. 저장소 추적 파일 어디에도 실제 Slack webhook 토큰 경로가 커밋되지 않음.
12. .gitignore 에 docker/secrets/ 가 포함되어 있음.
13. docker-compose.prod.yml 의 alertmanager 서비스에 비밀 파일 볼륨 마운트가 명시됨.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest
import yaml

from scripts.render_alertmanager_secret import render_alertmanager_secret

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ALERTMANAGER_YML = PROJECT_ROOT / "docker" / "alertmanager.yml"
DOCKER_COMPOSE_PROD_YML = PROJECT_ROOT / "docker-compose.prod.yml"
GITIGNORE_FILE = PROJECT_ROOT / ".gitignore"


def test_alertmanager_yaml_validity() -> None:
    """docker/alertmanager.yml 파일이 유효한 YAML 구조를 가지는지 검증합니다."""
    assert ALERTMANAGER_YML.is_file(), f"{ALERTMANAGER_YML} 파일이 존재하지 않습니다."
    content = ALERTMANAGER_YML.read_text(encoding="utf-8")
    data = yaml.safe_load(content)

    assert isinstance(data, dict), "Alertmanager 설정 최상위는 딕셔너리여야 합니다."
    assert "route" in data, "route 블록이 정의되어 있어야 합니다."
    assert "receivers" in data, "receivers 블록이 정의되어 있어야 합니다."
    assert "inhibit_rules" in data, "inhibit_rules 블록이 정의되어 있어야 합니다."


def test_default_receiver_is_local_hold_and_timings_preserved() -> None:
    """기본 수신기가 local-hold 이고 group_wait, group_interval, repeat_interval 이 보존되는지 검증합니다."""
    data = yaml.safe_load(ALERTMANAGER_YML.read_text(encoding="utf-8"))
    route = data["route"]

    assert route.get("receiver") == "local-hold", "기본 receiver 는 local-hold 여야 합니다."
    assert route.get("group_wait") == "30s", "group_wait 는 30s 로 유지되어야 합니다."
    assert route.get("group_interval") == "5m", "group_interval 은 5m 로 유지되어야 합니다."
    assert route.get("repeat_interval") == "4h", "repeat_interval 은 4h 로 유지되어야 합니다."

    # local-hold 수신기는 외부 발신 설정이 없어야 함
    receivers = {r["name"]: r for r in data["receivers"]}
    assert "local-hold" in receivers, "local-hold 수신기가 정의되어 있어야 합니다."
    local_hold = receivers["local-hold"]
    assert "slack_configs" not in local_hold, "local-hold 에 slack_configs 가 있으면 안 됩니다."
    assert "webhook_configs" not in local_hold, "local-hold 에 webhook_configs 가 있으면 안 됩니다."


def test_critical_only_routes_to_slack_slo() -> None:
    """severity=critical 알람만 slack-slo 로 분기하는 자식 라우트가 존재하는지 검증합니다."""
    data = yaml.safe_load(ALERTMANAGER_YML.read_text(encoding="utf-8"))
    route = data["route"]

    routes = route.get("routes", [])
    assert len(routes) > 0, "자식 라우트 목록이 존재해야 합니다."

    slack_routes = [r for r in routes if r.get("receiver") == "slack-slo"]
    assert len(slack_routes) == 1, "slack-slo 로 분기하는 자식 라우트가 정확히 1건 있어야 합니다."

    slack_route = slack_routes[0]
    matchers = slack_route.get("matchers", [])
    assert any("severity" in m and "critical" in m for m in matchers), (
        f"slack-slo 라우트는 severity=critical 조건이어야 합니다: {matchers}"
    )


def test_slack_receiver_uses_api_url_file_and_no_raw_url() -> None:
    """slack-slo 수신기가 api_url_file 을 사용하고 파일 어디에도 실제 웹훅 URL 문자열이 없는지 검증합니다."""
    raw_content = ALERTMANAGER_YML.read_text(encoding="utf-8")
    data = yaml.safe_load(raw_content)

    receivers = {r["name"]: r for r in data["receivers"]}
    assert "slack-slo" in receivers, "slack-slo 수신기가 정의되어 있어야 합니다."

    slack_slo = receivers["slack-slo"]
    assert "slack_configs" in slack_slo, "slack_configs 가 정의되어 있어야 합니다."
    assert len(slack_slo["slack_configs"]) >= 1, "최소 1개 이상의 slack_config 가 필요합니다."

    slack_cfg = slack_slo["slack_configs"][0]
    assert "api_url_file" in slack_cfg, "api_url_file 설정이 필수입니다."
    assert slack_cfg["api_url_file"] == "/etc/alertmanager/secrets/slack_url", (
        f"api_url_file 경로가 예상과 다릅니다: {slack_cfg.get('api_url_file')}"
    )
    assert "api_url" not in slack_cfg, "api_url 에 직접 URL 을 지정하면 안 됩니다."

    # 원본 텍스트에 hooks.slack.com 문자열이 일체 없어야 함
    assert "hooks.slack.com" not in raw_content, (
        "alertmanager.yml 에 hooks.slack.com 이 포함되면 안 됩니다."
    )


def test_slack_message_content_requirements() -> None:
    """Slack 메시지 템플릿에 알람명, slo, severity, 발화시각, Grafana 대시보드 링크가 포함되는지 검증합니다."""
    data = yaml.safe_load(ALERTMANAGER_YML.read_text(encoding="utf-8"))
    slack_cfg = next(r for r in data["receivers"] if r["name"] == "slack-slo")["slack_configs"][0]

    title = slack_cfg.get("title", "")
    text = slack_cfg.get("text", "")
    combined = f"{title}\n{text}"

    assert "alertname" in combined, "메시지에 alertname 이 포함되어야 합니다."
    assert "slo" in combined, "메시지에 slo 라벨이 포함되어야 합니다."
    assert "severity" in combined, "메시지에 severity 라벨이 포함되어야 합니다."
    assert "StartsAt" in combined or "startsAt" in combined, (
        "메시지에 발화 시각이 포함되어야 합니다."
    )
    assert "summary" in combined, "메시지에 summary 애노테이션 참조가 포함되어야 합니다."
    assert "description" in combined, "메시지에 description 애노테이션 참조가 포함되어야 합니다."
    assert "bidbox-slo-alerts" in combined, (
        "메시지에 bidbox-slo-alerts 대시보드 링크가 포함되어야 합니다."
    )


def test_render_script_does_not_create_file_when_secret_absent(tmp_path: Path) -> None:
    """비밀값 환경변수가 없거나 비어 있을 때 파일을 생성하지 않고 False 를 반환하는지 검증합니다."""
    empty_env = tmp_path / ".env.empty"
    empty_env.write_text(
        "SOME_OTHER_KEY=value\nALERTMANAGER_SLACK_WEBHOOK_URL=\n", encoding="utf-8"
    )

    out_file = tmp_path / "secrets" / "alertmanager_slack_url"
    success = render_alertmanager_secret(env_file_path=empty_env, output_file_path=out_file)

    assert not success, "비밀값이 없을 때 False 를 반환해야 합니다."
    assert not out_file.exists(), "비밀값이 없을 때 파일이 생성되면 안 됩니다."


def test_render_script_creates_file_with_0600_permissions(tmp_path: Path) -> None:
    """비밀값이 있을 때 파일을 생성하고 권한을 0600 으로 설정하는지 검증합니다."""
    test_env = tmp_path / ".env.test"
    dummy_url = "https://hooks.slack.com/services/DUMMY/URL/12345"
    test_env.write_text(f"ALERTMANAGER_SLACK_WEBHOOK_URL={dummy_url}\n", encoding="utf-8")

    out_file = tmp_path / "secrets" / "alertmanager_slack_url"
    success = render_alertmanager_secret(env_file_path=test_env, output_file_path=out_file)

    assert success, "비밀값이 있을 때 True 를 반환해야 합니다."
    assert out_file.is_file(), "비밀 파일이 생성되어야 합니다."
    assert out_file.read_text(encoding="utf-8").strip() == dummy_url

    mode = oct(out_file.stat().st_mode & 0o777)
    assert mode == "0o600", f"파일 권한이 0600 이어야 합니다: {mode}"


def test_render_script_does_not_leak_secret(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """렌더 스크립트가 비밀값을 표준출력이나 표준에러에 노출하지 않는지 검증합니다."""
    canary_id = "CANARY_VALUE_LEAK_CHECK"
    dummy_url = f"https://hooks.slack.com/services/{canary_id}"

    test_env = tmp_path / ".env.leak_test"
    test_env.write_text(f"ALERTMANAGER_SLACK_WEBHOOK_URL={dummy_url}\n", encoding="utf-8")

    out_file = tmp_path / "secrets" / "alertmanager_slack_url"
    render_alertmanager_secret(env_file_path=test_env, output_file_path=out_file)

    captured = capsys.readouterr()
    assert canary_id not in captured.out, "비밀값이 stdout 에 출력되었습니다."
    assert canary_id not in captured.err, "비밀값이 stderr 에 출력되었습니다."
    assert dummy_url not in captured.out, "웹훅 URL 이 stdout 에 출력되었습니다."
    assert dummy_url not in captured.err, "웹훅 URL 이 stderr 에 출력되었습니다."


def test_render_script_defends_against_docker_directory_trap(tmp_path: Path) -> None:
    """도커가 마운트 대상 부재 시 디렉터리로 자동 생성한 함정을 정리하고 정상 파일로 대체하는지 검증합니다."""
    out_file = tmp_path / "secrets" / "alertmanager_slack_url"
    out_file.mkdir(parents=True)
    assert out_file.is_dir(), "테스트 사전 조건: 디렉터리가 생성되어 있어야 합니다."

    test_env = tmp_path / ".env.test"
    test_env.write_text(
        "ALERTMANAGER_SLACK_WEBHOOK_URL=https://hooks.slack.com/services/DUMMY\n", encoding="utf-8"
    )

    success = render_alertmanager_secret(env_file_path=test_env, output_file_path=out_file)
    assert success
    assert out_file.is_file(), "디렉터리가 정리되고 정상 파일로 대체되어야 합니다."
    assert not out_file.is_dir()


def test_gitignore_contains_docker_secrets() -> None:
    """.gitignore 에 docker/secrets/ 가 포함되어 있는지 검증합니다."""
    assert GITIGNORE_FILE.is_file()
    lines = GITIGNORE_FILE.read_text(encoding="utf-8").splitlines()
    assert any("docker/secrets/" in line.strip() for line in lines), (
        ".gitignore 에 docker/secrets/ 가 명시되어 있어야 합니다."
    )


def test_docker_compose_prod_alertmanager_volume_mount() -> None:
    """docker-compose.prod.yml 의 alertmanager 서비스에 비밀 파일 마운트가 명시되어 있는지 검증합니다."""
    data = yaml.safe_load(DOCKER_COMPOSE_PROD_YML.read_text(encoding="utf-8"))
    services = data.get("services", {})
    assert "alertmanager" in services, "alertmanager 서비스가 정의되어 있어야 합니다."

    alertmanager_svc = services["alertmanager"]
    volumes = alertmanager_svc.get("volumes", [])

    expected_mount = (
        "./docker/secrets/alertmanager_slack_url:/etc/alertmanager/secrets/slack_url:ro"
    )
    expected_config_mount = "./docker/alertmanager.yml:/etc/alertmanager/alertmanager.yml:ro"
    expected_data_volume = "alertmanager_data:/alertmanager"

    assert any(expected_mount in str(v) for v in volumes), (
        f"비밀 파일 마운트({expected_mount})가 volumes 에 포함되어야 합니다: {volumes}"
    )
    assert any(expected_config_mount in str(v) for v in volumes), (
        f"설정 파일 마운트({expected_config_mount})가 volumes 에 포함되어야 합니다: {volumes}"
    )
    assert any(expected_data_volume in str(v) for v in volumes), (
        f"데이터 볼륨({expected_data_volume})이 volumes 에 포함되어야 합니다: {volumes}"
    )


def test_no_slack_tokens_committed_in_git() -> None:
    """Git 추적 파일 어디에도 실제 Slack webhook 토큰 형식이 커밋되지 않았는지 검증합니다."""
    # Slack Incoming Webhook 정규식: hooks.slack.com/services/T.../B.../...
    pattern = re.compile(r"hooks\.slack\.com/services/T[0-9A-Z]+/B[0-9A-Z]+/[0-9A-Za-z]+")

    # git ls-files 로 추적 중인 모든 파일 검사
    result = subprocess.run(
        ["git", "ls-files"],  # noqa: S607
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    tracked_files = [line.strip() for line in result.stdout.splitlines() if line.strip()]

    leaked_files: list[str] = []
    for rel_path in tracked_files:
        full_path = PROJECT_ROOT / rel_path
        if not full_path.is_file():
            continue
        try:
            content = full_path.read_text(encoding="utf-8", errors="ignore")
            if pattern.search(content):
                leaked_files.append(rel_path)
        except OSError:
            continue

    assert not leaked_files, (
        f"실제 Slack webhook 토큰이 포함된 파일이 발견되었습니다: {leaked_files}"
    )

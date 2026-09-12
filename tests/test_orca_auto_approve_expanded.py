"""확장된 자동 승인 화이트리스트의 허용 경계를 검증합니다."""

from __future__ import annotations

import pytest

from scripts.orca_auto_approve import classify_command


@pytest.mark.parametrize(
    "cmd",
    [
        "git add src/main.py",
        "git add src/main.py tests/test_orca_auto_approve_expanded.py",
        "git add --dry-run src/main.py",
        "git add -n -- src/main.py",
        "git commit -m 'feat: 안전한 커밋'",
        "git commit --message 'feat: 안전한 커밋'",
        "git commit -F commit-message.txt",
        "git commit --file commit-message.txt",
        "pgrep -af python",
        "arbitrary-cli --help",
        "arbitrary-cli -h",
        "orca orchestration send --from term_worker --type heartbeat",
    ],
)
def test_expanded_safe_commands_are_approved(cmd: str) -> None:
    """명시된 읽기 전용 또는 정규 조율 명령은 자동 승인합니다."""
    verdict, reason = classify_command(cmd)
    assert verdict == "approve", f"'{cmd}' 판정이 {verdict}입니다: {reason}"


@pytest.mark.parametrize(
    "cmd",
    [
        "git add",
        "git add -A",
        "git add --all",
        "git add -u",
        "git add --update",
        "git add .",
        "git add -- .",
        "git add --dry-run",
        "git commit",
        "git commit --no-verify",
        "git commit -n",
        "git commit --amend",
        "git commit --allow-empty",
        "git commit --author='작성자 <author@example.com>'",
        "git commit --date='2026-09-10'",
        "git commit --reset-author",
        "orca worktree rm worker-tree",
        "orca terminal close --terminal term_worker",
    ],
)
def test_expanded_unsafe_commands_are_held(cmd: str) -> None:
    """전체 스테이징, 커밋 검증 우회, Orca 변경 명령은 사람에게 묻습니다."""
    verdict, reason = classify_command(cmd)
    assert verdict == "hold", f"'{cmd}' 판정이 {verdict}입니다: {reason}"


@pytest.mark.parametrize(
    "cmd",
    [
        "git commit -m '메시지' --no-verify",
        "git commit -m '메시지' -n",
        "git commit -m '메시지' --amend",
        "git commit -m '메시지' --allow-empty",
        "git commit -m '메시지' --author='작성자'",
        "git commit -m '메시지' --date='2026-09-10'",
        "git commit -m '메시지' --reset-author",
        "unknown-cli --help | rm temporary.txt",
        "orca orchestration send --type heartbeat | git push origin main",
        "git add src/main.py | git push origin main",
        "unknown-cli --help > ../outside.txt",
        "echo $(rm --help)",
    ],
)
def test_expanded_allowances_do_not_bypass_existing_composite_guards(cmd: str) -> None:
    """새 허용 명령 뒤의 위험 구간과 기존 셸 보호 경로는 계속 보류합니다."""
    verdict, reason = classify_command(cmd)
    assert verdict == "hold", f"'{cmd}' 판정이 {verdict}입니다: {reason}"


@pytest.mark.parametrize(
    "cmd",
    [
        "git status",
        "git diff",
        "git log",
        "git merge-base main HEAD",
        "git rev-parse HEAD",
        "git show HEAD",
    ],
)
def test_existing_safe_git_subcommands_remain_approved(cmd: str) -> None:
    """기존 여섯 읽기 전용 git 서브커맨드의 판정은 유지합니다."""
    verdict, reason = classify_command(cmd)
    assert verdict == "approve", f"'{cmd}' 판정이 {verdict}입니다: {reason}"


@pytest.mark.parametrize(
    "cmd",
    [
        "docker info",
        "docker images",
        "docker images | grep refac-bid-box",
        "docker ps -a",
        "docker version",
        "docker context ls",
        "docker image ls",
        "docker volume ls",
        "docker network ls",
        "docker system df",
        "docker compose config -q",
        "docker compose ps",
        "docker build -t refac-bid-box-root:orca-gate .",
        "docker build -t refac-bid-box-frontend:orca-gate frontend",
        "sleep 5",
        "for i in {1..30}; do docker info >/dev/null 2>&1 && echo ready || sleep 2; done",
        "npm audit --audit-level=high --json",
        "npm audit --audit-level=high --json 2>/tmp/err.log >/tmp/out.json",
        "npm ls nanoid",
        "npm outdated",
        "npm config get registry",
        "docker rmi refac-bid-box-root:orca-gate",
        "docker image rm old",
    ],
)
def test_docker_and_npm_readonly_commands_are_approved(cmd: str) -> None:
    """상태를 바꾸지 않는 docker/npm 조회와 로컬 이미지 빌드는 자동 승인합니다."""
    verdict, reason = classify_command(cmd)
    assert verdict == "approve", f"'{cmd}' 판정이 {verdict}입니다: {reason}"


@pytest.mark.parametrize(
    "cmd",
    [
        "docker run -d nginx",
        "docker exec -i db mysql -e 'SELECT 1'",
        "docker rm -f app",
        "docker system prune -af",
        "docker volume rm data",
        "docker rmi",
        "docker image rm",
        "docker rmi -f",
        "docker context use remote",
        "docker build -o type=local,dest=/tmp/out .",
        "docker build --output type=tar,dest=/tmp/out.tar .",
        "docker --host tcp://remote:2375 info",
        "docker",
        "npm install",
        "npm ci",
        "npm audit fix",
        "npm audit fix --force",
        "npm run build",
        "npm config set registry http://example.invalid",
        "npm publish",
        "npx create-app",
    ],
)
def test_docker_and_npm_mutating_commands_are_held(cmd: str) -> None:
    """컨테이너나 의존성 트리를 바꾸는 명령은 종전대로 사람 승인을 기다립니다."""
    verdict, reason = classify_command(cmd)
    assert verdict == "hold", f"'{cmd}' 판정이 {verdict}입니다: {reason}"


def test_docker_exec_mysql_path_stays_closed() -> None:
    """docker exec 를 통한 DB 접근 경로는 확장 이후에도 열리지 않습니다."""
    verdict, _ = classify_command(
        "docker exec -i mysql mysql -e 'SELECT COUNT(*) FROM bid_results'"
    )
    assert verdict == "hold"


def test_docker_build_redirect_to_secret_is_held() -> None:
    """리다이렉트 대상 검증이 docker build 승인보다 우선합니다."""
    verdict, _ = classify_command("docker build . > /Users/kwanbum/.env")
    assert verdict == "hold"


@pytest.mark.parametrize(
    "cmd",
    [
        "node -e \"const t = require('typescript-eslint'); console.log(Object.keys(t));\"",
        "node -p \"require('./package.json').version\"",
        "node scripts/build.js",
        "node --version",
        "node --help",
    ],
)
def test_node_inline_evaluation_is_approved(cmd: str) -> None:
    """셸 탈출이나 삭제 토큰이 없는 node 실행은 python -c 와 같은 기준으로 승인합니다."""
    verdict, reason = classify_command(cmd)
    assert verdict == "approve", f"'{cmd}' 판정이 {verdict}입니다: {reason}"


@pytest.mark.parametrize(
    "cmd",
    [
        "node -e \"require('child_process').execSync('ls')\"",
        "node -e \"require('fs').rmSync('/tmp/x')\"",
        "node -e \"require('fs').unlinkSync('a')\"",
        'node -e "eval(process.argv[1])"',
        "node -e \"require('vm').runInNewContext(s)\"",
        "node",
        "node --inspect-brk",
    ],
)
def test_node_escape_tokens_are_held(cmd: str) -> None:
    """셸 탈출, 파일 삭제, 동적 평가 토큰이 있으면 종전대로 사람 승인을 기다립니다."""
    verdict, reason = classify_command(cmd)
    assert verdict == "hold", f"'{cmd}' 판정이 {verdict}입니다: {reason}"

"""M7 1단계 CLI 권한 하드닝 계약 검증.

워커 런처 argv(cmd --yolo 제거, opencode --auto 제거, agy 샌드박스)와 저장소가
관리하는 cmd 워커 deny 정책, opencode.json permission 블록, 정책 배치 경계를
단위 시험으로 고정합니다. 실제 워커 CLI 는 띄우지 않습니다.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts import orca_agy_launch, orca_auto_approve, orca_cmd_launch, orca_opencode_launch
from scripts.orca_worker_launch_common import (
    WORKER_SETTINGS_PATH,
    deploy_worker_settings,
    worker_policy_source,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CMD_MODEL = "deepseek/deepseek-v4.1-flash"
OPENCODE_MODEL = "openai/gpt-5.6-turbo"
AGY_MODEL = "gemini-3.8-flash-medium"


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _policy_permissions() -> dict:
    return _read_json(worker_policy_source())["permissions"]


# ---------------------------------------------------------------------------
# 1. 런처 argv
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("one_shot", [False, True])
@pytest.mark.parametrize("auto", [False, True])
@pytest.mark.parametrize("effort", [None, "low"])
def test_cmd_launcher_never_adds_yolo(auto: bool, one_shot: bool, effort: str | None):
    """cmd 는 어떤 인자 조합에서도 권한 우회를 켜지 않습니다."""
    cmd = orca_cmd_launch.build_command(
        CMD_MODEL, "지시문", effort=effort, one_shot=one_shot, auto=auto
    )
    assert "--yolo" not in cmd
    assert "--dangerously-skip-permissions" not in cmd


def test_cmd_launcher_auto_keeps_only_workspace_trust():
    """--trust 는 작업 공간 신뢰 대화창만 넘기므로 유지하고 --yolo 는 뺍니다."""
    assert orca_cmd_launch.build_command(CMD_MODEL, "지시문", auto=True) == [
        "cmd",
        "--model",
        CMD_MODEL,
        "--trust",
        "지시문",
    ]


@patch("scripts.orca_cmd_launch.run_cmd", return_value=0)
def test_cmd_main_never_execs_yolo(mock_run, tmp_path: Path, monkeypatch):
    """build_command 뿐 아니라 실제 main 실행 경로에서도 --yolo 가 없어야 합니다."""
    monkeypatch.setattr(orca_cmd_launch.common, "deploy_worker_settings", lambda *a, **k: None)
    target = tmp_path / "preamble_policy_cmd.txt"
    target.write_text("지시문", encoding="utf-8")

    code = orca_cmd_launch.main(
        [
            "--model",
            CMD_MODEL,
            "--effort",
            "low",
            "--auto",
            "--preamble",
            str(target),
            "--one-shot",
            "--no-keep-open",
            "--no-commit-notice",
        ]
    )

    assert code == 0
    argv = mock_run.call_args[0][0]
    assert argv[:5] == ["cmd", "--model", CMD_MODEL, "--effort", "low"]
    assert "--trust" in argv
    assert "--yolo" not in argv


@pytest.mark.parametrize("one_shot", [False, True])
@pytest.mark.parametrize("auto", [False, True])
@pytest.mark.parametrize("binary", ["opencode", "kilo"])
def test_opencode_launcher_never_forwards_auto(binary: str, one_shot: bool, auto: bool):
    """--auto 는 명시 deny 가 아닌 모든 승인 요청을 자동 승인하므로 넘기지 않습니다."""
    variant = "max" if (binary == "kilo" or one_shot) else None
    cmd = orca_opencode_launch.build_command(
        OPENCODE_MODEL,
        "지시문",
        one_shot=one_shot,
        auto=auto,
        binary=binary,
        variant=variant,
    )
    assert "--auto" not in cmd


def test_agy_launcher_enables_terminal_sandbox():
    """agy --help 기준 --sandbox 는 터미널 제한 샌드박스를 켭니다."""
    cmd = orca_agy_launch.build_command(AGY_MODEL, "지시문")
    assert "--sandbox" in cmd
    assert "--dangerously-skip-permissions" not in cmd


# ---------------------------------------------------------------------------
# 2. cmd 워커 deny 정책
# ---------------------------------------------------------------------------


def test_policy_source_is_repo_managed_file():
    source = worker_policy_source()
    assert source.is_file()
    assert source.relative_to(PROJECT_ROOT) == Path(
        "scripts/orca_policies/commandcode_worker_settings.json"
    )


def test_policy_keeps_default_mode_and_allows_yolo():
    """yolo 진입을 열어 두고(defaultMode 유지, disableBypass 없음) 고정합니다."""
    permissions = _policy_permissions()
    assert permissions["defaultMode"] == "default"
    assert "disableBypass" not in permissions, "yolo 진입을 막으면 안 됩니다"


def test_policy_has_no_allow_rules():
    """yolo 는 deny 규칙만으로 위험 명령을 막습니다. allow 규칙은 두지 않습니다."""
    assert "allow" not in _policy_permissions()


def test_policy_denies_git_push_git_dir_and_secret_reads():
    deny = _policy_permissions()["deny"]
    assert isinstance(deny, list)
    assert deny, "deny 가 비어 있으면 정책이 무의미합니다"
    assert "Shell(git push:*)" in deny
    assert "Edit(.git/**)" in deny
    assert "Read(.env*)" in deny
    assert "Read(//etc/**)" in deny
    assert any(rule.startswith("Read(~/") for rule in deny), deny


# yolo 에서도 살아남아야 하는 추가 deny 입니다. yolo 는 deny 규칙을 지웁니다.
REQUIRED_DENY_RULES = {
    # 운영 DB 직접 접근
    "Shell(mysql:*)",
    "Shell(mysqldump:*)",
    "Shell(mysqladmin:*)",
    # 컨테이너/볼륨/이미지 삭제와 임의 실행
    "Shell(docker compose down:*)",
    "Shell(docker-compose down:*)",
    "Shell(docker compose rm:*)",
    "Shell(docker volume rm:*)",
    "Shell(docker volume prune:*)",
    "Shell(docker system prune:*)",
    "Shell(docker rm:*)",
    "Shell(docker exec:*)",
    "Shell(docker run:*)",
    # 작업 트리 밖 삭제와 권한 상승
    "Shell(rm -rf:*)",
    "Shell(rm -fr:*)",
    "Shell(sudo:*)",
    # main 브랜치 조작과 이력 재작성
    "Shell(git checkout main:*)",
    "Shell(git switch main:*)",
    "Shell(git merge:*)",
    "Shell(git reset --hard:*)",
    "Shell(git branch -D:*)",
    "Shell(git rebase:*)",
    # 하위 경로 비밀 파일
    "Read(**/.env)",
    "Read(**/.env.*)",
}


def test_policy_denies_database_docker_delete_and_branch_commands():
    """yolo 에서도 유효해야 하는 위험 명령이 deny 에 모두 있는지 고정합니다."""
    deny = set(_policy_permissions()["deny"])
    missing = sorted(REQUIRED_DENY_RULES - deny)
    assert not missing, missing


# ---------------------------------------------------------------------------
# 3. opencode.json permission 블록
# ---------------------------------------------------------------------------


def test_opencode_json_instructions_and_provider_preserved():
    data = _read_json(PROJECT_ROOT / "opencode.json")
    assert data["instructions"] == ["AGENTS.md"]
    assert data["provider"]["cerebras"]["models"]["gemma-4-31b"]["name"] == "Gemma 4 31B"


def test_opencode_json_denies_external_directory_and_env_reads():
    permission = _read_json(PROJECT_ROOT / "opencode.json")["permission"]
    assert permission["external_directory"] == "deny"
    read_rules = permission["read"]
    assert read_rules["*.env"] == "deny"
    assert read_rules["*.env.*"] == "deny"
    assert read_rules["*.env.example"] == "allow"


def test_opencode_json_denies_dangerous_bash_patterns():
    bash_rules = _read_json(PROJECT_ROOT / "opencode.json")["permission"]["bash"]
    for pattern in ("git push*", "git reset --hard*", "git clean -*", "rm -rf *", "sudo *"):
        assert bash_rules[pattern] == "deny", pattern


def test_opencode_json_has_no_blanket_allow():
    permission = _read_json(PROJECT_ROOT / "opencode.json")["permission"]
    assert permission.get("bash", {}).get("*") is None
    assert permission.get("read", {}).get("*") is None


# ---------------------------------------------------------------------------
# 4. 정책 배치 경계 (실제 연결 워크트리)
# ---------------------------------------------------------------------------


def _git(args: list[str], cwd: Path) -> None:
    argv = ["git", "-C", str(cwd), *args]
    subprocess.run(argv, check=True, capture_output=True, text=True)  # noqa: S603


def _init_repo_with_worktree(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    repo.mkdir()
    worktree = tmp_path / "worker-wt"
    _git(["init", "-q"], repo)
    _git(
        [
            "-c",
            "user.email=test@example.com",
            "-c",
            "user.name=test",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            "init",
        ],
        repo,
    )
    _git(["worktree", "add", "--detach", str(worktree)], repo)
    return repo, worktree


def test_deploy_writes_policy_into_real_linked_worktree(tmp_path: Path):
    _repo, worktree = _init_repo_with_worktree(tmp_path)

    deployed = deploy_worker_settings(worktree)

    assert deployed == worktree / WORKER_SETTINGS_PATH
    assert deployed is not None
    assert deployed.read_text(encoding="utf-8") == worker_policy_source().read_text(
        encoding="utf-8"
    )


def test_deploy_skips_real_main_worktree(tmp_path: Path):
    """주 저장소의 .commandcode/settings.json 은 사용자 개인 설정이라 건드리지 않습니다."""
    repo, _worktree = _init_repo_with_worktree(tmp_path)
    existing = repo / WORKER_SETTINGS_PATH
    existing.parent.mkdir(parents=True)
    existing.write_text('{"permissions": {"allow": ["Shell(brew:*)"]}}', encoding="utf-8")

    assert deploy_worker_settings(repo) is None
    assert existing.read_text(encoding="utf-8") == '{"permissions": {"allow": ["Shell(brew:*)"]}}'


# ---------------------------------------------------------------------------
# 5. 감시기 교차 확인 (정책 deny 와 같은 명령이 보류되는지)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        "git push origin main",
        "cat .env",
        "rm -rf build",
    ],
)
def test_policy_denied_commands_are_held_by_watcher(command: str):
    """정책이 막는 명령은 감시기도 승인하지 않아야 이중 방어선이 성립합니다."""
    verdict, _reason = orca_auto_approve.classify_command(command)
    assert verdict == "hold"


def test_watcher_detects_opencode_permission_dialog():
    """opencode 승인 대화창은 cmd/agy 패턴에 걸리지 않으므로 전용 탐지가 필요합니다."""
    screen = (
        "△ Permission required\n"
        "$ git status --short\n"
        "Allow once  Always allow  Reject\n"
        "enter confirm\n"
    )
    assert orca_auto_approve.pending_command(screen) == "git status --short"

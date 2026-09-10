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

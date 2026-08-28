"""scripts/orca_auto_approve.py 에 대한 단위 테스트."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from scripts.orca_auto_approve import (
    classify_command,
    is_safe_git_branch,
    parse_git_subcommand,
    pending_command,
    poll_loop,
    read,
    send,
)


class TestClassifyCommandSafe:
    """안전한 읽기 전용 명령 자동 승인(approve) 검증."""

    @pytest.mark.parametrize(
        "cmd",
        [
            "git status",
            "git status -s",
            "git -C /tmp status",
            "git diff",
            "git diff HEAD~1",
            "git --no-pager diff",
            "git log",
            "git log -n 10 --oneline",
            "git show HEAD",
            "git show HEAD:src/main.py",
            "git rev-parse HEAD",
            "git rev-parse --show-toplevel",
            "git branch --show-current",
            "git branch",
            "git branch -a",
            "git branch -r",
            "git branch --list",
            "git worktree list",
            "git worktree list --porcelain",
            "rg 'def main' src/",
            "grep 'TODO' README.md",
            "cat pyproject.toml",
            "head -n 20 setup.py",
            "tail -n 50 app.log",
            "wc -l src/main.py",
            "ls -la",
            "echo 'hello world'",
            "jq '.name' package.json",
            "diff file1.txt file2.txt",
            "find . -name '*.py'",
            "find src -type f",
            "sed -n '1,10p' file.txt",
            "sed -n -e '1,5p' file.txt",
            "pytest",
            "pytest tests/ -q",
            "uv run pytest",
            "uv run pytest tests/ -q -m 'not data_assets'",
        ],
    )
    def test_safe_commands_approved(self, cmd: str) -> None:
        verdict, reason = classify_command(cmd)
        assert verdict == "approve", f"Expected approve for '{cmd}', got {verdict} ({reason})"


class TestClassifyCommandHold:
    """파괴적이거나 위험한 명령 보류(hold) 검증."""

    @pytest.mark.parametrize(
        "cmd",
        [
            # (b) Git 위험 명령
            "git clean -fdx",
            "git clean -f",
            "git branch -D x",
            "git branch -d feature",
            "git branch -m old new",
            "git branch new_branch_name",
            "git reset --hard",
            "git reset --hard HEAD~1",
            "git reset --soft HEAD~1",
            "git push",
            "git push origin main",
            "git checkout main",
            "git checkout -b feature",
            "git restore src/main.py",
            "git commit -m 'feat: something'",
            "git merge feature",
            "git rebase main",
            "git worktree add ../other main",
            "git worktree remove ../other",
            # (c) Python 임의 실행
            'python3 -c "import os"',
            "python3 scripts/foo.py",
            "python script.py",
            "python3.12 test.py",
            # (d) find 위험 옵션
            "find . -delete",
            "find . -exec rm {} +",
            "find . -execdir rm {} +",
            "find . -ok rm {} +",
            # (e) 빌드, 도커, 파일 변경
            "npm run build",
            "npm test",
            "npm install",
            "mv a b",
            "cp a b",
            "mkdir -p new_dir",
            "rm file.txt",
            "chmod 755 script.sh",
            "docker compose exec api sh",
            "docker compose up -d",
            "docker ps",
            "docker run -it ubuntu",
            # sed 수정 옵션
            "sed -i 's/a/b/g' file.txt",
            "sed -i.bak 's/a/b/g' file.txt",
            "sed 's/a/b/g' file.txt",
            # uv 위험 명령
            "uv run python script.py",
            "uv add requests",
            "uv pip install flask",
        ],
    )
    def test_hold_commands(self, cmd: str) -> None:
        verdict, reason = classify_command(cmd)
        assert verdict == "hold", f"Expected hold for '{cmd}', got {verdict} ({reason})"


class TestClassifyCommandMetacharacters:
    """(f) 셸 메타문자 포함 명령 보류 검증."""

    @pytest.mark.parametrize(
        "cmd",
        [
            "ls | grep foo",
            "cat file.txt > output.txt",
            "cat < input.txt",
            "cat file.txt >> output.txt",
            "ls; echo 1",
            "pytest && echo done",
            "pytest || echo fail",
            "echo `whoami`",
            "echo $(whoami)",
            "echo $((1 + 1))",
            "git status\nrm -rf /",
            "git diff\recho 1",
            "find . -exec rm {} \\;",
        ],
    )
    def test_shell_metacharacters_hold(self, cmd: str) -> None:
        verdict, reason = classify_command(cmd)
        assert verdict == "hold"
        assert "셸 메타문자" in reason or "위험 패턴" in reason or "보류" in reason


class TestClassifyCommandParsingAndEmpty:
    """(g), (h) 파싱 실패 및 빈 문자열/알 수 없는 명령 검증."""

    @pytest.mark.parametrize(
        "cmd",
        [
            "",
            "   ",
            "\t\n",
        ],
    )
    def test_empty_command_hold(self, cmd: str) -> None:
        verdict, reason = classify_command(cmd)
        assert verdict == "hold"
        assert "빈 명령" in reason

    @pytest.mark.parametrize(
        "cmd",
        [
            'git log "unclosed quote',
            "rg 'unclosed single quote",
            'echo "test',
        ],
    )
    def test_unclosed_quotes_parsing_failure_hold(self, cmd: str) -> None:
        verdict, reason = classify_command(cmd)
        assert verdict == "hold"
        assert "명령 파싱 실패" in reason

    @pytest.mark.parametrize(
        "cmd",
        [
            "unknown_binary_xyz",
            "curl https://example.com",
            "wget https://example.com",
            "bash script.sh",
            "sh test.sh",
            "sudo ls",
        ],
    )
    def test_unknown_commands_fail_closed(self, cmd: str) -> None:
        verdict, _ = classify_command(cmd)
        assert verdict == "hold"


class TestHelperFunctions:
    """보조 파싱 함수 및 pending_command 단위 테스트."""

    def test_parse_git_subcommand(self) -> None:
        subcmd, args = parse_git_subcommand(["diff", "HEAD"])
        assert subcmd == "diff"
        assert args == ["HEAD"]

        subcmd, args = parse_git_subcommand(["-C", "/path/to/repo", "status", "-s"])
        assert subcmd == "status"
        assert args == ["-s"]

        subcmd, args = parse_git_subcommand(["--no-pager", "log", "-n", "5"])
        assert subcmd == "log"
        assert args == ["-n", "5"]

        subcmd, args = parse_git_subcommand(["--version"])
        assert subcmd is None
        assert args == []

    def test_is_safe_git_branch(self) -> None:
        assert is_safe_git_branch([]) is True
        assert is_safe_git_branch(["--show-current"]) is True
        assert is_safe_git_branch(["-a"]) is True
        assert is_safe_git_branch(["--sort=-committerdate"]) is True
        assert is_safe_git_branch(["-D", "branch_name"]) is False
        assert is_safe_git_branch(["new_branch"]) is False

    def test_pending_command_extraction(self) -> None:
        screen_no_prompt = "Everything is running smoothly."
        assert pending_command(screen_no_prompt) is None

        screen_prompt = (
            "Some log output\n"
            "Requesting permission for:\n"
            "  git status -s\n"
            "Do you want to proceed?\n"
            "[1] Deny  [2] Allow"
        )
        assert pending_command(screen_prompt) == "git status -s"

        screen_missing_marker = "Some strange prompt\nDo you want to proceed?\n"
        assert pending_command(screen_missing_marker) == ""


class TestSubprocessInteractionMocks:
    """read, send, poll_loop mock 기반 테스트 (외부 프로세스 실행 방지)."""

    @patch("subprocess.run")
    def test_read_mocked(self, mock_run: MagicMock) -> None:
        mock_run.return_value.stdout = "mocked terminal screen output"
        out = read("term_123")
        assert out == "mocked terminal screen output"
        mock_run.assert_called_once_with(
            ["orca", "terminal", "read", "--terminal", "term_123"],
            capture_output=True,
            text=True,
            timeout=60,
        )

    @patch("subprocess.run")
    def test_send_mocked(self, mock_run: MagicMock) -> None:
        send("term_123", "2")
        mock_run.assert_called_once_with(
            ["orca", "terminal", "send", "--terminal", "term_123", "--text", "2", "--enter"],
            capture_output=True,
            text=True,
            timeout=60,
        )

    @patch("scripts.orca_auto_approve.time.sleep", side_effect=StopIteration)
    @patch("scripts.orca_auto_approve.send")
    @patch("scripts.orca_auto_approve.read")
    def test_poll_loop_iteration(
        self, mock_read: MagicMock, mock_send: MagicMock, mock_sleep: MagicMock
    ) -> None:
        mock_read.return_value = "Requesting permission for:\n  git status\nDo you want to proceed?"
        with pytest.raises(StopIteration):
            poll_loop(["term_abc"])
        mock_send.assert_called_once_with("term_abc", "2")

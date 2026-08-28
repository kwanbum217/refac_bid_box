"""scripts/orca_auto_approve.py 에 대한 단위 테스트."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts.orca_auto_approve import (
    CATEGORY_READ_ONLY,
    CATEGORY_TEST_EXECUTION,
    SAFE_STANDALONE_COMMANDS,
    SAFE_TEST_COMMANDS,
    classify_command,
    get_watcher_pid_path,
    is_safe_git_branch,
    is_safe_git_subcommand,
    parse_git_subcommand,
    pending_command,
    poll_loop,
    read,
    send,
    write_watcher_pid,
)


class TestClassifyCommandSafe:
    """안전한 읽기 전용 명령 및 테스트 코드 실행 검증 자동 승인(approve) 검증."""

    @pytest.mark.parametrize(
        "cmd",
        [
            "git status",
            "git status -s",
            "git status --short --branch",
            "git status -uno",
            "git status --porcelain",
            "git diff",
            "git diff HEAD~1",
            "git diff --stat",
            "git diff --name-only",
            "git diff -p src/main.py",
            "git diff --cached",
            "git diff --staged",
            "git log",
            "git log -n 10 --oneline",
            "git log -5",
            "git log --oneline",
            "git log --graph --decorate",
            "git show HEAD",
            "git show HEAD:src/main.py",
            "git show --stat HEAD",
            "git rev-parse HEAD",
            "git rev-parse --show-toplevel",
            "git rev-parse --git-dir",
            "git rev-parse --verify HEAD",
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
    """파괴적이거나 위험한 명령, git 전역 옵션, 허용 목록 밖 옵션 보류(hold) 검증."""

    @pytest.mark.parametrize(
        "cmd",
        [
            # (a)~(d) Git 전역 옵션 금지 (감사 지적 사항 고정)
            "git -c core.pager=x diff",
            "git -c diff.external=foo diff",
            "git --exec-path=/tmp status",
            "git --git-dir=/tmp/x log",
            "git -C /tmp status",
            "git --work-tree=/tmp diff",
            "git --namespace=foo log",
            "git --super-prefix=bar diff",
            "git --no-pager diff",
            "git --paginate log",
            "git -p status",
            "git --bare status",
            # (f) Git diff 허용 목록 밖 옵션
            "git diff --output=/tmp/out.patch",
            "git diff --ext-diff",
            "git diff --textconv",
            "git diff --no-index /a /b",
            # Git log / status 허용 목록 밖 옵션
            "git log --exec=rm",
            "git status --ignored=invalid_mode",
            # (b) Git 위험/수정 명령
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
            # Antigravity 파일 편집/생성 승인 대화창 (자동 승인하지 않고 보류)
            "Accept this file edit?",
            "Allow creation of this file?",
            "  accept   THIS  file  edit?  ",
            "ALLOW CREATION OF THIS FILE?",
        ],
    )
    def test_hold_commands(self, cmd: str) -> None:
        verdict, reason = classify_command(cmd)
        assert verdict == "hold", f"Expected hold for '{cmd}', got {verdict} ({reason})"


class TestClassifyCommandMetacharacters:
    """셸 메타문자 포함 명령 보류 검증."""

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
    """파싱 실패 및 빈 문자열/알 수 없는 명령 검증."""

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


class TestPytestClassificationDistinct:
    """(g) pytest 및 uv run pytest 가 approve 이면서 읽기 전용과 구분되는지 검증."""

    def test_pytest_and_uv_run_pytest_distinct_category(self) -> None:
        # pytest 는 SAFE_STANDALONE_COMMANDS 에 포함되지 않아야 함
        assert "pytest" not in SAFE_STANDALONE_COMMANDS
        assert "pytest" in SAFE_TEST_COMMANDS
        assert CATEGORY_READ_ONLY != CATEGORY_TEST_EXECUTION

        verdict_pytest, reason_pytest = classify_command("pytest")
        assert verdict_pytest == "approve"
        assert "테스트 코드 실행 검증" in reason_pytest
        assert "읽기 전용" not in reason_pytest

        verdict_pytest_args, reason_pytest_args = classify_command("pytest tests/ -q")
        assert verdict_pytest_args == "approve"
        assert "테스트 코드 실행 검증" in reason_pytest_args

        verdict_uv_pytest, reason_uv_pytest = classify_command("uv run pytest")
        assert verdict_uv_pytest == "approve"
        assert "테스트 코드 실행 검증" in reason_uv_pytest
        assert "읽기 전용" not in reason_uv_pytest

        verdict_ro, reason_ro = classify_command("cat pyproject.toml")
        assert verdict_ro == "approve"
        assert "읽기 전용" in reason_ro


class TestHelperFunctions:
    """보조 파싱 함수 및 pending_command 단위 테스트."""

    def test_parse_git_subcommand(self) -> None:
        subcmd, args = parse_git_subcommand(["diff", "HEAD"])
        assert subcmd == "diff"
        assert args == ["HEAD"]

        # 전역 옵션이 선행되면 None 반환
        subcmd, args = parse_git_subcommand(["-C", "/path/to/repo", "status", "-s"])
        assert subcmd is None
        assert args == []

        subcmd, args = parse_git_subcommand(["--no-pager", "log", "-n", "5"])
        assert subcmd is None
        assert args == []

        subcmd, args = parse_git_subcommand(["--version"])
        assert subcmd is None
        assert args == []

    def test_is_safe_git_subcommand(self) -> None:
        safe, _ = is_safe_git_subcommand("diff", ["HEAD~1", "--stat"])
        assert safe is True

        safe, msg = is_safe_git_subcommand("diff", ["--output=/tmp/leak.patch"])
        assert safe is False
        assert "허용되지 않은" in msg

        safe, _ = is_safe_git_subcommand("log", ["-n", "5", "--oneline"])
        assert safe is True

        safe, _ = is_safe_git_subcommand("log", ["-10"])
        assert safe is True

        safe, _ = is_safe_git_subcommand("status", ["-s", "-uno"])
        assert safe is True

        safe, _ = is_safe_git_subcommand("rev-parse", ["--show-toplevel"])
        assert safe is True

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

    @pytest.mark.parametrize(
        "screen, expected_sig",
        [
            ("Antigravity CLI\nAccept this file edit?\n[Y]es / [N]o", "Accept this file edit?"),
            ("Allow creation of this file?\n[Y/n]", "Allow creation of this file?"),
            ("  accept   THIS\n  file  edit?  ", "Accept this file edit?"),
            ("ALLOW CREATION OF THIS FILE?", "Allow creation of this file?"),
        ],
    )
    def test_pending_command_file_edit_dialog(self, screen: str, expected_sig: str) -> None:
        assert pending_command(screen) == expected_sig


class TestSubprocessInteractionMocks:
    """read, send, poll_loop mock 기반 테스트 (외부 프로세스 실행 방지)."""

    @patch("subprocess.run")
    def test_read_mocked_success(self, mock_run: MagicMock) -> None:
        mock_run.return_value.stdout = "mocked terminal screen output"
        mock_run.return_value.returncode = 0
        out = read("term_123")
        assert out == "mocked terminal screen output"
        mock_run.assert_called_once_with(
            ["orca", "terminal", "read", "--terminal", "term_123"],
            capture_output=True,
            text=True,
            timeout=60,
        )

    @patch("subprocess.run")
    def test_read_mocked_failure_returns_none(self, mock_run: MagicMock) -> None:
        mock_run.return_value.returncode = 1
        mock_run.return_value.stdout = ""
        out = read("term_missing")
        assert out is None

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

    @patch("scripts.orca_auto_approve.time.sleep", side_effect=StopIteration)
    @patch("scripts.orca_auto_approve.send")
    @patch("scripts.orca_auto_approve.read")
    def test_poll_loop_holds_file_edit_dialog(
        self,
        mock_read: MagicMock,
        mock_send: MagicMock,
        mock_sleep: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        mock_read.return_value = "Accept this file edit?\n[Y]es / [N]o"
        with pytest.raises(StopIteration):
            poll_loop(["term_xyz"])
        mock_send.assert_not_called()
        captured = capsys.readouterr()
        assert "[보류]" in captured.out
        assert "파일 편집/생성 승인은 수동 판단 필요" in captured.out

    @patch("scripts.orca_auto_approve.time.sleep")
    @patch("scripts.orca_auto_approve.read")
    def test_poll_loop_terminates_on_consecutive_failures(
        self, mock_read: MagicMock, mock_sleep: MagicMock
    ) -> None:
        """연속 읽기 실패 시 감시 대상에서 제외되고 모든 대상 소진 시 루프가 정상 종료하는지 검증."""
        mock_read.return_value = None
        # max_failures=3 으로 2개 터미널 감시 시 총 6번 호출 후 정상 반환해야 함
        poll_loop(["term_1", "term_2"], max_failures=3)
        assert mock_read.call_count == 6

    @patch("scripts.orca_auto_approve.time.sleep")
    @patch("scripts.orca_auto_approve.read")
    def test_poll_loop_cleans_up_pid_file_on_exit(
        self,
        mock_read: MagicMock,
        mock_sleep: MagicMock,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """poll_loop 종료 시 감시 대상 터미널의 PID 파일이 자동 정리되는지 검증."""
        monkeypatch.setattr("tempfile.gettempdir", lambda: str(tmp_path))
        pid_path = get_watcher_pid_path("term_clean")
        write_watcher_pid(pid_path, 98765)
        assert pid_path.exists()

        mock_read.return_value = None
        poll_loop(["term_clean"], max_failures=1)
        assert not pid_path.exists()

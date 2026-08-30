"""scripts/orca_auto_approve.py 에 대한 단위 테스트."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts.orca_auto_approve import (
    CATEGORY_READ_ONLY,
    CATEGORY_TEST_EXECUTION,
    DANGEROUS_PROMPT_PATTERNS,
    MAX_PROMPT_REPEATS,
    SAFE_NON_COMMAND_PROMPTS,
    SAFE_STANDALONE_COMMANDS,
    SAFE_TEST_COMMANDS,
    check_dangerous_prompt,
    classify_command,
    get_watcher_pid_path,
    is_safe_git_branch,
    is_safe_git_subcommand,
    match_safe_prompt,
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
            # (c) Python 실행 중 셸로 빠져나가거나 파일을 지우는 것
            "python3 -c \"import os; os.system('rm -rf /')\"",
            'python3 -c "import subprocess"',
            "python3 -c \"import shutil; shutil.rmtree('/')\"",
            "python3 /etc/evil.py",
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
    """합성 명령은 구간별로 판정합니다.

    2026-08-30 이전에는 셸 메타문자가 하나라도 있으면 통째로 보류했습니다. 그 결과
    워커의 조사와 검증 명령이 거의 전부 보류에 걸려 사람이 손으로 풀어 줄 때까지
    작업이 멈췄습니다. 이제 파이프라인 구간을 나눠 각각을 기존 규칙으로 판정하며,
    모든 구간이 승인일 때만 승인합니다. 판정이 느슨해진 것이 아니라 정밀해졌습니다.
    """

    @pytest.mark.parametrize(
        "cmd",
        [
            # 되돌릴 수 없는 셸 기능은 분해해도 안전을 보장할 수 없습니다.
            "echo `whoami`",
            "echo $(whoami)",
            "echo $((1 + 1))",
            # 한 구간이라도 보류면 전체가 보류입니다.
            "git status\nrm -rf /",
            "ls | git push origin main",
            "cat x.md && docker compose down",
            "find . -exec rm {} \\;",
            # 리다이렉트 대상이 워크트리 밖이거나 비밀 파일이면 보류합니다.
            "echo x > /etc/passwd",
            "echo x > ../outside.txt",
            "cat .env",
        ],
    )
    def test_unsafe_composites_hold(self, cmd: str) -> None:
        verdict, _ = classify_command(cmd)
        assert verdict == "hold"

    @pytest.mark.parametrize(
        "cmd",
        [
            "ls | grep foo",
            "cat file.txt > output.txt",
            "cat file.txt >> output.txt",
            "ls; echo 1",
            "pytest && echo done",
            "pytest || echo fail",
            "git diff\recho 1",
            "grep -n lwlt src/ml/dataset.py | head -20",
        ],
    )
    def test_safe_composites_approve(self, cmd: str) -> None:
        """모든 구간이 안전하면 승인합니다. 이것이 워커 대기를 없앤 변경의 핵심입니다."""
        verdict, _ = classify_command(cmd)
        assert verdict == "approve"

    def test_every_segment_is_judged(self) -> None:
        """앞 구간이 안전해도 뒤 구간이 위험하면 보류합니다."""
        assert classify_command("ls && rm -rf /")[0] == "hold"
        assert classify_command("git status | git push")[0] == "hold"

    def test_newline_and_carriage_return_are_separators(self) -> None:
        """개행과 캐리지 리턴을 구분자로 다루지 않으면 숨은 명령이 승인됩니다."""
        assert classify_command("git diff\nrm -rf /")[0] == "hold"
        assert classify_command("git diff\rrm -rf /")[0] == "hold"


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
        # 따옴표가 닫히지 않으면 구간을 나눌 수 없으므로 분해 단계에서 먼저 걸립니다.
        assert "따옴표" in reason or "명령 파싱 실패" in reason

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


class TestNonCommandPromptWhitelist:
    """비명령 프롬프트 화이트리스트 탐색 및 안전성 단위 검증."""

    def test_cli_satisfaction_survey_detected(self) -> None:
        """관측된 CLI 만족도 설문 화면이 정확히 감지되고 '0'(Skip) 응답이 지정되어 있는지 검증."""
        screen = (
            "How's the CLI experience so far? Help us improve:\n"
            "[1] Good  [2] Fine  [3] Bad  [0] Skip"
        )
        matched = match_safe_prompt(screen)
        assert matched is not None
        assert matched["id"] == "cli_satisfaction_survey"
        assert matched["response"] == "0"

    @pytest.mark.parametrize(
        "screen",
        [
            "How's the CLI experience so far?\n[1] Good [2] Fine [3] Bad [0] Skip",
            "  HOW'S THE CLI EXPERIENCE SO FAR?  \n  [1] Good  [0] SKIP  ",
            "CLI tool running\nHow's the CLI experience so far? Help us improve:\n[1] Good [2] Fine [3] Bad [0] Skip\nWaiting for input...",
        ],
    )
    def test_cli_satisfaction_survey_variations(self, screen: str) -> None:
        """공백 및 대소문자 변형에서도 설문 화면이 정상 인식되는지 검증."""
        matched = match_safe_prompt(screen)
        assert matched is not None
        assert matched["id"] == "cli_satisfaction_survey"
        assert matched["response"] == "0"

    def test_safe_prompt_constants_validity(self) -> None:
        """화이트리스트 상수 정의가 필수 키(id, keywords, response, description)를 모두 갖추고 있는지 검증."""
        assert len(SAFE_NON_COMMAND_PROMPTS) > 0
        for item in SAFE_NON_COMMAND_PROMPTS:
            assert item["id"]
            assert len(item["keywords"]) > 0
            assert item["response"] != ""
            assert item["description"]

    @pytest.mark.parametrize(
        "screen",
        [
            "Do you want to enable experimental features? [y/n]",
            "Would you like to install recommended extensions? [Y/n]",
            "Send anonymous usage telemetry? [y/N]",
            "Select language: [1] Python [2] Rust [3] Go",
            "Press Enter to continue...",
            "Random terminal message without any prompt structure",
        ],
    )
    def test_unlisted_prompts_return_none(self, screen: str) -> None:
        """화이트리스트에 등록되지 않은 임의의 프롬프트는 안전하게 None을 반환(fail-closed)하는지 검증."""
        assert match_safe_prompt(screen) is None


class TestNonCommandPromptDangerous:
    """되돌리기 어렵거나 외부에 영향을 주는 위험 프롬프트 보류 검증."""

    def test_dangerous_prompt_constants_validity(self) -> None:
        """위험 프롬프트 패턴 상수가 라벨과 컴파일된 정규식을 정상 포함하는지 검증."""
        assert len(DANGEROUS_PROMPT_PATTERNS) > 0
        for label, pattern in DANGEROUS_PROMPT_PATTERNS:
            assert label
            assert hasattr(pattern, "search")

    @pytest.mark.parametrize(
        "screen, expected_label",
        [
            ("Are you sure you want to delete file /tmp/data.csv? [y/N]", "파일 삭제"),
            ("Remove directory /var/data? [yes/no]", "파일 삭제"),
            ("Enter password for user:", "자격증명/인증"),
            ("Please enter your API Key:", "자격증명/인증"),
            ("Confirm payment of $50.00 for subscription? [y/N]", "결제/과금"),
            ("Deploy to production cluster? [y/N]", "원격 반영/배포"),
            ("Publish package to npm registry? [y/N]", "원격 반영/배포"),
            ("Enter sudo command to continue:", "권한 상승"),
            ("Run as administrator? [Y/n]", "권한 상승"),
        ],
    )
    def test_dangerous_prompts_detected_and_not_in_safe_whitelist(
        self, screen: str, expected_label: str
    ) -> None:
        """위험 프롬프트가 감지되고 화이트리스트에는 매칭되지 않는지 검증."""
        danger_reason = check_dangerous_prompt(screen)
        assert danger_reason is not None
        assert expected_label in danger_reason
        assert match_safe_prompt(screen) is None


class TestPollLoopNonCommandPrompts:
    """poll_loop 에서의 비명령 프롬프트 자동 해제, 위험 보류 및 반복 상한 검증."""

    @patch("scripts.orca_auto_approve.time.sleep", side_effect=StopIteration)
    @patch("scripts.orca_auto_approve.send")
    @patch("scripts.orca_auto_approve.read")
    def test_poll_loop_answers_satisfaction_survey(
        self,
        mock_read: MagicMock,
        mock_send: MagicMock,
        mock_sleep: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """(a) CLI 만족도 설문 화면 인식 시 '0' 건너뛰기를 전송하고 자동 해제 로그를 남기는지 검증."""
        mock_read.return_value = (
            "How's the CLI experience so far? Help us improve:\n"
            "[1] Good  [2] Fine  [3] Bad  [0] Skip"
        )
        with pytest.raises(StopIteration):
            poll_loop(["term_survey"])

        mock_send.assert_called_once_with("term_survey", "0")
        captured = capsys.readouterr()
        assert "[자동해제]" in captured.out
        assert "cli_satisfaction_survey" in captured.out
        assert "0" in captured.out

    @patch("scripts.orca_auto_approve.time.sleep", side_effect=StopIteration)
    @patch("scripts.orca_auto_approve.send")
    @patch("scripts.orca_auto_approve.read")
    def test_poll_loop_ignores_unlisted_prompt(
        self,
        mock_read: MagicMock,
        mock_send: MagicMock,
        mock_sleep: MagicMock,
    ) -> None:
        """(b) 화이트리스트에 없는 확인 화면에는 아무것도 전송하지 않는지 검증."""
        mock_read.return_value = "Do you want to enable experimental features? [y/n]"
        with pytest.raises(StopIteration):
            poll_loop(["term_unlisted"])

        mock_send.assert_not_called()

    @patch("scripts.orca_auto_approve.time.sleep", side_effect=StopIteration)
    @patch("scripts.orca_auto_approve.send")
    @patch("scripts.orca_auto_approve.read")
    def test_poll_loop_holds_dangerous_prompt(
        self,
        mock_read: MagicMock,
        mock_send: MagicMock,
        mock_sleep: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """(c) 파일 삭제·자격증명 등 위험 프롬프트에는 응답하지 않고 보류 로그를 남기는지 검증."""
        mock_read.return_value = "Are you sure you want to delete file database.db? [y/N]"
        with pytest.raises(StopIteration):
            poll_loop(["term_danger"])

        mock_send.assert_not_called()
        captured = capsys.readouterr()
        assert "[보류]" in captured.out
        assert "위험 프롬프트 감지" in captured.out

    @patch("scripts.orca_auto_approve.time.sleep")
    @patch("scripts.orca_auto_approve.send")
    @patch("scripts.orca_auto_approve.read")
    def test_poll_loop_repeat_limit_stops_answering(
        self,
        mock_read: MagicMock,
        mock_send: MagicMock,
        mock_sleep: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """(d) 동일 비명령 프롬프트가 반복될 때 MAX_PROMPT_REPEATS(3회)까지만 응답하고 이후 중단되는지 검증."""
        mock_read.return_value = (
            "How's the CLI experience so far? Help us improve:\n"
            "[1] Good  [2] Fine  [3] Bad  [0] Skip"
        )
        sleep_count = 0

        def fake_sleep(sec: float) -> None:
            nonlocal sleep_count
            sleep_count += 1
            # 반복 3회(각 2회 sleep: send 후 2s + 루프 말단 8s) + 상한 초과 2회(각 1회 sleep: 루프 말단 8s)
            if sleep_count >= 8:
                raise StopIteration

        mock_sleep.side_effect = fake_sleep

        with pytest.raises(StopIteration):
            poll_loop(["term_repeat"])

        # 3회까지만 send 호출되어야 함
        assert mock_send.call_count == MAX_PROMPT_REPEATS
        assert mock_send.call_args_list == [
            (("term_repeat", "0"),),
            (("term_repeat", "0"),),
            (("term_repeat", "0"),),
        ]
        captured = capsys.readouterr()
        assert "[경고]" in captured.out
        assert f"반복 상한({MAX_PROMPT_REPEATS}회) 초과" in captured.out
        assert "사람 개입 필요" in captured.out

    @patch("scripts.orca_auto_approve.time.sleep")
    @patch("scripts.orca_auto_approve.send")
    @patch("scripts.orca_auto_approve.read")
    def test_poll_loop_resets_count_when_prompt_cleared(
        self,
        mock_read: MagicMock,
        mock_send: MagicMock,
        mock_sleep: MagicMock,
    ) -> None:
        """프롬프트 해제 후 일반 화면으로 전환되면 카운트가 정상 초기화되는지 검증."""
        survey_screen = (
            "How's the CLI experience so far? Help us improve:\n"
            "[1] Good  [2] Fine  [3] Bad  [0] Skip"
        )
        normal_screen = "Build completed successfully."

        # 순서: 설문(1회응답) -> 일반화면(초기화) -> 설문(1회응답)
        screens = [survey_screen, normal_screen, survey_screen]
        screen_idx = 0

        def fake_read(handle: str) -> str:
            nonlocal screen_idx
            idx = min(screen_idx, len(screens) - 1)
            return screens[idx]

        def fake_sleep(sec: float) -> None:
            nonlocal screen_idx
            screen_idx += 1
            if screen_idx >= 3:
                raise StopIteration

        mock_read.side_effect = fake_read
        mock_sleep.side_effect = fake_sleep

        with pytest.raises(StopIteration):
            poll_loop(["term_reset"])

        # 2번의 설문 노출에 대해 각각 응답하여 총 2회 전송
        assert mock_send.call_count == 2


class TestPythonExecutionPolicy:
    """python 실행 허용 경계 검증.

    워커의 조사와 검증은 거의 전부 python 으로 이뤄집니다. 무조건 보류하면 작업이
    멈추므로(2026-08-30 다수 발생) 셸로 빠져나가거나 파일을 지우는 토큰이 없을 때만
    승인합니다.
    """

    @pytest.mark.parametrize(
        "cmd",
        [
            "python3 scripts/validate_agent_rules.py --quiet",
            ".venv/bin/python -m pytest tests/test_x.py -q",
            'python3 -c "import json; print(1)"',
            "python3 /tmp/probe.py",
        ],
    )
    def test_safe_python_approves(self, cmd: str) -> None:
        assert classify_command(cmd)[0] == "approve"

    @pytest.mark.parametrize(
        "cmd",
        [
            "python3 -c \"import os; os.system('ls')\"",
            "python3 -c \"import subprocess; subprocess.run(['ls'])\"",
            "python3 -c \"import shutil; shutil.rmtree('x')\"",
            "python3 -c \"import os; os.remove('x')\"",
            'python3 -c "eval(payload)"',
            'python3 -c "exec(payload)"',
        ],
    )
    def test_escaping_python_holds(self, cmd: str) -> None:
        verdict, reason = classify_command(cmd)
        assert verdict == "hold"
        assert "탈출" in reason or "보류" in reason


class TestSecretPathPolicy:
    """비밀 파일은 읽기 전용 도구로도 열지 않습니다. AGENTS.md 7장."""

    @pytest.mark.parametrize(
        "cmd",
        [
            "cat .env",
            "head -5 .env",
            "grep SECRET .env",
            "cat ~/.ssh/id_rsa",
            "cat config/secrets.yaml",
        ],
    )
    def test_secret_paths_hold(self, cmd: str) -> None:
        verdict, reason = classify_command(cmd)
        assert verdict == "hold"
        assert "비밀" in reason or "보류" in reason

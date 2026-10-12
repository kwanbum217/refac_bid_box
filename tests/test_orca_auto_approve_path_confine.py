"""작업 트리 밖 경로를 가리키는 읽기 전용 명령의 보류 판정 단위 테스트.

2026-10-12 에 리뷰어가 `find ~` 와 `find /` 로 작업 트리 밖을 뒤졌는데도 감시기가
승인했습니다. 판정 범위를 워커 작업 트리 안으로 좁혀, 작업 트리 밖 경로를 인자로
받는 명령은 사람 승인으로 돌립니다. 시스템 임시 디렉터리는 예외입니다.

경로 인자의 셸 변수 확장(`cat $HOME/.netrc`)도 정적으로 작업 트리 안팎을 가릴 수
없으므로 보류합니다. 다만 루프 변수는 루프가 값을 정하므로 본문에서 보류하지
않고, grep 패턴의 정규식 앵커($)도 확장이 아니므로 승인을 유지합니다.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts.orca_auto_approve import (
    check_path_argument,
    classify_command,
    poll_loop,
    resolve_workspace_root,
)


@pytest.fixture
def worktree(tmp_path: Path) -> Path:
    """작업 트리 루트로 쓸 실제 디렉터리를 만듭니다."""
    root = tmp_path / "worktree"
    root.mkdir()
    (root / "README.md").write_text("# 문서\n", encoding="utf-8")
    return root.resolve()


class TestOutsidePathsAreHeld:
    """실측에서 승인되던 작업 트리 밖 명령이 모두 보류로 바뀌어야 합니다."""

    @pytest.mark.parametrize(
        "cmd",
        [
            "find ~ -maxdepth 3 -name .orca",
            "find / -name x",
            "cat /etc/hosts",
            "ls ~/.ssh",
            "cat ../../other/file",
        ],
    )
    def test_measured_commands_are_held(self, cmd: str, worktree: Path) -> None:
        verdict, reason = classify_command(cmd, workspace_root=worktree)
        assert verdict == "hold", f"'{cmd}' 판정이 {verdict}입니다: {reason}"
        assert "작업 트리 밖 경로" in reason

    @pytest.mark.parametrize(
        "cmd",
        [
            "cat /etc/hosts",
            "ls ~/.ssh",
            "cat ../outside/secret.txt",
        ],
    )
    def test_missing_workspace_root_fails_closed(self, cmd: str) -> None:
        """작업 트리 루트를 알 수 없으면 절대 경로와 홈과 상위 참조를 보류합니다."""
        verdict, reason = classify_command(cmd)
        assert verdict == "hold", f"'{cmd}' 판정이 {verdict}입니다: {reason}"
        assert "작업 트리 밖 경로" in reason

    def test_parent_reference_escape_is_held(self, worktree: Path) -> None:
        verdict, reason = classify_command("cat ../outside/secret.txt", workspace_root=worktree)
        assert verdict == "hold"
        assert "작업 트리 밖 경로" in reason

    def test_symlink_escape_is_held(self, tmp_path: Path) -> None:
        """작업 트리 안 심볼릭 링크가 밖을 가리키면 링크 우회로 보고 보류합니다."""
        root = tmp_path / "worktree"
        root.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "secret.txt").write_text("비밀\n", encoding="utf-8")
        (root / "link").symlink_to(outside, target_is_directory=True)

        resolved_root = root.resolve()
        verdict, reason = classify_command("cat link/secret.txt", workspace_root=resolved_root)
        assert verdict == "hold"
        assert "작업 트리 밖 경로" in reason

        # 같은 작업 트리 안 실경로는 계속 승인합니다.
        (root / "inside.txt").write_text("안\n", encoding="utf-8")
        assert classify_command("cat inside.txt", workspace_root=resolved_root)[0] == "approve"

    def test_outside_path_inside_command_substitution_is_held(self, worktree: Path) -> None:
        verdict, reason = classify_command("cat $(echo /etc/hosts)", workspace_root=worktree)
        assert verdict == "hold"
        assert "작업 트리 밖 경로" in reason

    def test_absolute_path_outside_worktree_is_held(self, worktree: Path) -> None:
        verdict, reason = classify_command("/bin/cat /etc/hosts", workspace_root=worktree)
        assert verdict == "hold"
        assert "작업 트리 밖 경로" in reason


class TestVariableExpansionInPathArguments:
    """경로 인자의 셸 변수 확장은 정적으로 해석할 수 없으므로 보류합니다.

    이전 시도에서 `cat $HOME/.netrc` 같은 명령이 작업 트리 안 상대 경로로
    해석되어 승인되었습니다. 변수는 실행 시점에 정해지므로 작업 트리 밖을
    가리킬 수 있어 사람 승인으로 돌립니다. 옵션 플래그가 아닌 비경로 인자
    (grep 패턴의 정규식 앵커)의 $ 는 확장이 아니므로 승인을 유지합니다.
    """

    @pytest.mark.parametrize(
        "cmd",
        [
            "cat $HOME/.netrc",
            "cat ${HOME}/.netrc",
            'cat "$HOME"/x',
            "cat $PWD/../x",
            "ls $TMPDIR",
            "cat ./$X",
        ],
    )
    def test_expanded_path_arguments_are_held(self, cmd: str, worktree: Path) -> None:
        verdict, reason = classify_command(cmd, workspace_root=worktree)
        assert verdict == "hold", f"'{cmd}' 판정이 {verdict}입니다: {reason}"
        assert "경로 인자에 변수 확장" in reason

    @pytest.mark.parametrize(
        "cmd",
        [
            "cat $HOME/.netrc",
            "cat ${HOME}/.netrc",
            'cat "$HOME"/x',
            "cat $PWD/../x",
            "ls $TMPDIR",
            "cat ./$X",
        ],
    )
    def test_expanded_path_arguments_are_held_without_workspace_root(self, cmd: str) -> None:
        verdict, reason = classify_command(cmd)
        assert verdict == "hold", f"'{cmd}' 판정이 {verdict}입니다: {reason}"
        assert "경로 인자에 변수 확장" in reason

    def test_regex_anchor_dollar_is_not_expansion(self, worktree: Path) -> None:
        """grep 패턴의 $ 는 정규식 앵커이므로 확장으로 보지 않습니다."""
        verdict, reason = classify_command("grep -n 'foo$' README.md", workspace_root=worktree)
        assert verdict == "approve", f"판정이 {verdict}입니다: {reason}"

    def test_loop_variable_path_arguments_are_approved(self, worktree: Path) -> None:
        """루프 변수는 루프가 값을 정하므로 본문에서 보류하지 않습니다."""
        for cmd in (
            "for f in src/*.py; do cat $f; done",
            "while read h; do git show --stat $h; done",
        ):
            verdict, reason = classify_command(cmd, workspace_root=worktree)
            assert verdict == "approve", f"'{cmd}' 판정이 {verdict}입니다: {reason}"

    def test_unbound_variable_inside_loop_is_held(self, worktree: Path) -> None:
        """루프가 묶지 않은 변수는 루프 안에서도 해석 불가이므로 보류합니다."""
        verdict, reason = classify_command(
            "for f in src/*.py; do cat $HOME/.netrc; done", workspace_root=worktree
        )
        assert verdict == "hold", f"판정이 {verdict}입니다: {reason}"
        assert "경로 인자에 변수 확장" in reason


class TestExitCodeSpecialParameter:
    """직전 명령 종료 코드($?)는 경로가 될 수 없으므로 확장으로 보지 않습니다.

    2026-10-13 cmd 워커가 `uv run pytest ... ; echo "EXIT=$?"` 형태의 검증 명령을
    승인 대화창에서 붙잡혀 멈췄습니다. 원인은 check_variable_expansion 이 $? 를
    이름형 변수처럼 보류한 것입니다. $? 와 ${?} 만 통과시키고 다른 특수 매개변수와
    이름형 변수 확장은 종전대로 보류합니다.
    """

    STALLED_COMMAND = 'uv run pytest tests/test_x.py -q 2>&1 | tail -20; echo "EXIT=$?"'

    def test_stalled_verification_command_is_approved(self, worktree: Path) -> None:
        verdict, reason = classify_command(self.STALLED_COMMAND, workspace_root=worktree)
        assert verdict == "approve", f"판정이 {verdict}입니다: {reason}"

    def test_stalled_verification_command_is_approved_without_workspace_root(self) -> None:
        verdict, reason = classify_command(self.STALLED_COMMAND)
        assert verdict == "approve", f"판정이 {verdict}입니다: {reason}"

    @pytest.mark.parametrize("cmd", ['echo "EXIT=$?"', "echo ${?}", "echo $?"])
    def test_exit_code_expansion_is_approved(self, cmd: str, worktree: Path) -> None:
        verdict, reason = classify_command(cmd, workspace_root=worktree)
        assert verdict == "approve", f"'{cmd}' 판정이 {verdict}입니다: {reason}"

    @pytest.mark.parametrize("cmd", ['echo "$?$HOME"', "cat $HOME/x"])
    def test_exit_code_mixed_with_name_expansion_is_held(self, cmd: str, worktree: Path) -> None:
        verdict, reason = classify_command(cmd, workspace_root=worktree)
        assert verdict == "hold", f"'{cmd}' 판정이 {verdict}입니다: {reason}"
        assert "경로 인자에 변수 확장" in reason

    @pytest.mark.parametrize("cmd", ["echo $#", "echo $$"])
    def test_other_special_parameters_are_held(self, cmd: str, worktree: Path) -> None:
        verdict, reason = classify_command(cmd, workspace_root=worktree)
        assert verdict == "hold", f"'{cmd}' 판정이 {verdict}입니다: {reason}"
        assert "경로 인자에 변수 확장" in reason


class TestInsidePathsAreApproved:
    """작업 트리 안 상대 경로와 임시 디렉터리는 계속 승인해야 합니다."""

    @pytest.mark.parametrize(
        "cmd",
        [
            "find . -name x",
            "cat README.md",
            "ls src",
            "grep -n foo src/main.py",
            "find src -type f",
        ],
    )
    def test_inside_relative_commands_are_approved(self, cmd: str, worktree: Path) -> None:
        verdict, reason = classify_command(cmd, workspace_root=worktree)
        assert verdict == "approve", f"'{cmd}' 판정이 {verdict}입니다: {reason}"

    @pytest.mark.parametrize(
        "cmd",
        [
            "cat /tmp/orca_path_probe.txt",
            "ls /private/tmp",
            "wc -l /tmp/a.log",
        ],
    )
    def test_system_temp_paths_are_approved(self, cmd: str, worktree: Path) -> None:
        verdict, reason = classify_command(cmd, workspace_root=worktree)
        assert verdict == "approve", f"'{cmd}' 판정이 {verdict}입니다: {reason}"

    def test_inside_command_substitution_is_approved(self, worktree: Path) -> None:
        assert classify_command("cat $(echo README.md)", workspace_root=worktree)[0] == "approve"

    def test_relative_commands_stay_approved_without_workspace_root(self) -> None:
        assert classify_command("cat README.md")[0] == "approve"
        assert classify_command("find . -name x")[0] == "approve"

    def test_inside_absolute_path_is_approved(self, worktree: Path) -> None:
        target = worktree / "README.md"
        verdict, reason = classify_command(f"cat {target}", workspace_root=worktree)
        assert verdict == "approve", f"판정이 {verdict}입니다: {reason}"


class TestPathArgumentHelper:
    """경로 인자 판정 보조 함수의 경계를 고정합니다."""

    def test_option_flags_are_skipped(self, worktree: Path) -> None:
        assert check_path_argument("--name-only", worktree) is None
        assert check_path_argument("-", worktree) is None

    def test_tilde_is_always_held(self, worktree: Path) -> None:
        assert check_path_argument("~", worktree) is not None
        assert check_path_argument("~/x", worktree) is not None

    def test_temp_is_allowed(self, worktree: Path) -> None:
        assert check_path_argument("/tmp/x", worktree) is None

    def test_outside_absolute_is_held(self, worktree: Path) -> None:
        assert check_path_argument("/etc/hosts", worktree) is not None

    def test_inside_relative_is_allowed(self, worktree: Path) -> None:
        assert check_path_argument("src/main.py", worktree) is None


class TestWorkspaceRootResolution:
    """orca terminal show 결과에서 작업 트리 루트를 뽑아내는 계약."""

    def test_parses_worktree_path(self, worktree: Path) -> None:
        payload = json.dumps({"ok": True, "result": {"terminal": {"worktreePath": str(worktree)}}})
        with patch("scripts.orca_auto_approve.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=payload)
            assert resolve_workspace_root("term_z") == worktree

    def test_parses_cwd_fallback(self, worktree: Path) -> None:
        payload = json.dumps({"ok": True, "result": {"terminal": {"cwd": str(worktree)}}})
        with patch("scripts.orca_auto_approve.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=payload)
            assert resolve_workspace_root("term_z") == worktree

    def test_returns_none_when_unresolved(self) -> None:
        with patch("scripts.orca_auto_approve.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="")
            assert resolve_workspace_root("term_z") is None

    def test_returns_none_on_invalid_json(self) -> None:
        with patch("scripts.orca_auto_approve.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="not-json")
            assert resolve_workspace_root("term_z") is None


class TestPollLoopPathConfine:
    """poll_loop 이 터미널 작업 트리 루트를 반영해 승인 여부를 가르는지 검증합니다."""

    OUTSIDE_SCREEN = (
        "Command Code needs to execute cat /etc/hosts.\n\nPress [ctrl+e] to explain this command\n"
    )
    INSIDE_SCREEN = (
        "Command Code needs to execute cat README.md.\n\nPress [ctrl+e] to explain this command\n"
    )

    def _run(self, screen: str) -> MagicMock:
        with (
            patch("scripts.orca_auto_approve.read", return_value=screen),
            patch("scripts.orca_auto_approve.send") as mock_send,
            patch("scripts.orca_auto_approve.time.sleep", side_effect=StopIteration),
            pytest.raises(StopIteration),
        ):
            poll_loop(["term_confine"])
        return mock_send

    def test_outside_path_is_not_answered(
        self, worktree: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with patch("scripts.orca_auto_approve.resolve_workspace_root", return_value=worktree):
            mock_send = self._run(self.OUTSIDE_SCREEN)
        mock_send.assert_not_called()
        assert "작업 트리 밖 경로" in capsys.readouterr().out

    def test_inside_path_is_approved(self, worktree: Path) -> None:
        with patch("scripts.orca_auto_approve.resolve_workspace_root", return_value=worktree):
            mock_send = self._run(self.INSIDE_SCREEN)
        # cmd 대화창은 1회 승인(1번)을 보냅니다. 2번은 상시 허용이라 정책을 넓힙니다.
        mock_send.assert_called_once_with("term_confine", "1")

    def test_unresolved_root_holds_absolute_path(self, capsys: pytest.CaptureFixture[str]) -> None:
        with patch("scripts.orca_auto_approve.resolve_workspace_root", return_value=None):
            mock_send = self._run(self.OUTSIDE_SCREEN)
        mock_send.assert_not_called()
        assert "작업 트리 밖 경로" in capsys.readouterr().out

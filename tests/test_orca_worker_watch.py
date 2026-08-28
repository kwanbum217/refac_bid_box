"""scripts/orca_worker_watch.py 회귀 테스트.

감시 도구가 조용히 망가지면 워커 차단을 아무도 발견하지 못한다. 특히
스크롤백에 남은 옛 대화창을 현재 차단으로 오판하는 회귀를 고정한다.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from scripts import orca_worker_watch as watch


@pytest.mark.parametrize(
    "needle, expected_fragment",
    [
        ("Do you trust the contents of this project?", "신뢰"),
        ("▶ [a] Trust this workspace", "신뢰"),
        ("Welcome to the Antigravity CLI. You are currently not signed in.", "인증"),
        ("How's the CLI experience so far? Help us improve:", "설문"),
        ("Accept this file edit?", "파일 편집"),
        ("Allow creation of this file?", "파일 생성"),
        ("  ACCEPT   this\n  FILE edit?  ", "파일 편집"),
        ("ALLOW  creation OF this file?", "파일 생성"),
        ("Allow this", "도구 실행 권한"),
        ("Do you want to proceed?", "진행 확인"),
    ],
)
def test_detect_block_finds_known_signals(needle: str, expected_fragment: str) -> None:
    found = watch.detect_block(needle)
    assert found is not None
    reason, fix, kind = found
    assert expected_fragment in reason
    assert fix
    assert kind == "prompt"


def test_file_edit_signals_have_shift_tab_fix() -> None:
    for sig in watch.FILE_EDIT_DIALOG_SIGNALS:
        found = watch.detect_block(sig)
        assert found is not None
        _reason, fix, kind = found
        assert "shift+tab" in fix
        assert kind == "prompt"


def test_detect_block_returns_none_for_working_screen() -> None:
    screen = "\n".join(
        [
            "  → Add a follow-up",
            "  Composer 2.5 · 34%",
            "  ~/orca/workspaces/refac_bid_box/orca-w2-mypy-debt",
        ]
    )
    assert watch.detect_block(screen) is None


def test_tail_scope_prevents_stale_dialog_false_positive() -> None:
    """이미 승인하고 지나간 대화창이 위쪽에 남아 있어도 차단으로 읽지 않는다."""
    stale = "Do you trust the contents of this project?"
    working_tail = ["작업 중" for _ in range(watch.TAIL_LINES)]
    whole = "\n".join([stale, *working_tail])
    tail = "\n".join(whole.splitlines()[-watch.TAIL_LINES :])
    assert watch.detect_block(whole) is not None, "전체를 보면 잡힌다 (오판의 원인)"
    assert watch.detect_block(tail) is None, "끝부분만 보면 잡히지 않아야 한다"


def test_worker_state_blocked_flag_and_payload() -> None:
    state = watch.WorkerState(name="orca-x", path="/tmp/orca-x", branch="b", commits=0, dirty=0)
    assert state.blocked is False
    state.blocked_reason = "테스트 차단"
    state.blocked_fix = "조치"
    state.blocked_kind = "failure"
    assert state.blocked is True
    payload = state.as_dict()
    assert payload["blocked"] is True
    assert payload["blocked_kind"] == "failure"
    assert payload["blocked_reason"] == "테스트 차단"
    assert set(payload) >= {"name", "branch", "commits", "dirty", "terminal", "notes"}


def test_block_signals_all_have_reason_and_fix() -> None:
    assert watch.BLOCK_SIGNALS
    for needle, reason, fix, kind in watch.BLOCK_SIGNALS:
        assert needle
        assert reason
        assert fix
        assert kind in {"prompt", "failure"}


def test_main_exit_code_blocked_returns_1() -> None:
    blocked_state = watch.WorkerState(
        name="orca-w1",
        path="/tmp/w1",
        branch="b1",
        commits=0,
        dirty=0,
        terminal="term_1",
        blocked_reason="Antigravity 파일 편집 승인 대화창",
        blocked_fix="화면을 읽고 판단",
    )
    with patch("scripts.orca_worker_watch.collect", return_value=[blocked_state]):
        exit_code = watch.main([])
        assert exit_code == 1


def test_main_exit_code_clean_returns_0() -> None:
    clean_state = watch.WorkerState(
        name="orca-w1",
        path="/tmp/w1",
        branch="b1",
        commits=2,
        dirty=1,
        terminal="term_1",
    )
    with patch("scripts.orca_worker_watch.collect", return_value=[clean_state]):
        exit_code = watch.main([])
        assert exit_code == 0


def test_collect_adds_advice_note_on_blocked() -> None:
    fake_worktrees = [("w1", "/tmp/w1", "feature")]
    fake_terminals = {"/tmp/w1": {"handle": "term_123"}}
    with (
        patch("scripts.orca_worker_watch.list_worktrees", return_value=fake_worktrees),
        patch("scripts.orca_worker_watch.worktree_progress", return_value=(0, 0)),
        patch("scripts.orca_worker_watch.terminal_map", return_value=fake_terminals),
        patch(
            "scripts.orca_worker_watch.terminal_tail", return_value="Accept this file edit?\n[Y/n]"
        ),
    ):
        states = watch.collect(watch.Path("/tmp/repo"), "main")
        assert len(states) == 1
        assert states[0].blocked is True
        assert states[0].blocked_kind == "prompt"
        assert "파일 편집" in (states[0].blocked_reason or "")
        assert any("터미널을 직접 확인" in note for note in states[0].notes)


@pytest.mark.parametrize(
    "screen, expected_reason_fragment",
    [
        ("Error: network error while streaming response", "네트워크"),
        ("rate limit exceeded, retry after 60s", "rate limit"),
        ("HTTP 401 unauthorized", "인증"),
        ("token expired at 2026-08-28", "토큰"),
        ("model not found: gemini-foo", "모델"),
        ("HTTP 429 Too Many Requests", "rate limit"),
        ("upstream returned status 502", "502"),
    ],
)
def test_detect_block_classifies_failure_signals(
    screen: str, expected_reason_fragment: str
) -> None:
    found = watch.detect_block(screen)
    assert found is not None
    reason, fix, kind = found
    assert kind == "failure"
    assert expected_reason_fragment in reason
    assert "재전송" in fix or "재기동" in fix
    assert "terminal send" not in fix


def test_detect_block_failure_takes_priority_over_prompt() -> None:
    screen = "\n".join(
        [
            "How's the CLI experience so far? Help us improve:",
            "Error: network error while streaming response",
        ]
    )
    found = watch.detect_block(screen)
    assert found is not None
    reason, _fix, kind = found
    assert kind == "failure"
    assert "네트워크" in reason


@pytest.mark.parametrize(
    "screen",
    [
        "2537 passed, 6 skipped in 429.31s",
        "Editing 7.59k tokens 502 lines changed",
        "tests/test_foo.py:429: assert x",
        "Read(scripts/orca_taskctl.py) 1502 lines",
    ],
)
def test_detect_block_ignores_bare_status_code_substrings(screen: str) -> None:
    assert watch.detect_block(screen) is None


def test_detect_block_contextual_status_codes_still_match() -> None:
    cases = [
        ("HTTP 429 Too Many Requests", "rate limit"),
        ("error 429: rate limit exceeded", "rate limit"),
        ("received status 429 from upstream", "rate limit"),
        ("HTTP 502 Bad Gateway", "502"),
        ("error 502 while contacting model", "502"),
        ("upstream returned status code 502", "502"),
    ]
    for screen, fragment in cases:
        found = watch.detect_block(screen)
        assert found is not None, screen
        reason, _fix, kind = found
        assert kind == "failure"
        assert fragment in reason


def test_existing_prompt_signals_keep_reason_and_fix() -> None:
    expected: dict[str, tuple[str, str]] = {
        "Do you trust": (
            "Antigravity 폴더 신뢰 대화창",
            "terminal send --enter --text '' (기본 선택이 신뢰)",
        ),
        "Trust this workspace": (
            "Cursor 워크스페이스 신뢰 대화창",
            "terminal send --text 'a'",
        ),
        "not signed in": (
            "Antigravity 부팅이 인증 단계에서 정체",
            "터미널을 닫고 재기동. --model 플래그 없이 agy 로 띄울 것",
        ),
        "How's the CLI experience": (
            "CLI 만족도 설문 프롬프트",
            "terminal send --text '0' (Skip)",
        ),
        "Accept this file edit?": (
            "Antigravity 파일 편집 승인 대화창",
            "화면을 읽고 승인 여부를 판단. shift+tab(ESC [ Z)으로 auto-approve 전환 가능",
        ),
        "Allow creation of this file?": (
            "Antigravity 파일 생성 승인 대화창",
            "화면을 읽고 승인 여부를 판단. shift+tab(ESC [ Z)으로 auto-approve 전환 가능",
        ),
        "Allow this": (
            "도구 실행 권한 요청",
            "화면을 읽고 승인 여부를 판단. shift+tab 으로 auto-approve 전환 가능",
        ),
        "Do you want to proceed": (
            "진행 확인 프롬프트",
            "화면을 읽고 승인 여부를 판단",
        ),
    }
    for needle, (exp_reason, exp_fix) in expected.items():
        found = watch.detect_block(needle)
        assert found is not None
        reason, fix, kind = found
        assert reason == exp_reason
        assert fix == exp_fix
        assert kind == "prompt"


def test_main_json_output_includes_blocked_kind(capsys: pytest.CaptureFixture[str]) -> None:
    blocked_state = watch.WorkerState(
        name="orca-w1",
        path="/tmp/w1",
        branch="b1",
        commits=0,
        dirty=0,
        terminal="term_1",
        blocked_reason="네트워크 오류로 턴 종료",
        blocked_fix=watch.FAILURE_REDEPLOY_FIX,
        blocked_kind="failure",
    )
    with patch("scripts.orca_worker_watch.collect", return_value=[blocked_state]):
        exit_code = watch.main(["--json"])
        assert exit_code == 1
        payload = capsys.readouterr().out
        assert '"blocked_kind": "failure"' in payload


def test_main_exit_code_failure_blocked_returns_1() -> None:
    blocked_state = watch.WorkerState(
        name="orca-w1",
        path="/tmp/w1",
        branch="b1",
        commits=0,
        dirty=0,
        terminal="term_1",
        blocked_reason="네트워크 오류로 턴 종료",
        blocked_fix=watch.FAILURE_REDEPLOY_FIX,
        blocked_kind="failure",
    )
    with patch("scripts.orca_worker_watch.collect", return_value=[blocked_state]):
        exit_code = watch.main([])
        assert exit_code == 1


def test_collect_adds_failure_note_on_failure_block() -> None:
    fake_worktrees = [("w1", "/tmp/w1", "feature")]
    fake_terminals = {"/tmp/w1": {"handle": "term_123"}}
    with (
        patch("scripts.orca_worker_watch.list_worktrees", return_value=fake_worktrees),
        patch("scripts.orca_worker_watch.worktree_progress", return_value=(0, 0)),
        patch("scripts.orca_worker_watch.terminal_map", return_value=fake_terminals),
        patch(
            "scripts.orca_worker_watch.terminal_tail",
            return_value="Error: network error while streaming response",
        ),
    ):
        states = watch.collect(watch.Path("/tmp/repo"), "main")
        assert len(states) == 1
        assert states[0].blocked_kind == "failure"
        assert any("재전송" in note for note in states[0].notes)

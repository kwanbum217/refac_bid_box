"""scripts/orca_worker_watch.py 회귀 테스트.

감시 도구가 조용히 망가지면 워커 차단을 아무도 발견하지 못한다. 특히
스크롤백에 남은 옛 대화창을 현재 차단으로 오판하는 회귀를 고정한다.
"""

from __future__ import annotations

import json
from pathlib import Path
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
    fake_terminals = {"/tmp/w1": [{"handle": "term_123"}]}
    with (
        patch("scripts.orca_worker_watch.list_worktrees", return_value=fake_worktrees),
        patch("scripts.orca_worker_watch.worktree_progress", return_value=(0, 0)),
        patch("scripts.orca_worker_watch.terminal_map", return_value=fake_terminals),
        patch(
            "scripts.orca_worker_watch.read_terminal_screen",
            return_value=("screen", "Accept this file edit?\n[Y/n]"),
        ),
        patch("scripts.orca_worker_watch.collect_lingering_sessions", return_value=[]),
        patch("scripts.orca_worker_watch.collect_unanswered_questions", return_value=[]),
    ):
        states = watch.collect(watch.Path("/tmp/repo"), "main")
        assert len(states) == 1
        assert states[0].blocked is True
        assert states[0].blocked_kind == "prompt"
        assert states[0].blocked_source == "screen"
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
    fake_terminals = {"/tmp/w1": [{"handle": "term_123"}]}
    with (
        patch("scripts.orca_worker_watch.list_worktrees", return_value=fake_worktrees),
        patch("scripts.orca_worker_watch.worktree_progress", return_value=(0, 0)),
        patch("scripts.orca_worker_watch.terminal_map", return_value=fake_terminals),
        patch(
            "scripts.orca_worker_watch.read_terminal_screen",
            return_value=("screen", "Error: network error while streaming response"),
        ),
        patch("scripts.orca_worker_watch.collect_lingering_sessions", return_value=[]),
        patch("scripts.orca_worker_watch.collect_unanswered_questions", return_value=[]),
    ):
        states = watch.collect(watch.Path("/tmp/repo"), "main")
        assert len(states) == 1
        assert states[0].blocked_kind == "failure"
        assert states[0].blocked_source == "screen"
        assert any("재전송" in note for note in states[0].notes)


def _terminal_item(handle: str, title: str | None = None) -> dict[str, str | None]:
    return {"handle": handle, "title": title, "worktreePath": "/tmp/wt"}


def test_select_worker_terminal_prefers_agent_over_shell() -> None:
    worker = _terminal_item("term_worker", "Cursor Agent")
    shell = _terminal_item("term_shell", "Terminal 1")
    chosen, notes = watch.select_worker_terminal([shell, worker])
    assert chosen is not None
    assert chosen["handle"] == "term_worker"
    assert any("터미널 2개" in note and "term_worker" in note for note in notes)


def test_select_worker_terminal_order_independent() -> None:
    worker = _terminal_item("term_worker", "Cursor Agent")
    shell = _terminal_item("term_shell", "Terminal 1")
    chosen_forward, _ = watch.select_worker_terminal([worker, shell])
    chosen_reverse, _ = watch.select_worker_terminal([shell, worker])
    assert chosen_forward is not None
    assert chosen_reverse is not None
    assert chosen_forward["handle"] == chosen_reverse["handle"] == "term_worker"


def test_select_worker_terminal_single_candidate() -> None:
    only = _terminal_item("term_only", "Terminal 1")
    chosen, notes = watch.select_worker_terminal([only])
    assert chosen is not None
    assert chosen["handle"] == "term_only"
    assert notes == []


def test_select_worker_terminal_handles_none_title() -> None:
    none_title = _terminal_item("term_none", None)
    shell = _terminal_item("term_shell", "Terminal 1")
    chosen, notes = watch.select_worker_terminal([none_title, shell])
    assert chosen is not None
    assert chosen["handle"] == "term_none"
    assert any("터미널 2개" in note for note in notes)


def test_select_worker_terminal_prefers_titled_worker_over_untitled_shell() -> None:
    """제목 없는 셸은 워커 후보가 아닙니다.

    2026-08-28 에 제목이 없는 셸이 워커와 같은 워크트리에 있었고, 이를 후보로 보면
    선택이 핸들 정렬 우연에 좌우됩니다. 핸들이 앞서더라도 워커가 선택되어야 합니다.
    """
    for blank in (None, "", "   "):
        untitled = _terminal_item("term_aaa", blank)
        worker = _terminal_item("term_zzz", "worker-n9")
        chosen, _ = watch.select_worker_terminal([untitled, worker])
        assert chosen is not None
        assert chosen["handle"] == "term_zzz"
        chosen_reversed, _ = watch.select_worker_terminal([worker, untitled])
        assert chosen_reversed is not None
        assert chosen_reversed["handle"] == "term_zzz"


def test_select_worker_terminal_all_shell_defaults_use_first_with_note() -> None:
    first = _terminal_item("term_a", "Terminal 1")
    second = _terminal_item("term_b", "Terminal 2")
    chosen, notes = watch.select_worker_terminal([first, second])
    assert chosen is not None
    assert chosen["handle"] == "term_a"
    assert any("모두 셸 기본 제목" in note for note in notes)


def test_collect_selects_worker_terminal_over_shell(capsys: pytest.CaptureFixture[str]) -> None:
    fake_worktrees = [("w1", "/tmp/w1", "feature")]
    fake_terminals = {
        "/tmp/w1": [
            {"handle": "term_shell", "title": "Terminal 1"},
            {"handle": "term_worker", "title": "Cursor Agent"},
        ]
    }
    with (
        patch("scripts.orca_worker_watch.list_worktrees", return_value=fake_worktrees),
        patch("scripts.orca_worker_watch.worktree_progress", return_value=(1, 0)),
        patch("scripts.orca_worker_watch.terminal_map", return_value=fake_terminals),
        patch(
            "scripts.orca_worker_watch.read_terminal_screen",
            return_value=("screen", "working normally"),
        ),
        patch("scripts.orca_worker_watch.collect_lingering_sessions", return_value=[]),
        patch("scripts.orca_worker_watch.collect_unanswered_questions", return_value=[]),
    ):
        states = watch.collect(watch.Path("/tmp/repo"), "main")
        assert len(states) == 1
        assert states[0].terminal == "term_worker"
        assert any("터미널 2개" in note for note in states[0].notes)

        exit_code = watch.main([])
        assert exit_code == 0
        out = capsys.readouterr().out
        assert "터미널: term_worker" in out


def test_main_json_always_includes_terminal(capsys: pytest.CaptureFixture[str]) -> None:
    clean_state = watch.WorkerState(
        name="orca-w1",
        path="/tmp/w1",
        branch="b1",
        commits=2,
        dirty=1,
        terminal="term_worker",
    )
    with patch("scripts.orca_worker_watch.collect", return_value=[clean_state]):
        exit_code = watch.main(["--json"])
        assert exit_code == 0
        payload = capsys.readouterr().out
        assert '"terminal": "term_worker"' in payload


def test_default_no_args_is_one_shot_without_sleep() -> None:
    """인자 없이 호출 시 1회 점검으로 끝나며 sleep 이 호출되지 않는다."""
    clean_state = watch.WorkerState(
        name="orca-w1",
        path="/tmp/w1",
        branch="b1",
        commits=1,
        dirty=0,
    )
    mock_sleep = patch("time.sleep")
    with (
        patch("scripts.orca_worker_watch.collect", return_value=[clean_state]),
        mock_sleep as sleep_mock,
    ):
        exit_code = watch.main([])
        assert exit_code == 0
        assert sleep_mock.call_count == 0


def test_watch_mode_immediate_exit_on_block() -> None:
    """--max-iterations 가 있는 반복 모드에서 차단을 만나면 남은 반복 없이 즉시 종료 코드 1로 끝난다."""
    clean_state = watch.WorkerState(name="orca-w1", path="/tmp/w1", branch="b1", commits=0, dirty=0)
    blocked_state = watch.WorkerState(
        name="orca-w1",
        path="/tmp/w1",
        branch="b1",
        commits=0,
        dirty=0,
        blocked_reason="CLI 만족도 설문 프롬프트",
        blocked_fix="terminal send --text '0'",
        blocked_kind="prompt",
    )
    mock_sleep = patch("time.sleep")
    with (
        patch("scripts.orca_worker_watch.collect", side_effect=[[clean_state], [blocked_state]]),
        mock_sleep as sleep_mock,
    ):
        exit_code = watch.main(["--watch", "--max-iterations", "10", "--interval", "5"])
        assert exit_code == 1
        assert sleep_mock.call_count == 1


def test_unbounded_watch_continues_after_block() -> None:
    """무제한 --watch 는 차단을 출력한 뒤에도 종료하지 않아 다른 워커 감시가 끊기지 않는다."""
    blocked_state = watch.WorkerState(
        name="orca-w1",
        path="/tmp/w1",
        branch="b1",
        commits=0,
        dirty=0,
        blocked_reason="completed Task 의 워커 터미널이 아직 열려 있습니다",
        blocked_fix="worker-release 후 terminal close",
        blocked_kind="settled_session",
    )
    clean_state = watch.WorkerState(
        name="orca-w2",
        path="/tmp/w2",
        branch="b2",
        commits=1,
        dirty=0,
    )
    calls = {"n": 0}

    def fake_collect(*_args: object, **_kwargs: object) -> list[watch.WorkerState]:
        calls["n"] += 1
        if calls["n"] <= 2:
            return [blocked_state]
        return [clean_state]

    def fake_sleep(_seconds: float) -> None:
        if calls["n"] >= 3:
            raise KeyboardInterrupt

    with (
        patch("scripts.orca_worker_watch.collect", side_effect=fake_collect),
        patch("time.sleep", side_effect=fake_sleep),
    ):
        exit_code = watch.main(["--watch", "--interval", "1"])
    assert exit_code == 0
    assert calls["n"] >= 3


def test_respawn_restarts_after_nonzero_then_stops_on_zero() -> None:
    """--respawn 무제한 감시는 비정상 종료 코드 뒤에 재기동하고 0 이면 멈춘다."""
    calls = {"n": 0}

    def fake_loop(**_kwargs: object) -> int:
        calls["n"] += 1
        return 2 if calls["n"] == 1 else 0

    with (
        patch("scripts.orca_worker_watch.watch_loop", side_effect=fake_loop),
        patch("time.sleep"),
    ):
        exit_code = watch.main(["--watch", "--respawn"])
    assert exit_code == 0
    assert calls["n"] == 2


def test_watch_mode_min_commits_completion() -> None:
    """완료 조건(min-commits) 만족 시 즉시 종료 코드 0으로 정상 종료한다."""
    iter0_state = watch.WorkerState(name="orca-w1", path="/tmp/w1", branch="b1", commits=0, dirty=1)
    iter1_state = watch.WorkerState(name="orca-w1", path="/tmp/w1", branch="b1", commits=2, dirty=0)
    mock_sleep = patch("time.sleep")
    with (
        patch("scripts.orca_worker_watch.collect", side_effect=[[iter0_state], [iter1_state]]),
        mock_sleep as sleep_mock,
    ):
        exit_code = watch.main(["--watch", "--min-commits", "2", "--max-iterations", "10"])
        assert exit_code == 0
        assert sleep_mock.call_count == 1


def test_watch_mode_quiet_output_no_repetition_on_identical_state(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """상태가 직전 주기와 같으면 요약을 반복 출력하지 않는다."""
    same_state = watch.WorkerState(name="orca-w1", path="/tmp/w1", branch="b1", commits=1, dirty=0)
    mock_sleep = patch("time.sleep")
    with (
        patch(
            "scripts.orca_worker_watch.collect",
            side_effect=[[same_state], [same_state], [same_state]],
        ),
        mock_sleep,
    ):
        exit_code = watch.main(["--watch", "--max-iterations", "3", "--interval", "10"])
        assert exit_code == 0
        out = capsys.readouterr().out
        assert out.count("[진행] orca-w1") == 1


def test_watch_mode_prints_only_changed_worker(capsys: pytest.CaptureFixture[str]) -> None:
    """반복 모드에서 특정 워커만 변경되면 변경된 워커만 출력한다."""
    w1_v0 = watch.WorkerState(name="orca-w1", path="/tmp/w1", branch="b1", commits=0, dirty=0)
    w2_v0 = watch.WorkerState(name="orca-w2", path="/tmp/w2", branch="b2", commits=0, dirty=0)

    w1_v1 = watch.WorkerState(name="orca-w1", path="/tmp/w1", branch="b1", commits=1, dirty=0)
    w2_v1 = watch.WorkerState(name="orca-w2", path="/tmp/w2", branch="b2", commits=0, dirty=0)

    mock_sleep = patch("time.sleep")
    with (
        patch(
            "scripts.orca_worker_watch.collect",
            side_effect=[[w1_v0, w2_v0], [w1_v1, w2_v1]],
        ),
        mock_sleep,
    ):
        exit_code = watch.main(["--watch", "--max-iterations", "2"])
        assert exit_code == 0
        out = capsys.readouterr().out
        assert out.count("orca-w1") == 2
        assert out.count("orca-w2") == 1


def test_stall_candidate_tracking_and_display() -> None:
    """변화 없는 경과 시간이 임계값을 넘으면 정체 후보로 표시된다."""
    history: dict[str, dict[str, float | int]] = {}
    state = watch.WorkerState(name="orca-w1", path="/tmp/w1", branch="b1", commits=0, dirty=0)

    watch.update_history([state], history, now=1000.0, stall_threshold=300.0)
    assert state.unchanged_seconds == 0.0
    assert state.stall_candidate is False

    state2 = watch.WorkerState(name="orca-w1", path="/tmp/w1", branch="b1", commits=0, dirty=0)
    watch.update_history([state2], history, now=1200.0, stall_threshold=300.0)
    assert state2.unchanged_seconds == 200.0
    assert state2.stall_candidate is False

    state3 = watch.WorkerState(name="orca-w1", path="/tmp/w1", branch="b1", commits=0, dirty=0)
    watch.update_history([state3], history, now=1350.0, stall_threshold=300.0)
    assert state3.unchanged_seconds == 350.0
    assert state3.stall_candidate is True
    assert any("정체 후보" in note for note in state3.notes)

    lines = watch.format_worker_state(state3)
    assert any("[정체후보]" in line for line in lines)


def test_stall_candidate_alone_does_not_exit_1() -> None:
    """정체 후보만으로는 종료 코드가 1이 되지 않고 0을 반환한다."""
    stall_state = watch.WorkerState(
        name="orca-w1",
        path="/tmp/w1",
        branch="b1",
        commits=0,
        dirty=0,
        stall_candidate=True,
        unchanged_seconds=400.0,
    )
    mock_sleep = patch("time.sleep")
    with (
        patch("scripts.orca_worker_watch.collect", return_value=[stall_state]),
        mock_sleep,
    ):
        exit_code = watch.main([])
        assert exit_code == 0

        exit_code_watch = watch.main(["--watch", "--max-iterations", "2"])
        assert exit_code_watch == 0


def test_json_output_includes_stall_fields(capsys: pytest.CaptureFixture[str]) -> None:
    """--json 출력에 stall_candidate 및 unchanged_seconds 가 포함된다."""
    state = watch.WorkerState(
        name="orca-w1",
        path="/tmp/w1",
        branch="b1",
        commits=1,
        dirty=0,
        stall_candidate=True,
        unchanged_seconds=312.4,
    )
    with patch("scripts.orca_worker_watch.collect", return_value=[state]):
        exit_code = watch.main(["--json"])
        assert exit_code == 0
        payload = capsys.readouterr().out
        assert '"stall_candidate": true' in payload
        assert '"unchanged_seconds": 312.4' in payload


def test_worker_done_missing_report_path_classified_as_blocked(tmp_path: Path) -> None:
    """worker_done 전송 화면에 reportPath 가 없으면 [차단]으로 분류되어야 합니다."""
    terminal_text = "orca orchestration send --type worker_done --outcome succeeded\n"
    res = watch.detect_block(terminal_text, worktree_path=str(tmp_path))
    assert res is not None
    reason, _fix, kind = res
    assert "reportPath 가 누락됨" in reason
    assert kind == "failure"


def test_worker_done_nonexistent_report_file_classified_as_blocked(tmp_path: Path) -> None:
    """worker_done 에 지정된 보고 파일이 디스크에 없으면 [차단]으로 분류되어야 합니다."""
    terminal_text = (
        "orca orchestration send --type worker_done --report-path .orca/worker_done.json\n"
    )
    res = watch.detect_block(terminal_text, worktree_path=str(tmp_path))
    assert res is not None
    reason, _fix, kind = res
    assert "보고 파일이 존재하지 않음" in reason
    assert kind == "failure"


def test_worker_done_valid_report_file_not_blocked(tmp_path: Path) -> None:
    """worker_done 에 지정된 보고 파일이 디스크에 실존하면 차단되지 않아야 합니다."""
    report_file = tmp_path / ".orca" / "worker_done.json"
    report_file.parent.mkdir(parents=True, exist_ok=True)
    report_file.write_text("{}", encoding="utf-8")

    terminal_text = (
        "orca orchestration send --type worker_done --report-path .orca/worker_done.json\n"
    )
    res = watch.detect_block(terminal_text, worktree_path=str(tmp_path))
    assert res is None


DISPATCH_PREAMBLE_SAMPLE = """\
You are working inside Orca, a multi-agent IDE. You are a dispatched worker.
Your coordinator's terminal handle is: term_311de244-f5fa-42dc-bd1b-565a8829d08e
Your task ID is: task_78b8425799bd

You talk to the coordinator only through the CLI commands below. Do not use
Slack, GitHub comments, or any other channel to reach a human during the run.

=== CLI COMMANDS ===

  # Report the terminal task outcome (REQUIRED exactly once).
  #
  # RULE: --body must be a 3-sentence executive summary (what you did,
  # what you found, what's left). Never send an empty body; the coordinator
  # reads the body first and only opens artifacts if it needs more detail.
  # If you produced a long-form artifact, include its path as
  # payload.reportPath so the coordinator can find it without a file search.
  #
  # RULE: send worker_done exactly once. Use --outcome succeeded when the
  # requested work is done, or replace it with --outcome failed when it is not.
  # Never encode failure only in prose and never silently exit.
  # Include BOTH taskId and dispatchId in the payload so a late completion
  # from a failed retry cannot complete the current dispatch.
  orca orchestration send --from term_92f9b7e0-8142-49ac-9e68-48d296059588 \\
    --type worker_done --subject "<short status>" \\
    --body "<3-sentence summary: what you did, what you found, what's left>" \\
    --task-id task_78b8425799bd --dispatch-id ctx_d993478c46fe --outcome succeeded \\
    --files-modified "path/a,path/b" \\
    --report-path "<optional: path to the full artifact>"

  # BEHAVIOR RULE: send a heartbeat every 5 minutes
  # while actively working on the task. The coordinator uses this to
  # distinguish "still thinking" from "hung / crashed." Skip heartbeats only
  # while blocked inside `check --wait` or `ask` — those calls are
  # themselves liveness signals.
  #
  # Include BOTH taskId and dispatchId in the payload: the coordinator
  # attributes the heartbeat to the specific dispatch context, not just
  # the task, so a straggler heartbeat from a previously-failed dispatch
  # cannot mask a hung retry.
  orca orchestration send --from term_92f9b7e0-8142-49ac-9e68-48d296059588 \\
    --type heartbeat --subject "alive" \\
    --task-id task_78b8425799bd --dispatch-id ctx_d993478c46fe \\
    --phase "<short: investigating|implementing|reviewing|waiting>"

  # Ask the coordinator a question and block until it answers.
  orca orchestration ask --from term_92f9b7e0-8142-49ac-9e68-48d296059588 \\
    --question "<your question>" \\
    --options "<optional,comma,separated>" \\
    --timeout-ms 600000

  # Escalate a blocker or failure (pre-completion, when you need the
  # coordinator to do something before you can continue):
  orca orchestration send --from term_92f9b7e0-8142-49ac-9e68-48d296059588 \\
    --type escalation --subject "Blocked: <reason>" \\
    --body "<details>" \\
    --task-id task_78b8425799bd --dispatch-id ctx_d993478c46fe

  # Check for messages from the coordinator:
  orca orchestration check --terminal term_92f9b7e0-8142-49ac-9e68-48d296059588

=== AFTER YOU SEND worker_done ===

worker_done ends your turn for this task. Your dispatched work is complete:
stop, return to an idle prompt, and take no further actions — do NOT start
new or unrelated work, do NOT run a sleep/poll loop, and do NOT keep calling
`orca orchestration check`. The coordinator has already recorded your
completion and expects no further output.

=== TASK ===
감시기가 화면에 떠 있는 Dispatch 지시문(preamble)의 명령 템플릿을 실제 worker_done 보고로 오인해 정상 작업 중인 워커를 실패 정체로 표시하는 오탐을 없앤다.
"""


def test_preamble_full_text_not_classified_as_blocked(tmp_path: Path) -> None:
    """Dispatch preamble 전문이 화면에 떠 있어도 차단으로 판정하지 않아야 합니다."""
    res = watch.detect_block(DISPATCH_PREAMBLE_SAMPLE, worktree_path=str(tmp_path))
    assert res is None


def test_multiline_worker_done_with_backslash_valid_report(tmp_path: Path) -> None:
    """백슬래시로 이어진 여러 줄 worker_done 명령에서 실존하는 report-path 를 정상 추출해야 합니다."""
    report_file = tmp_path / ".orca" / "worker_done.json"
    report_file.parent.mkdir(parents=True, exist_ok=True)
    report_file.write_text("{}", encoding="utf-8")

    terminal_text = (
        "orca orchestration send --from term_abc \\\n"
        "  --type worker_done \\\n"
        "  --outcome succeeded \\\n"
        "  --report-path .orca/worker_done.json\n"
    )
    res = watch.detect_block(terminal_text, worktree_path=str(tmp_path))
    assert res is None


def test_multiline_worker_done_with_backslash_nonexistent_report(tmp_path: Path) -> None:
    """백슬래시로 이어진 여러 줄 worker_done 명령에서 존재하지 않는 report-path 는 failure 로 판정해야 합니다."""
    terminal_text = (
        "orca orchestration send --from term_abc \\\n"
        "  --type worker_done \\\n"
        "  --outcome succeeded \\\n"
        "  --report-path .orca/missing_report.json\n"
    )
    res = watch.detect_block(terminal_text, worktree_path=str(tmp_path))
    assert res is not None
    reason, _fix, kind = res
    assert "보고 파일이 존재하지 않음" in reason
    assert kind == "failure"


def test_multiline_worker_done_with_backslash_missing_report_path(tmp_path: Path) -> None:
    """백슬래시로 이어진 여러 줄 worker_done 명령에서 report-path 가 없으면 failure 로 판정해야 합니다."""
    terminal_text = (
        "orca orchestration send --from term_abc \\\n"
        "  --type worker_done \\\n"
        "  --outcome succeeded\n"
    )
    res = watch.detect_block(terminal_text, worktree_path=str(tmp_path))
    assert res is not None
    reason, _fix, kind = res
    assert "reportPath 가 누락됨" in reason
    assert kind == "failure"


def test_placeholder_command_outside_preamble_not_blocked(tmp_path: Path) -> None:
    """preamble 헤더 없이 명령 템플릿만 화면에 남아있어도 자리표시자(<...>)가 있으면 차단으로 판정하지 않습니다."""
    terminal_text = (
        "orca orchestration send --from term_123 \\\n"
        '  --type worker_done --subject "<short status>" \\\n'
        '  --report-path "<optional: path to the full artifact>"\n'
    )
    res = watch.detect_block(terminal_text, worktree_path=str(tmp_path))
    assert res is None


def test_strip_preamble_removes_cli_commands_to_task() -> None:
    """strip_preamble 은 '=== CLI COMMANDS ===' 부터 '=== TASK ===' 까지의 구간을 제거합니다."""
    text = "before\n=== CLI COMMANDS ===\ntemplate content\n=== TASK ===\nafter task"
    cleaned = watch.strip_preamble(text)
    assert "before" in cleaned
    assert "template content" not in cleaned
    assert "after task" in cleaned


def test_natural_text_mentioning_worker_done_not_blocked(tmp_path: Path) -> None:
    """일반 대화나 작업 지시문에 worker_done 이라는 단어가 언급되어도 차단으로 판정하지 않습니다."""
    terminal_text = (
        "git log: fix worker_done handling in watch script\n"
        "이 작업은 worker_done 오탐을 수정하는 작업입니다.\n"
    )
    res = watch.detect_block(terminal_text, worktree_path=str(tmp_path))
    assert res is None


def test_real_failure_detected_even_with_template_present(tmp_path: Path) -> None:
    """화면에 지시문 템플릿과 함께 실제 실패한 worker_done 전송이 공존하면 실패를 정상 탐지합니다."""
    terminal_text = (
        DISPATCH_PREAMBLE_SAMPLE + "\n"
        "orca orchestration send --type worker_done --outcome succeeded\n"
    )
    res = watch.detect_block(terminal_text, worktree_path=str(tmp_path))
    assert res is not None
    reason, _fix, kind = res
    assert "reportPath 가 누락됨" in reason
    assert kind == "failure"


def test_placeholder_report_path_not_treated_as_real_file(tmp_path: Path) -> None:
    """꺾쇠 자리표시자 report-path 는 디스크 실존 여부를 검사하지 않고 차단하지 않습니다."""
    terminal_text = (
        'orca orchestration send --type worker_done --report-path "<path/to/report.json>"\n'
    )
    res = watch.detect_block(terminal_text, worktree_path=str(tmp_path))
    assert res is None


def test_collect_does_not_touch_real_runtime() -> None:
    """collect 는 잔류 세션 조회를 주입 가능한 지점으로 통과해야 합니다.

    2026-09-01 까지 collect 안에서 audit_lingering_sessions 를 직접 import 하고
    불러 **단위 테스트가 실제 Orca 런타임에 붙었습니다.** list_worktrees 를 mock 해도
    막히지 않아, 개발 머신에 열린 워크트리 수에 따라 통과 여부가 갈렸습니다
    (워크트리 4개면 assert 1 == 4, 2개면 assert 1 == 2). CI 는 워크트리가 없어
    통과하므로 로컬에서만 깨졌습니다.
    """
    fake_worktrees = [("w1", "/tmp/w1", "feature")]
    called = []

    def fake_lingering():
        called.append(True)
        return []

    with (
        patch("scripts.orca_worker_watch.list_worktrees", return_value=fake_worktrees),
        patch("scripts.orca_worker_watch.worktree_progress", return_value=(0, 0)),
        patch("scripts.orca_worker_watch.terminal_map", return_value={}),
        patch("scripts.orca_worker_watch.collect_lingering_sessions", fake_lingering),
        patch("scripts.orca_worker_watch.collect_unanswered_questions", return_value=[]),
    ):
        states = watch.collect(watch.Path("/tmp/repo"), "main")

    assert len(states) == 1, "주입한 워크트리 외의 상태가 섞이면 실환경에 붙은 것입니다."
    assert called, "잔류 세션 조회는 주입 가능한 함수를 거쳐야 합니다."


def test_collect_survives_lingering_lookup_failure() -> None:
    """잔류 세션 조회가 실패해도 감시 자체는 계속돼야 합니다."""
    fake_worktrees = [("w1", "/tmp/w1", "feature")]

    def boom():
        raise RuntimeError("orca runtime unavailable")

    with (
        patch("scripts.orca_worker_watch.list_worktrees", return_value=fake_worktrees),
        patch("scripts.orca_worker_watch.worktree_progress", return_value=(0, 0)),
        patch("scripts.orca_worker_watch.terminal_map", return_value={}),
        patch("scripts.orca_worker_watch.collect_lingering_sessions", boom),
        patch("scripts.orca_worker_watch.collect_unanswered_questions", return_value=[]),
    ):
        states = watch.collect(watch.Path("/tmp/repo"), "main")

    assert len(states) == 1


# ---------------------------------------------------------------------------
# 미답변 질문 탐지
# ---------------------------------------------------------------------------


def _inbox_payload(messages):
    return json.dumps({"result": {"messages": messages}})


def test_unanswered_question_is_detected():
    """스레드에 답이 없는 question 은 미답변으로 잡혀야 합니다."""
    payload = _inbox_payload(
        [
            {
                "id": "msg_q",
                "type": "question",
                "from_handle": "term_a",
                "subject": "물음",
                "body": "본문",
            },
        ]
    )
    with patch("scripts.orca_worker_watch._run", return_value=payload):
        pending = watch.collect_unanswered_questions()
    assert [p["id"] for p in pending] == ["msg_q"]


def test_answered_question_is_not_reported():
    """thread_id 로 답이 걸린 question 은 미답변이 아닙니다."""
    payload = _inbox_payload(
        [
            {
                "id": "msg_q",
                "type": "question",
                "from_handle": "term_a",
                "subject": "물음",
                "body": "",
            },
            {
                "id": "msg_r",
                "type": "status",
                "thread_id": "msg_q",
                "from_handle": "run:r",
                "subject": "Re",
            },
        ]
    )
    with patch("scripts.orca_worker_watch._run", return_value=payload):
        pending = watch.collect_unanswered_questions()
    assert pending == []


def test_escalation_is_treated_as_pending():
    """escalation 도 코디네이터 조치를 기다리는 상태입니다."""
    payload = _inbox_payload(
        [
            {
                "id": "msg_e",
                "type": "escalation",
                "from_handle": "term_a",
                "subject": "막힘",
                "body": "",
            },
        ]
    )
    with patch("scripts.orca_worker_watch._run", return_value=payload):
        pending = watch.collect_unanswered_questions()
    assert [p["type"] for p in pending] == ["escalation"]


def test_heartbeat_and_worker_done_are_not_pending():
    """답변을 요구하지 않는 유형은 잡지 않습니다."""
    payload = _inbox_payload(
        [
            {"id": "msg_h", "type": "heartbeat", "from_handle": "term_a", "subject": "alive"},
            {"id": "msg_d", "type": "worker_done", "from_handle": "term_a", "subject": "완료"},
        ]
    )
    with patch("scripts.orca_worker_watch._run", return_value=payload):
        pending = watch.collect_unanswered_questions()
    assert pending == []


def test_unanswered_question_from_dead_terminal_is_ignored():
    """종료된 워커의 질문은 답해도 도착하지 않으므로 차단으로 보지 않습니다."""
    with (
        patch(
            "scripts.orca_worker_watch.list_worktrees",
            return_value=[("wt", "/tmp/wt", "feat/x")],
        ),
        patch("scripts.orca_worker_watch.worktree_progress", return_value=(1, 0)),
        patch(
            "scripts.orca_worker_watch.terminal_map",
            return_value={"/tmp/wt": [{"handle": "term_live", "title": "worker"}]},
        ),
        patch("scripts.orca_worker_watch.read_terminal_screen", return_value=("screen", "")),
        patch("scripts.orca_worker_watch.collect_lingering_sessions", return_value=[]),
        patch(
            "scripts.orca_worker_watch.collect_unanswered_questions",
            return_value=[
                {
                    "id": "msg_old",
                    "type": "question",
                    "from_handle": "term_closed",
                    "subject": "옛 질문",
                    "body": "",
                }
            ],
        ),
    ):
        states = watch.collect(Path("/tmp/repo"))
    assert all(s.blocked_kind != "answer_pending" for s in states)


def test_unanswered_question_from_live_terminal_blocks():
    """살아 있는 워커의 미답변 질문은 차단으로 보고되어야 합니다."""
    with (
        patch(
            "scripts.orca_worker_watch.list_worktrees",
            return_value=[("wt", "/tmp/wt", "feat/x")],
        ),
        patch("scripts.orca_worker_watch.worktree_progress", return_value=(0, 3)),
        patch(
            "scripts.orca_worker_watch.terminal_map",
            return_value={"/tmp/wt": [{"handle": "term_live", "title": "worker"}]},
        ),
        patch("scripts.orca_worker_watch.read_terminal_screen", return_value=("screen", "")),
        patch("scripts.orca_worker_watch.collect_lingering_sessions", return_value=[]),
        patch(
            "scripts.orca_worker_watch.collect_unanswered_questions",
            return_value=[
                {
                    "id": "msg_q",
                    "type": "question",
                    "from_handle": "term_live",
                    "subject": "범위 확장 요청",
                    "body": "본문",
                }
            ],
        ),
    ):
        states = watch.collect(Path("/tmp/repo"))
    blocked = [s for s in states if s.blocked_kind == "answer_pending"]
    assert len(blocked) == 1
    assert "msg_q" in blocked[0].blocked_fix


# ---------------------------------------------------------------------------
# 화면 기준 차단 검사 및 fallback 지속성 검증 (task_76e874acc927)
# ---------------------------------------------------------------------------


def test_screen_path_detects_block_signal() -> None:
    """1. 화면 경로에서 신호가 있으면 즉시 차단으로 판정하고 근거를 screen 으로 기록한다."""
    with patch(
        "scripts.orca_worker_watch.read_terminal_screen",
        return_value=("screen", "Accept this file edit?\n[Y/n]"),
    ):
        res = watch.inspect_terminal_block("term_test")
        assert res is not None
        (reason, _fix, kind), evidence = res
        assert "파일 편집" in reason
        assert kind == "prompt"
        assert evidence == "screen"


def test_screen_path_ignores_boot_string_absent_from_screen() -> None:
    """2. 화면에는 없고 누적 출력에만 있는 부팅 문자열은 차단으로 잡지 않는다."""
    boot_output = "Welcome to the Antigravity CLI. You are currently not signed in."
    rendered_screen = (
        "  Composer 2.5 · 34%\n  ~/workspaces/refac_bid_box\n> Accept-edits mode active"
    )

    with (
        patch(
            "scripts.orca_worker_watch.read_terminal_screen",
            return_value=("screen", rendered_screen),
        ),
        patch(
            "scripts.orca_worker_watch.read_terminal_stream_tail",
            return_value=boot_output,
        ),
    ):
        res = watch.inspect_terminal_block("term_test")
        assert res is None, "화면에 없는 지나간 부팅 출력은 차단으로 오판하지 않아야 한다"


def test_screen_unavailable_single_observation_is_not_blocked() -> None:
    """3-A. screen-unavailable 일 때 1회만 관측된 신호는 차단으로 판정하지 않는다."""
    first_tail = "Accept this file edit?\n[Y/n]"
    second_tail = "file edited successfully\n$ "
    mock_sleep: list[float] = []

    with (
        patch(
            "scripts.orca_worker_watch.read_terminal_screen",
            return_value=("screen-unavailable", first_tail),
        ),
        patch("scripts.orca_worker_watch.read_terminal_stream_tail", return_value=second_tail),
    ):
        res = watch.inspect_terminal_block(
            "term_test",
            sleep_func=lambda s: mock_sleep.append(s),
        )
        assert res is None, "2회차 관측에서 신호가 사라졌으므로 차단이 아니어야 한다"
        assert len(mock_sleep) == 1
        assert mock_sleep[0] == watch.FALLBACK_RECHECK_DELAY_SECONDS


def test_screen_unavailable_two_consecutive_observations_is_blocked() -> None:
    """3-B. screen-unavailable 일 때 2회 연속 관측되면 차단으로 판정한다."""
    persistent_tail = "Accept this file edit?\n[Y/n]"
    mock_sleep: list[float] = []

    with (
        patch(
            "scripts.orca_worker_watch.read_terminal_screen",
            return_value=("screen-unavailable", persistent_tail),
        ),
        patch(
            "scripts.orca_worker_watch.read_terminal_stream_tail",
            return_value=persistent_tail,
        ),
    ):
        res = watch.inspect_terminal_block(
            "term_test",
            sleep_func=lambda s: mock_sleep.append(s),
        )
        assert res is not None, "2회 연속 관측되었으므로 차단으로 판정되어야 한다"
        (reason, _fix, kind), evidence = res
        assert "파일 편집" in reason
        assert kind == "prompt"
        assert evidence == "stream_fallback"
        assert len(mock_sleep) == 1
        assert mock_sleep[0] == watch.FALLBACK_RECHECK_DELAY_SECONDS


def test_fallback_block_evidence_labeled_in_output_and_json(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """4. fallback 판정 시 사람이 읽는 출력과 JSON 에 근거가 화면이 아니라는 표시가 드러난다."""
    persistent_tail = "Error: network error while streaming response"
    fake_worktrees = [("w1", "/tmp/w1", "feature")]
    fake_terminals = {"/tmp/w1": [{"handle": "term_fb"}]}

    with (
        patch("scripts.orca_worker_watch.list_worktrees", return_value=fake_worktrees),
        patch("scripts.orca_worker_watch.worktree_progress", return_value=(0, 0)),
        patch("scripts.orca_worker_watch.terminal_map", return_value=fake_terminals),
        patch(
            "scripts.orca_worker_watch.read_terminal_screen",
            return_value=("screen-unavailable", persistent_tail),
        ),
        patch("scripts.orca_worker_watch.read_terminal_stream_tail", return_value=persistent_tail),
        patch("scripts.orca_worker_watch.collect_lingering_sessions", return_value=[]),
        patch("scripts.orca_worker_watch.collect_unanswered_questions", return_value=[]),
    ):
        states = watch.collect(
            watch.Path("/tmp/repo"),
            sleep_func=lambda s: None,
        )
        assert len(states) == 1
        state = states[0]
        assert state.blocked is True
        assert state.blocked_source == "stream_fallback"
        assert any("누적 출력 fallback" in note for note in state.notes)

        # 1. 사람 판독 출력 확인
        lines = watch.format_worker_state(state)
        assert any("근거: 누적 출력 fallback" in line for line in lines)

        # 2. JSON 직렬화 확인
        payload = state.as_dict()
        assert payload["blocked_source"] == "stream_fallback"

        # 3. main --json 실행 확인
        with patch("scripts.orca_worker_watch.collect", return_value=[state]):
            code = watch.main(["--json"])
            assert code == 1
            out = capsys.readouterr().out
            assert '"blocked_source": "stream_fallback"' in out


def test_no_signal_does_not_call_recheck_sleep_or_tail() -> None:
    """5. 신호가 없으면 재확인 sleep 이나 2회차 조회를 하지 않는다."""
    clean_tail = "Running tests...\nAll 50 tests passed.\n$ "
    sleep_calls: list[float] = []
    tail_calls: list[str] = []

    def mock_tail(handle: str, lines: int = watch.TAIL_LINES) -> str:
        tail_calls.append(handle)
        return clean_tail

    with (
        patch(
            "scripts.orca_worker_watch.read_terminal_screen",
            return_value=("screen-unavailable", clean_tail),
        ),
        patch("scripts.orca_worker_watch.read_terminal_stream_tail", side_effect=mock_tail),
    ):
        res = watch.inspect_terminal_block(
            "term_clean",
            sleep_func=lambda s: sleep_calls.append(s),
        )
        assert res is None
        assert len(sleep_calls) == 0, "신호가 없으면 sleep 을 호출하지 않아야 한다"
        assert len(tail_calls) == 0, (
            "screen_res 에서 이미 clean 을 확인했으므로 추가 조회가 없어야 한다"
        )


def test_no_signal_failed_screen_call_does_not_recheck() -> None:
    """5-B. screen 호출 실패 fallback 에서도 1회차 누적 출력에 신호가 없으면 재확인 sleep 을 하지 않는다."""
    clean_tail = "Running tests...\nAll 50 tests passed.\n$ "
    sleep_calls: list[float] = []
    tail_calls: list[str] = []

    def mock_tail(handle: str, lines: int = watch.TAIL_LINES) -> str:
        tail_calls.append(handle)
        return clean_tail

    with (
        patch("scripts.orca_worker_watch.read_terminal_screen", return_value=None),
        patch("scripts.orca_worker_watch.read_terminal_stream_tail", side_effect=mock_tail),
    ):
        res = watch.inspect_terminal_block(
            "term_clean",
            sleep_func=lambda s: sleep_calls.append(s),
        )
        assert res is None
        assert len(sleep_calls) == 0, "신호가 없으면 재확인 sleep 을 하지 않아야 한다"
        assert len(tail_calls) == 1, "1회차 조회만 수행되어야 한다"

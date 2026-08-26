"""scripts/orca_worker_watch.py 회귀 테스트.

감시 도구가 조용히 망가지면 워커 차단을 아무도 발견하지 못한다. 특히
스크롤백에 남은 옛 대화창을 현재 차단으로 오판하는 회귀를 고정한다.
"""

from __future__ import annotations

import pytest

from scripts import orca_worker_watch as watch


@pytest.mark.parametrize(
    "needle, expected_fragment",
    [
        ("Do you trust the contents of this project?", "신뢰"),
        ("▶ [a] Trust this workspace", "신뢰"),
        ("Welcome to the Antigravity CLI. You are currently not signed in.", "인증"),
        ("How's the CLI experience so far? Help us improve:", "설문"),
    ],
)
def test_detect_block_finds_known_signals(needle: str, expected_fragment: str) -> None:
    found = watch.detect_block(needle)
    assert found is not None
    reason, fix = found
    assert expected_fragment in reason
    assert fix


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
    assert state.blocked is True
    payload = state.as_dict()
    assert payload["blocked"] is True
    assert payload["blocked_reason"] == "테스트 차단"
    assert set(payload) >= {"name", "branch", "commits", "dirty", "terminal", "notes"}


def test_block_signals_all_have_reason_and_fix() -> None:
    assert watch.BLOCK_SIGNALS
    for needle, reason, fix in watch.BLOCK_SIGNALS:
        assert needle
        assert reason
        assert fix

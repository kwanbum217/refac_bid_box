"""2026-11-25 런처 고지문 회귀 시험.

워커가 전량 시험을 배경으로 돌려 놓고 완료 알림을 기다리다 턴을 끝내는 문제를
막기 위해, 빌더(COMMIT_NOTICE)와 리뷰어(REVIEWER_NOTICE) 고지문 모두에
배경 실행 금지와 같은 턴 마무리 지시가 들어 있어야 합니다.
"""

from __future__ import annotations

from scripts.orca_worker_launch_common import (
    COMMIT_NOTICE,
    REVIEWER_NOTICE,
    resolve_notice,
)


def test_commit_notice_forbids_background_and_requires_same_turn_finish() -> None:
    assert "배경" in COMMIT_NOTICE
    assert "기다리겠다며 턴을 끝내면" in COMMIT_NOTICE
    assert "같은 턴" in COMMIT_NOTICE
    # 기존 커밋 지시는 유지된다
    assert "커밋" in COMMIT_NOTICE
    assert "git add -A" in COMMIT_NOTICE


def test_reviewer_notice_forbids_background_and_requires_same_turn_finish() -> None:
    assert "배경" in REVIEWER_NOTICE
    assert "기다리겠다며 턴을 끝내면" in REVIEWER_NOTICE
    assert "같은 턴" in REVIEWER_NOTICE
    assert "review_done.json" in REVIEWER_NOTICE


def test_worker_notice_selection_keeps_background_rule() -> None:
    for role, prompt in (("builder", ""), ("reviewer", "")):
        notice = resolve_notice(role, prompt)
        assert "배경" in notice
        assert "같은 턴" in notice

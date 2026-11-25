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


def test_commit_notice_requires_full_suite_rerun_after_last_edit() -> None:
    """최종 수정 뒤 전량 시험 재실행 요구가 빌더 고지문에 있어야 합니다.

    2026-11-25 보완 투찰률 병합에서 빌더가 전량 시험 후 문서를 고치고 대상
    시험만 다시 돌려 보고 건수(11737)와 실제(11738)가 달라 게이트 6 이 막혔습니다.
    """
    assert "마지막 코드·문서 수정 뒤에 전량 시험을 다시" in COMMIT_NOTICE
    assert "passed 건수" in COMMIT_NOTICE
    assert "게이트 6" in COMMIT_NOTICE
    assert "건수 불일치" in COMMIT_NOTICE
    # 리뷰어 고지문에는 전량 재실행 의무를 넣지 않는다.
    assert "게이트 6" not in REVIEWER_NOTICE


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


def test_commit_notice_adds_long_session_closing_rule() -> None:
    """장기 세션 분할 대응: 마무리 전 불필요한 재열람을 막는 문장이 있어야 합니다.

    컨텍스트가 커진 세션이 보고서 직전에 같은 파일을 다시 읽으면 재읽기 비용이
    누적됩니다. 기존 세 문장(커밋 요구, 배경 금지, 전량 재실행)은 그대로 둡니다.
    """
    assert "같은 세션에서 큰 파일을 여러 번 열어 컨텍스트가 커졌다면" in COMMIT_NOTICE
    assert "불필요한 재열람을 하지 말고" in COMMIT_NOTICE
    assert "이미 얻은 결과로 바로 마무리하십시오" in COMMIT_NOTICE
    # 기존 문장 회귀 방지
    assert "커밋" in COMMIT_NOTICE
    assert "git add -A" in COMMIT_NOTICE
    assert "배경" in COMMIT_NOTICE
    assert "마지막 코드·문서 수정 뒤에 전량 시험을 다시" in COMMIT_NOTICE
    # 리뷰어 고지문은 바꾸지 않는다.
    assert "불필요한 재열람" not in REVIEWER_NOTICE

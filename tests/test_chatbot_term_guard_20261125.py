"""공고 상세가 실제로 가진 값을 '수집하지 않는 값'으로 안내하던 문구 회귀 시험.

챗봇 가드 문구, 가격 용어 안내, 입력창 예시가 실제 보유 상태와 맞는지 확인합니다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.rag.answer_format import PRICE_TERM_NOTES
from src.rag.data_gap_guard import DATA_GAP_MESSAGES, detect_data_gap
from src.rag.query_planning import build_retrieval_plan

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_TSX = REPO_ROOT / "frontend" / "src" / "App.tsx"

NOT_COLLECTED_PHRASE = "포함되어 있지 않"
DETAIL_SCREEN_PHRASE = "공고 상세"


@pytest.mark.parametrize(
    ("message", "item"),
    [
        ("낙찰하한율 평균 알려줘", "낙찰하한율"),
        ("낙찰하한율 실측값 보여줘", "낙찰하한율"),
    ],
)
def test_lower_rate_notice_points_to_announcement_detail(message: str, item: str) -> None:
    """(a) 낙찰하한율 안내가 미수집이라고 말하지 않고 공고 상세를 가리킨다."""
    assert detect_data_gap(message) == item
    notice = DATA_GAP_MESSAGES[item]

    assert NOT_COLLECTED_PHRASE not in notice
    assert DETAIL_SCREEN_PHRASE in notice
    assert "낙찰하한율" in notice


@pytest.mark.parametrize(
    "message",
    ["지역 제한 공고 보여줘", "업종 제한 공고 알려줘"],
)
def test_restriction_notice_points_to_announcement_detail(message: str) -> None:
    """(b) 지역·업종 제한 안내도 공고 상세에서 확인 가능함을 말한다."""
    item = detect_data_gap(message)

    assert item == "지역 제한·업종 제한 참가자격"
    notice = DATA_GAP_MESSAGES[item]
    assert NOT_COLLECTED_PHRASE not in notice
    assert DETAIL_SCREEN_PHRASE in notice


@pytest.mark.parametrize(
    "message",
    ["참가업체 수 알려줘", "참가 업체 수 알려줘", "참가업체 수 평균 알려줘"],
)
def test_participant_count_questions_route_to_competition(message: str) -> None:
    """(c) 참가업체 수 질문은 경쟁률 집계 경로로 보낸다."""
    assert detect_data_gap(message) is None
    assert build_retrieval_plan(message).filters.get("metric") == "avg_participants"


def test_participant_count_filter_notice_mentions_competition() -> None:
    """(c-2) 공고별 조건 필터로 남는 질문의 안내는 경쟁률 조회 가능을 말한다."""
    item = detect_data_gap("참가업체 수 10개 이상인 공고 보여줘")

    assert item == "참가업체 수"
    notice = DATA_GAP_MESSAGES[item]
    assert "경쟁률" in notice
    assert NOT_COLLECTED_PHRASE not in notice


def test_bidder_list_notice_stays_unchanged() -> None:
    """(d) 투찰자·참여 업체 개별 명단은 수집하지 않는다는 안내를 유지한다."""
    item = detect_data_gap("투찰자 알려줘")

    assert item == "투찰자·참여 업체"
    notice = DATA_GAP_MESSAGES[item]
    assert NOT_COLLECTED_PHRASE in notice


def test_price_term_notes_distinguish_rate_terms() -> None:
    """(e) 가격 용어 안내가 사정률·투찰률·낙찰하한율·낙찰률을 구분한다."""
    for term in ("사정률", "투찰률", "낙찰하한율", "낙찰률"):
        assert f"- {term}:" in PRICE_TERM_NOTES

    assert "86.745" not in PRICE_TERM_NOTES


def test_chat_placeholder_asks_service_price_question() -> None:
    """(f) 입력창 예시가 물품 적격 산식 설명이 아니라 용역 가격 보완 질문이다."""
    source = APP_TSX.read_text(encoding="utf-8")

    assert "물품구매" not in source
    assert "정량점수가 1점 모자라면 투찰률을 얼마나 올려야 하나요?" in source


def test_rate_terms_are_defined_without_fixed_numbers() -> None:
    """새 용어 설명이 특정 수치를 기본값처럼 제시하지 않는다."""
    rate_notes = [
        line
        for line in PRICE_TERM_NOTES.splitlines()
        if line.startswith(("- 사정률:", "- 투찰률:", "- 낙찰하한율:", "- 낙찰률:"))
    ]

    assert len(rate_notes) == 4
    for line in rate_notes:
        assert not any(char.isdigit() for char in line)

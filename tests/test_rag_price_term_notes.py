"""tests/test_rag_price_term_notes.py

금액 용어(예정가격, 추정가격, 기초금액) 검색 컨텍스트 결정론적 주입 및 유출 가드 정합성 테스트.
"""

from __future__ import annotations

import pytest

from src.rag.answer_format import PRICE_TERM_NOTES, _compose_context_text
from src.rag.engine import SYSTEM_PROMPT
from src.rag.leak_guard import contains_system_prompt_leak, init_leak_guard
from src.rag.query_planning import build_retrieval_plan
from src.rag.schemas import RetrievalPlan


def test_price_term_notes_constant_structure():
    """PRICE_TERM_NOTES 상수가 계약된 정확한 4개 줄을 갖추었는지 검증합니다."""
    expected_lines = [
        "- 기초금액: 발주기관이 예정가격 작성의 기준으로 공고하는 금액입니다.",
        "- 예정가격: 기초금액을 바탕으로 복수예비가격 추첨 등을 거쳐 개찰 시점에 확정되는 낙찰자 결정 기준 가격이며, 개찰 전에는 공개되지 않습니다.",
        "- 추정가격: 입찰 방법 결정 등에 쓰도록 부가가치세를 제외하고 산정한 금액입니다.",
        "- 공고별 값은 아래 Source 에 있는 값만 인용하고, 없는 값은 추정하지 않습니다.",
    ]
    actual_lines = PRICE_TERM_NOTES.strip().splitlines()
    assert actual_lines == expected_lines, "PRICE_TERM_NOTES 상수가 계약 문구와 일치해야 합니다."


def test_adv_num_01_context_placement():
    """(a) adv_num_01 질문이면 컨텍스트에 안내 섹션과 네 줄이 있고 '적용 필터' 뒤·'Source [1]' 앞에 위치함을 검증합니다."""
    question = (
        "2026년 도로포장 공사의 예정가격, 추정가격, 기초금액을 혼동하지 말고 "
        "각각의 정의와 공고에 제시된 값을 명확히 구분해서 알려줘."
    )
    plan = build_retrieval_plan(question)
    structured_data = {
        "summary": {
            "total_bids": 1,
            "avg_rate": 87.5,
        }
    }
    context = _compose_context_text(plan, structured_data, [], None)

    # 1. 안내 섹션 헤더 및 네 줄 존재 검증
    header = "금액 용어 안내 (시스템 기준 정의, 인용 번호 없음):"
    assert header in context
    for line in PRICE_TERM_NOTES.strip().splitlines():
        assert line in context

    # 2. 위치 순서 검증: '적용 필터' 뒤, 'Source [1]' 앞
    filter_pos = context.index("적용 필터:")
    note_pos = context.index(header)
    source1_pos = context.index("Source [1]")

    assert filter_pos < note_pos < source1_pos, (
        "안내 섹션은 '적용 필터' 뒤, 'Source [1]' 앞에 위치해야 합니다."
    )


def test_canonical_q26_context_attachment():
    """(b) canonical q26(미래 공고의 사전 확정 예정가격 질의) 질문에도 금액 용어 안내 섹션이 붙음을 검증합니다."""
    question = "2030년 부산항 신항 북컨테이너 2단계 인입철도 건설공사의 사전 확정 예정가격과 낙찰률을 알려줘"
    plan = build_retrieval_plan(question)
    context = _compose_context_text(plan, None, [], None)

    header = "금액 용어 안내 (시스템 기준 정의, 인용 번호 없음):"
    assert header in context
    assert PRICE_TERM_NOTES in context


def test_context_unchanged_when_terms_absent():
    """(c) 세 용어가 없는 질문은 기존 컨텍스트와 완전히 같음을 검증합니다."""
    plan_without_terms = RetrievalPlan(
        route_reason="정형 통계 질의",
        lexical_query="최근 서울특별시 공사 낙찰률 추세를 분석해줘",
        semantic_query="최근 서울특별시 공사 낙찰률 추세를 분석해줘",
        filters={"institution_name": "서울특별시", "category": "Cnstwk"},
    )
    structured_data = {
        "summary": {
            "total_bids": 5,
            "avg_rate": 86.4,
        }
    }
    context = _compose_context_text(plan_without_terms, structured_data, [], None)

    # 안내 섹션이 전혀 없어야 함
    assert "금액 용어 안내" not in context
    assert "기초금액: 발주기관이" not in context
    assert "예정가격: 기초금액을" not in context
    assert "추정가격: 입찰 방법" not in context

    # 섹션 구성이 검색 라우팅 -> 적용 필터 -> Source [1] 순서로만 이어져야 함
    expected_sections = [
        f"검색 라우팅: {plan_without_terms.route_reason}",
        "적용 필터:\n- 기관/지역: 서울특별시\n- 분야: 건설",
        context[context.index("Source [1]") :].split("\n\n한계 및 주의:")[0],
    ]
    assert context.startswith(f"{expected_sections[0]}\n\n{expected_sections[1]}\n\nSource [1]")


@pytest.mark.parametrize("term", ["예정가격", "추정가격", "기초금액"])
def test_individual_terms_trigger_note(term: str):
    """세 용어 중 하나라도 질문에 포함되면 안내 섹션이 추가되는지 검증합니다."""
    plan_lexical = RetrievalPlan(
        route_reason="테스트 질의",
        lexical_query=f"해당 공고의 {term} 기준을 알려주세요.",
        semantic_query="",
    )
    context_lexical = _compose_context_text(plan_lexical, None, [], None)
    assert "금액 용어 안내 (시스템 기준 정의, 인용 번호 없음):" in context_lexical

    # lexical_query 가 비어 있고 semantic_query 에만 있는 경우
    plan_semantic = RetrievalPlan(
        route_reason="테스트 질의",
        lexical_query=None,
        semantic_query=f"해당 공고의 {term} 기준을 알려주세요.",
    )
    context_semantic = _compose_context_text(plan_semantic, None, [], None)
    assert "금액 용어 안내 (시스템 기준 정의, 인용 번호 없음):" in context_semantic


def test_no_filter_placement():
    """적용 필터 섹션이 없을 때는 '검색 라우팅' 섹션 바로 뒤에 안내 구역이 위치함을 검증합니다."""
    plan = RetrievalPlan(
        route_reason="개체 질의",
        lexical_query="기초금액 얼마인가요",
        filters={},
    )
    context = _compose_context_text(plan, None, [], None)
    header = "금액 용어 안내 (시스템 기준 정의, 인용 번호 없음):"

    # '적용 필터:' 가 없어야 하고, 검색 라우팅 바로 다음 섹션이어야 함
    assert "적용 필터:" not in context
    assert context.startswith(f"검색 라우팅: {plan.route_reason}\n\n{header}\n{PRICE_TERM_NOTES}")


def test_leak_guard_does_not_flag_price_term_notes():
    """(d) src.rag.leak_guard.contains_system_prompt_leak 가 PRICE_TERM_NOTES 각 줄을 담은 답을 유출로 판정하지 않음을 검증합니다."""
    init_leak_guard(SYSTEM_PROMPT)

    # 1. PRICE_TERM_NOTES 의 각 개별 라인이 유출로 판정되지 않음
    for line in PRICE_TERM_NOTES.strip().splitlines():
        assert not contains_system_prompt_leak(line), f"유출 오판정: {line}"

    # 2. PRICE_TERM_NOTES 전체 블록이 유출로 판정되지 않음
    assert not contains_system_prompt_leak(PRICE_TERM_NOTES)

    # 3. 모델 응답에 각 정의 문구가 포함되어 있어도 정상 통과함
    sample_llm_answers = [
        "기초금액: 발주기관이 예정가격 작성의 기준으로 공고하는 금액입니다.",
        "예정가격은 기초금액을 바탕으로 복수예비가격 추첨 등을 거쳐 개찰 시점에 확정되는 낙찰자 결정 기준 가격이며, 개찰 전에는 공개되지 않습니다.",
        "추정가격은 입찰 방법 결정 등에 쓰도록 부가가치세를 제외하고 산정한 금액입니다.",
        f"질문하신 용어의 정의는 다음과 같습니다.\n{PRICE_TERM_NOTES}\n공고에 명시된 기초금액은 100억원입니다.",
    ]
    for ans in sample_llm_answers:
        assert not contains_system_prompt_leak(ans), f"답변 유출 오판정: {ans}"

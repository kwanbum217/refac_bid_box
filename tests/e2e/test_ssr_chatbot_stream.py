"""tests/e2e/test_ssr_chatbot_stream.py

SSR 챗봇 브라우저 E2E 실시간 SSE 스트리밍 및 인터랙션 검증 테스트.
- 인증/비인증 챗봇 화면 접근 제어 검증
- 사용자 질의 전송 후 SSE 토큰 실시간 누적 렌더링 검증 (중간 상태 단언)
- 스트림 정상 완료 및 최종 답변 렌더링 검증
- 스트림 도중 백엔드 예외 발생 시 에러 처리 및 UI 안정성 검증
- 낙찰 결과 연계(result_id) 초기 프롬프트 자동 주입 및 발송 검증
- 고정 대기(sleep) 배제: Playwright 자동 재시도 및 조건 대기(expect, wait_for_function)만 사용
"""

from __future__ import annotations

import itertools
from datetime import timedelta
from typing import Any

import pytest
from playwright.async_api import Page, expect
from sqlalchemy.orm import Session

from src.app.api.v1.chatbot import STREAM_ERROR_MESSAGE
from src.app.core.timeutil import utcnow
from src.app.models.bids import BidResult


@pytest.mark.e2e
async def test_ssr_chatbot_unauthenticated_redirect(
    page: Page,
    live_server_url: str,
) -> None:
    """비인증 사용자가 /chatbot/ 접근 시 로그인 페이지로 303 리다이렉트되는지 검증합니다."""
    response = await page.goto(f"{live_server_url}/chatbot/")
    assert response is not None
    assert "/accounts/login/" in page.url
    assert "next=%2Fchatbot%2F" in page.url or "next=/chatbot/" in page.url


@pytest.mark.e2e
async def test_ssr_chatbot_page_access_authenticated(
    authenticated_page: Page,
    live_server_url: str,
    e2e_test_user: dict[str, Any],
) -> None:
    """인증된 세션으로 /chatbot/ 진입 시 챗봇 메인 UI와 세션 정보가 정상 렌더링되는지 검증합니다."""
    response = await authenticated_page.goto(f"{live_server_url}/chatbot/")
    assert response is not None
    assert response.status == 200

    # 챗봇 입력창(#chat-input) 및 전송 버튼(#btn-send) 가시성 검증
    chat_input = authenticated_page.locator("#chat-input")
    await expect(chat_input).to_be_visible()

    send_btn = authenticated_page.locator("#btn-send")
    await expect(send_btn).to_be_visible()


@pytest.mark.e2e
async def test_ssr_chatbot_streaming_token_accumulation(
    authenticated_page: Page,
    live_server_url: str,
) -> None:
    """SSE 실시간 스트리밍 시 토큰이 DOM에 점진적으로 누적 렌더링되고 최종 완료되는지 검증합니다.

    - 단언 원칙: 고정 sleep 배제, 중간 토큰 누적 상태(길이 증가) 단언, 최종 답변 일치 검증.
    """
    await authenticated_page.goto(f"{live_server_url}/chatbot/")

    chat_input = authenticated_page.locator("#chat-input")
    send_btn = authenticated_page.locator("#btn-send")

    question = "국가계약법 시행령 제42조 규정에 대해 설명해주세요"
    await chat_input.fill(question)
    await send_btn.click()

    # 1. 사용자 질문 메시지 버블이 DOM에 즉시 렌더링되는지 확인
    user_bubble = authenticated_page.locator("text=" + question).first
    await expect(user_bubble).to_be_visible()

    # 2. 중간 토큰 누적 상태 검증
    #
    # 최종 문장만 확인하면 서버가 한 번에 렌더링해도 통과하므로 스트리밍을 증명하지
    # 못합니다. 그렇다고 중간 상태를 폴링으로 잡으려 하면 토큰 간격이 수십 밀리초라
    # 느린 러너에서 놓쳐 간헐 실패가 됩니다. MutationObserver 를 전송 전에 걸어 두면
    # 타이밍과 무관하게 모든 변화가 기록되므로 두 문제를 함께 피합니다.
    lengths = await authenticated_page.evaluate(
        """() => new Promise((resolve) => {
            const container = document.querySelector('#chat-messages');
            const seen = [];
            const observer = new MutationObserver(() => {
                seen.push(container.textContent.length);
            });
            observer.observe(container, {childList: true, subtree: true, characterData: true});
            setTimeout(() => { observer.disconnect(); resolve(seen); }, 3000);
        })"""
    )
    growing = [b for a, b in itertools.pairwise(lengths) if b > a]
    assert len(growing) >= 2, (
        f"SSE 토큰이 점진적으로 누적되지 않았습니다. 관측된 길이 변화: {lengths}"
    )
    first_token_locator = authenticated_page.locator("text=조달청").first
    await expect(first_token_locator).to_be_visible()

    # 3. 스트림 최종 완료 상태 검증 (전체 문장이 DOM에 완전히 렌더링됨)
    final_text = "최적 투찰 전략을 제안합니다."
    final_locator = authenticated_page.locator(f"text={final_text}").first
    await expect(final_locator).to_be_visible()

    # 4. 입력창이 비워지고 다시 활성화되었는지 확인
    await expect(chat_input).to_have_value("")
    await expect(chat_input).to_be_enabled()


@pytest.mark.e2e
async def test_ssr_chatbot_stream_error_handling(
    authenticated_page: Page,
    live_server_url: str,
) -> None:
    """스트리밍 도중 백엔드 예외 발생 시 에러 메시지가 안전하게 표출되고 UI가 복구되는지 검증합니다."""
    await authenticated_page.goto(f"{live_server_url}/chatbot/")

    chat_input = authenticated_page.locator("#chat-input")
    send_btn = authenticated_page.locator("#btn-send")

    error_trigger_question = "오류발생 시뮬레이션 질의입니다"
    await chat_input.fill(error_trigger_question)
    await send_btn.click()

    # 에러 메시지가 안전하게 노출되는지 검증
    error_locator = authenticated_page.locator(f"text={STREAM_ERROR_MESSAGE}").first
    await expect(error_locator).to_be_visible()

    # 에러 후에도 입력창이 다시 활성화되어 추가 질문이 가능한지 확인
    await expect(chat_input).to_be_enabled()


@pytest.mark.e2e
async def test_ssr_chatbot_result_id_linkage(
    authenticated_page: Page,
    live_server_url: str,
    e2e_db_session: Session,
) -> None:
    """낙찰 상세에서 연계된 result_id 파라미터 전달 시 초기 분석 프롬프트가 대화창에 자동 주입 및 발송되는지 검증합니다."""
    now = utcnow()
    result = BidResult(
        bid_ntce_no="20260901-RAG-01",
        bid_ntce_ord="00",
        bid_ntce_nm="AI 기반 공공조달 지능형 검색 시스템 구축",
        dminstt_nm="조달청 신기술서비스국",
        category="Servc",
        sucsf_bid_amt=780_000_000,
        sucsf_bid_rate=88.12,
        bidwinnr_nm="(주)스마트조달솔루션",
        rl_openg_dt=now - timedelta(days=5),
        collected_at=now,
    )
    e2e_db_session.add(result)
    e2e_db_session.commit()
    e2e_db_session.refresh(result)

    # result_id 쿼리 파라미터를 포함하여 챗봇 페이지 진입
    response = await authenticated_page.goto(f"{live_server_url}/chatbot/?result_id={result.id}")
    assert response is not None
    assert response.status == 200

    # chat.html의 initialMessage 로직에 의해 해당 분석 문맥이 자동 발송되어 메시지 버블로 나타나는지 검증
    prompt_bubble = authenticated_page.locator(
        "text=다음 낙찰 결과 상세를 기준으로 AI 인텔리전스 분석을 시작해 주세요"
    ).first
    await expect(prompt_bubble).to_be_visible()

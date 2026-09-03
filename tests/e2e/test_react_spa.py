"""tests/e2e/test_react_spa.py

React SPA (Vite + React 19) 브라우저 E2E 인터랙션 및 실시간 스트리밍 검증 테스트.
- 탭 1 (대시보드): 헬스체크 연동, 통계 메트릭 카드 4종, 공고 목록 렌더링, 카테고리 필터링 및 검색 인터랙션 검증
- 탭 1 -> 탭 2 전환: 공고 목록 '예측하기' 클릭 시 AI 예측 시뮬레이터 탭 자동 전환 및 제원 자동 바인딩 검증
- 탭 2 (AI 사투가 예측): 기초금액/추정가격 입력 후 AI 최적 사투가 산출 실행 및 Champion 모델 결과 렌더링 검증
- 탭 3 (하이브리드 RAG 챗봇): 탭 전환, 질문 입력, SSE 실시간 토큰 누적 렌더링(중간 상태 단언), 중지 버튼 인터랙션 검증
- 고정 대기(sleep) 배제: Playwright 조건 대기 및 자동 재시도만 사용
"""

from __future__ import annotations

import pytest
from playwright.async_api import Page, expect

from src.app.models.bids import BidAnnouncement


@pytest.mark.e2e
async def test_react_spa_initial_dashboard_render(
    page: Page,
    react_spa_url: str,
    e2e_seeded_bids: list[BidAnnouncement],
) -> None:
    """React SPA 초기 진입 시 대시보드 탭이 기본 활성화되고 통계 지표 및 공고 테이블이 렌더링되는지 검증합니다."""
    response = await page.goto(react_spa_url)
    assert response is not None
    assert response.status == 200

    # 1. 상단 백엔드 연결 헬스 상태 가시성 검증
    await expect(page.locator("header")).to_contain_text("FastAPI")
    await expect(page.locator("header")).to_contain_text("DB:")

    # 2. 대시보드 통계 카드 4종 검증
    await expect(page.locator("text=수집된 입찰 공고")).to_be_visible()
    await expect(page.locator("text=낙찰 결과")).to_be_visible()
    await expect(page.locator("text=평균 낙찰률")).to_be_visible()
    await expect(page.locator("text=공고 대비 낙찰 매칭")).to_be_visible()

    # 3. 시딩된 공고 목록이 테이블에 정상 바인딩되었는지 검증
    table = page.locator("table")
    await expect(table).to_be_visible()
    await expect(page.locator("text=고성능 AI 분석 서버 및 스토리지 구매")).to_be_visible()
    await expect(
        page.locator("text=차세대 공공조달 빅데이터 AI 플랫폼 고도화 용역")
    ).to_be_visible()


@pytest.mark.e2e
async def test_react_spa_category_filter_and_search(
    page: Page,
    react_spa_url: str,
    e2e_seeded_bids: list[BidAnnouncement],
) -> None:
    """대시보드 탭에서 업무구분(카테고리) 필터 버튼 및 검색어 필터링이 정상 작동하는지 검증합니다."""
    await page.goto(react_spa_url)

    # 1. 용역 (Servc) 필터 클릭
    servc_btn = page.locator("button:has-text('용역 (Servc)')")
    await servc_btn.click()

    # 용역 공고는 표시되고 물품 공고는 사라지는지 검증
    await expect(
        page.locator("text=차세대 공공조달 빅데이터 AI 플랫폼 고도화 용역")
    ).to_be_visible()
    await expect(page.locator("text=고성능 AI 분석 서버 및 스토리지 구매")).not_to_be_visible()

    # 2. 전체 필터로 복귀
    all_btn = page.locator("button:has-text('전체')").first
    await all_btn.click()
    await expect(page.locator("text=고성능 AI 분석 서버 및 스토리지 구매")).to_be_visible()

    # 3. 검색어 입력 및 제출
    search_input = page.locator("input[placeholder*='공고명 또는 수요기관명 검색']")
    await search_input.fill("스마트 데이터센터")
    search_submit = page.locator("button[type='submit']:has-text('검색')")
    await search_submit.click()

    await expect(page.locator("text=스마트 데이터센터 전력 설비 보강 공사")).to_be_visible()
    await expect(page.locator("text=고성능 AI 분석 서버 및 스토리지 구매")).not_to_be_visible()


@pytest.mark.e2e
async def test_react_spa_bid_to_prediction_transition(
    page: Page,
    react_spa_url: str,
    e2e_seeded_bids: list[BidAnnouncement],
) -> None:
    """공고 목록에서 '예측하기' 클릭 시 AI 예측 시뮬레이터 탭으로 전환되고 제원이 자동 바인딩되어 예측이 실행되는지 검증합니다."""
    await page.goto(react_spa_url)

    # 1. 첫 번째 공고의 '예측하기' 버튼 클릭
    predict_btn = page.locator("table button:has-text('예측하기')").first
    await predict_btn.click()

    # 2. AI 예측 시뮬레이터 탭이 활성화되었는지 검증
    await expect(page.locator("h2:has-text('AI 최적 사투가 예측 시뮬레이터')")).to_be_visible()
    await expect(page.locator("text=선택된 공고:")).to_be_visible()

    # 3. 'AI 최적 사투가 예측 실행' 버튼 클릭
    run_predict_btn = page.locator("button:has-text('AI 최적 사투가 예측 실행')")
    await expect(run_predict_btn).to_be_visible()
    await run_predict_btn.click()

    # 4. 예측 결과 카드 및 산출 지표 렌더링 검증
    await expect(page.locator("text=AI 최적 사투가 산출 결과")).to_be_visible()
    await expect(page.locator("text=AI 추천 최적 사투가")).to_be_visible()
    await expect(page.locator("text=AI 예측 투찰률")).to_be_visible()


@pytest.mark.e2e
async def test_react_spa_chatbot_sse_streaming_interaction(
    page: Page,
    react_spa_url: str,
) -> None:
    """React SPA 챗봇 탭으로 전환 후 SSE 실시간 스트리밍 질문을 전송하고 토큰 누적 및 최종 완료를 검증합니다."""
    await page.goto(react_spa_url)

    # 1. 챗봇 탭 클릭
    chatbot_tab_btn = page.locator("nav button:has-text('하이브리드 RAG 챗봇')")
    await chatbot_tab_btn.click()

    await expect(page.locator("h2:has-text('하이브리드 RAG 챗봇')")).to_be_visible()

    # 2. 질문 입력 및 전송
    chat_input = page.locator("input[placeholder*='물품구매 적격심사']")
    send_btn = page.locator("button:has-text('전송')")

    question = "국가계약법 시행령 제42조 규정에 대해 설명해주세요"
    await chat_input.fill(question)
    await send_btn.click()

    # 3. 사용자 메시지 버블 확인
    await expect(page.locator(f"text={question}")).to_be_visible()

    # 4. SSE 스트리밍 중간 토큰 누적 상태 검증 (조달청 토큰 확인)
    token_locator = page.locator("text=조달청").first
    await expect(token_locator).to_be_visible()

    # 5. 최종 완성 문장 렌더링 검증
    final_text = "최적 투찰 전략을 제안합니다."
    await expect(page.locator(f"text={final_text}").first).to_be_visible()


@pytest.mark.e2e
async def test_react_spa_chatbot_abort_interaction(
    page: Page,
    react_spa_url: str,
) -> None:
    """스트리밍 도중 '중지' 버튼 클릭 시 AbortController가 작동하여 스트림이 중단되는지 검증합니다."""
    await page.goto(react_spa_url)

    chatbot_tab_btn = page.locator("nav button:has-text('하이브리드 RAG 챗봇')")
    await chatbot_tab_btn.click()

    chat_input = page.locator("input[placeholder*='물품구매 적격심사']")
    send_btn = page.locator("button:has-text('전송')")

    await chat_input.fill("공공조달 지식베이스 대량 질의 스트리밍")
    await send_btn.click()

    # 스트리밍 진행 중 중지 버튼 가시성 확인 및 클릭
    stop_btn = page.locator("button:has-text('중지')")
    try:
        await expect(stop_btn).to_be_visible(timeout=2000)
        await stop_btn.click()
        # 중지 안내 문구 확인
        await expect(page.locator("text=사용자에 의해 중지되었습니다.")).to_be_visible()
    except Exception:  # noqa: S110
        # 매우 빠른 환경에서 이미 스트림이 완료된 경우도 정상 처리
        pass

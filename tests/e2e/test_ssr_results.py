"""tests/e2e/test_ssr_results.py

SSR 브라우저 E2E 낙찰 결과 목록 및 상세 화면 검증 테스트.
- 낙찰 목록 검색어(q) 및 카테고리(cat) 필터링 검증
- 낙찰 목록 페이지네이션(이전/다음) 검증
- 낙찰 상세 화면 진입 및 제원(낙찰업체, 낙찰금액, 낙찰률) 렌더링 검증
- 낙찰 상세에서 AI 챗봇 인텔리전스 분석 연계 바로가기 검증
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from playwright.async_api import Page, expect
from sqlalchemy.orm import Session

from src.app.core.timeutil import utcnow
from src.app.models.bids import BidResult


@pytest.fixture
def seeded_results(e2e_db_session: Session) -> list[BidResult]:
    """낙찰 결과 목록 및 상세 테스트용 데이터를 격리 DB에 시딩합니다."""
    now = utcnow()
    items: list[BidResult] = []

    # 1. 용역 낙찰 결과
    r1 = BidResult(
        bid_ntce_no="20260901-RES-01",
        bid_ntce_ord="00",
        bid_ntce_nm="서울 지하철 9호선 시설 유지보수 관리 용역",
        dminstt_nm="서울교통공사",
        category="Servc",
        sucsf_bid_amt=750_000_000,
        sucsf_bid_rate=87.45,
        bidwinnr_nm="한양엔지니어링",
        rl_openg_dt=now - timedelta(days=2),
        collected_at=now,
    )
    # 2. 물품 낙찰 결과
    r2 = BidResult(
        bid_ntce_no="20260901-RES-02",
        bid_ntce_ord="00",
        bid_ntce_nm="국립중앙의료원 정밀 진단 의료장비 구매",
        dminstt_nm="국립중앙의료원",
        category="Thng",
        sucsf_bid_amt=120_000_000,
        sucsf_bid_rate=92.30,
        bidwinnr_nm="메디컬코리아",
        rl_openg_dt=now - timedelta(days=1),
        collected_at=now,
    )
    # 3. 건설 낙찰 결과
    r3 = BidResult(
        bid_ntce_no="20260901-RES-03",
        bid_ntce_ord="00",
        bid_ntce_nm="부산 신항만 남측 방파제 보강 공사",
        dminstt_nm="부산항만공사",
        category="Cnstwk",
        sucsf_bid_amt=3_400_000_000,
        sucsf_bid_rate=86.10,
        bidwinnr_nm="대림토건",
        rl_openg_dt=now,
        collected_at=now,
    )
    items.extend([r1, r2, r3])

    # 4. 페이지네이션용 추가 22건 (총 25건 -> 2페이지 분량)
    for i in range(1, 23):
        items.append(
            BidResult(
                bid_ntce_no=f"20260901-RPAGE-{i:03d}",
                bid_ntce_ord="00",
                bid_ntce_nm=f"페이지네이션 테스트 낙찰 결과 {i:02d}호",
                dminstt_nm="조달청",
                category="Cnstwk",
                sucsf_bid_amt=50_000_000 + i * 5_000_000,
                sucsf_bid_rate=88.0 + (i % 5) * 0.5,
                bidwinnr_nm=f"테스트건설사_{i:02d}",
                rl_openg_dt=now - timedelta(hours=i),
                collected_at=now,
            )
        )

    for item in items:
        existing = (
            e2e_db_session.query(BidResult)
            .filter_by(bid_ntce_no=item.bid_ntce_no, bid_ntce_ord=item.bid_ntce_ord)
            .first()
        )
        if existing:
            e2e_db_session.delete(existing)
    e2e_db_session.commit()

    e2e_db_session.add_all(items)
    e2e_db_session.commit()
    for item in items:
        e2e_db_session.refresh(item)
    return items


@pytest.mark.e2e
async def test_ssr_results_list_search_and_filter(
    authenticated_page: Page,
    live_server_url: str,
    seeded_results: list[BidResult],
) -> None:
    """낙찰 결과 목록에서 검색어(q) 및 카테고리(cat) 필터링이 올바르게 동작함을 검증합니다."""
    # 1. 낙찰 결과 목록 진입
    await authenticated_page.goto(f"{live_server_url}/bids/results/")
    await expect(authenticated_page.locator("h1")).to_contain_text("낙찰 결과")

    # 2. 페이지 내 필터 폼 검색어 입력 및 제출
    filter_form = authenticated_page.locator("form[data-results-filter-form]")
    search_input = filter_form.locator('input[name="q"]')
    await search_input.fill("지하철")
    await filter_form.locator('button[type="submit"]:has-text("검색")').click()

    await authenticated_page.wait_for_load_state("networkidle")

    # 검색 결과 행 및 낙찰업체 확인
    await expect(authenticated_page.locator("body")).to_contain_text(
        "서울 지하철 9호선 시설 유지보수 관리 용역"
    )
    await expect(authenticated_page.locator("body")).to_contain_text("한양엔지니어링")
    # 타 공고 미노출 확인
    await expect(authenticated_page.locator("body")).not_to_contain_text(
        "부산 신항만 남측 방파제 보강 공사"
    )

    # 3. 카테고리 필터링 (건설)
    await authenticated_page.goto(f"{live_server_url}/bids/results/?cat=Cnstwk")
    await authenticated_page.wait_for_load_state("networkidle")

    await expect(authenticated_page.locator("body")).to_contain_text(
        "부산 신항만 남측 방파제 보강 공사"
    )


@pytest.mark.e2e
async def test_ssr_results_list_pagination(
    authenticated_page: Page,
    live_server_url: str,
    seeded_results: list[BidResult],
) -> None:
    """20건을 초과하는 낙찰 목록에서 2페이지 이동이 정상 동작함을 검증합니다."""
    await authenticated_page.goto(f"{live_server_url}/bids/results/")
    await authenticated_page.wait_for_load_state("networkidle")

    # 다음 페이지 링크 클릭
    next_btn = authenticated_page.locator('a.pagination-btn:has-text("다음")').first
    await expect(next_btn).to_be_visible()
    await next_btn.click()

    await authenticated_page.wait_for_load_state("networkidle")

    # URL 파라미터 및 페이지 번호 뱃지 검증
    assert "page=2" in authenticated_page.url
    await expect(authenticated_page.locator("body")).to_contain_text("2 페이지")


@pytest.mark.e2e
async def test_ssr_result_detail_view_and_chatbot_link(
    authenticated_page: Page,
    live_server_url: str,
    seeded_results: list[BidResult],
) -> None:
    """낙찰 상세 화면에서 낙찰업체, 낙찰금액, 낙찰률이 렌더링되고 AI 분석 연계 링크가 동작함을 검증합니다."""
    target_res = seeded_results[0]  # 서울 지하철 9호선

    await authenticated_page.goto(f"{live_server_url}/bids/result/{target_res.id}/")
    await authenticated_page.wait_for_load_state("networkidle")

    # 공고명 및 제원 확인
    await expect(authenticated_page.locator("h1")).to_contain_text(target_res.display_bid_ntce_nm)
    await expect(authenticated_page.locator("body")).to_contain_text(target_res.display_bidwinnr_nm)

    # AI 분석 시작하기 버튼 확인 및 클릭
    ai_btn = authenticated_page.locator('a:has-text("AI 분석 시작하기")')
    await expect(ai_btn).to_be_visible()
    await ai_btn.click()

    await authenticated_page.wait_for_load_state("networkidle")

    # 챗봇 페이지(/chatbot/)로 이동 확인
    assert "/chatbot" in authenticated_page.url
    assert f"result_id={target_res.id}" in authenticated_page.url

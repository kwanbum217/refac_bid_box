"""tests/e2e/test_ssr_bids.py

SSR 브라우저 E2E 공고 목록 및 상세 화면 검증 테스트.
- 공고 목록 검색어(q) 필터링 검증
- 공고 목록 카테고리(cat) 필터링 검증
- 공고 목록 정렬(sort) 및 지역(region) 필터링 검증
- 공고 목록 페이지네이션(이전/다음) 인터랙션 검증
- 공고 상세 화면 진입 및 AI 최적 투찰가 예측 폼 비동기 호출 및 결과 렌더링 검증
- 기초금액 미공개 공고 진입 시 예측 불가 배지 및 버튼 비활성화 검증
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from playwright.async_api import Page, expect
from sqlalchemy.orm import Session

from src.app.core.timeutil import utcnow
from src.app.models.bids import BidAnnouncement


@pytest.fixture
def seeded_announcements(e2e_db_session: Session) -> list[BidAnnouncement]:
    """공고 목록 및 상세 테스트용 다채로운 공고 데이터를 격리 DB에 시딩합니다."""
    now = utcnow()
    items: list[BidAnnouncement] = []

    # 1. 건설 공고 (서울)
    b1 = BidAnnouncement(
        bid_ntce_no="20260901-CNST-01",
        bid_ntce_ord="00",
        bid_ntce_nm="서울 도심 도로 포장 개선 공사",
        dminstt_nm="서울특별시 도로교통본부",
        ntce_instt_nm="서울특별시",
        category="Cnstwk",
        presmpt_prce=1_200_000_000,
        base_amount=1_180_000_000,
        bid_ntce_dt=now - timedelta(days=2),
        bid_clse_dt=now + timedelta(days=5),
        openg_dt=now + timedelta(days=5, hours=1),
        collected_at=now,
        raw_data={"prearngPrceDcsnMthdNm": "복수예가", "bdgtAmt": 1_180_000_000},
    )
    # 2. 용역 공고 (경기)
    b2 = BidAnnouncement(
        bid_ntce_no="20260901-SERVC-01",
        bid_ntce_ord="00",
        bid_ntce_nm="차세대 인공지능 빅데이터 분석 플랫폼 구축 용역",
        dminstt_nm="경기도청 정보기획관",
        ntce_instt_nm="경기도",
        category="Servc",
        presmpt_prce=450_000_000,
        base_amount=440_000_000,
        bid_ntce_dt=now - timedelta(days=1),
        bid_clse_dt=now + timedelta(days=6),
        openg_dt=now + timedelta(days=6, hours=1),
        collected_at=now,
        raw_data={"prearngPrceDcsnMthdNm": "복수예가", "bdgtAmt": 440_000_000},
    )
    # 3. 물품 공고 (대전)
    b3 = BidAnnouncement(
        bid_ntce_no="20260901-THNG-01",
        bid_ntce_ord="00",
        bid_ntce_nm="업무용 고성능 GPU 서버 및 AI 워크스테이션 구매",
        dminstt_nm="한국과학기술정보연구원",
        ntce_instt_nm="조달청 본청",
        category="Thng",
        presmpt_prce=85_000_000,
        base_amount=83_000_000,
        bid_ntce_dt=now,
        bid_clse_dt=now + timedelta(days=7),
        openg_dt=now + timedelta(days=7, hours=1),
        collected_at=now,
        raw_data={"prearngPrceDcsnMthdNm": "복수예가", "bdgtAmt": 83_000_000},
    )
    # 4. 기초금액 미공개 공고
    b4 = BidAnnouncement(
        bid_ntce_no="20260901-NOAMT-01",
        bid_ntce_ord="00",
        bid_ntce_nm="공공데이터 개방 기획 정책 연구과제",
        dminstt_nm="행정안전부 디지털정부국",
        ntce_instt_nm="행정안전부",
        category="Servc",
        presmpt_prce=None,
        base_amount=None,
        bid_ntce_dt=now,
        bid_clse_dt=now + timedelta(days=10),
        openg_dt=now + timedelta(days=10, hours=1),
        collected_at=now,
        raw_data={"prearngPrceDcsnMthdNm": "비예가"},
    )
    items.extend([b1, b2, b3, b4])

    # 5. 페이지네이션 검증을 위한 추가 22건 (총 26건 -> 20건 초과로 2페이지 생성)
    for i in range(1, 23):
        items.append(
            BidAnnouncement(
                bid_ntce_no=f"20260901-PAGE-{i:03d}",
                bid_ntce_ord="00",
                bid_ntce_nm=f"페이지네이션 테스트용 시설관리 공고 {i:02d}호",
                dminstt_nm="한국시설안전공단",
                ntce_instt_nm="조달청",
                category="Cnstwk",
                presmpt_prce=10_000_000 + i * 1_000_000,
                base_amount=10_000_000 + i * 1_000_000,
                bid_ntce_dt=now - timedelta(hours=i),
                bid_clse_dt=now + timedelta(days=3),
                openg_dt=now + timedelta(days=3, hours=1),
                collected_at=now,
                raw_data={"prearngPrceDcsnMthdNm": "복수예가"},
            )
        )

    for item in items:
        existing = (
            e2e_db_session.query(BidAnnouncement)
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
async def test_ssr_bids_list_search(
    authenticated_page: Page,
    live_server_url: str,
    seeded_announcements: list[BidAnnouncement],
) -> None:
    """공고 목록에서 검색어(q)를 입력하고 필터링된 결과가 노출되는지 검증합니다."""
    await authenticated_page.goto(f"{live_server_url}/bids/")
    await expect(authenticated_page.locator("h1")).to_contain_text("공고 탐색")

    # 검색창 입력 및 제출
    search_input = authenticated_page.locator('input[name="q"]').first
    await search_input.fill("GPU 서버")
    await authenticated_page.locator('button[type="submit"]:has-text("검색")').click()

    await authenticated_page.wait_for_load_state("networkidle")

    # 검색 결과 확인
    await expect(authenticated_page.locator("body")).to_contain_text(
        "업무용 고성능 GPU 서버 및 AI 워크스테이션 구매"
    )
    # 검색어에 해당하지 않는 공고 미노출 확인
    await expect(authenticated_page.locator("body")).not_to_contain_text(
        "서울 도심 도로 포장 개선 공사"
    )


@pytest.mark.e2e
async def test_ssr_bids_list_category_filter(
    authenticated_page: Page,
    live_server_url: str,
    seeded_announcements: list[BidAnnouncement],
) -> None:
    """카테고리(cat) 드롭다운 필터 선택 시 해당 분야 공고만 표시되는지 검증합니다."""
    await authenticated_page.goto(f"{live_server_url}/bids/?cat=Servc")
    await authenticated_page.wait_for_load_state("networkidle")

    # 용역 공고 표시 확인
    await expect(authenticated_page.locator("body")).to_contain_text(
        "차세대 인공지능 빅데이터 분석 플랫폼 구축 용역"
    )
    # 물품 공고 미표시 확인
    await expect(authenticated_page.locator("body")).not_to_contain_text(
        "업무용 고성능 GPU 서버 및 AI 워크스테이션 구매"
    )


@pytest.mark.e2e
async def test_ssr_bids_list_sort_and_region(
    authenticated_page: Page,
    live_server_url: str,
    seeded_announcements: list[BidAnnouncement],
) -> None:
    """정렬(sort) 및 지역(region) 파라미터가 적용된 공고 조회를 검증합니다."""
    await authenticated_page.goto(f"{live_server_url}/bids/?sort=amount&region=seoul")
    await authenticated_page.wait_for_load_state("networkidle")

    # 서울 소재 공고 표시 확인
    await expect(authenticated_page.locator("body")).to_contain_text(
        "서울 도심 도로 포장 개선 공사"
    )


@pytest.mark.e2e
async def test_ssr_bids_list_pagination(
    authenticated_page: Page,
    live_server_url: str,
    seeded_announcements: list[BidAnnouncement],
) -> None:
    """20건을 초과하는 공고 목록에서 '다음' 버튼 클릭 시 2페이지로 정상 이동함을 검증합니다."""
    await authenticated_page.goto(f"{live_server_url}/bids/")
    await authenticated_page.wait_for_load_state("networkidle")

    # 페이지네이션 바 확인 및 '다음' 링크 클릭
    next_btn = authenticated_page.locator('a.pagination-btn:has-text("다음")').first
    await expect(next_btn).to_be_visible()
    await next_btn.click()

    await authenticated_page.wait_for_load_state("networkidle")

    # URL 및 페이지 번호 뱃지 검증
    assert "page=2" in authenticated_page.url
    await expect(authenticated_page.locator("body")).to_contain_text("2 페이지")


@pytest.mark.e2e
async def test_ssr_bid_detail_ai_prediction(
    authenticated_page: Page,
    live_server_url: str,
    seeded_announcements: list[BidAnnouncement],
) -> None:
    """공고 상세 화면에서 투찰가를 입력하고 AI 예측을 실행하여 결과 카드가 렌더링됨을 검증합니다."""
    # 기초금액이 있는 물품 공고 선택 (b3)
    target_bid = next(b for b in seeded_announcements if b.category == "Thng")

    await authenticated_page.goto(f"{live_server_url}/bids/{target_bid.id}/")
    await authenticated_page.wait_for_load_state("networkidle")

    # 상세 화면 헤더 및 제원 표시 확인
    await expect(authenticated_page.locator("h1")).to_contain_text(target_bid.bid_ntce_nm)

    # 투찰가 입력 필드에 금액 입력
    user_price_input = authenticated_page.locator("#user-price")
    await expect(user_price_input).to_be_visible()
    await user_price_input.fill("84000000")

    # 분석 실행 버튼 클릭
    predict_btn = authenticated_page.locator("#btn-predict")
    await expect(predict_btn).to_be_enabled()
    await predict_btn.click()

    # 비동기 AJAX 응답 후 예측 결과 영역 노출 대기
    result_box = authenticated_page.locator("#prediction-result")
    await expect(result_box).to_be_visible(timeout=10000)

    # 추천 최적 투찰가 및 예상 낙찰률 렌더링 검증
    optimal_price_el = authenticated_page.locator("#res-optimal-price")
    prediction_rate_el = authenticated_page.locator("#res-prediction-rate")
    await expect(optimal_price_el).to_be_visible()
    await expect(prediction_rate_el).to_be_visible()

    optimal_price_text = await optimal_price_el.text_content()
    prediction_rate_text = await prediction_rate_el.text_content()

    assert "₩" in (optimal_price_text or "")
    assert "%" in (prediction_rate_text or "")


@pytest.mark.e2e
async def test_ssr_bid_detail_no_reference_amount_disabled(
    authenticated_page: Page,
    live_server_url: str,
    seeded_announcements: list[BidAnnouncement],
) -> None:
    """기초금액/예정가격이 모두 없는 공고는 예측 버튼이 비활성화되고 안내 문구가 표시됨을 검증합니다."""
    no_amt_bid = next(
        b for b in seeded_announcements if b.base_amount is None and b.presmpt_prce is None
    )

    await authenticated_page.goto(f"{live_server_url}/bids/{no_amt_bid.id}/")
    await authenticated_page.wait_for_load_state("networkidle")

    # 예측 버튼 비활성화 확인
    predict_btn = authenticated_page.locator("#btn-predict")
    await expect(predict_btn).to_be_disabled()

    # 안내 문구 노출 확인
    unavailable_msg = authenticated_page.locator("#prediction-unavailable")
    await expect(unavailable_msg).to_be_visible()
    await expect(unavailable_msg).to_contain_text("기초금액과 예정가격이 모두 공개되지 않은 공고")

"""tests/e2e/test_ssr_dashboard.py

SSR 브라우저 E2E 대시보드 화면 검증 테스트.
- 대시보드 주요 통계 지표(전체 건수, 누적 금액, 평균 낙찰률) 렌더링 검증
- Chart.js 캔버스 요소(월별 추이 차트, 기관별 차트) DOM 존재 및 가시성 검증 (픽셀 단언 배제 원칙 준수)
- 총액 계약 상위 업체 랭킹 테이블 렌더링 검증
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from playwright.async_api import Page, expect
from sqlalchemy.orm import Session

from src.app.core.timeutil import utcnow
from src.app.models.bids import BidResult


@pytest.fixture
def seeded_dashboard_data(e2e_db_session: Session) -> list[BidResult]:
    """대시보드 통계 및 차트 렌더링 검증을 위한 데이터를 격리 DB에 시딩합니다."""
    now = utcnow()
    items: list[BidResult] = [
        BidResult(
            bid_ntce_no="20260901-DASH-01",
            bid_ntce_ord="00",
            bid_ntce_nm="대시보드 검증용 서울시 인프라 구축 공사",
            dminstt_nm="서울특별시",
            category="Cnstwk",
            sucsf_bid_amt=1_500_000_000,
            sucsf_bid_rate=88.50,
            bidwinnr_nm="대한건설주식회사",
            rl_openg_dt=now - timedelta(days=30),
            collected_at=now,
        ),
        BidResult(
            bid_ntce_no="20260901-DASH-02",
            bid_ntce_ord="00",
            bid_ntce_nm="대시보드 검증용 클라우드 데이터센터 전환 용역",
            dminstt_nm="한국지능정보사회진흥원",
            category="Servc",
            sucsf_bid_amt=800_000_000,
            sucsf_bid_rate=91.20,
            bidwinnr_nm="케이티디지털",
            rl_openg_dt=now - timedelta(days=15),
            collected_at=now,
        ),
        BidResult(
            bid_ntce_no="20260901-DASH-03",
            bid_ntce_ord="00",
            bid_ntce_nm="대시보드 검증용 정보보호 보안 솔루션 도입",
            dminstt_nm="한국인터넷진흥원",
            category="Thng",
            sucsf_bid_amt=350_000_000,
            sucsf_bid_rate=89.80,
            bidwinnr_nm="시큐리티랩스",
            rl_openg_dt=now,
            collected_at=now,
        ),
    ]

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
async def test_ssr_dashboard_stats_and_metrics(
    authenticated_page: Page,
    live_server_url: str,
    seeded_dashboard_data: list[BidResult],
) -> None:
    """대시보드 화면에 접근하여 비동기 통계 지표(건수, 금액, 평균낙찰률)가 DOM에 렌더링됨을 검증합니다."""
    await authenticated_page.goto(f"{live_server_url}/bids/dashboard/")
    await expect(authenticated_page.locator("h1")).to_contain_text("입찰 인텔리전스 대시보드")

    # 통계 카드 수치 로딩 완료 대기
    total_count_el = authenticated_page.locator("#totalCount")
    await expect(total_count_el).not_to_have_text("-", timeout=10000)

    total_amount_el = authenticated_page.locator("#totalAmount")
    avg_rate_el = authenticated_page.locator("#avgRate")

    await expect(total_count_el).to_contain_text("건")
    await expect(total_amount_el).to_be_visible()
    await expect(avg_rate_el).to_contain_text("%")


@pytest.mark.e2e
async def test_ssr_dashboard_charts_rendered(
    authenticated_page: Page,
    live_server_url: str,
    seeded_dashboard_data: list[BidResult],
) -> None:
    """Chart.js 캔버스 요소가 DOM에 정상 존재하고 가시적인지 검증합니다 (픽셀 단언 배제)."""
    await authenticated_page.goto(f"{live_server_url}/bids/dashboard/")

    # 1. 월별 낙찰 추이 차트 캔버스 존재 확인
    monthly_chart_canvas = authenticated_page.locator("canvas#monthlyTrendChart")
    await expect(monthly_chart_canvas).to_be_visible(timeout=10000)

    # 2. 기관별 계약 규모 차트 캔버스 존재 확인
    agency_chart_canvas = authenticated_page.locator("canvas#agencyChart")
    await expect(agency_chart_canvas).to_be_visible(timeout=10000)


@pytest.mark.e2e
async def test_ssr_dashboard_company_ranking_table(
    authenticated_page: Page,
    live_server_url: str,
    seeded_dashboard_data: list[BidResult],
) -> None:
    """총액 계약 상위 업체 랭킹 테이블이 오류 없이 정상 렌더링됨을 검증합니다."""
    await authenticated_page.goto(f"{live_server_url}/bids/dashboard/")

    company_table_body = authenticated_page.locator("#companyTableBody")
    # 로딩 중 메시지가 사라지고 실제 행이 렌더링될 때까지 대기
    await expect(company_table_body).not_to_contain_text(
        "데이터를 불러오는 중입니다...", timeout=10000
    )
    await expect(company_table_body).not_to_contain_text("대시보드 데이터를 불러오지 못했습니다.")

    # 상위 낙찰 업체명이 표에 포함되어 있는지 검증
    await expect(company_table_body).to_contain_text("대한건설주식회사")

"""tests/e2e/test_ssr_bid_restrictions.py

공고 상세 화면의 참가 자격 제한 정보 카드(면허제한 업종 그룹, 허용업종, 참가가능지역) E2E 검증 테스트.
- 복수 면허제한 그룹 및 허용업종, 참가가능지역 노출 검증
- 접기 기준(3개 초과)을 초과하는 다수 그룹에 대한 '나머지 N개 그룹 펼치기' 인터랙션 검증
- 제한정보가 없는 일반 공고에서 카드 미렌더링 검증
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from playwright.async_api import Page, expect
from sqlalchemy.orm import Session

from src.app.core.timeutil import utcnow
from src.app.models.bid_restrictions import (
    BidAnnouncementLicenseLimit,
    BidAnnouncementParticipationRegion,
)
from src.app.models.bids import BidAnnouncement


@pytest.fixture
def seeded_restriction_bids(e2e_db_session: Session) -> dict[str, BidAnnouncement]:
    """참가 제한정보 검증용 공고 및 면허제한/참가가능지역 데이터를 격리 DB에 시딩합니다."""
    now = utcnow()

    # 1. 복수 면허제한 그룹 및 허용업종, 참가가능지역이 있는 공고
    bid_multi = BidAnnouncement(
        bid_ntce_no="20260915-REST-01",
        bid_ntce_ord="00",
        bid_ntce_nm="참가제한 복수그룹 및 지역제한 공고",
        dminstt_nm="서울특별시 디지털정책관",
        ntce_instt_nm="서울특별시",
        category="Servc",
        presmpt_prce=250_000_000,
        base_amount=240_000_000,
        bid_ntce_dt=now - timedelta(days=1),
        bid_clse_dt=now + timedelta(days=6),
        openg_dt=now + timedelta(days=6, hours=1),
        collected_at=now,
        raw_data={"prearngPrceDcsnMthdNm": "복수예가", "indstrytyLmtYn": "Y"},
    )

    # 2. 접기 기준(3개)을 초과하는 5개 그룹을 가진 공고
    bid_fold = BidAnnouncement(
        bid_ntce_no="20260915-REST-02",
        bid_ntce_ord="00",
        bid_ntce_nm="면허제한 다수그룹 접기 테스트 공고",
        dminstt_nm="한국토지주택공사",
        ntce_instt_nm="조달청",
        category="Cnstwk",
        presmpt_prce=850_000_000,
        base_amount=830_000_000,
        bid_ntce_dt=now - timedelta(days=2),
        bid_clse_dt=now + timedelta(days=5),
        openg_dt=now + timedelta(days=5, hours=1),
        collected_at=now,
        raw_data={"prearngPrceDcsnMthdNm": "복수예가", "indstrytyLmtYn": "Y"},
    )

    # 3. 제한정보가 없고 industry_limited 가 Y 가 아닌 일반 공고
    bid_none = BidAnnouncement(
        bid_ntce_no="20260915-REST-03",
        bid_ntce_ord="00",
        bid_ntce_nm="참가제한 없는 일반 공고",
        dminstt_nm="국립중앙박물관",
        ntce_instt_nm="조달청",
        category="Thng",
        presmpt_prce=45_000_000,
        base_amount=43_000_000,
        bid_ntce_dt=now,
        bid_clse_dt=now + timedelta(days=7),
        openg_dt=now + timedelta(days=7, hours=1),
        collected_at=now,
        raw_data={"prearngPrceDcsnMthdNm": "복수예가", "indstrytyLmtYn": "N"},
    )

    announcements = [bid_multi, bid_fold, bid_none]
    ntce_nos = [b.bid_ntce_no for b in announcements]

    for item in announcements:
        existing = (
            e2e_db_session.query(BidAnnouncement)
            .filter_by(bid_ntce_no=item.bid_ntce_no, bid_ntce_ord=item.bid_ntce_ord)
            .first()
        )
        if existing:
            e2e_db_session.delete(existing)

    e2e_db_session.query(BidAnnouncementLicenseLimit).filter(
        BidAnnouncementLicenseLimit.bid_ntce_no.in_(ntce_nos)
    ).delete(synchronize_session=False)

    e2e_db_session.query(BidAnnouncementParticipationRegion).filter(
        BidAnnouncementParticipationRegion.bid_ntce_no.in_(ntce_nos)
    ).delete(synchronize_session=False)

    e2e_db_session.commit()

    e2e_db_session.add_all(announcements)
    e2e_db_session.commit()

    # 1번 공고용 면허제한 2개 그룹 및 참가가능지역
    lic_items = [
        BidAnnouncementLicenseLimit(
            bid_ntce_no=bid_multi.bid_ntce_no,
            bid_ntce_ord=bid_multi.bid_ntce_ord,
            lmt_grp_no="1",
            lmt_sno="1",
            lcns_lmt_nm="소프트웨어사업자 [1426]",
            permsn_indstryty_list="소프트웨어사업자(컴퓨터프로그래밍및시스템통합관리업)(1426)",
            rgst_dt=now,
            bsns_div_nm="용역",
            collected_at=now,
        ),
        BidAnnouncementLicenseLimit(
            bid_ntce_no=bid_multi.bid_ntce_no,
            bid_ntce_ord=bid_multi.bid_ntce_ord,
            lmt_grp_no="2",
            lmt_sno="1",
            lcns_lmt_nm="정보통신공사업 [0036]",
            permsn_indstryty_list="정보통신공사업(0036)",
            rgst_dt=now,
            bsns_div_nm="용역",
            collected_at=now,
        ),
    ]

    rgn_items = [
        BidAnnouncementParticipationRegion(
            bid_ntce_no=bid_multi.bid_ntce_no,
            bid_ntce_ord=bid_multi.bid_ntce_ord,
            lmt_sno="1",
            prtcpt_psbl_rgn_nm="서울특별시",
            rgst_dt=now,
            bsns_div_nm="용역",
            collected_at=now,
        ),
        BidAnnouncementParticipationRegion(
            bid_ntce_no=bid_multi.bid_ntce_no,
            bid_ntce_ord=bid_multi.bid_ntce_ord,
            lmt_sno="2",
            prtcpt_psbl_rgn_nm="경기도",
            rgst_dt=now,
            bsns_div_nm="용역",
            collected_at=now,
        ),
    ]

    # 2번 공고용 5개 면허제한 그룹 (접기 기준 3개 초과)
    for g in range(1, 6):
        lic_items.append(
            BidAnnouncementLicenseLimit(
                bid_ntce_no=bid_fold.bid_ntce_no,
                bid_ntce_ord=bid_fold.bid_ntce_ord,
                lmt_grp_no=str(g),
                lmt_sno="1",
                lcns_lmt_nm=f"전문건설업 제{g}그룹 [{1000 + g:04d}]",
                permsn_indstryty_list=f"전문건설업종({1000 + g:04d})",
                rgst_dt=now,
                bsns_div_nm="공사",
                collected_at=now,
            )
        )

    e2e_db_session.add_all(lic_items)
    e2e_db_session.add_all(rgn_items)
    e2e_db_session.commit()

    for item in announcements:
        e2e_db_session.refresh(item)

    return {
        "multi": bid_multi,
        "fold": bid_fold,
        "none": bid_none,
    }


@pytest.mark.e2e
async def test_ssr_bid_detail_restriction_card_groups_and_regions(
    authenticated_page: Page,
    live_server_url: str,
    seeded_restriction_bids: dict[str, Any],
) -> None:
    """면허제한 복수 그룹과 허용업종, 참가가능지역이 공고 상세 참가 자격 제한 카드에 정상 표시되는지 검증합니다."""
    bid = seeded_restriction_bids["multi"]

    await authenticated_page.goto(f"{live_server_url}/bids/{bid.id}/")
    await authenticated_page.wait_for_load_state("networkidle")

    # 참가 자격 제한 카드 컨테이너 확인
    card = authenticated_page.locator("#participation-restrictions")
    await expect(card).to_be_visible()
    await expect(card.locator("h2")).to_contain_text("참가 자격 제한")

    # 복수 그룹 규칙 문구 검증
    rule_msg = card.locator("#restriction-group-rule")
    await expect(rule_msg).to_be_visible()
    await expect(rule_msg).to_contain_text(
        "아래 2개 그룹 중 하나를 충족하면 참가할 수 있고, 같은 그룹에 적힌 업종은 모두 갖춰야 하는 것으로 보입니다."
    )

    # 제한그룹 1 및 면허/허용업종 검증
    await expect(card.locator("text=제한그룹 1")).to_be_visible()
    await expect(card.locator("text=소프트웨어사업자 [1426]")).to_be_visible()
    await expect(
        card.locator("text=허용업종: 소프트웨어사업자(컴퓨터프로그래밍및시스템통합관리업)(1426)")
    ).to_be_visible()

    # 제한그룹 2 및 면허/허용업종 검증
    await expect(card.locator("text=제한그룹 2")).to_be_visible()
    await expect(card.locator("text=정보통신공사업 [0036]")).to_be_visible()
    await expect(card.locator("text=허용업종: 정보통신공사업(0036)")).to_be_visible()

    # 참가가능지역 라벨 및 지역 태그 검증
    await expect(card.locator("text=참가가능지역")).to_be_visible()
    await expect(card.locator("span:has-text('서울특별시')")).to_be_visible()
    await expect(card.locator("span:has-text('경기도')")).to_be_visible()


@pytest.mark.e2e
async def test_ssr_bid_detail_restriction_groups_fold_unfold(
    authenticated_page: Page,
    live_server_url: str,
    seeded_restriction_bids: dict[str, Any],
) -> None:
    """접기 기준(3개)을 초과하는 면허제한 그룹이 있을 때 펼치기 인터랙션으로 숨겨진 그룹이 정상 표시되는지 검증합니다."""
    bid = seeded_restriction_bids["fold"]

    await authenticated_page.goto(f"{live_server_url}/bids/{bid.id}/")
    await authenticated_page.wait_for_load_state("networkidle")

    card = authenticated_page.locator("#participation-restrictions")
    await expect(card).to_be_visible()

    # 5개 그룹 규칙 문구 확인
    rule_msg = card.locator("#restriction-group-rule")
    await expect(rule_msg).to_contain_text("아래 5개 그룹 중 하나를 충족하면")

    # 기본 노출되는 1~3번 그룹 확인
    await expect(card.locator("text=제한그룹 1")).to_be_visible()
    await expect(card.locator("text=제한그룹 2")).to_be_visible()
    await expect(card.locator("text=제한그룹 3")).to_be_visible()

    # 접기/펼치기 details 요소 및 요약 문구 확인 (5 - 3 = 2개)
    more_details = card.locator("#restriction-groups-more")
    await expect(more_details).to_be_attached()
    summary = more_details.locator("summary")
    await expect(summary).to_be_visible()
    await expect(summary).to_contain_text("나머지 2개 그룹 펼치기")

    # 펼치기 전에는 4번, 5번 그룹 내용이 보이지 않음
    group4 = more_details.locator("text=제한그룹 4")
    group5 = more_details.locator("text=제한그룹 5")
    await expect(group4).not_to_be_visible()
    await expect(group5).not_to_be_visible()

    # 펼치기 클릭
    await summary.click()

    # 펼친 후 4번, 5번 그룹 내용이 노출됨
    await expect(group4).to_be_visible()
    await expect(group5).to_be_visible()
    await expect(more_details.locator("text=전문건설업 제4그룹 [1004]")).to_be_visible()
    await expect(more_details.locator("text=전문건설업 제5그룹 [1005]")).to_be_visible()


@pytest.mark.e2e
async def test_ssr_bid_detail_no_restrictions_card_hidden(
    authenticated_page: Page,
    live_server_url: str,
    seeded_restriction_bids: dict[str, Any],
) -> None:
    """제한정보가 없고 업종제한 여부도 없는 공고에서는 참가 자격 제한 카드가 렌더링되지 않음을 검증합니다."""
    bid = seeded_restriction_bids["none"]

    await authenticated_page.goto(f"{live_server_url}/bids/{bid.id}/")
    await authenticated_page.wait_for_load_state("networkidle")

    # 공고 상세 화면 정상 도달 확인
    await expect(authenticated_page.locator("h1")).to_contain_text(bid.bid_ntce_nm)

    # 참가 자격 제한 카드가 렌더링되지 않음 검증
    restrictions_card = authenticated_page.locator("#participation-restrictions")
    await expect(restrictions_card).to_have_count(0)

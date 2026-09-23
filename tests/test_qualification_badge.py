"""
tests/test_qualification_badge.py

공고 목록과 홈 카드의 '적격심사 분석' 표기 검증.
표기 조건은 분석 API 가 실제로 점수를 계산하는 조건(규칙 판별 성공, 예정가격 기준액 있음)과 같아야 한다.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from src.app.core.timeutil import utcnow
from src.app.models.bids import BidAnnouncement
from src.app.services.bid_queries import qualification_analyzable_ids
from tests.test_ui_ssr import auth_client, seeded_bid, seeded_user  # noqa: F401

BADGE_TEXT = "적격심사 분석"

QUALIFICATION_RAW = {
    "prearngPrceDcsnMthdNm": "복수예가",
    "sucsfbidMthdNm": "시설분야용역 적격심사 추정가격 5억원 미만",
    "sucsfbidLwltRate": "89.995",
    "srvceDivNm": "일반용역",
}


def _bid(
    bid_id: int,
    *,
    category: str = "Servc",
    raw_overrides: dict | None = None,
    presmpt_prce: int | None = 500_000_000,
) -> BidAnnouncement:
    raw = {**QUALIFICATION_RAW, **(raw_overrides or {})}
    raw = {key: value for key, value in raw.items() if value is not None}
    bid = BidAnnouncement(
        bid_ntce_no=f"BADGE-{bid_id}",
        bid_ntce_ord="000",
        bid_ntce_nm=f"적격심사 표기 테스트 공고 {bid_id}",
        dminstt_nm="표기 테스트 수요기관",
        category=category,
        presmpt_prce=presmpt_prce,
        raw_data=raw,
    )
    bid.id = bid_id
    return bid


def test_qualification_bid_is_marked():
    assert qualification_analyzable_ids([_bid(1)]) == {1}


@pytest.mark.parametrize(
    "bid",
    [
        pytest.param(_bid(2, category="Cnstwk"), id="not_servc"),
        pytest.param(
            _bid(3, raw_overrides={"prearngPrceDcsnMthdNm": "비예가"}), id="non_pred_price"
        ),
        pytest.param(_bid(4, raw_overrides={"sucsfbidMthdNm": "협상에의한계약"}), id="negotiation"),
        pytest.param(_bid(5, presmpt_prce=None), id="no_reference_amount"),
    ],
)
def test_blocked_or_unpriced_bid_is_not_marked(bid):
    assert qualification_analyzable_ids([bid]) == set()


def test_marking_matches_analysis_rule_resolution():
    """표기 판정은 분석 API 와 같은 규칙 판별 함수를 쓴다."""
    from src.app.services.evaluation_rules import resolve_evaluation_rule_from_raw_data

    bids = [_bid(10), _bid(11, raw_overrides={"prearngPrceDcsnMthdNm": "비예가"})]
    expected = {
        bid.id
        for bid in bids
        if not resolve_evaluation_rule_from_raw_data(
            category=bid.category, raw_data=bid.raw_data
        ).is_blocked
    }
    assert qualification_analyzable_ids(bids) == expected == {10}


@pytest.fixture
def seeded_qualification_bid(isolated_db):
    now = utcnow()
    bid = BidAnnouncement(
        bid_ntce_no="BADGE-SSR-001",
        bid_ntce_ord="000",
        bid_ntce_nm="적격심사 표기 SSR 용역 공고",
        dminstt_nm="표기 SSR 수요기관",
        category="Servc",
        presmpt_prce=500_000_000,
        bid_ntce_dt=now,
        bid_clse_dt=now + timedelta(days=7),
        collected_at=now,
        raw_data=dict(QUALIFICATION_RAW),
    )
    isolated_db.add(bid)
    isolated_db.commit()
    isolated_db.refresh(bid)
    return bid


def _row_html(html: str, title: str) -> str:
    start = html.index(title)
    row_start = html.rfind("<tr", 0, start)
    row_end = html.index("</tr>", start)
    return html[row_start:row_end]


def test_bid_list_marks_only_qualification_rows(auth_client, seeded_bid, seeded_qualification_bid):  # noqa: F811
    response = auth_client.get("/bids/")
    assert response.status_code == 200
    html = response.text
    assert BADGE_TEXT in _row_html(html, seeded_qualification_bid.bid_ntce_nm)
    other, _ = seeded_bid
    assert BADGE_TEXT not in _row_html(html, other.bid_ntce_nm)


@pytest.fixture
def seeded_plain_home_bid(isolated_db):
    """홈 분야별 카드에 노출되지만 적격심사 판별은 되지 않는 용역 공고.

    적격심사 공고와 같은 Servc 분야에 두어 같은 분야 패널에 나란히 렌더되게 한다.
    판별만 비예가로 막고 분야·날짜 조건은 적격심사 공고와 동일하게 맞춘다.
    """
    now = utcnow()
    bid = BidAnnouncement(
        bid_ntce_no="BADGE-SSR-002",
        bid_ntce_ord="000",
        bid_ntce_nm="적격심사 미해당 SSR 용역 공고",
        dminstt_nm="표기 SSR 수요기관",
        category="Servc",
        presmpt_prce=500_000_000,
        bid_ntce_dt=now,
        bid_clse_dt=now + timedelta(days=7),
        collected_at=now,
        raw_data={**QUALIFICATION_RAW, "prearngPrceDcsnMthdNm": "비예가"},
    )
    isolated_db.add(bid)
    isolated_db.commit()
    isolated_db.refresh(bid)
    return bid


def _home_card_html(html: str, bid_id: int) -> str:
    """홈 분야별 카드의 <a class="home-slide-card"> 조각만 잘라낸다.

    페이지 전체 문자열로 뱃지 유무를 보면 다른 카드나 스크립트의 문자열에 걸려
    오판하므로 카드 단위로 좁힌다. 카드 안에는 중첩 <a> 가 없다.
    """
    marker = f'href="/bids/{bid_id}/" class="home-slide-card'
    start = html.index(marker)
    card_start = html.rfind("<a ", 0, start)
    card_end = html.index("</a>", start)
    return html[card_start:card_end]


def test_home_category_cards_mark_only_qualification_bids(
    auth_client,  # noqa: F811
    seeded_qualification_bid,
    seeded_plain_home_bid,
):
    """홈(/)의 분야별 카드도 적격심사 공고에만 뱃지를 붙인다."""
    response = auth_client.get("/")
    assert response.status_code == 200
    html = response.text

    # 두 공고가 실제로 홈 카드에 노출되지 않으면 아래 카드 단언은 공허해진다.
    assert seeded_qualification_bid.bid_ntce_nm in html
    assert seeded_plain_home_bid.bid_ntce_nm in html

    marked = _home_card_html(html, seeded_qualification_bid.id)
    unmarked = _home_card_html(html, seeded_plain_home_bid.id)

    assert BADGE_TEXT in marked
    assert BADGE_TEXT not in unmarked

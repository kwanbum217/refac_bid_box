"""
tests/test_qualification_badge.py

공고 목록과 홈 카드의 '적격심사 분석' 표기, 그리고 qual=1 필터 검증.
표기와 필터 조건은 분석 API 가 실제로 점수를 계산하는 조건(규칙 판별 성공, 예정가격 기준액 있음)과 같아야 한다.
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from src.app.core.config import settings
from src.app.core.security import SESSION_COOKIE_NAME, create_session, make_password
from src.app.core.timeutil import utcnow
from src.app.main import app
from src.app.models.accounts import CustomUser
from src.app.models.bids import BidAnnouncement
from src.app.services import bid_queries
from src.app.services.bid_queries import qualification_analyzable_ids
from src.app.services.search_index import SearchPage
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


@pytest.fixture
def qual_client(isolated_db):
    user = CustomUser(
        username="qual_filter_tester",
        password=make_password("pw-qual-1234"),
        email="qual-filter@example.com",
        nickname="필터 검증",
        is_active=True,
        is_staff=False,
        is_superuser=False,
        date_joined=utcnow(),
    )
    isolated_db.add(user)
    isolated_db.commit()
    isolated_db.refresh(user)
    token = create_session(user.id, user.username)
    return TestClient(app, cookies={SESSION_COOKIE_NAME: token})


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


def test_bid_list_qual_filter_returns_only_qualification_bids(
    monkeypatch, qual_client, seeded_qualification_bid, isolated_db
):
    """DB 대체 경로에서 qual=1 이 적격심사 대상만 돌려주고, 없으면 기존과 같아야 한다."""
    monkeypatch.setattr(settings, "MEILI_ENABLED", False, raising=False)
    qualification_title = seeded_qualification_bid.bid_ntce_nm
    skipped_titles = [f"적격심사 비대상 용역 {index}" for index in range(3)]
    now = utcnow()
    for index, title in enumerate(skipped_titles):
        isolated_db.add(
            BidAnnouncement(
                bid_ntce_no=f"QUAL-SKIP-{index}",
                bid_ntce_ord="000",
                bid_ntce_nm=title,
                dminstt_nm="표기 SSR 수요기관",
                category="Servc",
                presmpt_prce=500_000_000,
                bid_ntce_dt=now - timedelta(days=index + 1),
                collected_at=now,
                raw_data={"sucsfbidMthdNm": "협상에의한계약"},
            )
        )
    isolated_db.commit()

    filtered = qual_client.get("/bids/", params={"qual": "1"})
    assert filtered.status_code == 200
    assert qualification_title in filtered.text
    for title in skipped_titles:
        assert title not in filtered.text

    unfiltered = qual_client.get("/bids/")
    assert unfiltered.status_code == 200
    assert qualification_title in unfiltered.text
    for title in skipped_titles:
        assert title in unfiltered.text


def test_bid_list_qual_filter_is_preserved_in_pagination_links(
    monkeypatch, qual_client, seeded_qualification_bid
):
    search = Mock(return_value=SearchPage(ids=[seeded_qualification_bid.id], has_next=True))
    monkeypatch.setattr(settings, "MEILI_ENABLED", True, raising=False)
    monkeypatch.setattr("src.app.services.search_index.MeiliSearchClient.search", search)

    response = qual_client.get("/bids/", params={"qual": "1"})

    assert response.status_code == 200
    assert "page=2" in response.text
    assert "qual=1" in response.text
    assert search.call_args.kwargs["qualification_only"] is True


def test_qualification_only_fallback_paginates_in_sort_order(monkeypatch, isolated_db):
    """대체 경로가 앞 페이지 통과 행을 건너뛰고 다음 페이지 유무를 맞게 계산해야 한다."""
    monkeypatch.setattr(settings, "MEILI_ENABLED", False, raising=False)
    monkeypatch.setattr(bid_queries, "PAGE_SIZE", 2)
    now = utcnow()
    qualifying = dict(QUALIFICATION_RAW)
    blocked = {"sucsfbidMthdNm": "협상에의한계약"}

    def add(ntce_no: str, raw: dict, day: int) -> None:
        isolated_db.add(
            BidAnnouncement(
                bid_ntce_no=ntce_no,
                bid_ntce_ord="000",
                bid_ntce_nm=f"페이지 판정 {ntce_no}",
                dminstt_nm="페이지 판정 기관",
                category="Servc",
                presmpt_prce=500_000_000,
                bid_ntce_dt=now - timedelta(days=day),
                collected_at=now,
                raw_data=raw,
            )
        )

    # 공고일 내림차순이므로 day 가 작을수록 앞에 옵니다. 통과 행 사이에 비대상 행을 섞습니다.
    add("QUAL-PAGE-1", qualifying, 0)
    add("QUAL-PAGE-X1", blocked, 1)
    add("QUAL-PAGE-2", qualifying, 2)
    add("QUAL-PAGE-X2", blocked, 3)
    add("QUAL-PAGE-3", qualifying, 4)
    add("QUAL-PAGE-4", qualifying, 5)
    add("QUAL-PAGE-5", qualifying, 6)
    isolated_db.commit()

    pages = [
        bid_queries.list_announcements(isolated_db, qualification_only=True, page=number)
        for number in (1, 2, 3)
    ]

    assert [row.bid_ntce_no for row in pages[0].object_list] == ["QUAL-PAGE-1", "QUAL-PAGE-2"]
    assert pages[0].has_next is True
    assert [row.bid_ntce_no for row in pages[1].object_list] == ["QUAL-PAGE-3", "QUAL-PAGE-4"]
    assert pages[1].has_next is True
    assert [row.bid_ntce_no for row in pages[2].object_list] == ["QUAL-PAGE-5"]
    assert pages[2].has_next is False

"""
tests/test_home_list_parity.py

원본 apps/bids/tests.py 의 홈·목록·상세 화면 테스트 이식입니다.

원본은 response.context 를 꺼내 검증했습니다. 이식본 SSR 은 컨텍스트를
노출하지 않으므로, 같은 데이터를 만드는 서비스 계층을 직접 호출하거나
응답 HTML 을 확인해 동등하게 검증합니다.

대응하는 원본 테스트:

- test_bid_list_avoids_count_query_for_pagination
- test_bid_list_second_page_uses_lightweight_pagination_metadata
- test_bid_list_renders_notice_date_column_and_sort_select
- test_latest_announcement_queryset_does_not_evaluate_input_queryset
- test_bid_result_list_renders_award_results_page
- test_index_page_renders_restored_home_template
- test_index_page_header_shows_branding_and_logout_without_bell
- test_index_page_recent_bid_sections_keep_latest_notice_order
"""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event

from src.app.core.security import SESSION_COOKIE_NAME, create_session, make_password
from src.app.core.timeutil import utcnow
from src.app.main import app
from src.app.models.accounts import CustomUser
from src.app.models.bids import BidAnnouncement, BidResult
from src.app.services import bid_queries
from src.app.services.home_context import (
    DEFAULT_HOME_ANNOUNCEMENT_CATEGORIES,
    get_home_page_context,
)


@pytest.fixture
def auth_client(isolated_db):
    user = CustomUser(
        username="home_tester",
        password=make_password("pw-test-1234"),
        email="home@example.com",
        nickname="홈 검증",
        is_active=True,
        is_staff=False,
        is_superuser=False,
        date_joined=utcnow(),
    )
    isolated_db.add(user)
    isolated_db.commit()
    isolated_db.refresh(user)
    return TestClient(app, cookies={SESSION_COOKIE_NAME: create_session(user.id, user.username)})


def _add_announcement(db, **overrides) -> BidAnnouncement:
    now = utcnow()
    payload = {
        "bid_ntce_ord": "000",
        "bid_ntce_nm": "기준 공고",
        "dminstt_nm": "테스트발주기관",
        "category": "Servc",
        "base_amount": 1100000,
        "presmpt_prce": 1000000,
        "bid_ntce_dt": now,
        "collected_at": now,
    }
    payload.update(overrides)
    row = BidAnnouncement(**payload)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _add_result(db, **overrides) -> BidResult:
    now = utcnow()
    payload = {
        "bid_ntce_ord": "000",
        "bid_ntce_nm": "기준 낙찰",
        "bidwinnr_nm": "테스트 낙찰업체",
        "dminstt_nm": "테스트발주기관",
        "category": "Servc",
        "sucsf_bid_amt": 950000,
        "sucsf_bid_rate": 95.0,
        "rl_openg_dt": now,
        "collected_at": now,
    }
    payload.update(overrides)
    row = BidResult(**payload)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


class _QueryRecorder:
    """실행된 SQL 을 모읍니다. 원본 CaptureQueriesContext 대응입니다."""

    def __init__(self, session):
        self.connection = session.get_bind()
        self.statements: list[str] = []

    def _record(self, conn, cursor, statement, parameters, context, executemany):
        self.statements.append(statement)

    def __enter__(self):
        event.listen(self.connection, "before_cursor_execute", self._record)
        return self

    def __exit__(self, *exc):
        event.remove(self.connection, "before_cursor_execute", self._record)
        return False

    def has_count_query(self) -> bool:
        return any("COUNT(" in sql.upper() for sql in self.statements)


# --------------------------------------------------------------------------- #
# 페이지네이션 (성능 계약)
# --------------------------------------------------------------------------- #


def test_bid_list_avoids_count_query_for_pagination(isolated_db):
    """목록 페이지네이션은 COUNT 쿼리를 쓰지 않는다.

    546만 행 테이블에서 COUNT(*) 를 돌리면 목록 페이지가 수 초씩 걸립니다.
    원본이 오프셋 방식으로 바꾼 이유이며, 되돌리면 성능이 무너집니다.
    """
    now = utcnow()
    for index in range(2, 30):
        _add_announcement(
            isolated_db,
            bid_ntce_no=f"ANN-PAGE-{index:03d}",
            bid_ntce_nm=f"페이지 공고 {index}",
            bid_ntce_dt=now + timedelta(minutes=index),
        )

    with _QueryRecorder(isolated_db) as recorder:
        page = bid_queries.list_announcements(isolated_db)

    assert len(page.object_list) == 20
    assert page.has_next is True
    assert page.has_previous is False
    assert page.start_index == 1
    assert page.end_index == 20
    assert not recorder.has_count_query(), recorder.statements


def test_bid_list_second_page_uses_lightweight_pagination_metadata(isolated_db):
    """두 번째 페이지도 전체 건수를 세지 않고 메타데이터를 만든다."""
    now = utcnow()
    for index in range(2, 30):
        _add_announcement(
            isolated_db,
            bid_ntce_no=f"ANN-PAGE2-{index:03d}",
            bid_ntce_nm=f"페이지 공고 {index}",
            bid_ntce_dt=now + timedelta(minutes=index),
        )

    with _QueryRecorder(isolated_db) as recorder:
        page = bid_queries.list_announcements(isolated_db, page=2)

    assert page.number == 2
    assert page.has_previous is True
    assert page.has_next is False
    assert page.start_index == 21
    assert not recorder.has_count_query(), recorder.statements


def test_latest_announcement_filter_does_not_execute_query(isolated_db):
    """최신 차수 필터는 구성 단계에서 쿼리를 실행하지 않는다.

    원본 _latest_announcement_queryset 대응입니다. 여기서 즉시 평가하면
    목록 조회가 두 번 도는 셈이 됩니다.
    """
    from sqlalchemy import select

    stmt = select(BidAnnouncement)

    with _QueryRecorder(isolated_db) as recorder:
        bid_queries.latest_announcement_filter(stmt)

    assert recorder.statements == []


# --------------------------------------------------------------------------- #
# 목록 화면
# --------------------------------------------------------------------------- #


def test_bid_list_renders_notice_date_column_and_sort_select(auth_client, isolated_db):
    """정렬 select 와 지역 필터가 원본 구성 그대로 렌더링된다."""
    _add_announcement(isolated_db, bid_ntce_no="ANN-RENDER")

    body = auth_client.get("/bids/").text

    assert "공고일시" in body
    assert 'name="sort"' in body
    assert 'name="region"' in body
    for label in ("공고일", "마감일", "금액별", "지역별"):
        assert label in body, label
    for value in ("notice", "deadline", "amount", "region"):
        assert f'value="{value}"' in body, value
    assert 'label="특별시"' in body
    assert 'value="seoul"' in body
    assert "서울특별시" in body
    assert 'value="jeonbuk"' in body
    assert "전북특별자치도" in body


def test_region_groups_cover_seventeen_areas():
    """지역 목록은 17개 광역자치단체를 모두 담는다."""
    groups = bid_queries.region_groups_payload()
    assert sum(len(group["items"]) for group in groups) == 17


def test_bid_result_list_renders_award_results_page(auth_client, isolated_db):
    """낙찰결과 목록이 원본 표 구성과 상세 링크를 유지한다."""
    result = _add_result(isolated_db, bid_ntce_no="ANN-001")

    body = auth_client.get("/bids/results/").text

    for phrase in ("낙찰 결과", "낙찰 업체", "낙찰금액", "낙찰률"):
        assert phrase in body, phrase
    assert "테스트 낙찰업체" in body
    assert f"/bids/result/{result.id}/" in body
    assert "data-results-page" in body
    assert "data-results-filter-form" in body
    assert 'name="sort"' in body
    assert "개찰일" in body


# --------------------------------------------------------------------------- #
# 홈 화면
# --------------------------------------------------------------------------- #


def test_index_page_renders_restored_home_template(auth_client, isolated_db):
    """홈이 원본 히어로 슬라이드 구성을 그대로 쓴다."""
    _add_announcement(isolated_db, bid_ntce_no="ANN-001", bid_ntce_nm="홈 노출 공고")
    now = utcnow()
    # 원본 setUp 의 기준 낙찰 1건에 대응합니다. 아래 반복분과 합쳐 8건입니다.
    _add_result(isolated_db, bid_ntce_no="ANN-001")
    for index in range(2, 9):
        _add_result(
            isolated_db,
            bid_ntce_no=f"ANN-{index:03d}",
            bid_ntce_nm=f"낙찰 결과 {index}",
            bidwinnr_nm=f"테스트 낙찰업체 {index}",
            sucsf_bid_amt=950000 + index,
            sucsf_bid_rate=95.0 + index,
            rl_openg_dt=now + timedelta(minutes=index),
        )

    body = auth_client.get("/").text

    for phrase in (
        "홈 노출 공고",
        "최근 낙찰 결과",
        "홈 브리핑",
        "home-hero-slide",
        "공고 전체 탐색",
        "최근 동기화",
        'data-slide-index="0"',
        'data-slide-index="4"',
        "data-home-swipe-track",
        "align-items: flex-start",
        "syncTrackHeight",
        "bootstrap.bundle.min.js",
    ):
        assert phrase in body, phrase
    # 홈은 사이드바를 감춥니다 (hide_sidebar).
    assert '<aside id="sidebar"' not in body

    context = get_home_page_context(isolated_db, DEFAULT_HOME_ANNOUNCEMENT_CATEGORIES)
    assert context["announcement_total"] == 1
    assert context["result_total"] == 8


def test_index_page_header_shows_branding_and_logout_without_bell(
    auth_client, isolated_db
):
    """헤더는 검색 폼과 로그아웃을 노출하고 알림 아이콘은 두지 않는다."""
    _add_announcement(isolated_db, bid_ntce_no="ANN-HEADER")

    body = auth_client.get("/").text

    assert "border-slate-200/80 bg-white" in body
    assert 'action="/bids/"' in body
    assert 'name="q"' in body
    assert "공고명 또는 번호 검색" in body
    assert "/accounts/logout/" in body
    assert "로그아웃" in body
    assert "fa-bell" not in body


def test_index_page_recent_bid_sections_keep_latest_notice_order(isolated_db):
    """홈의 분야별 최근 공고도 같은 공고번호는 최신 차수만 노출한다."""
    now = utcnow()
    _add_announcement(
        isolated_db,
        bid_ntce_no="ANN-HOME",
        bid_ntce_ord="000",
        bid_ntce_nm="홈 중복 공고",
        category="Thng",
        base_amount=5100000,
        presmpt_prce=5000000,
        bid_ntce_dt=now,
    )
    latest = _add_announcement(
        isolated_db,
        bid_ntce_no="ANN-HOME",
        bid_ntce_ord="001",
        bid_ntce_nm="홈 중복 공고",
        category="Thng",
        base_amount=5200000,
        presmpt_prce=5100000,
        bid_ntce_dt=now + timedelta(minutes=1),
    )

    context = get_home_page_context(isolated_db, DEFAULT_HOME_ANNOUNCEMENT_CATEGORIES)
    section = next(
        item for item in context["recent_bid_sections"] if item["code"] == "Thng"
    )
    matching = [row for row in section["entries"] if row.bid_ntce_no == "ANN-HOME"]

    assert len(matching) == 1
    assert matching[0].id == latest.id

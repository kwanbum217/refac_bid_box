from datetime import timedelta
from unittest.mock import Mock

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.dialects import mysql, sqlite
from sqlalchemy.exc import DBAPIError

from src.app.core.config import settings
from src.app.core.timeutil import utcnow
from src.app.models.bids import BidAnnouncement, BidResult
from src.app.services import bid_queries
from src.app.services.search_index import (
    INDEX_MAX_TOTAL_HITS,
    INDEX_UID,
    MeiliSearchClient,
    SearchBackendUnavailable,
    SearchPage,
    announcement_document,
)


def test_announcement_document_uses_stable_notice_identity():
    row = BidAnnouncement(
        id=42,
        bid_ntce_no="20260810001",
        bid_ntce_ord="002",
        bid_ntce_nm="서울 청소 용역",
        dminstt_nm="서울특별시 강남구",
        category="Servc",
        bid_ntce_dt=utcnow(),
        collected_at=utcnow(),
    )

    document = announcement_document(row)

    assert document["id"] == "announcement_Servc_20260810001"
    assert document["source_id"] == 42
    assert document["region_codes"] == ["seoul"]


def test_meili_search_sends_dataset_filters_and_sort(monkeypatch):
    response = Mock()
    response.content = b"{}"
    response.json.return_value = {"hits": [{"source_id": 7}], "estimatedTotalHits": 21}
    response.raise_for_status.return_value = None
    request = Mock(return_value=response)
    monkeypatch.setattr(httpx, "request", request)

    page = MeiliSearchClient(base_url="http://search", master_key="test-key").search(
        query="청소",
        dataset="announcement",
        category="Servc",
        region="seoul",
        sort=["bid_ntce_dt:desc"],
        offset=0,
        limit=20,
    )

    assert page == SearchPage(ids=[7], has_next=True)
    assert request.call_args.args[:2] == ("POST", f"http://search/indexes/{INDEX_UID}/search")
    assert request.call_args.kwargs["json"]["filter"] == (
        'dataset = "announcement" AND category = "Servc" AND region_codes = "seoul"'
    )


def test_configure_index_supports_full_dataset_pagination_and_rate_filter(monkeypatch):
    response = Mock(content=b"")
    response.raise_for_status.return_value = None
    request = Mock(return_value=response)
    monkeypatch.setattr(httpx, "request", request)

    MeiliSearchClient(base_url="http://search", master_key="test-key").configure_index()

    settings_payload = request.call_args_list[-1].kwargs["json"]
    assert settings_payload["pagination"] == {"maxTotalHits": INDEX_MAX_TOTAL_HITS}
    assert INDEX_MAX_TOTAL_HITS >= 10_000_000
    assert "sucsf_bid_rate" in settings_payload["filterableAttributes"]


def test_rate_sort_excludes_null_rates_and_escapes_filter_values(monkeypatch):
    response = Mock(content=b"{}")
    response.json.return_value = {"hits": [], "estimatedTotalHits": 0}
    response.raise_for_status.return_value = None
    request = Mock(return_value=response)
    monkeypatch.setattr(httpx, "request", request)

    MeiliSearchClient(base_url="http://search", master_key="test-key").search(
        query="",
        dataset="result",
        category='Servc" OR dataset = "announcement',
        region="seoul",
        sort=["sucsf_bid_rate:asc", "source_id:asc"],
        offset=0,
        limit=20,
    )

    assert request.call_args.kwargs["json"]["filter"] == (
        'dataset = "result" AND '
        'category = "Servc\\" OR dataset = \\"announcement" AND '
        'region_codes = "seoul" AND sucsf_bid_rate IS NOT NULL'
    )


def test_meili_transport_failure_is_not_hidden(monkeypatch):
    monkeypatch.setattr(httpx, "request", Mock(side_effect=httpx.ConnectError("offline")))

    with pytest.raises(SearchBackendUnavailable):
        MeiliSearchClient().search(
            query="청소",
            dataset="announcement",
            category=None,
            region=None,
            sort=[],
            offset=0,
            limit=20,
        )


def test_keyword_search_uses_index_order_not_mysql_like(monkeypatch, isolated_db):
    now = utcnow()
    first = BidAnnouncement(
        bid_ntce_no="SEARCH-1",
        bid_ntce_ord="000",
        bid_ntce_nm="청소 용역 1",
        dminstt_nm="서울특별시",
        category="Servc",
        bid_ntce_dt=now - timedelta(days=1),
        collected_at=now,
    )
    second = BidAnnouncement(
        bid_ntce_no="SEARCH-2",
        bid_ntce_ord="000",
        bid_ntce_nm="청소 용역 2",
        dminstt_nm="서울특별시",
        category="Servc",
        bid_ntce_dt=now,
        collected_at=now,
    )
    isolated_db.add_all([first, second])
    isolated_db.commit()

    monkeypatch.setattr(settings, "MEILI_ENABLED", True, raising=False)
    monkeypatch.setattr(
        "src.app.services.search_index.MeiliSearchClient.search",
        lambda *_args, **_kwargs: SearchPage(ids=[first.id, second.id], has_next=False),
    )

    page = bid_queries.list_announcements(isolated_db, q="청소")

    assert [row.id for row in page.object_list] == [first.id, second.id]


def test_empty_query_announcement_search_sends_filters_sort_and_page(monkeypatch, isolated_db):
    row = BidAnnouncement(
        bid_ntce_no="EMPTY-Q-ANN",
        bid_ntce_ord="000",
        bid_ntce_nm="빈 검색어 공고",
        dminstt_nm="서울특별시",
        category="Servc",
        bid_ntce_dt=utcnow(),
        collected_at=utcnow(),
    )
    isolated_db.add(row)
    isolated_db.commit()
    search = Mock(return_value=SearchPage(ids=[row.id], has_next=True))
    monkeypatch.setattr(settings, "MEILI_ENABLED", True, raising=False)
    monkeypatch.setattr("src.app.services.search_index.MeiliSearchClient.search", search)

    page = bid_queries.list_announcements(
        isolated_db,
        q="",
        cat="Servc",
        region="seoul",
        sort="deadline",
        page=2,
    )

    assert [item.id for item in page.object_list] == [row.id]
    assert page.number == 2
    assert page.has_next is True
    assert search.call_args.kwargs == {
        "query": "",
        "dataset": "announcement",
        "category": "Servc",
        "region": "seoul",
        "sort": ["bid_clse_dt:asc", "source_id:desc"],
        "offset": 20,
        "limit": 20,
    }


def test_empty_query_announcement_search_continues_after_page_50(monkeypatch, isolated_db):
    row = BidAnnouncement(
        bid_ntce_no="EMPTY-Q-PAGE-51",
        bid_ntce_ord="000",
        bid_ntce_nm="51페이지 공고",
        category="Servc",
        bid_ntce_dt=utcnow(),
        collected_at=utcnow(),
    )
    isolated_db.add(row)
    isolated_db.commit()
    search = Mock(return_value=SearchPage(ids=[row.id], has_next=True))
    monkeypatch.setattr(settings, "MEILI_ENABLED", True, raising=False)
    monkeypatch.setattr("src.app.services.search_index.MeiliSearchClient.search", search)

    page = bid_queries.list_announcements(isolated_db, q="", page=51)

    assert [item.id for item in page.object_list] == [row.id]
    assert page.number == 51
    assert page.has_next is True
    assert search.call_args.kwargs["offset"] == 1_000


def test_empty_query_result_search_preserves_index_order(monkeypatch, isolated_db):
    now = utcnow()
    first = BidResult(
        bid_ntce_no="EMPTY-Q-RES-1",
        bid_ntce_ord="00",
        bid_ntce_nm="첫 낙찰",
        dminstt_nm="부산광역시",
        bidwinnr_nm="첫 업체",
        category="Servc",
        sucsf_bid_amt=1_000_000,
        sucsf_bid_rate=90,
        rl_openg_dt=now,
        collected_at=now,
    )
    second = BidResult(
        bid_ntce_no="EMPTY-Q-RES-2",
        bid_ntce_ord="00",
        bid_ntce_nm="둘째 낙찰",
        dminstt_nm="부산광역시",
        bidwinnr_nm="둘째 업체",
        category="Servc",
        sucsf_bid_amt=2_000_000,
        sucsf_bid_rate=91,
        rl_openg_dt=now - timedelta(days=1),
        collected_at=now,
    )
    isolated_db.add_all([first, second])
    isolated_db.commit()
    search = Mock(return_value=SearchPage(ids=[second.id, first.id], has_next=False))
    monkeypatch.setattr(settings, "MEILI_ENABLED", True, raising=False)
    monkeypatch.setattr("src.app.services.search_index.MeiliSearchClient.search", search)

    page = bid_queries.list_results(
        isolated_db,
        q="",
        cat="Servc",
        region="busan",
        sort="amount",
        page=1,
    )

    assert [item.id for item in page.object_list] == [second.id, first.id]
    assert search.call_args.kwargs == {
        "query": "",
        "dataset": "result",
        "category": "Servc",
        "region": "busan",
        "sort": ["sucsf_bid_amt:desc", "source_id:desc"],
        "offset": 0,
        "limit": 20,
    }


def test_missing_hydration_row_is_skipped_without_reordering(monkeypatch, isolated_db):
    now = utcnow()
    first = BidAnnouncement(
        bid_ntce_no="HYDRATE-1",
        bid_ntce_ord="000",
        bid_ntce_nm="첫 공고",
        category="Servc",
        bid_ntce_dt=now,
        collected_at=now,
    )
    second = BidAnnouncement(
        bid_ntce_no="HYDRATE-2",
        bid_ntce_ord="000",
        bid_ntce_nm="둘째 공고",
        category="Servc",
        bid_ntce_dt=now,
        collected_at=now,
    )
    isolated_db.add_all([first, second])
    isolated_db.commit()
    monkeypatch.setattr(settings, "MEILI_ENABLED", True, raising=False)
    monkeypatch.setattr(
        "src.app.services.search_index.MeiliSearchClient.search",
        Mock(return_value=SearchPage(ids=[second.id, 999_999, first.id], has_next=True)),
    )

    page = bid_queries.list_announcements(isolated_db)

    assert [item.id for item in page.object_list] == [second.id, first.id]
    assert page.has_next is True


def test_disabled_search_backend_uses_mysql_without_calling_meili(monkeypatch, isolated_db):
    row = BidAnnouncement(
        bid_ntce_no="MYSQL-DISABLED",
        bid_ntce_ord="000",
        bid_ntce_nm="MySQL 공고",
        category="Servc",
        bid_ntce_dt=utcnow(),
        collected_at=utcnow(),
    )
    isolated_db.add(row)
    isolated_db.commit()
    search = Mock()
    monkeypatch.setattr(settings, "MEILI_ENABLED", False, raising=False)
    monkeypatch.setattr("src.app.services.search_index.MeiliSearchClient.search", search)

    page = bid_queries.list_announcements(isolated_db, q="MySQL")

    assert [item.id for item in page.object_list] == [row.id]
    search.assert_not_called()


@pytest.mark.parametrize(
    "list_rows",
    [bid_queries.list_announcements, bid_queries.list_results],
)
def test_enabled_search_backend_failure_is_propagated(monkeypatch, isolated_db, list_rows):
    monkeypatch.setattr(settings, "MEILI_ENABLED", True, raising=False)
    monkeypatch.setattr(
        "src.app.services.search_index.MeiliSearchClient.search",
        Mock(side_effect=SearchBackendUnavailable("offline")),
    )

    with pytest.raises(SearchBackendUnavailable, match="offline"):
        list_rows(isolated_db)


def test_announcement_search_backend_failure_returns_503(monkeypatch, client):
    monkeypatch.setattr(settings, "MEILI_ENABLED", True, raising=False)
    monkeypatch.setattr(
        "src.app.services.search_index.MeiliSearchClient.search",
        Mock(side_effect=SearchBackendUnavailable("offline")),
    )

    response = client.get("/api/v1/bids", params={"q": "청소"})

    assert response.status_code == 503
    assert "검색 인덱스" in response.json()["detail"]


def test_result_search_backend_failure_returns_503(monkeypatch, client):
    monkeypatch.setattr(settings, "MEILI_ENABLED", True, raising=False)
    monkeypatch.setattr(
        "src.app.services.search_index.MeiliSearchClient.search",
        Mock(side_effect=SearchBackendUnavailable("offline")),
    )

    response = client.get("/api/v1/bids/results", params={"q": "낙찰"})

    assert response.status_code == 503
    assert "검색 인덱스" in response.json()["detail"]


def test_mysql_fallback_select_has_server_execution_limit():
    stmt = bid_queries._with_mysql_execution_limit(select(BidResult))
    mysql_sql = str(stmt.compile(dialect=mysql.dialect()))
    sqlite_sql = str(stmt.compile(dialect=sqlite.dialect()))

    assert "MAX_EXECUTION_TIME(5000)" in mysql_sql
    assert "MAX_EXECUTION_TIME" not in sqlite_sql


def test_mysql_timeout_is_exposed_as_search_backend_unavailable():
    db = Mock()
    timeout = DBAPIError("SELECT", {}, RuntimeError(3024, "maximum statement time exceeded"), False)
    db.execute.side_effect = timeout

    with pytest.raises(SearchBackendUnavailable, match="실행시간"):
        bid_queries._paginate_without_count(db, select(BidResult), 1)


def test_mysql_timeout_keeps_api_503_contract(monkeypatch, client):
    monkeypatch.setattr(
        bid_queries,
        "list_announcements",
        Mock(side_effect=SearchBackendUnavailable("MySQL fallback timeout")),
    )

    response = client.get("/api/v1/bids")

    assert response.status_code == 503
    assert "검색 인덱스" in response.json()["detail"]


def test_latest_announcement_filter_uses_ranked_derived_ids():
    stmt = bid_queries.latest_announcement_filter(select(BidAnnouncement))
    sql = str(stmt.compile(dialect=mysql.dialect())).upper()

    assert "ROW_NUMBER() OVER" in sql
    assert "LATEST_RANK" in sql

from datetime import timedelta
from unittest.mock import Mock

import httpx
import pytest

from src.app.core.config import settings
from src.app.core.timeutil import utcnow
from src.app.models.bids import BidAnnouncement
from src.app.services import bid_queries
from src.app.services.search_index import (
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


def test_search_backend_failure_returns_explicit_503(monkeypatch, client):
    monkeypatch.setattr(settings, "MEILI_ENABLED", True, raising=False)
    monkeypatch.setattr(
        "src.app.services.search_index.MeiliSearchClient.search",
        Mock(side_effect=SearchBackendUnavailable("offline")),
    )

    response = client.get("/api/v1/bids", params={"q": "청소"})

    assert response.status_code == 503
    assert "검색 인덱스" in response.json()["detail"]

"""tests/test_list_cancelled_20261122.py

공고 탐색 목록(/bids/, 목록 API)이 최신 차수 취소공고를 기본으로 빼는지 DB 경로와
Meilisearch 경로에서 확인합니다. 홈 '더보기'가 이 목록으로 이어지므로, 이미 취소된
공고가 재공고와 함께 노출되지 않아야 합니다.

색인에는 (공고번호, 업무구분)마다 최신 차수 행만 들어가므로 `is_cancelled` 값은 그
공고번호의 최신 차수 취소 여부가 됩니다. 재색인 전 옛 문서에는 이 필드가 없고,
질의 필터 `is_cancelled != true` 는 필드 없는 문서를 통과시킵니다.
"""

from datetime import timedelta
from unittest.mock import Mock

import httpx
import pytest

from src.app.core.timeutil import utcnow
from src.app.models.bids import BidAnnouncement
from src.app.services import bid_queries
from src.app.services.search_index import (
    MeiliSearchClient,
    _latest_announcements,
    announcement_document,
)


def _add_announcement(db, **overrides) -> BidAnnouncement:
    payload = {
        "bid_ntce_ord": "000",
        "dminstt_nm": "테스트발주기관",
        "category": "Servc",
        "bid_ntce_dt": utcnow(),
        "collected_at": utcnow(),
    }
    payload.update(overrides)
    row = BidAnnouncement(**payload)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


# --------------------------------------------------------------------------- #
# (a) DB 경로: 최신 차수 취소 번호만 제외, 다른 공고종류는 유지
# --------------------------------------------------------------------------- #


def test_db_list_excludes_only_latest_cancelled_notice_number(isolated_db):
    now = utcnow()
    _add_announcement(
        isolated_db,
        bid_ntce_no="CXL-LATEST",
        bid_ntce_ord="000",
        bid_ntce_nm="취소 전 등록 차수",
        bid_ntce_dt=now,
    )
    _add_announcement(
        isolated_db,
        bid_ntce_no="CXL-LATEST",
        bid_ntce_ord="002",
        bid_ntce_nm="취소된 최신 차수",
        ntce_kind_nm="취소공고",
        bid_ntce_dt=now + timedelta(minutes=1),
    )
    _add_announcement(
        isolated_db,
        bid_ntce_no="CXL-ONLY",
        bid_ntce_nm="취소만 있는 공고",
        ntce_kind_nm="취소공고",
        bid_ntce_dt=now,
    )
    # 이전 차수만 취소고 최신 차수가 재공고면 유효한 공고이므로 유지합니다.
    _add_announcement(
        isolated_db,
        bid_ntce_no="KEEP-RERE",
        bid_ntce_ord="000",
        bid_ntce_nm="취소 뒤 재공고",
        ntce_kind_nm="취소공고",
        bid_ntce_dt=now,
    )
    rere = _add_announcement(
        isolated_db,
        bid_ntce_no="KEEP-RERE",
        bid_ntce_ord="002",
        bid_ntce_nm="재공고 최신 차수",
        ntce_kind_nm="재공고",
        bid_ntce_dt=now + timedelta(minutes=1),
    )
    _add_announcement(
        isolated_db,
        bid_ntce_no="KEEP-NULL",
        bid_ntce_nm="공고종류 없는 공고",
        ntce_kind_nm=None,
        bid_ntce_dt=now,
    )
    _add_announcement(
        isolated_db,
        bid_ntce_no="KEEP-CHANGED",
        bid_ntce_nm="변경공고",
        ntce_kind_nm="변경공고",
        bid_ntce_dt=now,
    )
    _add_announcement(
        isolated_db,
        bid_ntce_no="KEEP-REGISTERED",
        bid_ntce_nm="등록공고",
        ntce_kind_nm="등록공고",
        bid_ntce_dt=now,
    )

    page = bid_queries.list_announcements(isolated_db)
    rows = {row.bid_ntce_no: row for row in page.object_list}

    assert set(rows) == {
        "KEEP-RERE",
        "KEEP-NULL",
        "KEEP-CHANGED",
        "KEEP-REGISTERED",
    }
    # 이전 취소 차수가 아니라 재공고 최신 차수를 보여줍니다.
    assert rows["KEEP-RERE"].id == rere.id


def test_db_list_cancelled_exclusion_keeps_paging_contract(isolated_db):
    """취소 제외는 행 단위 조건이라 페이지 크기와 다음 페이지 계약을 바꾸지 않습니다."""
    now = utcnow()
    for index in range(bid_queries.PAGE_SIZE + 3):
        _add_announcement(
            isolated_db,
            bid_ntce_no=f"PAGE-{index:03d}",
            bid_ntce_nm=f"정상 공고 {index}",
            ntce_kind_nm="등록공고",
            bid_ntce_dt=now - timedelta(minutes=index),
        )
    _add_announcement(
        isolated_db,
        bid_ntce_no="PAGE-CANCELLED",
        bid_ntce_nm="취소 공고",
        ntce_kind_nm="취소공고",
        bid_ntce_dt=now,
    )

    first = bid_queries.list_announcements(isolated_db, page=1)
    second = bid_queries.list_announcements(isolated_db, page=2)

    assert len(first.object_list) == bid_queries.PAGE_SIZE
    assert first.has_next is True
    assert "PAGE-CANCELLED" not in {row.bid_ntce_no for row in first.object_list}
    assert "PAGE-CANCELLED" not in {row.bid_ntce_no for row in second.object_list}


# --------------------------------------------------------------------------- #
# (b) 색인 문서의 is_cancelled 값
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "notice_kind, expected",
    [
        ("취소공고", True),
        ("재공고", False),
        ("변경공고", False),
        ("등록공고", False),
        (None, False),
    ],
)
def test_announcement_document_records_is_cancelled(notice_kind, expected):
    row = BidAnnouncement(
        id=501,
        bid_ntce_no="DOC-KIND",
        bid_ntce_ord="000",
        bid_ntce_nm="공고종류 판정",
        dminstt_nm="서울특별시",
        category="Servc",
        ntce_kind_nm=notice_kind,
        bid_ntce_dt=utcnow(),
        collected_at=utcnow(),
    )

    assert announcement_document(row)["is_cancelled"] is expected


def test_indexed_documents_keep_only_latest_order(isolated_db):
    """색인은 최신 차수 행만 넣으므로 최신 차수가 취소면 그 문서가 취소로 남는다."""
    now = utcnow()
    _add_announcement(
        isolated_db,
        bid_ntce_no="IDX-CXL",
        bid_ntce_nm="이전 등록 차수",
        bid_ntce_dt=now,
    )
    latest = _add_announcement(
        isolated_db,
        bid_ntce_no="IDX-CXL",
        bid_ntce_ord="002",
        bid_ntce_nm="취소된 최신 차수",
        ntce_kind_nm="취소공고",
        bid_ntce_dt=now + timedelta(minutes=1),
    )

    rows = list(_latest_announcements(isolated_db, None))
    documents = [announcement_document(row) for row in rows]

    assert [document["bid_ntce_no"] for document in documents] == ["IDX-CXL"]
    assert documents[0]["source_id"] == latest.id
    assert documents[0]["is_cancelled"] is True


# --------------------------------------------------------------------------- #
# (c) Meili 검색 필터: 공고 질의에만 기본 적용, 낙찰 결과 질의는 불변
# --------------------------------------------------------------------------- #


def _search_with_captured_payload(monkeypatch, request: Mock) -> None:
    response = Mock(content=b"{}")
    response.json.return_value = {"hits": [], "estimatedTotalHits": 0}
    response.raise_for_status.return_value = None
    request.return_value = response
    monkeypatch.setattr(httpx, "request", request)


def test_meili_announcement_search_filters_cancelled_by_default(monkeypatch):
    request = Mock()
    _search_with_captured_payload(monkeypatch, request)
    client = MeiliSearchClient(base_url="http://search", master_key="test-key")

    client.search(
        query="",
        dataset="announcement",
        category=None,
        region=None,
        sort=["bid_ntce_dt:desc"],
        offset=0,
        limit=20,
    )
    client.search(
        query="",
        dataset="result",
        category=None,
        region=None,
        sort=["rl_openg_dt:desc"],
        offset=0,
        limit=20,
    )

    announcement_filter = request.call_args_list[0].kwargs["json"]["filter"]
    result_filter = request.call_args_list[1].kwargs["json"]["filter"]
    assert announcement_filter == 'dataset = "announcement" AND is_cancelled != true'
    assert "is_cancelled" not in result_filter


def test_meili_announcement_filter_combines_with_category_and_region(monkeypatch):
    request = Mock()
    _search_with_captured_payload(monkeypatch, request)

    MeiliSearchClient(base_url="http://search", master_key="test-key").search(
        query="청소",
        dataset="announcement",
        category="Servc",
        region="seoul",
        sort=["bid_ntce_dt:desc"],
        offset=0,
        limit=20,
    )

    assert request.call_args.kwargs["json"]["filter"] == (
        'dataset = "announcement" AND is_cancelled != true AND '
        'category = "Servc" AND participation_region_codes = "seoul"'
    )


# --------------------------------------------------------------------------- #
# (d) filterableAttributes 등록
# --------------------------------------------------------------------------- #


def test_configure_index_registers_is_cancelled_filter(monkeypatch):
    response = Mock(content=b"")
    response.raise_for_status.return_value = None
    request = Mock(return_value=response)
    monkeypatch.setattr(httpx, "request", request)

    MeiliSearchClient(base_url="http://search", master_key="test-key").configure_index()

    settings_payload = request.call_args_list[-1].kwargs["json"]
    assert "is_cancelled" in settings_payload["filterableAttributes"]

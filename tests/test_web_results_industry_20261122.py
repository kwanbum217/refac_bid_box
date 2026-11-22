"""낙찰 결과 목록(/bids/results/)의 4대 업종 제한 회귀 시험.

Meilisearch 색인 문서·검색 필터 경로와 MySQL DB 대체 경로가 모두 4개 업종(파견,
경비업, 위생관리용역업, 유료직업소개업) 제한 공고의 결과만 돌려주는지 확인합니다.
공고 목록의 기존 업종 판정 SQL 은 바뀌지 않아야 합니다.
"""

from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import or_, select
from sqlalchemy.dialects import sqlite

from src.app.core.config import settings
from src.app.core.security import SESSION_COOKIE_NAME, create_session, make_password
from src.app.core.timeutil import utcnow
from src.app.main import app
from src.app.models.accounts import CustomUser
from src.app.models.bid_restrictions import BidAnnouncementLicenseLimit
from src.app.models.bids import BidAnnouncement, BidResult
from src.app.services import bid_queries
from src.app.services.search_index import (
    MeiliSearchClient,
    SearchPage,
    _build_result_batch,
    result_document,
)

DISPATCH_CODE = "1172"
SECURITY_CODE = "1164"
OUTSIDE_CODE = "9999"


def _result(bid_ntce_no: str, name: str, *, ord_: str = "000", now=None) -> BidResult:
    now = now or utcnow()
    return BidResult(
        bid_ntce_no=bid_ntce_no,
        bid_ntce_ord=ord_,
        bid_ntce_nm=name,
        category="Servc",
        dminstt_nm="서울특별시",
        bidwinnr_nm="테스트업체",
        rl_openg_dt=now,
        collected_at=now,
    )


def _limit(result: BidResult, *, license_name: str | None = None, permitted=None):
    return BidAnnouncementLicenseLimit(
        bid_ntce_no=result.bid_ntce_no,
        bid_ntce_ord=result.bid_ntce_ord,
        lmt_grp_no="1",
        lmt_sno="1",
        lcns_lmt_nm=license_name,
        permsn_indstryty_list=permitted,
        collected_at=result.collected_at,
    )


# --------------------------------------------------------------------------- #
# (a) 결과 색인 배치가 공고의 업종 코드를 붙인다
# --------------------------------------------------------------------------- #


def test_build_result_batch_attaches_license_codes(isolated_db):
    guarded = _result("RES-LIC-1", "파견 용역")
    outside = _result("RES-LIC-2", "업종 밖 용역")
    no_limits = _result("RES-LIC-3", "제한 없는 용역")
    isolated_db.add_all([guarded, outside, no_limits])
    isolated_db.commit()
    isolated_db.add_all(
        [
            _limit(guarded, license_name="파견근로자고용허가/1172"),
            _limit(outside, permitted="[세무사업/9999]"),
        ]
    )
    isolated_db.commit()

    docs = _build_result_batch(isolated_db, [guarded, outside, no_limits])

    doc_map = {doc["bid_ntce_no"]: doc for doc in docs}
    assert doc_map["RES-LIC-1"]["license_codes"] == [DISPATCH_CODE]
    assert doc_map["RES-LIC-2"]["license_codes"] == [OUTSIDE_CODE]
    assert doc_map["RES-LIC-3"]["license_codes"] == []
    assert doc_map["RES-LIC-1"]["dataset"] == "result"


def test_result_document_defaults_to_empty_license_codes():
    document = result_document(_result("RES-DOC-1", "기본 문서"))

    assert document["license_codes"] == []


def test_build_result_batch_queries_license_limits_once_per_batch(isolated_db):
    now = utcnow()
    rows = []
    limits = []
    for index in range(10):
        row = _result(f"RES-BATCH-{index}", f"배치 결과 {index}", now=now)
        rows.append(row)
        limits.append(_limit(row, license_name="파견/1172"))
    isolated_db.add_all(rows)
    isolated_db.commit()
    isolated_db.add_all(limits)
    isolated_db.commit()

    limit_query_count = 0
    orig_execute = isolated_db.execute

    def spy_execute(statement, *args, **kwargs):
        nonlocal limit_query_count
        if "BID_ANNOUNCEMENT_LICENSE_LIMITS" in str(statement).upper():
            limit_query_count += 1
        return orig_execute(statement, *args, **kwargs)

    isolated_db.execute = spy_execute
    try:
        docs = _build_result_batch(isolated_db, rows)
    finally:
        isolated_db.execute = orig_execute

    assert len(docs) == 10
    assert limit_query_count == 1


# --------------------------------------------------------------------------- #
# (b) DB 대체 경로: 4개 업종 제한 공고의 결과만 남는다
# --------------------------------------------------------------------------- #


def test_result_list_db_fallback_keeps_only_four_industry_results(monkeypatch, isolated_db):
    monkeypatch.setattr(settings, "MEILI_ENABLED", False, raising=False)
    sanitized = _result("RES-DB-1", "위생관리 용역")
    dispatched = _result("RES-DB-2", "파견 용역")
    outside = _result("RES-DB-3", "업종 밖 용역")
    no_limits = _result("RES-DB-4", "제한 없는 용역")
    isolated_db.add_all([sanitized, dispatched, outside, no_limits])
    isolated_db.commit()
    isolated_db.add_all(
        [
            _limit(sanitized, license_name="위생관리용역업/1162"),
            _limit(dispatched, permitted="[파견근로자고용허가/1172]"),
            _limit(outside, license_name="축산물판매업/9999"),
        ]
    )
    isolated_db.commit()

    page = bid_queries.list_results(isolated_db, cat="Servc")

    ids = {row.id for row in page.object_list}
    assert sanitized.id in ids
    assert dispatched.id in ids
    assert outside.id not in ids
    assert no_limits.id not in ids


def test_result_list_db_fallback_matches_any_industry_code(monkeypatch, isolated_db):
    monkeypatch.setattr(settings, "MEILI_ENABLED", False, raising=False)
    security = _result("RES-ANY-1", "경비 용역")
    isolated_db.add(security)
    isolated_db.commit()
    isolated_db.add(_limit(security, permitted="[경비업/1164]"))
    isolated_db.commit()

    page = bid_queries.list_results(isolated_db, cat="Servc")

    assert [row.id for row in page.object_list] == [security.id]


# --------------------------------------------------------------------------- #
# (c) Meilisearch 경로: 결과 목록이 4개 업종 코드 필터를 넘긴다
# --------------------------------------------------------------------------- #


def test_result_list_meili_path_sends_four_industry_codes(monkeypatch, isolated_db):
    monkeypatch.setattr(settings, "MEILI_ENABLED", True, raising=False)
    search_mock = Mock(return_value=SearchPage(ids=[], has_next=False))
    monkeypatch.setattr("src.app.services.search_index.MeiliSearchClient.search", search_mock)

    bid_queries.list_results(isolated_db, cat="Servc")

    kwargs = search_mock.call_args.kwargs
    assert kwargs["dataset"] == "result"
    assert kwargs["license_codes"] == list(bid_queries.BID_INDUSTRY_CODES)
    assert "license_code" not in kwargs


def test_meili_search_serializes_industry_filter_for_result_dataset(monkeypatch):
    response = Mock()
    response.content = b"{}"
    response.json.return_value = {"hits": [], "estimatedTotalHits": 0}
    response.raise_for_status.return_value = None
    request = Mock(return_value=response)
    monkeypatch.setattr("httpx.request", request)

    client = MeiliSearchClient(base_url="http://search", master_key="test-key")
    client.search(
        query="",
        dataset="result",
        category="Servc",
        region=None,
        sort=["rl_openg_dt:desc", "source_id:desc"],
        offset=0,
        limit=20,
        license_codes=list(bid_queries.BID_INDUSTRY_CODES),
    )

    filter_str = request.call_args.kwargs["json"]["filter"]
    assert 'dataset = "result"' in filter_str
    assert "license_codes IN [" in filter_str
    for code in bid_queries.BID_INDUSTRY_CODES:
        assert f'"{code}"' in filter_str


# --------------------------------------------------------------------------- #
# (d) 공고 목록의 업종 판정 SQL 은 그대로다
# --------------------------------------------------------------------------- #


def test_announcement_license_match_clause_sql_is_unchanged():
    actual = bid_queries.license_match_clause([SECURITY_CODE])
    expected = (
        select(1)
        .where(
            BidAnnouncementLicenseLimit.bid_ntce_no == BidAnnouncement.bid_ntce_no,
            BidAnnouncementLicenseLimit.bid_ntce_ord == BidAnnouncement.bid_ntce_ord,
            or_(
                BidAnnouncementLicenseLimit.lcns_lmt_nm.like(f"%/{SECURITY_CODE}%"),
                BidAnnouncementLicenseLimit.permsn_indstryty_list.like(f"%/{SECURITY_CODE}%"),
            ),
        )
        .exists()
    )

    dialect = sqlite.dialect()
    assert str(actual.compile(dialect=dialect)) == str(expected.compile(dialect=dialect))


def test_announcement_list_db_fallback_still_filters_by_selected_industry(monkeypatch, isolated_db):
    monkeypatch.setattr(settings, "MEILI_ENABLED", False, raising=False)
    now = utcnow()
    guarded = BidAnnouncement(
        bid_ntce_no="ANN-STILL-1",
        bid_ntce_ord="000",
        bid_ntce_nm="경비 공고",
        category="Servc",
        bid_ntce_dt=now,
        collected_at=now,
    )
    outside = BidAnnouncement(
        bid_ntce_no="ANN-STILL-2",
        bid_ntce_ord="000",
        bid_ntce_nm="업종 밖 공고",
        category="Servc",
        bid_ntce_dt=now,
        collected_at=now,
    )
    isolated_db.add_all([guarded, outside])
    isolated_db.commit()
    isolated_db.add_all(
        [
            _limit(guarded, license_name="경비업/1164"),
            _limit(outside, license_name="축산물판매업/9999"),
        ]
    )
    isolated_db.commit()

    page = bid_queries.list_announcements(isolated_db, lic=SECURITY_CODE)

    ids = {row.id for row in page.object_list}
    assert guarded.id in ids
    assert outside.id not in ids


# --------------------------------------------------------------------------- #
# 화면 안내 문구
# --------------------------------------------------------------------------- #


@pytest.fixture
def logged_in_client(isolated_db):
    user = CustomUser(
        username="results_industry_tester",
        password=make_password("pw-results-1234"),
        email="results@example.com",
        nickname="낙찰 업종 검증",
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


def test_results_page_states_four_industry_restriction(monkeypatch, logged_in_client):
    monkeypatch.setattr(settings, "MEILI_ENABLED", False, raising=False)

    response = logged_in_client.get("/bids/results/")

    assert response.status_code == 200
    assert "4대 업종(파견·경비·위생관리·유료직업소개) 낙찰 결과" in response.text

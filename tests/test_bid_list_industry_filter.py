"""
tests/test_bid_list_industry_filter.py

공고 탐색(/bids/) 업종 필터 및 Meilisearch 읽기 모델 색인 검증.
Capsule 계약 (a)~(f) 전체 검증:
  (a) 코드 추출(면허명, 허용업종 목록, 잘못된 형식)
  (b) 배치 문서에 license_codes 가 채워지고 제한 없는 공고는 빈 배열
  (c) 배치당 제한정보 조회가 한 번 (N+1 방지)
  (d) search 필터 문자열에 license_codes 조건 추가
  (e) /bids/?lic=0036 이 search 에 코드를 넘기고 잘못된 lic 는 무시
  (f) 페이지 링크에 lic 보존 및 안내 문구 렌더링, 업종 선택지 캐싱
"""

from unittest.mock import Mock

import httpx
import pytest
from fastapi.testclient import TestClient

from src.app.core.cache import cache
from src.app.core.config import settings
from src.app.core.security import SESSION_COOKIE_NAME, create_session, make_password
from src.app.core.timeutil import utcnow
from src.app.main import app
from src.app.models.accounts import CustomUser
from src.app.models.bid_restrictions import BidAnnouncementLicenseLimit
from src.app.models.bids import BidAnnouncement
from src.app.services import bid_queries
from src.app.services.search_index import (
    MeiliSearchClient,
    SearchPage,
    _build_announcement_batch,
    extract_license_codes,
)


@pytest.fixture
def auth_user(isolated_db):
    user = CustomUser(
        username="filter_tester",
        password=make_password("pw-filter-1234"),
        email="filter@example.com",
        nickname="필터 검증",
        is_active=True,
        is_staff=False,
        is_superuser=False,
        date_joined=utcnow(),
    )
    isolated_db.add(user)
    isolated_db.commit()
    isolated_db.refresh(user)
    return user


@pytest.fixture
def logged_in_client(auth_user):
    token = create_session(auth_user.id, auth_user.username)
    return TestClient(app, cookies={SESSION_COOKIE_NAME: token})


# --------------------------------------------------------------------------- #
# (a) 코드 추출: 면허명, 허용업종 목록, 잘못된 형식
# --------------------------------------------------------------------------- #


def test_extract_license_codes_from_license_name():
    assert extract_license_codes("정보통신공사업/0036") == ["0036"]


def test_extract_license_codes_from_permitted_industry_list():
    raw = "[전문소방공사감리업/1492],[소방시설공사업/1490]"
    assert extract_license_codes(raw) == ["1490", "1492"]


def test_extract_license_codes_deduplicates_and_sorts():
    codes = extract_license_codes(
        "정보통신공사업/0036",
        "[정보통신공사업/0036],[전문소방공사감리업/1492]",
    )
    assert codes == ["0036", "1492"]


@pytest.mark.parametrize(
    "malformed_text",
    [
        "건설업/123",  # 3자리 숫자
        "기타업종/12345",  # 5자리 숫자
        "정보통신/abcd",  # 영문 코드
        "1234",  # 슬래시 없음
        "/12",  # 2자리
        "",
        None,
    ],
)
def test_extract_license_codes_ignores_malformed_formats(malformed_text):
    assert extract_license_codes(malformed_text) == []


# --------------------------------------------------------------------------- #
# (b) 배치 문서에 license_codes 가 채워지고 제한 없는 공고는 빈 배열
# --------------------------------------------------------------------------- #


def test_build_announcement_batch_populates_license_codes(isolated_db):
    now = utcnow()
    ann_with_limits = BidAnnouncement(
        bid_ntce_no="ANN-LIC-1",
        bid_ntce_ord="000",
        bid_ntce_nm="면허제한 있는 공고",
        category="Servc",
        bid_ntce_dt=now,
        collected_at=now,
    )
    ann_no_limits = BidAnnouncement(
        bid_ntce_no="ANN-LIC-2",
        bid_ntce_ord="000",
        bid_ntce_nm="면허제한 없는 공고",
        category="Servc",
        bid_ntce_dt=now,
        collected_at=now,
    )
    isolated_db.add_all([ann_with_limits, ann_no_limits])
    isolated_db.commit()

    isolated_db.add(
        BidAnnouncementLicenseLimit(
            bid_ntce_no="ANN-LIC-1",
            bid_ntce_ord="000",
            lmt_grp_no="1",
            lmt_sno="1",
            lcns_lmt_nm="정보통신공사업/0036",
            permsn_indstryty_list="[전문소방공사감리업/1492]",
            collected_at=now,
        )
    )
    isolated_db.commit()

    docs = _build_announcement_batch(isolated_db, [ann_with_limits, ann_no_limits])

    assert len(docs) == 2
    doc_map = {d["bid_ntce_no"]: d for d in docs}
    assert doc_map["ANN-LIC-1"]["license_codes"] == ["0036", "1492"]
    assert doc_map["ANN-LIC-2"]["license_codes"] == []


# --------------------------------------------------------------------------- #
# (c) 배치당 제한정보 조회가 한 번 (N+1 방지)
# --------------------------------------------------------------------------- #


def test_announcement_batches_queries_license_limits_once_per_batch(isolated_db):
    now = utcnow()
    announcements = []
    limits = []
    for i in range(10):
        ntce_no = f"BATCH-NTCE-{i}"
        announcements.append(
            BidAnnouncement(
                bid_ntce_no=ntce_no,
                bid_ntce_ord="000",
                bid_ntce_nm=f"배치 공고 {i}",
                category="Servc",
                bid_ntce_dt=now,
                collected_at=now,
            )
        )
        limits.append(
            BidAnnouncementLicenseLimit(
                bid_ntce_no=ntce_no,
                bid_ntce_ord="000",
                lmt_grp_no="1",
                lmt_sno="1",
                lcns_lmt_nm=f"업종_{i}/0036",
                collected_at=now,
            )
        )
    isolated_db.add_all(announcements + limits)
    isolated_db.commit()

    limit_query_count = 0
    orig_execute = isolated_db.execute

    def spy_execute(statement, *args, **kwargs):
        nonlocal limit_query_count
        stmt_str = str(statement).upper()
        if "BID_ANNOUNCEMENT_LICENSE_LIMITS" in stmt_str:
            limit_query_count += 1
        return orig_execute(statement, *args, **kwargs)

    isolated_db.execute = spy_execute
    try:
        docs = _build_announcement_batch(isolated_db, announcements)
    finally:
        isolated_db.execute = orig_execute

    assert len(docs) == 10
    # 10건의 공고가 포함된 1개 배치에 대해 제한정보 쿼리는 단 1번만 실행되어야 함
    assert limit_query_count == 1


# --------------------------------------------------------------------------- #
# (d) search 필터 문자열에 license_codes 조건 추가
# --------------------------------------------------------------------------- #


def test_meili_search_includes_license_codes_filter_when_present(monkeypatch):
    response = Mock()
    response.content = b"{}"
    response.json.return_value = {"hits": [], "estimatedTotalHits": 0}
    response.raise_for_status.return_value = None
    request = Mock(return_value=response)
    monkeypatch.setattr(httpx, "request", request)

    client = MeiliSearchClient(base_url="http://search", master_key="test-key")
    client.search(
        query="",
        dataset="announcement",
        category="Servc",
        region="seoul",
        sort=["bid_ntce_dt:desc"],
        offset=0,
        limit=20,
        license_code="0036",
    )

    filter_str = request.call_args.kwargs["json"]["filter"]
    assert 'license_codes = "0036"' in filter_str
    assert 'dataset = "announcement"' in filter_str
    assert 'category = "Servc"' in filter_str
    assert 'region_codes = "seoul"' in filter_str


def test_meili_search_omits_license_codes_filter_when_absent(monkeypatch):
    response = Mock()
    response.content = b"{}"
    response.json.return_value = {"hits": [], "estimatedTotalHits": 0}
    response.raise_for_status.return_value = None
    request = Mock(return_value=response)
    monkeypatch.setattr(httpx, "request", request)

    client = MeiliSearchClient(base_url="http://search", master_key="test-key")
    client.search(
        query="",
        dataset="announcement",
        category=None,
        region=None,
        sort=["bid_ntce_dt:desc"],
        offset=0,
        limit=20,
        license_code=None,
    )

    filter_str = request.call_args.kwargs["json"]["filter"]
    assert "license_codes" not in filter_str


# --------------------------------------------------------------------------- #
# (e) /bids/?lic=0036 이 search 에 코드를 넘기고 잘못된 lic 는 무시
# --------------------------------------------------------------------------- #


def test_bids_route_passes_valid_lic_to_search(monkeypatch, logged_in_client):
    search_mock = Mock(return_value=SearchPage(ids=[], has_next=False))
    monkeypatch.setattr(settings, "MEILI_ENABLED", True, raising=False)
    monkeypatch.setattr("src.app.services.search_index.MeiliSearchClient.search", search_mock)

    response = logged_in_client.get("/bids/", params={"lic": "0036"})
    assert response.status_code == 200
    assert search_mock.call_args.kwargs["license_code"] == "0036"


@pytest.mark.parametrize("invalid_lic", ["123", "12345", "abcd", "00 36", "drop table"])
def test_bids_route_ignores_invalid_lic_in_search(monkeypatch, logged_in_client, invalid_lic):
    search_mock = Mock(return_value=SearchPage(ids=[], has_next=False))
    monkeypatch.setattr(settings, "MEILI_ENABLED", True, raising=False)
    monkeypatch.setattr("src.app.services.search_index.MeiliSearchClient.search", search_mock)

    response = logged_in_client.get("/bids/", params={"lic": invalid_lic})
    assert response.status_code == 200
    # 잘못된 형식은 무시되어 None 으로 전달
    assert search_mock.call_args.kwargs.get("license_code") is None


# --------------------------------------------------------------------------- #
# (f) 페이지 링크에 lic 보존 및 안내 문구 렌더링, 업종 선택지 캐싱
# --------------------------------------------------------------------------- #


def test_bids_page_preserves_lic_in_pagination_and_form(monkeypatch, logged_in_client, isolated_db):
    now = utcnow()
    row = BidAnnouncement(
        bid_ntce_no="PAGINATE-LIC",
        bid_ntce_ord="000",
        bid_ntce_nm="페이지 공고",
        category="Servc",
        bid_ntce_dt=now,
        collected_at=now,
    )
    isolated_db.add(row)
    isolated_db.commit()

    search_mock = Mock(return_value=SearchPage(ids=[row.id], has_next=True))
    monkeypatch.setattr(settings, "MEILI_ENABLED", True, raising=False)
    monkeypatch.setattr("src.app.services.search_index.MeiliSearchClient.search", search_mock)

    response = logged_in_client.get("/bids/", params={"lic": "0036", "page": 1})
    assert response.status_code == 200
    html = response.text

    # 1. 폼 input에 lic 값 유지
    assert 'name="lic"' in html
    assert 'value="0036"' in html

    # 2. 다음 페이지 링크에 lic=0036 보존
    assert "lic=0036" in html
    assert "page=2" in html

    # 3. 계약 안내 문구 노출
    expected_notice = (
        "면허제한 업종이나 허용업종에 해당 업종이 있는 공고만 표시합니다. "
        "업종 제한이 없는 공고는 제외됩니다"
    )
    assert expected_notice in html


def test_top_industry_choices_uses_cache(isolated_db):
    now = utcnow()
    isolated_db.add(
        BidAnnouncementLicenseLimit(
            bid_ntce_no="CACHE-TEST-1",
            bid_ntce_ord="000",
            lmt_grp_no="1",
            lmt_sno="1",
            lcns_lmt_nm="정보통신공사업/0036",
            permsn_indstryty_list="[전문소방공사감리업/1492]",
            collected_at=now,
        )
    )
    isolated_db.commit()

    # 첫 호출: DB에서 계산 후 캐시 저장
    choices1 = bid_queries.get_top_industry_choices(isolated_db)
    assert len(choices1) >= 2
    codes1 = [c["code"] for c in choices1]
    assert "0036" in codes1
    assert "1492" in codes1

    # 새 행 추가 (캐시 무효화 전)
    isolated_db.add(
        BidAnnouncementLicenseLimit(
            bid_ntce_no="CACHE-TEST-2",
            bid_ntce_ord="000",
            lmt_grp_no="1",
            lmt_sno="1",
            lcns_lmt_nm="전기공사업/0037",
            collected_at=now,
        )
    )
    isolated_db.commit()

    # 두 번째 호출: 캐시에서 반환되어 새 행이 반영되지 않음 (1시간 캐시 계약)
    choices2 = bid_queries.get_top_industry_choices(isolated_db)
    codes2 = [c["code"] for c in choices2]
    assert "0037" not in codes2

    # 캐시 삭제 후 재호출: 새 행 반영
    cache.delete(bid_queries.TOP_INDUSTRY_CHOICES_CACHE_KEY)
    choices3 = bid_queries.get_top_industry_choices(isolated_db)
    codes3 = [c["code"] for c in choices3]
    assert "0037" in codes3

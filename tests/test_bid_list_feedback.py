"""tests/test_bid_list_feedback.py

2026-10-06 웹 피드백 개정(업종 한정, 지역 제한) 검증.

- 4개 업종(파견, 경비업, 위생관리용역업, 유료직업소개업) 확정 코드 매핑과 7740 제외
- 목록 기본 조건의 4개 업종 합집합 한정과 그 안에서의 하위 선택
- 참가가능지역 기준 지역 제한 필터와 '행 없음' 처리
- 목록 화면의 발주처 지역·참가가능지역 표시
- SQL 경로와 Meilisearch 문서 판정의 동등성

업종 한정은 서비스가 아니라 라우트 계층에서 lic 기본값을 합집합으로 넘겨 적용합니다.
home 대시보드 목록은 이 개정 범위가 아닙니다.
"""

from unittest.mock import Mock

from fastapi.testclient import TestClient

from src.app.core.config import settings
from src.app.core.security import SESSION_COOKIE_NAME, create_session, make_password
from src.app.core.timeutil import utcnow
from src.app.main import app
from src.app.models.accounts import CustomUser
from src.app.models.bid_restrictions import (
    BidAnnouncementLicenseLimit,
    BidAnnouncementParticipationRegion,
)
from src.app.models.bids import BidAnnouncement
from src.app.services import bid_queries
from src.app.services.search_index import SearchPage, announcement_document

CONFIRMED_CODES = {
    "1172",
    "1164",
    "1167",
    "1165",
    "1168",
    "2775",
    "1162",
    "5603",
    "5604",
    "5601",
    "5602",
}


def _add_announcement(db, ntce_no: str, *, dminstt_nm: str = "테스트발주기관") -> BidAnnouncement:
    now = utcnow()
    row = BidAnnouncement(
        bid_ntce_no=ntce_no,
        bid_ntce_ord="000",
        bid_ntce_nm=f"업종/지역 공고 {ntce_no}",
        dminstt_nm=dminstt_nm,
        category="Servc",
        bid_ntce_dt=now,
        collected_at=now,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _add_license(db, ntce_no: str, code: str) -> None:
    db.add(
        BidAnnouncementLicenseLimit(
            bid_ntce_no=ntce_no,
            bid_ntce_ord="000",
            lmt_grp_no="1",
            lmt_sno="1",
            lcns_lmt_nm=f"업종_{code}/{code}",
            collected_at=utcnow(),
        )
    )
    db.commit()


def _add_region(db, ntce_no: str, name: str, sno: str = "1") -> None:
    db.add(
        BidAnnouncementParticipationRegion(
            bid_ntce_no=ntce_no,
            bid_ntce_ord="000",
            lmt_sno=sno,
            prtcpt_psbl_rgn_nm=name,
            collected_at=utcnow(),
        )
    )
    db.commit()


def _logged_in_client(isolated_db) -> TestClient:
    user = CustomUser(
        username="feedback_tester",
        password=make_password("pw-feedback-1234"),
        email="feedback@example.com",
        nickname="피드백 검증",
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


# --------------------------------------------------------------------------- #
# 업종 매핑
# --------------------------------------------------------------------------- #


def test_industry_mapping_matches_confirmed_codes():
    assert set(bid_queries.BID_INDUSTRY_CODES) == CONFIRMED_CODES
    assert "7740" not in bid_queries.BID_INDUSTRY_CODE_SET
    assert {key: label for key, label, _codes in bid_queries.BID_INDUSTRY_GROUPS} == {
        "dispatch": "파견",
        "security": "경비업",
        "sanitation": "위생관리용역업",
        "job_placement": "유료직업소개업",
    }


def test_industry_filter_codes_defaults_to_union_and_ignores_outside_codes():
    assert bid_queries.industry_filter_codes("") == list(bid_queries.BID_INDUSTRY_CODES)
    assert bid_queries.industry_filter_codes("0036") == list(bid_queries.BID_INDUSTRY_CODES)
    assert bid_queries.industry_filter_codes("7740") == list(bid_queries.BID_INDUSTRY_CODES)


def test_industry_filter_codes_narrows_within_union():
    assert bid_queries.industry_filter_codes("1164,1167") == ["1164", "1167"]
    assert bid_queries.industry_filter_codes("5601,5602") == ["5601", "5602"]
    # 합집합 밖 코드는 무시하고 안쪽 코드만 남긴다.
    assert bid_queries.industry_filter_codes("1162,7740") == ["1162"]


# --------------------------------------------------------------------------- #
# 목록 기본 한정과 하위 선택 (SQL 경로)
# --------------------------------------------------------------------------- #


def _seed_industry_rows(db) -> dict[str, BidAnnouncement]:
    rows = {
        "parsed": _add_announcement(db, "FB-PARSED"),
        "security": _add_announcement(db, "FB-SECURITY"),
        "sanitation": _add_announcement(db, "FB-SANITATION"),
        "job": _add_announcement(db, "FB-JOB"),
        "livestock": _add_announcement(db, "FB-LIVESTOCK"),
        "unlimited": _add_announcement(db, "FB-UNLIMITED"),
    }
    _add_license(db, "FB-PARSED", "1172")
    _add_license(db, "FB-SECURITY", "1164")
    _add_license(db, "FB-SANITATION", "1162")
    _add_license(db, "FB-JOB", "5601")
    _add_license(db, "FB-LIVESTOCK", "7740")
    return rows


def test_default_list_limited_to_four_industries(monkeypatch, isolated_db):
    monkeypatch.setattr(settings, "MEILI_ENABLED", False, raising=False)
    rows = _seed_industry_rows(isolated_db)

    page = bid_queries.list_announcements(
        isolated_db, lic=",".join(bid_queries.industry_filter_codes(""))
    )
    ids = {row.id for row in page.object_list}

    assert ids == {rows["parsed"].id, rows["security"].id, rows["sanitation"].id, rows["job"].id}
    assert rows["livestock"].id not in ids  # 7740 제외
    assert rows["unlimited"].id not in ids  # 면허제한 행 없는 공고 제외


def test_route_defaults_to_four_industries(monkeypatch, isolated_db):
    monkeypatch.setattr(settings, "MEILI_ENABLED", False, raising=False)
    rows = _seed_industry_rows(isolated_db)
    titles = {key: row.bid_ntce_nm for key, row in rows.items()}
    client = _logged_in_client(isolated_db)

    response = client.get("/bids/")
    assert response.status_code == 200
    html = response.text

    assert titles["parsed"] in html
    assert titles["job"] in html
    assert titles["livestock"] not in html
    assert titles["unlimited"] not in html


def test_route_narrows_within_union(monkeypatch, isolated_db):
    monkeypatch.setattr(settings, "MEILI_ENABLED", False, raising=False)
    rows = _seed_industry_rows(isolated_db)
    titles = {key: row.bid_ntce_nm for key, row in rows.items()}
    client = _logged_in_client(isolated_db)

    security_only = client.get("/bids/", params={"lic": "1164"})
    assert titles["security"] in security_only.text
    assert titles["parsed"] not in security_only.text

    job_only = client.get("/bids/", params={"lic": "5601,5602"})
    assert titles["job"] in job_only.text
    assert titles["security"] not in job_only.text


def test_route_ignores_outside_union_code(monkeypatch, isolated_db):
    monkeypatch.setattr(settings, "MEILI_ENABLED", False, raising=False)
    rows = _seed_industry_rows(isolated_db)
    titles = {key: row.bid_ntce_nm for key, row in rows.items()}
    client = _logged_in_client(isolated_db)

    response = client.get("/bids/", params={"lic": "7740"})
    assert titles["parsed"] in response.text
    assert titles["livestock"] not in response.text


# --------------------------------------------------------------------------- #
# 참가가능지역 기준 지역 제한
# --------------------------------------------------------------------------- #


def _seed_region_rows(db) -> dict[str, BidAnnouncement]:
    rows = {
        "seoul": _add_announcement(db, "FB-RGN-SEOUL", dminstt_nm="서울특별시 강남구"),
        "busan": _add_announcement(db, "FB-RGN-BUSAN", dminstt_nm="부산광역시 해운대구"),
        "none": _add_announcement(db, "FB-RGN-NONE", dminstt_nm="대구광역시 중구"),
    }
    for row in rows.values():
        _add_license(db, row.bid_ntce_no, "1162")
    _add_region(db, "FB-RGN-SEOUL", "서울특별시")
    _add_region(db, "FB-RGN-BUSAN", "부산광역시")
    return rows


def test_region_filter_uses_participation_region(monkeypatch, isolated_db):
    monkeypatch.setattr(settings, "MEILI_ENABLED", False, raising=False)
    rows = _seed_region_rows(isolated_db)
    union = ",".join(bid_queries.industry_filter_codes(""))

    seoul = bid_queries.list_announcements(isolated_db, lic=union, region="seoul")
    assert {row.id for row in seoul.object_list} == {rows["seoul"].id}

    busan = bid_queries.list_announcements(isolated_db, lic=union, region="busan")
    assert {row.id for row in busan.object_list} == {rows["busan"].id}

    # 지역을 고르지 않으면 참가가능지역 행이 없는 공고도 목록에 남는다.
    all_rows = bid_queries.list_announcements(isolated_db, lic=union)
    assert {row.id for row in all_rows.object_list} == {row.id for row in rows.values()}


def test_region_filter_excludes_rows_without_participation_region(monkeypatch, isolated_db):
    monkeypatch.setattr(settings, "MEILI_ENABLED", False, raising=False)
    rows = _seed_region_rows(isolated_db)
    union = ",".join(bid_queries.industry_filter_codes(""))

    filtered = bid_queries.list_announcements(isolated_db, lic=union, region="busan")
    ids = {row.id for row in filtered.object_list}
    assert rows["none"].id not in ids  # 행 없음 -> 제한 없음으로 단정하지 않는다


# --------------------------------------------------------------------------- #
# 목록 표시 (발주처 지역 + 참가가능지역)
# --------------------------------------------------------------------------- #


def test_list_displays_region_and_participation_region(monkeypatch, isolated_db):
    monkeypatch.setattr(settings, "MEILI_ENABLED", False, raising=False)
    _seed_region_rows(isolated_db)
    client = _logged_in_client(isolated_db)

    html = client.get("/bids/").text

    assert "발주처" in html
    assert "참가가능" in html
    assert "서울특별시" in html
    assert "부산광역시" in html
    assert "참가 지역 제한 정보 없음" in html


def test_region_display_helper_attaches_values(isolated_db):
    rows = _seed_region_rows(isolated_db)
    bids = [rows["seoul"], rows["none"]]
    bid_queries.load_announcement_region_display(isolated_db, bids)

    assert rows["seoul"].institution_region == "서울특별시"  # type: ignore[attr-defined]
    assert rows["seoul"].participation_regions == ["서울특별시"]  # type: ignore[attr-defined]
    assert rows["none"].institution_region == "대구광역시"  # type: ignore[attr-defined]
    assert rows["none"].participation_regions == []  # type: ignore[attr-defined]


# --------------------------------------------------------------------------- #
# SQL·Meilisearch 동등성
# --------------------------------------------------------------------------- #


def test_announcement_document_carries_participation_region_codes():
    row = BidAnnouncement(
        id=101,
        bid_ntce_no="FB-DOC",
        bid_ntce_ord="000",
        bid_ntce_nm="문서 공고",
        dminstt_nm="서울특별시 강남구",
        category="Servc",
        bid_ntce_dt=utcnow(),
        collected_at=utcnow(),
    )
    document = announcement_document(
        row,
        license_codes=["1162"],
        participation_region_names=["서울특별시", "경기도"],
    )
    assert document["participation_region_codes"] == ["seoul", "gyeonggi"]
    assert document["license_codes"] == ["1162"]


def test_sql_and_meili_region_selection_agree(monkeypatch, isolated_db):
    monkeypatch.setattr(settings, "MEILI_ENABLED", False, raising=False)
    rows = _seed_region_rows(isolated_db)
    union = ",".join(bid_queries.industry_filter_codes(""))
    region_names = {
        "FB-RGN-SEOUL": ["서울특별시"],
        "FB-RGN-BUSAN": ["부산광역시"],
        "FB-RGN-NONE": [],
    }

    for region_code in ("seoul", "busan"):
        meili_ids: set[int] = set()
        for row in rows.values():
            document = announcement_document(
                row,
                license_codes=["1162"],
                participation_region_names=region_names[row.bid_ntce_no],
            )
            if region_code in document["participation_region_codes"]:
                meili_ids.add(int(document["source_id"]))

        db_page = bid_queries.list_announcements(isolated_db, lic=union, region=region_code)
        db_ids = {row.id for row in db_page.object_list}
        assert db_ids == meili_ids


def test_route_default_industry_reaches_search_index(monkeypatch, isolated_db):
    search = Mock(return_value=SearchPage(ids=[], has_next=False))
    monkeypatch.setattr(settings, "MEILI_ENABLED", True, raising=False)
    monkeypatch.setattr("src.app.services.search_index.MeiliSearchClient.search", search)
    client = _logged_in_client(isolated_db)

    response = client.get("/bids/")
    assert response.status_code == 200
    assert search.call_args.kwargs["license_codes"] == list(bid_queries.BID_INDUSTRY_CODES)

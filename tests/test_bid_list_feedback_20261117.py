"""tests/test_bid_list_feedback_20261117.py

2026-11-17 웹 피드백: 공고 탐색(/bids/) 첫 화면의 업종 체크박스 기본 해제.

- (a) lic 없이 열면 업종 체크박스에 checked 가 하나도 없다.
- (b) 이때 목록 질의에 넘어가는 lic 는 지금처럼 4개 업종 전체 코드다.
- (c) /bids/?lic=1172 로 열면 파견만 checked 다.
"""

import re
from unittest.mock import Mock

from fastapi.testclient import TestClient

from src.app.core.config import settings
from src.app.core.security import SESSION_COOKIE_NAME, create_session, make_password
from src.app.core.timeutil import utcnow
from src.app.main import app
from src.app.models.accounts import CustomUser
from src.app.services import bid_queries
from src.app.services.search_index import SearchPage

LIC_INPUT_RE = re.compile(r'<input[^>]*name="lic"[^>]*>')
VALUE_RE = re.compile(r'value="([^"]*)"')


def _logged_in_client(isolated_db) -> TestClient:
    user = CustomUser(
        username="feedback_20261117",
        password=make_password("pw-feedback-20261117"),
        email="feedback-20261117@example.com",
        nickname="업종 체크 검증",
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


def _industry_checked_values(html: str) -> list[str]:
    checked: list[str] = []
    for tag in LIC_INPUT_RE.findall(html):
        if "checked" not in tag:
            continue
        match = VALUE_RE.search(tag)
        checked.append(match.group(1) if match else "")
    return checked


def _spy_list_announcements(monkeypatch) -> dict:
    captured: dict = {}
    original = bid_queries.list_announcements

    def spy(db, **kwargs):
        captured.update(kwargs)
        return original(db, **kwargs)

    monkeypatch.setattr(bid_queries, "list_announcements", spy)
    return captured


def test_bids_first_view_unchecks_industry_boxes(monkeypatch, isolated_db):
    monkeypatch.setattr(settings, "MEILI_ENABLED", False, raising=False)
    _spy_list_announcements(monkeypatch)
    client = _logged_in_client(isolated_db)

    response = client.get("/bids/")

    assert response.status_code == 200
    assert _industry_checked_values(response.text) == []


def test_bids_first_view_keeps_four_industry_query(monkeypatch, isolated_db):
    monkeypatch.setattr(settings, "MEILI_ENABLED", False, raising=False)
    captured = _spy_list_announcements(monkeypatch)
    client = _logged_in_client(isolated_db)

    response = client.get("/bids/")

    assert response.status_code == 200
    assert captured["lic"] == ",".join(bid_queries.BID_INDUSTRY_CODES)


def test_bids_first_view_reaches_search_with_four_industries(monkeypatch, isolated_db):
    search = Mock(return_value=SearchPage(ids=[], has_next=False))
    monkeypatch.setattr(settings, "MEILI_ENABLED", True, raising=False)
    monkeypatch.setattr("src.app.services.search_index.MeiliSearchClient.search", search)
    client = _logged_in_client(isolated_db)

    response = client.get("/bids/")

    assert response.status_code == 200
    assert search.call_args.kwargs["license_codes"] == list(bid_queries.BID_INDUSTRY_CODES)


def test_bids_explicit_lic_checks_only_selected_group(monkeypatch, isolated_db):
    monkeypatch.setattr(settings, "MEILI_ENABLED", False, raising=False)
    captured = _spy_list_announcements(monkeypatch)
    client = _logged_in_client(isolated_db)

    response = client.get("/bids/", params={"lic": "1172"})

    assert response.status_code == 200
    assert _industry_checked_values(response.text) == ["1172"]
    assert captured["lic"] == "1172"


def test_bids_outside_union_lic_shows_no_checked_boxes(monkeypatch, isolated_db):
    monkeypatch.setattr(settings, "MEILI_ENABLED", False, raising=False)
    captured = _spy_list_announcements(monkeypatch)
    client = _logged_in_client(isolated_db)

    response = client.get("/bids/", params={"lic": "7740"})

    assert response.status_code == 200
    assert _industry_checked_values(response.text) == []
    assert captured["lic"] == ",".join(bid_queries.BID_INDUSTRY_CODES)

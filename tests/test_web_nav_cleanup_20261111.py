"""2026-11-11 사용자 웹 개편 탐색 정리 시험.

정본: .orca/capsules/task_web_nav_cleanup_20261111/capsule.yaml.
  - 기본 브레드크럼 '기본 프로젝트' 제거, 페이지 제목으로 대체
  - 낙찰 결과 목록을 용역(Servc)으로 고정
  - 입찰 인텔리전스 대시보드 삭제(옛 주소는 홈으로), 비교 분석 메뉴 유지
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.app.core.security import SESSION_COOKIE_NAME, create_session, make_password
from src.app.core.timeutil import utcnow
from src.app.main import app
from src.app.models.accounts import CustomUser
from src.app.services import bid_queries


@pytest.fixture
def seeded_user(isolated_db):
    user = CustomUser(
        username="web_nav_tester",
        password=make_password("pw-test-1234"),
        email="web-nav@example.com",
        nickname="탐색 정리 검증",
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
def auth_client(seeded_user):
    token = create_session(seeded_user.id, seeded_user.username)
    return TestClient(app, cookies={SESSION_COOKIE_NAME: token})


@pytest.mark.parametrize("path", ["/bids/", "/bids/results/"])
def test_pages_do_not_render_default_breadcrumb(auth_client, path):
    body = auth_client.get(path).text

    assert "기본 프로젝트" not in body


def test_result_list_forces_service_category(monkeypatch, auth_client):
    calls: list[dict] = []

    def fake_list_results(db, **kwargs):
        calls.append(kwargs)
        return bid_queries.OffsetPage(object_list=[], number=1, per_page=20, has_next=False)

    monkeypatch.setattr(bid_queries, "list_results", fake_list_results)

    response = auth_client.get("/bids/results/", params={"cat": "Thng"})

    assert response.status_code == 200
    assert calls[0]["cat"] == "Servc"


def test_result_list_has_no_category_select(auth_client):
    body = auth_client.get("/bids/results/").text

    assert 'name="cat"' not in body
    assert "용역 분야" in body


@pytest.mark.parametrize("path", ["/bids/dashboard/", "/dashboard/"])
def test_removed_dashboard_redirects_home(auth_client, path):
    response = auth_client.get(path, follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"] == "/"


def test_sidebar_links_compare_without_dashboard(auth_client):
    body = auth_client.get("/bids/").text

    assert "입찰 인텔리전스" not in body
    assert 'href="/bids/compare/"' in body
    assert "비교 분석" in body

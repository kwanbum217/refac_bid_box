"""SSR 화면의 모바일 반응형 골격 회귀 테스트.

768px 미만에서만 쓰는 왼쪽 서랍(주 메뉴, 챗봇 대화 목록)의 접근성 계약과
CSP 때문에 인라인 이벤트 핸들러를 쓸 수 없어 외부 스크립트로 동작을 옮긴
구조를 렌더링된 HTML 에서 고정합니다. 데스크톱(1024px 이상) 클래스는
md:/lg: 접두로 복원되는지도 함께 확인합니다.
"""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from src.app.core.security import SESSION_COOKIE_NAME, create_session, make_password
from src.app.core.timeutil import utcnow
from src.app.main import app
from src.app.models.accounts import CustomUser

INLINE_HANDLER = re.compile(r"<[a-zA-Z][^>]*\son[a-z]+\s*=")

AUTHENTICATED_PATHS = (
    "/bids/dashboard/",
    "/bids/",
    "/bids/results/",
    "/chatbot/",
    "/accounts/mypage/",
)

ANONYMOUS_PATHS = ("/accounts/login/", "/accounts/signup/")


@pytest.fixture
def seeded_user(isolated_db):
    user = CustomUser(
        username="responsive_tester",
        password=make_password("pw-test-1234"),
        email="responsive@example.com",
        nickname="반응형 검증",
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


def _rendered(client, path: str) -> str:
    response = client.get(path)
    assert response.status_code == 200, path
    return response.text


@pytest.mark.parametrize("path", AUTHENTICATED_PATHS)
def test_authenticated_pages_expose_mobile_nav_drawer(auth_client, path):
    body = _rendered(auth_client, path)

    assert 'id="mobile-nav-toggle"' in body
    assert "data-mobile-nav-toggle" in body
    assert 'aria-controls="mobile-nav-drawer"' in body
    assert 'aria-expanded="false"' in body
    assert 'id="mobile-nav-drawer"' in body
    assert "data-mobile-nav-close" in body


def test_mobile_nav_script_is_loaded_from_static(auth_client):
    body = _rendered(auth_client, "/bids/dashboard/")
    assert "js/mobile-nav.js" in body


def test_sidebar_is_hidden_below_tablet_and_restored_at_md(auth_client):
    body = _rendered(auth_client, "/bids/dashboard/")

    match = re.search(r'<aside id="sidebar" class="([^"]*)"', body)
    assert match, "사이드바 aside 를 찾지 못했습니다"
    classes = match.group(1).split()
    assert "hidden" in classes
    assert "md:flex" in classes
    assert "w-20" in classes
    assert "lg:w-64" in classes


@pytest.mark.parametrize("path", ANONYMOUS_PATHS)
def test_anonymous_pages_do_not_render_nav_drawer(client, path):
    body = _rendered(client, path)
    assert 'id="mobile-nav-drawer"' not in body
    assert 'id="mobile-nav-toggle"' not in body


def test_chat_page_exposes_sessions_drawer(auth_client):
    body = _rendered(auth_client, "/chatbot/")

    assert 'id="chat-sessions-toggle"' in body
    assert "data-chat-sessions-toggle" in body
    assert 'aria-controls="chat-sessions-panel"' in body
    assert 'aria-expanded="false"' in body
    assert 'id="chat-sessions-panel"' in body
    assert 'id="chat-sessions-overlay"' in body

    panel = re.search(r'<aside id="chat-sessions-panel" class="([^"]*)"', body)
    assert panel, "챗봇 대화 목록 aside 를 찾지 못했습니다"
    panel_classes = panel.group(1).split()
    assert "hidden" in panel_classes
    assert "md:flex" in panel_classes


@pytest.mark.parametrize("path", ANONYMOUS_PATHS + AUTHENTICATED_PATHS)
def test_rendered_pages_have_no_inline_event_handlers(auth_client, client, path):
    page_client = client if path in ANONYMOUS_PATHS else auth_client
    body = _rendered(page_client, path)

    assert not INLINE_HANDLER.search(body), "인라인 이벤트 핸들러는 CSP 위반입니다"
    assert "javascript:" not in body.lower()


@pytest.mark.parametrize("path", ANONYMOUS_PATHS + AUTHENTICATED_PATHS)
def test_footer_has_no_empty_links(auth_client, client, path):
    """연결할 페이지가 없는 href="#" 링크를 푸터에 남기지 않습니다."""
    page_client = client if path in ANONYMOUS_PATHS else auth_client
    body = _rendered(page_client, path)

    footer = re.search(r"<footer\b.*?</footer>", body, re.DOTALL)
    assert footer, "푸터를 찾지 못했습니다"
    footer_html = footer.group(0)
    assert 'href="#"' not in footer_html
    for label in ("문서", "지원 센터", "API 안내"):
        assert label not in footer_html

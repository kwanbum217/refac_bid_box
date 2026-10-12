"""SSR 화면의 모바일 반응형 골격 회귀 테스트.

768px 미만에서만 쓰는 왼쪽 서랍(주 메뉴, 챗봇 대화 목록)의 접근성 계약과
CSP 때문에 인라인 이벤트 핸들러를 쓸 수 없어 외부 스크립트로 동작을 옮긴
구조를 렌더링된 HTML 에서 고정합니다. 데스크톱(1024px 이상) 클래스는
md:/lg: 접두로 복원되는지도 함께 확인합니다.

Bootstrap 5 를 함께 불러오므로 이름이 겹치는 간격 유틸리티는 !important 로
Tailwind 의 반응형 변형을 이깁니다. 같은 class 속성에 둘이 함께 있으면 모바일
여백이 데스크톱까지 덮어써지므로, main 에 이미 있던 조합만 예외로 두고
이번 변경이 새로 만든 조합은 test_no_new_bootstrap_spacing_conflicts 가 막습니다.
"""

from __future__ import annotations

import re
from pathlib import Path

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


TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "src" / "app" / "templates"

CLASS_ATTR = re.compile(r'class="([^"]*)"')
RESPONSIVE_PREFIX = re.compile(r"^(?:sm|md|lg|xl|2xl|max-(?:sm|md|lg|xl|2xl)):")

# Bootstrap 5 의 간격 유틸리티 접두. -0 ~ -5 만 생성되며 값이 모두 !important 다.
BOOTSTRAP_SPACING_PREFIXES = frozenset(
    ("p", "px", "py", "pt", "pb", "ps", "pe", "m", "mx", "my", "mt", "mb", "ms", "me", "gap", "g")
)

# main(67ddfc99) 에 원래 있던 조합. Bootstrap 의 !important 값이 이미 적용되고
# 있어 이번 변경의 회귀가 아니므로 그대로 둔다.
PINNED_BOOTSTRAP_CONFLICTS = frozenset(
    {
        ("accounts/login.html", "px-4", "sm:px-6"),
        ("accounts/login.html", "px-4", "lg:px-8"),
        ("accounts/mypage.html", "px-4", "sm:px-6"),
        ("accounts/mypage.html", "px-4", "lg:px-8"),
        ("accounts/mypage_edit.html", "px-4", "sm:px-6"),
        ("accounts/mypage_edit.html", "px-4", "lg:px-8"),
        ("accounts/signup.html", "px-4", "sm:px-6"),
        ("accounts/signup.html", "px-4", "lg:px-8"),
        ("accounts/signup.html", "p-4", "sm:p-6"),
        ("bids/detail.html", "p-3", "sm:p-6"),
        ("bids/detail.html", "p-0", "sm:p-4"),
        ("index.html", "px-5", "sm:px-8"),
        ("index.html", "px-5", "xl:px-10"),
    }
)


def _spacing_axis(token: str) -> str | None:
    """'px-4', 'sm:px-8' 처럼 간격 클래스면 접두(px, py, gap...)를 돌려준다."""
    parts = token.split(":")[-1].split("-")
    if len(parts) < 2 or parts[0] not in BOOTSTRAP_SPACING_PREFIXES:
        return None
    try:
        int(parts[1])
    except ValueError:
        return None
    return parts[0]


def _is_bootstrap_spacing_class(token: str) -> bool:
    """Bootstrap 5 가 -0 ~ -5 로 만드는, 접두 없는 간격 클래스인지 본다."""
    if ":" in token:
        return False
    parts = token.split("-")
    if len(parts) < 2 or parts[0] not in BOOTSTRAP_SPACING_PREFIXES:
        return False
    try:
        step = int(parts[1])
    except ValueError:
        return False
    return 0 <= step <= 5


def _bootstrap_spacing_conflicts(markup: str) -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    for match in CLASS_ATTR.finditer(markup):
        tokens = match.group(1).split()
        for token in tokens:
            if not _is_bootstrap_spacing_class(token):
                continue
            axis = _spacing_axis(token)
            for candidate in tokens:
                if RESPONSIVE_PREFIX.match(candidate) and _spacing_axis(candidate) == axis:
                    found.add((token, candidate))
    return found


def test_no_new_bootstrap_spacing_conflicts():
    """Bootstrap 과 겹치는 간격 클래스 옆에 같은 속성의 반응형 변형을 두지 않는다.

    둘이 같은 class 속성에 있으면 Bootstrap 의 !important 가 반응형 변형을 이겨
    모바일 값이 데스크톱까지 번진다. 모바일 값은 겹치지 않는 클래스의 max-sm:
    변형으로만 주고, main 에 원래 있던 조합은 예외로 고정한다.
    """
    found = set()
    for template in sorted(TEMPLATES_DIR.rglob("*.html")):
        relative = template.relative_to(TEMPLATES_DIR).as_posix()
        for bare, variant in _bootstrap_spacing_conflicts(template.read_text(encoding="utf-8")):
            found.add((relative, bare, variant))

    unexpected = sorted(found - PINNED_BOOTSTRAP_CONFLICTS)
    assert not unexpected, f"Bootstrap 간격 유틸리티와 충돌하는 조합이 추가되었습니다: {unexpected}"

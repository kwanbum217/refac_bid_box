"""
tests/test_csp_nonce.py

요청마다 발급하는 nonce 기반 CSP(Content-Security-Policy) 회귀 테스트입니다.

앱은 모든 HTML 응답에 CSP 헤더를 달고, 템플릿의 인라인 <script> 에는 그 요청의
nonce 를 씁니다. 이 파일은 SSR 화면 전부에 대해 헤더 존재, 응답 본문의 모든 인라인
스크립트 nonce 일치, 인라인 이벤트 속성·javascript: URL 부재, 요청별 nonce 갱신을
확인합니다. JSON API 응답에는 헤더를 강제하지 않습니다.
"""

import re
from datetime import timedelta
from html.parser import HTMLParser

import pytest
from fastapi.testclient import TestClient

from src.app.core.config import settings
from src.app.core.security import SESSION_COOKIE_NAME, create_session, make_password
from src.app.core.timeutil import utcnow
from src.app.main import app
from src.app.models.accounts import CustomUser
from src.app.models.bids import BidAnnouncement, BidResult

CSP_HEADER = "content-security-policy"
NONCE_PATTERN = re.compile(r"'nonce-([A-Za-z0-9_\-]+)'")
INLINE_HANDLER_PATTERN = re.compile(r"on[a-z]+")

EXPECTED_DIRECTIVES = (
    "default-src 'self'",
    "script-src 'self' 'nonce-",
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: https://upload.wikimedia.org",
    "connect-src 'self'",
    "font-src 'self' data:",
    "object-src 'none'",
    "base-uri 'self'",
    "frame-ancestors 'self'",
    "form-action 'self'",
)

ANONYMOUS_PATHS = ("/accounts/login/", "/accounts/signup/")

AUTHENTICATED_PATHS = (
    "/",
    "/bids/",
    "/bids/results/",
    "/bids/dashboard/",
    "/bids/compare/",
    "/chatbot/",
    "/accounts/mypage/",
    "/accounts/mypage/edit/",
)

DETAIL_PATHS = ("/bids/{bid_id}/", "/bids/result/{result_id}/")

SSR_PATH_TEMPLATES = ANONYMOUS_PATHS + AUTHENTICATED_PATHS + DETAIL_PATHS


@pytest.fixture
def seeded_user(isolated_db):
    user = CustomUser(
        username="csp_tester",
        password=make_password("pw-test-1234"),
        email="csp@example.com",
        nickname="CSP 검증",
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


@pytest.fixture
def seeded_bid(isolated_db):
    now = utcnow()
    bid = BidAnnouncement(
        bid_ntce_no="20261011-CSP",
        bid_ntce_ord="00",
        bid_ntce_nm="CSP 검증 도로 포장 공사 공고",
        dminstt_nm="테스트발주기관",
        category="Cnstwk",
        presmpt_prce=1_000_000_000,
        base_amount=990_000_000,
        bid_ntce_dt=now,
        bid_clse_dt=now + timedelta(days=7),
        collected_at=now,
    )
    result = BidResult(
        bid_ntce_no="20261011-CSP",
        bid_ntce_ord="00",
        bid_ntce_nm="CSP 검증 낙찰 결과 공고",
        dminstt_nm="테스트발주기관",
        category="Cnstwk",
        sucsf_bid_amt=880_000_000,
        sucsf_bid_rate=88.88,
        rl_openg_dt=now,
        collected_at=now,
    )
    isolated_db.add_all([bid, result])
    isolated_db.commit()
    isolated_db.refresh(bid)
    isolated_db.refresh(result)
    return bid, result


@pytest.fixture
def ssr_page(client, auth_client, seeded_bid):
    """경로 템플릿을 실제 경로로 바꿔 SSR 응답을 돌려주는 조회 함수입니다."""
    bid, result = seeded_bid
    ids = {"bid_id": bid.id, "result_id": result.id}
    cached: dict[str, object] = {}

    def get(path_template: str):
        path = path_template.format(**ids)
        if path not in cached:
            page_client = client if path_template in ANONYMOUS_PATHS else auth_client
            cached[path] = page_client.get(path)
        return cached[path]

    return get


class _HtmlInspector(HTMLParser):
    """응답 본문에서 인라인 스크립트 nonce 와 인라인 이벤트 속성을 모읍니다."""

    def __init__(self) -> None:
        super().__init__()
        self.inline_script_nonces: list[str | None] = []
        self.inline_handlers: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "script" and not attributes.get("src"):
            self.inline_script_nonces.append(attributes.get("nonce"))
        self.inline_handlers.extend(
            name for name in attributes if INLINE_HANDLER_PATTERN.fullmatch(name)
        )


def _header_nonce(response) -> str:
    match = NONCE_PATTERN.search(response.headers[CSP_HEADER])
    assert match, response.headers[CSP_HEADER]
    return match.group(1)


def _script_src(policy: str) -> str:
    for directive in policy.split(";"):
        directive = directive.strip()
        if directive.startswith("script-src"):
            return directive
    return ""


@pytest.mark.parametrize("path_template", SSR_PATH_TEMPLATES)
def test_ssr_page_has_nonce_csp_header(ssr_page, path_template):
    response = ssr_page(path_template)

    assert response.status_code == 200, path_template
    policy = response.headers[CSP_HEADER]
    assert "'unsafe-eval'" not in _script_src(policy)
    assert "'unsafe-inline'" not in _script_src(policy)
    assert NONCE_PATTERN.search(policy)


def test_csp_policy_keeps_required_directives(client):
    policy = client.get("/accounts/login/").headers[CSP_HEADER]

    for directive in EXPECTED_DIRECTIVES:
        assert directive in policy, directive


@pytest.mark.parametrize("path_template", SSR_PATH_TEMPLATES)
def test_every_inline_script_uses_response_nonce(ssr_page, path_template):
    response = ssr_page(path_template)
    inspector = _HtmlInspector()
    inspector.feed(response.text)

    assert inspector.inline_script_nonces, path_template
    nonce = _header_nonce(response)
    assert inspector.inline_script_nonces == [nonce] * len(inspector.inline_script_nonces)


@pytest.mark.parametrize("path_template", SSR_PATH_TEMPLATES)
def test_no_inline_event_attributes_or_javascript_urls(ssr_page, path_template):
    response = ssr_page(path_template)
    inspector = _HtmlInspector()
    inspector.feed(response.text)

    assert inspector.inline_handlers == []
    assert "javascript:" not in response.text.lower()


def test_nonce_changes_between_requests(auth_client, seeded_bid):
    first = auth_client.get("/")
    second = auth_client.get("/")

    assert first.status_code == 200
    assert second.status_code == 200
    assert _header_nonce(first) != _header_nonce(second)
    for response in (first, second):
        inspector = _HtmlInspector()
        inspector.feed(response.text)
        nonce = _header_nonce(response)
        assert inspector.inline_script_nonces == [nonce] * len(inspector.inline_script_nonces)


def test_docs_ui_is_excluded_from_csp(client):
    if not settings.docs_enabled:
        pytest.skip("문서 UI 가 닫힌 환경입니다")

    for path in ("/docs", "/redoc"):
        response = client.get(path)
        assert response.status_code == 200
        assert CSP_HEADER not in response.headers


def test_json_api_response_does_not_carry_html_csp(client):
    response = client.post("/api/v1/accounts/login", json={})

    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/json")
    assert CSP_HEADER not in response.headers

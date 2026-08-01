"""
tests/test_ui_ssr.py

원본 Django 템플릿 12종을 Jinja2 로 이식한 SSR 화면의 회귀 테스트입니다.
템플릿이 컴파일만 되고 실제로는 빈 화면을 내보내는 상황을 막기 위해,
DB 에 넣은 값이 응답 HTML 에 실제로 나타나는지까지 확인합니다.
"""

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from jinja2 import TemplateSyntaxError

from src.app.core.security import SESSION_COOKIE_NAME, create_session, make_password
from src.app.core.templating import TEMPLATE_DIR, templates
from src.app.main import app
from src.app.models.accounts import CustomUser
from src.app.models.bids import BidAnnouncement, BidResult

PROTECTED_PATHS = [
    "/",
    "/bids/",
    "/results/",
    "/dashboard/",
    "/compare/",
    "/chat/",
]


@pytest.fixture
def seeded_user(isolated_db):
    user = CustomUser(
        username="ssr_tester",
        password=make_password("pw-test-1234"),
        email="ssr@example.com",
        nickname="SSR 검증",
        is_active=True,
        is_staff=False,
        is_superuser=False,
        date_joined=datetime.utcnow(),
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
    now = datetime.utcnow()
    bid = BidAnnouncement(
        bid_ntce_no="20260801-TEST",
        bid_ntce_ord="00",
        bid_ntce_nm="테스트 도로 포장 공사 공고",
        dminstt_nm="테스트발주기관",
        category="Cnstwk",
        presmpt_prce=1_000_000_000,
        base_amount=990_000_000,
        bid_ntce_dt=now,
        bid_clse_dt=now + timedelta(days=7),
        collected_at=now,
    )
    result = BidResult(
        bid_ntce_no="20260801-TEST",
        bid_ntce_ord="00",
        bid_ntce_nm="테스트 낙찰 결과 공고",
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


def test_all_templates_compile():
    """12종 템플릿이 Jinja2 문법 오류 없이 컴파일된다."""
    names = sorted(
        str(path.relative_to(TEMPLATE_DIR)) for path in TEMPLATE_DIR.rglob("*.html")
    )
    assert len(names) == 12, names
    for name in names:
        try:
            templates.env.get_template(name)
        except TemplateSyntaxError as exc:  # pragma: no cover - 실패 시 진단용
            pytest.fail(f"{name}:{exc.lineno} {exc.message}")


@pytest.mark.parametrize("path", PROTECTED_PATHS)
def test_protected_pages_redirect_when_anonymous(client, path):
    """원본 LoginRequiredMixin 과 동일하게 비로그인 접근은 로그인으로 보낸다."""
    response = client.get(path, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == f"/accounts/login/?next={path}"


@pytest.mark.parametrize("path", PROTECTED_PATHS)
def test_protected_pages_render_when_logged_in(auth_client, seeded_bid, path):
    response = auth_client.get(path)
    assert response.status_code == 200
    assert "BIDBOX" in response.text


def test_bid_list_renders_actual_row(auth_client, seeded_bid):
    """목록 화면이 DB 행을 실제로 출력하는지 확인한다 (빈 껍데기 방지)."""
    bid, _ = seeded_bid
    response = auth_client.get("/bids/")
    assert response.status_code == 200
    assert bid.bid_ntce_nm in response.text
    assert bid.dminstt_nm in response.text


def test_result_list_renders_actual_row(auth_client, seeded_bid):
    _, result = seeded_bid
    response = auth_client.get("/results/")
    assert response.status_code == 200
    assert result.bid_ntce_nm in response.text


def test_bid_detail_renders(auth_client, seeded_bid):
    bid, _ = seeded_bid
    response = auth_client.get(f"/bids/{bid.id}/")
    assert response.status_code == 200
    assert bid.bid_ntce_nm in response.text


def test_result_detail_renders(auth_client, seeded_bid):
    _, result = seeded_bid
    response = auth_client.get(f"/results/{result.id}/")
    assert response.status_code == 200
    assert result.bid_ntce_nm in response.text


def test_bid_list_search_filters_rows(auth_client, seeded_bid):
    """검색어가 실제로 결과를 좁히는지 확인한다."""
    bid, _ = seeded_bid
    hit = auth_client.get("/bids/", params={"q": "도로 포장"})
    miss = auth_client.get("/bids/", params={"q": "존재하지않는공고명XYZ"})
    assert bid.bid_ntce_nm in hit.text
    assert bid.bid_ntce_nm not in miss.text


def test_region_filter_groups_render(auth_client, seeded_bid):
    """지역 필터가 group['items'] 로 정상 순회되는지 확인한다."""
    response = auth_client.get("/bids/")
    assert "서울특별시" in response.text


def test_auth_pages_render_for_anonymous(client):
    for path in ("/accounts/login/", "/accounts/signup/"):
        response = client.get(path)
        assert response.status_code == 200
        assert "BIDBOX" in response.text


def test_signup_form_fields_render(client):
    """폼 호환 계층이 Django BoundField 처럼 순회·렌더링되는지 확인한다."""
    response = client.get("/accounts/signup/")
    body = response.text
    for name in ("username", "password1", "password2", "nickname", "email"):
        assert f'name="{name}"' in body, name
    # birth_y/m/d 는 원본에서 HiddenInput 이다
    assert 'type="hidden" name="birth_y"' in body
    # 성별은 RadioSelect
    assert 'type="radio" name="gender"' in body


def test_social_login_buttons_hidden(client):
    """소셜 인증이 없으므로 동작하지 않는 링크가 노출되면 안 된다."""
    body = client.get("/accounts/login/").text
    assert 'href=""' not in body
    assert "provider_login_url" not in body


def test_authenticated_user_redirected_from_auth_pages(auth_client):
    response = auth_client.get("/accounts/login/", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/"


def test_sidebar_active_nav_differs_per_page(auth_client, seeded_bid):
    """active_nav 치환이 실제로 페이지마다 다른 항목을 강조하는지 확인한다."""
    bids_body = auth_client.get("/bids/").text
    results_body = auth_client.get("/results/").text
    marker = "bg-primary text-white font-bold"
    assert bids_body.count(marker) >= 1
    assert results_body.count(marker) >= 1
    assert bids_body != results_body


def test_missing_detail_returns_404(auth_client):
    """존재하지 않는 상세 페이지는 500 이 아니라 404 를 반환한다."""
    assert auth_client.get("/bids/99999999/").status_code == 404
    assert auth_client.get("/results/99999999/").status_code == 404


def test_chat_header_shows_configured_model(auth_client, seeded_bid):
    """원본에 하드코딩되어 있던 모델명이 실제 설정값으로 표시되는지 확인한다."""
    from src.app.core.config import settings

    body = auth_client.get("/chat/").text
    assert "Gemini 3.1 Flash-Lite preview" not in body
    if settings.LLM_PROVIDER == "gemini":
        assert settings.GEMINI_MODEL in body
    else:
        assert settings.OLLAMA_MODEL in body
    assert "842K Records Indexed" not in body


def test_login_post_success_sets_session(client, seeded_user):
    """SSR 로그인 폼 제출이 세션 쿠키를 발급하고 홈으로 보낸다."""
    response = client.post(
        "/accounts/login/",
        data={"username": "ssr_tester", "password": "pw-test-1234"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/"
    assert SESSION_COOKIE_NAME in response.cookies


def test_login_post_failure_rerenders_with_error(client, seeded_user):
    """실패 시 401 과 함께 오류 메시지가 담긴 로그인 화면을 다시 그린다."""
    response = client.post(
        "/accounts/login/",
        data={"username": "ssr_tester", "password": "wrong-password"},
        follow_redirects=False,
    )
    assert response.status_code == 401
    assert "아이디 또는 비밀번호가 올바르지 않습니다." in response.text


def test_login_post_honours_next_param(client, seeded_user):
    """로그인 리다이렉트의 next 파라미터가 실제로 반영된다."""
    response = client.post(
        "/accounts/login/?next=/bids/",
        data={"username": "ssr_tester", "password": "pw-test-1234"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/bids/"


def test_logout_clears_session(auth_client):
    """원본은 링크(GET)로 로그아웃하므로 GET 도 동작해야 한다."""
    response = auth_client.get("/accounts/logout/", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/accounts/login/"

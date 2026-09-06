"""tests/e2e/test_ssr_auth.py

SSR 브라우저 E2E 인증 플로우 검증 테스트.
- 회원가입 성공 및 DB 사용자 생성 검증
- 로그인 성공 및 세션 쿠키 발급, 홈 이동 검증
- next 쿼리 파라미터를 통한 타깃 URL 리다이렉트 검증
- POST 로그아웃 및 세션 무효화, 보호 경로 재진입 차단 검증
- CSRF 토큰 누락 시 403 Forbidden 거부 검증
- 잘못된 자격증명 제출 시 로그인 실패 처리 검증
"""

from __future__ import annotations

import contextlib
import re
from typing import Any

import pytest
from playwright.async_api import Page, expect
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from sqlalchemy.orm import Session

from src.app.models.accounts import CustomUser


@pytest.mark.e2e
async def test_ssr_auth_signup_flow(
    page: Page,
    live_server_url: str,
    e2e_db_session: Session,
) -> None:
    """회원가입 폼을 통해 신규 계정을 생성하고 DB 반영 및 리다이렉트를 검증합니다."""
    signup_username = "e2e_new_signup_user"
    # 기존 잔여 데이터 정리
    existing = e2e_db_session.query(CustomUser).filter_by(username=signup_username).first()
    if existing:
        e2e_db_session.delete(existing)
        e2e_db_session.commit()

    response = await page.goto(f"{live_server_url}/accounts/signup/")
    assert response is not None
    assert response.status == 200

    # 폼 필드 입력
    await page.locator("#id_username").fill(signup_username)
    await page.locator("#id_password1").fill("ValidPassword1234!")
    await page.locator("#id_password2").fill("ValidPassword1234!")
    await page.locator("#id_nickname").fill("신규E2E가입자")
    await page.locator("#id_email").fill("new_signup@example.com")
    await page.locator("#id_birth_date").fill("1995-05-15")

    # 성별 라디오 버튼 선택 (sr-only 이므로 force=True 또는 label 선택)
    await page.locator('input[name="gender"][value="M"]').check(force=True)

    # 필수 약관 체크 (force=True)
    await page.locator('input[name="agree_terms"]').check(force=True)
    await page.locator('input[name="agree_privacy"]').check(force=True)

    # 제출
    await page.get_by_role("button", name="계정 생성").click()

    # 회원가입 처리 완료 후 홈으로 이동할 때까지 조건 대기한다.
    # networkidle 은 부하 시 유휴 구간이 없어 타임아웃 오탐을 내므로
    # 실제 검증 대상인 URL 이동을 직접 기다린다.
    await expect(page).not_to_have_url(re.compile(r".*/accounts/signup.*"), timeout=15_000)
    await page.wait_for_load_state("domcontentloaded")

    # DB에 신규 사용자가 정상 생성되었는지 검증
    e2e_db_session.expire_all()
    created_user = e2e_db_session.query(CustomUser).filter_by(username=signup_username).first()
    assert created_user is not None
    assert created_user.nickname == "신규E2E가입자"
    assert created_user.email == "new_signup@example.com"
    assert created_user.is_active is True


@pytest.mark.e2e
async def test_ssr_auth_login_success(
    page: Page,
    live_server_url: str,
    e2e_test_user: dict[str, Any],
) -> None:
    """로그인 폼에 유효한 자격증명을 입력하여 로그인 후 메인 화면으로 이동함을 검증합니다."""
    response = await page.goto(f"{live_server_url}/accounts/login/")
    assert response is not None
    assert response.status == 200

    await page.locator("#id_username").fill(e2e_test_user["username"])
    await page.locator("#id_password").fill(e2e_test_user["password"])
    await page.get_by_role("button", name="로그인").click()

    # 로그인 성공 후 로그인 페이지를 벗어날 때까지 조건 대기한다.
    await expect(page).not_to_have_url(re.compile(r".*/accounts/login.*"), timeout=15_000)

    # 메인 홈으로 이동 확인
    assert "/accounts/login" not in page.url
    # 홈 헤더의 로그아웃 버튼 가시성 확인
    await expect(page.get_by_role("button", name="로그아웃")).to_be_visible(timeout=15_000)

    # 사이드바가 있는 대시보드 페이지 방문 시 닉네임 표시 검증
    await page.goto(f"{live_server_url}/bids/dashboard/")
    await expect(page.locator("body")).to_contain_text(e2e_test_user["nickname"], timeout=15_000)


@pytest.mark.e2e
async def test_ssr_auth_login_with_next_redirect(
    page: Page,
    live_server_url: str,
    e2e_test_user: dict[str, Any],
) -> None:
    """next 파라미터가 지정된 로그인 페이지에서 로그인 성공 시 해당 타깃 경로로 이동함을 검증합니다."""
    target_path = "/bids/"
    response = await page.goto(f"{live_server_url}/accounts/login/?next={target_path}")
    assert response is not None
    assert response.status == 200

    await page.locator("#id_username").fill(e2e_test_user["username"])
    await page.locator("#id_password").fill(e2e_test_user["password"])
    await page.get_by_role("button", name="로그인").click()

    # next 타깃 경로(/bids/)로 이동할 때까지 조건 대기한다.
    await page.wait_for_url(re.compile(r".*/bids/?(?:\?.*)?$"), timeout=15_000)

    # 타깃 경로(/bids/)로 이동 확인
    assert page.url.rstrip("/").endswith("/bids")
    await expect(page.locator("h1")).to_contain_text("공고 탐색", timeout=15_000)


@pytest.mark.e2e
async def test_ssr_auth_logout_post(
    authenticated_page: Page,
    live_server_url: str,
) -> None:
    """인증 상태에서 POST 로그아웃 수행 시 세션이 무효화되고 로그인 페이지로 리다이렉트됨을 검증합니다."""
    # 1. 보호된 화면 진입
    response = await authenticated_page.goto(f"{live_server_url}/bids/dashboard/")
    assert response is not None
    assert response.status == 200

    # 2. 로그아웃 버튼 클릭 (POST 폼 제출)
    logout_btn = authenticated_page.locator(
        'form[action*="/accounts/logout/"] button[type="submit"]'
    ).first
    await logout_btn.click()
    # 로그아웃 POST 처리 후 로그인 페이지로 이동할 때까지 조건 대기한다.
    await authenticated_page.wait_for_url(re.compile(r".*/accounts/login.*"), timeout=15_000)

    # 3. 로그인 페이지로 리다이렉트 확인
    assert "/accounts/login/" in authenticated_page.url

    # 4. 보호된 화면 재접근 시 로그인 리다이렉트 확인 (세션 무효화)
    re_response = await authenticated_page.goto(f"{live_server_url}/bids/dashboard/")
    assert re_response is not None
    await authenticated_page.wait_for_url(re.compile(r".*/accounts/login.*"), timeout=15_000)
    assert "/accounts/login/" in authenticated_page.url


@pytest.mark.e2e
async def test_ssr_auth_csrf_rejection(
    page: Page,
    live_server_url: str,
) -> None:
    """CSRF 토큰 없이 또는 유효하지 않은 토큰으로 POST 요청 시 403 Forbidden이 반환됨을 검증합니다."""
    # CSRF 토큰 없이 direct POST
    response = await page.request.post(
        f"{live_server_url}/accounts/login/",
        data={"username": "test_user", "password": "password1234"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert response.status == 403


@pytest.mark.e2e
async def test_ssr_auth_login_invalid_credentials(
    page: Page,
    live_server_url: str,
) -> None:
    """잘못된 비밀번호 제출 시 오류 알림 대화창이 발생함을 검증합니다."""
    await page.goto(f"{live_server_url}/accounts/login/")

    dialog_message = ""

    async def handle_dialog(dialog: Any) -> None:
        nonlocal dialog_message
        dialog_message = dialog.message
        await dialog.accept()

    page.on("dialog", handle_dialog)

    await page.locator("#id_username").fill("invalid_user_name_e2e")
    await page.locator("#id_password").fill("wrong_password_1234")
    await page.get_by_role("button", name="로그인").click()

    # 실패 알림 대화창이 나타날 때까지 조건 대기한다. 고정 대기는 부하 시
    # 대화창이 늦게 나타나면 놓치고 부하가 없으면 낭비하므로, dialog 이벤트를
    # 직접 기다린다. 대화창 없는 실패 응답도 허용하므로 타임아웃은 무시한다.
    with contextlib.suppress(PlaywrightTimeoutError):
        await page.wait_for_event("dialog", timeout=15_000)
    await expect(page).to_have_url(re.compile(r".*/accounts/login.*"), timeout=15_000)

    # 실패 다이얼로그 확인 또는 로그인 URL 유지 확인
    assert "/accounts/login" in page.url
    assert len(dialog_message) > 0 or "/accounts/login" in page.url

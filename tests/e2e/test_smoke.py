"""tests/e2e/test_smoke.py

SSR 브라우저 E2E 스모크 테스트.
비인증 상태에서 로그인 화면(/accounts/login/)에 정상 접근하여
주요 UI 요소(제목, 입력 폼, 제출 버튼)가 브라우저 DOM에 올바르게 렌더링되는지 검증합니다.
"""

import pytest
from playwright.async_api import Page, expect


@pytest.mark.e2e
async def test_login_page_smoke(page: Page, live_server_url: str) -> None:
    """비인증 사용자가 로그인 화면에 접근할 때 페이지와 폼 요소가 정상 렌더링되는지 검증합니다."""
    response = await page.goto(f"{live_server_url}/accounts/login/")
    assert response is not None
    assert response.status == 200

    # 브라우저 페이지 타이틀 및 메인 헤딩 검증
    await expect(page).to_have_title("로그인 - BIDBOX Intelligence")
    await expect(page.locator("h1")).to_contain_text("계정에 로그인하세요")

    # 로그인 폼 및 주요 입력 필드 DOM 가시성 검증
    username_input = page.locator("#id_username")
    password_input = page.locator("#id_password")
    submit_button = page.get_by_role("button", name="로그인")

    await expect(username_input).to_be_visible()
    await expect(password_input).to_be_visible()
    await expect(submit_button).to_be_visible()

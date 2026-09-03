"""tests/e2e/test_ssr_auth_session.py

SSR 브라우저 E2E 인증 세션 주입 및 DB 격리 검증 테스트.
- G1 데이터 무손실 원칙 준수: 임시 SQLite DB 격리 및 개발 DB 오염 방지 단언
- create_session 기반 세션 쿠키 직접 주입 Fixture 동작 검증
- 인증이 필요한 화면(대시보드 /bids/dashboard/) 로그인 상태 진입 검증
- 비인증 접근 시 로그인 화면 리다이렉트 검증
"""

from __future__ import annotations

from typing import Any

import pytest
from playwright.async_api import Page, expect
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from src.app.core.db import engine as global_engine
from src.app.core.db import get_db
from src.app.main import app
from src.app.models.accounts import CustomUser


def test_e2e_db_isolation_and_dependency_override(
    e2e_db_engine: Engine,
    e2e_db_session: Session,
    e2e_test_user: dict[str, Any],
) -> None:
    """E2E 서버가 개발 DB 가 아닌 격리 SQLite DB 를 사용함을 명확히 단언합니다."""
    # 1. FastAPI get_db 의존성 오버라이드가 등록되어 있는지 확인
    assert get_db in app.dependency_overrides
    override_fn = app.dependency_overrides[get_db]
    assert callable(override_fn)

    # 2. 격리 엔진이 SQLite 기반이며 글로벌 개발 DB 엔진과 분리되어 있는지 검증
    assert e2e_db_engine.url.drivername == "sqlite"
    assert str(global_engine.url) != str(e2e_db_engine.url)

    # 3. 테스트 사용자가 격리 DB 에만 정상 등록되어 있는지 확인
    user = e2e_db_session.query(CustomUser).filter_by(id=e2e_test_user["id"]).first()
    assert user is not None
    assert user.username == e2e_test_user["username"]
    assert user.nickname == e2e_test_user["nickname"]


@pytest.mark.e2e
async def test_authenticated_access_to_protected_page(
    authenticated_page: Page,
    live_server_url: str,
    e2e_test_user: dict[str, Any],
) -> None:
    """세션 쿠키 주입 Fixture 를 통해 인증 필요 화면(/bids/dashboard/)에 정상 진입함을 검증합니다."""
    response = await authenticated_page.goto(f"{live_server_url}/bids/dashboard/")
    assert response is not None
    assert response.status == 200

    # 리다이렉트 없이 대시보드 URL 유지 확인
    assert authenticated_page.url.rstrip("/").endswith("/bids/dashboard")

    # 브라우저 DOM 에 페이지 헤더 및 대시보드 콘텐츠 렌더링 확인
    await expect(
        authenticated_page.locator("h1, header, span.font-semibold")
        .filter(has_text="대시보드")
        .first
    ).to_be_visible()

    # 사이드바에 주입된 사용자 닉네임 및 엔터프라이즈 라벨 가시성 검증
    user_nickname = e2e_test_user["nickname"]
    await expect(
        authenticated_page.locator("p.font-bold").filter(has_text=user_nickname).first
    ).to_be_visible()
    await expect(
        authenticated_page.locator("p").filter(has_text="엔터프라이즈 사용자").first
    ).to_be_visible()


@pytest.mark.e2e
async def test_unauthenticated_access_redirects_to_login(
    page: Page,
    live_server_url: str,
) -> None:
    """비인증 사용자가 보호된 화면 접근 시 로그인 페이지로 리다이렉트됨을 검증합니다."""
    response = await page.goto(f"{live_server_url}/bids/dashboard/")
    assert response is not None
    assert response.status == 200

    # 로그인 페이지 URL 로 리다이렉트 여부 및 next 쿼리 파라미터 확인
    assert "/accounts/login/" in page.url
    assert "next=" in page.url

    # 로그인 폼 렌더링 확인
    await expect(page.locator("#id_username")).to_be_visible()
    await expect(page.locator("#id_password")).to_be_visible()
    await expect(page.get_by_role("button", name="로그인")).to_be_visible()

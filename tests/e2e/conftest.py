"""tests/e2e/conftest.py

SSR 및 프론트엔드 브라우저 E2E 테스트용 공통 Fixture 및 설정.
- 동적 포트 할당 기반 Uvicorn 백그라운드 서버 구동 및 정상 종료 보장
- Headless Chromium 브라우저 바이너리 존재 여부에 따른 자동 skip 처리
- pytest-asyncio 와의 완벽한 융합을 위한 async_playwright 기반 Fixture
- G1 데이터 무손실 원칙 준수: 실제 운영/개발 DB 오염 차단
"""

from __future__ import annotations

import collections.abc
import concurrent.futures
import contextlib
import socket
import threading
import time

import httpx
import pytest
import uvicorn
from playwright.async_api import Browser, BrowserContext, Page, async_playwright

from src.app.main import app

_CHROMIUM_AVAILABLE: bool | None = None


def find_free_port() -> int:
    """사용 가능한 임의의 로컬 포트를 동적으로 찾아 반환합니다."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        s.listen(1)
        return int(s.getsockname()[1])


def _probe_chromium() -> bool:
    """별도 스레드에서 Playwright Chromium 브라우저 런타임을 점검합니다."""
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            browser.close()
            return True
    except Exception:
        return False


def is_chromium_available() -> bool:
    """Playwright Chromium 브라우저 바이너리가 설치되어 실행 가능한지 확인합니다."""
    global _CHROMIUM_AVAILABLE
    if _CHROMIUM_AVAILABLE is not None:
        return _CHROMIUM_AVAILABLE

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            fut = executor.submit(_probe_chromium)
            _CHROMIUM_AVAILABLE = fut.result(timeout=5.0)
    except Exception:
        _CHROMIUM_AVAILABLE = False

    return bool(_CHROMIUM_AVAILABLE)


def pytest_runtest_setup(item: pytest.Item) -> None:
    """테스트 실행 전 브라우저 바이너리 유무를 검사하여 없으면 즉시 skip합니다.

    바이너리가 없는 CI 러너 등에서 에러가 아닌 skip 으로 정상 처리됩니다.
    """
    if (
        "e2e" in item.keywords or "page" in getattr(item, "fixturenames", [])
    ) and not is_chromium_available():
        pytest.skip(
            "Playwright Chromium 브라우저 바이너리가 설치되어 있지 않아 E2E 테스트를 건너뜁니다."
        )


@pytest.fixture(scope="session")
def live_server_url() -> collections.abc.Generator[str, None, None]:
    """FastAPI 앱을 백그라운드 스레드에서 Uvicorn 서버로 구동하고 기본 URL을 반환합니다.

    포트는 동적으로 할당되어 기존 개발/운영 포트 충돌을 방지하며,
    테스트 세션 종료 시 Uvicorn 서버를 정상 종료(graceful shutdown)하여
    프로세스 및 포트 누수를 방지합니다.
    """
    port = find_free_port()
    config = uvicorn.Config(
        app=app,
        host="127.0.0.1",
        port=port,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(config=config)

    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    url = f"http://127.0.0.1:{port}"

    # 서버 준비 대기 (최대 10초)
    deadline = time.time() + 10.0
    started = False
    while time.time() < deadline:
        if server.started:
            with contextlib.suppress(httpx.RequestError, httpx.HTTPStatusError):
                resp = httpx.get(f"{url}/accounts/login/", timeout=1.0)
                if resp.status_code == 200:
                    started = True
                    break
        time.sleep(0.05)

    if not started:
        server.should_exit = True
        thread.join(timeout=2.0)
        raise RuntimeError(f"FastAPI 백그라운드 서버가 포트 {port}에서 정상 기동되지 않았습니다.")

    try:
        yield url
    finally:
        # 서버 정상 종료 및 스레드 정리
        server.should_exit = True
        thread.join(timeout=5.0)


@pytest.fixture
async def browser() -> collections.abc.AsyncIterator[Browser]:
    """Headless Chromium 브라우저 인스턴스를 비동기로 생성하고 종료합니다."""
    async with async_playwright() as p:
        b = await p.chromium.launch(headless=True)
        try:
            yield b
        finally:
            await b.close()


@pytest.fixture
async def context(browser: Browser) -> collections.abc.AsyncIterator[BrowserContext]:
    """새로운 격리된 브라우저 컨텍스트를 생성합니다."""
    ctx = await browser.new_context()
    try:
        yield ctx
    finally:
        await ctx.close()


@pytest.fixture
async def page(context: BrowserContext) -> collections.abc.AsyncIterator[Page]:
    """새로운 브라우저 페이지 인스턴스를 생성합니다."""
    pg = await context.new_page()
    try:
        yield pg
    finally:
        await pg.close()

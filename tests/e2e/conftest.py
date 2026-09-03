"""tests/e2e/conftest.py

SSR 및 프론트엔드 브라우저 E2E 테스트용 공통 Fixture 및 설정.
- 동적 포트 할당 기반 Uvicorn 백그라운드 서버 구동 및 정상 종료 보장
- Headless Chromium 브라우저 바이너리 존재 여부에 따른 자동 skip 처리
- pytest-asyncio 와의 완벽한 융합을 위한 async_playwright 기반 Fixture
- G1 데이터 무손실 원칙 준수: 임시 SQLite 기반 완전 격리 DB 주입으로 개발/운영 DB 오염 원천 차단
- 세션 쿠키(bidbox_session) 직접 주입 Fixture 제공 (UI 로그인 반복 방지)
"""

from __future__ import annotations

import asyncio
import collections.abc
import concurrent.futures
import contextlib
import http.server
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
import uvicorn
from playwright.async_api import Browser, BrowserContext, Page, async_playwright
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from src.app.core.db import Base, get_db
from src.app.core.security import SESSION_COOKIE_NAME, create_session, make_password
from src.app.main import app
from src.app.models.accounts import CustomUser
from src.app.models.bids import BidAnnouncement, BidResult

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


class E2EMockModelWrapper:
    """E2E 테스트 시 무거운 ML 가중치 로드 없이 UI 예측 인터랙션을 검증하기 위한 경량 Mock 어댑터입니다."""

    def __init__(self, name: str = "Quantum Leap V25 Pro") -> None:
        self.metadata = {
            "name": name,
            "required_features": [],
            "interval": {"target_coverage": 0.9},
        }

    def get_display_name(self) -> str:
        return str(self.metadata["name"])

    def get_features(self) -> list[str]:
        return []

    def get_serving_columns(self) -> list[str]:
        return []

    def get_category_levels(self) -> None:
        return None

    def run_preprocess(self, features_dict: dict[str, Any]) -> None:
        return None

    def predict(self, df: Any) -> float:
        return 0.8752

    def predict_interval(self, df: Any) -> tuple[float, float]:
        return (0.8500, 0.9000)


@pytest.fixture(scope="session")
def e2e_db_engine() -> collections.abc.Generator[Engine, None, None]:
    """E2E 테스트 전용 임시 SQLite 격리 DB 엔진을 생성하고 FastAPI 의존성에 주입합니다.

    G1 데이터 무손실 원칙을 보장하기 위해 개발 DB(MySQL procurement)를 완전히 배제하고
    파일 기반 임시 SQLite DB 에 모든 테이블 스키마를 초기화한 뒤 get_db 의존성을 교체합니다.
    테스트 세션 종료 시 의존성 오버라이드를 해제하고 임시 디렉터리를 정리합니다.
    """
    temp_dir = tempfile.mkdtemp(prefix="bidbox_e2e_db_")
    db_path = Path(temp_dir) / "e2e_isolated.db"
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False, "timeout": 30.0},
    )

    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    # 모든 ORM 테이블 스키마 생성
    Base.metadata.create_all(bind=engine)

    isolated_session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def override_get_db() -> collections.abc.Generator[Session, None, None]:
        db = isolated_session_factory()
        try:
            yield db
        finally:
            db.close()

    # FastAPI 의존성 오버라이드 등록 및 글로벌 SessionLocal 교체 (백그라운드 스레드 및 open_thread_session 지원)
    app.dependency_overrides[get_db] = override_get_db

    import src.app.core.db as core_db

    orig_session_local = core_db.SessionLocal
    orig_engine = core_db.engine
    core_db.SessionLocal = isolated_session_factory
    core_db.engine = engine

    try:
        yield engine
    finally:
        app.dependency_overrides.pop(get_db, None)
        core_db.SessionLocal = orig_session_local
        core_db.engine = orig_engine
        engine.dispose()
        shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture(autouse=True)
def _e2e_mock_prediction_models(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """E2E 테스트 실행 시에만 한정하여 가중치 없는 경량 Mock 모델을 안전하게 주입합니다."""
    from src.ml.model_registry import ModelRegistry

    mock_wrapper = E2EMockModelWrapper("Quantum Leap V25 Pro")
    mock_models: dict[str, Any] = {
        "quantum_leap_v25_pro": mock_wrapper,
        "v25": mock_wrapper,
        "servc_institution_v1": mock_wrapper,
    }

    monkeypatch.setattr(ModelRegistry, "_sync_registry", classmethod(lambda cls, force=False: None))
    monkeypatch.setattr(
        ModelRegistry,
        "get_model",
        classmethod(lambda cls, model_id: mock_models.get(str(model_id), mock_wrapper)),
    )
    monkeypatch.setattr(ModelRegistry, "_models", mock_models)


@pytest.fixture(scope="session")
def e2e_session_factory(e2e_db_engine: Engine) -> sessionmaker[Session]:
    """격리 DB 에 연결된 SQLAlchemy SessionFactory 를 반환합니다."""
    return sessionmaker(autocommit=False, autoflush=False, bind=e2e_db_engine)


@pytest.fixture
def e2e_db_session(
    e2e_session_factory: sessionmaker[Session],
) -> collections.abc.Generator[Session, None, None]:
    """개별 테스트 함수에서 격리 DB 에 접근할 수 있는 세션을 제공합니다."""
    session = e2e_session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(scope="session")
def live_server_url(e2e_db_engine: Engine) -> collections.abc.Generator[str, None, None]:
    """FastAPI 앱을 백그라운드 스레드에서 Uvicorn 서버로 구동하고 기본 URL을 반환합니다.

    e2e_db_engine 에 의존하여 서버 구동 전 반드시 격리 DB 의존성 오버라이드가
    완료되도록 보장합니다.
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
def e2e_test_user(e2e_db_session: Session) -> dict[str, Any]:
    """격리 DB 에 테스트 사용자를 생성하고 정보를 반환합니다."""
    username = "e2e_test_user"
    user = e2e_db_session.query(CustomUser).filter_by(username=username).first()
    if user is None:
        user = CustomUser(
            username=username,
            password=make_password("e2e_test_password_1234"),
            email="e2e_test_user@example.com",
            nickname="E2E인증테스터",
            is_active=True,
            is_superuser=False,
            is_staff=False,
            date_joined=datetime.now(UTC),
        )
        e2e_db_session.add(user)
        e2e_db_session.commit()
        e2e_db_session.refresh(user)

    return {
        "id": user.id,
        "username": user.username,
        "nickname": user.nickname,
        "email": user.email,
        "password": "e2e_test_password_1234",
    }


@pytest.fixture
def e2e_session_token(e2e_test_user: dict[str, Any]) -> str:
    """테스트 사용자에 대한 인증 세션 토큰을 create_session 으로 직접 발급합니다."""
    return create_session(user_id=e2e_test_user["id"], username=e2e_test_user["username"])


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
    """새로운 비인증 브라우저 컨텍스트를 생성합니다."""
    ctx = await browser.new_context()
    try:
        yield ctx
    finally:
        await ctx.close()


@pytest.fixture
async def page(context: BrowserContext) -> collections.abc.AsyncIterator[Page]:
    """새로운 비인증 브라우저 페이지 인스턴스를 생성합니다."""
    pg = await context.new_page()
    try:
        yield pg
    finally:
        await pg.close()


@pytest.fixture
async def authenticated_context(
    browser: Browser,
    live_server_url: str,
    e2e_session_token: str,
) -> collections.abc.AsyncIterator[BrowserContext]:
    """인증 세션 쿠키(bidbox_session)가 주입된 브라우저 컨텍스트를 생성합니다."""
    ctx = await browser.new_context()
    await ctx.add_cookies(
        [
            {
                "name": SESSION_COOKIE_NAME,
                "value": e2e_session_token,
                "url": live_server_url,
                "httpOnly": True,
                "sameSite": "Lax",
            }
        ]
    )
    try:
        yield ctx
    finally:
        await ctx.close()


@pytest.fixture
async def authenticated_page(
    authenticated_context: BrowserContext,
) -> collections.abc.AsyncIterator[Page]:
    """인증 세션 쿠키가 적용된 브라우저 페이지 인스턴스를 생성합니다."""
    pg = await authenticated_context.new_page()
    try:
        yield pg
    finally:
        await pg.close()


@pytest.fixture(autouse=True)
def _e2e_mock_rag_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    """E2E 테스트 시 실제 외부 LLM(Ollama/Gemini)이나 ChromaDB 호출 없이 비동기 SSE 스트리밍을 검증하도록 Mock을 주입합니다."""
    from src.rag.engine import rag_engine

    async def mock_stream_tokens(
        query: str,
        history: list[dict[str, Any]] | None = None,
        tool_context: dict[str, Any] | None = None,
    ) -> collections.abc.AsyncIterator[dict[str, Any]]:
        if "오류발생" in query or "simulate_stream_error" in query:
            yield {"type": "token", "text": "스트림 처리 시작 "}
            await asyncio.sleep(0.01)
            raise RuntimeError("시뮬레이션된 LLM 스트림 오류 발생")

        yield {
            "type": "docs",
            "docs": [
                {"title": "공공조달 계약사무처리기준", "content": "제12조 적격심사 세부배점표"}
            ],
        }
        await asyncio.sleep(0.02)

        tokens = [
            "조달청 ",
            "적격심사 ",
            "입찰가격 평점산식 ",
            "분석 결과입니다. ",
            "최적 투찰 전략을 제안합니다.",
        ]
        accumulated = ""
        for t in tokens:
            accumulated += t
            yield {"type": "token", "text": t}
            await asyncio.sleep(0.03)

        yield {
            "type": "done",
            "final_answer": accumulated,
            "trace_id": "e2e_trace_stream_001",
        }

    class MockProvenance:
        def __init__(self, trace_id: str = "e2e_trace_001") -> None:
            self.trace_id = trace_id

        def model_dump(self) -> dict[str, Any]:
            return {"trace_id": self.trace_id, "backend": "mock_e2e"}

    class MockAnswerBundle:
        def __init__(self, answer: str = "E2E 테스트용 단발 질의 응답입니다.") -> None:
            self.answer = answer
            self.provenance = MockProvenance()
            self.retrieved_docs = [{"title": "참조규정", "content": "내용"}]
            self.latency_ms = 25.0
            self.route_reason = "e2e_mock"
            self.citations = []
            self.segment_metrics = {}

    async def mock_get_answer(query: str, db: Any = None) -> MockAnswerBundle:
        return MockAnswerBundle(answer=f"'{query}'에 대한 E2E 모의 응답입니다.")

    def mock_get_answer_sync(
        query: str, db: Any = None, history: Any = None, tool_context: Any = None
    ) -> MockAnswerBundle:
        return MockAnswerBundle(answer=f"'{query}'에 대한 E2E 모의 동기 응답입니다.")

    monkeypatch.setattr(rag_engine, "stream_tokens", mock_stream_tokens)
    monkeypatch.setattr(rag_engine, "get_answer", mock_get_answer)
    monkeypatch.setattr(rag_engine, "get_answer_sync", mock_get_answer_sync)


class _SPAProxyHandler(http.server.SimpleHTTPRequestHandler):
    """React SPA 정적 파일 서빙 및 백엔드 API 요청(/api/*)을 live_server_url 로 중계하는 프록시 핸들러입니다."""

    def __init__(self, *args: Any, live_url: str, dist_dir: str, **kwargs: Any) -> None:
        self.live_url = live_url.rstrip("/")
        self.dist_dir = dist_dir
        super().__init__(*args, directory=dist_dir, **kwargs)

    def log_message(self, format: str, *args: Any) -> None:
        pass

    def do_GET(self) -> None:
        if self.path.startswith("/api/"):
            self._proxy_request("GET")
        else:
            file_path = Path(self.dist_dir) / self.path.lstrip("/").split("?")[0]
            if not file_path.exists() and not self.path.startswith("/assets/"):
                self.path = "/index.html"
            super().do_GET()

    def do_POST(self) -> None:
        if self.path.startswith("/api/"):
            self._proxy_request("POST")
        else:
            self.send_error(405)

    def _proxy_request(self, method: str) -> None:
        target_url = f"{self.live_url}{self.path}"
        headers = {
            k: v for k, v in self.headers.items() if k.lower() not in ("host", "content-length")
        }
        body: bytes | None = None
        if method == "POST":
            content_length = int(self.headers.get("Content-Length", 0))
            if content_length > 0:
                body = self.rfile.read(content_length)

        req = urllib.request.Request(target_url, data=body, headers=headers, method=method)  # noqa: S310
        try:
            with urllib.request.urlopen(req, timeout=30.0) as resp:  # noqa: S310
                self.send_response(resp.status)
                for k, v in resp.getheaders():
                    if k.lower() not in ("transfer-encoding",):
                        self.send_header(k, v)
                self.end_headers()
                while chunk := resp.read(1024):
                    self.wfile.write(chunk)
                    self.wfile.flush()
        except urllib.error.HTTPError as e:
            self.send_response(e.code)
            for k, v in e.headers.items():
                if k.lower() not in ("transfer-encoding",):
                    self.send_header(k, v)
            self.end_headers()
            self.wfile.write(e.read())
        except Exception as exc:
            self.send_response(502)
            self.end_headers()
            self.wfile.write(str(exc).encode())


@pytest.fixture(scope="session")
def react_spa_url(live_server_url: str) -> collections.abc.Generator[str, None, None]:
    """React SPA(frontend/dist)를 빌드 및 서빙하고 백엔드 API를 live_server_url로 프록시합니다."""
    frontend_dir = Path(__file__).parent.parent.parent / "frontend"
    dist_dir = frontend_dir / "dist"

    if not (dist_dir / "index.html").exists():
        npm_bin = shutil.which("npm") or "npm"
        subprocess.run(  # noqa: S603
            [npm_bin, "run", "build"],
            cwd=str(frontend_dir),
            check=True,
            capture_output=True,
        )

    spa_port = find_free_port()

    class CustomHandler(_SPAProxyHandler):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, live_url=live_server_url, dist_dir=str(dist_dir), **kwargs)

    server = http.server.ThreadingHTTPServer(("127.0.0.1", spa_port), CustomHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    url = f"http://127.0.0.1:{spa_port}"
    try:
        yield url
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture
def e2e_seeded_bids(e2e_db_session: Session) -> list[BidAnnouncement]:
    """React SPA 및 SSR E2E 테스트용 공고 및 낙찰 데이터를 격리 DB에 시딩합니다."""
    from datetime import timedelta

    from src.app.core.timeutil import utcnow
    from src.app.models.bids import BidAnnouncement

    now = utcnow()
    announcements: list[BidAnnouncement] = []

    bids_data = [
        (
            "20260901-SPA-THNG-01",
            "00",
            "고성능 AI 분석 서버 및 스토리지 구매",
            "한국지능정보사회진흥원",
            "조달청",
            "Thng",
            500_000_000,
            495_000_000,
            1,
        ),
        (
            "20260901-SPA-SERVC-01",
            "00",
            "차세대 공공조달 빅데이터 AI 플랫폼 고도화 용역",
            "조달청 정보기획과",
            "조달청",
            "Servc",
            850_000_000,
            840_000_000,
            2,
        ),
        (
            "20260901-SPA-CNST-01",
            "00",
            "스마트 데이터센터 전력 설비 보강 공사",
            "한국전력공사",
            "한국전력공사",
            "Cnstwk",
            1_200_000_000,
            1_180_000_000,
            3,
        ),
    ]

    for no, ord_val, nm, dminstt, ntce_instt, cat, presmpt, base, day_offset in bids_data:
        item = (
            e2e_db_session.query(BidAnnouncement)
            .filter_by(bid_ntce_no=no, bid_ntce_ord=ord_val)
            .first()
        )
        if not item:
            item = BidAnnouncement(
                bid_ntce_no=no,
                bid_ntce_ord=ord_val,
                bid_ntce_nm=nm,
                dminstt_nm=dminstt,
                ntce_instt_nm=ntce_instt,
                category=cat,
                presmpt_prce=presmpt,
                base_amount=base,
                bid_ntce_dt=now - timedelta(days=day_offset),
                bid_clse_dt=now + timedelta(days=5),
                openg_dt=now + timedelta(days=5, hours=1),
                collected_at=now,
            )
            e2e_db_session.add(item)
        announcements.append(item)

    r1 = (
        e2e_db_session.query(BidResult)
        .filter_by(bid_ntce_no="20260901-SPA-THNG-01", bid_ntce_ord="00")
        .first()
    )
    if not r1:
        r1 = BidResult(
            bid_ntce_no="20260901-SPA-THNG-01",
            bid_ntce_ord="00",
            bid_ntce_nm="고성능 AI 분석 서버 및 스토리지 구매",
            dminstt_nm="한국지능정보사회진흥원",
            category="Thng",
            sucsf_bid_amt=435_000_000,
            sucsf_bid_rate=87.88,
            bidwinnr_nm="(주)에이아이인프라",
            rl_openg_dt=now - timedelta(days=10),
            collected_at=now,
        )
        e2e_db_session.add(r1)

    e2e_db_session.commit()
    for item in announcements:
        e2e_db_session.refresh(item)

    return announcements

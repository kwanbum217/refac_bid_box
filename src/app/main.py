import asyncio
import logging
import sys
import time
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import TypedDict

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from src.app.api.ui import router as ui_router
from src.app.api.v1.accounts import router as accounts_router
from src.app.api.v1.automation import router as automation_router
from src.app.api.v1.bids import router as bids_router
from src.app.api.v1.chatbot import router as chatbot_router
from src.app.api.v1.health import router as health_router
from src.app.api.v1.health import warmup_state
from src.app.api.v1.predictions import router as predictions_router
from src.app.core.config import Settings, settings

APP_DIR = Path(__file__).resolve().parent

logger = logging.getLogger(__name__)


async def _warm_llm_backend() -> None:
    """로컬 LLM 을 미리 올려 첫 질의가 모델 로드 비용을 내지 않게 합니다.

    2026-08-05 실측에서 콜드 첫 토큰 11.92초, 웜 0.61초였습니다. Phase 7 의
    SSE 첫 토큰 미달(P95 11.06초)은 프리필이 아니라 이 로드 시간이었습니다.

    기동을 막지 않도록 배경 태스크로 돌립니다. 예열이 늦어도 서비스는 정상이며,
    실패해도 첫 질의가 느려질 뿐입니다.
    """
    if not settings.LLM_WARMUP_ON_STARTUP:
        warmup_state.mark_llm_done(skipped=True)
        return
    from src.rag.llm import build_backend

    try:
        backend = await asyncio.to_thread(build_backend)
        if backend is None:
            logger.warning("LLM 백엔드가 없어 예열을 건너뜁니다.")
            warmup_state.mark_llm_done(success=False, error="no_backend")
            return
        success = await asyncio.to_thread(backend.warmup)
        warmup_state.mark_llm_done(success=bool(success))
    except Exception as exc:
        logger.warning("LLM 예열 실패: %s", exc)
        warmup_state.mark_llm_done(success=False, error=str(exc))


async def _warm_predictor() -> None:
    """예측 모델을 미리 올려 기동 직후 요청이 로드 비용을 내지 않게 합니다.

    2026-08-06 실측입니다. 기동 직후 100회에서 P95 164.1ms 로 목표 100ms 를
    넘겼으나, 같은 부하를 예열 뒤에 다시 주니 P95 16.4ms 였습니다. 꼬리 전부가
    첫 요청들이 문 모델 로드 비용이었습니다.

    LLM 예열과 같은 이유로 배경 태스크입니다. 실패해도 첫 요청이 지연 로드로 처리합니다.
    """
    import os

    if os.getenv("SKIP_MODEL_LOAD", "false").lower() == "true":
        logger.info("event=predictor_warmup, status=skipped, elapsed_ms=0.00")
        warmup_state.mark_predictor_done(skipped=True)
        return

    from src.ml.model_registry import ModelRegistry

    t_start = time.perf_counter()
    try:
        count = await asyncio.to_thread(ModelRegistry.load_all_models)
        elapsed_ms = max(0.0, (time.perf_counter() - t_start) * 1000.0)
        logger.info(
            "event=predictor_warmup, status=success, elapsed_ms=%.2f, models_loaded=%d",
            elapsed_ms,
            count if isinstance(count, int) else 0,
        )
        warmup_state.mark_predictor_done(success=True)
    # 예열은 부가 기능입니다. 실패해도 첫 요청이 지연 로드로 처리합니다.
    except Exception as exc:
        elapsed_ms = max(0.0, (time.perf_counter() - t_start) * 1000.0)
        logger.warning(
            "event=predictor_warmup, status=failed, elapsed_ms=%.2f, error=%s",
            elapsed_ms,
            exc,
        )
        warmup_state.mark_predictor_done(success=False, error=str(exc))


async def _warm_vector_search() -> None:
    """ChromaDB 컬렉션과 임베딩 경로를 미리 예열합니다.

    2026-09-01 컨테이너 실측입니다. 프로세스 첫
    `retrieve_semantic_context` 가 13,142ms 였고 이후 46~56ms 였습니다. 비용은
    HNSW 인덱스 적재(첫 질의 4.7초)와 Ollama 임베딩 첫 연결에 몰려 있으며,
    두 번째 요청부터는 사라집니다.

    `keep_alive` 는 Ollama 모델 상주만 보장합니다. ChromaDB 인덱스와 이 프로세스의
    연결·클라이언트 캐시는 그 대상이 아니므로 여기서 따로 예열합니다.

    LLM·예측기 예열과 같은 이유로 배경 태스크이며, 실패해도 첫 질의가 지연 로드로
    처리합니다. **결과에는 영향이 없습니다.** 같은 코드 경로를 한 번 더 부를 뿐입니다.
    """
    if not settings.VECTOR_WARMUP_ON_STARTUP:
        warmup_state.mark_vector_done(skipped=True)
        return

    from src.rag.schemas import RetrievalPlan
    from src.rag.vector_store import retrieve_semantic_context

    t_start = time.perf_counter()
    try:
        plan = RetrievalPlan(semantic_query="예열", filters={})
        await asyncio.to_thread(retrieve_semantic_context, plan)
        elapsed_ms = max(0.0, (time.perf_counter() - t_start) * 1000.0)
        logger.info("event=vector_warmup, status=success, elapsed_ms=%.2f", elapsed_ms)
        warmup_state.mark_vector_done(success=True)
    # 예열은 부가 기능입니다. 실패해도 첫 질의가 지연 로드로 처리합니다.
    except Exception as exc:
        elapsed_ms = max(0.0, (time.perf_counter() - t_start) * 1000.0)
        logger.warning(
            "event=vector_warmup, status=failed, elapsed_ms=%.2f, error=%s",
            elapsed_ms,
            exc,
        )
        warmup_state.mark_vector_done(success=False, error=str(exc))


def _enable_latency_segment_logging() -> None:
    """구간 계측 로그가 실제로 나가도록 로거를 준비합니다.

    계측은 `logger.info` 로 나가는데 컨테이너 런타임의 루트 로거는 WARNING 이고
    핸들러가 없을 수 있습니다. 플래그가 켜진 경우에만 해당 로거의 레벨과 자체 핸들러를
    보강하여 루트 핸들러 유무와 관계없이 로그 유실이 없도록 구성하고, 중복 출력을 막기 위해
    propagate를 비활성화합니다.
    """
    if not settings.LATENCY_SEGMENT_LOGGING:
        return
    segment_logger = logging.getLogger("src.rag.engine")
    segment_logger.setLevel(logging.INFO)
    if not segment_logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        segment_logger.addHandler(handler)
    segment_logger.propagate = False


def _enable_warmup_logging() -> None:
    """예열 로그가 실제로 나가도록 이 모듈 로거를 준비합니다.

    예열 결과는 `logger.info` 로 나가는데 컨테이너 런타임의 루트 로거는 WARNING
    이고 핸들러가 없을 수 있습니다. 그래서 2026-09-01 까지 `predictor_warmup` 과
    `llm_warmup` 로그가 한 줄도 남지 않았고, **예열이 성공했는지 실패했는지
    운영에서 알 수 없었습니다.** 실패해도 조용히 느려질 뿐이라 더 위험합니다.
    """
    if logger.level == logging.NOTSET or logger.level > logging.INFO:
        logger.setLevel(logging.INFO)
    if not logger.handlers and not logging.getLogger().handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)


@asynccontextmanager
async def lifespan(_: FastAPI):
    _enable_warmup_logging()
    _enable_latency_segment_logging()
    warmup_state.start()
    tasks = [
        asyncio.create_task(_warm_llm_backend()),
        asyncio.create_task(_warm_predictor()),
        asyncio.create_task(_warm_vector_search()),
    ]
    try:
        yield
    finally:
        for task in tasks:
            task.cancel()


DOUBLE_SLASH_PREFIX = "/bids//"


class _CorsKwargs(TypedDict):
    allow_origins: list[str]
    allow_credentials: bool
    allow_methods: list[str]
    allow_headers: list[str]


def _docs_kwargs(app_settings: Settings) -> dict[str, str | None]:
    """production 에서 API 문서 표면을 닫습니다.

    docs_url 만 None 으로 두면 /openapi.json 이 남아 전체 스키마가 그대로
    노출됩니다. Swagger UI 는 그 문서를 읽어 화면을 그리는 것이므로 세 경로를
    함께 닫아야 실제로 가려집니다.
    """
    if not app_settings.docs_enabled:
        return {"docs_url": None, "redoc_url": None, "openapi_url": None}
    return {"docs_url": "/docs", "redoc_url": "/redoc", "openapi_url": "/openapi.json"}


def _cors_kwargs(app_settings: Settings) -> _CorsKwargs:
    """자격증명 허용 CORS 의 오리진 범위를 환경에 따라 좁힙니다.

    Starlette 은 allow_origins=["*"] 와 allow_credentials=True 가 함께 오면
    쿠키가 실린 요청에 대해 요청 Origin 을 그대로 반사하고
    Access-Control-Allow-Credentials: true 를 붙입니다. 사실상 임의 오리진
    허용이며, 지금 악용되지 않는 것은 세션 쿠키가 samesite=lax 여서 생긴
    우연한 방어입니다. production 에서는 명시 목록만 허용합니다.

    개발·스테이징은 로컬 화면이 깨지지 않도록 기존 범위를 유지합니다.
    """
    origins = app_settings.cors_allowed_origins
    production = app_settings.ENVIRONMENT == "production"
    if not origins and not production and app_settings.CORS_DEV_ALLOW_ALL:
        origins = ["*"]

    return {
        "allow_origins": origins,
        "allow_credentials": True,
        "allow_methods": ["*"],
        "allow_headers": ["*"],
    }


async def collapse_bids_double_slash(request: Request, call_next):
    """원본 config/urls.py 의 re_path(r'^bids//(?P<remaining>.*)$') 대응입니다.

    화면 스크립트가 경로를 문자열로 이어붙이다 슬래시를 겹쳐 넣는 경우가 있어
    원본은 이를 리다이렉트로 교정했습니다. 없으면 같은 요청이 404 가 됩니다.
    슬래시가 셋 이상이어도 원본처럼 한 번에 하나씩 줄이며 수렴합니다.
    """
    path = request.url.path
    if path.startswith(DOUBLE_SLASH_PREFIX):
        target = "/bids/" + path[len(DOUBLE_SLASH_PREFIX) :]
        if request.url.query:
            target = f"{target}?{request.url.query}"
        return RedirectResponse(target, status_code=302)
    return await call_next(request)


async def mark_prediction_dispatch(request: Request, call_next):
    """예측 sync 엔드포인트의 실행기 대기 기준 시각을 남깁니다.

    sync 라우트는 Starlette/AnyIO 실행기로 넘겨지므로 라우트 함수 안에서는
    요청이 실행기 토큰을 기다린 시간을 직접 알 수 없습니다. ASGI 요청 수신
    직전 시각을 scope 에 남기고 라우트 진입 시 차이를 별도 계측으로 기록해
    모델 구간과 실행기·요청 준비 구간을 분리합니다.
    """
    if request.url.path in {
        "/api/v1/predictions/predict",
        "/api/v1/predictions/predict-price",
    }:
        request.scope["prediction_dispatch_start_ns"] = time.perf_counter_ns()
    return await call_next(request)


class LimitRequestBodySizeMiddleware:
    """요청 본문 크기 상한을 검사하는 ASGI 미들웨어.

    요청 헤더의 Content-Length 또는 실제 수신된 본문 누적 크기가 설정된 상한을
    초과하면 413 (Payload Too Large) 상태 코드로 즉시 거부합니다.
    서버의 응답 스트림(SSE 등)은 일절 건드리지 않고 클라이언트가 보내는 요청 본문만 제한합니다.
    """

    def __init__(self, app, max_body_size: int | None = None):
        self.app = app
        self._max_body_size = max_body_size

    @property
    def max_body_size(self) -> int:
        if self._max_body_size is not None:
            return self._max_body_size
        return int(getattr(settings, "MAX_REQUEST_BODY_SIZE", 10 * 1024 * 1024))

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        limit = self.max_body_size

        # 1. Content-Length 헤더 선행 검사 (대용량 메모리 적재 사전 차단)
        content_length = None
        for key, value in scope.get("headers", []):
            if key.lower() == b"content-length":
                with suppress(ValueError):
                    content_length = int(value.decode("latin1"))
                break

        if content_length is not None and content_length > limit:
            response = JSONResponse(
                status_code=413,
                content={"detail": "요청 본문 크기가 제한을 초과했습니다."},
            )
            await response(scope, receive, send)
            return

        # 2. 청크/스트리밍 수신 본문 누적 크기 검사
        received_bytes = 0

        async def wrapped_receive():
            nonlocal received_bytes
            message = await receive()
            if message["type"] == "http.request":
                body = message.get("body", b"")
                received_bytes += len(body)
                if received_bytes > limit:
                    raise HTTPException(
                        status_code=413,
                        detail="요청 본문 크기가 제한을 초과했습니다.",
                    )
            return message

        try:
            await self.app(scope, wrapped_receive, send)
        except HTTPException as exc:
            if exc.status_code == 413:
                response = JSONResponse(
                    status_code=413,
                    content={"detail": exc.detail or "요청 본문 크기가 제한을 초과했습니다."},
                )
                await response(scope, receive, send)
            else:
                raise


def create_app(app_settings: Settings | None = None) -> FastAPI:
    """환경별 노출 정책을 적용한 앱을 만듭니다.

    팩토리로 둔 이유는 문서 노출과 CORS 범위가 ENVIRONMENT 에 좌우되기
    때문입니다. 모듈 수준 전역 하나만 두면 환경별 동작을 테스트할 때
    모듈을 다시 임포트해야 하고, 그러면 같은 세션의 다른 테스트가 잡은
    앱 객체와 어긋납니다.
    """
    app_settings = app_settings or settings
    docs_kwargs = _docs_kwargs(app_settings)
    cors_kwargs = _cors_kwargs(app_settings)

    app = FastAPI(
        title="refac_bid_box API",
        description="Refactored Procurement Analytics, Hybrid RAG Chatbot, AI Prediction & MLOps Platform",
        version="0.1.0",
        lifespan=lifespan,
        docs_url=docs_kwargs["docs_url"],
        redoc_url=docs_kwargs["redoc_url"],
        openapi_url=docs_kwargs["openapi_url"],
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_kwargs["allow_origins"],
        allow_credentials=cors_kwargs["allow_credentials"],
        allow_methods=cors_kwargs["allow_methods"],
        allow_headers=cors_kwargs["allow_headers"],
    )
    app.add_middleware(
        LimitRequestBodySizeMiddleware,
        max_body_size=app_settings.MAX_REQUEST_BODY_SIZE,
    )
    app.middleware("http")(collapse_bids_double_slash)
    app.middleware("http")(mark_prediction_dispatch)

    app.mount("/static", StaticFiles(directory=str(APP_DIR / "static")), name="static")

    app.include_router(health_router, prefix="/api/v1")
    app.include_router(bids_router, prefix="/api/v1")
    app.include_router(predictions_router, prefix="/api/v1")
    app.include_router(chatbot_router, prefix="/api/v1")
    app.include_router(automation_router, prefix="/api/v1")
    app.include_router(accounts_router, prefix="/api/v1")

    # SSR 화면은 원본 Django 경로를 그대로 사용하므로 prefix 없이 마지막에 포함합니다.
    app.include_router(ui_router)

    return app


app = create_app()

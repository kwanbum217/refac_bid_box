import asyncio
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from src.app.api.ui import router as ui_router
from src.app.api.v1.accounts import router as accounts_router
from src.app.api.v1.automation import router as automation_router
from src.app.api.v1.bids import router as bids_router
from src.app.api.v1.chatbot import router as chatbot_router
from src.app.api.v1.health import router as health_router
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
        return
    from src.rag.llm import build_backend

    backend = await asyncio.to_thread(build_backend)
    if backend is None:
        logger.warning("LLM 백엔드가 없어 예열을 건너뜁니다.")
        return
    await asyncio.to_thread(backend.warmup)


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
    # 예열은 부가 기능입니다. 실패해도 첫 요청이 지연 로드로 처리합니다.
    except Exception as exc:
        elapsed_ms = max(0.0, (time.perf_counter() - t_start) * 1000.0)
        logger.warning(
            "event=predictor_warmup, status=failed, elapsed_ms=%.2f, error=%s",
            elapsed_ms,
            exc,
        )


@asynccontextmanager
async def lifespan(_: FastAPI):
    tasks = [
        asyncio.create_task(_warm_llm_backend()),
        asyncio.create_task(_warm_predictor()),
    ]
    try:
        yield
    finally:
        for task in tasks:
            task.cancel()


DOUBLE_SLASH_PREFIX = "/bids//"


def _docs_kwargs(app_settings: Settings) -> dict[str, str | None]:
    """production 에서 API 문서 표면을 닫습니다.

    docs_url 만 None 으로 두면 /openapi.json 이 남아 전체 스키마가 그대로
    노출됩니다. Swagger UI 는 그 문서를 읽어 화면을 그리는 것이므로 세 경로를
    함께 닫아야 실제로 가려집니다.
    """
    if not app_settings.docs_enabled:
        return {"docs_url": None, "redoc_url": None, "openapi_url": None}
    return {"docs_url": "/docs", "redoc_url": "/redoc", "openapi_url": "/openapi.json"}


def _cors_kwargs(app_settings: Settings) -> dict[str, object]:
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


def create_app(app_settings: Settings | None = None) -> FastAPI:
    """환경별 노출 정책을 적용한 앱을 만듭니다.

    팩토리로 둔 이유는 문서 노출과 CORS 범위가 ENVIRONMENT 에 좌우되기
    때문입니다. 모듈 수준 전역 하나만 두면 환경별 동작을 테스트할 때
    모듈을 다시 임포트해야 하고, 그러면 같은 세션의 다른 테스트가 잡은
    앱 객체와 어긋납니다.
    """
    app_settings = app_settings or settings

    app = FastAPI(
        title="refac_bid_box API",
        description="Refactored Procurement Analytics, Hybrid RAG Chatbot, AI Prediction & MLOps Platform",
        version="0.1.0",
        lifespan=lifespan,
        **_docs_kwargs(app_settings),
    )

    app.add_middleware(CORSMiddleware, **_cors_kwargs(app_settings))
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

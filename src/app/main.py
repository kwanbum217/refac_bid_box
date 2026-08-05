import asyncio
import logging
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

APP_DIR = Path(__file__).resolve().parent

logger = logging.getLogger(__name__)


async def _warm_llm_backend() -> None:
    """로컬 LLM 을 미리 올려 첫 질의가 모델 로드 비용을 내지 않게 합니다.

    2026-08-05 실측에서 콜드 첫 토큰 11.92초, 웜 0.61초였습니다. Phase 7 의
    SSE 첫 토큰 미달(P95 11.06초)은 프리필이 아니라 이 로드 시간이었습니다.

    기동을 막지 않도록 배경 태스크로 돌립니다. 예열이 늦어도 서비스는 정상이며,
    실패해도 첫 질의가 느려질 뿐입니다.
    """
    from src.app.core.config import settings

    if not settings.LLM_WARMUP_ON_STARTUP:
        return
    from src.rag.llm import build_backend

    backend = await asyncio.to_thread(build_backend)
    if backend is None:
        logger.warning("LLM 백엔드가 없어 예열을 건너뜁니다.")
        return
    await asyncio.to_thread(backend.warmup)


@asynccontextmanager
async def lifespan(_: FastAPI):
    task = asyncio.create_task(_warm_llm_backend())
    try:
        yield
    finally:
        task.cancel()


app = FastAPI(
    title="refac_bid_box API",
    description="Refactored Procurement Analytics, Hybrid RAG Chatbot, AI Prediction & MLOps Platform",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DOUBLE_SLASH_PREFIX = "/bids//"


@app.middleware("http")
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


app.mount("/static", StaticFiles(directory=str(APP_DIR / "static")), name="static")

app.include_router(health_router, prefix="/api/v1")
app.include_router(bids_router, prefix="/api/v1")
app.include_router(predictions_router, prefix="/api/v1")
app.include_router(chatbot_router, prefix="/api/v1")
app.include_router(automation_router, prefix="/api/v1")
app.include_router(accounts_router, prefix="/api/v1")

# SSR 화면은 원본 Django 경로를 그대로 사용하므로 prefix 없이 마지막에 포함합니다.
app.include_router(ui_router)

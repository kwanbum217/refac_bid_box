from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from src.app.api.ui import router as ui_router
from src.app.api.v1.accounts import router as accounts_router
from src.app.api.v1.automation import router as automation_router
from src.app.api.v1.bids import router as bids_router
from src.app.api.v1.chatbot import router as chatbot_router
from src.app.api.v1.health import router as health_router
from src.app.api.v1.predictions import router as predictions_router

APP_DIR = Path(__file__).resolve().parent

app = FastAPI(
    title="refac_bid_box API",
    description="Refactored Procurement Analytics, Hybrid RAG Chatbot, AI Prediction & MLOps Platform",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=str(APP_DIR / "static")), name="static")

app.include_router(health_router, prefix="/api/v1")
app.include_router(bids_router, prefix="/api/v1")
app.include_router(predictions_router, prefix="/api/v1")
app.include_router(chatbot_router, prefix="/api/v1")
app.include_router(automation_router, prefix="/api/v1")
app.include_router(accounts_router, prefix="/api/v1")

# SSR 화면은 원본 Django 경로를 그대로 사용하므로 prefix 없이 마지막에 포함합니다.
app.include_router(ui_router)

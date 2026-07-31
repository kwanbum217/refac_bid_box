from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from src.app.api.v1.bids import router as bids_router
from src.app.api.v1.chatbot import router as chatbot_router
from src.app.api.v1.health import router as health_router
from src.app.api.v1.predictions import router as predictions_router

APP_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(APP_DIR / "templates"))

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


@app.get("/")
def root():
    return {
        "message": "Welcome to refac_bid_box API platform",
        "ui": "/ui/",
        "docs": "/docs",
        "health": "/api/v1/health",
    }


@app.get("/ui/")
def ui_dashboard(request: Request):
    return templates.TemplateResponse(
        "dashboard.html",
        {"request": request, "active_tab": "dashboard"},
    )


@app.get("/ui/prediction")
def ui_prediction(request: Request):
    return templates.TemplateResponse(
        "prediction.html",
        {"request": request, "active_tab": "prediction"},
    )


@app.get("/ui/chatbot")
def ui_chatbot(request: Request):
    return templates.TemplateResponse(
        "chatbot.html",
        {"request": request, "active_tab": "chatbot"},
    )

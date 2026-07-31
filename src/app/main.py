from fastapi import FastAPI
from src.app.api.v1.health import router as health_router
from src.app.core.config import settings

app = FastAPI(
    title="refac_bid_box API",
    description="Refactored Procurement Analytics, Hybrid RAG Chatbot, AI Prediction & MLOps Platform",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.include_router(health_router, prefix="/api/v1")


@app.get("/")
def root():
    return {
        "message": "Welcome to refac_bid_box API platform",
        "docs": "/docs",
        "health": "/api/v1/health",
    }

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from src.app.api.v1.bids import router as bids_router
from src.app.api.v1.chatbot import router as chatbot_router
from src.app.api.v1.health import router as health_router
from src.app.api.v1.predictions import router as predictions_router
from src.app.core.config import settings

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

app.include_router(health_router, prefix="/api/v1")
app.include_router(bids_router, prefix="/api/v1")
app.include_router(predictions_router, prefix="/api/v1")
app.include_router(chatbot_router, prefix="/api/v1")




@app.get("/")
def root():
    return {
        "message": "Welcome to refac_bid_box API platform",
        "docs": "/docs",
        "health": "/api/v1/health",
    }

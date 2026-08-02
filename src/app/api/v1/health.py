from fastapi import APIRouter

from src.app.core.config import settings

router = APIRouter(prefix="/health", tags=["Health"])


@router.get("")
def health_check():
    return {
        "status": "healthy",
        "service": "refac_bid_box",
        "environment": settings.ENVIRONMENT,
        "framework": "FastAPI (ASGI)",
        "database": "MySQL 8 (Docker)",
        "task_queue": "Arq (asyncio)",
    }

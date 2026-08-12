import asyncio
import logging
import time
from collections.abc import Callable
from typing import Any

import httpx
from fastapi import APIRouter, Response, status
from sqlalchemy import text

from src.app.core.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/health", tags=["Health"])

CHECK_TIMEOUT_SECONDS = 2.0


def _check_mysql() -> None:
    from src.app.core.db import engine

    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))


def _check_redis() -> None:
    import redis

    client = redis.Redis.from_url(
        settings.REDIS_URL,
        socket_connect_timeout=CHECK_TIMEOUT_SECONDS,
        socket_timeout=CHECK_TIMEOUT_SECONDS,
    )
    try:
        client.ping()
    finally:
        client.close()


def _check_meilisearch() -> None:
    headers = (
        {"Authorization": f"Bearer {settings.MEILI_MASTER_KEY}"}
        if settings.MEILI_MASTER_KEY
        else {}
    )
    response = httpx.get(
        f"{settings.MEILI_URL.rstrip('/')}/health",
        headers=headers,
        timeout=CHECK_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    if response.json().get("status") != "available":
        raise RuntimeError("unexpected_health_status")


def _check_model_registry() -> None:
    from src.ml.model_registry import CATEGORY_DEFAULT_MODELS, ModelRegistry

    unavailable = [
        model_id
        for model_id in set(CATEGORY_DEFAULT_MODELS.values())
        if ModelRegistry.get_model(model_id) is None
    ]
    if unavailable:
        raise RuntimeError("serving_model_unavailable")


def _check_chromadb() -> None:
    import chromadb

    from src.rag.vector_store import DEFAULT_COLLECTION

    client = chromadb.PersistentClient(path=str(settings.CHROMA_DB_PATH))
    collection = client.get_collection(DEFAULT_COLLECTION)
    collection.count()


def _safe_failure_detail(exc: BaseException) -> str:
    classification = "timeout" if isinstance(exc, TimeoutError) else "dependency_check_failed"
    return f"{type(exc).__name__}: {classification}"


async def _run_check(name: str, check: Callable[[], None]) -> tuple[str, dict[str, Any]]:
    started_at = time.perf_counter()
    try:
        await asyncio.wait_for(
            asyncio.to_thread(check),
            timeout=CHECK_TIMEOUT_SECONDS,
        )
    except TimeoutError as exc:
        logger.warning("헬스체크 시간 초과: %s", name)
        result = {"ok": False, "detail": _safe_failure_detail(exc)}
    except Exception as exc:
        logger.exception("헬스체크 실패: %s", name)
        result = {"ok": False, "detail": _safe_failure_detail(exc)}
    else:
        result = {"ok": True, "detail": None}
    result["latency_ms"] = round((time.perf_counter() - started_at) * 1000, 3)
    return name, result


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


@router.get("/live")
async def liveness_check():
    return {"status": "alive"}


@router.get("/ready")
async def readiness_check(response: Response):
    checks = dict(
        await asyncio.gather(
            _run_check("mysql", _check_mysql),
            _run_check("redis", _check_redis),
            _run_check("meilisearch", _check_meilisearch),
            _run_check("model_registry", _check_model_registry),
            _run_check("chromadb", _check_chromadb),
        )
    )

    if not all(checks[name]["ok"] for name in ("mysql", "redis", "model_registry")):
        readiness_status = "not_ready"
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    elif not all(check["ok"] for check in checks.values()):
        readiness_status = "degraded"
    else:
        readiness_status = "ready"

    return {"status": readiness_status, "checks": checks}

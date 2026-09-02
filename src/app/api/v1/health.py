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


class WarmupState:
    """애플리케이션 기동 시점의 백그라운드 예열(warmup) 진행 및 완료 상태를 추적합니다."""

    def __init__(self) -> None:
        self._started: bool = False
        self._llm: bool = True
        self._predictor: bool = True
        self._vector: bool = True
        self._llm_error: str | None = None
        self._predictor_error: str | None = None
        self._vector_error: str | None = None

    def start(self) -> None:
        self._started = True
        self._llm = False
        self._predictor = False
        self._vector = False
        self._llm_error = None
        self._predictor_error = None
        self._vector_error = None

    def reset(self) -> None:
        self._started = False
        self._llm = True
        self._predictor = True
        self._vector = True
        self._llm_error = None
        self._predictor_error = None
        self._vector_error = None

    def mark_llm_done(
        self, success: bool = True, skipped: bool = False, error: str | None = None
    ) -> None:
        self._llm = success or skipped
        self._llm_error = error

    def mark_predictor_done(
        self, success: bool = True, skipped: bool = False, error: str | None = None
    ) -> None:
        self._predictor = success or skipped
        self._predictor_error = error

    def mark_vector_done(
        self, success: bool = True, skipped: bool = False, error: str | None = None
    ) -> None:
        self._vector = success or skipped
        self._vector_error = error

    @property
    def is_started(self) -> bool:
        return self._started

    @property
    def completed(self) -> bool:
        if not self._started:
            return True
        return self._llm and self._predictor and self._vector

    def get_summary(self) -> dict[str, Any]:
        return {
            "completed": self.completed,
            "started": self._started,
            "details": {
                "llm": {"ok": self._llm, "error": self._llm_error},
                "predictor": {"ok": self._predictor, "error": self._predictor_error},
                "vector_search": {"ok": self._vector, "error": self._vector_error},
            },
        }


warmup_state = WarmupState()


def _check_llm() -> dict[str, Any]:
    started_at = time.perf_counter()
    try:
        from src.rag.llm import build_backend

        backend = build_backend()
        if backend is None:
            return {
                "ok": False,
                "provider": getattr(settings, "LLM_PROVIDER", "unknown"),
                "detail": "llm_backend_unavailable",
                "latency_ms": round((time.perf_counter() - started_at) * 1000, 3),
            }
        available = backend.available()
        return {
            "ok": bool(available),
            "provider": getattr(backend, "name", settings.LLM_PROVIDER),
            "detail": None if available else "llm_service_unavailable",
            "latency_ms": round((time.perf_counter() - started_at) * 1000, 3),
        }
    except Exception as exc:
        return {
            "ok": False,
            "provider": getattr(settings, "LLM_PROVIDER", "unknown"),
            "detail": f"{type(exc).__name__}: {exc}",
            "latency_ms": round((time.perf_counter() - started_at) * 1000, 3),
        }


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


@router.get("/served-version", summary="실제 서빙 모델 버전 조회")
def served_version_check():
    """인메모리 모델과 디스크 승격본의 버전 상태를 조회합니다."""
    from src.ml.model_registry import ModelRegistry

    models = ModelRegistry.list_served_versions()
    mismatches = [model for model in models if model["status"] == "mismatch"]
    return {
        "status": "mismatch" if mismatches else "ok",
        "models": models,
        "mismatches": mismatches,
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

    llm_status = await asyncio.to_thread(_check_llm)
    warmup_status = warmup_state.get_summary()

    critical_checks = {"mysql", "redis", "model_registry"}
    if settings.READINESS_REQUIRE_WARMUP:
        critical_checks.add("warmup")
    if settings.READINESS_REQUIRE_LLM:
        critical_checks.add("llm")

    critical_failed = False
    for name in ("mysql", "redis", "model_registry"):
        if not checks[name]["ok"]:
            critical_failed = True
            break
    if "warmup" in critical_checks and not warmup_status["completed"]:
        critical_failed = True
    if "llm" in critical_checks and not llm_status["ok"]:
        critical_failed = True

    if critical_failed:
        readiness_status = "not_ready"
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    elif (
        not all(check["ok"] for check in checks.values())
        or not warmup_status["completed"]
        or not llm_status["ok"]
    ):
        readiness_status = "degraded"
    else:
        readiness_status = "ready"

    return {
        "status": readiness_status,
        "checks": checks,
        "warmup": warmup_status,
        "llm": llm_status,
    }

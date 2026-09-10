"""src/app/core/latency_segments.py

compare-stats 경로 전용 구간 계측 레코더입니다.

RAG 경로의 정본(src/rag/structured_data.py)이 쓰는 3단 구조(레코더, 로그 줄,
하네스 파싱)를 compare-stats 경로에 그대로 본뜬 것이며, RAG 기준선을 오염
시키지 않기 위해 파일을 공유하지 않고 별도로 둡니다. 중복은 의도된 것입니다.

동작 계약은 다음과 같습니다.
1. settings.LATENCY_SEGMENT_LOGGING 이 꺼져 있으면 모든 함수는 무동작이며
   로그 줄도 남기지 않습니다.
2. 켜져 있으면 요청별로 contextvars 레코더를 열고 명명 구간과 SQLAlchemy
   커서 실행 시간(cursor_ms, cursor_count)을 모읍니다.
3. 내부 예외는 요청 처리를 실패시키지 않고 경고만 남긴 뒤 삼킵니다.
"""

from __future__ import annotations

import contextvars
import json
import logging
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import event
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)

COMPARE_STATS_SEGMENT_NAMES: tuple[str, ...] = (
    "announcement_summary",
    "result_summary",
    "cache_lookup",
    "matched_count",
    "announce_by_month",
    "result_by_month",
    "agency_announce_top10",
    "cache_store",
    "result_assembly",
)

LOG_MARKER = "compare_stats_segments="

_compare_stats_record: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "compare_stats_latency_record", default=None
)
_listener_lock = threading.Lock()
_listeners_registered = False


def _latency_enabled() -> bool:
    try:
        from src.app.core.config import settings

        return bool(getattr(settings, "LATENCY_SEGMENT_LOGGING", False))
    except Exception:
        return False


def _before_cursor_execute(conn, cursor, statement, parameters, context, executemany) -> None:
    try:
        record = _compare_stats_record.get()
        if record is not None and record.get("active"):
            record.setdefault("cursor_starts", []).append(time.perf_counter())
    except Exception:
        return


def _after_cursor_execute(conn, cursor, statement, parameters, context, executemany) -> None:
    try:
        record = _compare_stats_record.get()
        if record is None or not record.get("active"):
            return
        starts = record.get("cursor_starts", [])
        if not starts:
            return
        elapsed_ms = max(0.0, (time.perf_counter() - starts.pop()) * 1000.0)
        record["cursor_ms"] = record.get("cursor_ms", 0.0) + elapsed_ms
        record["cursor_count"] = record.get("cursor_count", 0) + 1
    except Exception:
        return


def _register_cursor_listeners() -> None:
    global _listeners_registered
    if not _latency_enabled() or _listeners_registered:
        return
    with _listener_lock:
        if _listeners_registered or not _latency_enabled():
            return
        try:
            if not event.contains(Engine, "before_cursor_execute", _before_cursor_execute):
                event.listen(Engine, "before_cursor_execute", _before_cursor_execute)
            if not event.contains(Engine, "after_cursor_execute", _after_cursor_execute):
                event.listen(Engine, "after_cursor_execute", _after_cursor_execute)
            _listeners_registered = True
        except Exception as exc:
            logger.warning("비교 통계 SQL 계측 리스너 등록 중 예외 발생 (무시됨): %s", exc)


def open_compare_stats_record() -> dict[str, Any] | None:
    """현재 요청의 계측 레코더를 엽니다. 계측이 꺼져 있으면 None 을 돌려줍니다."""
    if not _latency_enabled():
        return None
    _register_cursor_listeners()
    record: dict[str, Any] = {
        "active": True,
        "started_at": time.perf_counter(),
        "cursor_ms": 0.0,
        "cursor_count": 0,
        "cursor_starts": [],
        "segments": dict.fromkeys(COMPARE_STATS_SEGMENT_NAMES, 0.0),
    }
    _compare_stats_record.set(record)
    return record


def close_compare_stats_record(record: dict[str, Any] | None) -> None:
    """레코더를 닫고 총 시간과 잔여 시간을 확정합니다. 예외는 삼킵니다."""
    if record is None:
        return
    try:
        record["active"] = False
        total_ms = max(0.0, (time.perf_counter() - record["started_at"]) * 1000.0)
        cursor_ms = float(record.get("cursor_ms", 0.0))
        record["total_ms"] = total_ms
        record["residual_ms"] = max(0.0, total_ms - cursor_ms)
        record.pop("cursor_starts", None)
    except Exception as exc:
        logger.warning("비교 통계 계측 종료 중 예외 발생 (무시됨): %s", exc)


def _record_segment(label: str, elapsed_ms: float) -> None:
    try:
        record = _compare_stats_record.get()
        if record is not None and record.get("active"):
            segments = record.setdefault("segments", {})
            segments[label] = round(float(segments.get(label, 0.0)) + elapsed_ms, 2)
    except Exception:
        return


@contextmanager
def compare_stats_segment(label: str) -> Iterator[None]:
    """명명 구간 하나를 계측합니다. 계측이 꺼져 있으면 시간만 재지 않고 통과합니다."""
    if not _latency_enabled():
        yield
        return
    try:
        record = _compare_stats_record.get()
    except Exception:
        yield
        return
    if record is None or not record.get("active"):
        yield
        return
    started = time.perf_counter()
    try:
        yield
    finally:
        try:
            _record_segment(label, (time.perf_counter() - started) * 1000.0)
        except Exception:
            return


def get_compare_stats_segments() -> dict[str, Any] | None:
    """닫힌 레코더의 계측 결과를 호출자에게 안전하게 제공합니다.

    닫히지 않은 레코더나 계측이 꺼진 상태에서는 None 을 돌려줍니다.
    지정된 아홉 구간 이름은 관측되지 않았어도 0.0 으로 채워 돌려줍니다.
    """
    if not _latency_enabled():
        return None
    try:
        record = _compare_stats_record.get()
        if record is None or record.get("active"):
            return None
        raw_segments = record.get("segments", {})
        segments = {
            name: round(float(raw_segments.get(name, 0.0)), 2)
            for name in COMPARE_STATS_SEGMENT_NAMES
        }
        return {
            "segments": segments,
            "cursor_ms": round(float(record.get("cursor_ms", 0.0)), 2),
            "cursor_count": int(record.get("cursor_count", 0)),
            "total_ms": round(float(record.get("total_ms", 0.0)), 2),
            "residual_ms": round(float(record.get("residual_ms", 0.0)), 2),
        }
    except Exception as exc:
        logger.warning("비교 통계 계측 결과 읽기 중 예외 발생 (무시됨): %s", exc)
        return None


def build_compare_stats_payload(cache_hit: bool) -> dict[str, Any] | None:
    """로그 한 줄에 실을 JSON 페이로드를 만듭니다. 계측이 꺼져 있으면 None 입니다."""
    if not _latency_enabled():
        return None
    try:
        snapshot = get_compare_stats_segments()
        if snapshot is None:
            return None
        return {"cache_hit": bool(cache_hit), **snapshot}
    except Exception as exc:
        logger.warning("비교 통계 페이로드 구성 중 예외 발생 (무시됨): %s", exc)
        return None


def log_compare_stats_segments(target_logger: logging.Logger, cache_hit: bool) -> None:
    """compare_stats_segments=<JSON> 한 줄을 남깁니다. 예외는 삼킵니다."""
    if not _latency_enabled():
        return
    try:
        payload = build_compare_stats_payload(cache_hit)
        if payload is None:
            return
        target_logger.info(
            "%s%s",
            LOG_MARKER,
            json.dumps(payload, ensure_ascii=False, sort_keys=True),
        )
    except Exception as exc:
        logger.warning("비교 통계 구간 로깅 중 예외 발생 (무시됨): %s", exc)


__all__ = [
    "COMPARE_STATS_SEGMENT_NAMES",
    "LOG_MARKER",
    "build_compare_stats_payload",
    "close_compare_stats_record",
    "compare_stats_segment",
    "get_compare_stats_segments",
    "log_compare_stats_segments",
    "open_compare_stats_record",
]

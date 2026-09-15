"""
src/rag/structured_data.py

RAG 정형 검색 (원본 rag_engine.retrieve_structured_data / _apply_*_filters SQLAlchemy 이식).
필터 규칙, 집계 항목, 시계열 버킷 산출을 원본과 동일하게 유지합니다.
"""

from __future__ import annotations

import contextvars
import hashlib
import logging
import re
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import event, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from src.app.core.cache import cache
from src.app.core.config import settings
from src.app.models.bids import (
    CATEGORY_LABELS,
    CORRUPTED_TEXT_FALLBACKS,
    BidAnnouncement,
    BidResult,
    clean_display_text,
    is_corrupted_display_text,
)
from src.app.services.ranking_snapshots import (
    DATASET_ANNOUNCEMENT,
    DATASET_RESULT,
    REPLACEMENT_CHAR,
    exclude_corrupted,
    get_skipped_count,
    get_skipped_marker,
    get_top_rankings,
)
from src.rag.schemas import RetrievalPlan

logger = logging.getLogger(__name__)

_latency_record: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "structured_latency_record", default=None
)
_listener_lock = threading.Lock()
_listeners_registered = False
# 병렬 집계 스레드가 같은 계측 기록을 함께 고칩니다.
_record_lock = threading.Lock()
# 병렬 집계가 쓸 구간 라벨을 호출 순서대로 미리 정해 둡니다. 완료 순서로 번호를 매기면 회차마다 뜻이 바뀝니다.
_reserved_segment_label: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "structured_reserved_segment_label", default=None
)


def _latency_enabled() -> bool:
    try:
        return bool(getattr(settings, "LATENCY_SEGMENT_LOGGING", False))
    except Exception:
        return False


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
            logger.warning("정형 검색 SQL 계측 리스너 등록 중 예외 발생 (무시됨): %s", exc)


def _before_cursor_execute(conn, cursor, statement, parameters, context, executemany) -> None:
    try:
        record = _latency_record.get()
        if record is not None and record.get("active"):
            with _record_lock:
                starts = record.setdefault("cursor_starts", {})
                starts.setdefault(threading.get_ident(), []).append(time.perf_counter())
    except Exception:
        return


def _after_cursor_execute(conn, cursor, statement, parameters, context, executemany) -> None:
    try:
        record = _latency_record.get()
        if record is None or not record.get("active"):
            return
        with _record_lock:
            starts = record.get("cursor_starts", {}).get(threading.get_ident())
            if not starts:
                return
            elapsed_ms = max(0.0, (time.perf_counter() - starts.pop()) * 1000.0)
            record["cursor_ms"] = record.get("cursor_ms", 0.0) + elapsed_ms
            record["cursor_count"] = record.get("cursor_count", 0) + 1
    except Exception:
        return


def _open_latency_record() -> dict[str, Any] | None:
    if not _latency_enabled():
        return None
    _register_cursor_listeners()
    record: dict[str, Any] = {
        "active": True,
        "started_at": time.perf_counter(),
        "cursor_ms": 0.0,
        "cursor_count": 0,
        "cursor_starts": {},
        "segments": {},
        "counters": {},
    }
    _latency_record.set(record)
    return record


def _close_latency_record(record: dict[str, Any] | None) -> None:
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
        logger.warning("정형 검색 SQL 계측 종료 중 예외 발생 (무시됨): %s", exc)


def get_structured_latency_segments() -> dict[str, Any] | None:
    """현재 context의 정형 검색 계측 결과를 호출자에게 안전하게 제공합니다."""
    if not _latency_enabled():
        return None
    try:
        record = _latency_record.get()
        if record is None or record.get("active"):
            return None
        return {
            "segments": dict(record.get("segments", {})),
            "cursor_ms": round(float(record.get("cursor_ms", 0.0)), 2),
            "cursor_count": int(record.get("cursor_count", 0)),
            "total_ms": round(float(record.get("total_ms", 0.0)), 2),
            "residual_ms": round(float(record.get("residual_ms", 0.0)), 2),
        }
    except Exception as exc:
        logger.warning("정형 검색 SQL 계측 결과 읽기 중 예외 발생 (무시됨): %s", exc)
        return None


def _record_segment(label: str, elapsed_ms: float) -> None:
    try:
        record = _latency_record.get()
        if record is not None and record.get("active"):
            with _record_lock:
                segments = record.setdefault("segments", {})
                segments[label] = round(float(segments.get(label, 0.0)) + elapsed_ms, 2)
    except Exception:
        return


def _next_segment_label(prefix: str) -> str:
    record = _latency_record.get()
    if record is None or not record.get("active"):
        return prefix
    with _record_lock:
        counters = record.setdefault("counters", {})
        index = int(counters.get(prefix, 0)) + 1
        counters[prefix] = index
    return f"{prefix}_{index}"


def _measure_call(prefix: str):
    def decorator(func):
        def measured(*args, **kwargs):
            reserved = _reserved_segment_label.get()
            token = _reserved_segment_label.set(None)
            started = time.perf_counter()
            try:
                return func(*args, **kwargs)
            finally:
                _reserved_segment_label.reset(token)
                _record_segment(
                    reserved or _next_segment_label(prefix),
                    (time.perf_counter() - started) * 1000.0,
                )

        measured.__name__ = func.__name__
        measured.__doc__ = func.__doc__
        return measured

    return decorator


def _timed_cache_get(key: str) -> Any:
    started = time.perf_counter()
    try:
        return cache.get(key)
    finally:
        _record_segment("cache_lookup_ms", (time.perf_counter() - started) * 1000.0)


def _normalize_text(value: str | None) -> str:
    return unicodedata.normalize("NFC", (value or "").strip())


# MySQL ngram 파서 기본 토큰 크기(ngram_token_size=2) 및 FULLTEXT boolean 모드 특수문자 정의
# 1. 2글자 미만: 2-gram 토큰이 생성되지 않아 MATCH AGAINST가 0건을 반환 (조용한 누락 발생)
# 2. LIKE 와일드카드(%, _): 패턴 매칭 문자로 ngram 역색인 검색 범위와 불일치 발생
# 3. FULLTEXT boolean 연산자(+, -, *, >, <, (, ), ~, @): 구문 제어 연산자로 오작동 방지
# 4. 따옴표('", `) 및 역슬래시(\): SQL 리터럴 파싱 및 구문 검색(phrase query) 왜곡 방지
# 픽스처(tests/fixtures/ngram_edge_keywords.json)와의 정합성:
# - 픽스처에서는 구문 검색 래핑(+'"kw"') 전제로 edge_04(parentheses), edge_05(hyphen),
#   edge_07(alphanumeric_mixed), edge_09(like_wildcard_percent), edge_10(like_wildcard_underscore),
#   edge_11(single_quote), edge_12(boolean_operators)가 is_safe_for_ngram=True 로 기록되어 있습니다.
# - 그러나 실제 운영 코드에서는 와일드카드 매칭 범위 불일치(100% 등), boolean 연산자 충돌(-, + 등),
#   따옴표 파싱 리스크를 원천 차단하기 위해 픽스처보다 보수적으로 이들 문자가 포함된 키워드를
#   안전하지 않음(False)으로 판정하여 기존 LIKE 단독 경로로 폴백합니다.
# - 따라서 코드의 안전 판정 집합은 픽스처의 안전 집합(True)의 진부분집합(strict subset)을 형성합니다.
UNSAFE_NGRAM_CHARS = frozenset("%_+-*><()~@'\"`\\")


def is_safe_for_ngram_prefilter(keyword: str | None) -> bool:
    """키워드가 MySQL ngram FULLTEXT 선행필터(MATCH AGAINST)에 안전한지 판정합니다.

    다음 조건 중 하나라도 해당하면 안전하지 않음(False)으로 판정하여 기존 LIKE 단독 경로로 폴백합니다:
    1. 정규화(NFC) 후 길이가 2글자 미만인 경우 (1글자 한글 등 ngram_token_size=2 에서 누락 발생)
    2. LIKE 와일드카드(%, _) 또는 따옴표('", `)가 포함된 경우
    3. FULLTEXT boolean 모드 연산자(+, -, *, >, <, (, ), ~, @) 및 특수 제어 문자가 포함된 경우
    """
    if not keyword:
        return False
    normalized = _normalize_text(keyword)
    if len(normalized) < 2:
        return False
    return not any(char in UNSAFE_NGRAM_CHARS for char in normalized)


def _build_boolean_ft_query(keyword: str) -> str:
    """MySQL BOOLEAN MODE 구문 검색 문자열(+'"kw"')을 생성합니다."""
    return f'+"{keyword}"'


def _category_label(category: str | None) -> str:
    category_code = _normalize_text(str(category or ""))
    return CATEGORY_LABELS.get(category_code, category_code or "-")


class InvalidDateFilterError(ValueError):
    """날짜 필터를 해석하지 못했음을 알립니다.

    종전에는 None 을 돌려줘 필터가 통째로 빠졌고, 사용자는 전체 기간 통계를
    자기가 지정한 기간의 답으로 읽었습니다. 값이 없는 것과 해석하지 못한
    것은 다릅니다.
    """

    def __init__(self, field: str, value: object) -> None:
        self.field = field
        self.value = value
        super().__init__(f"{field} 날짜 형식을 해석하지 못했습니다: {value}")


def _parse_date(value: str | date | datetime | None, field: str = "date") -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError as exc:
        raise InvalidDateFilterError(field, value) from exc
    return parsed.replace(tzinfo=None)


def _resolve_window(filters: dict[str, Any]) -> tuple[datetime | None, datetime | None]:
    date_from = _parse_date(filters.get("date_from"), "date_from")
    date_to = _parse_date(filters.get("date_to"), "date_to")
    relative_years = int(filters.get("relative_years") or 0)

    if relative_years and not date_from:
        today = date.today()
        date_from = _parse_date((today - timedelta(days=(365 * relative_years) - 1)).isoformat())
        date_to = date_to or _parse_date(today.isoformat())
    return date_from, date_to


def _institution_condition(column, institution_name: str, institution_names: list[str] | None):
    """해석된 기관명 목록이 있으면 등호 조회로, 없으면 부분 일치로 거릅니다."""
    if institution_names is not None:
        return column.in_(institution_names)
    return column.contains(institution_name)


def _result_conditions(
    plan: RetrievalPlan,
    *,
    enable_ngram_prefilter: bool = False,
    institution_names: list[str] | None = None,
) -> list:
    filters = plan.filters or {}
    date_from, date_to = _resolve_window(filters)
    institution_name = _normalize_text(str(filters.get("institution_name") or ""))
    category = _normalize_text(str(filters.get("category") or ""))

    conditions = []
    if (
        enable_ngram_prefilter
        and settings.NGRAM_PREFILTER_ENABLED
        and is_safe_for_ngram_prefilter(institution_name)
    ):
        conditions.append(BidResult.dminstt_nm.match(_build_boolean_ft_query(institution_name)))
    if date_from:
        conditions.append(BidResult.rl_openg_dt >= date_from)
    if date_to:
        conditions.append(BidResult.rl_openg_dt <= date_to + timedelta(days=1))
    if institution_name:
        conditions.append(
            _institution_condition(BidResult.dminstt_nm, institution_name, institution_names)
        )
    if category:
        conditions.append(BidResult.category == category)
    return conditions


def _announcement_conditions(
    plan: RetrievalPlan,
    *,
    enable_ngram_prefilter: bool = False,
    institution_names: list[str] | None = None,
) -> list:
    filters = plan.filters or {}
    date_from, date_to = _resolve_window(filters)
    institution_name = _normalize_text(str(filters.get("institution_name") or ""))
    category = _normalize_text(str(filters.get("category") or ""))

    conditions = []
    if (
        enable_ngram_prefilter
        and settings.NGRAM_PREFILTER_ENABLED
        and is_safe_for_ngram_prefilter(institution_name)
    ):
        conditions.append(
            BidAnnouncement.dminstt_nm.match(_build_boolean_ft_query(institution_name))
        )
    if date_from:
        conditions.append(BidAnnouncement.bid_ntce_dt >= date_from)
    if date_to:
        conditions.append(BidAnnouncement.bid_ntce_dt <= date_to + timedelta(days=1))
    if institution_name:
        conditions.append(
            _institution_condition(BidAnnouncement.dminstt_nm, institution_name, institution_names)
        )
    if category:
        conditions.append(BidAnnouncement.category == category)
    return conditions


def _resolve_time_series_granularity(plan: RetrievalPlan) -> str:
    date_from, date_to = _resolve_window(plan.filters or {})
    if date_from and date_to and (date_to.date() - date_from.date()).days <= 45:
        return "day"
    return "month"


def _time_series_bucket_key(opened_at: datetime, granularity: str) -> str:
    if granularity == "day":
        return opened_at.strftime("%Y-%m-%d")
    return opened_at.strftime("%Y-%m")


def _snapshot_scope(plan: RetrievalPlan) -> str | None:
    """사전 집계 스냅샷을 쓸 수 있는 질의인지 판정합니다.

    스냅샷은 category 조합만 미리 계산해 둡니다. 날짜나 기관명이 걸리면 조합이
    사실상 무한하므로 실시간 집계로 넘깁니다. 반환값은 category 코드이며,
    필터가 전혀 없으면 빈 문자열(전체)입니다.
    """
    filters = plan.filters or {}
    date_from, date_to = _resolve_window(filters)
    if date_from or date_to:
        return None
    if _normalize_text(str(filters.get("institution_name") or "")):
        return None
    return _normalize_text(str(filters.get("category") or ""))


def _result_limit(plan: RetrievalPlan) -> int:
    raw_limit = (plan.filters or {}).get("result_limit")
    if raw_limit in (None, ""):
        return 0
    try:
        return min(max(int(raw_limit), 1), 20)
    except (TypeError, ValueError):
        return 0


# 낙찰업체 집계는 날짜만 걸리고 category 가 없을 때 옵티마이저가 그룹 인덱스
# (ix_bid_results_bidwinnr_nm)를 골라 인덱스 전체를 훑습니다(filtered 15.29%).
# EXPLAIN rows 추정은 약 3.27M 이고 bid_results 의 실제 행 수는 3,423,008 입니다.
# 추정치를 실측처럼 읽으면 다음 최적화 판단이 다시 어긋납니다(2026-08-30 실측,
# docs/analysis/task_f3_ngram_fulltext_probe.md 2.1 절).
# 버퍼 풀이 식어 있으면 이 스캔이 최대 97초를 씁니다(2026-08-30 실측).
# 날짜 인덱스를 강제하면 범위 스캔으로 좁혀져 13,412ms 가 714ms 로 떨어집니다.
# category 가 함께 걸리면 옵티마이저가 ix_bid_results_cat_dt_stats 로 182,902행까지
# 이미 좁히므로 그때는 힌트를 주지 않습니다.
RESULT_DATE_INDEX_HINT = "FORCE INDEX (ix_bid_results_dt_cat)"
ANNOUNCEMENT_DATE_INDEX_HINT = "FORCE INDEX (ix_bid_ann_dt_cat)"


def _needs_result_date_index_hint(plan: RetrievalPlan) -> bool:
    """날짜 범위는 있고 category 가 없는 낙찰 집계인지 판정합니다."""
    filters = plan.filters or {}
    date_from, date_to = _resolve_window(filters)
    if not (date_from or date_to):
        return False
    return not _normalize_text(str(filters.get("category") or ""))


def _hint_result_date_index(stmt, plan: RetrievalPlan):
    """조건이 맞을 때만 날짜 인덱스 힌트를 붙입니다. 결과 집합은 바뀌지 않습니다."""
    if not _needs_result_date_index_hint(plan):
        return stmt
    return stmt.with_hint(BidResult, RESULT_DATE_INDEX_HINT, dialect_name="mysql")


# 날짜 범위 없이 기관명 부분 일치만 걸려도 옵티마이저가 같은 그룹 인덱스를 골라 339만 항목을
# 훑으며 기관명 확인을 위해 행마다 본문을 읽습니다. "서울" 낙찰업체 집계가 완전 콜드에서
# 7,159~13,218ms 였고, 이 인덱스만 막으면 테이블 순차 스캔으로 1,258~1,470ms 였습니다
# (2026-09-13 실측, 결과 동일, docs/analysis/rag_coldsql_root_cause_20260913.md 10장).
# 날짜 범위가 있으면 위 날짜 인덱스 강제가 더 좁히므로 이 힌트를 붙이지 않습니다.
RESULT_WINNER_GROUP_INDEX_IGNORE_HINT = "IGNORE INDEX (ix_bid_results_bidwinnr_nm)"


def _needs_result_winner_group_index_ignore(plan: RetrievalPlan) -> bool:
    """기관명 조건은 있고 날짜 범위가 없는 낙찰업체 집계인지 판정합니다."""
    filters = plan.filters or {}
    if not _normalize_text(str(filters.get("institution_name") or "")):
        return False
    date_from, date_to = _resolve_window(filters)
    return not (date_from or date_to)


def _hint_result_winner_group_index(stmt, plan: RetrievalPlan):
    """조건이 맞을 때만 낙찰업체 그룹 인덱스를 배제합니다. 결과 집합은 바뀌지 않습니다."""
    if not _needs_result_winner_group_index_ignore(plan):
        return stmt
    return stmt.with_hint(BidResult, RESULT_WINNER_GROUP_INDEX_IGNORE_HINT, dialect_name="mysql")


# 공고 쪽(ANNOUNCEMENT_INSTITUTION_COVER_HINT)과 같은 판단 착오가 낙찰 테이블에도 있습니다. 기관명이 부분 일치로
# 되돌아가고 category 가 붙으면 옵티마이저가 category 인덱스 조회를 커버링 인덱스보다 싸다고 골라 행마다 본문을
# 읽습니다. category 가 없으면 옵티마이저가 커버링 인덱스를 스스로 고르므로 붙이지 않습니다
# (2026-09-13 EXPLAIN, docs/analysis/rag_coldsql_root_cause_20260913.md 14장).
RESULT_INSTITUTION_COVER_HINT = "FORCE INDEX (ix_bid_results_inst_cat_stats)"


def _needs_result_institution_cover_hint(
    plan: RetrievalPlan, institution_names: list[str] | None
) -> bool:
    """부분 일치로 되돌아간 기관명과 category 가 함께 걸리고 날짜 범위가 없는 낙찰 집계인지 판정합니다."""
    filters = plan.filters or {}
    if institution_names is not None:
        return False
    if not _normalize_text(str(filters.get("institution_name") or "")):
        return False
    if not _normalize_text(str(filters.get("category") or "")):
        return False
    date_from, date_to = _resolve_window(filters)
    return not (date_from or date_to)


def _hint_result_institution_cover(stmt, plan: RetrievalPlan, institution_names: list[str] | None):
    """조건이 맞을 때만 낙찰 기관명 커버링 인덱스를 강제합니다. 결과 집합은 바뀌지 않습니다."""
    if not _needs_result_institution_cover_hint(plan, institution_names):
        return stmt
    return stmt.with_hint(BidResult, RESULT_INSTITUTION_COVER_HINT, dialect_name="mysql")


def _needs_announcement_date_index_hint(plan: RetrievalPlan) -> bool:
    """날짜 범위는 있고 category 가 없는 공고 집계인지 판정합니다."""
    filters = plan.filters or {}
    date_from, date_to = _resolve_window(filters)
    if not (date_from or date_to):
        return False
    return not _normalize_text(str(filters.get("category") or ""))


def _hint_announcement_date_index(stmt, plan: RetrievalPlan):
    """조건이 맞을 때만 공고 날짜 인덱스 힌트를 붙입니다. 결과 집합은 바뀌지 않습니다."""
    if not _needs_announcement_date_index_hint(plan):
        return stmt
    return stmt.with_hint(BidAnnouncement, ANNOUNCEMENT_DATE_INDEX_HINT, dialect_name="mysql")


# 기관명이 상한을 넘어 부분 일치로 되돌아가고 category 가 붙으면, 옵티마이저가 행 수만 보고
# category 인덱스 조회(추정 비용 67만)를 커버링 인덱스 스캔(700만)보다 싸다고 판단합니다. 실제로는
# Servc 공고 211만 행 본문을 31.6GB 테이블에서 흩어 읽습니다. "광주"+Servc 완전 콜드에서 COUNT 가
# 16,086~50,236ms, 기관별 집계가 16,069~16,911ms 였고 커버링 인덱스를 강제하면 1,136~1,589ms,
# 1,296~1,567ms 였습니다(2026-09-13 실측, 결과 동일, docs/analysis/rag_coldsql_root_cause_20260913.md 13장).
# category 가 없으면 옵티마이저가 이미 기관명 인덱스를 고르고, 날짜 범위가 있으면 위 날짜 인덱스
# 강제가 적용되므로 붙이지 않습니다. 이름 목록으로 해석된 경우(IN)도 붙이지 않습니다.
ANNOUNCEMENT_INSTITUTION_COVER_HINT = "FORCE INDEX (ix_bid_ann_inst_cat_ntce)"


def _needs_announcement_institution_cover_hint(
    plan: RetrievalPlan, institution_names: list[str] | None
) -> bool:
    """부분 일치로 되돌아간 기관명과 category 가 함께 걸리고 날짜 범위가 없는지 판정합니다."""
    filters = plan.filters or {}
    if institution_names is not None:
        return False
    if not _normalize_text(str(filters.get("institution_name") or "")):
        return False
    if not _normalize_text(str(filters.get("category") or "")):
        return False
    date_from, date_to = _resolve_window(filters)
    return not (date_from or date_to)


def _hint_announcement_institution_cover(
    stmt, plan: RetrievalPlan, institution_names: list[str] | None
):
    """조건이 맞을 때만 공고 기관명 커버링 인덱스를 강제합니다. 결과 집합은 바뀌지 않습니다."""
    if not _needs_announcement_institution_cover_hint(plan, institution_names):
        return stmt
    return stmt.with_hint(
        BidAnnouncement, ANNOUNCEMENT_INSTITUTION_COVER_HINT, dialect_name="mysql"
    )


def _result_availability_conditions(
    plan: RetrievalPlan, *, institution_names: list[str] | None = None
) -> list:
    """날짜 필터를 제외한 결과 보유 범위 확인 조건을 만듭니다."""
    filters = plan.filters or {}
    institution_name = _normalize_text(str(filters.get("institution_name") or ""))
    category = _normalize_text(str(filters.get("category") or ""))
    conditions = []
    if institution_name:
        conditions.append(
            _institution_condition(BidResult.dminstt_nm, institution_name, institution_names)
        )
    if category:
        conditions.append(BidResult.category == category)
    return conditions


# 기관명 부분 일치는 선행 와일드카드라 날짜 범위가 없으면 후보 행 본문을 전부 읽습니다.
# bid_announcements 데이터 31.6GB 가 버퍼풀 2GB 밖에 있어 콜드에서 문장당 16~28초가
# 걸렸고, 인덱스 힌트로는 줄지 않았습니다. 기관명 인덱스(359MB)만 훑어 정확한 이름을
# 먼저 구한 뒤 등호로 조회하면 같은 문장이 콜드 4.5~4.9초였습니다(2026-09-13 실측,
# docs/analysis/rag_coldsql_root_cause_20260913.md). 이름이 너무 많으면 IN 목록이
# 과대해지므로 상한을 넘을 때는 종전 부분 일치로 돌아갑니다.
INSTITUTION_NAME_RESOLVE_LIMIT = 1000

# 상한 초과 판정은 오래 둡니다. 기관명 집합은 수집으로 늘기만 하므로 한 번 넘은 검색어가 다시
# 상한 안으로 들어오지 않고, 넘은 경우의 되돌림은 항상 완전한 부분 일치입니다. "서울"은 요청마다
# 1,369ms 해석 질의를 돌린 뒤 결과를 버렸습니다(2026-09-13). 이름 목록은 새 기관을 놓치지 않도록
# 집계와 같은 1시간을 유지합니다(최근 7일 신규 기관명 낙찰 63, 공고 68).
INSTITUTION_OVERFLOW_CACHE_TTL = 7 * 24 * 60 * 60

# 해석 질의 결과가 빈 이름 목록일 때의 유효 시간 (300초).
# 새 기관이 들어온 뒤 빈 결과가 1시간 남는 결함을 막기 위해 짧게 캐시합니다.
INSTITUTION_EMPTY_RESOLVE_CACHE_TTL = 300

# 해석 질의도 상한 안의 검색어는 기관명 인덱스(공고 359MB)를 끝까지 훑습니다. "광주"가 콜드에서
# 4.6~12.9초, 웜에서 0.7초였습니다. 고유 기관명은 공고 43,755종, 낙찰 50,854종으로 합쳐도 약 2MB 라
# 목록째 캐시하고 파이썬에서 고릅니다(2026-09-13 실측). 목록 조회는 skip scan 이라 웜 175ms 입니다.
# 파이썬 부분 일치가 utf8mb4_unicode_ci LIKE 와 같은 것은 한글 음절만으로 된 검색어뿐입니다. 전각 괄호,
# 전각 숫자, 악센트 문자는 MySQL 이 같은 글자로 보므로 괄호·영문·숫자·공백이 섞이면 해석 질의로 갑니다.
_CATALOG_TERM = re.compile(r"[가-힣]+")
# 무시 가능 문자가 이름 안에 끼면 LIKE 결과를 파이썬에서 확정할 수 없습니다.
_CATALOG_UNCERTAIN_CHARS = re.compile(
    "[\x00-\x1f\x7f-\x9f\u00ad\u200b-\u200f\u202a-\u202e\u2060-\u206f\ufeff\ufff9-\ufffb]"
)


def _catalog_eligible(institution_name: str) -> bool:
    return bool(_CATALOG_TERM.fullmatch(institution_name))


# 워커가 매시 목록을 덮어써 요청 경로가 콜드 목록 생성을 만나지 않게 합니다. 두 번 거르기 전에는 만료되지
# 않도록 주기의 두 배로 둡니다. 워커가 멈추면 요청 경로가 종전처럼 1시간 목록을 직접 만듭니다.
INSTITUTION_CATALOG_REFRESH_TTL = 2 * 60 * 60


def _institution_catalog_key(column) -> str:
    return f"rag:inst_catalog:{column.class_.__tablename__}"


def _load_institution_catalog(db: Session, column) -> list[str]:
    return [row[0] for row in db.execute(select(column).distinct()).all() if row[0]]


def _institution_name_catalog(db: Session, column) -> list[str]:
    key = _institution_catalog_key(column)
    names = _timed_cache_get(key)
    if names is None:
        with _flight_lock(key):
            names = _timed_cache_get(key)
            if names is None:
                names = _load_institution_catalog(db, column)
                cache.set(key, names, AGGREGATE_CACHE_TTL)
    return names


def refresh_institution_name_catalogs(db: Session) -> dict[str, int]:
    """공고·낙찰 고유 기관명 목록을 다시 읽어 캐시를 덮어씁니다."""
    counts = {}
    for column in (BidAnnouncement.dminstt_nm, BidResult.dminstt_nm):
        names = _load_institution_catalog(db, column)
        cache.set(_institution_catalog_key(column), names, INSTITUTION_CATALOG_REFRESH_TTL)
        counts[column.class_.__tablename__] = len(names)
    return counts


def _match_institution_catalog(names: list[str], institution_name: str) -> list[str] | None:
    """목록에서 부분 일치 이름을 고릅니다. 확정할 수 없는 이름이 있으면 None 입니다."""
    matched = []
    for name in names:
        if institution_name in name:
            matched.append(name)
        elif _CATALOG_UNCERTAIN_CHARS.search(name) and institution_name in (
            _CATALOG_UNCERTAIN_CHARS.sub("", name)
        ):
            return None
    return matched


@_measure_call("institution_resolve")
def _resolve_institution_names(db: Session, column, institution_name: str) -> list[str] | None:
    """기관명 부분 일치를 정확한 이름 목록으로 풉니다. 상한 초과면 None 입니다.

    utf8mb4_unicode_ci 등호는 대소문자와 끝 공백 차이를 같게 보므로, 여기서 얻은
    대표 이름의 IN 조회는 부분 일치가 잡던 변형 행을 함께 잡습니다.
    """
    if _catalog_eligible(institution_name):
        matched = _match_institution_catalog(
            _institution_name_catalog(db, column), institution_name
        )
        if matched is not None and len(matched) > 0:
            return None if len(matched) > INSTITUTION_NAME_RESOLVE_LIMIT else matched
    stmt = (
        select(column)
        .where(column.contains(institution_name))
        .distinct()
        .limit(INSTITUTION_NAME_RESOLVE_LIMIT + 1)
    )
    key = _stmt_cache_key("rag:inst:", stmt)
    cached = _timed_cache_get(key)
    if cached is None:
        with _flight_lock(key):
            cached = _timed_cache_get(key)
            if cached is None:
                names = [row[0] for row in db.execute(stmt).all() if row[0] is not None]
                if len(names) > INSTITUTION_NAME_RESOLVE_LIMIT:
                    cached = {"overflow": True}
                    cache.set(key, cached, INSTITUTION_OVERFLOW_CACHE_TTL)
                elif not names:
                    cached = {"names": names}
                    cache.set(key, cached, INSTITUTION_EMPTY_RESOLVE_CACHE_TTL)
                else:
                    cached = {"names": names}
                    cache.set(key, cached, AGGREGATE_CACHE_TTL)
    if cached.get("overflow"):
        return None
    names = list(cached["names"])
    if len(names) > INSTITUTION_NAME_RESOLVE_LIMIT:
        return None
    return names


# U+FFFD 는 SQL 에서 먼저 쳐내므로 배수는 작아도 됩니다.
LIVE_OVERFETCH_FACTOR = 3

# 집계 캐시 유효 시간. 원본 데이터는 야간 수집(02:00)에서만 바뀌므로 한 시간
# 묵은 값이어도 답변의 사실관계가 흔들리지 않습니다. 대시보드 계열이 24시간을
# 쓰지만 그쪽은 야간에 명시적으로 예열하는 반면 이 경로는 예열 대상이 아니라
# 짧게 잡습니다.
AGGREGATE_CACHE_TTL = 60 * 60


def _stmt_cache_key(prefix: str, stmt) -> str:
    """리터럴을 채운 SQL 문자열의 해시를 키로 씁니다.

    조건이 하나라도 다르면 다른 키가 되므로, 필터가 다른 질의가 서로의 값을
    물려받는 사고가 없습니다.
    """
    compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
    return prefix + hashlib.sha256(compiled.encode("utf-8")).hexdigest()


def _drop_corrupted(rows, limit: int) -> tuple[list, int]:
    """인코딩이 깨진 값을 순위에서 제외합니다.

    복구 불가능한 손상값(bid_results 의 41%)을 그대로 두면 순위 상위가 전부
    깨진 문자열로 채워집니다. 제외 건수를 함께 돌려 답변에 안내를 답니다.
    """
    kept: list = []
    dropped = 0
    for row in rows:
        if is_corrupted_display_text(row[0]):
            dropped += 1
            continue
        kept.append(row)
        if len(kept) >= limit:
            break
    return kept, dropped


class _FlightLockEntry:
    __slots__ = ("lock", "ref_count")

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.ref_count = 0


_flight_master_lock = threading.Lock()
_flight_locks: dict[str, _FlightLockEntry] = {}


@contextmanager
def _flight_lock(key: str):
    """동일 캐시 키에 대한 동시 DB 조회를 1회로 병합(single-flight)하기 위한 참조 계수 기반 잠금을 제공합니다.

    마지막 대기자가 빠져나갈 때 딕셔너리에서 항목을 제거하여 동적 SQL 리터럴 키가 무한 누적되는 메모리 누수를 방지합니다.
    """
    with _flight_master_lock:
        entry = _flight_locks.get(key)
        if entry is None:
            entry = _FlightLockEntry()
            _flight_locks[key] = entry
        entry.ref_count += 1

    try:
        with entry.lock:
            yield
    finally:
        with _flight_master_lock:
            entry.ref_count -= 1
            if entry.ref_count == 0:
                _flight_locks.pop(key, None)


@_measure_call("top_rows")
def _top_rows(
    db: Session,
    *,
    scope: str | None,
    dataset: str,
    dimension: str,
    live_stmt,
    category: str = "",
    corrupted_probe: Any = None,
    limit: int = 5,
    ttl: int = AGGREGATE_CACHE_TTL,
) -> tuple[list, int]:
    """스냅샷이 있으면 그것을, 없으면 실시간 집계를 씁니다.

    스냅샷은 집계 시점에 이미 손상값을 걸러 두었으므로 그대로 씁니다.
    실시간 경로는 여기서 걸러냅니다.
    키별 single-flight 로 동시 cold miss 가 같은 순위 집계를 중복 실행하지 않게 합니다.
    """
    if scope is not None:
        cached = get_top_rankings(db, dataset, dimension, scope, limit)
        if cached is not None:
            # 스냅샷은 집계 시점에 걸러냈으므로 그때 기록해 둔 표시를 씁니다.
            return cached, get_skipped_count(db, dataset, dimension, scope)

    # 스냅샷은 날짜 필터가 붙는 순간 포기합니다(_snapshot_scope). "2026년" 같은
    # 흔한 표현이 곧 날짜 필터이므로 실시간 경로가 자주 타며, 그 경로가 캐시
    # 없이는 매번 46~97초를 씁니다(2026-08-30 실측). 같은 창을 다시 묻는 일이
    # 잦으므로 캐시합니다.
    stmt = live_stmt.limit(limit * LIVE_OVERFETCH_FACTOR)
    key = _stmt_cache_key("rag:top:", stmt)
    cached_live = _timed_cache_get(key)
    if cached_live is not None:
        rows, dropped = cached_live
        return [tuple(row) for row in rows], int(dropped)

    with _flight_lock(key):
        # 잠금 획득 후 캐시 재확인
        cached_live = _timed_cache_get(key)
        if cached_live is not None:
            rows, dropped = cached_live
            return [tuple(row) for row in rows], int(dropped)

        kept, dropped = _drop_corrupted(db.execute(stmt).all(), limit)
        marker: int | None = None
        if not dropped:
            # 마커가 존재하면(0 포함) 그 값을 그대로 쓰고 탐침을 돌지 않습니다.
            # 마커가 아예 없을 때만 종전대로 탐침을 실행합니다.
            marker = get_skipped_marker(db, dataset, dimension, category)
            if marker is not None:
                dropped = marker
        if not dropped and marker is None and corrupted_probe is not None:
            # 마커까지 없으면 제외 여부를 알 방법이 없습니다. SQL 이 exclude_corrupted 로
            # 이미 손상값을 걸러 보내기 때문에 파이썬 계층이 셀 것이 남지 않습니다.
            # 그 상태로 0 을 확정하면 실제로 제외했는데도 안내가 사라집니다(Wave E1 회귀).
            # 순위가 채워졌어도 탐침을 생략할 수 없습니다. 가져온 창이 깨끗한 것과
            # 전체 결과에 손상이 없는 것은 다르기 때문입니다(2026-09-06 확인,
            # tests/test_ranking_snapshots.py 의 live_path 계열이 이 동작을 고정합니다).
            # 마커가 있는 운영 환경에서는 앞 줄에서 끝나 이 줄에 오지 않으므로,
            # 스냅샷이 아직 없는 환경에서만 LIMIT 1 탐침 한 번을 씁니다.
            # 비용 실측(2026-09-06 EXPLAIN): 날짜 무 3,118,641행 전체 스캔,
            # 날짜 유 501,266행 범위 스캔. 선행 와일드카드라 줄일 수 없습니다.
            probe_started = time.perf_counter()
            try:
                dropped = int(db.execute(corrupted_probe.limit(1)).first() is not None)
            finally:
                _record_segment(
                    "corrupted_probe_ms", (time.perf_counter() - probe_started) * 1000.0
                )

        # 손상 탐지 결과까지 함께 담습니다. 순위만 캐시하면 적중할 때마다 탐지
        # 질의가 다시 돌아 절반만 아끼게 됩니다.
        cache.set(key, [[[_cacheable(v) for v in row] for row in kept], dropped], ttl)
        return kept, dropped


@_measure_call("cached_aggregate")
def _cached_aggregate(db: Session, stmt, ttl: int = AGGREGATE_CACHE_TTL) -> list[Any]:
    """집계 결과를 캐시에서 돌려줍니다.

    3,405,928 행 위의 COUNT/AVG/SUM 은 질의당 190ms 가 걸립니다. 챗봇 한 번에
    이런 집계가 아홉 번 돌아 1.72초를 씁니다. 그동안 첫 토큰은 나오지 않습니다.

    캐시가 없어도(Redis 미가용) CacheLayer 가 메모리 캐시로 내려가므로 동작은
    같습니다. 값이 없으면 그냥 DB 를 칩니다.
    키별 single-flight 로 동시 cold miss 가 같은 대규모 집계를 중복 실행하지 않게 합니다.
    """
    key = _stmt_cache_key("rag:agg:", stmt)

    cached = _timed_cache_get(key)
    if cached is not None:
        return list(cached)

    with _flight_lock(key):
        # 잠금 획득 후 캐시 재확인
        cached = _timed_cache_get(key)
        if cached is not None:
            return list(cached)

        row = list(db.execute(stmt).one())
        # Redis 경로는 JSON 직렬화라 Decimal 이 문자열이 됩니다. 메모리 캐시와 값
        # 종류가 달라지지 않도록 여기서 미리 float 로 맞춥니다. 호출부는 어차피
        # int()/float() 로 다시 감쌉니다.
        normalized = [_numeric_or_none(value) for value in row]
        cache.set(key, normalized, ttl)
        return normalized


# 서로 기다리지 않는 집계 다섯 개를 순차로 돌면 q08 콜드에서 SQL 합계 약 4.9초였고 가장 긴 문장은 1.9초였습니다
# (2026-09-13). 프로세스 전체에서 스레드를 넷으로 묶어 추가 연결이 요청 수에 비례해 늘지 않게 합니다
# (연결 풀 10+20). 붐비면 대기열에서 기다리므로 순차 실행보다 느려지지는 않습니다.
PARALLEL_AGGREGATE_WORKERS = 4
_parallel_executor: ThreadPoolExecutor | None = None
_parallel_executor_lock = threading.Lock()


def _aggregate_executor() -> ThreadPoolExecutor:
    global _parallel_executor
    with _parallel_executor_lock:
        if _parallel_executor is None:
            _parallel_executor = ThreadPoolExecutor(
                max_workers=PARALLEL_AGGREGATE_WORKERS, thread_name_prefix="rag-aggregate"
            )
        return _parallel_executor


def _parallel_aggregates_enabled(db: Session) -> bool:
    # SQLite 인메모리 테스트 DB 는 연결 하나를 공유하므로 스레드별 세션을 열 수 없습니다.
    return db.get_bind().dialect.name == "mysql"


def _run_with_label(label: str, func, session: Session):
    token = _reserved_segment_label.set(label)
    try:
        return func(session)
    finally:
        _reserved_segment_label.reset(token)


def _run_in_own_session(label: str, func, bind):
    with Session(bind=bind) as session:
        return _run_with_label(label, func, session)


def _run_aggregates(db: Session, tasks: list[tuple[str, Any]]) -> list[Any]:
    """(구간 접두어, 세션을 받는 함수) 목록을 실행해 결과를 같은 순서로 돌려줍니다.

    MySQL 이면 마지막 작업은 요청 세션에서, 나머지는 각자 세션으로 동시에 돌립니다.
    """
    if not _parallel_aggregates_enabled(db):
        return [func(db) for _, func in tasks]
    labels = [_next_segment_label(prefix) for prefix, _ in tasks]
    bind = db.get_bind()
    executor = _aggregate_executor()
    futures = [
        executor.submit(contextvars.copy_context().run, _run_in_own_session, label, func, bind)
        for label, (_, func) in zip(labels[:-1], tasks[:-1], strict=True)
    ]
    try:
        last = _run_with_label(labels[-1], tasks[-1][1], db)
    finally:
        results = [future.result() for future in futures]
    return [*results, last]


def _cacheable(value: Any) -> Any:
    """순위 행의 값을 Redis JSON 경로에서도 같은 모양이 되도록 맞춥니다.

    순위 행은 (이름, 건수) 형태라 문자열이 섞입니다. 숫자만 다루는
    `_numeric_or_none` 을 쓰면 이름을 float 로 바꾸려다 실패합니다.
    """
    if value is None or isinstance(value, (str, int, float)):
        return value
    if isinstance(value, Decimal):
        return float(value)
    return str(value)


def _numeric_or_none(value: Any) -> Any:
    if value is None or isinstance(value, (int, float)):
        return value
    return float(value)


def _format_recent_result(result: BidResult) -> dict[str, Any]:
    """낙찰 결과 단건 모델 인스턴스를 반환용 딕셔너리로 변환합니다."""
    return {
        "id": result.id,
        "bid_ntce_no": result.bid_ntce_no,
        "bid_ntce_ord": result.bid_ntce_ord,
        "bid_ntce_nm": clean_display_text(result.bid_ntce_nm, CORRUPTED_TEXT_FALLBACKS["title"]),
        "dminstt_nm": clean_display_text(result.dminstt_nm, CORRUPTED_TEXT_FALLBACKS["agency"]),
        "bidwinnr_nm": clean_display_text(result.bidwinnr_nm, CORRUPTED_TEXT_FALLBACKS["winner"]),
        "sucsf_bid_amt": (int(result.sucsf_bid_amt) if result.sucsf_bid_amt is not None else None),
        "sucsf_bid_rate": (
            float(result.sucsf_bid_rate) if result.sucsf_bid_rate is not None else None
        ),
        "rl_openg_dt": (
            result.rl_openg_dt.isoformat(sep=" ") if result.rl_openg_dt is not None else None
        ),
        "category": result.category,
        "category_label": _category_label(result.category),
    }


def _fetch_recent_results(db: Session, conditions: list, limit: int) -> list[dict[str, Any]]:
    """조건에 맞는 최신 낙찰 결과를 손상값 제외 후 최대 limit 건 조회합니다."""
    if not limit:
        return []
    result_rows = (
        db.execute(
            select(BidResult)
            .where(*conditions)
            .order_by(
                BidResult.rl_openg_dt.is_(None),
                BidResult.rl_openg_dt.desc(),
                BidResult.id.desc(),
            )
            .limit(limit * LIVE_OVERFETCH_FACTOR)
        )
        .scalars()
        .all()
    )
    recent: list[dict[str, Any]] = []
    for result in result_rows:
        if any(
            is_corrupted_display_text(value)
            for value in (
                result.bid_ntce_nm,
                result.dminstt_nm,
                result.bidwinnr_nm,
            )
        ):
            continue
        recent.append(_format_recent_result(result))
        if len(recent) >= limit:
            break
    return recent


def _fetch_sample_announcements(
    db: Session, conditions: list, limit: int = 3
) -> list[dict[str, Any]]:
    """표본 공고 목록을 조회하고 화면 표시용 대체 텍스트를 적용합니다."""
    rows = db.execute(
        select(
            BidAnnouncement.bid_ntce_no,
            BidAnnouncement.bid_ntce_nm,
            BidAnnouncement.dminstt_nm,
        )
        .where(*conditions)
        .order_by(BidAnnouncement.bid_ntce_dt.desc())
        .limit(limit)
    ).all()
    return [
        {
            "bid_ntce_no": row[0],
            # 표본은 순위와 달리 건너뛸 수 없으므로 화면과 같은 안내 문구로 대체합니다.
            "bid_ntce_nm": clean_display_text(row[1], CORRUPTED_TEXT_FALLBACKS["title"]),
            "dminstt_nm": clean_display_text(row[2], CORRUPTED_TEXT_FALLBACKS["agency"]),
        }
        for row in rows
    ]


def _generate_quarters_between(
    start_date: date | datetime, end_date: date | datetime
) -> list[tuple[int, int]]:
    """start_date부터 end_date까지의 (연도, 분기) 목록을 순서대로 생성합니다."""
    start_y = start_date.year
    start_q = (start_date.month - 1) // 3 + 1
    end_y = end_date.year
    end_q = (end_date.month - 1) // 3 + 1

    quarters: list[tuple[int, int]] = []
    curr_y, curr_q = start_y, start_q
    while (curr_y < end_y) or (curr_y == end_y and curr_q <= end_q):
        quarters.append((curr_y, curr_q))
        if curr_q == 4:
            curr_y += 1
            curr_q = 1
        else:
            curr_q += 1
    return quarters


def _quarter_boundaries(year: int, quarter: int) -> tuple[datetime, datetime]:
    """분기의 시작과 다음 분기의 시작 [분기 첫날 00:00, 다음 분기 첫날 00:00) 반열림 구간을 반환합니다."""
    start_month = (quarter - 1) * 3 + 1
    start_dt = datetime(year, start_month, 1, 0, 0, 0)
    if quarter == 4:
        next_dt = datetime(year + 1, 1, 1, 0, 0, 0)
    else:
        next_dt = datetime(year, start_month + 3, 1, 0, 0, 0)
    return start_dt, next_dt


def _build_time_series(
    db: Session,
    plan: RetrievalPlan,
    conditions: list,
    announcement_conditions: list | None = None,
    result_names: list[str] | None = None,
    announcement_names: list[str] | None = None,
) -> list[dict[str, Any]]:
    """트렌드 분석 모드이거나 time_bucket이 quarter일 때 개찰일자별 낙찰률 시계열 버킷을 계산합니다."""
    filters = plan.filters or {}
    is_quarter = filters.get("time_bucket") == "quarter"

    if not is_quarter and filters.get("analysis_mode") != "trend":
        return []

    if is_quarter:
        date_from, date_to = _resolve_window(filters)
        if date_from and date_to:
            quarters = _generate_quarters_between(date_from, date_to)
        elif date_from:
            quarters = _generate_quarters_between(date_from, date_from)
        else:
            today = date.today()
            quarters = [(today.year, q) for q in range(1, 5)]

        institution_name = _normalize_text(str(filters.get("institution_name") or ""))
        category = _normalize_text(str(filters.get("category") or ""))

        base_res_conditions = []
        if institution_name:
            base_res_conditions.append(
                _institution_condition(BidResult.dminstt_nm, institution_name, result_names)
            )
        if category:
            base_res_conditions.append(BidResult.category == category)

        base_ann_conditions = []
        if institution_name:
            base_ann_conditions.append(
                _institution_condition(
                    BidAnnouncement.dminstt_nm, institution_name, announcement_names
                )
            )
        if category:
            base_ann_conditions.append(BidAnnouncement.category == category)

        series = []
        for year, quarter in quarters:
            q_start, q_next = _quarter_boundaries(year, quarter)
            res_stmt = select(
                func.count(BidResult.id),
                func.avg(BidResult.sucsf_bid_rate),
            ).where(
                BidResult.rl_openg_dt >= q_start,
                BidResult.rl_openg_dt < q_next,
                *base_res_conditions,
            )
            ann_stmt = select(func.count(BidAnnouncement.id)).where(
                BidAnnouncement.bid_ntce_dt >= q_start,
                BidAnnouncement.bid_ntce_dt < q_next,
                *base_ann_conditions,
            )

            res_row = _cached_aggregate(db, res_stmt)
            bid_count = int(res_row[0] or 0)
            avg_rate = float(round(float(res_row[1] or 0), 4)) if res_row[1] is not None else 0.0

            ann_row = _cached_aggregate(db, ann_stmt)
            ann_count = int(ann_row[0] or 0)

            label = f"{year}년 {quarter}분기"
            series.append(
                {
                    "label": label,
                    "month": label,
                    "period": "quarter",
                    "avg_rate": avg_rate,
                    "bid_count": bid_count,
                    "announcement_count": ann_count,
                    "ntce_count": ann_count,
                }
            )
        return series

    granularity = _resolve_time_series_granularity(plan)
    series_buckets: dict[str, dict[str, float]] = {}
    rows = db.execute(
        select(BidResult.rl_openg_dt, BidResult.sucsf_bid_rate)
        .where(*conditions)
        .order_by(BidResult.rl_openg_dt)
    ).all()
    for opened_at, bid_rate in rows:
        if not opened_at:
            continue
        bucket_key = _time_series_bucket_key(opened_at, granularity)
        bucket = series_buckets.setdefault(bucket_key, {"sum_rate": 0.0, "bid_count": 0})
        bucket["sum_rate"] += float(bid_rate or 0)
        bucket["bid_count"] += 1

    return [
        {
            "label": bucket_key,
            "month": bucket_key,
            "period": granularity,
            "avg_rate": float(
                round(
                    (bucket["sum_rate"] / bucket["bid_count"]) if bucket["bid_count"] else 0,
                    4,
                )
            ),
            "bid_count": int(bucket["bid_count"]),
        }
        for bucket_key, bucket in sorted(series_buckets.items())
    ]


def _build_insufficiency_hints(
    *,
    total_count: float | None,
    result_limit: int,
    recent_results: list[dict[str, Any]],
    latest_available_result_at: datetime | None,
    announcement_count: float | None,
    dropped_total: int,
) -> list[str]:
    """데이터 부족 및 손상값 제외 안내 힌트 목록을 생성합니다."""
    hints: list[str] = []
    if not total_count:
        hints.append("조건에 맞는 낙찰 결과가 충분하지 않습니다.")
    if result_limit and not recent_results:
        if latest_available_result_at:
            hints.append(
                "요청 기간에 조건에 맞는 낙찰 결과가 없습니다. "
                f"DB에서 확인 가능한 해당 조건의 최신 개찰일은 "
                f"{latest_available_result_at.isoformat(sep=' ')}입니다."
            )
        else:
            hints.append("해당 분야의 낙찰 결과 보유 데이터가 없습니다.")
    if not announcement_count and not result_limit:
        hints.append("조건에 맞는 공고 데이터가 없어 추세 해석이 제한될 수 있습니다.")

    # 순위에서 손상값을 빼면 답이 읽히지만 집계 모수가 달라집니다. 숨기지 않고 알립니다.
    if dropped_total:
        hints.append(
            "일부 항목은 원문 인코딩이 손상되어 순위 집계에서 제외했습니다. "
            "표시된 순위는 판독 가능한 값 기준입니다."
        )
    return hints


def _empty_result(plan: RetrievalPlan, hint: str) -> dict[str, Any]:
    """조회를 수행하지 않았음을 드러내는 빈 결과를 만듭니다."""
    return {
        "filters": dict(plan.filters or {}),
        "summary": {
            "total_bids": None,
            "announcement_count": None,
            "average_winning_rate": None,
            "total_winning_amount": None,
            "top_winners": [],
            "top_institutions": [],
            "top_announcements": [],
            "sample_announcements": [],
            "recent_results": [],
            "latest_available_result_at": None,
            "time_series": [],
        },
        "insufficiency_hints": [hint],
        "query_skipped": True,
    }


def _retrieve_structured_data_impl(db: Session, plan: RetrievalPlan) -> dict[str, Any]:
    try:
        _resolve_window(plan.filters or {})
    except InvalidDateFilterError as exc:
        # 해석하지 못한 날짜 필터를 빼고 조회하면 전체 기간 통계가 사용자가
        # 지정한 기간의 답으로 돌아갑니다. 조회 자체를 하지 않고 알립니다.
        return _empty_result(
            plan,
            f"{exc} 날짜를 YYYY-MM-DD 형식으로 다시 알려주시면 해당 기간으로 조회하겠습니다.",
        )
    institution_name = _normalize_text(str((plan.filters or {}).get("institution_name") or ""))
    result_names = announcement_names = None
    if institution_name:
        result_names = _resolve_institution_names(db, BidResult.dminstt_nm, institution_name)
        announcement_names = _resolve_institution_names(
            db, BidAnnouncement.dminstt_nm, institution_name
        )
    result_conditions = _result_conditions(plan, institution_names=result_names)
    announcement_conditions = _announcement_conditions(plan, institution_names=announcement_names)
    snapshot_scope = _snapshot_scope(plan)
    result_limit = _result_limit(plan)
    latest_available_result_at = None
    if result_limit:
        latest_available_result_at = db.scalar(
            select(func.max(BidResult.rl_openg_dt)).where(
                *_result_availability_conditions(plan, institution_names=result_names)
            )
        )

    category_filter = _normalize_text(str((plan.filters or {}).get("category") or ""))
    winner_conditions = _result_conditions(
        plan, enable_ngram_prefilter=True, institution_names=result_names
    )
    institution_conditions = _announcement_conditions(
        plan, enable_ngram_prefilter=True, institution_names=announcement_names
    )

    def result_amounts(session: Session) -> list[Any]:
        return _cached_aggregate(
            session,
            _hint_result_institution_cover(
                select(
                    func.count(BidResult.id),
                    func.avg(BidResult.sucsf_bid_rate),
                    func.sum(BidResult.sucsf_bid_amt),
                ).where(*result_conditions),
                plan,
                result_names,
            ),
        )

    def announcement_total(session: Session) -> list[Any]:
        return _cached_aggregate(
            session,
            _hint_announcement_institution_cover(
                select(func.count(BidAnnouncement.id)).where(*announcement_conditions),
                plan,
                announcement_names,
            ),
        )

    def winner_ranking(session: Session) -> tuple[list, int]:
        return _top_rows(
            session,
            scope=snapshot_scope,
            dataset=DATASET_RESULT,
            dimension="bidwinnr_nm",
            category=category_filter,
            live_stmt=_hint_result_institution_cover(
                _hint_result_winner_group_index(
                    _hint_result_date_index(
                        select(BidResult.bidwinnr_nm, func.count(BidResult.id))
                        .where(exclude_corrupted(BidResult.bidwinnr_nm), *winner_conditions)
                        .group_by(BidResult.bidwinnr_nm)
                        .order_by(func.count(BidResult.id).desc()),
                        plan,
                    ),
                    plan,
                ),
                plan,
                result_names,
            ),
            corrupted_probe=select(BidResult.id).where(
                BidResult.bidwinnr_nm.contains(REPLACEMENT_CHAR), *result_conditions
            ),
        )

    def institution_ranking(session: Session) -> tuple[list, int]:
        return _top_rows(
            session,
            scope=snapshot_scope,
            dataset=DATASET_ANNOUNCEMENT,
            dimension="dminstt_nm",
            category=category_filter,
            live_stmt=_hint_announcement_institution_cover(
                _hint_announcement_date_index(
                    select(BidAnnouncement.dminstt_nm, func.count(BidAnnouncement.id))
                    .where(exclude_corrupted(BidAnnouncement.dminstt_nm), *institution_conditions)
                    .group_by(BidAnnouncement.dminstt_nm)
                    .order_by(func.count(BidAnnouncement.id).desc()),
                    plan,
                ),
                plan,
                announcement_names,
            ),
            corrupted_probe=select(BidAnnouncement.id).where(
                BidAnnouncement.dminstt_nm.contains(REPLACEMENT_CHAR), *announcement_conditions
            ),
        )

    def announcement_ranking(session: Session) -> tuple[list, int]:
        return _top_rows(
            session,
            scope=snapshot_scope,
            dataset=DATASET_ANNOUNCEMENT,
            dimension="bid_ntce_nm",
            category=category_filter,
            live_stmt=_hint_announcement_institution_cover(
                _hint_announcement_date_index(
                    select(BidAnnouncement.bid_ntce_nm, func.count(BidAnnouncement.id))
                    .where(exclude_corrupted(BidAnnouncement.bid_ntce_nm), *announcement_conditions)
                    .group_by(BidAnnouncement.bid_ntce_nm)
                    .order_by(func.count(BidAnnouncement.id).desc()),
                    plan,
                ),
                plan,
                announcement_names,
            ),
            corrupted_probe=select(BidAnnouncement.id).where(
                BidAnnouncement.bid_ntce_nm.contains(REPLACEMENT_CHAR), *announcement_conditions
            ),
        )

    # 가장 긴 공고명 집계를 마지막에 두어 요청 세션이 직접 맡게 합니다.
    (
        (total_count, avg_rate, total_amt),
        (announcement_count,),
        (winner_rows, dropped_winners),
        (institution_rows, dropped_institutions),
        (announcement_rows, dropped_announcements),
    ) = _run_aggregates(
        db,
        [
            ("cached_aggregate", result_amounts),
            ("cached_aggregate", announcement_total),
            ("top_rows", winner_ranking),
            ("top_rows", institution_ranking),
            ("top_rows", announcement_ranking),
        ],
    )

    recent_results = _fetch_recent_results(db, result_conditions, result_limit)
    top_winners = [
        {"bidwinnr_nm": _normalize_text(row[0]) if row[0] else row[0], "win_count": row[1]}
        for row in winner_rows
    ]
    top_institutions = [
        {"dminstt_nm": _normalize_text(row[0]) if row[0] else row[0], "ntce_count": row[1]}
        for row in institution_rows
    ]
    top_announcements = [
        {"bid_ntce_nm": _normalize_text(row[0]) if row[0] else row[0], "ntce_count": row[1]}
        for row in announcement_rows
    ]

    sample_announcements = _fetch_sample_announcements(db, announcement_conditions)
    time_series = _build_time_series(
        db,
        plan,
        result_conditions,
        announcement_conditions=announcement_conditions,
        result_names=result_names,
        announcement_names=announcement_names,
    )

    dropped_total = dropped_winners + dropped_institutions + dropped_announcements
    insufficiency = _build_insufficiency_hints(
        total_count=total_count,
        result_limit=result_limit,
        recent_results=recent_results,
        latest_available_result_at=latest_available_result_at,
        announcement_count=announcement_count,
        dropped_total=dropped_total,
    )

    assembly_started = time.perf_counter()
    response_filters = dict(plan.filters or {})
    if response_filters.get("category"):
        response_filters["category_label"] = _category_label(str(response_filters["category"]))

    result = {
        "filters": response_filters,
        "summary": {
            "total_bids": int(total_count or 0),
            "announcement_count": int(announcement_count or 0),
            "average_winning_rate": float(round(avg_rate or 0, 4)),
            "total_winning_amount": float(total_amt or 0),
            "top_winners": top_winners,
            "top_institutions": top_institutions,
            "top_announcements": top_announcements,
            "sample_announcements": sample_announcements,
            "recent_results": recent_results,
            "latest_available_result_at": (
                latest_available_result_at.isoformat(sep=" ")
                if latest_available_result_at
                else None
            ),
            "time_series": time_series,
        },
        "insufficiency_hints": insufficiency,
    }
    _record_segment("result_assembly_ms", (time.perf_counter() - assembly_started) * 1000.0)
    return result


def retrieve_structured_data(db: Session, plan: RetrievalPlan) -> dict[str, Any]:
    """정형 검색을 실행하고 진단용 구간 계측을 contextvar에 남깁니다."""
    record = _open_latency_record()
    try:
        return _retrieve_structured_data_impl(db, plan)
    except Exception as exc:
        if record is not None:
            logger.warning("정형 검색 계측 중 호출 경로 예외를 관찰했습니다: %s", exc)
        raise
    finally:
        _close_latency_record(record)

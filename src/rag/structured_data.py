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

from sqlalchemy import Integer, and_, case, event, func, or_, select
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
from src.rag.query_planning import (
    DEFAULT_AMOUNT_FIELD,
    DEFAULT_GROUP_LIMIT,
    MAX_GROUP_LIMIT,
    REGION_ALIASES,
    RESULT_AMOUNT_FIELD,
    _single_metric,
    collect_unapplied_result_conditions,
    is_result_amount_scope,
    unapplied_result_condition_notice,
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
    relative_days = int(filters.get("recent_days") or 0)
    relative_years = int(filters.get("relative_years") or 0)

    if relative_days and not date_from:
        today = date.today()
        date_from = _parse_date((today - timedelta(days=relative_days - 1)).isoformat())
        date_to = date_to or _parse_date(today.isoformat())
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


def _region_condition(column, aliases: tuple[str, ...]) -> Any:
    """지역 별칭 목록을 기관명 부분 일치 OR 묶음 조건으로 만듭니다."""
    return or_(*[column.contains(alias) for alias in aliases])


def _region_scope_names(filters: dict[str, Any]) -> list[str]:
    """나열 지역 합집합 조건의 정규화된 지역명을 질의 순서대로 돌려줍니다."""
    raw_names = filters.get("region_scope_names")
    if not isinstance(raw_names, (list, tuple)):
        return []
    names: list[str] = []
    for item in raw_names:
        name = _normalize_text(str(item))
        if name in REGION_ALIASES and name not in names:
            names.append(name)
    return names


def _region_scope_condition(column, filters: dict[str, Any]) -> Any:
    """나열 지역 전체를 지역 별칭 부분 일치 OR 하나로 묶습니다."""
    names = _region_scope_names(filters)
    if not names:
        return None
    return or_(*[column.contains(alias) for name in names for alias in REGION_ALIASES[name]])


# 업체명 표기는 "주식회사 한백", "(주)한백", "한백" 처럼 법인 표지와 공백·괄호가
# 섞입니다. 부분 일치로 비교하면 "한백" 질의가 "한백건설" 행까지 반환하므로,
# 양쪽에서 같은 표지를 떼고 정규화 값이 같은 행만 고릅니다.
WINNER_NAME_NOISE_MARKERS = ("주식회사", "(주)", "㈜", "유한회사", "합자회사")
WINNER_NAME_NOISE_CHARACTERS = (" ", "\u3000", "(", ")", "\uff08", "\uff09")


def _normalize_winner_name_value(value: str) -> str:
    """업체명에서 법인 표지·공백·괄호를 뗀 비교용 값을 만듭니다."""
    normalized = _normalize_text(value)
    for marker in WINNER_NAME_NOISE_MARKERS:
        normalized = normalized.replace(marker, "")
    for character in WINNER_NAME_NOISE_CHARACTERS:
        normalized = normalized.replace(character, "")
    return normalized


# 두 글자 이하 상호는 흔한 낱말과 겹쳐 부분 일치가 다른 업체를 대량으로
# 끌어옵니다. 안내를 붙이지 않는 하한입니다.
WINNER_VARIANT_MIN_NAME_LENGTH = 3


def _normalized_winner_name_column():
    """업체명 컬럼을 파이썬과 같은 규칙(법인 표지·공백·괄호 제거)으로 정규화합니다."""
    column: Any = BidResult.bidwinnr_nm
    for marker in WINNER_NAME_NOISE_MARKERS:
        column = func.replace(column, marker, "")
    for character in WINNER_NAME_NOISE_CHARACTERS:
        column = func.replace(column, character, "")
    return column


def _winner_name_condition(winner_name: str):
    """업체명을 컬럼 쪽도 같은 규칙으로 정규화한 뒤 등호로 비교합니다."""
    return _normalized_winner_name_column() == _normalize_winner_name_value(winner_name)


def _winner_name_variant_conditions(winner_name: str):
    """정규화한 상호를 포함하되 정확 일치가 아닌 행을 고르는 조건을 만듭니다."""
    normalized = _normalize_winner_name_value(winner_name)
    escaped = normalized.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    column = _normalized_winner_name_column()
    return column.like(f"%{escaped}%", escape="\\"), column != normalized


def _winner_variant_notice(name: str, other_count: int, total_count: int) -> str:
    """정확 일치 밖 상호의 건수와 합계를 한 문장으로 만듭니다."""
    last = name[-1] if name else ""
    has_final_consonant = "\uac00" <= last <= "\ud7a3" and (ord(last) - 0xAC00) % 28 != 0
    particle = "이" if has_final_consonant or not last else "가"
    return (
        f"상호에 {name}{particle} 들어간 다른 업체(지점 등) 낙찰은 같은 기간 "
        f"{other_count:,}건이며, 합치면 {total_count:,}건입니다."
    )


def _count_other_winner_variants(
    db: Session,
    plan: RetrievalPlan,
    winner_name: str,
    *,
    institution_names: list[str] | None = None,
) -> int:
    """같은 기간·분류·지역 조건에서 정확 일치 밖 상호의 낙찰 건수를 셉니다."""
    normalized = _normalize_winner_name_value(winner_name)
    if len(normalized) < WINNER_VARIANT_MIN_NAME_LENGTH:
        return 0
    filters = dict(plan.filters or {})
    filters.pop("winner_name", None)
    scope_plan = plan.model_copy(update={"filters": filters})
    contains_condition, not_exact_condition = _winner_name_variant_conditions(winner_name)
    (count,) = _cached_aggregate(
        db,
        select(func.count(BidResult.id)).where(
            *_result_conditions(scope_plan, institution_names=institution_names),
            contains_condition,
            not_exact_condition,
            exclude_corrupted(BidResult.bidwinnr_nm),
        ),
    )
    return int(count or 0)


# 금액 조건과 정렬에 쓰는 컬럼입니다. 계획기는 컬럼 이름 문자열을 넘기고,
# 조회 계층이 이 표에서 실제 컬럼을 고릅니다. 대상 테이블에 없는 컬럼은
# 조건을 만들지 않아 다른 금액 축의 조건이 잘못 적용되지 않습니다.
ANNOUNCEMENT_AMOUNT_COLUMNS = {
    "presmpt_prce": BidAnnouncement.presmpt_prce,
    "base_amount": BidAnnouncement.base_amount,
}
RESULT_AMOUNT_COLUMNS = {
    "sucsf_bid_amt": BidResult.sucsf_bid_amt,
}
ANNOUNCEMENT_SORT_COLUMNS = {
    **ANNOUNCEMENT_AMOUNT_COLUMNS,
    "bid_clse_dt": BidAnnouncement.bid_clse_dt,
}
RESULT_SORT_COLUMNS = {
    **RESULT_AMOUNT_COLUMNS,
    "rl_openg_dt": BidResult.rl_openg_dt,
}


def _int_filter(filters: dict[str, Any], key: str) -> int | None:
    raw = filters.get(key)
    if raw in (None, ""):
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _amount_field_filter(filters: dict[str, Any], default: str = DEFAULT_AMOUNT_FIELD) -> str:
    return _normalize_text(str(filters.get("amount_field") or "")) or default


def _amount_conditions(
    filters: dict[str, Any], columns: dict[str, Any], *, default_field: str = DEFAULT_AMOUNT_FIELD
) -> list:
    """금액 하한·상한 조건을 만듭니다. 대상 컬럼이 없으면 빈 목록입니다."""
    column = columns.get(_amount_field_filter(filters, default_field))
    if column is None:
        return []
    min_amount = _int_filter(filters, "min_amount")
    max_amount = _int_filter(filters, "max_amount")
    conditions = []
    if min_amount is not None:
        conditions.append(column >= min_amount)
    if max_amount is not None:
        conditions.append(column <= max_amount)
    return conditions


def _close_conditions(filters: dict[str, Any]) -> list:
    """마감일 창 조건을 만듭니다. 하루 단위 창이므로 종료일 다음 날 0시 미만입니다."""
    close_from = _parse_date(filters.get("close_from"), "close_from")
    close_to = _parse_date(filters.get("close_to"), "close_to")
    conditions = []
    if close_from:
        conditions.append(BidAnnouncement.bid_clse_dt >= close_from)
    if close_to:
        conditions.append(BidAnnouncement.bid_clse_dt < close_to + timedelta(days=1))
    return conditions


def _order_direction(filters: dict[str, Any]) -> str:
    return (
        "asc" if _normalize_text(str(filters.get("order_dir") or "")).lower() == "asc" else "desc"
    )


def _announcement_order_by(filters: dict[str, Any]) -> list:
    """공고 목록 정렬입니다. 정렬 표지가 없으면 기존 공고일 내림차순입니다."""
    column = ANNOUNCEMENT_SORT_COLUMNS.get(_normalize_text(str(filters.get("order_by") or "")))
    if column is None:
        return [BidAnnouncement.bid_ntce_dt.desc()]
    ordered = column.asc() if _order_direction(filters) == "asc" else column.desc()
    return [column.is_(None), ordered, BidAnnouncement.bid_ntce_dt.desc()]


def _result_order_by(filters: dict[str, Any]) -> list:
    """낙찰 목록 정렬입니다. 정렬 표지가 없으면 기존 개찰일 내림차순입니다."""
    column = RESULT_SORT_COLUMNS.get(_normalize_text(str(filters.get("order_by") or "")))
    if column is None:
        return [
            BidResult.rl_openg_dt.is_(None),
            BidResult.rl_openg_dt.desc(),
            BidResult.id.desc(),
        ]
    ordered = column.asc() if _order_direction(filters) == "asc" else column.desc()
    return [
        column.is_(None),
        ordered,
        BidResult.rl_openg_dt.is_(None),
        BidResult.rl_openg_dt.desc(),
        BidResult.id.desc(),
    ]


def _result_conditions(
    plan: RetrievalPlan,
    *,
    enable_ngram_prefilter: bool = False,
    institution_names: list[str] | None = None,
    bid_ntce_no: str | None = None,
) -> list:
    # 공고번호 단건 조회는 유일 키 하나만 조건으로 씁니다. "최근" 같은 상대 기간
    # 표지나 분류·기관·지역·목록 필터를 함께 걸면 개찰일이 그 창 밖인 행을
    # 놓칩니다. 이 조기 반환이 단건 경로와 집계 경로의 경계입니다.
    if bid_ntce_no:
        return [BidResult.bid_ntce_no == bid_ntce_no]

    filters = plan.filters or {}
    date_from, date_to = _resolve_window(filters)
    institution_name = _normalize_text(str(filters.get("institution_name") or ""))
    category = _normalize_text(str(filters.get("category") or ""))
    winner_name = _normalize_text(str(filters.get("winner_name") or ""))

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
    if institution_name or institution_names is not None:
        conditions.append(
            _institution_condition(BidResult.dminstt_nm, institution_name, institution_names)
        )
    region_scope_condition = _region_scope_condition(BidResult.dminstt_nm, filters)
    if region_scope_condition is not None:
        conditions.append(region_scope_condition)
    if category:
        conditions.append(BidResult.category == category)
    # 업체 조건은 낙찰 결과 테이블에만 있습니다. 업체를 지목한 질의에서 이 조건을
    # 빼면 전체 최신 목록이 그 업체 실적처럼 답해집니다. 손상값 제외 기준은
    # 순위 집계와 같게 유지합니다.
    if winner_name:
        conditions.append(_winner_name_condition(winner_name))
        conditions.append(exclude_corrupted(BidResult.bidwinnr_nm))
    conditions.extend(
        _amount_conditions(filters, RESULT_AMOUNT_COLUMNS, default_field=RESULT_AMOUNT_FIELD)
    )
    # 단건 조회 호출만 값을 넘깁니다. 이 조건이 집계용 조건에 섞이면 평균
    # 기준선이 그 공고 자체가 되거나 축 집계가 1행으로 붕괴합니다.
    if bid_ntce_no:
        conditions.append(BidResult.bid_ntce_no == bid_ntce_no)
    return conditions


def _announcement_conditions(
    plan: RetrievalPlan,
    *,
    enable_ngram_prefilter: bool = False,
    institution_names: list[str] | None = None,
    bid_ntce_no: str | None = None,
) -> list:
    # 공고번호 단건 조회는 유일 키 하나만 조건으로 씁니다. 공고일 기준 기간
    # 필터를 함께 걸면 "최근" 표지가 붙은 질의가 그 공고를 놓칩니다.
    if bid_ntce_no:
        return [BidAnnouncement.bid_ntce_no == bid_ntce_no]

    filters = plan.filters or {}
    date_from, date_to = _resolve_window(filters)
    institution_name = _normalize_text(str(filters.get("institution_name") or ""))
    category = _normalize_text(str(filters.get("category") or ""))
    notice_kind = _normalize_text(str(filters.get("notice_kind") or ""))

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
    if institution_name or institution_names is not None:
        conditions.append(
            _institution_condition(BidAnnouncement.dminstt_nm, institution_name, institution_names)
        )
    region_scope_condition = _region_scope_condition(BidAnnouncement.dminstt_nm, filters)
    if region_scope_condition is not None:
        conditions.append(region_scope_condition)
    if category:
        conditions.append(BidAnnouncement.category == category)
    if notice_kind:
        conditions.append(BidAnnouncement.ntce_kind_nm == notice_kind)
    conditions.extend(_close_conditions(filters))
    conditions.extend(_amount_conditions(filters, ANNOUNCEMENT_AMOUNT_COLUMNS))
    # 최댓값·최솟값 질문은 금액이 NULL 인 행을 순위에서 제외합니다. 정렬만으로는
    # NULL 이 섞일 수 있고, 값 하나를 묻는 답에 빈 금액이 1위가 되면 안 됩니다.
    if _normalize_text(str(filters.get("amount_extreme") or "")):
        amount_column = ANNOUNCEMENT_AMOUNT_COLUMNS.get(_amount_field_filter(filters))
        if amount_column is not None:
            conditions.append(amount_column.is_not(None))
    if bid_ntce_no:
        conditions.append(BidAnnouncement.bid_ntce_no == bid_ntce_no)
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
    if filters.get("recent_days"):
        return None
    if (
        filters.get("region_names")
        or filters.get("region_scope_names")
        or filters.get("institution_names")
        or filters.get("institution_aliases")
    ):
        return None
    if filters.get("bid_ntce_no"):
        return None
    # 사전 집계 스냅샷은 업체 축 전체 순위입니다. 특정 업체를 지목한 조회에
    # 쓰면 그 업체 조건이 사라진 전체 순위가 함께 나옵니다.
    if filters.get("winner_name"):
        return None
    if _normalize_text(str(filters.get("notice_kind") or "")):
        return None
    if filters.get("close_from") or filters.get("close_to"):
        return None
    if (
        _int_filter(filters, "min_amount") is not None
        or _int_filter(filters, "max_amount") is not None
    ):
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


def _announcement_limit(plan: RetrievalPlan) -> int:
    raw_limit = (plan.filters or {}).get("announcement_limit")
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
# 축별 집계 전용 힌트입니다. 한 문장에 테이블당 힌트 하나만 붙입니다.
# 분류별 낙찰 지표는 (category, dt, rate, amt) 커버링 인덱스로 3.37초(웜),
# 지역별 공고 건수는 (inst, category, dt) 커버링 인덱스로 9.2초(웜)였습니다.
# 지역 축에 날짜 인덱스(ix_bid_ann_dt_cat)를 강제하면 38.6초로 4.2배 느려집니다.
RESULT_CATEGORY_AXIS_HINT = "FORCE INDEX (ix_bid_results_cat_dt_stats)"
ANNOUNCEMENT_REGION_AXIS_HINT = "FORCE INDEX (ix_bid_ann_inst_cat_dt)"


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
    winner_name = _normalize_text(str(filters.get("winner_name") or ""))
    conditions = []
    if institution_name or institution_names is not None:
        conditions.append(
            _institution_condition(BidResult.dminstt_nm, institution_name, institution_names)
        )
    region_scope_condition = _region_scope_condition(BidResult.dminstt_nm, filters)
    if region_scope_condition is not None:
        conditions.append(region_scope_condition)
    if category:
        conditions.append(BidResult.category == category)
    # 업체 조건이 걸린 질의는 전체 최신 개찰일이 아니라 그 업체의 최신 개찰일을
    # 확인해야 빈 결과 안내가 다른 업체 실적을 가리키지 않습니다.
    if winner_name:
        conditions.append(_winner_name_condition(winner_name))
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
    key = _stmt_cache_key("rag:inst:", stmt, db)
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


def _institution_aliases(filters: dict[str, Any]) -> list[str]:
    """필터의 기관 별칭을 정규화해 중복 없이 돌려줍니다."""
    raw = filters.get("institution_aliases")
    if not isinstance(raw, (list, tuple)):
        return []
    aliases: list[str] = []
    for value in raw:
        normalized = _normalize_text(str(value or ""))
        if normalized and normalized not in aliases:
            aliases.append(normalized)
    return aliases


def _resolve_institution_scope_names(
    db: Session, column, institution_name: str, institution_aliases: list[str]
) -> list[str] | None:
    """기관명과 별칭을 각각 해석해 이름 합집합을 만듭니다.

    광역 단축명("충남")과 정식 명칭("충청남도")을 함께 넣어야 두 표기를 모두
    잡습니다. 한 검색어라도 해석 상한을 넘으면 부분 일치로 되돌리도록 None 을
    돌려줍니다.
    """
    terms: list[str] = []
    if institution_name:
        terms.append(institution_name)
    for alias in institution_aliases:
        if alias not in terms:
            terms.append(alias)
    if not terms:
        return None

    merged: list[str] = []
    for term in terms:
        names = _resolve_institution_names(db, column, term)
        if names is None:
            return None
        for name in names:
            if name not in merged:
                merged.append(name)
    return merged


def _resolve_multi_institution_scope_names(
    db: Session, column, institution_names: list[str]
) -> tuple[list[str], list[str]]:
    """이름마다 기관명을 해석해 합집합과 부분 일치 대체 이름을 돌려줍니다.

    해석 상한을 넘은 검색어는 이름 목록을 만들 수 없지만 버리지 않고 부분
    일치 대상으로 남깁니다. 그 이름을 버리면 기관 조건이 사라져 전체 목록으로
    조용히 넓어집니다.
    """
    resolved: list[str] = []
    fallback: list[str] = []
    for raw in institution_names:
        name = _normalize_text(str(raw))
        if not name:
            continue
        matched = _resolve_institution_names(db, column, name)
        if matched is None:
            if name not in fallback:
                fallback.append(name)
            continue
        for value in matched:
            if value not in resolved:
                resolved.append(value)
    return resolved, fallback


def _multi_institution_condition(column, resolved: list[str], fallback: list[str]):
    """해석된 이름 목록과 부분 일치 대체 이름을 하나의 OR 조건으로 묶습니다."""
    terms: list[Any] = []
    if resolved:
        terms.append(column.in_(resolved))
    terms.extend(column.contains(name) for name in fallback)
    if not terms:
        return None
    return or_(*terms)


# U+FFFD 는 SQL 에서 먼저 쳐내므로 배수는 작아도 됩니다.
LIVE_OVERFETCH_FACTOR = 3

# 집계 캐시 유효 시간. 원본 데이터는 야간 수집(02:00)에서만 바뀌므로 한 시간
# 묵은 값이어도 답변의 사실관계가 흔들리지 않습니다. 대시보드 계열이 24시간을
# 쓰지만 그쪽은 야간에 명시적으로 예열하는 반면 이 경로는 예열 대상이 아니라
# 짧게 잡습니다.
AGGREGATE_CACHE_TTL = 60 * 60


def _dataset_identity(db: Session | Engine | None) -> str:
    """캐시 키에 넣을 데이터셋 신원입니다.

    같은 SQL 이라도 다른 DB 에서 계산한 값이 섞이지 않도록 방언, 호스트, 포트,
    데이터베이스 이름을 넣습니다. 비밀번호와 사용자 이름은 넣지 않습니다.
    세션이나 엔진이 아닌 대역(시험용 가짜 세션)은 구분할 신원이 없으므로 빈
    문자열을 돌려줍니다.
    """
    if isinstance(db, Session):
        try:
            bind = db.get_bind()
        except Exception:
            return ""
    elif isinstance(db, Engine):
        bind = db
    else:
        return ""
    url = getattr(bind, "url", None)
    if url is None:
        url = getattr(getattr(bind, "engine", None), "url", None)
    if url is None:
        return ""
    return "|".join(
        (
            str(url.drivername),
            str(url.host or ""),
            "" if url.port is None else str(url.port),
            str(url.database or ""),
        )
    )


def _stmt_cache_key(prefix: str, stmt, db: Session | Engine | None = None) -> str:
    """리터럴을 채운 SQL 문자열과 데이터셋 신원의 해시를 키로 씁니다.

    조건이 하나라도 다르면 다른 키가 되므로, 필터가 다른 질의가 서로의 값을
    물려받는 사고가 없습니다. 데이터셋 신원을 함께 넣어 시험·시드 DB 의 집계가
    운영 Redis 의 같은 키를 채우지 않게 합니다.
    """
    compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
    identity = _dataset_identity(db)
    return prefix + hashlib.sha256(f"{identity}\x00{compiled}".encode()).hexdigest()


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
    key = _stmt_cache_key("rag:top:", stmt, db)
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
    key = _stmt_cache_key("rag:agg:", stmt, db)

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


@_measure_call("cached_rows")
def _cached_rows(db: Session, stmt, ttl: int = AGGREGATE_CACHE_TTL) -> list[tuple[Any, ...]]:
    """키별 여러 행을 돌려주는 일괄 집계 결과를 캐시합니다.

    _cached_aggregate 는 .one() 으로 단일 행만 다룹니다. GROUP BY 로 여러 키를
    한 번에 집계하는 경로는 이 함수로 같은 캐시 계층과 single-flight 를 씁니다.
    키 접두어가 달라 단일 행 캐시와 값이 섞이지 않습니다.
    """
    key = _stmt_cache_key("rag:rows:", stmt, db)

    cached = _timed_cache_get(key)
    if cached is not None:
        return [tuple(row) for row in cached]

    with _flight_lock(key):
        cached = _timed_cache_get(key)
        if cached is not None:
            return [tuple(row) for row in cached]

        rows = [tuple(_cacheable(value) for value in row) for row in db.execute(stmt).all()]
        cache.set(key, [[_cacheable(value) for value in row] for row in rows], ttl)
        return rows


def _group_limit(plan: RetrievalPlan) -> int:
    """축 표 행 상한을 안전한 범위로 정규화합니다."""
    raw_limit = (plan.filters or {}).get("group_limit")
    if raw_limit in (None, ""):
        return DEFAULT_GROUP_LIMIT
    try:
        value = int(str(raw_limit))
    except (TypeError, ValueError):
        return DEFAULT_GROUP_LIMIT
    return min(max(value, 1), MAX_GROUP_LIMIT)


def _axis_entry(
    label: str,
    key: str,
    *,
    announcement_count: int | None = None,
    bid_count: int | None = None,
    avg_rate: float | None = None,
    sample_count: int | None = None,
    award_amount: int | None = None,
) -> dict[str, Any]:
    """축 하나의 집계 결과를 기존 키와 겹치지 않는 모양으로 만듭니다."""
    return {
        "label": label,
        "key": key,
        "announcement_count": announcement_count,
        "bid_count": bid_count,
        "avg_rate": avg_rate,
        "sample_count": sample_count,
        "award_amount": award_amount,
    }


def _axis_rate(rate_value: Any, sample_count: int) -> float | None:
    """표본이 없으면 0.0 이 아니라 None 입니다. 없는 값이 값처럼 보이면 안 됩니다."""
    if not sample_count or rate_value is None:
        return None
    return float(round(float(rate_value), 4))


def _category_axis_breakdown(
    db: Session,
    metric: str,
    result_conditions: list,
    announcement_conditions: list,
    limit: int,
) -> tuple[list[dict[str, Any]], bool]:
    """분류 축을 집계합니다. 공고 건수는 공고 테이블, 낙찰 지표는 낙찰 테이블입니다."""
    if metric == "announcement_count":
        stmt = (
            select(BidAnnouncement.category, func.count())
            .where(*announcement_conditions)
            .group_by(BidAnnouncement.category)
        )
        rows = _cached_rows(db, stmt)
        entries = [
            _axis_entry(
                _category_label(row[0]),
                _normalize_text(str(row[0])),
                announcement_count=int(row[1] or 0),
            )
            for row in rows
            if row[0]
        ]
    elif metric == "award_amount":
        amount_expr = func.sum(BidResult.sucsf_bid_amt)
        amount_stmt = (
            select(BidResult.category, amount_expr)
            .where(*result_conditions)
            .group_by(BidResult.category)
            .with_hint(BidResult, RESULT_CATEGORY_AXIS_HINT, dialect_name="mysql")
        )
        entries = [
            _axis_entry(
                _category_label(row[0]),
                _normalize_text(str(row[0])),
                award_amount=int(row[1] or 0),
            )
            for row in _cached_rows(db, amount_stmt)
            if row[0]
        ]
    else:
        stmt = (
            select(
                BidResult.category,
                func.count(),
                func.avg(BidResult.sucsf_bid_rate),
                func.count(BidResult.sucsf_bid_rate),
            )
            .where(*result_conditions)
            .group_by(BidResult.category)
            .with_hint(BidResult, RESULT_CATEGORY_AXIS_HINT, dialect_name="mysql")
        )
        rows = _cached_rows(db, stmt)
        entries = []
        for row in rows:
            if not row[0]:
                continue
            sample_count = int(row[3] or 0)
            entries.append(
                _axis_entry(
                    _category_label(row[0]),
                    _normalize_text(str(row[0])),
                    bid_count=int(row[1] or 0),
                    avg_rate=_axis_rate(row[2], sample_count),
                    sample_count=sample_count,
                )
            )

    entries.sort(key=lambda item: float(item.get(metric) or 0), reverse=True)
    return entries[:limit], len(entries) > limit


def _institution_result_axis_breakdown(
    db: Session,
    metric: str,
    result_conditions: list,
    limit: int,
) -> tuple[list[dict[str, Any]], bool]:
    """기관별 낙찰 지표를 2단계로 집계합니다.

    한 문장으로 기관별 낙찰률을 집계하면 콜드 12.9~16.8초가 걸립니다. 기관명
    목록을 먼저 좁힌 뒤 그 목록으로 집계하면 같은 조건의 기관만 읽습니다.
    낙찰 금액 합계는 합계 기준으로 순위를 정해야 하므로 손상·빈 기관명을 먼저
    제외하고 한 번에 집계합니다.
    """
    if metric == "award_amount":
        amount_expr = func.sum(BidResult.sucsf_bid_amt)
        amount_stmt = (
            select(BidResult.dminstt_nm, amount_expr)
            .where(
                exclude_corrupted(BidResult.dminstt_nm),
                BidResult.dminstt_nm.is_not(None),
                BidResult.dminstt_nm != "",
                *result_conditions,
            )
            .group_by(BidResult.dminstt_nm)
            .order_by(amount_expr.desc(), BidResult.dminstt_nm.asc())
            .limit(limit)
        )
        entries: list[dict[str, Any]] = []
        for row in _cached_rows(db, amount_stmt):
            name = _normalize_text(str(row[0] or ""))
            if not name:
                continue
            entries.append(_axis_entry(name, name, award_amount=int(row[1] or 0)))
        return entries, len(entries) >= limit

    count_expr = func.count()
    top_stmt = (
        select(BidResult.dminstt_nm, count_expr)
        .where(*result_conditions, BidResult.dminstt_nm.is_not(None))
        .group_by(BidResult.dminstt_nm)
        .order_by(count_expr.desc(), BidResult.dminstt_nm.asc())
        .limit(limit)
    )
    names = [
        _normalize_text(str(row[0]))
        for row in _cached_rows(db, top_stmt)
        if row[0] and _normalize_text(str(row[0]))
    ]
    if not names:
        return [], False

    stats_stmt = (
        select(
            BidResult.dminstt_nm,
            func.count(),
            func.avg(BidResult.sucsf_bid_rate),
            func.count(BidResult.sucsf_bid_rate),
        )
        .where(*result_conditions, BidResult.dminstt_nm.in_(names))
        .group_by(BidResult.dminstt_nm)
    )
    stats: dict[str, tuple[int, Any, int]] = {}
    for row in _cached_rows(db, stats_stmt):
        if row[0] is None:
            continue
        stats[_normalize_text(str(row[0]))] = (
            int(row[1] or 0),
            row[2],
            int(row[3] or 0),
        )

    entries = []
    for name in names:
        bid_count, rate_value, sample_count = stats.get(name, (0, None, 0))
        entries.append(
            _axis_entry(
                name,
                name,
                bid_count=bid_count,
                avg_rate=_axis_rate(rate_value, sample_count),
                sample_count=sample_count,
            )
        )
    return entries, len(names) >= limit


def _winner_axis_breakdown(
    db: Session,
    metric: str,
    result_conditions: list,
    limit: int,
) -> tuple[list[dict[str, Any]], bool]:
    """업체별 낙찰 지표를 실시간으로 집계합니다.

    스냅샷은 업체 순위를 상위 5개까지만 보관하므로 "상위 10개" 요청을 조용히
    자를 수 있고, 기간 조건이 붙으면 애초에 쓸 수 없습니다. 업체 축은 항상
    실시간 SQL 로 집계하고, 손상값과 빈 업체명을 먼저 제외합니다. 평균
    낙찰률은 값이 없는 행을 평균에서 빼고 건수 하한을 두지 않으며, 건수와
    낙찰률 모두 내림차순, 업체명 오름차순으로 정렬해 동점 순서를 고정합니다.
    """
    count_expr = func.count()
    rate_expr = func.avg(BidResult.sucsf_bid_rate)
    sample_expr = func.count(BidResult.sucsf_bid_rate)
    amount_expr = func.sum(BidResult.sucsf_bid_amt)
    conditions: list[Any] = [
        exclude_corrupted(BidResult.bidwinnr_nm),
        BidResult.bidwinnr_nm != "",
        *result_conditions,
    ]
    value_columns: list[Any] = [count_expr, rate_expr, sample_expr]
    if metric == "avg_rate":
        conditions.append(BidResult.sucsf_bid_rate.is_not(None))
        order_columns: list[Any] = [rate_expr.desc(), BidResult.bidwinnr_nm.asc()]
    elif metric == "award_amount":
        value_columns.append(amount_expr)
        order_columns = [amount_expr.desc(), BidResult.bidwinnr_nm.asc()]
    else:
        order_columns = [count_expr.desc(), BidResult.bidwinnr_nm.asc()]
    stmt = (
        select(BidResult.bidwinnr_nm, *value_columns)
        .where(*conditions)
        .group_by(BidResult.bidwinnr_nm)
        .order_by(*order_columns)
        .limit(limit)
    )
    entries: list[dict[str, Any]] = []
    for row in _cached_rows(db, stmt):
        name = _normalize_text(str(row[0] or ""))
        if not name:
            continue
        sample_count = int(row[3] or 0)
        entries.append(
            _axis_entry(
                name,
                name,
                bid_count=int(row[1] or 0),
                avg_rate=_axis_rate(row[2], sample_count),
                sample_count=sample_count,
                award_amount=int(row[4] or 0) if metric == "award_amount" else None,
            )
        )
    return entries, len(entries) >= limit


def _region_axis_breakdown(
    db: Session,
    metric: str,
    result_conditions: list,
    announcement_conditions: list,
    limit: int,
) -> tuple[list[dict[str, Any]], bool]:
    """지역 축을 집계합니다. 단축형과 정식 명칭을 함께 라벨로 묶습니다."""
    hint_target: Any = None
    hint_sql = ""
    if metric == "announcement_count":
        column = BidAnnouncement.dminstt_nm
        conditions = announcement_conditions
        value_columns: list[Any] = [func.count()]
    elif metric == "award_amount":
        column = BidResult.dminstt_nm
        conditions = result_conditions
        value_columns = [func.sum(BidResult.sucsf_bid_amt)]
    else:
        column = BidResult.dminstt_nm
        conditions = result_conditions
        value_columns = [
            func.count(),
            func.avg(BidResult.sucsf_bid_rate),
            func.count(BidResult.sucsf_bid_rate),
        ]
    if metric == "announcement_count":
        hint_target = BidAnnouncement
        hint_sql = ANNOUNCEMENT_REGION_AXIS_HINT

    region_expr = case(
        *[
            (column.contains(alias), label)
            for label, aliases in REGION_ALIASES.items()
            for alias in aliases
        ],
        else_=None,
    )
    stmt = (
        select(region_expr.label("region"), *value_columns)
        .where(column.is_not(None), *conditions)
        .group_by(region_expr)
    )
    if hint_target is not None and hint_sql:
        stmt = stmt.with_hint(hint_target, hint_sql, dialect_name="mysql")
    rows = _cached_rows(db, stmt)

    entries: list[dict[str, Any]] = []
    for row in rows:
        if not row[0]:
            continue
        if metric == "announcement_count":
            entries.append(
                _axis_entry(
                    str(row[0]),
                    str(row[0]),
                    announcement_count=int(row[1] or 0),
                )
            )
            continue
        if metric == "award_amount":
            entries.append(
                _axis_entry(
                    str(row[0]),
                    str(row[0]),
                    award_amount=int(row[1] or 0),
                )
            )
            continue
        sample_count = int(row[3] or 0)
        entries.append(
            _axis_entry(
                str(row[0]),
                str(row[0]),
                bid_count=int(row[1] or 0),
                avg_rate=_axis_rate(row[2], sample_count),
                sample_count=sample_count,
            )
        )

    entries.sort(key=lambda item: float(item.get(metric) or 0), reverse=True)
    return entries[:limit], len(entries) > limit


def _build_axis_breakdown(
    db: Session,
    *,
    group_by: str,
    metric: str,
    result_conditions: list,
    announcement_conditions: list,
    limit: int,
) -> tuple[list[dict[str, Any]], bool] | None:
    """축 집계를 실행합니다.

    기관별 공고 건수는 기존 institution_ranking 결과를 그대로 쓰므로 여기서
    None 을 돌려 호출부가 추가 SQL 없이 축 표를 만들게 합니다.
    """
    if group_by == "category":
        return _category_axis_breakdown(
            db, metric, result_conditions, announcement_conditions, limit
        )
    if group_by == "institution":
        if metric == "announcement_count":
            return None
        return _institution_result_axis_breakdown(db, metric, result_conditions, limit)
    if group_by == "region":
        return _region_axis_breakdown(db, metric, result_conditions, announcement_conditions, limit)
    if group_by == "winner":
        return _winner_axis_breakdown(db, metric, result_conditions, limit)
    return None


def _comparison_region_names(filters: dict[str, Any]) -> list[str]:
    """지역 비교 대상 목록을 정규화해 질의 순서를 유지합니다."""
    raw_names = filters.get("region_names")
    if not isinstance(raw_names, list):
        return []
    names: list[str] = []
    for item in raw_names:
        name = _normalize_text(str(item))
        if name in REGION_ALIASES and name not in names:
            names.append(name)
    return names


def _comparison_condition(column, spec: dict[str, Any]) -> Any:
    """대상 하나의 기관명 조건을 만듭니다.

    지역은 단축형·정식 명칭을 모두 부분 일치로 묶습니다. 정확 기관명은 해석된
    이름이 있으면 등호 목록으로, 해석 상한을 넘어 이름 목록이 없으면(None)
    후보를 버리지 않고 부분 일치로 폴백합니다.
    """
    if spec["kind"] == "region":
        return _region_condition(column, spec["aliases"])
    matched_names = spec.get("names")
    if matched_names:
        return column.in_(matched_names)
    return column.contains(str(spec["name"]))


def _comparison_scope_plan(plan: RetrievalPlan) -> RetrievalPlan:
    """비교 범위는 대상 specs 가 정하므로 단일 institution_name 을 제외합니다.

    bid_query_tool 은 플래너 파라미터(institution_name='부산')를 필터에 더합니다.
    그 값을 그대로 쓰면 두 번째 지역(대구)이 사라지므로 비교 경로에서만 뺍니다.
    """
    filters = dict(plan.filters or {})
    filters.pop("institution_name", None)
    return plan.model_copy(update={"filters": filters})


def _comparison_breakdown(
    db: Session,
    plan: RetrievalPlan,
    specs: list[dict[str, Any]],
    *,
    dimension: str,
) -> list[dict[str, Any]]:
    """대상별 공고 건수와 낙찰 지표를 테이블 두 개로 집계합니다.

    한 문장에 대상별 라벨을 CASE 로 붙여 GROUP BY 하므로 대상 수가 늘어도
    문장 수는 늘지 않습니다. 지역 공고 집계에는 기관명 커버링 인덱스 힌트를
    하나만 붙이고, 날짜 인덱스 힌트는 쓰지 않습니다.
    """
    scope_plan = _comparison_scope_plan(plan)
    announcement_expr = case(
        *[
            (_comparison_condition(BidAnnouncement.dminstt_nm, spec), spec["label"])
            for spec in specs
        ],
        else_=None,
    )
    announcement_stmt = (
        select(announcement_expr, func.count())
        .where(BidAnnouncement.dminstt_nm.is_not(None), *_announcement_conditions(scope_plan))
        .group_by(announcement_expr)
    )
    if dimension == "region":
        announcement_stmt = announcement_stmt.with_hint(
            BidAnnouncement, ANNOUNCEMENT_REGION_AXIS_HINT, dialect_name="mysql"
        )
    announcement_counts: dict[str, int] = {}
    for label, count in _cached_rows(db, announcement_stmt):
        if label:
            announcement_counts[str(label)] = int(count or 0)

    result_expr = case(
        *[(_comparison_condition(BidResult.dminstt_nm, spec), spec["label"]) for spec in specs],
        else_=None,
    )
    result_stmt = (
        select(
            result_expr,
            func.count(),
            func.avg(BidResult.sucsf_bid_rate),
            func.count(BidResult.sucsf_bid_rate),
        )
        .where(BidResult.dminstt_nm.is_not(None), *_result_conditions(scope_plan))
        .group_by(result_expr)
    )
    result_stats: dict[str, tuple[int, Any, int]] = {}
    for label, count, rate_value, sample_count in _cached_rows(db, result_stmt):
        if label:
            result_stats[str(label)] = (int(count or 0), rate_value, int(sample_count or 0))

    entries: list[dict[str, Any]] = []
    for spec in specs:
        label = str(spec["label"])
        bid_count, rate_value, sample_count = result_stats.get(label, (0, None, 0))
        entries.append(
            _axis_entry(
                label,
                label,
                announcement_count=announcement_counts.get(label, 0),
                bid_count=bid_count,
                avg_rate=_axis_rate(rate_value, sample_count),
                sample_count=sample_count,
            )
        )
    return entries


def _comparison_result(
    plan: RetrievalPlan,
    entries: list[dict[str, Any]],
    *,
    dimension: str,
) -> dict[str, Any]:
    """비교 응답을 기존 summary 키를 유지한 채 가법적으로 만듭니다."""
    filters = plan.filters or {}
    metric = _normalize_text(str(filters.get("metric") or "")) or "announcement_count"
    response_filters = dict(filters)
    if response_filters.get("region_names"):
        response_filters.pop("institution_name", None)
    if response_filters.get("category"):
        response_filters["category_label"] = _category_label(str(response_filters["category"]))

    sample_total = sum(int(item.get("sample_count") or 0) for item in entries)
    weighted_rate = sum(
        float(item.get("avg_rate") or 0.0) * int(item.get("sample_count") or 0) for item in entries
    )
    hints: list[str] = []
    if dimension == "region":
        hints.append(
            "지역 구분은 기관명 부분 일치 기준이라 지역 합계가 전체 건수와 일치하지 않을 수 있습니다."
        )

    summary: dict[str, Any] = {
        "total_bids": sum(int(item.get("bid_count") or 0) for item in entries),
        "announcement_count": sum(int(item.get("announcement_count") or 0) for item in entries),
        "average_winning_rate": (
            float(round(weighted_rate / sample_total, 4)) if sample_total else 0.0
        ),
        "total_winning_amount": 0.0,
        "top_winners": [],
        "top_institutions": [],
        "top_announcements": [],
        "sample_announcements": [],
        "recent_results": [],
        "latest_available_result_at": None,
        "time_series": [],
        "comparison": entries,
        "comparison_meta": {
            "dimension": dimension,
            "metric": metric,
            "targets": [str(item.get("label") or "") for item in entries],
        },
    }
    return {
        "filters": response_filters,
        "summary": summary,
        "insufficiency_hints": hints,
    }


def _period_category_comparison_breakdown(
    db: Session,
    plan: RetrievalPlan,
    targets: list[dict[str, Any]],
    *,
    dimension: str,
) -> list[dict[str, Any]]:
    """기간·분류 비교의 대상별 지표를 실시간으로 집계합니다.

    기간 비교는 대상마다 다른 공고일·개찰일 창을 쓰고, 분류 비교는 대상마다
    분야 코드를 씁니다. 스냅샷은 기간·분류 조합을 미리 갖고 있지 않으므로
    쓰지 않습니다.
    """
    filters = plan.filters or {}
    shared_category = _normalize_text(str(filters.get("category") or ""))
    shared_from, shared_to = _resolve_window(filters)
    # "한국전력공사 작년 대비 올해", "부산 작년 대비 올해" 처럼 기관·지역 하나가
    # 기간 비교와 섞이면 그 범위를 두 대상 모두에 공통으로 겁니다. 이 조건을
    # 빠뜨리면 대상별 값이 전체 기관 기준으로 조용히 넓어집니다.
    shared_institution = _normalize_text(str(filters.get("institution_name") or ""))
    shared_aliases = _institution_aliases(filters)
    shared_scope = bool(shared_institution or shared_aliases)
    announcement_scope_names = (
        _resolve_institution_scope_names(
            db, BidAnnouncement.dminstt_nm, shared_institution, shared_aliases
        )
        if shared_scope
        else None
    )
    result_scope_names = (
        _resolve_institution_scope_names(
            db, BidResult.dminstt_nm, shared_institution, shared_aliases
        )
        if shared_scope
        else None
    )

    def _shared_scope_condition(column, names: list[str] | None):
        """공통 기관·지역 조건을 만듭니다. 해석 결과가 없으면 0건으로 좁힙니다."""
        if not shared_scope:
            return None
        if names is None:
            terms = [term for term in (shared_institution, *shared_aliases) if term]
            return or_(*[column.contains(term) for term in terms])
        return column.in_(names)

    announcement_scope_condition = _shared_scope_condition(
        BidAnnouncement.dminstt_nm, announcement_scope_names
    )
    result_scope_condition = _shared_scope_condition(BidResult.dminstt_nm, result_scope_names)

    specs: list[dict[str, Any]] = []
    for item in targets:
        key = _normalize_text(str(item.get("key") or ""))
        label = _normalize_text(str(item.get("label") or "")) or key
        spec: dict[str, Any] = {"key": key, "label": label}
        if dimension == "time":
            spec["date_from"] = _parse_date(str(item.get("date_from") or ""), "date_from")
            spec["date_to"] = _parse_date(str(item.get("date_to") or ""), "date_to")
        specs.append(spec)

    def _announcement_conditions_for(spec: dict[str, Any]) -> list:
        conditions = []
        if dimension == "time":
            if spec.get("date_from"):
                conditions.append(BidAnnouncement.bid_ntce_dt >= spec["date_from"])
            if spec.get("date_to"):
                conditions.append(BidAnnouncement.bid_ntce_dt < spec["date_to"] + timedelta(days=1))
            if shared_category:
                conditions.append(BidAnnouncement.category == shared_category)
        else:
            conditions.append(BidAnnouncement.category == spec["key"])
            if shared_from:
                conditions.append(BidAnnouncement.bid_ntce_dt >= shared_from)
            if shared_to:
                conditions.append(BidAnnouncement.bid_ntce_dt <= shared_to + timedelta(days=1))
        if announcement_scope_condition is not None:
            conditions.append(announcement_scope_condition)
        return conditions

    def _result_conditions_for(spec: dict[str, Any]) -> list:
        conditions = []
        if dimension == "time":
            if spec.get("date_from"):
                conditions.append(BidResult.rl_openg_dt >= spec["date_from"])
            if spec.get("date_to"):
                conditions.append(BidResult.rl_openg_dt < spec["date_to"] + timedelta(days=1))
            if shared_category:
                conditions.append(BidResult.category == shared_category)
        else:
            conditions.append(BidResult.category == spec["key"])
            if shared_from:
                conditions.append(BidResult.rl_openg_dt >= shared_from)
            if shared_to:
                conditions.append(BidResult.rl_openg_dt <= shared_to + timedelta(days=1))
        if result_scope_condition is not None:
            conditions.append(result_scope_condition)
        return conditions

    announcement_conditions = [_announcement_conditions_for(spec) for spec in specs]
    announcement_expr = case(
        *[
            (and_(*conditions), spec["key"])
            for spec, conditions in zip(specs, announcement_conditions, strict=True)
        ],
        else_=None,
    )
    announcement_stmt = (
        select(announcement_expr, func.count())
        .where(or_(*[and_(*conditions) for conditions in announcement_conditions]))
        .group_by(announcement_expr)
    )
    announcement_counts: dict[str, int] = {}
    for key, count in _cached_rows(db, announcement_stmt):
        if key:
            announcement_counts[str(key)] = int(count or 0)

    result_conditions = [_result_conditions_for(spec) for spec in specs]
    result_expr = case(
        *[
            (and_(*conditions), spec["key"])
            for spec, conditions in zip(specs, result_conditions, strict=True)
        ],
        else_=None,
    )
    result_stmt = (
        select(
            result_expr,
            func.count(),
            func.avg(BidResult.sucsf_bid_rate),
            func.count(BidResult.sucsf_bid_rate),
        )
        .where(or_(*[and_(*conditions) for conditions in result_conditions]))
        .group_by(result_expr)
    )
    result_stats: dict[str, tuple[int, Any, int]] = {}
    for key, count, rate_value, sample_count in _cached_rows(db, result_stmt):
        if key:
            result_stats[str(key)] = (int(count or 0), rate_value, int(sample_count or 0))

    entries: list[dict[str, Any]] = []
    for spec in specs:
        key = str(spec["key"])
        bid_count, rate_value, sample_count = result_stats.get(key, (0, None, 0))
        entries.append(
            _axis_entry(
                str(spec["label"]),
                key,
                announcement_count=announcement_counts.get(key, 0),
                bid_count=bid_count,
                avg_rate=_axis_rate(rate_value, sample_count),
                sample_count=sample_count,
            )
        )
    return entries


def _period_category_comparison_result(
    db: Session,
    plan: RetrievalPlan,
    targets: list[dict[str, Any]],
    *,
    dimension: str,
) -> dict[str, Any]:
    """기간·분류 비교 응답을 기존 comparison 키 모양으로 만듭니다."""
    filters = dict(plan.filters or {})
    shared_institution = _normalize_text(str(filters.get("institution_name") or ""))
    shared_aliases = _institution_aliases(filters)
    if shared_institution or shared_aliases:
        # 기관명을 하나도 확정하지 못하면 전체 기관 통계로 넓히지 않고
        # 기존 미해석 기관 안내를 그대로 냅니다.
        announcement_names = _resolve_institution_scope_names(
            db, BidAnnouncement.dminstt_nm, shared_institution, shared_aliases
        )
        result_names = _resolve_institution_scope_names(
            db, BidResult.dminstt_nm, shared_institution, shared_aliases
        )
        if announcement_names == [] and result_names == []:
            return _empty_result(
                plan,
                "요청한 기관명을 데이터에서 확인하지 못해 비교 대상을 확정하지 못했습니다. "
                "기관명을 다시 확인해 주세요.",
            )
    comparison_plan = plan
    if dimension == "category" and (plan.filters or {}).get("category"):
        # bid_query_tool 은 플래너가 고른 분야 하나를 파라미터로 다시 더합니다.
        # 분류 비교에서는 두 분야가 대상이므로 그 단일 조건을 응답 필터에서 뺍니다.
        filters.pop("category", None)
        comparison_plan = plan.model_copy(update={"filters": filters})
    result = _comparison_result(
        comparison_plan,
        _period_category_comparison_breakdown(db, comparison_plan, targets, dimension=dimension),
        dimension=dimension,
    )
    if dimension == "time":
        periods: list[dict[str, Any]] = []
        for item in targets:
            start = _parse_date(str(item.get("date_from") or ""), "date_from")
            end = _parse_date(str(item.get("date_to") or ""), "date_to")
            days = (end.date() - start.date()).days + 1 if start and end else 0
            periods.append(
                {
                    "key": str(item.get("key") or ""),
                    "label": str(item.get("label") or ""),
                    "date_from": str(item.get("date_from") or ""),
                    "date_to": str(item.get("date_to") or ""),
                    "ongoing": bool(item.get("ongoing")),
                    "days": days,
                }
            )
        result["summary"]["comparison_meta"]["periods"] = periods
    comparison_meta = result["summary"]["comparison_meta"]
    if shared_institution:
        comparison_meta["scope"] = {"institution_name": shared_institution}
    shared_category = _normalize_text(str(filters.get("category") or ""))
    if shared_category:
        comparison_meta.setdefault("scope", {})["category"] = shared_category
    return result


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


def _fetch_recent_results(
    db: Session,
    conditions: list,
    limit: int,
    *,
    filters: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """조건에 맞는 최신 낙찰 결과를 손상값 제외 후 최대 limit 건 조회합니다."""
    if not limit:
        return []
    result_rows = (
        db.execute(
            select(BidResult)
            .where(*conditions)
            .order_by(*_result_order_by(filters or {}))
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


def _recent_result_order_key(result: BidResult) -> tuple[bool, float, int]:
    """_fetch_recent_results 의 정렬 기준(개찰일 내림차순, NULL 뒤, id 내림차순)을 파이썬으로 옮깁니다."""
    opened_at = result.rl_openg_dt
    if opened_at is None:
        return (True, 0.0, -(result.id or 0))
    return (False, -opened_at.timestamp(), -(result.id or 0))


def _fetch_recent_results_batch(
    db: Session, conditions: list, names: list[str], limit: int
) -> dict[str, list[BidResult]]:
    """기관명 목록 전체의 최신 낙찰 결과를 한 번의 질의로 모아 기관명별로 나눕니다.

    기관마다 _fetch_recent_results 를 부르면 기관 수만큼 질의가 늘어납니다. 윈도
    함수로 기관명별 상위 (limit * LIVE_OVERFETCH_FACTOR) 건을 한 질의로 받아
    호출부가 기관별로 합쳐 상한을 적용합니다. 기관명별 상한 건수가 같으므로
    합집합 상위 구간도 기존과 동일합니다.
    """
    if not limit or not names:
        return {}

    ranked = (
        select(
            BidResult.id.label("id"),
            func.row_number()
            .over(
                partition_by=BidResult.dminstt_nm,
                order_by=(
                    BidResult.rl_openg_dt.is_(None),
                    BidResult.rl_openg_dt.desc(),
                    BidResult.id.desc(),
                ),
            )
            .label("recent_rank"),
        )
        .where(*conditions, BidResult.dminstt_nm.in_(names))
        .subquery()
    )
    rows = (
        db.execute(
            select(BidResult)
            .join(ranked, ranked.c.id == BidResult.id)
            .where(ranked.c.recent_rank <= limit * LIVE_OVERFETCH_FACTOR)
        )
        .scalars()
        .all()
    )

    grouped: dict[str, list[BidResult]] = {}
    for result in rows:
        if result.dminstt_nm is None:
            continue
        grouped.setdefault(result.dminstt_nm, []).append(result)
    return grouped


def _select_recent_results(candidates: list[BidResult], limit: int) -> list[dict[str, Any]]:
    """기관별 후보 행을 정렬해 손상값을 제외하고 최대 limit 건을 고릅니다.

    기존 _fetch_recent_results 가 DB 에서 상위 (limit * LIVE_OVERFETCH_FACTOR)
    건을 받아 자르던 것과 같은 상한을 파이썬에서 적용합니다.
    """
    if not limit or not candidates:
        return []
    ordered = sorted(candidates, key=_recent_result_order_key)[: limit * LIVE_OVERFETCH_FACTOR]
    recent: list[dict[str, Any]] = []
    for result in ordered:
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


SAMPLE_ANNOUNCEMENT_OVERFETCH_LIMIT = 60


def _fetch_sample_announcements(
    db: Session,
    conditions: list,
    limit: int = 3,
    *,
    detailed: bool = False,
    filters: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """표본 공고 목록을 조회하고 화면 표시용 대체 텍스트를 적용합니다.

    공고 목록 질의는 detailed 로 불러 공고일·마감일 같은 표 열을 함께 담습니다.
    detailed 가 아니면 기존 표본 3건과 키 구성이 그대로 유지됩니다.
    정렬 표지가 없으면 기존 공고일 내림차순을 유지합니다.

    같은 공고번호의 정정·안내 행이 목록 개수를 잡아먹지 않도록 공고번호마다
    첫 등장 행만 남깁니다. 정렬 순서를 그대로 따르므로 기본 공고일 내림차순에서는
    가장 최신 행이 남습니다. 중복 행을 건너뛸 여유를 두려고 limit 보다 넉넉히
    조회하되 상한을 두고, 그래도 모자라면 있는 만큼만 돌려줍니다.
    """
    columns: list[Any] = [
        BidAnnouncement.bid_ntce_no,
        BidAnnouncement.bid_ntce_nm,
        BidAnnouncement.dminstt_nm,
    ]
    if detailed:
        columns.extend(
            [
                BidAnnouncement.bid_ntce_dt,
                BidAnnouncement.category,
                BidAnnouncement.presmpt_prce,
                BidAnnouncement.bid_clse_dt,
                BidAnnouncement.base_amount,
            ]
        )
    rows = db.execute(
        select(*columns)
        .where(*conditions)
        .order_by(*_announcement_order_by(filters or {}))
        .limit(min(limit * LIVE_OVERFETCH_FACTOR, SAMPLE_ANNOUNCEMENT_OVERFETCH_LIMIT))
    ).all()
    samples: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        if len(samples) >= limit:
            break
        if row[0] in seen:
            continue
        seen.add(row[0])
        sample: dict[str, Any] = {
            "bid_ntce_no": row[0],
            # 표본은 순위와 달리 건너뛸 수 없으므로 화면과 같은 안내 문구로 대체합니다.
            "bid_ntce_nm": clean_display_text(row[1], CORRUPTED_TEXT_FALLBACKS["title"]),
            "dminstt_nm": clean_display_text(row[2], CORRUPTED_TEXT_FALLBACKS["agency"]),
        }
        if detailed:
            sample.update(
                {
                    "bid_ntce_dt": row[3].isoformat(sep=" ") if row[3] is not None else None,
                    "category": row[4],
                    "category_label": _category_label(row[4]),
                    "presmpt_prce": int(row[5]) if row[5] is not None else None,
                    "bid_clse_dt": row[6].isoformat(sep=" ") if row[6] is not None else None,
                    "base_amount": int(row[7]) if row[7] is not None else None,
                }
            )
        samples.append(sample)
    return samples


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


def _quarter_group_expressions(db: Session, column) -> tuple[Any, Any]:
    """날짜 컬럼을 (연도, 분기) 정수로 묶는 방언별 GROUP BY 식을 만듭니다.

    SQLite 는 YEAR()/QUARTER() 가 없어 strftime 결과를 정수로 캐스팅하고 월을
    분기로 나눕니다. MySQL 은 YEAR()/MONTH() 를 씁니다. 분기 판정은 두 방언이
    같은 CASE 식을 공유합니다.
    """
    year_expr: Any
    month_expr: Any
    if db.get_bind().dialect.name == "sqlite":
        year_expr = func.strftime("%Y", column).cast(Integer)
        month_expr = func.strftime("%m", column).cast(Integer)
    else:
        year_expr = func.year(column)
        month_expr = func.month(column)
    quarter_expr = case(
        (month_expr <= 3, 1),
        (month_expr <= 6, 2),
        (month_expr <= 9, 3),
        else_=4,
    )
    return year_expr, quarter_expr


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

        series: list[dict[str, Any]] = []
        if not quarters:
            return series

        # 분기마다 집계 질의를 따로 내면 질의 수가 분기 수에 비례합니다. 대상 분기가
        # 연속이므로 전체 구간을 한 번에 GROUP BY (연도, 분기) 로 집계하고 파이썬에서
        # 분기별로 나눠 담습니다. 질의 수는 분기 수와 무관하게 낙찰·공고 각 1회입니다.
        range_start, _ = _quarter_boundaries(*quarters[0])
        _, range_end = _quarter_boundaries(*quarters[-1])

        res_year, res_quarter = _quarter_group_expressions(db, BidResult.rl_openg_dt)
        ann_year, ann_quarter = _quarter_group_expressions(db, BidAnnouncement.bid_ntce_dt)

        res_stmt = (
            select(
                res_year.label("year"),
                res_quarter.label("quarter"),
                func.count(BidResult.id),
                func.avg(BidResult.sucsf_bid_rate),
            )
            .where(
                BidResult.rl_openg_dt >= range_start,
                BidResult.rl_openg_dt < range_end,
                *base_res_conditions,
            )
            .group_by(res_year, res_quarter)
        )
        ann_stmt = (
            select(
                ann_year.label("year"),
                ann_quarter.label("quarter"),
                func.count(BidAnnouncement.id),
            )
            .where(
                BidAnnouncement.bid_ntce_dt >= range_start,
                BidAnnouncement.bid_ntce_dt < range_end,
                *base_ann_conditions,
            )
            .group_by(ann_year, ann_quarter)
        )

        res_by_quarter = {
            (int(row[0]), int(row[1])): (int(row[2] or 0), row[3])
            for row in _cached_rows(db, res_stmt)
            if row[0] is not None and row[1] is not None
        }
        ann_by_quarter = {
            (int(row[0]), int(row[1])): int(row[2] or 0)
            for row in _cached_rows(db, ann_stmt)
            if row[0] is not None and row[1] is not None
        }

        for year, quarter in quarters:
            bid_count, avg_value = res_by_quarter.get((year, quarter), (0, None))
            avg_rate = float(round(float(avg_value or 0), 4)) if avg_value is not None else 0.0
            ann_count = ann_by_quarter.get((year, quarter), 0)

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
    filters = dict(plan.filters or {})
    summary: dict[str, Any] = {
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
    }
    group_by = _normalize_text(str(filters.get("group_by") or ""))
    if group_by:
        summary["axis_breakdown"] = []
        summary["aggregate_meta"] = {
            "group_by": group_by,
            "metric": _normalize_text(str(filters.get("metric") or "")) or "announcement_count",
            "limit": _group_limit(plan),
            "truncated": False,
            "dropped": 0,
            "window": {
                "date_from": filters.get("date_from"),
                "date_to": filters.get("date_to"),
            },
        }
    # 공고번호 단건은 미발견을 전체 통계로 폴백하지 않습니다. 응답 단계가
    # "해당 공고번호 없음" 을 낼 수 있도록 키만 가법적으로 표시합니다.
    if filters.get("bid_ntce_no"):
        summary["bid_detail"] = None
    return {
        "filters": filters,
        "summary": summary,
        "insufficiency_hints": [hint],
        "query_skipped": True,
    }


def _bid_detail_result(db: Session, plan: RetrievalPlan, bid_ntce_no: str) -> dict[str, Any]:
    """공고번호 단건 조회 결과를 기존 summary 키를 유지한 채 만듭니다.

    공고와 낙찰을 각각 유일 인덱스 범위로 한 번씩 읽고, 낙찰 행이 있으면 그
    행의 분류와 같은 기간의 평균을 한 번 계산합니다. 어느 쪽도 없으면 전체
    통계로 넓히지 않고 해당 공고번호가 없다는 빈 결과를 냅니다.
    """
    filters = plan.filters or {}
    announcements = _fetch_sample_announcements(
        db,
        _announcement_conditions(plan, bid_ntce_no=bid_ntce_no),
        limit=1,
        detailed=True,
        filters=filters,
    )
    results = _fetch_recent_results(
        db,
        _result_conditions(plan, bid_ntce_no=bid_ntce_no),
        1,
        filters=filters,
    )
    announcement = announcements[0] if announcements else None
    result = results[0] if results else None

    if announcement is None and result is None:
        return _empty_result(
            plan,
            f"공고번호 {bid_ntce_no} 은(는) 수집 데이터에서 확인할 수 없습니다.",
        )

    comparison: dict[str, Any] | None = None
    if result is not None:
        category = _normalize_text(str(filters.get("category") or result.get("category") or ""))
        date_from, date_to = _resolve_window(filters)
        baseline_conditions = []
        if date_from:
            baseline_conditions.append(BidResult.rl_openg_dt >= date_from)
        if date_to:
            baseline_conditions.append(BidResult.rl_openg_dt <= date_to + timedelta(days=1))
        if category:
            baseline_conditions.append(BidResult.category == category)
        baseline_count, baseline_rate, baseline_samples = _cached_aggregate(
            db,
            select(
                func.count(BidResult.id),
                func.avg(BidResult.sucsf_bid_rate),
                func.count(BidResult.sucsf_bid_rate),
            ).where(*baseline_conditions),
        )
        comparison = {
            "category": category,
            "category_label": _category_label(category),
            "average_winning_rate": (
                round(float(baseline_rate), 4) if baseline_rate is not None else None
            ),
            "sample_count": int(baseline_samples or 0),
            "bid_count": int(baseline_count or 0),
            "date_from": filters.get("date_from"),
            "date_to": filters.get("date_to"),
        }

    response_filters = dict(filters)
    if response_filters.get("category"):
        response_filters["category_label"] = _category_label(str(response_filters["category"]))

    summary: dict[str, Any] = {
        "total_bids": 1 if result else 0,
        "announcement_count": 1 if announcement else 0,
        "average_winning_rate": (
            round(float(result.get("sucsf_bid_rate") or 0), 4) if result else 0.0
        ),
        "total_winning_amount": float(result.get("sucsf_bid_amt") or 0) if result else 0.0,
        "top_winners": [],
        "top_institutions": [],
        "top_announcements": [],
        "sample_announcements": announcements,
        "recent_results": results,
        "latest_available_result_at": None,
        "time_series": [],
        "bid_detail": {
            "bid_ntce_no": bid_ntce_no,
            "announcement": announcement,
            "result": result,
            "comparison": comparison,
        },
    }
    return {
        "filters": response_filters,
        "summary": summary,
        "insufficiency_hints": [],
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
    filters = plan.filters or {}
    region_names = _comparison_region_names(filters)
    if region_names:
        region_specs = [
            {"kind": "region", "label": name, "aliases": REGION_ALIASES[name]}
            for name in region_names
        ]
        return _comparison_result(
            plan,
            _comparison_breakdown(db, plan, region_specs, dimension="region"),
            dimension="region",
        )

    period_category_dimension = _normalize_text(str(filters.get("comparison_dimension") or ""))
    period_category_targets = filters.get("comparison_targets")
    if (
        period_category_dimension in ("time", "category")
        and isinstance(period_category_targets, list)
        and len(period_category_targets) == 2
    ):
        return _period_category_comparison_result(
            db,
            plan,
            period_category_targets,
            dimension=period_category_dimension,
        )

    comparison_metric = _normalize_text(str(filters.get("metric") or ""))
    raw_institution_names = filters.get("institution_names")
    multi_list_names: list[str] = []
    if (
        raw_institution_names
        and isinstance(raw_institution_names, list)
        and (_announcement_limit(plan) or _result_limit(plan))
    ):
        # 기관 둘 이상을 지목한 목록 질의는 비교 요약 분기로 보내지 않고 아래
        # 목록 경로에서 IN 조건으로 조회합니다.
        multi_list_names = [
            name for name in (_normalize_text(str(item)) for item in raw_institution_names) if name
        ]
    if raw_institution_names and isinstance(raw_institution_names, list) and not multi_list_names:
        target_names = raw_institution_names[:5]
        requested_targets: list[tuple[str, list[str] | None]] = []
        targets: list[tuple[str, list[str] | None]] = []
        for name in target_names:
            norm_name = _normalize_text(name)
            if not norm_name:
                continue
            matched = _resolve_institution_names(db, BidResult.dminstt_nm, norm_name)
            requested_targets.append((norm_name, matched))
            # 해석 상한 초과(None)는 버리지 않고 contains 폴백으로 범위를 정합니다.
            # 이 후보를 버리면 기관 조건이 사라져 전체 통계로 조용히 넓어집니다.
            if matched is None or matched:
                targets.append((norm_name, matched))
        unresolved_names = [name for name, matched in requested_targets if matched == []]

        if not targets:
            return _empty_result(
                plan,
                "요청한 기관명을 데이터에서 확인하지 못해 비교 대상을 확정하지 못했습니다. "
                "기관명을 다시 확인해 주세요.",
            )

        date_from, date_to = _resolve_window(filters)
        category = _normalize_text(str(filters.get("category") or ""))

        # 기관마다 집계와 최신 결과 질의를 따로 내면 질의 수가 기관 수에
        # 비례합니다. 공통 조건은 그대로 두고 기관명만 IN 으로 합쳐 GROUP BY
        # 한 번과, 윈도 함수로 기관명별 최신 결과를 뽑는 한 번으로 줄입니다.
        common_conditions = []
        if date_from:
            common_conditions.append(BidResult.rl_openg_dt >= date_from)
        if date_to:
            common_conditions.append(BidResult.rl_openg_dt <= date_to + timedelta(days=1))
        if category:
            common_conditions.append(BidResult.category == category)

        resolved_targets = [(name, matched) for name, matched in targets if matched]
        fallback_targets = [(name, matched) for name, matched in targets if matched is None]
        all_matched_names = sorted(
            {name for _, matched_names in resolved_targets for name in matched_names or []}
        )

        stats_by_name: dict[str, tuple[int, float, int]] = {}
        if all_matched_names:
            for db_name, id_count, rate_value, rate_rows in db.execute(
                select(
                    BidResult.dminstt_nm,
                    func.count(BidResult.id),
                    func.sum(BidResult.sucsf_bid_rate),
                    func.count(BidResult.sucsf_bid_rate),
                )
                .where(*common_conditions, BidResult.dminstt_nm.in_(all_matched_names))
                .group_by(BidResult.dminstt_nm)
            ).all():
                if db_name is None:
                    continue
                stats_by_name[db_name] = (
                    int(id_count or 0),
                    float(rate_value) if rate_value is not None else 0.0,
                    int(rate_rows or 0),
                )

        if fallback_targets:
            fallback_expr = case(
                *[(BidResult.dminstt_nm.contains(name), name) for name, _ in fallback_targets],
                else_=None,
            )
            fallback_scope = or_(
                *[BidResult.dminstt_nm.contains(name) for name, _ in fallback_targets]
            )
            for db_name, id_count, rate_value, rate_rows in db.execute(
                select(
                    fallback_expr,
                    func.count(BidResult.id),
                    func.sum(BidResult.sucsf_bid_rate),
                    func.count(BidResult.sucsf_bid_rate),
                )
                .where(*common_conditions, fallback_scope)
                .group_by(fallback_expr)
            ).all():
                if db_name is None:
                    continue
                stats_by_name[str(db_name)] = (
                    int(id_count or 0),
                    float(rate_value) if rate_value is not None else 0.0,
                    int(rate_rows or 0),
                )

        recent_by_name = _fetch_recent_results_batch(
            db, common_conditions, all_matched_names, limit=3
        )

        by_institution: list[dict[str, Any]] = []
        all_recent_results: list[dict[str, Any]] = []
        total_bids = 0
        rate_sum = 0.0
        rate_count = 0

        for inst_name, matched_names in targets:
            bid_count = 0
            inst_rate_sum = 0.0
            inst_rate_rows = 0
            candidates: list[BidResult] = []
            if matched_names:
                for matched_name in matched_names:
                    count_value, rate_value, rate_rows = stats_by_name.get(
                        matched_name, (0, 0.0, 0)
                    )
                    bid_count += count_value
                    inst_rate_sum += rate_value
                    inst_rate_rows += rate_rows
                    candidates.extend(recent_by_name.get(matched_name, []))
                recent_list = _select_recent_results(candidates, limit=3)
            else:
                bid_count, inst_rate_sum, inst_rate_rows = stats_by_name.get(inst_name, (0, 0.0, 0))
                recent_list = _fetch_recent_results(
                    db,
                    [*common_conditions, BidResult.dminstt_nm.contains(inst_name)],
                    3,
                    filters=filters,
                )

            raw_avg_rate = inst_rate_sum / inst_rate_rows if inst_rate_rows > 0 else None
            avg_rate = float(round(raw_avg_rate, 4)) if raw_avg_rate is not None else 0.0

            total_bids += bid_count
            if bid_count > 0 and raw_avg_rate is not None:
                rate_sum += raw_avg_rate * bid_count
                rate_count += bid_count

            all_recent_results.extend(recent_list)

            by_institution.append(
                {
                    "institution_name": inst_name,
                    "resolved_names": matched_names or [],
                    "bid_count": bid_count,
                    "avg_rate": avg_rate,
                    "recent_results": recent_list,
                }
            )

        overall_avg_rate = float(round(rate_sum / rate_count, 4)) if rate_count > 0 else 0.0
        response_filters = dict(filters)
        if response_filters.get("category"):
            response_filters["category_label"] = _category_label(str(response_filters["category"]))

        summary_payload: dict[str, Any] = {
            "total_bids": total_bids,
            "announcement_count": 0,
            "average_winning_rate": overall_avg_rate,
            "total_winning_amount": 0.0,
            "top_winners": [],
            "top_institutions": [],
            "top_announcements": [],
            "sample_announcements": [],
            "recent_results": all_recent_results,
            "latest_available_result_at": None,
            "time_series": [],
            "by_institution": by_institution,
        }
        leftovers: list[str] = []
        if comparison_metric:
            institution_specs = [
                {
                    "kind": "institution",
                    "label": inst_name,
                    "name": inst_name,
                    "names": matched,
                }
                for inst_name, matched in requested_targets
            ]
            summary_payload["comparison"] = _comparison_breakdown(
                db, plan, institution_specs, dimension="institution"
            )
            summary_payload["comparison_meta"] = {
                "dimension": "institution",
                "metric": comparison_metric,
                "targets": [inst_name for inst_name, _ in requested_targets],
            }
        if unresolved_names:
            leftovers.append(
                "요청한 기관명 중 "
                + ", ".join(unresolved_names)
                + " 은(는) 데이터에서 확인하지 못해 집계에서 제외했습니다."
            )

        return {
            "filters": response_filters,
            "summary": summary_payload,
            "insufficiency_hints": leftovers,
        }

    # 공고번호 단건은 다중 기관 분기 뒤, 집계 준비 앞에서 끝냅니다. 여기서
    # 반환해야 5개 대형 집계와 스냅샷을 타지 않고, 조건에 공고번호를 섞지
    # 않으므로 다른 경로의 평균 기준선도 오염되지 않습니다.
    bid_ntce_no = _normalize_text(str(filters.get("bid_ntce_no") or "")).upper()
    if bid_ntce_no:
        return _bid_detail_result(db, plan, bid_ntce_no)

    institution_name = _normalize_text(str((plan.filters or {}).get("institution_name") or ""))
    institution_aliases = _institution_aliases(plan.filters or {})
    result_names: list[str] | None = None
    announcement_names: list[str] | None = None
    result_name_fallbacks: list[str] = []
    announcement_name_fallbacks: list[str] = []
    condition_plan = plan
    if multi_list_names:
        # 이름마다 해석해 IN 조건의 합집합을 만듭니다. 해석 상한을 넘은 이름은
        # 부분 일치로 남겨 기관 조건이 사라지지 않게 합니다.
        result_names, result_name_fallbacks = _resolve_multi_institution_scope_names(
            db, BidResult.dminstt_nm, multi_list_names
        )
        announcement_names, announcement_name_fallbacks = _resolve_multi_institution_scope_names(
            db, BidAnnouncement.dminstt_nm, multi_list_names
        )
        # 해석된 이름이 하나도 없으면 전체 목록으로 넘어가지 않고 빈 결과를
        # 돌려줍니다.
        if _announcement_limit(plan) and not (announcement_names or announcement_name_fallbacks):
            return _empty_result(
                plan,
                "요청한 기관명을 데이터에서 확인하지 못해 공고 목록을 조회하지 못했습니다. "
                "기관명을 다시 확인해 주세요.",
            )
        if _result_limit(plan) and not (result_names or result_name_fallbacks):
            return _empty_result(
                plan,
                "요청한 기관명을 데이터에서 확인하지 못해 낙찰 결과 목록을 조회하지 못했습니다. "
                "기관명을 다시 확인해 주세요.",
            )
        # 필터에 남은 단일 기관 조건이 IN 합집합과 겹쳐 걸리지 않게 지웁니다.
        scope_filters = dict(plan.filters or {})
        scope_filters.pop("institution_name", None)
        scope_filters.pop("institution_aliases", None)
        condition_plan = plan.model_copy(update={"filters": scope_filters})
    elif institution_name or institution_aliases:
        result_names = _resolve_institution_scope_names(
            db, BidResult.dminstt_nm, institution_name, institution_aliases
        )
        announcement_names = _resolve_institution_scope_names(
            db, BidAnnouncement.dminstt_nm, institution_name, institution_aliases
        )
        if (
            institution_name
            and result_names == []
            and announcement_names == []
            and _single_metric(_normalize_text(plan.semantic_query).lower())
            and not _result_limit(plan)
            and not _announcement_limit(plan)
            and not _normalize_text(str(filters.get("group_by") or ""))
            and filters.get("analysis_mode") != "trend"
        ):
            # 카탈로그에서 확인하지 못한 기관명을 0건이라는 측정값처럼 내지
            # 않습니다. 전체 값으로 넓히지도 않고 기존 미해석 안내를 냅니다.
            return _empty_result(
                plan,
                "요청한 기관명을 데이터에서 확인하지 못해 조회 대상을 확정하지 못했습니다. "
                "기관명을 다시 확인해 주세요.",
            )
    # 해석 상한 초과(None)는 이름 목록 대신 부분 일치 OR 조건으로 넘깁니다.
    result_names_arg = None if result_name_fallbacks else result_names
    announcement_names_arg = None if announcement_name_fallbacks else announcement_names
    result_conditions = _result_conditions(condition_plan, institution_names=result_names_arg)
    announcement_conditions = _announcement_conditions(
        condition_plan, institution_names=announcement_names_arg
    )
    if result_name_fallbacks:
        fallback_condition = _multi_institution_condition(
            BidResult.dminstt_nm, result_names or [], result_name_fallbacks
        )
        if fallback_condition is not None:
            result_conditions.append(fallback_condition)
    if announcement_name_fallbacks:
        fallback_condition = _multi_institution_condition(
            BidAnnouncement.dminstt_nm, announcement_names or [], announcement_name_fallbacks
        )
        if fallback_condition is not None:
            announcement_conditions.append(fallback_condition)
    snapshot_scope = _snapshot_scope(condition_plan)
    result_limit = _result_limit(plan)
    announcement_limit = _announcement_limit(plan)
    # 낙찰 결과 테이블이 지원하지 않는 축의 조건은 조회에서 빠집니다. 조용히 빼지
    # 않고 남겨, 사용자가 조건이 적용된 줄 오해하지 않게 합니다. 목록뿐 아니라
    # 낙찰 건수·평균 낙찰률 같은 통계도 같은 테이블을 집계하므로 함께 밝힙니다.
    result_amount_scope = is_result_amount_scope(plan.semantic_query)
    unapplied_conditions = (
        collect_unapplied_result_conditions(plan.filters)
        if result_limit or result_amount_scope
        else []
    )
    latest_available_result_at = None
    if result_limit:
        latest_available_result_at = db.scalar(
            select(func.max(BidResult.rl_openg_dt)).where(
                *_result_availability_conditions(condition_plan, institution_names=result_names_arg)
            )
        )

    category_filter = _normalize_text(str((plan.filters or {}).get("category") or ""))
    group_by = _normalize_text(str((plan.filters or {}).get("group_by") or ""))
    metric = _normalize_text(str((plan.filters or {}).get("metric") or "")) or "announcement_count"
    # 업체 축은 낙찰 결과 테이블에만 있으므로 기본 지표를 낙찰 건수로 두되,
    # "낙찰률" 표지가 있으면 평균 낙찰률을, "낙찰 금액" 표지가 있으면 금액
    # 합계를 그대로 씁니다. 호출부가 hand-built plan 으로 다른 지표를 넘겨도
    # 표 라벨과 값이 어긋나지 않습니다.
    if group_by == "winner" and metric not in ("avg_rate", "award_amount"):
        metric = "bid_count"
    group_limit = _group_limit(plan)
    winner_conditions = _result_conditions(
        condition_plan, enable_ngram_prefilter=True, institution_names=result_names_arg
    )
    institution_conditions = _announcement_conditions(
        condition_plan, enable_ngram_prefilter=True, institution_names=announcement_names_arg
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
                condition_plan,
                result_names_arg,
            ),
        )

    def announcement_total(session: Session) -> list[Any]:
        return _cached_aggregate(
            session,
            _hint_announcement_institution_cover(
                select(func.count(BidAnnouncement.id)).where(*announcement_conditions),
                condition_plan,
                announcement_names_arg,
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
                condition_plan,
                result_names_arg,
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
                condition_plan,
                announcement_names_arg,
            ),
            corrupted_probe=select(BidAnnouncement.id).where(
                BidAnnouncement.dminstt_nm.contains(REPLACEMENT_CHAR), *announcement_conditions
            ),
            limit=(
                group_limit if group_by == "institution" and metric == "announcement_count" else 5
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
                condition_plan,
                announcement_names_arg,
            ),
            corrupted_probe=select(BidAnnouncement.id).where(
                BidAnnouncement.bid_ntce_nm.contains(REPLACEMENT_CHAR), *announcement_conditions
            ),
        )

    def axis_aggregate(session: Session):
        return _build_axis_breakdown(
            session,
            group_by=group_by,
            metric=metric,
            result_conditions=result_conditions,
            announcement_conditions=announcement_conditions,
            limit=group_limit,
        )

    # 가장 긴 공고명 집계를 마지막에 두어 요청 세션이 직접 맡게 합니다.
    (
        (total_count, avg_rate, total_amt),
        (announcement_count,),
        (winner_rows, dropped_winners),
        (institution_rows, dropped_institutions),
        axis_result,
        (announcement_rows, dropped_announcements),
    ) = _run_aggregates(
        db,
        [
            ("cached_aggregate", result_amounts),
            ("cached_aggregate", announcement_total),
            ("top_rows", winner_ranking),
            ("top_rows", institution_ranking),
            ("axis_breakdown", axis_aggregate),
            ("top_rows", announcement_ranking),
        ],
    )

    recent_results = _fetch_recent_results(
        db, result_conditions, result_limit, filters=plan.filters or {}
    )
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

    axis_breakdown: list[dict[str, Any]] = []
    axis_truncated = False
    axis_dropped = 0
    if axis_result is not None:
        axis_breakdown, axis_truncated = axis_result
    elif group_by == "institution" and metric == "announcement_count":
        # 기관별 공고 건수는 위 institution_ranking 이 이미 집계했습니다.
        axis_breakdown = [
            _axis_entry(
                _normalize_text(row[0]) if row[0] else "-",
                _normalize_text(row[0]) if row[0] else "",
                announcement_count=int(row[1] or 0),
            )
            for row in institution_rows
        ]
        axis_truncated = len(institution_rows) >= group_limit
        axis_dropped = dropped_institutions

    sample_announcements = _fetch_sample_announcements(
        db,
        announcement_conditions,
        limit=announcement_limit or 3,
        detailed=bool(announcement_limit),
        filters=plan.filters or {},
    )
    time_series = _build_time_series(
        db,
        condition_plan,
        result_conditions,
        announcement_conditions=announcement_conditions,
        result_names=result_names_arg,
        announcement_names=announcement_names_arg,
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

    # 상호가 같은 업체만 세는 기본값은 유지하되, 지점·가맹점처럼 상호에 그
    # 이름이 들어간 다른 사업자가 몇 건인지 밝혀 사용자가 수치 범위를 알게
    # 합니다. 정확 일치 값은 건드리지 않습니다.
    winner_filter_name = _normalize_text(str((plan.filters or {}).get("winner_name") or ""))
    winner_variant: dict[str, Any] | None = None
    if winner_filter_name:
        other_variant_count = _count_other_winner_variants(
            db, plan, winner_filter_name, institution_names=result_names
        )
        if other_variant_count:
            variant_total = int(total_count or 0) + other_variant_count
            winner_variant = {
                "name": winner_filter_name,
                "other_count": other_variant_count,
                "total_count": variant_total,
                "notice": _winner_variant_notice(
                    winner_filter_name, other_variant_count, variant_total
                ),
            }
            insufficiency.append(winner_variant["notice"])
    if group_by == "region":
        insufficiency.append(
            "지역 구분은 기관명 부분 일치 기준이라 지역 합계가 전체 건수와 일치하지 않을 수 있습니다."
        )
    unapplied_notice = unapplied_result_condition_notice(unapplied_conditions)
    if unapplied_notice:
        insufficiency.append(unapplied_notice)

    assembly_started = time.perf_counter()
    response_filters = dict(plan.filters or {})
    if response_filters.get("category"):
        response_filters["category_label"] = _category_label(str(response_filters["category"]))
    # 공고 목록 머리 문장은 category_label 을 그대로 씁니다. 공고 종류 조건이
    # 걸린 질의는 종류를 라벨 앞에 붙여 "최근 재공고 용역 공고 5건입니다." 처럼
    # 어떤 종류를 조회했는지 밝힙니다.
    notice_kind_label = _normalize_text(str(response_filters.get("notice_kind") or ""))
    if notice_kind_label:
        category_label = _normalize_text(str(response_filters.get("category_label") or ""))
        response_filters["category_label"] = (
            f"{notice_kind_label} {category_label}".strip() if category_label else notice_kind_label
        )

    summary: dict[str, Any] = {
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
            latest_available_result_at.isoformat(sep=" ") if latest_available_result_at else None
        ),
        "time_series": time_series,
    }
    if group_by:
        summary["axis_breakdown"] = axis_breakdown
        summary["aggregate_meta"] = {
            "group_by": group_by,
            "metric": metric,
            "limit": group_limit,
            "truncated": axis_truncated,
            "dropped": axis_dropped,
            "window": {
                "date_from": (plan.filters or {}).get("date_from"),
                "date_to": (plan.filters or {}).get("date_to"),
            },
        }

    result = {
        "filters": response_filters,
        "summary": summary,
        "insufficiency_hints": insufficiency,
        "unapplied_conditions": unapplied_conditions,
    }
    if winner_variant:
        result["winner_variant"] = winner_variant
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

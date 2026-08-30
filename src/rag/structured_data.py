"""
src/rag/structured_data.py

RAG 정형 검색 (원본 rag_engine.retrieve_structured_data / _apply_*_filters SQLAlchemy 이식).
필터 규칙, 집계 항목, 시계열 버킷 산출을 원본과 동일하게 유지합니다.
"""

from __future__ import annotations

import hashlib
import unicodedata
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.app.core.cache import cache
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
    get_top_rankings,
)
from src.rag.schemas import RetrievalPlan


def _normalize_text(value: str | None) -> str:
    return unicodedata.normalize("NFC", (value or "").strip())


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


def _result_conditions(plan: RetrievalPlan) -> list:
    filters = plan.filters or {}
    date_from, date_to = _resolve_window(filters)
    institution_name = _normalize_text(str(filters.get("institution_name") or ""))
    category = _normalize_text(str(filters.get("category") or ""))

    conditions = []
    if date_from:
        conditions.append(BidResult.rl_openg_dt >= date_from)
    if date_to:
        conditions.append(BidResult.rl_openg_dt <= date_to + timedelta(days=1))
    if institution_name:
        conditions.append(BidResult.dminstt_nm.contains(institution_name))
    if category:
        conditions.append(BidResult.category == category)
    return conditions


def _announcement_conditions(plan: RetrievalPlan) -> list:
    filters = plan.filters or {}
    date_from, date_to = _resolve_window(filters)
    institution_name = _normalize_text(str(filters.get("institution_name") or ""))
    category = _normalize_text(str(filters.get("category") or ""))

    conditions = []
    if date_from:
        conditions.append(BidAnnouncement.bid_ntce_dt >= date_from)
    if date_to:
        conditions.append(BidAnnouncement.bid_ntce_dt <= date_to + timedelta(days=1))
    if institution_name:
        conditions.append(BidAnnouncement.dminstt_nm.contains(institution_name))
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
# (ix_bid_results_bidwinnr_nm)를 골라 3,267,347행 전부를 훑습니다(filtered 15.29%).
# 버퍼 풀이 식어 있으면 이 스캔이 최대 97초를 씁니다(2026-08-30 실측).
# 날짜 인덱스를 강제하면 범위 스캔으로 좁혀져 13,412ms 가 714ms 로 떨어집니다.
# category 가 함께 걸리면 옵티마이저가 ix_bid_results_cat_dt_stats 로 182,902행까지
# 이미 좁히므로 그때는 힌트를 주지 않습니다.
RESULT_DATE_INDEX_HINT = "FORCE INDEX (ix_bid_results_dt_cat)"


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


def _result_availability_conditions(plan: RetrievalPlan) -> list:
    """날짜 필터를 제외한 결과 보유 범위 확인 조건을 만듭니다."""
    filters = plan.filters or {}
    institution_name = _normalize_text(str(filters.get("institution_name") or ""))
    category = _normalize_text(str(filters.get("category") or ""))
    conditions = []
    if institution_name:
        conditions.append(BidResult.dminstt_nm.contains(institution_name))
    if category:
        conditions.append(BidResult.category == category)
    return conditions


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


def _top_rows(
    db: Session,
    *,
    scope: str | None,
    dataset: str,
    dimension: str,
    live_stmt,
    corrupted_probe,
    limit: int = 5,
    ttl: int = AGGREGATE_CACHE_TTL,
) -> tuple[list, int]:
    """스냅샷이 있으면 그것을, 없으면 실시간 집계를 씁니다.

    스냅샷은 집계 시점에 이미 손상값을 걸러 두었으므로 그대로 씁니다.
    실시간 경로는 여기서 걸러냅니다.
    """
    if scope is not None:
        cached = get_top_rankings(db, dataset, dimension, scope, limit)
        if cached is not None:
            # 스냅샷은 집계 시점에 걸러냈으므로 그때 기록해 둔 표시를 씁니다.
            return cached, get_skipped_count(db, dataset, dimension, scope)

    # 스냅샷은 날짜 필터가 붙는 순간 포기합니다(_snapshot_scope). "2026년" 같은
    # 흔한 표현이 곧 날짜 필터이므로 실시간 경로가 자주 타며, 그 경로가 캐시
    # 없이는 매번 2초를 씁니다. 같은 창을 다시 묻는 일이 잦으므로 캐시합니다.
    stmt = live_stmt.limit(limit * LIVE_OVERFETCH_FACTOR)
    key = _stmt_cache_key("rag:top:", stmt)
    cached_live = cache.get(key)
    if cached_live is not None:
        rows, dropped = cached_live
        return [tuple(row) for row in rows], int(dropped)

    kept, dropped = _drop_corrupted(db.execute(stmt).all(), limit)
    if not dropped:
        # SQL 이 이미 U+FFFD 를 쳐냈으므로, 제외가 있었는지는 따로 확인합니다.
        # 첫 건에서 멈추므로 전체 스캔이 되지 않습니다.
        dropped = int(db.execute(corrupted_probe.limit(1)).first() is not None)

    # 손상 탐지 결과까지 함께 담습니다. 순위만 캐시하면 적중할 때마다 탐지
    # 질의가 다시 돌아 절반만 아끼게 됩니다.
    cache.set(key, [[[_cacheable(v) for v in row] for row in kept], dropped], ttl)
    return kept, dropped


def _cached_aggregate(db: Session, stmt, ttl: int = AGGREGATE_CACHE_TTL) -> list[Any]:
    """집계 결과를 캐시에서 돌려줍니다.

    3,405,928 행 위의 COUNT/AVG/SUM 은 질의당 190ms 가 걸립니다. 챗봇 한 번에
    이런 집계가 아홉 번 돌아 1.72초를 씁니다. 그동안 첫 토큰은 나오지 않습니다.

    캐시가 없어도(Redis 미가용) CacheLayer 가 메모리 캐시로 내려가므로 동작은
    같습니다. 값이 없으면 그냥 DB 를 칩니다.
    """
    key = _stmt_cache_key("rag:agg:", stmt)

    cached = cache.get(key)
    if cached is not None:
        return list(cached)

    row = list(db.execute(stmt).one())
    # Redis 경로는 JSON 직렬화라 Decimal 이 문자열이 됩니다. 메모리 캐시와 값
    # 종류가 달라지지 않도록 여기서 미리 float 로 맞춥니다. 호출부는 어차피
    # int()/float() 로 다시 감쌉니다.
    normalized = [_numeric_or_none(value) for value in row]
    cache.set(key, normalized, ttl)
    return normalized


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


def _build_time_series(db: Session, plan: RetrievalPlan, conditions: list) -> list[dict[str, Any]]:
    """트렌드 분석 모드일 때 개찰일자별 낙찰률 시계열 버킷을 계산합니다."""
    if (plan.filters or {}).get("analysis_mode") != "trend":
        return []
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


def retrieve_structured_data(db: Session, plan: RetrievalPlan) -> dict[str, Any]:
    try:
        result_conditions = _result_conditions(plan)
    except InvalidDateFilterError as exc:
        # 해석하지 못한 날짜 필터를 빼고 조회하면 전체 기간 통계가 사용자가
        # 지정한 기간의 답으로 돌아갑니다. 조회 자체를 하지 않고 알립니다.
        return _empty_result(
            plan,
            f"{exc} 날짜를 YYYY-MM-DD 형식으로 다시 알려주시면 해당 기간으로 조회하겠습니다.",
        )
    announcement_conditions = _announcement_conditions(plan)
    snapshot_scope = _snapshot_scope(plan)
    result_limit = _result_limit(plan)
    latest_available_result_at = None
    if result_limit:
        latest_available_result_at = db.scalar(
            select(func.max(BidResult.rl_openg_dt)).where(*_result_availability_conditions(plan))
        )

    total_count, avg_rate, total_amt = _cached_aggregate(
        db,
        select(
            func.count(BidResult.id),
            func.avg(BidResult.sucsf_bid_rate),
            func.sum(BidResult.sucsf_bid_amt),
        ).where(*result_conditions),
    )
    (announcement_count,) = _cached_aggregate(
        db,
        select(func.count(BidAnnouncement.id)).where(*announcement_conditions),
    )

    recent_results = _fetch_recent_results(db, result_conditions, result_limit)

    winner_rows, dropped_winners = _top_rows(
        db,
        scope=snapshot_scope,
        dataset=DATASET_RESULT,
        dimension="bidwinnr_nm",
        live_stmt=_hint_result_date_index(
            select(BidResult.bidwinnr_nm, func.count(BidResult.id))
            .where(exclude_corrupted(BidResult.bidwinnr_nm), *result_conditions)
            .group_by(BidResult.bidwinnr_nm)
            .order_by(func.count(BidResult.id).desc()),
            plan,
        ),
        corrupted_probe=select(BidResult.id).where(
            BidResult.bidwinnr_nm.contains(REPLACEMENT_CHAR), *result_conditions
        ),
    )
    top_winners = [
        {"bidwinnr_nm": _normalize_text(row[0]) if row[0] else row[0], "win_count": row[1]}
        for row in winner_rows
    ]

    institution_rows, dropped_institutions = _top_rows(
        db,
        scope=snapshot_scope,
        dataset=DATASET_ANNOUNCEMENT,
        dimension="dminstt_nm",
        live_stmt=select(BidAnnouncement.dminstt_nm, func.count(BidAnnouncement.id))
        .where(exclude_corrupted(BidAnnouncement.dminstt_nm), *announcement_conditions)
        .group_by(BidAnnouncement.dminstt_nm)
        .order_by(func.count(BidAnnouncement.id).desc()),
        corrupted_probe=select(BidAnnouncement.id).where(
            BidAnnouncement.dminstt_nm.contains(REPLACEMENT_CHAR), *announcement_conditions
        ),
    )
    top_institutions = [
        {"dminstt_nm": _normalize_text(row[0]) if row[0] else row[0], "ntce_count": row[1]}
        for row in institution_rows
    ]

    announcement_rows, dropped_announcements = _top_rows(
        db,
        scope=snapshot_scope,
        dataset=DATASET_ANNOUNCEMENT,
        dimension="bid_ntce_nm",
        live_stmt=select(BidAnnouncement.bid_ntce_nm, func.count(BidAnnouncement.id))
        .where(exclude_corrupted(BidAnnouncement.bid_ntce_nm), *announcement_conditions)
        .group_by(BidAnnouncement.bid_ntce_nm)
        .order_by(func.count(BidAnnouncement.id).desc()),
        corrupted_probe=select(BidAnnouncement.id).where(
            BidAnnouncement.bid_ntce_nm.contains(REPLACEMENT_CHAR), *announcement_conditions
        ),
    )
    top_announcements = [
        {"bid_ntce_nm": _normalize_text(row[0]) if row[0] else row[0], "ntce_count": row[1]}
        for row in announcement_rows
    ]

    sample_announcements = _fetch_sample_announcements(db, announcement_conditions)
    time_series = _build_time_series(db, plan, result_conditions)

    dropped_total = dropped_winners + dropped_institutions + dropped_announcements
    insufficiency = _build_insufficiency_hints(
        total_count=total_count,
        result_limit=result_limit,
        recent_results=recent_results,
        latest_available_result_at=latest_available_result_at,
        announcement_count=announcement_count,
        dropped_total=dropped_total,
    )

    response_filters = dict(plan.filters or {})
    if response_filters.get("category"):
        response_filters["category_label"] = _category_label(str(response_filters["category"]))

    return {
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

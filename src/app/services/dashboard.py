"""
src/app/services/dashboard.py

대시보드/비교분석 집계 (원본 apps/bids/dashboard_api.py 1:1 이식).
Django ORM 집계를 SQLAlchemy 2.0 표현식으로 옮기되 산출 값과 캐시 키 규칙은 원본과 동일합니다.
"""

from __future__ import annotations

import logging
import re
import threading
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Numeric, String, case, func, literal, or_, select
from sqlalchemy.orm import Session

from src.app.core.cache import cache
from src.app.core.timeutil import utcnow
from src.app.models.bids import (
    DATASET_ANNOUNCEMENT,
    DATASET_RESULT,
    BidAnnouncement,
    BidDatasetSummary,
    BidResult,
    is_corrupted_display_text,
)

logger = logging.getLogger(__name__)

# 금액 집계는 DECIMAL 로 누적합니다. 자릿수는 조달 금액 규모에 비해 넉넉히 둡니다.
AMOUNT_NUMERIC = Numeric(30, 0)
# 집계에서 제외할 기초금액 상한(100조). 2026-09-04 기준 전체 5,497,840 건 중 이
# 상한을 넘는 33건은 모두 조달청 원본 오류입니다. 자릿수 중복 입력(137150000137150000
# 은 137150000 의 반복), 더미값(111111111111111 계열 27건), 그리고 원본이 BIGINT
# 범위를 넘겨 적재 시점에 9223372036854775807 로 포화된 2건입니다. 실재하는 최대
# 규모 사업(가덕도신공항 약 10.7조)은 상한 아래이므로 살아남습니다.
MAX_REASONABLE_ANNOUNCEMENT_AMOUNT = 100_000_000_000_000

# 데이터셋별 집계 알고리즘 기대 버전.
# announcement 는 base_amount 컬럼 기반 집계 전환으로 3으로 상향되었습니다.
# result 는 기존 알고리즘을 유지하므로 1입니다.
# DB 에 저장된 버전이 기대 버전과 다르면 stale 로 판정해 재집계합니다.
SUMMARY_ALGORITHM_VERSIONS: dict[str, int] = {
    DATASET_ANNOUNCEMENT: 3,
    DATASET_RESULT: 1,
}

DASHBOARD_STATS_CACHE_TTL = 60 * 60 * 24
COMPARE_STATS_CACHE_TTL = 60 * 60 * 24
DASHBOARD_STATS_STALE_CACHE_TTL = 60
# 최초 동기 집계용 분산 락의 수명입니다. announcement 전체 집계 실측이 콜드 버퍼풀에서
# 554초였으므로 600초는 여유가 8퍼센트뿐입니다. 락이 집계보다 먼저 풀리면 두 번째
# 요청이 같은 집계를 또 시작해 락이 있으나 없으나 같아집니다. 실측의 세 배로 둡니다.
SUMMARY_INIT_LOCK_TIMEOUT = 1800
COMPARE_STATS_STALE_CACHE_TTL = 60
DASHBOARD_RESULT_SCOPE_START = datetime(2015, 1, 1, tzinfo=UTC).replace(tzinfo=None)
DASHBOARD_RESULT_SCOPE_LABEL = "2015년 ~ 현재"
UNIT_PRICE_RESULT_KEYWORDS = (
    "단가",
    "교복",
    "학생복",
)
UNCLASSIFIED_AGENCY_LABELS = {
    "기타 기관(분석불가)",
    "기타 기관 (분석 불가)",
}


def _display_agency_name(name: str | None) -> str | None:
    if name in UNCLASSIFIED_AGENCY_LABELS:
        return "미분류 기관"
    return name


def _is_readable_agency_name(name: str | None) -> bool:
    """업체 순위(`_is_readable_company_name`)와 같은 기준을 기관 순위에도 적용합니다.

    parquet 복구분에 인코딩이 깨진 기관명이 남아 있어, 걸러내지 않으면 순위 상단이
    읽을 수 없는 문자열로 채워집니다.
    """
    return bool(name) and not is_corrupted_display_text(name)


def _exclude_unit_price_results(stmt):
    for keyword in UNIT_PRICE_RESULT_KEYWORDS:
        stmt = stmt.where(
            or_(
                BidResult.bid_ntce_nm.is_(None),
                ~BidResult.bid_ntce_nm.contains(keyword),
            )
        )
    return stmt


def _extract_representative_company_name(raw_name: str | None) -> str:
    if not raw_name:
        return ""
    match = re.search(r"\^\s*(?:공동|단독)\^([^^\],]+)", raw_name)
    if match:
        return match.group(1).strip()
    return raw_name.strip()


def _is_readable_company_name(name: str) -> bool:
    if not name or "�" in name:
        return False
    return bool(re.search(r"[가-힣A-Za-z0-9]", name))


def _build_company_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    company_totals: dict[str, dict[str, Any]] = {}
    for row in rows:
        name = _extract_representative_company_name(row["bidwinnr_nm"])
        if not _is_readable_company_name(name):
            continue
        existing = company_totals.setdefault(name, {"name": name, "count": 0, "total_amt": 0})
        existing["count"] += row["cnt"]
        existing["total_amt"] += int(row["total_amt"] or 0)
    return sorted(company_totals.values(), key=lambda item: item["total_amt"], reverse=True)[:10]


def _dialect_name(db: Session) -> str:
    try:
        return db.get_bind().dialect.name
    except Exception:
        return "mysql"


def _month_bucket_expr(db: Session, column):
    """월 버킷 문자열(YYYY-MM) 표현식. 원본의 vendor 분기를 그대로 유지합니다."""
    vendor = _dialect_name(db)
    if vendor == "sqlite":
        return func.strftime("%Y-%m", column).cast(String)
    if vendor == "postgresql":
        return func.to_char(column, "YYYY-MM").cast(String)
    return func.date_format(column, "%Y-%m").cast(String)


def _build_monthly_counts(db: Session, base_stmt, column) -> list[dict[str, Any]]:
    subquery = base_stmt.where(column.is_not(None)).subquery()
    aliased_column = getattr(subquery.c, column.key)
    aliased_bucket = _month_bucket_expr(db, aliased_column)
    rows = db.execute(
        select(aliased_bucket.label("month"), func.count(subquery.c.id).label("cnt"))
        .group_by(aliased_bucket)
        .order_by(aliased_bucket)
    ).all()
    return [{"month": row.month, "count": row.cnt} for row in rows if row.month]


def _marker_value(value: datetime | None) -> str:
    if value is None:
        return "empty"
    return value.isoformat()


def _latest_collection_value(db: Session, model) -> datetime | None:
    return db.scalar(select(func.max(model.collected_at)))


def _dashboard_stats_cache_key(summary: BidDatasetSummary) -> str:
    return (
        "dashboard_basic_stats:v4:"
        f"{DASHBOARD_RESULT_SCOPE_START.isoformat()}:"
        f"v{summary.aggregation_version}:"
        f"{_marker_value(summary.source_latest_collected_at)}:"
        f"{_marker_value(summary.rebuilt_at)}"
    )


def _compare_stats_cache_key(
    announcement_summary: BidDatasetSummary,
    result_summary: BidDatasetSummary,
) -> str:
    return (
        "dashboard_compare_stats:"
        f"v{announcement_summary.aggregation_version}:"
        f"{_marker_value(announcement_summary.source_latest_collected_at)}:"
        f"{_marker_value(announcement_summary.rebuilt_at)}:"
        f"v{result_summary.aggregation_version}:"
        f"{_marker_value(result_summary.source_latest_collected_at)}:"
        f"{_marker_value(result_summary.rebuilt_at)}"
    )


def _model_for_dataset(dataset: str):
    if dataset == DATASET_ANNOUNCEMENT:
        return BidAnnouncement
    return BidResult


def _json_text(db: Session, column, key: str):
    """raw_data JSON 키를 텍스트로 추출합니다 (원본 KeyTextTransform 대응)."""
    if _dialect_name(db) == "mysql":
        return func.json_unquote(func.json_extract(column, f"$.{key}"))
    return func.json_extract(column, f"$.{key}")


def _announcement_amount_expr(db: Session | None = None):
    """집계용 기초금액 표현식.

    base_amount 컬럼 기반으로 집계합니다. 수집 파서가 이미 raw_data 의
    기초금액(asignBdgtAmt, bdgtAmt)을 Decimal 기반으로 정제하여 base_amount
    컬럼에 적재하므로, 질의 시점의 반복적인 json_extract 와 형변환을 제거합니다.

    누적은 BIGINT 가 아니라 DECIMAL(AMOUNT_NUMERIC)로 유지합니다.
    MAX_REASONABLE_ANNOUNCEMENT_AMOUNT(100조)를 초과하는 이상치는
    집계에서 제외(None 처리)합니다. 포화 2건(9223372036854775807)도
    상한을 넘으므로 집계에서 안전하게 배제됩니다.
    근거는 docs/ops/announcement_amount_outliers_20260904.md 및
    docs/analysis/base_amount_column_mismatch_343_20260904.md.
    """
    resolved = func.cast(BidAnnouncement.base_amount, AMOUNT_NUMERIC)
    return case((resolved > literal(MAX_REASONABLE_ANNOUNCEMENT_AMOUNT), None), else_=resolved)


def _build_summary_defaults(db: Session, dataset: str) -> dict[str, Any]:
    expected_version = SUMMARY_ALGORITHM_VERSIONS.get(dataset, 1)
    if dataset == DATASET_ANNOUNCEMENT:
        row = db.execute(
            select(
                func.count(BidAnnouncement.id),
                func.sum(_announcement_amount_expr(db)),
                func.max(BidAnnouncement.collected_at),
            )
        ).one()
        avg_rate = None
        total_count, total_amount, latest_collected_at = row
    else:
        row = db.execute(
            select(
                func.count(BidResult.id),
                func.sum(BidResult.sucsf_bid_amt),
                func.avg(BidResult.sucsf_bid_rate),
                func.max(BidResult.collected_at),
            )
        ).one()
        total_count, total_amount, avg_rate, latest_collected_at = row

    return {
        "total_count": total_count or 0,
        "total_amount": total_amount or 0,
        "avg_rate": avg_rate,
        "source_latest_collected_at": latest_collected_at,
        "aggregation_version": expected_version,
    }


def rebuild_bid_dataset_summary(db: Session, dataset: str) -> BidDatasetSummary:
    defaults = _build_summary_defaults(db, dataset)
    summary = db.get(BidDatasetSummary, dataset)
    if summary is None:
        summary = BidDatasetSummary(dataset=dataset, **defaults)
        db.add(summary)
    else:
        for field, value in defaults.items():
            setattr(summary, field, value)
        summary.rebuilt_at = utcnow()
    db.commit()
    db.refresh(summary)
    return summary


def rebuild_bid_dataset_summaries(db: Session, datasets=None) -> dict[str, BidDatasetSummary]:
    datasets = list(datasets or (DATASET_ANNOUNCEMENT, DATASET_RESULT))
    return {dataset: rebuild_bid_dataset_summary(db, dataset) for dataset in datasets}


_process_init_locks: dict[str, threading.Lock] = {}
_process_init_guard = threading.Lock()


def _get_process_lock(dataset: str) -> threading.Lock:
    with _process_init_guard:
        if dataset not in _process_init_locks:
            _process_init_locks[dataset] = threading.Lock()
        return _process_init_locks[dataset]


def _summary_job_id(dataset: str, expected_version: int, marker: datetime | None) -> str:
    """재집계 작업의 중복 판정 키입니다.

    데이터셋 단위 고정 job_id 를 쓰면 안 됩니다. arq 는 같은 job_id 의 결과 키가
    남아 있는 동안 등록을 거부하고(`arq/connections.py` 중복 검사), 이 저장소의
    `keep_result` 는 3600초입니다. 즉 재집계가 끝난 뒤 한 시간 동안은 새로 생긴
    stale 을 큐에 넣을 수 없습니다. 독립 리뷰어가 이 결함을 찾았습니다.

    그래서 **stale 조건 자체를 키로 씁니다.** 같은 조건의 반복 조회는 하나로
    합쳐지고(원래 의도), 수집이나 알고리즘 변경으로 조건이 바뀌면 새 키가 되어
    곧바로 등록됩니다.
    """
    marker_part = marker.isoformat() if marker is not None else "none"
    return f"rebuild_dataset_summary:{dataset}:v{expected_version}:{marker_part}"


def enqueue_rebuild_dataset_summary(
    dataset: str, expected_version: int, marker: datetime | None
) -> bool:
    """데이터셋 요약 재집계 작업을 Arq 큐에 등록합니다.

    같은 stale 조건의 중복 등록은 arq 가 job_id 로 합칩니다. 중복으로 합쳐진 것과
    등록 실패는 다른 사건이므로 로그에서 구분합니다. 구분하지 않으면 큐에 아무것도
    들어가지 않았는데 성공으로 읽습니다.
    """
    from src.app.services.automation_jobs import enqueue_arq_job_reporting_dedupe

    job_id = _summary_job_id(dataset, expected_version, marker)
    created = enqueue_arq_job_reporting_dedupe(
        "rebuild_dataset_summary_task", arq_job_id=job_id, dataset=dataset
    )
    if created is None:
        logger.warning("요약 재집계 작업 등록 실패: %s", job_id)
        return False
    if created is False:
        logger.debug("요약 재집계 작업이 이미 등록돼 있어 합쳤습니다: %s", job_id)
    return True


def _rebuild_with_lock(db: Session, dataset: str) -> BidDatasetSummary:
    """스냅샷이 아예 없는 최초 상태에서만 동기 집계를 수행합니다.

    분산 락(Redis)을 우선 획득하여 동시 유입 요청 중 1개만 집계를 수행하도록 통제하며,
    Redis가 없을 때는 프로세스 내 락(threading.Lock)을 사용하여 fail-open으로
    인한 동시 대량 쿼리 부하를 차단합니다.
    """
    client = cache.client()
    lock_name = f"lock:bid_dataset_summary:init:{dataset}"

    if client is not None:
        try:
            with client.lock(lock_name, timeout=SUMMARY_INIT_LOCK_TIMEOUT, blocking_timeout=30):
                existing = db.get(BidDatasetSummary, dataset)
                if existing is not None:
                    existing.is_stale = False
                    return existing
                summary = rebuild_bid_dataset_summary(db, dataset)
                summary.is_stale = False
                return summary
        except Exception as exc:
            logger.warning("Redis 분산 락 획득 실패 (%s): %s", lock_name, exc)
            existing = db.get(BidDatasetSummary, dataset)
            if existing is not None:
                existing.is_stale = False
                return existing
            raise RuntimeError(f"데이터셋 요약 초기 집계 분산 락 획득 실패: {dataset}") from exc
    else:
        logger.warning("Redis 미가용 상태에서 프로세스 락으로 초기 집계를 제어합니다: %s", dataset)
        process_lock = _get_process_lock(dataset)
        with process_lock:
            existing = db.get(BidDatasetSummary, dataset)
            if existing is not None:
                existing.is_stale = False
                return existing
            summary = rebuild_bid_dataset_summary(db, dataset)
            summary.is_stale = False
            return summary


def get_bid_dataset_summary(db: Session, dataset: str) -> BidDatasetSummary:
    """데이터셋 요약을 조회합니다.

    조회 경로는 절대로 전체 재집계를 수행하지 않습니다.
    1. 스냅샷이 없는 최초 상태: 분산 락 하에서 1회만 동기 집계 수행.
    2. 스냅샷이 있는 stale 상태: 이전 스냅샷을 그대로 반환하고, is_stale=True 표시 후
       비동기 재집계 작업을 Arq 큐에 등록(고정 job_id로 중복 방지).
    3. fresh 상태: is_stale=False 표시 후 그대로 반환.
    """
    summary = db.get(BidDatasetSummary, dataset)
    if summary is None:
        return _rebuild_with_lock(db, dataset)

    latest_collected_at = _latest_collection_value(db, _model_for_dataset(dataset))
    expected_version = SUMMARY_ALGORITHM_VERSIONS.get(dataset, 1)
    is_stale = (
        summary.source_latest_collected_at != latest_collected_at
        or summary.aggregation_version != expected_version
    )
    summary.is_stale = is_stale

    if is_stale:
        enqueue_rebuild_dataset_summary(dataset, expected_version, latest_collected_at)

    return summary


def get_dashboard_stats(db: Session) -> dict[str, Any]:
    """대시보드 기본 통계 데이터."""
    result_summary = get_bid_dataset_summary(db, DATASET_RESULT)
    is_stale = getattr(result_summary, "is_stale", False)
    cache_key = _dashboard_stats_cache_key(result_summary)
    if is_stale:
        cache_key = f"{cache_key}:stale"

    data = cache.get(cache_key)
    if data:
        return data

    now = utcnow()
    one_year_ago = now - timedelta(days=365)

    scoped = db.execute(
        select(
            func.count(BidResult.id),
            func.sum(BidResult.sucsf_bid_amt),
            func.avg(BidResult.sucsf_bid_rate),
            func.max(BidResult.collected_at),
        ).where(BidResult.rl_openg_dt >= DASHBOARD_RESULT_SCOPE_START)
    ).one()
    scoped_count, scoped_amount, scoped_avg_rate, scoped_latest = scoped

    # 기관별 TOP 10 (최근 1년)
    by_agency = db.execute(
        select(
            BidResult.dminstt_nm,
            func.sum(BidResult.sucsf_bid_amt).label("total_amt"),
            func.count(BidResult.id).label("cnt"),
        )
        .where(BidResult.rl_openg_dt >= one_year_ago, BidResult.dminstt_nm.is_not(None))
        .group_by(BidResult.dminstt_nm)
        .order_by(func.sum(BidResult.sucsf_bid_amt).desc())
        .limit(10)
    ).all()

    # 업체별 TOP 10 (최근 1년) — 원본과 동일하게 상위 100건을 대표명으로 재집계
    company_stmt = select(
        BidResult.bidwinnr_nm,
        func.count(BidResult.id).label("cnt"),
        func.sum(BidResult.sucsf_bid_amt).label("total_amt"),
    ).where(
        BidResult.rl_openg_dt >= one_year_ago,
        BidResult.bidwinnr_nm.is_not(None),
        BidResult.bidwinnr_nm != "",
        BidResult.sucsf_bid_amt > 0,
    )
    company_stmt = _exclude_unit_price_results(company_stmt)
    by_company = db.execute(
        company_stmt.group_by(BidResult.bidwinnr_nm)
        .order_by(func.sum(BidResult.sucsf_bid_amt).desc())
        .limit(100)
    ).all()

    # 월별 추세 (최근 1년)
    by_month = _build_monthly_counts(
        db,
        select(BidResult.id, BidResult.rl_openg_dt).where(BidResult.rl_openg_dt >= one_year_ago),
        BidResult.rl_openg_dt,
    )

    data = {
        "scope_label": DASHBOARD_RESULT_SCOPE_LABEL,
        "total_count": scoped_count or 0,
        "total_amount": int(scoped_amount or 0),
        "avg_rate": round(float(scoped_avg_rate or 0), 2),
        "latest_collected": scoped_latest.isoformat() if scoped_latest else None,
        "by_agency": [
            {
                "name": _display_agency_name(row.dminstt_nm),
                "total_amt": int(row.total_amt or 0),
                "count": row.cnt,
            }
            for row in by_agency
            if _is_readable_agency_name(row.dminstt_nm)
        ],
        "by_company": _build_company_rows(
            [
                {"bidwinnr_nm": row.bidwinnr_nm, "cnt": row.cnt, "total_amt": row.total_amt}
                for row in by_company
            ]
        ),
        "by_month": by_month,
    }

    ttl = (
        DASHBOARD_STATS_STALE_CACHE_TTL
        if getattr(result_summary, "is_stale", False)
        else DASHBOARD_STATS_CACHE_TTL
    )
    cache.set(cache_key, data, ttl)
    return data


def get_compare_stats_data(db: Session) -> dict[str, Any]:
    """입찰공고 vs 낙찰 비교 통계."""
    announcement_summary = get_bid_dataset_summary(db, DATASET_ANNOUNCEMENT)
    result_summary = get_bid_dataset_summary(db, DATASET_RESULT)
    is_stale = getattr(announcement_summary, "is_stale", False) or getattr(
        result_summary, "is_stale", False
    )
    cache_key = _compare_stats_cache_key(announcement_summary, result_summary)
    if is_stale:
        cache_key = f"{cache_key}:stale"

    data = cache.get(cache_key)
    if data:
        return data

    now = utcnow()
    one_year_ago = now - timedelta(days=365)

    # 매칭 데이터 (최근 1년)
    matched_count = db.scalar(
        select(func.count(BidAnnouncement.id)).where(
            BidAnnouncement.bid_ntce_no.in_(
                select(BidResult.bid_ntce_no).where(BidResult.rl_openg_dt >= one_year_ago)
            )
        )
    )

    announce_by_month = _build_monthly_counts(
        db,
        select(BidAnnouncement.id, BidAnnouncement.bid_ntce_dt).where(
            BidAnnouncement.bid_ntce_dt >= one_year_ago
        ),
        BidAnnouncement.bid_ntce_dt,
    )
    result_by_month = _build_monthly_counts(
        db,
        select(BidResult.id, BidResult.rl_openg_dt).where(BidResult.rl_openg_dt >= one_year_ago),
        BidResult.rl_openg_dt,
    )

    amount_expr = _announcement_amount_expr(db)
    agency_announce = db.execute(
        select(
            BidAnnouncement.dminstt_nm,
            func.sum(amount_expr).label("total_base_amount"),
            func.count(BidAnnouncement.id).label("cnt"),
        )
        .where(BidAnnouncement.bid_ntce_dt >= one_year_ago, BidAnnouncement.dminstt_nm.is_not(None))
        .group_by(BidAnnouncement.dminstt_nm)
        .order_by(func.sum(amount_expr).desc())
        .limit(10)
    ).all()

    announcement_total_amount = int(announcement_summary.total_amount or 0)

    data = {
        "announce_count": announcement_summary.total_count or 0,
        "announce_total_base_amount": announcement_total_amount,
        "announce_total_prce": announcement_total_amount,
        "result_count": result_summary.total_count or 0,
        "result_total_amt": int(result_summary.total_amount or 0),
        "matched_count": int(matched_count or 0),
        "announce_by_month": announce_by_month,
        "result_by_month": result_by_month,
        "agency_announce_top10": [
            {
                "name": row.dminstt_nm,
                "total_base_amount": int(row.total_base_amount or 0),
                "total_prce": int(row.total_base_amount or 0),
                "count": row.cnt,
            }
            for row in agency_announce
        ],
    }

    is_stale = getattr(announcement_summary, "is_stale", False) or getattr(
        result_summary, "is_stale", False
    )
    ttl = COMPARE_STATS_STALE_CACHE_TTL if is_stale else COMPARE_STATS_CACHE_TTL
    cache.set(cache_key, data, ttl)
    return data


def warm_dashboard_stats_cache(db: Session) -> dict[str, Any]:
    """대시보드 첫 진입 전 기본 통계를 미리 적재합니다."""
    return get_dashboard_stats(db)


def warm_compare_stats_cache(db: Session) -> dict[str, Any]:
    """비교 분석 첫 진입 전 비교 통계를 미리 적재합니다."""
    return get_compare_stats_data(db)


def warm_dashboard_caches(db: Session) -> dict[str, Any]:
    """수집 직후 대시보드/비교 분석 통계를 모두 적재합니다."""
    return {
        "dashboard_stats": warm_dashboard_stats_cache(db),
        "compare_stats": warm_compare_stats_cache(db),
    }


__all__ = [
    "DASHBOARD_RESULT_SCOPE_LABEL",
    "SUMMARY_ALGORITHM_VERSIONS",
    "enqueue_rebuild_dataset_summary",
    "get_bid_dataset_summary",
    "get_compare_stats_data",
    "get_dashboard_stats",
    "rebuild_bid_dataset_summaries",
    "rebuild_bid_dataset_summary",
    "warm_compare_stats_cache",
    "warm_dashboard_caches",
    "warm_dashboard_stats_cache",
]

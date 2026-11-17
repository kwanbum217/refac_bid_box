"""
src/app/services/home_summary.py

한 화면 메인의 요약 값을 만듭니다.

| 지표 | 조건 |
| --- | --- |
| 정확도 | 서빙 버전과 일치하는 사이드카 실측 `rmse`, 없으면 `source_metrics.rmse` |
| 최근 365일 | `category='Servc'` AND `bid_ntce_dt >= now-365일` 의 최신 차수 공고 수 |
| 입찰 중 | `category='Servc'` AND `bid_clse_dt >= now` AND `bid_ntce_dt >= now-90일` |
| 마감 구간 | 위 입찰 중 공고를 KST 날짜 기준 오늘/1~3일/4~7일/8일 이후로 나눈 수 |
| 내 조건 | 관심 업종·지역에 맞는 입찰 중 용역 공고 수와 마감 임박 순 목록 |

최신 차수 판정은 같은 공고번호의 더 새 차수 존재 여부를 인덱스로 확인하는
`bid_queries.similar_announcement_latest_filter` 를 씁니다. 테이블 전체에
`row_number()` 를 계산하던 `latest_announcement_filter` 는 결과는 같지만
요청 경로에서 수 분이 걸려 쓰지 않습니다.
관심 조건 셈·목록은 `bid_preferences` 의 함수를 그대로 호출하며 두 함수는
같은 조건 함수를 공유합니다.

365일·입찰 중 건수와 마감 구간은 대형 테이블 집계라 요청 경로에서 세지
않습니다. worker 의 10분 예열 작업이 캐시를 채우고, 캐시가 비어 있으면 화면은
'집계 중' 을 보여 줍니다. 정확도는 서빙 메타데이터를 매 요청 읽어 모델 교체가
화면에 바로 반영되게 합니다.
"""

from __future__ import annotations

import json
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from src.app.core.cache import cache
from src.app.core.timeutil import kst_now
from src.app.models.bids import BidAnnouncement
from src.app.services.bid_preferences import (
    BidPreferenceView,
    count_open_servc_matching,
    get_bid_preferences,
    list_open_servc_matching,
)
from src.app.services.bid_queries import similar_announcement_latest_filter
from src.ml.model_registry import resolve_serving_tree
from src.ml.promotion import METRICS_ROOT, SERVING_ROOT, load_serving_metrics

SERVC_CATEGORY = "Servc"
SERVC_MODEL_NAME = "servc_institution_v1"

RECENT_YEAR_DAYS = 365
OPEN_BID_LOOKBACK_DAYS = 90

# KST 날짜 기준 마감 구간입니다. 화면 순서와 인덱스가 같아야 합니다.
OPEN_DEADLINE_BUCKETS: tuple[tuple[str, str], ...] = (
    ("today", "오늘 마감"),
    ("d1_3", "1~3일"),
    ("d4_7", "4~7일"),
    ("d8_plus", "8일 이후"),
)

SERVIC_COUNTS_CACHE_KEY = "home:summary:servc_counts:v1"
# 예열 주기(10분)의 12배입니다. 예열이 한두 번 실패해도 화면이 비지 않습니다.
SERVIC_COUNTS_CACHE_TTL = 2 * 60 * 60


def _to_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number


def _serving_metadata(serving_root: Path) -> dict[str, Any]:
    """서빙 트리의 metadata.json 을 읽습니다. 없거나 깨졌으면 빈 dict 입니다."""
    meta_path = resolve_serving_tree(serving_root / SERVC_MODEL_NAME) / "metadata.json"
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return meta if isinstance(meta, dict) else {}


def _promoted_date(meta: dict[str, Any]) -> str | None:
    """metadata.json 의 승격일을 화면 표기 형식으로 돌려줍니다.

    날짜가 없거나 형식이 깨졌으면 None 이고, 화면은 날짜 없이 문구를 만듭니다.
    """
    promoted_at = meta.get("promoted_at")
    if not isinstance(promoted_at, str) or not promoted_at:
        return None
    try:
        return datetime.fromisoformat(promoted_at).strftime("%Y-%m-%d")
    except ValueError:
        return None


def _measured_rmse(version: str, metrics_dir: Path) -> float | None:
    """서빙 버전과 일치하는 사이드카 실측 rmse 입니다.

    버전이 다르거나 파일이 없거나 형식이 깨졌으면 None 이며 호출부는
    metadata.json 의 `source_metrics` 로 물러납니다.
    """
    sidecar = metrics_dir / f"{SERVC_MODEL_NAME}.json"
    try:
        measured = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(measured, dict) or str(measured.get("version") or "") != version:
        return None
    metrics = measured.get("metrics")
    return _to_float(metrics.get("rmse")) if isinstance(metrics, dict) else None


def load_serving_accuracy(
    serving_dir: Path | str | None = None,
    metrics_dir: Path | str | None = None,
) -> dict[str, Any]:
    """서빙 중인 용역 모델의 실측 오차를 화면 표시 형태로 돌려줍니다.

    사이드카의 실측값이 서빙 버전과 일치하면 그것을 씁니다. 없거나 버전이
    다르면 승격이 기록한 metadata.json 의 `source_metrics` 로 물러납니다.
    읽지 못하면 available=False 이며 화면은 '측정값 준비 중' 을 보여 줍니다.
    """
    serving_root = Path(SERVING_ROOT) if serving_dir is None else Path(serving_dir)
    metrics_root = Path(METRICS_ROOT) if metrics_dir is None else Path(metrics_dir)
    meta = _serving_metadata(serving_root)

    version = str(meta.get("version") or "")
    rmse = _measured_rmse(version, metrics_root) if version else None
    if rmse is None:
        _version, metrics = load_serving_metrics(SERVC_MODEL_NAME, serving_dir=serving_root)
        rmse = _to_float(metrics.get("rmse")) if isinstance(metrics, dict) else None
    if rmse is None:
        return {"available": False, "rmse_display": None, "promoted_date": None}
    return {
        "available": True,
        "rmse_display": f"{rmse:.2f}",
        "promoted_date": _promoted_date(meta),
    }


def _count_recent_year_servc(db: Session, now_dt: datetime) -> int:
    stmt = (
        select(func.count())
        .select_from(BidAnnouncement)
        .where(
            BidAnnouncement.category == SERVC_CATEGORY,
            BidAnnouncement.bid_ntce_dt >= now_dt - timedelta(days=RECENT_YEAR_DAYS),
        )
    )
    return int(db.scalar(similar_announcement_latest_filter(stmt)) or 0)


def _open_servc_filters(now_dt: datetime) -> tuple[Any, ...]:
    """입찰 중 용역 공고를 고르는 공통 조건입니다.

    건수와 마감 구간이 같은 조건을 쓰도록 한 곳에 둡니다. 두 값이 서로 다른
    조건으로 계산되면 구간 합과 전체 건수가 어긋납니다.
    """
    return (
        BidAnnouncement.category == SERVC_CATEGORY,
        BidAnnouncement.bid_clse_dt >= now_dt,
        BidAnnouncement.bid_ntce_dt >= now_dt - timedelta(days=OPEN_BID_LOOKBACK_DAYS),
    )


def _count_open_servc(db: Session, now_dt: datetime) -> int:
    stmt = select(func.count()).select_from(BidAnnouncement).where(*_open_servc_filters(now_dt))
    return int(db.scalar(similar_announcement_latest_filter(stmt)) or 0)


def _open_deadline_buckets(db: Session, now_dt: datetime) -> list[dict[str, Any]]:
    """입찰 중 공고를 KST 날짜 기준 마감 구간 네 개로 나눠 셉니다.

    GROUP BY 한 번으로 세고, 같은 조건이라 네 구간 합은 `_count_open_servc`
    결과와 같습니다. DB 가 UTC naive 를 쓰지만 나라장터 원문 컬럼은 KST naive
    이므로 now_dt 도 KST 기준입니다.
    """
    today_start = datetime.combine(now_dt.date(), time.min)
    day1_start = today_start + timedelta(days=1)
    day4_start = today_start + timedelta(days=4)
    day8_start = today_start + timedelta(days=8)

    bucket_expr = case(
        (BidAnnouncement.bid_clse_dt < day1_start, 0),
        (BidAnnouncement.bid_clse_dt < day4_start, 1),
        (BidAnnouncement.bid_clse_dt < day8_start, 2),
        else_=3,
    )
    stmt = (
        select(bucket_expr.label("deadline_bucket"), func.count())
        .select_from(BidAnnouncement)
        .where(*_open_servc_filters(now_dt))
    )
    stmt = similar_announcement_latest_filter(stmt).group_by(bucket_expr)

    counts = {int(index): int(count) for index, count in db.execute(stmt).all()}
    return [
        {"key": key, "label": label, "count": counts.get(index, 0)}
        for index, (key, label) in enumerate(OPEN_DEADLINE_BUCKETS)
    ]


def _servc_counts(
    db: Session, now_dt: datetime, *, use_cache: bool
) -> tuple[int | None, int | None, list[dict[str, Any]] | None]:
    """캐시된 건수·마감 구간을 돌려주고, 캐시가 없으면 집계하지 않습니다.

    use_cache=False 인 시험 경로만 즉시 집계합니다. 요청 경로에서 이 집계를
    동기로 돌리면 대형 테이블 질의가 요청을 수 분 붙잡습니다. 마감 구간이 없는
    옛 캐시는 건수만 쓰고 구간은 None 으로 두어 화면이 막대를 그리지 않습니다.
    """
    if use_cache:
        cached = cache.get(SERVIC_COUNTS_CACHE_KEY)
        if isinstance(cached, dict):
            recent_year = cached.get("recent_year_count")
            open_count = cached.get("open_count")
            if isinstance(recent_year, int) and isinstance(open_count, int):
                buckets = cached.get("open_deadline_buckets")
                return (
                    recent_year,
                    open_count,
                    buckets if isinstance(buckets, list) else None,
                )
        return None, None, None

    recent_year = _count_recent_year_servc(db, now_dt)
    open_count = _count_open_servc(db, now_dt)
    return recent_year, open_count, _open_deadline_buckets(db, now_dt)


def get_home_summary(
    db: Session,
    user_id: int | None = None,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """메인 한 화면이 쓰는 요약 문맥을 만듭니다.

    now 를 넘기면 캐시를 건너뛰고 즉시 집계합니다. 시험이 기준 시각을 고정할 때
    씁니다. 운영 요청 경로에서는 now 가 None 이므로 캐시만 읽고, 캐시가 비어
    있으면 건수를 None 으로 두어 화면이 '집계 중' 을 보여 줍니다.
    """
    now_dt = now or kst_now()
    recent_year_count, open_count, open_deadline_buckets = _servc_counts(
        db, now_dt, use_cache=now is None
    )

    prefs: BidPreferenceView | None = get_bid_preferences(db, user_id) if user_id else None
    has_preferences = prefs is not None and not prefs.is_empty
    matching_count: int | None = None
    matching_bids: list[dict[str, Any]] = []
    matching_license_codes: list[str] = []
    matching_region_code = ""
    if has_preferences and prefs is not None:
        matching_count = count_open_servc_matching(db, prefs, now=now)
        matching_bids = list_open_servc_matching(db, prefs, now=now)
        matching_license_codes = list(prefs.license_codes)
        matching_region_code = prefs.region_code

    return {
        "accuracy": load_serving_accuracy(),
        "recent_year_count": recent_year_count,
        "open_count": open_count,
        "open_deadline_buckets": open_deadline_buckets,
        "has_preferences": has_preferences,
        "matching_count": matching_count,
        "matching_bids": matching_bids,
        "matching_license_codes": matching_license_codes,
        "matching_region_code": matching_region_code,
    }


def warm_home_summary_cache(db: Session) -> dict[str, Any]:
    """365일·입찰 중 건수와 마감 구간을 집계해 캐시에 채웁니다. worker 전용입니다."""
    now_dt = kst_now()
    recent_year_count = _count_recent_year_servc(db, now_dt)
    open_count = _count_open_servc(db, now_dt)
    open_deadline_buckets = _open_deadline_buckets(db, now_dt)
    payload: dict[str, Any] = {
        "recent_year_count": recent_year_count,
        "open_count": open_count,
        "open_deadline_buckets": open_deadline_buckets,
    }
    cache.set(SERVIC_COUNTS_CACHE_KEY, payload, SERVIC_COUNTS_CACHE_TTL)
    return payload

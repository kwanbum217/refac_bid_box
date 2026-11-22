"""
src/app/services/home_summary.py

한 화면 메인의 요약 값을 만듭니다.

| 지표 | 조건 |
| --- | --- |
| 정확도 | 서빙 버전과 일치하는 사이드카 실측값, 없으면 `source_metrics` |
| 승격 추이 | `generations/*/metadata.json` 의 `source_metrics` 세대별 값 |
| 입찰 중 | `category='Servc'` AND `bid_clse_dt >= now` AND `bid_ntce_dt >= now-90일` AND 4대 업종 |
| 마감 구간 | 위 입찰 중 공고를 KST 날짜 기준 오늘/1~3일/4~7일/8일 이후로 나눈 수 |
| 내 조건 | 관심 업종·지역에 맞는 입찰 중 용역 공고 수와 마감 임박 순 목록 |

입찰 중 건수와 마감 구간은 `bid_queries.BID_INDUSTRY_CODES`(파견·경비업·
위생관리용역업·유료직업소개업)에 해당하는 공고만 셉니다. 업종 판정은 같은
모듈의 `license_match_clause` EXISTS 절을 쓰므로 공고 탐색 목록과 정의가
같습니다. 두 값은 같은 조건 함수를 공유해 구간 합이 항상 건수와 같습니다.

최신 차수 판정은 같은 공고번호의 더 새 차수 존재 여부를 인덱스로 확인하는
`bid_queries.similar_announcement_latest_filter` 를 씁니다. 테이블 전체에
`row_number()` 를 계산하던 `latest_announcement_filter` 는 결과는 같지만
요청 경로에서 수 분이 걸려 쓰지 않습니다.
관심 조건 셈·목록은 `bid_preferences` 의 함수를 그대로 호출하며 두 함수는
같은 조건 함수를 공유합니다.

입찰 중 건수와 마감 구간은 대형 테이블 집계라 요청 경로에서 세지 않습니다.
worker 의 10분 예열 작업이 캐시를 채우고, 캐시가 비어 있으면 화면은 '집계 중'
을 보여 줍니다. 정확도는 서빙 메타데이터를 매 요청 읽어 모델 교체가 화면에
바로 반영되게 합니다.
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
from src.app.services.bid_queries import (
    BID_INDUSTRY_CODES,
    license_match_clause,
    similar_announcement_latest_filter,
)
from src.ml.model_registry import resolve_serving_tree
from src.ml.promotion import METRICS_ROOT, SERVING_ROOT, load_serving_metrics

SERVC_CATEGORY = "Servc"
SERVC_MODEL_NAME = "servc_institution_v1"

OPEN_BID_LOOKBACK_DAYS = 90

# KST 날짜 기준 마감 구간입니다. 화면 순서와 인덱스가 같아야 합니다.
OPEN_DEADLINE_BUCKETS: tuple[tuple[str, str], ...] = (
    ("today", "오늘 마감"),
    ("d1_3", "1~3일"),
    ("d4_7", "4~7일"),
    ("d8_plus", "8일 이후"),
)

# 4대 업종 한정으로 셈 정의가 바뀌어 v2 로 올립니다. v1 캐시에는 전체 용역
# 집계값이 남아 있을 수 있으므로 키를 분리해야 옛 값이 화면에 섞이지 않습니다.
SERVIC_COUNTS_CACHE_KEY = "home:summary:servc_counts:v2"
# 예열 주기(10분)의 12배입니다. 예열이 한두 번 실패해도 화면이 비지 않습니다.
SERVIC_COUNTS_CACHE_TTL = 2 * 60 * 60


def _to_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number


def _rounded(value: Any, digits: int = 4) -> float | None:
    """지표 파일 값을 그래프 전송용으로 자릅니다. 값이 없으면 None 입니다."""
    number = _to_float(value)
    return None if number is None else round(number, digits)


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


def _measured_metrics(version: str, metrics_dir: Path) -> dict[str, Any] | None:
    """서빙 버전과 일치하는 사이드카 실측 묶음입니다.

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
    if not isinstance(metrics, dict) or _to_float(metrics.get("rmse")) is None:
        return None
    return measured


def _tile(key: str, label: str, value: str, unit: str, note: str) -> dict[str, str]:
    """정확도 지표 타일 한 칸입니다. 값은 모두 지표 파일에서 읽은 것입니다."""
    return {"key": key, "label": label, "value": value, "unit": unit, "note": note}


def _accuracy_tiles(
    metrics: dict[str, Any],
    interval: dict[str, Any],
    measured: dict[str, Any] | None,
) -> list[dict[str, str]]:
    """확보된 값만 타일로 만듭니다. 없는 값은 타일 자체를 만들지 않습니다."""
    tiles: list[dict[str, str]] = []
    rmse = _to_float(metrics.get("rmse"))
    if rmse is not None:
        tiles.append(_tile("rmse", "RMSE", f"{rmse:.2f}", "%p", "낙찰률 예측 평균 오차"))
    mae = _to_float(metrics.get("mae"))
    if mae is not None:
        tiles.append(_tile("mae", "MAE", f"{mae:.2f}", "%p", "낙찰률 예측 절대 오차"))
    r2 = _to_float(metrics.get("r2"))
    if r2 is not None:
        tiles.append(_tile("r2", "설명력 R2", f"{r2 * 100:.1f}", "%", "낙찰률 변동 설명 비율"))

    target = _to_float(interval.get("target_coverage"))
    if target is not None:
        calibration = interval.get("calibration_samples")
        note = "예측구간 적중률 목표"
        if isinstance(calibration, int) and not isinstance(calibration, bool):
            note += f" · 보정 표본 {calibration:,}건"
        tiles.append(_tile("coverage", "구간 적중률", f"{target * 100:.0f}", "%", note))

    samples = measured.get("samples") if isinstance(measured, dict) else None
    holdout_since = measured.get("holdout_since") if isinstance(measured, dict) else None
    if isinstance(samples, int) and not isinstance(samples, bool):
        note = "검증 표본"
        if isinstance(holdout_since, str) and holdout_since:
            note += f" · {holdout_since} 이후"
        tiles.append(_tile("validation", "검증 표본", f"{samples:,}", "건", note))
    return tiles


def _generation_rows(serving_root: Path) -> list[dict[str, Any]]:
    """승격 세대 metadata.json 에서 추이 그래프에 쓸 실제 지표만 모읍니다.

    세대 순서는 promoted_at 입니다. rmse 가 없는 세대는 그래프에서 뺍니다.
    """
    generations = serving_root / SERVC_MODEL_NAME / "generations"
    try:
        entries = sorted(generations.iterdir())
    except OSError:
        return []

    rows: list[dict[str, Any]] = []
    for entry in entries:
        if not entry.is_dir():
            continue
        try:
            meta = json.loads((entry / "metadata.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(meta, dict):
            continue
        source = meta.get("source_metrics")
        if not isinstance(source, dict):
            continue
        rmse = _to_float(source.get("rmse"))
        if rmse is None:
            continue
        rows.append(
            {
                "version": str(meta.get("version") or entry.name),
                "promoted_at": str(meta.get("promoted_at") or ""),
                "date": _promoted_date(meta) or "",
                "rmse": round(rmse, 4),
                "mape": _rounded(source.get("mape")),
                "r2": _rounded(source.get("r2")),
            }
        )
    rows.sort(key=lambda row: (row["promoted_at"], row["version"]))
    return rows


def _accuracy_chart(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """승격 세대별 오차 추이를 Chart.js 가 읽을 형태로 만듭니다.

    세대가 두 개 미만이면 그릴 추이가 없으므로 visible=False 이고 화면은
    그래프 영역을 숨깁니다.
    """
    hidden = {"visible": False, "labels": [], "versions": [], "series": [], "note": ""}
    if len(rows) < 2:
        return hidden

    series: list[dict[str, Any]] = [
        {
            "key": "rmse",
            "label": "RMSE",
            "unit": "%p",
            "data": [row["rmse"] for row in rows],
        }
    ]
    mape_data = [row["mape"] for row in rows]
    if sum(1 for value in mape_data if value is not None) >= 2:
        series.append({"key": "mape", "label": "MAPE", "unit": "%", "data": mape_data})

    return {
        "visible": True,
        "labels": [row["date"] or row["version"] for row in rows],
        "versions": [row["version"] for row in rows],
        "series": series,
        "note": "승격 세대별 검증 지표(source_metrics)",
    }


def load_serving_accuracy(
    serving_dir: Path | str | None = None,
    metrics_dir: Path | str | None = None,
) -> dict[str, Any]:
    """서빙 중인 용역 모델의 실측 오차와 승격 추이를 돌려줍니다.

    사이드카의 실측값이 서빙 버전과 일치하면 그것을 씁니다. 없거나 버전이
    다르면 승격이 기록한 metadata.json 의 `source_metrics` 로 물러납니다.
    그래프는 세대 metadata 의 `source_metrics` 만 쓰며, 읽지 못하면
    available=False 이고 화면은 '측정값 준비 중' 을 보여 줍니다.
    """
    serving_root = Path(SERVING_ROOT) if serving_dir is None else Path(serving_dir)
    metrics_root = Path(METRICS_ROOT) if metrics_dir is None else Path(metrics_dir)
    meta = _serving_metadata(serving_root)

    version = str(meta.get("version") or "")
    measured = _measured_metrics(version, metrics_root) if version else None
    measured_metrics = measured.get("metrics") if isinstance(measured, dict) else None
    if isinstance(measured_metrics, dict):
        metrics: dict[str, Any] = measured_metrics
        source = "measured"
    else:
        _version, served = load_serving_metrics(SERVC_MODEL_NAME, serving_dir=serving_root)
        metrics = served if isinstance(served, dict) else {}
        source = "promoted"
        measured = None

    rmse = _to_float(metrics.get("rmse"))
    if rmse is None:
        return {
            "available": False,
            "source": None,
            "source_label": None,
            "version": version or None,
            "rmse_display": None,
            "promoted_date": None,
            "tiles": [],
            "chart": _accuracy_chart([]),
        }

    interval = meta.get("interval")
    return {
        "available": True,
        "source": source,
        "source_label": "운영 경로 실측" if source == "measured" else "승격 시 검증 지표",
        "version": version or None,
        "rmse_display": f"{rmse:.2f}",
        "promoted_date": _promoted_date(meta),
        "tiles": _accuracy_tiles(metrics, interval if isinstance(interval, dict) else {}, measured),
        "chart": _accuracy_chart(_generation_rows(serving_root)),
    }


def _open_servc_filters(now_dt: datetime) -> tuple[Any, ...]:
    """입찰 중 4대 업종 용역 공고를 고르는 공통 조건입니다.

    건수와 마감 구간이 같은 조건을 쓰도록 한 곳에 둡니다. 업종은
    `BID_INDUSTRY_CODES`(파견·경비업·위생관리용역업·유료직업소개업)에 한정하며,
    공고 탐색 목록과 같은 `license_match_clause` EXISTS 절로 판정합니다.
    두 값이 서로 다른 조건으로 계산되면 구간 합과 전체 건수가 어긋납니다.
    """
    return (
        BidAnnouncement.category == SERVC_CATEGORY,
        BidAnnouncement.bid_clse_dt >= now_dt,
        BidAnnouncement.bid_ntce_dt >= now_dt - timedelta(days=OPEN_BID_LOOKBACK_DAYS),
        license_match_clause(BID_INDUSTRY_CODES),
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
) -> tuple[int | None, list[dict[str, Any]] | None]:
    """캐시된 입찰 중 건수·마감 구간을 돌려주고, 없으면 집계하지 않습니다.

    use_cache=False 인 시험 경로만 즉시 집계합니다. 요청 경로에서 이 집계를
    동기로 돌리면 대형 테이블 질의가 요청을 수 분 붙잡습니다. 마감 구간이 없는
    옛 캐시는 건수만 쓰고 구간은 None 으로 두어 화면이 막대를 그리지 않습니다.
    """
    if use_cache:
        cached = cache.get(SERVIC_COUNTS_CACHE_KEY)
        if isinstance(cached, dict):
            open_count = cached.get("open_count")
            if isinstance(open_count, int):
                buckets = cached.get("open_deadline_buckets")
                return open_count, buckets if isinstance(buckets, list) else None
        return None, None

    return _count_open_servc(db, now_dt), _open_deadline_buckets(db, now_dt)


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
    open_count, open_deadline_buckets = _servc_counts(db, now_dt, use_cache=now is None)

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
        "open_count": open_count,
        "open_deadline_buckets": open_deadline_buckets,
        "has_preferences": has_preferences,
        "matching_count": matching_count,
        "matching_bids": matching_bids,
        "matching_license_codes": matching_license_codes,
        "matching_region_code": matching_region_code,
    }


def warm_home_summary_cache(db: Session) -> dict[str, Any]:
    """4대 업종 입찰 중 건수와 마감 구간을 집계해 캐시에 채웁니다. worker 전용입니다."""
    now_dt = kst_now()
    open_count = _count_open_servc(db, now_dt)
    open_deadline_buckets = _open_deadline_buckets(db, now_dt)
    payload: dict[str, Any] = {
        "open_count": open_count,
        "open_deadline_buckets": open_deadline_buckets,
    }
    cache.set(SERVIC_COUNTS_CACHE_KEY, payload, SERVIC_COUNTS_CACHE_TTL)
    return payload

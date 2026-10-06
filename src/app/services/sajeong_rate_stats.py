"""
src/app/services/sajeong_rate_stats.py

`bid_prearng_prices` 에서 발주처별 사정률 분포를 `institution_sajeong_rate_stats`
로 재집계하고, (수요기관명, category) 로 최저/최상 사정률을 조회합니다.

사정률의 정의는 설계 정본과 같습니다: `plnprc / bssamt * 100` (NUMERIC(10,4)).
대체 순서는 institution -> region(시·도) -> category 이며, 표본이 최소치에
못 미치면 다음 순위로 내려갑니다. 최소 표본은 institution 30, region 50 입니다.

API 응답에는 지역 정보가 없어 발주처명에서 시·도를 유도합니다. 매핑에 실패하면
category 로 떨어집니다. 이 표는 선택된 scope 의 min_rate/max_rate 를 그대로
최저가·최상가 근거로 쓰기 위한 것이며, 평가 엔진 연결은 이 모듈 범위 밖입니다.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import delete, select

from src.app.core.timeutil import utcnow
from src.app.models.prearng_prices import BidPrearngPrice, InstitutionSajeongRateStat
from src.app.services.demand_institutions import SIDO_ALIASES, SIDO_CODES

DEFAULT_WINDOW_DAYS = 1095
MIN_INSTITUTION_SAMPLES = 30
MIN_REGION_SAMPLES = 50

SCOPE_INSTITUTION = "institution"
SCOPE_REGION = "region"
SCOPE_CATEGORY = "category"
SCOPE_NONE = "none"

_RATE_QUANTUM = Decimal("0.0001")


def derive_sido(institution_name: str | None) -> str | None:
    """발주처명에서 현행 시·도 명칭을 유도합니다. 판별 불가면 None 입니다.

    옛 도명·통합시 명칭은 `SIDO_ALIASES` 로 정규화합니다. 기관명에 시·도 명칭이
    포함되면 매칭하며, 여러 개가 걸리면 가장 긴 이름을 고릅니다.
    """
    if not institution_name:
        return None
    normalized = " ".join(str(institution_name).strip().split())
    if not normalized:
        return None
    for alias, current in SIDO_ALIASES.items():
        if alias in normalized:
            return current
    matches = [name for name in SIDO_CODES if name in normalized]
    if not matches:
        return None
    return max(matches, key=len)


def _quantize_rate(value: float | Decimal | None) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value)).quantize(_RATE_QUANTUM, rounding=ROUND_HALF_UP)


def _percentile(sorted_values: list[float], quantile: float) -> float | None:
    """선형 보간 백분위수. 빈 목록이면 None 입니다."""
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return sorted_values[0]
    position = (len(sorted_values) - 1) * quantile
    lower = int(position)
    upper = min(lower + 1, len(sorted_values) - 1)
    fraction = position - lower
    return sorted_values[lower] * (1.0 - fraction) + sorted_values[upper] * fraction


def _stat_row(
    *,
    scope: str,
    institution_name: str,
    category: str,
    values: list[float],
    window_days: int,
    rebuilt_at: Any,
) -> dict[str, Any]:
    ordered = sorted(values)
    return {
        "scope": scope,
        "institution_name": institution_name or "",
        "category": category or "",
        "window_days": window_days,
        "sample_count": len(ordered),
        "min_rate": _quantize_rate(ordered[0]),
        "max_rate": _quantize_rate(ordered[-1]),
        "p10_rate": _quantize_rate(_percentile(ordered, 0.10)),
        "p50_rate": _quantize_rate(_percentile(ordered, 0.50)),
        "p90_rate": _quantize_rate(_percentile(ordered, 0.90)),
        "rebuilt_at": rebuilt_at,
    }


def rebuild_institution_sajeong_rate_stats(
    session: Any,
    *,
    window_days: int = DEFAULT_WINDOW_DAYS,
    min_institution_samples: int = MIN_INSTITUTION_SAMPLES,
    min_region_samples: int = MIN_REGION_SAMPLES,
) -> dict[str, Any]:
    """`institution_sajeong_rate_stats` 를 통째로 다시 만듭니다.

    institution -> region(시·도) -> category 세 scope 를 한 번의 스캔으로 만듭니다.
    표본이 최소치 미만인 institution/region 은 행을 만들지 않아 조회가 다음
    순위로 대체됩니다. category scope 는 최소 표본 없이 만듭니다.
    """
    cutoff = utcnow() - timedelta(days=window_days)
    stmt = (
        select(
            BidPrearngPrice.dminstt_nm,
            BidPrearngPrice.category,
            BidPrearngPrice.sajeong_rate,
        )
        .where(
            BidPrearngPrice.sajeong_rate.is_not(None),
            BidPrearngPrice.bssamt > 0,
            BidPrearngPrice.rl_openg_dt.is_not(None),
            BidPrearngPrice.rl_openg_dt >= cutoff,
        )
        .order_by(
            BidPrearngPrice.dminstt_nm,
            BidPrearngPrice.category,
            BidPrearngPrice.sajeong_rate,
        )
    )

    institution_groups: dict[tuple[str, str], list[float]] = {}
    region_groups: dict[tuple[str, str], list[float]] = {}
    category_groups: dict[str, list[float]] = {}

    for name, category, rate in session.execute(stmt).yield_per(10_000):
        if rate is None:
            continue
        value = float(rate)
        category_key = str(category or "")
        if name:
            institution_groups.setdefault((str(name), category_key), []).append(value)
            sido = derive_sido(str(name))
            if sido:
                region_groups.setdefault((sido, category_key), []).append(value)
        category_groups.setdefault(category_key, []).append(value)

    rebuilt_at = utcnow()
    rows: list[dict[str, Any]] = []
    for (name, category_key), values in institution_groups.items():
        if len(values) >= min_institution_samples:
            rows.append(
                _stat_row(
                    scope=SCOPE_INSTITUTION,
                    institution_name=name,
                    category=category_key,
                    values=values,
                    window_days=window_days,
                    rebuilt_at=rebuilt_at,
                )
            )
    for (sido, category_key), values in region_groups.items():
        if len(values) >= min_region_samples:
            rows.append(
                _stat_row(
                    scope=SCOPE_REGION,
                    institution_name=sido,
                    category=category_key,
                    values=values,
                    window_days=window_days,
                    rebuilt_at=rebuilt_at,
                )
            )
    for category_key, values in category_groups.items():
        if values:
            rows.append(
                _stat_row(
                    scope=SCOPE_CATEGORY,
                    institution_name="",
                    category=category_key,
                    values=values,
                    window_days=window_days,
                    rebuilt_at=rebuilt_at,
                )
            )

    session.execute(delete(InstitutionSajeongRateStat))
    if rows:
        session.bulk_insert_mappings(InstitutionSajeongRateStat, rows)
    session.commit()

    return {
        "rows": len(rows),
        "institution_rows": sum(1 for row in rows if row["scope"] == SCOPE_INSTITUTION),
        "region_rows": sum(1 for row in rows if row["scope"] == SCOPE_REGION),
        "category_rows": sum(1 for row in rows if row["scope"] == SCOPE_CATEGORY),
        "window_days": window_days,
        "rebuilt_at": rebuilt_at.isoformat(),
    }


def lookup_sajeong_rate_range(
    institution_name: str | None,
    category: str | None,
    *,
    session: Any = None,
    window_days: int = DEFAULT_WINDOW_DAYS,
) -> dict[str, Any]:
    """(수요기관명, category) 의 사정률 범위를 대체 순서로 조회합니다.

    institution -> region(시·도) -> category 순으로 찾고, 없으면 scope='none' 을
    돌려줍니다. 최저가·최상가는 선택된 scope 의 min_rate/max_rate 입니다.
    """
    result: dict[str, Any] = {
        "scope": SCOPE_NONE,
        "institution_name": "",
        "min_rate": None,
        "max_rate": None,
        "sample_count": 0,
        "window_days": window_days,
    }
    if session is None:
        return result

    category_key = str(category or "")
    name = " ".join(str(institution_name or "").split())
    sido = derive_sido(name)

    candidates: list[tuple[str, str]] = []
    if name:
        candidates.append((SCOPE_INSTITUTION, name))
    if sido:
        candidates.append((SCOPE_REGION, sido))
    candidates.append((SCOPE_CATEGORY, ""))

    for scope, scope_name in candidates:
        row = session.execute(
            select(
                InstitutionSajeongRateStat.min_rate,
                InstitutionSajeongRateStat.max_rate,
                InstitutionSajeongRateStat.sample_count,
            ).where(
                InstitutionSajeongRateStat.scope == scope,
                InstitutionSajeongRateStat.institution_name == scope_name,
                InstitutionSajeongRateStat.category == category_key,
                InstitutionSajeongRateStat.window_days == window_days,
            )
        ).one_or_none()
        if row is None or not row.sample_count:
            continue
        return {
            "scope": scope,
            "institution_name": scope_name,
            "min_rate": row.min_rate,
            "max_rate": row.max_rate,
            "sample_count": int(row.sample_count),
            "window_days": window_days,
        }
    return result

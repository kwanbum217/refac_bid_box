"""협상에의한계약 변종별 과거 낙찰률 참고 분포 집계."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from statistics import median
from typing import Any

from sqlalchemy import Integer, cast, func, select
from sqlalchemy.orm import Session

from src.app.core.cache import cache
from src.app.models.bids import BidAnnouncement, BidResult

NEGOTIATION_STATS_CACHE_TTL = 60 * 60 * 24
NEGOTIATION_STATS_ALGORITHM_VERSION = "v1-20260526"
_MIN_RATE = Decimal("50")
_MAX_RATE = Decimal("110")
_VARIANT_MARKERS = {
    "STANDARD": "",
    "SW": "(SW사업)",
    "ENGINEERING": "(엔지니어링)",
    "CONSTRUCTION_ENGINEERING": "(건설엔지니어링)",
}


def _cache_key(variant: str) -> str:
    return f"negotiation_stats:{NEGOTIATION_STATS_ALGORITHM_VERSION}:{variant}"


def _round_rate(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def _normalized_ord(db: Session):
    """차수를 세 자리로 정규화합니다. MySQL에서는 명세대로 LPAD를 사용합니다."""
    dialect = db.get_bind().dialect.name
    if dialect == "mysql":
        return func.lpad(BidResult.bid_ntce_ord, 3, "0")
    return func.printf("%03d", cast(BidResult.bid_ntce_ord, Integer))


def _rows(db: Session, variant: str) -> list[tuple[Any, Any]]:
    marker = _VARIANT_MARKERS.get(variant)
    if marker is None:
        return []
    method = func.json_unquote(func.json_extract(BidAnnouncement.raw_data, "$.sucsfbidMthdNm"))
    if db.get_bind().dialect.name != "mysql":
        method = func.json_extract(BidAnnouncement.raw_data, "$.sucsfbidMthdNm")
    stmt = (
        select(BidResult.sucsf_bid_amt, BidAnnouncement.base_amount)
        .join(
            BidAnnouncement,
            (BidAnnouncement.bid_ntce_no == BidResult.bid_ntce_no)
            & (BidAnnouncement.category == BidResult.category)
            & (_normalized_ord(db) == BidAnnouncement.bid_ntce_ord),
        )
        .where(
            BidAnnouncement.category == "Servc",
            BidAnnouncement.bid_ntce_dt >= "2026-05-26",
            method.startswith("협상에의한계약"),
            *(
                [method.contains(marker)]
                if marker
                else [
                    ~method.contains("(SW사업)"),
                    ~method.contains("(엔지니어링)"),
                    ~method.contains("(건설엔지니어링)"),
                ]
            ),
            BidResult.sucsf_bid_amt.is_not(None),
            BidAnnouncement.base_amount.is_not(None),
            BidAnnouncement.base_amount > 0,
        )
    )
    return [tuple(row) for row in db.execute(stmt).all()]


def get_negotiation_stats(db: Session, variant: str) -> dict[str, Any]:
    """변종의 유효 낙찰률 분포를 반환하며 결과를 24시간 캐시합니다."""
    key = _cache_key(variant)
    cached = cache.get(key)
    if cached is not None:
        return cached

    rates: list[Decimal] = []
    for awarded, base in _rows(db, variant):
        if awarded is None or base is None:
            continue
        rate = Decimal(str(awarded)) / Decimal(str(base)) * Decimal("100")
        if _MIN_RATE <= rate <= _MAX_RATE:
            rates.append(rate)

    if rates:
        result: dict[str, Any] = {
            "valid_count": len(rates),
            "average": _round_rate(sum(rates, Decimal("0")) / len(rates)),
            "median": _round_rate(Decimal(str(median(rates)))),
            "minimum": _round_rate(min(rates)),
            "maximum": _round_rate(max(rates)),
        }
    else:
        result = {
            "valid_count": 0,
            "average": None,
            "median": None,
            "minimum": None,
            "maximum": None,
        }
    cache.set(key, result, NEGOTIATION_STATS_CACHE_TTL)
    return result

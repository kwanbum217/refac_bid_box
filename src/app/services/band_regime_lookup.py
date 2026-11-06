"""
src/app/services/band_regime_lookup.py

`bid_announcement_regime` 에 저장된 첨부 판별 결과를 규칙 해석 호출부가 읽는 조회 계층.

판별은 `band_regime_classifier`, 해석은 `evaluation_rules` 가 정본이며, 이 모듈은 저장된
행을 공고 키(공고번호·차수·업무구분)로 찾아 `CLASSIFIED` 인 갈래만 돌려줍니다. 판별 행이
없거나 `FAILED`·`NO_ATTACHMENT` 이거나 요청한 차수의 행이 없으면 `None` 이며, 다른 차수로
대체하지 않습니다. 조회 실패는 해석을 막지 않도록 `None` 으로 처리하고 로그만 남깁니다.

설계 정본: `.orca/ref/band_2to1_attachment_classifier_design_20261106.md` 4.2절.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any

from sqlalchemy import select
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session

from src.app.models.announcement_regime import (
    REGIME_STATUS_CLASSIFIED,
    BidAnnouncementRegime,
)

logger = logging.getLogger(__name__)

RegimeKey = tuple[str, str, str]

# 공고번호 IN 조건이 지나치게 길어지지 않도록 한 번에 조회할 번호 수를 제한합니다.
REGIME_LOOKUP_CHUNK_SIZE = 500

LookupExecutor = Session | Connection


def _clean(value: Any) -> str:
    return str(value or "").strip()


def regime_key(bid_ntce_no: Any, bid_ntce_ord: Any, category: Any) -> RegimeKey:
    """공고 키를 조회용 튜플로 맞춥니다."""
    return (_clean(bid_ntce_no), _clean(bid_ntce_ord), _clean(category))


def attachment_regime_key(bid: Any) -> RegimeKey:
    """공고 객체(또는 같은 컬럼을 가진 행)에서 조회 키를 만듭니다."""
    return regime_key(bid.bid_ntce_no, bid.bid_ntce_ord, bid.category)


def lookup_attachment_regimes(
    db: LookupExecutor,
    keys: Iterable[RegimeKey],
) -> dict[RegimeKey, str]:
    """키 여러 개의 판별 갈래를 한 번에 조회해 `CLASSIFIED` 결과만 돌려줍니다.

    원장·목록처럼 여러 공고를 한 번에 판정하는 경로에서 공고별 단건 조회로 늘어나는
    쿼리를 막습니다. 요청 키와 정확히 일치하는 행만 담고, 없는 키는 결과에서 빠집니다.
    """
    wanted = {regime_key(*key) for key in keys}
    wanted = {key for key in wanted if all(key)}
    if not wanted:
        return {}

    numbers = sorted({key[0] for key in wanted})
    categories = sorted({key[2] for key in wanted})
    found: dict[RegimeKey, str] = {}
    for start in range(0, len(numbers), REGIME_LOOKUP_CHUNK_SIZE):
        chunk = numbers[start : start + REGIME_LOOKUP_CHUNK_SIZE]
        stmt = select(
            BidAnnouncementRegime.bid_ntce_no,
            BidAnnouncementRegime.bid_ntce_ord,
            BidAnnouncementRegime.category,
            BidAnnouncementRegime.regime,
        ).where(
            BidAnnouncementRegime.bid_ntce_no.in_(chunk),
            BidAnnouncementRegime.category.in_(categories),
            BidAnnouncementRegime.status == REGIME_STATUS_CLASSIFIED,
        )
        for row in db.execute(stmt):
            key = regime_key(row.bid_ntce_no, row.bid_ntce_ord, row.category)
            if key in wanted:
                found[key] = row.regime
    return found


def lookup_attachment_regime(
    db: LookupExecutor,
    bid_ntce_no: str | None,
    bid_ntce_ord: str | None,
    category: str | None,
) -> str | None:
    """판별 상태가 `CLASSIFIED` 인 같은 차수·업무구분 행의 갈래를 돌려줍니다.

    행이 없거나 `FAILED`·`NO_ATTACHMENT` 이면 `None` 입니다. 차수가 다르면 다른 행을
    대신 쓰지 않습니다.
    """
    key = regime_key(bid_ntce_no, bid_ntce_ord, category)
    if not all(key):
        return None
    return lookup_attachment_regimes(db, (key,)).get(key)


def lookup_attachment_regime_for_bid(db: LookupExecutor, bid: Any) -> str | None:
    """공고 객체로 저장된 판별 갈래를 조회하고, 실패는 `None` 으로 삼킵니다.

    판별 결과는 계산을 바꾸는 보조 입력이므로, 조회 실패가 적격심사 API 자체를 깨뜨리지
    않도록 기존 해석 경로로 되돌립니다.
    """
    try:
        return lookup_attachment_regime(
            db,
            bid_ntce_no=bid.bid_ntce_no,
            bid_ntce_ord=bid.bid_ntce_ord,
            category=bid.category,
        )
    except Exception:
        logger.warning(
            "첨부 판별 갈래 조회에 실패해 판별 없이 해석합니다: %s",
            getattr(bid, "bid_ntce_no", None),
            exc_info=True,
        )
        return None

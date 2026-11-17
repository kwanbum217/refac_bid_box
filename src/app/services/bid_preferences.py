"""
src/app/services/bid_preferences.py

회원 관심 업종(면허)·지역 저장과 '현재 입찰 중인 용역 공고 수·목록' 조회.

셈·목록 조건은 공고 탐색 목록의 DB 경로(src/app/services/bid_queries.py 의
list_announcements)와 같습니다. 업종·지역 코드 정의와 정규화도 그 모듈의
함수를 그대로 씁니다.

| 조건 | 값 |
| --- | --- |
| 분야 | `Servc` |
| 마감 | `bid_clse_dt >= now` (마감 전) |
| 차수 | 최신 차수만 (`similar_announcement_latest_filter`) |
| 업종 | 관심 코드 중 하나라도 참가자격에 포함 |
| 지역 | 참가가능지역이 관심 지역과 일치 |
| 스캔 범위 | `bid_ntce_dt >= now - 90일` (ix_bid_ann_cat_dt) |

건수와 목록은 같은 조건 함수를 공유해 서로 다른 공고를 고를 수 없습니다.
업종·지역이 모두 비어 있으면 셈하지 않고 0 또는 빈 목록을 돌려줍니다.
호출자는 BidPreferenceView.is_empty 로 입력 안내를 띄울 수 있습니다.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.app.core.cache import cache
from src.app.core.timeutil import kst_now
from src.app.models.bid_preferences import AccountBidPreference
from src.app.models.bids import BidAnnouncement
from src.app.services.bid_queries import (
    BID_INDUSTRY_CODE_SET,
    _participation_region_match_clause,
    license_match_clause,
    normalize_license_codes,
    normalize_region_code,
    similar_announcement_latest_filter,
)

OPEN_BID_CATEGORY = "Servc"
# 마감 전 공고만 세지만, 오래된 공고까지 훑지 않도록 공고일 하한을 둡니다.
OPEN_BID_LOOKBACK_DAYS = 90
OPEN_BID_COUNT_CACHE_TTL = 60 * 10
OPEN_BID_COUNT_CACHE_PREFIX = "bid_prefs:open_servc_count:v1"
OPEN_BID_LIST_CACHE_PREFIX = "bid_prefs:open_servc_list:v1"
OPEN_BID_LIST_DEFAULT_LIMIT = 5


@dataclass(frozen=True)
class BidPreferenceView:
    """화면과 서비스가 함께 쓰는 관심 조건."""

    license_codes: list[str]
    region_code: str

    @property
    def is_empty(self) -> bool:
        """업종·지역이 모두 비어 있어 메인에서 입력 안내가 필요한 상태."""
        return not self.license_codes and not self.region_code


def _view_from_row(row: AccountBidPreference | None) -> BidPreferenceView | None:
    if row is None:
        return None
    codes = [code for code in (row.license_codes or []) if isinstance(code, str)]
    return BidPreferenceView(license_codes=codes, region_code=row.region_code or "")


def get_bid_preferences(db: Session, user_id: int) -> BidPreferenceView | None:
    """저장된 관심 조건을 읽습니다. 아직 저장한 적이 없으면 None 입니다."""
    row = db.execute(
        select(AccountBidPreference).where(AccountBidPreference.user_id == user_id)
    ).scalar_one_or_none()
    return _view_from_row(row)


def _normalized_codes(license_codes: Iterable[str] | str | None) -> list[str]:
    if isinstance(license_codes, str):
        raw = license_codes
    else:
        raw = ",".join(code for code in (license_codes or []) if code)
    # 공고 탐색 업종 필터와 같은 정규화를 거치고, 그 정의 밖 코드는 버립니다.
    return [code for code in normalize_license_codes(raw) if code in BID_INDUSTRY_CODE_SET]


def save_bid_preferences(
    db: Session,
    user_id: int,
    license_codes: Iterable[str] | str | None,
    region_code: str | None,
) -> BidPreferenceView:
    """관심 조건을 정규화해 저장하고, 커밋은 호출자에게 맡깁니다.

    회사 프로필 수정과 같은 트랜잭션에서 호출되도록 flush 만 합니다.
    """
    codes = _normalized_codes(license_codes)
    region = normalize_region_code(region_code)
    row = db.execute(
        select(AccountBidPreference).where(AccountBidPreference.user_id == user_id)
    ).scalar_one_or_none()
    if row is None:
        row = AccountBidPreference(user_id=user_id, license_codes=codes, region_code=region)
        db.add(row)
    else:
        row.license_codes = codes
        row.region_code = region
    db.flush()
    return BidPreferenceView(license_codes=list(codes), region_code=region)


def _prefs_cache_suffix(prefs: BidPreferenceView) -> str:
    return f"{','.join(prefs.license_codes)}:{prefs.region_code}"


def _count_cache_key(prefs: BidPreferenceView) -> str:
    return f"{OPEN_BID_COUNT_CACHE_PREFIX}:{_prefs_cache_suffix(prefs)}"


def _list_cache_key(prefs: BidPreferenceView, limit: int) -> str:
    return f"{OPEN_BID_LIST_CACHE_PREFIX}:{_prefs_cache_suffix(prefs)}:{limit}"


def _open_matching_conditions(prefs: BidPreferenceView, now_dt: datetime) -> list[Any]:
    """건수와 목록이 함께 쓰는 입찰 중·관심 조건입니다.

    두 함수가 각자 조건을 조립하면 한쪽만 바뀌어 서로 다른 공고를 고를 수
    있으므로 조건은 이 함수 한 곳에서만 만듭니다.
    """
    conditions: list[Any] = [
        BidAnnouncement.category == OPEN_BID_CATEGORY,
        BidAnnouncement.bid_clse_dt >= now_dt,
        BidAnnouncement.bid_ntce_dt >= now_dt - timedelta(days=OPEN_BID_LOOKBACK_DAYS),
    ]
    if prefs.region_code:
        conditions.append(_participation_region_match_clause(prefs.region_code))
    if prefs.license_codes:
        conditions.append(license_match_clause(prefs.license_codes))
    return conditions


def _matching_row_view(row: Any, now_dt: datetime) -> dict[str, Any]:
    close_dt = row.bid_clse_dt
    days_left = (close_dt.date() - now_dt.date()).days if close_dt else 0
    return {
        "id": row.id,
        "bid_ntce_nm": row.bid_ntce_nm or "공고명 없음",
        "dminstt_nm": row.dminstt_nm or "-",
        "deadline_label": close_dt.strftime("%Y.%m.%d %H:%M") if close_dt else "-",
        "dday_label": "오늘 마감" if days_left <= 0 else f"D-{days_left}",
    }


def count_open_servc_matching(
    db: Session,
    prefs: BidPreferenceView | None,
    now: datetime | None = None,
) -> int:
    """저장된 관심 조건에 맞는 현재 입찰 중인 용역 공고 수를 셉니다.

    now 를 넘기지 않으면 KST 현재 시각을 쓰고 결과를 10분 캐시합니다. 시험처럼
    기준 시각을 고정할 때는 now 를 넘겨 캐시를 건너뜁니다.
    """
    if prefs is None or prefs.is_empty:
        return 0

    now_dt = now or kst_now()
    cache_key = _count_cache_key(prefs)
    if now is None:
        cached = cache.get(cache_key)
        if isinstance(cached, int):
            return cached

    stmt = (
        select(func.count())
        .select_from(BidAnnouncement)
        .where(*_open_matching_conditions(prefs, now_dt))
    )
    stmt = similar_announcement_latest_filter(stmt)

    count = int(db.scalar(stmt) or 0)
    if now is None:
        cache.set(cache_key, count, OPEN_BID_COUNT_CACHE_TTL)
    return count


def list_open_servc_matching(
    db: Session,
    prefs: BidPreferenceView | None,
    limit: int = OPEN_BID_LIST_DEFAULT_LIMIT,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """관심 조건에 맞는 입찰 중 용역 공고를 마감 임박 순으로 돌려줍니다.

    조건은 count_open_servc_matching 과 같은 함수를 쓰고, 캐시도 같은 10분
    정책입니다. now 를 넘기면 캐시를 건너뜁니다. 화면이 바로 쓰도록 캐시에
    넣을 수 있는 원시값(dict)만 돌려줍니다.
    """
    if prefs is None or prefs.is_empty:
        return []

    now_dt = now or kst_now()
    cache_key = _list_cache_key(prefs, limit)
    if now is None:
        cached = cache.get(cache_key)
        if isinstance(cached, list):
            return cached

    stmt = (
        select(
            BidAnnouncement.id,
            BidAnnouncement.bid_ntce_nm,
            BidAnnouncement.dminstt_nm,
            BidAnnouncement.bid_clse_dt,
        )
        .where(*_open_matching_conditions(prefs, now_dt))
        .order_by(BidAnnouncement.bid_clse_dt.asc(), BidAnnouncement.id.asc())
        .limit(limit)
    )
    stmt = similar_announcement_latest_filter(stmt)

    items = [_matching_row_view(row, now_dt) for row in db.execute(stmt).all()]
    if now is None:
        cache.set(cache_key, items, OPEN_BID_COUNT_CACHE_TTL)
    return items

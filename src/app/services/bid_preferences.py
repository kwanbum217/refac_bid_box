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
| 공고종류 | 최신 차수가 `취소공고` 인 번호 제외 (NULL·재공고·변경공고 유지) |
| 업종 | 관심 코드 중 하나라도 참가자격에 포함 |
| 지역 | 참가가능지역이 관심 지역과 일치 |
| 스캔 범위 | `bid_ntce_dt >= now - 90일` (ix_bid_ann_cat_dt) |

건수와 목록은 같은 조건 함수를 공유해 서로 다른 공고를 고를 수 없습니다.
업종·지역이 모두 비어 있으면 셈하지 않고 0 또는 빈 목록을 돌려줍니다.
호출자는 BidPreferenceView.is_empty 로 입력 안내를 띄울 수 있습니다.

집계는 대형 공고 테이블을 훑어 수십 초가 걸릴 수 있으므로 요청 경로에서
실행하지 않습니다. 기준 시각(now)을 넘기지 않는 호출은 신선 키(10분)를 읽고,
없으면 보관 키(24시간)의 마지막 성공 값을 씁니다. 두 키 모두 worker 예열
(warm_open_servc_matching)이 채웁니다. 시험처럼 now 를 넘기거나
use_cache=False 를 주면 그 자리에서 집계합니다.
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
    not_cancelled_clause,
    similar_announcement_latest_filter,
)

OPEN_BID_CATEGORY = "Servc"
# 마감 전 공고만 세지만, 오래된 공고까지 훑지 않도록 공고일 하한을 둡니다.
OPEN_BID_LOOKBACK_DAYS = 90
OPEN_BID_COUNT_CACHE_TTL = 60 * 10
# 신선 키가 만료돼도 화면이 '집계 중' 으로 비지 않도록 마지막 성공 값을
# 24시간 보관합니다. worker 예열이 한두 번 실패해도 마지막 값을 이어 씁니다.
OPEN_BID_STALE_CACHE_TTL = 24 * 60 * 60
# 취소공고 제외 조건이 붙은 뒤 v2 입니다. v1 키에는 취소 행이 포함된 값이 남아
# 있으므로 접두사를 올려 옛 값을 읽지 않게 합니다.
OPEN_BID_COUNT_CACHE_PREFIX = "bid_prefs:open_servc_count:v2"
OPEN_BID_LIST_CACHE_PREFIX = "bid_prefs:open_servc_list:v2"
OPEN_BID_COUNT_STALE_CACHE_PREFIX = "bid_prefs:open_servc_count:stale:v2"
OPEN_BID_LIST_STALE_CACHE_PREFIX = "bid_prefs:open_servc_list:stale:v2"
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


def _count_stale_cache_key(prefs: BidPreferenceView) -> str:
    return f"{OPEN_BID_COUNT_STALE_CACHE_PREFIX}:{_prefs_cache_suffix(prefs)}"


def _list_stale_cache_key(prefs: BidPreferenceView, limit: int) -> str:
    return f"{OPEN_BID_LIST_STALE_CACHE_PREFIX}:{_prefs_cache_suffix(prefs)}:{limit}"


def _open_matching_conditions(prefs: BidPreferenceView, now_dt: datetime) -> list[Any]:
    """건수와 목록이 함께 쓰는 입찰 중·관심 조건입니다.

    두 함수가 각자 조건을 조립하면 한쪽만 바뀌어 서로 다른 공고를 고를 수
    있으므로 조건은 이 함수 한 곳에서만 만듭니다.
    """
    conditions: list[Any] = [
        BidAnnouncement.category == OPEN_BID_CATEGORY,
        BidAnnouncement.bid_clse_dt >= now_dt,
        BidAnnouncement.bid_ntce_dt >= now_dt - timedelta(days=OPEN_BID_LOOKBACK_DAYS),
        not_cancelled_clause(),
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


def _query_open_servc_count(db: Session, prefs: BidPreferenceView, now_dt: datetime) -> int:
    """관심 조건에 맞는 입찰 중 공고를 즉시 셉니다. worker·시험 전용입니다."""
    stmt = (
        select(func.count())
        .select_from(BidAnnouncement)
        .where(*_open_matching_conditions(prefs, now_dt))
    )
    stmt = similar_announcement_latest_filter(stmt)
    return int(db.scalar(stmt) or 0)


def _query_open_servc_list(
    db: Session,
    prefs: BidPreferenceView,
    limit: int,
    now_dt: datetime,
) -> list[dict[str, Any]]:
    """관심 조건 목록을 즉시 조회합니다. worker·시험 전용입니다."""
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
    return [_matching_row_view(row, now_dt) for row in db.execute(stmt).all()]


def _store_open_servc_count(prefs: BidPreferenceView, count: int) -> None:
    cache.set(_count_cache_key(prefs), count, OPEN_BID_COUNT_CACHE_TTL)
    cache.set(_count_stale_cache_key(prefs), count, OPEN_BID_STALE_CACHE_TTL)


def _store_open_servc_list(
    prefs: BidPreferenceView, limit: int, items: list[dict[str, Any]]
) -> None:
    cache.set(_list_cache_key(prefs, limit), items, OPEN_BID_COUNT_CACHE_TTL)
    cache.set(_list_stale_cache_key(prefs, limit), items, OPEN_BID_STALE_CACHE_TTL)


def read_cached_open_servc_count(prefs: BidPreferenceView | None) -> int | None:
    """신선 키, 없으면 보관 키의 건수를 읽습니다. 집계는 하지 않습니다."""
    if prefs is None or prefs.is_empty:
        return 0
    fresh = cache.get(_count_cache_key(prefs))
    if isinstance(fresh, int):
        return fresh
    stale = cache.get(_count_stale_cache_key(prefs))
    return stale if isinstance(stale, int) else None


def read_cached_open_servc_list(
    prefs: BidPreferenceView | None,
    limit: int = OPEN_BID_LIST_DEFAULT_LIMIT,
) -> list[dict[str, Any]] | None:
    """신선 키, 없으면 보관 키의 목록을 읽습니다. 집계는 하지 않습니다."""
    if prefs is None or prefs.is_empty:
        return []
    fresh = cache.get(_list_cache_key(prefs, limit))
    if isinstance(fresh, list):
        return fresh
    stale = cache.get(_list_stale_cache_key(prefs, limit))
    return stale if isinstance(stale, list) else None


def stored_bid_preference_views(db: Session) -> list[BidPreferenceView]:
    """저장된 관심 조건을 서로 다른 조건별로 한 번씩 돌려줍니다.

    같은 업종·지역을 여러 계정이 쓰면 집계 캐시 키도 같으므로 한 번만
    예열하면 됩니다. 입력 안내만 필요한 빈 조건은 건너뜁니다.
    """
    rows = db.execute(select(AccountBidPreference).order_by(AccountBidPreference.id)).scalars()
    views: list[BidPreferenceView] = []
    seen: set[str] = set()
    for row in rows:
        view = _view_from_row(row)
        if view is None or view.is_empty:
            continue
        suffix = _prefs_cache_suffix(view)
        if suffix in seen:
            continue
        seen.add(suffix)
        views.append(view)
    return views


def warm_open_servc_matching(
    db: Session,
    prefs: BidPreferenceView | None,
    now: datetime | None = None,
    limit: int = OPEN_BID_LIST_DEFAULT_LIMIT,
) -> None:
    """한 관심 조건의 건수·목록을 집계해 신선 키와 보관 키를 함께 채웁니다.

    worker 예열 전용입니다. 요청 경로에서는 부르지 않습니다.
    """
    if prefs is None or prefs.is_empty:
        return
    now_dt = now or kst_now()
    count = _query_open_servc_count(db, prefs, now_dt)
    items = _query_open_servc_list(db, prefs, limit, now_dt)
    _store_open_servc_count(prefs, count)
    _store_open_servc_list(prefs, limit, items)


def warm_stored_bid_preference(db: Session, user_id: int) -> BidPreferenceView | None:
    """한 사용자의 저장된 관심 조건만 예열하고 그 조건을 돌려줍니다.

    마이페이지 저장 직후 arq 작업이 부릅니다. 조건이 없거나 비어 있으면
    아무것도 하지 않고 None 을 돌려줍니다.
    """
    prefs = get_bid_preferences(db, user_id)
    if prefs is None or prefs.is_empty:
        return None
    warm_open_servc_matching(db, prefs)
    return prefs


def count_open_servc_matching(
    db: Session,
    prefs: BidPreferenceView | None,
    now: datetime | None = None,
    *,
    use_cache: bool = True,
) -> int | None:
    """저장된 관심 조건에 맞는 현재 입찰 중인 용역 공고 수를 돌려줍니다.

    now 를 넘기지 않고 use_cache=True 이면 캐시만 읽고, 신선 키가 없으면
    보관 키를 씁니다. 둘 다 없으면 None 이며 집계하지 않습니다. 시험처럼
    기준 시각을 고정하거나 use_cache=False 를 주면 그 자리에서 집계합니다.
    """
    if prefs is None or prefs.is_empty:
        return 0

    if use_cache and now is None:
        return read_cached_open_servc_count(prefs)

    now_dt = now or kst_now()
    count = _query_open_servc_count(db, prefs, now_dt)
    _store_open_servc_count(prefs, count)
    return count


def list_open_servc_matching(
    db: Session,
    prefs: BidPreferenceView | None,
    limit: int = OPEN_BID_LIST_DEFAULT_LIMIT,
    now: datetime | None = None,
    *,
    use_cache: bool = True,
) -> list[dict[str, Any]] | None:
    """관심 조건에 맞는 입찰 중 용역 공고를 마감 임박 순으로 돌려줍니다.

    조건은 count_open_servc_matching 과 같은 함수를 쓰고, 캐시 정책도 같습니다.
    now 를 넘기지 않고 use_cache=True 이면 캐시만 읽고, 둘 다 없으면 None 입니다.
    화면이 바로 쓰도록 캐시에 넣을 수 있는 원시값(dict)만 돌려줍니다.
    """
    if prefs is None or prefs.is_empty:
        return []

    if use_cache and now is None:
        return read_cached_open_servc_list(prefs, limit)

    now_dt = now or kst_now()
    items = _query_open_servc_list(db, prefs, limit, now_dt)
    _store_open_servc_list(prefs, limit, items)
    return items

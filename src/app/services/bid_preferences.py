"""
src/app/services/bid_preferences.py

회원 관심 업종(면허)·지역 저장과 '현재 입찰 중인 용역 공고 수' 셈.

셈 조건은 공고 탐색 목록의 DB 경로(src/app/services/bid_queries.py 의
list_announcements)와 같습니다. 업종·지역 코드 정의와 정규화도 그 모듈의
함수를 그대로 씁니다.

| 조건 | 값 |
| --- | --- |
| 분야 | `Servc` |
| 마감 | `bid_clse_dt >= now` (마감 전) |
| 차수 | 최신 차수만 (`latest_announcement_filter`) |
| 업종 | 관심 코드 중 하나라도 참가자격에 포함 |
| 지역 | 참가가능지역이 관심 지역과 일치 |
| 스캔 범위 | `bid_ntce_dt >= now - 90일` (ix_bid_ann_cat_dt) |

업종·지역이 모두 비어 있으면 셈하지 않고 0 을 돌려줍니다. 호출자는
BidPreferenceView.is_empty 로 입력 안내를 띄울 수 있습니다.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from src.app.core.cache import cache
from src.app.core.timeutil import kst_now
from src.app.models.bid_preferences import AccountBidPreference
from src.app.models.bid_restrictions import BidAnnouncementLicenseLimit
from src.app.models.bids import BidAnnouncement
from src.app.services.bid_queries import (
    BID_INDUSTRY_CODE_SET,
    _participation_region_match_clause,
    latest_announcement_filter,
    normalize_license_codes,
    normalize_region_code,
)

OPEN_BID_CATEGORY = "Servc"
# 마감 전 공고만 세지만, 오래된 공고까지 훑지 않도록 공고일 하한을 둡니다.
OPEN_BID_LOOKBACK_DAYS = 90
OPEN_BID_COUNT_CACHE_TTL = 60 * 10
OPEN_BID_COUNT_CACHE_PREFIX = "bid_prefs:open_servc_count:v1"


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


def _license_match_clause(codes: list[str]) -> Any:
    """업종 코드 중 하나라도 참가자격에 포함되는 공고만 통과시킵니다.

    bid_queries.list_announcements 의 업종 필터 절과 같은 조건입니다. 그 절은
    함수로 분리돼 있지 않고 bid_queries 는 이 과업에서 수정하지 않으므로 같은
    식을 여기에 둡니다. 두 곳이 어긋나면
    tests/test_bid_preferences_20261111.py 가 공고 탐색 결과와 대조해 잡습니다.
    """
    like_clauses: list[Any] = []
    for code in codes:
        pattern = f"%/{code}%"
        like_clauses.append(BidAnnouncementLicenseLimit.lcns_lmt_nm.like(pattern))
        like_clauses.append(BidAnnouncementLicenseLimit.permsn_indstryty_list.like(pattern))
    return (
        select(1)
        .where(
            BidAnnouncementLicenseLimit.bid_ntce_no == BidAnnouncement.bid_ntce_no,
            BidAnnouncementLicenseLimit.bid_ntce_ord == BidAnnouncement.bid_ntce_ord,
            or_(*like_clauses),
        )
        .exists()
    )


def _count_cache_key(prefs: BidPreferenceView) -> str:
    return f"{OPEN_BID_COUNT_CACHE_PREFIX}:{','.join(prefs.license_codes)}:{prefs.region_code}"


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
        .where(
            BidAnnouncement.category == OPEN_BID_CATEGORY,
            BidAnnouncement.bid_clse_dt >= now_dt,
            BidAnnouncement.bid_ntce_dt >= now_dt - timedelta(days=OPEN_BID_LOOKBACK_DAYS),
        )
    )
    if prefs.region_code:
        stmt = stmt.where(_participation_region_match_clause(prefs.region_code))
    if prefs.license_codes:
        stmt = stmt.where(_license_match_clause(prefs.license_codes))
    stmt = latest_announcement_filter(stmt)

    count = int(db.scalar(stmt) or 0)
    if now is None:
        cache.set(cache_key, count, OPEN_BID_COUNT_CACHE_TTL)
    return count

"""시각 유틸리티.

DB 의 DateTime 컬럼은 두 계열로 나뉩니다. 앱이 쓰는 컬럼은 UTC naive 이고,
나라장터 원문에서 온 컬럼은 원문 벽시계 시각인 KST naive 입니다.
기존 데이터와의 비교 연산이 깨지지 않도록 두 계열 모두 naive 를 유지합니다.
"""

from datetime import UTC, date, datetime, timedelta


def utcnow() -> datetime:
    """UTC 기준 naive datetime 을 반환합니다.

    Python 3.12 에서 폐기 예고된 datetime.utcnow() 의 대체이며 반환값은 동일합니다.
    """
    return datetime.now(UTC).replace(tzinfo=None)


def kst_now(base_utc: datetime | None = None) -> datetime:
    """KST 기준 naive datetime 을 반환합니다.

    한국은 일광절약시간이 없어 고정 +9시간으로 계산합니다. base_utc 를 주면 그
    UTC naive 시각을 기준으로 변환하며, 생략하면 utcnow() 를 씁니다. 나라장터
    원문에서 온 컬럼(KST naive)과 비교할 때 사용합니다.
    """
    base = utcnow() if base_utc is None else base_utc
    return base + timedelta(hours=9)


def kst_today(base_utc: datetime | None = None) -> date:
    """KST 달력 기준 오늘 날짜를 반환합니다.

    원문 날짜 체계(나라장터 API 질의일, 원문 계열 날짜 컬럼)와 비교할 때 사용합니다.
    """
    return kst_now(base_utc).date()

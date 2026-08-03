"""시각 유틸리티.

DB 의 DateTime 컬럼은 timezone 정보를 담지 않으며 UTC naive 값을 저장합니다.
기존 데이터와의 비교 연산이 깨지지 않도록 naive 를 유지합니다.
"""

from datetime import UTC, datetime


def utcnow() -> datetime:
    """UTC 기준 naive datetime 을 반환합니다.

    Python 3.12 에서 폐기 예고된 datetime.utcnow() 의 대체이며 반환값은 동일합니다.
    """
    return datetime.now(UTC).replace(tzinfo=None)

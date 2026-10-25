"""수집 데이터에 없는 입찰 항목 질문을 고정 안내로 돌리는 가드.

사정률, 낙찰하한율 실측, 경쟁률, 참가업체 수, 투찰자, 지역·업종 제한,
유찰 상태는 현재 수집 스키마에 해당 컬럼이 없습니다. 이런 질문을 다른
수치나 다른 조회 축으로 대체 해석하지 않도록 검색·도구·LLM 호출 전에
판정하고, 항목별 고정 안내 문구를 반환합니다.
"""

from __future__ import annotations

import re
import unicodedata

DATA_GAP_MESSAGES: dict[str, str] = {
    "사정률": (
        "사정률은 현재 수집하는 입찰 데이터에 포함되어 있지 않아 정확한 값을 "
        "알려드릴 수 없습니다. 대신 평균 낙찰률, 낙찰 건수, 업체별 낙찰 건수는 "
        "조회할 수 있습니다."
    ),
    "낙찰하한율": (
        "낙찰하한율은 현재 수집하는 입찰 데이터에 포함되어 있지 않아 정확한 값을 "
        "알려드릴 수 없습니다. 대신 공고별 낙찰률, 평균 낙찰률, 낙찰 건수는 "
        "조회할 수 있습니다."
    ),
    "경쟁률": (
        "경쟁률은 현재 수집하는 입찰 데이터에 포함되어 있지 않아 정확한 값을 "
        "알려드릴 수 없습니다. 대신 평균 낙찰률, 낙찰 건수, 수요기관 지역별 "
        "공고 건수는 조회할 수 있습니다."
    ),
    "참가업체 수": (
        "참가업체 수는 현재 수집하는 입찰 데이터에 포함되어 있지 않아 정확한 값을 "
        "알려드릴 수 없습니다. 대신 업체별 낙찰 건수, 최근 낙찰 결과, 수요기관 "
        "지역별 공고 건수는 조회할 수 있습니다."
    ),
    "투찰자·참여 업체": (
        "투찰자·참여 업체 정보는 현재 수집하는 입찰 데이터에 포함되어 있지 않아 "
        "정확한 값을 알려드릴 수 없습니다. 대신 낙찰업체 기준 업체별 낙찰 건수, "
        "최근 낙찰 결과, 업체 순위는 조회할 수 있습니다."
    ),
    "지역 제한·업종 제한 참가자격": (
        "지역 제한·업종 제한 참가자격 정보는 현재 수집하는 입찰 데이터에 포함되어 "
        "있지 않아 정확한 값을 알려드릴 수 없습니다. 대신 수요기관 지역별 공고 건수, "
        "공고 목록, 낙찰 건수는 조회할 수 있습니다."
    ),
    "유찰 상태": (
        "유찰 상태 정보는 현재 수집하는 입찰 데이터에 포함되어 있지 않아 정확한 "
        "값을 알려드릴 수 없습니다. 대신 최근 공고 목록, 낙찰 건수, 수요기관 "
        "지역별 공고 건수는 조회할 수 있습니다."
    ),
}

_DEFLATION_RATE = re.compile(r"사정\s*[률율]")

_LOWER_RATE = re.compile(r"(?:낙찰\s*)?하한율")

# 제도·개념 설명은 수집 데이터 없이도 답할 수 있습니다. 실측·평균·추이·적용
# 사례처럼 데이터 값이 필요한 표현이 있을 때만 미보유로 판정합니다.
_RATE_ACTUAL_VALUE = re.compile(
    r"평균|실측|추이|적용된|적용한|적용\s*공고|통계|분포|공고별|건별|"
    r"넘는|이상|이하|미만|높은|낮은|상위|하위|\d+\s*%"
)

_RATE_DEFINITION = re.compile(r"뭐야|뭔가요|무엇|뜻|의미|이란|설명|계산|개념|정의|기준")

_COMPETITION = re.compile(r"경쟁률|경쟁(?:\s*이|\s*은|\s*도)?\s*치열")

_PARTICIPANT_COUNT = re.compile(r"참가\s*업체|참여\s*업체|투찰\s*업체")

_BIDDER_HISTORY = re.compile(r"참여한\s*입찰|참여\s*입찰|투찰\s*내역|투찰\s*이력|투찰자")

_QUALIFICATION_RESTRICTION = re.compile(
    r"지역\s*제한|지역\s*업체만|지역업체만|업체만\s*참여|"
    r"업종\s*제한|참가자격|참가\s*자격\s*제한|면허\s*필요|면허\s*필수"
)

_VOID_STATUS = re.compile(r"유찰된|유찰\s*건|유찰\s*상태|유찰\s*후|유찰\s*공고")


def _normalize_request(message: str) -> str:
    """NFC 정규화와 소문자 변환만 수행합니다."""
    return unicodedata.normalize("NFC", message or "").lower()


def detect_data_gap(message: str) -> str | None:
    """수집 데이터에 없는 항목 질문이면 항목 이름을, 아니면 None 을 반환합니다.

    항목 이름은 `DATA_GAP_MESSAGES` 의 키와 같습니다. 판정은 원문 기준이며
    다른 축의 필터로 대체 해석하지 않습니다.
    """
    normalized = _normalize_request(message)
    if not normalized.strip():
        return None

    if _DEFLATION_RATE.search(normalized):
        if _RATE_ACTUAL_VALUE.search(normalized) or not _RATE_DEFINITION.search(normalized):
            return "사정률"
        return None
    if _LOWER_RATE.search(normalized) and _RATE_ACTUAL_VALUE.search(normalized):
        return "낙찰하한율"
    if _COMPETITION.search(normalized):
        return "경쟁률"
    if _PARTICIPANT_COUNT.search(normalized):
        return "참가업체 수"
    if _BIDDER_HISTORY.search(normalized):
        return "투찰자·참여 업체"
    if _QUALIFICATION_RESTRICTION.search(normalized):
        return "지역 제한·업종 제한 참가자격"
    if _VOID_STATUS.search(normalized):
        return "유찰 상태"
    return None


__all__ = [
    "DATA_GAP_MESSAGES",
    "detect_data_gap",
]

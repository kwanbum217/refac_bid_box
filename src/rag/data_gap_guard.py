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

_DEFLATION_RATE = re.compile(r"사정[률율]")

_LOWER_RATE = re.compile(r"(?:낙찰)?하한율")

_COMPETITION = re.compile(r"경쟁률|경쟁(?:이|은|도)?치열")

_PARTICIPANT_COUNT = re.compile(r"(?:참가|참여|투찰)(?:한|된)?(?:업체|기업)")

_BIDDER_HISTORY = re.compile(
    r"투찰자|투찰한(?:입찰|공고)|참여한(?:입찰|공고)|참여내역|참여이력|"
    r"투찰내역|투찰이력|응찰"
)

_QUALIFICATION_RESTRICTION = re.compile(
    r"지역\s*제한|지역\s*업체만|업체만\s*참여|업종\s*제한|참가자격|"
    r"참가\s*자격\s*제한|참가\s*자격\s*조건|면허\s*필요|면허\s*필수"
)

_VOID_STATUS = re.compile(r"유찰")

# 제도·개념·정의 설명은 수집 데이터 없이도 답할 수 있습니다. 다만 평균·실측·
# 추이처럼 실제 값을 요구하는 표현이 함께 있으면 미보유 판정을 유지합니다.
_EXPLANATION = re.compile(
    r"제도|뜻|의미|정의|개념|뭐야|뭔가요|무엇|이란|설명|기준|방법|계산"
    r"|(?<![가-힣])란(?![가-힣])"
)

_ACTUAL_VALUE = re.compile(
    r"평균|실측|추이|적용된|적용한|적용\s*공고|통계|분포|공고별|건별|"
    r"넘는|이상|이하|미만|높은|낮은|상위|하위|건수|개수|몇\s*건|몇\s*개|"
    r"\d+\s*%|\d+\s*건"
)

# 사업명(공고명) 구 안에 들어간 낱말은 미보유 항목이 아닙니다.
# 예: "참가자격 심사 용역 공고", "경쟁률 분석 용역 낙찰 결과"
_PROJECT_HEAD_NOUNS = (
    "용역",
    "사업",
    "구매",
    "심사",
    "분석",
    "컨설팅",
    "연구",
    "방지",
    "개선",
)

_PROJECT_TAIL_LENGTH = 16

# 미보유 낱말과 사업 명사 사이에 끼는 수량 표현은 공고명 구를 끊지 않습니다.
# 예: "참가업체 수 분석 용역 공고"
_PROJECT_COUNTERS = re.compile(r"^(?:가지|개|건|수|곳|회|차)+")

_WHITESPACE = re.compile(r"\s+")

# (항목, 패턴, 공백 제거 문자열로 검사할지 여부)
# "참가 자격" 처럼 띄어 쓴 일반 자격 안내는 사업명·속성 판정과 구분해야 하므로
# 참가자격 항목만 원문 공백을 유지한 문자열로 검사합니다.
_ITEM_PATTERNS: tuple[tuple[str, tuple[re.Pattern[str], ...], bool], ...] = (
    ("사정률", (_DEFLATION_RATE,), True),
    ("낙찰하한율", (_LOWER_RATE,), True),
    ("경쟁률", (_COMPETITION,), True),
    ("참가업체 수", (_PARTICIPANT_COUNT,), True),
    ("투찰자·참여 업체", (_BIDDER_HISTORY,), True),
    ("지역 제한·업종 제한 참가자격", (_QUALIFICATION_RESTRICTION,), False),
    ("유찰 상태", (_VOID_STATUS,), True),
)


def _normalize_request(message: str) -> str:
    """NFC 정규화와 소문자 변환만 수행합니다."""
    return unicodedata.normalize("NFC", message or "").lower()


def _is_project_name_phrase(text: str, match: re.Match[str]) -> bool:
    """미보유 낱말 뒤에 사업 명사가 붙어 공고명 구를 이루는지 판정합니다.

    모든 미보유 항목에 같은 규칙을 적용합니다. 낱말 바로 뒤에 수량 표현이
    끼어도 사업 명사가 이어지면 공고명 구로 봅니다.
    """
    tail = _WHITESPACE.sub("", text[match.end() :])[:_PROJECT_TAIL_LENGTH]
    if tail.startswith(_PROJECT_HEAD_NOUNS):
        return True
    return _PROJECT_COUNTERS.sub("", tail).startswith(_PROJECT_HEAD_NOUNS)


def detect_data_gap(message: str) -> str | None:
    """수집 데이터에 없는 항목 질문이면 항목 이름을, 아니면 None 을 반환합니다.

    항목 이름은 `DATA_GAP_MESSAGES` 의 키와 같습니다. 판정은 원문 기준이며
    다른 축의 필터로 대체 해석하지 않습니다.
    """
    normalized = _normalize_request(message)
    if not normalized.strip():
        return None

    if _EXPLANATION.search(normalized) and not _ACTUAL_VALUE.search(normalized):
        return None

    compact = _WHITESPACE.sub("", normalized)
    for item, patterns, use_compact in _ITEM_PATTERNS:
        text = compact if use_compact else normalized
        for pattern in patterns:
            for match in pattern.finditer(text):
                if _is_project_name_phrase(text, match):
                    continue
                return item
    return None


__all__ = [
    "DATA_GAP_MESSAGES",
    "detect_data_gap",
]

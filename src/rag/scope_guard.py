"""RAG 범위 밖 질문 결정론적 거절 가드.

입찰·공고·낙찰·조달과 무관한 질문을 검색·도구·LLM 호출 전에 고정 문구로
거절합니다. 판정은 표지 사전 기반이며 도메인 표지가 하나라도 있으면 절대
거절하지 않습니다(domain-first). 도메인 표지도 범위 밖 표지도 없으면 기존
경로를 유지합니다(fail-open).
"""

from __future__ import annotations

import re
import unicodedata

OUT_OF_SCOPE_REFUSAL_MESSAGE = (
    "죄송합니다. 저는 입찰 공고·낙찰 결과·입찰 통계·낙찰가 예측을 돕는 "
    "입찰 분석 어시스턴트입니다. "
    "이 질문은 제 지원 범위(입찰·공고·낙찰·조달 데이터 분석)를 벗어나 "
    "답변드리기 어렵습니다. "
    "공고 조회, 낙찰 결과, 입찰 통계, 낙찰가 예측에 대해 물어봐 주세요."
)

# 입찰 도메인 표지. 지역명 단독, "기관" 단독, "예측" 단독은 넣지 않습니다.
# "서울 날씨"나 "월드컵 예측"을 입찰 질문으로 구제하지 않기 위해서입니다.
_DOMAIN_MARKERS: tuple[str, ...] = (
    "입찰",
    "공고",
    "낙찰",
    "투찰",
    "개찰",
    "유찰",
    "조달",
    "발주",
    "나라장터",
    "공고번호",
    "공고명",
    "수요기관",
    "발주기관",
    "낙찰률",
    "투찰률",
    "경쟁률",
    "예정가격",
    "기초금액",
    "추정가격",
    "사정률",
    "적격심사",
    "기술평가",
    "가격평가",
    "입찰참가",
    "입찰보증",
    "낙찰가",
    "투찰가",
    "입찰가",
    "낙찰금액",
    "예측 모델 검증",
    "모델 검증",
    "성능 검증",
    "품질 기준",
    "기준 미달",
    "데이터 수집",
    "입찰 수집",
    "공고 수집",
    "공고 업데이트",
    "신규 공고",
    "kb 갱신",
    "지식베이스 갱신",
    "벡터 갱신",
    "인덱스 갱신",
    "색인 갱신",
    "공사",
    "물품",
    "용역",
    "외자",
    "분야",
    "업무구분",
    "분류별",
    "기관별",
    "지역별",
    "공고 건수",
    "낙찰 건수",
    "낙찰 통계",
)

# 범위 밖 표지. 도메인 표지가 하나도 없을 때만 사용합니다.
_OUT_OF_SCOPE_MARKERS: tuple[str, ...] = (
    "안녕",
    "너는 누구",
    "누구야",
    "정체",
    "자기소개",
    "이름이 뭐",
    "더하기",
    "빼기",
    "곱하기",
    "나누기",
    "계산",
    "수학",
    "역사",
    "인물",
    "장군",
    "대통령",
    "번역",
    "영어로",
    "상식",
    "퀴즈",
    "날씨",
    "기온",
    "강수",
    "예보",
    "미세먼지",
    "태풍",
    "폭우",
    "폭설",
    "맑",
    "흐리",
    "비가",
    "눈이",
    "습도",
    "바람",
    "황사",
    "파이썬",
    "자바",
    "자바스크립트",
    "타입스크립트",
    "코드",
    "프로그래밍",
    "함수",
    "클래스",
    "크롤러",
    "크롤링",
    "스크래핑",
    "알고리즘",
    "디버깅",
    "리팩터링",
    "도커",
    "주식",
    "코스피",
    "코스닥",
    "주가",
    "지수",
    "펀드",
    "투자",
    "매수",
    "매도",
    "상승",
    "하락",
    "전망",
    "시장",
    "점심",
    # "아침"은 "매일 아침 알림"처럼 시간대 표현과 겹쳐 표지에서 제외합니다.
    "저녁",
    "메뉴",
    "맛집",
    "식당",
    "요리",
    "여행",
    "놀러",
    "주말",
    "영화",
    "드라마",
    "음악",
    "노래",
    "운동",
    "다이어트",
    "게임",
    "쇼핑",
    "추천",
    "고양이",
    "강아지",
    "반려동물",
    "키우는 법",
    "사료",
    "예방접종",
    "중성화",
    "입양",
    "배변",
    "화장실",
    "월드컵",
    "올림픽",
    "축구",
    "야구",
    "배구",
    "농구",
    "우승국",
    "선수",
    "연예인",
    "아이돌",
    "농담",
    "심심",
    "재밌",
    "기분",
    "사랑",
    "운세",
    "타로",
    "명언",
    "시인",
    "시집",
    "소설",
)

# 한 글자 표지는 다른 낱말 안에서 우연히 걸리기 쉬워 경계를 요구합니다.
# "서울시교육청"의 "시", "왕십리"의 "왕"을 범위 밖 표지로 쓰지 않기 위해서입니다.
_OUT_OF_SCOPE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?<![가-힣])깃(?:허브)?(?![가-힣])"),
    re.compile(r"(?<![가-힣])왕(?:은|이|을|의|이고|이다)?(?![가-힣])"),
    re.compile(r"(?<![가-힣])시(?:\s*(?:를|가|한\s*편|써|작성|지어))"),
    re.compile(r"\d+\s*[+\-*/\u00d7\u00f7]\s*\d+"),
    re.compile(r"\d+\s*(?:더하기|빼기|곱하기|나누기)\s*\d+"),
    re.compile(
        r"\b(?:python|javascript|typescript|crawler|scrape|scraping|requests|pandas|numpy"
        r"|java|code|programming|function|class|algorithm|debugging|refactoring|git|docker)\b"
    ),
)


def _normalize_request(message: str) -> str:
    """NFC 정규화와 소문자 변환만 수행합니다. 공백은 보존합니다."""
    return unicodedata.normalize("NFC", message or "").lower()


def is_out_of_scope_request(message: str) -> bool:
    """입찰 도메인과 무관한 질문이면 True 를 반환합니다.

    판정 순서는 domain-first 입니다. 도메인 표지가 하나라도 있으면 False,
    범위 밖 표지나 산술 구조가 있으면 True, 둘 다 없으면 False 입니다.
    """
    normalized = _normalize_request(message)
    if not normalized.strip():
        return False
    if any(marker in normalized for marker in _DOMAIN_MARKERS):
        return False
    if any(marker in normalized for marker in _OUT_OF_SCOPE_MARKERS):
        return True
    return any(pattern.search(normalized) for pattern in _OUT_OF_SCOPE_PATTERNS)


__all__ = [
    "OUT_OF_SCOPE_REFUSAL_MESSAGE",
    "is_out_of_scope_request",
]

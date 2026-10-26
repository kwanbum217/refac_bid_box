"""
src/rag/query_planning.py

하이브리드 RAG 쿼리 플래너 및 기간/키워드 라우팅 규칙.
자연어 질의에서 정형 통계(SQL), 벡터 검색(Chroma), 지식베이스(KB) 상태 조회 대상을
판정하고 기간 조건을 안전하게 파싱합니다.
"""

from __future__ import annotations

import calendar
import re
import unicodedata
from datetime import date, timedelta
from typing import Any

from src.app.models.bids import CATEGORY_LABELS
from src.rag.schemas import (
    DEFAULT_STATISTICS_WINDOW_YEARS,
    DEFAULT_VECTOR_TOP_K,
    RetrievalPlan,
)

STATISTICS_KEYWORDS = (
    "통계",
    "평균",
    "추세",
    "비교",
    "건수",
    "낙찰률",
    "경쟁률",
    "집계",
    "흐름",
    "변화",
    "자주",
    "빈도",
    "많이",
)
# 건수를 묻는 표현은 "건수" 라는 낱말 없이도 통계 질의입니다.
# "몇 건", "총 몇", "얼마나 올라" 만으로는 목록과 구분되지 않으므로,
# 공고·낙찰 도메인 표지가 함께 있을 때만 통계로 봅니다.
COUNT_QUERY_PATTERN = re.compile(r"몇\s*건|몇\s*개|총\s*몇|얼마나\s*(?:올라|있)")
COUNT_QUERY_DOMAIN_MARKERS = ("공고", "낙찰")
# 목록·사례·리스트·보여줘 는 개별 항목을 늘어놓으라는 요청입니다. "몇 건" 같은
# 수량 표현이 함께 있어도 집계가 아니라 목록 요청이므로, 통계 라우팅과 단일
# 지표 직접 응답에서 제외합니다.
LIST_REQUEST_MARKERS = ("목록", "리스트", "사례", "목록으로", "보여줘")
SEMANTIC_KEYWORDS = (
    "사례",
    "상세",
    "특징",
    "문맥",
    "위험",
    "리스크",
    "어떤",
    "왜",
    "의미",
)
KB_KEYWORDS = (
    "kb",
    "지식베이스",
    "벡터",
    "임베딩",
    "인덱스",
)
CATEGORY_KEYWORDS = {
    "공사": "Cnstwk",
    "물품": "Thng",
    "용역": "Servc",
    "외자": "Frgcpt",
    "건설": "Cnstwk",
}
# 건설 은 업체명(대한건설)·기관명(종합건설본부)·사업명(주택건설공사)에 붙어
# 쓰입니다. 분야어는 독립 어절이거나 조사가 붙은 형태뿐이므로, 그 밖의 건설 은
# 분야 판정에서 지웁니다.
CONSTRUCTION_CATEGORY_PATTERN = re.compile(
    r"(?<![가-힣])건설"
    r"(?=$|[^가-힣]|"
    r"(?:에서는|에게는|으로는|에서|으로|처럼|보다|까지|부터|"
    r"은|는|이|가|을|를|의|에|로|와|과|도|만|랑)"
    r"(?=$|[^가-힣]))"
)
PUBLIC_CORPORATION_PREFIXES = (
    "한국",
    "서울",
    "부산",
    "인천",
    "경기",
    "대구",
    "광주",
    "대전",
    "울산",
    "세종",
    "인천국제",
)
# 접두어만으로 판정하면 "서울역사공원조성공사" 같은 건설 공사명이 공기업으로 오인됩니다.
# 접두어와 "공사" 사이가 실제 공기업 어간일 때만 공기업 이름으로 봅니다.
PUBLIC_CORPORATION_STEMS = (
    "전력",
    "교통",
    "도로",
    "도시",
    "주택도시",
    "토지주택",
    "도시개발",
    "수자원",
    "가스",
    "철도",
    "공항",
    "농어촌",
    "관광",
    "환경",
    "지역난방",
    "석유",
    "광해광업",
    "조폐",
)
PUBLIC_CORP_JOSA = ("의", "와", "과", "은", "는", "이", "가")
REGION_KEYWORDS = (
    "서울",
    "부산",
    "대구",
    "인천",
    "광주",
    "대전",
    "울산",
    "세종",
    "경기",
    "강원",
    "충북",
    "충남",
    "전북",
    "전남",
    "경북",
    "경남",
    "제주",
)
# 지역 축 집계는 단축형과 정식 명칭을 함께 잡아야 합니다. 기관명 부분 일치에
# "충북" 만 쓰면 "충청북도교육청" 이 빠집니다.
REGION_ALIASES: dict[str, tuple[str, ...]] = {
    "서울": ("서울",),
    "부산": ("부산",),
    "대구": ("대구",),
    "인천": ("인천",),
    "광주": ("광주",),
    "대전": ("대전",),
    "울산": ("울산",),
    "세종": ("세종",),
    "경기": ("경기",),
    "강원": ("강원",),
    "충북": ("충북", "충청북도"),
    "충남": ("충남", "충청남도"),
    "전북": ("전북", "전라북도", "전북특별자치도"),
    "전남": ("전남", "전라남도"),
    "경북": ("경북", "경상북도"),
    "경남": ("경남", "경상남도"),
    "제주": ("제주",),
}
# "도" 접미사는 공식 광역 도 명칭일 때만 행정 구역입니다. "인입철도", "도시철도",
# "고속도" 처럼 사업명·일반 명사가 도 접미사로 끝나는 경우를 걷어냅니다.
OFFICIAL_PROVINCE_NAMES = frozenset(
    {
        "경기도",
        "강원도",
        "강원특별자치도",
        "충청북도",
        "충청남도",
        "전라북도",
        "전북특별자치도",
        "전라남도",
        "경상북도",
        "경상남도",
        "제주도",
        "제주특별자치도",
    }
)
TREND_KEYWORDS = ("추세", "흐름", "변화", "추이", "월별", "분기별")

AGGREGATE_AXIS_MARKERS: dict[str, tuple[str, ...]] = {
    "category": ("분류별", "분야별", "업무구분별", "종류별", "카테고리별"),
    "institution": ("기관별", "수요기관별", "발주기관별", "기관순위"),
    "region": ("지역별", "시도별", "시·도별", "권역별"),
    # 업체 축은 낙찰 결과 테이블에만 있으므로 지표는 낙찰 건수가 기본이고,
    # "낙찰률" 표지가 있으면 평균 낙찰률을 씁니다. "업체" 한 낱말만으로 잡으면
    # 개체 조회가 순위로 새므로 순위를 드러내는 표현만 받습니다.
    "winner": (
        "업체별",
        "낙찰업체별",
        "업체순위",
        "업체 순위",
        "가장 많이 낙찰받은 업체",
        "낙찰 많이 한 업체",
        "많이 낙찰한 업체",
    ),
}
# "제일 많이 낙찰한 용역 업체" 처럼 최상급 표현과 "업체" 사이에 분야 낱말이
# 끼면 위의 연속 표기가 맞지 않습니다. "업체"를 함께 요구해 기관·분류 순위
# 질의를 업체 축으로 끌어오지 않습니다.
WINNER_AXIS_PATTERN = re.compile(
    r"(?:가장|제일|최다|최고|1등|1위)[^.!?]{0,10}?(?:낙찰|수주)[^.!?]{0,10}?"
    r"(?:업체|기업|회사)"
    r"|(?:낙찰|수주)[^.!?]{0,6}?(?:많이|많은)[^.!?]{0,6}?(?:업체|기업|회사)"
)
# 순서가 곧 우선순위입니다. "낙찰 공고" 를 "공고" 보다 먼저 판정하지 않으면
# 낙찰을 묻는 질문에 공고 건수를 답하는 결함이 재발합니다. "낙찰률" 이 있으면
# 건수 표현과 함께 있어도 평균 낙찰률 질의로 봅니다.
AGGREGATE_RATE_MARKERS = ("낙찰률", "평균 낙찰률", "평균낙찰률", "낙찰률 평균")
AGGREGATE_BID_MARKERS = (
    "낙찰 결과",
    "낙찰된",
    "낙찰받은",
    "낙찰 건수",
    "낙찰건수",
    "낙찰 많이",
    "많이 낙찰",
    "낙찰 공고",
    "낙찰공고",
    "낙찰 중",
    "낙찰 수",
)
AGGREGATE_ANNOUNCEMENT_MARKERS = ("공고 건수", "공고건수", "공고 수", "공고수", "공고")
DEFAULT_GROUP_LIMIT = 20
MAX_GROUP_LIMIT = 50

RESULT_QUERY_MARKERS = (
    "낙찰된",
    "낙찰 결과",
    "낙찰정보",
    "낙찰 정보",
    "낙찰 사업",
    "낙찰 업체",
    "낙찰 공고",
    "낙찰공고",
    "낙찰받은",
)
RESULT_LIST_MARKERS = ("리스트", "목록", "나열", "뽑아", "골라")
# 한글 수사 개수는 숫자와 같은 자리에서 읽습니다. 긴 수사를 먼저 두지 않으면
# "열한" 이 "열" 로 잘려 단위 검사에서 빠집니다.
KOREAN_NUMERALS: dict[str, int] = {
    "한": 1,
    "두": 2,
    "세": 3,
    "네": 4,
    "다섯": 5,
    "여섯": 6,
    "일곱": 7,
    "여덟": 8,
    "아홉": 9,
    "열": 10,
    "열한": 11,
    "열두": 12,
    "열세": 13,
    "열네": 14,
    "열다섯": 15,
    "열여섯": 16,
    "열일곱": 17,
    "열여덟": 18,
    "열아홉": 19,
    "스무": 20,
}
KOREAN_NUMERAL_FRAGMENT = "|".join(sorted(KOREAN_NUMERALS, key=len, reverse=True))
# 개수는 반드시 단위(개/건)가 붙은 형태만 인정합니다. "한 달", "세부", "열린",
# "한국전력공사" 처럼 수사 글자가 다른 낱말의 일부인 경우를 개수로 읽지 않습니다.
# 수사 앞도 제한합니다. "정한", "구두", "실세" 처럼 다른 낱말 끝 글자와 겹치면
# 개수로 읽지 않도록 한글 수사는 입력 시작·공백·비한글 뒤에서만 인정하고,
# 숫자는 숫자·영문자 뒤가 아닐 때만 인정합니다("최근5건" 은 인정).
# 단위 뒤에 다른 한글 음절이 이어지면 그 단위도 개수가 아닙니다. "세 건설사",
# "다섯 건설", "한 건강", "세 개발자" 를 개수로 읽지 않도록 단위 바로 뒤를
# 입력 끝·공백·비한글·개수 뒤 조사로 제한합니다.
COUNT_UNIT_BOUNDARY_PATTERN = r"(?=$|\s|[^가-힣]|만|씩|을|를|이|가|은|는|도|의|으로|정도|짜리)"
COUNT_PATTERN_FRAGMENT = (
    rf"(?:(?<![0-9A-Za-z])[0-9]+|(?<![가-힣])(?:{KOREAN_NUMERAL_FRAGMENT}))"
    rf"\s*(?:개|건){COUNT_UNIT_BOUNDARY_PATTERN}"
)
COUNT_PATTERN = re.compile(COUNT_PATTERN_FRAGMENT)
# 순위 질의의 행 수입니다. "1위" 는 한 행만, "상위 N개" 는 N행을 요청한 것으로
# 읽습니다. 순위 숫자(2위 등)를 행 수로 오인하지 않도록 "1위" 만 따로 잡습니다.
GROUP_FIRST_PATTERN = re.compile(r"(?<!\d)1\s*위(?!\d)")
GROUP_TOP_PATTERN = re.compile(
    rf"(?:상위|톱|top)\s*(?P<count>[0-9]+|{KOREAN_NUMERAL_FRAGMENT})\s*(?:개|곳|건|업체)?"
)
# "업체 순위 10개" 처럼 상위 표기 없이 순위와 개수만 붙는 형태도 같은 행 수로 읽습니다.
GROUP_RANK_COUNT_PATTERN = re.compile(
    rf"(?:순위|랭킹)\s*(?:상위\s*)?(?P<count>[0-9]+|{KOREAN_NUMERAL_FRAGMENT})\s*(?:개|곳|건|업체)"
)
# "가장 많이", "최다", "1등" 은 순위의 첫 행만 요청한 표현입니다. 상위 N 처럼
# 행 수가 명시되면 그 표기를 먼저 읽습니다.
GROUP_SINGLE_TOP_MARKERS = ("가장 많이", "제일 많이", "최다", "1등", "1위")
# 요청 동사는 어미 변형을 정규식 대안으로 받습니다.
RESULT_LIST_REQUEST_VERB_PATTERN = re.compile(
    r"(?:보여|알려|뽑아|나열|줄\s*수\s*있|볼\s*수\s*있|줄래|볼래|부탁|가르쳐|보내|줘)"
)
# 요청 동사만 있는 질의는 업체명·기관명·지역명이 섞이면 다른 경로가 맡습니다.
# 어절에서 조사·어미를 떼고 남은 어간이 모두 허용 어휘일 때만 목록 요청으로 봅니다.
RESULT_LIST_VOCABULARY_WORDS = frozenset(
    {
        "최근",
        "요즘",
        "오늘",
        "어제",
        "이번주",
        "지난주",
        "지난달",
        "이번달",
        "올해",
        "작년",
        "동안",
        "기준",
        "사이",
        "이후",
        "이전",
        "용역",
        "공사",
        "물품",
        "외자",
        "전체",
        "모든",
        "낙찰",
        "낙찰된",
        "낙찰공고",
        "공고",
        "결과",
        "보여",
        "알려",
        "뽑아",
        "나열",
        "보이",
        "알리",
        "줄래",
        "볼래",
        "부탁",
        "가르쳐",
        "보내",
        "개",
        "건",
        *KOREAN_NUMERALS,
    }
)
RESULT_LIST_VOCABULARY_PATTERNS = (
    re.compile(r"\d+\s*(?:일|월|년|분기|개월|주)"),
    COUNT_PATTERN,
)
RESULT_LIST_TOKEN_SUFFIXES = (
    "해줘",
    "줄래요",
    "주세요",
    "볼래요",
    "줄래",
    "볼래",
    "에서",
    "으로",
    "은",
    "는",
    "이",
    "가",
    "을",
    "를",
    "의",
    "에",
    "로",
    "와",
    "과",
    "만",
    "좀",
    "도",
    "요",
    "줘",
)
RESULT_LIST_TOKEN_SPLIT_PATTERN = re.compile(r"[\s,.;:!?~()\[\]{}'\"·/|\\-]+")
RESULT_LIST_SPACED_PERIOD_REPLACEMENTS = (("이번 주", "이번주"),)
RESULT_LIST_EXCLUDED_MARKERS = (
    "평균",
    "낙찰률",
    "건수",
    "순위",
    "top",
    "많이 받은",
    "통계",
    "비율",
    "분포",
    "추이",
    "높은 편",
    "비교",
)
# "몇 건"·"몇 개" 는 모호한 수량 질의이지 목록 개수가 아닙니다. 띄어 쓴 형태와
# 붙여 쓴 형태를 모두 같은 규칙으로 잡아야 "최신 공고 몇건 알려줘" 가 목록으로
# 새지 않습니다. 낙찰 결과 목록과 공고 목록 판정이 이 표지를 함께 씁니다.
RESULT_LIST_EXCLUDED_PATTERN = re.compile(r"몇\s*(?:건|개)")
RESULT_LIST_EXPLANATION_MARKERS = ("방법", "규정", "설명", "어떻게", "의미", "절차", "뭐야")
RESULT_LIST_BID_NUMBER_PATTERN = re.compile(r"[A-Z]\d{2}[A-Z]{2}\d{8}|\d{11,}", re.IGNORECASE)
# 공고번호는 "R26BK01778156" 처럼 영문 1자, 숫자 2자, 영문 2자, 숫자 8자로 고정됩니다.
# 접수번호(11자리 숫자)나 금액처럼 숫자만 긴 값을 공고번호로 읽지 않도록 숫자 대안을
# 두지 않습니다. 차수 접미사("-001")가 붙은 값은 다른 식별자이므로 단건 조회로
# 읽지 않습니다. 값은 대문자로 정규화해 DB 의 표기와 맞춥니다.
BID_NTCE_NO_PATTERN = re.compile(
    r"(?:공고\s*번호\s*)?(?<![A-Za-z0-9])"
    r"(?P<bid_ntce_no>[A-Z]\d{2}[A-Z]{2}\d{8})(?!\d)(?!-\d)",
    re.IGNORECASE,
)
BID_NTCE_NO_EXPLANATION_MARKERS = (
    "방법",
    "설명",
    "어떻게",
    "의미",
    "절차",
    "규정",
    "의미가 뭐야",
    "뜻이 뭐야",
    "차이가 뭐야",
    "이 뭐야",
    "가 뭐야",
    "란 뭐야",
    "이란 뭐야",
    "계산 방법",
    "어떻게 계산",
    "계산법",
)

ENTITY_ORG_SUFFIXES = (
    "주식회사",
    "(주)",
    "㈜",
    "(유)",
    "유한회사",
    "합자회사",
    "협동조합",
    "법률사무소",
    "회계법인",
    "초등학교",
    "중학교",
    "고등학교",
    "대학교",
    "대학원",
    "유치원",
    "어린이집",
    "여중",
    "남중",
    "여고",
    "남고",
    "병원",
    "의료원",
    "보건소",
    "공항공사",
    "철도공사",
    "도로공사",
    "수자원공사",
    "토지주택공사",
    "가스공사",
    "전력공사",
    "교통공사",
    "도시공사",
    "농어촌공사",
    "관광공사",
    "시설공단",
    "관리공단",
    "사업소",
    "교육청",
    "지원청",
    "기상청",
    "경찰서",
    "소방서",
    "주민센터",
    "행정복지센터",
)


ADMIN_REGION_PATTERN = re.compile(
    r"^[가-힣]{2,10}(?:특별자치시|특별자치도|특별시|광역시|도|시|군|구)$"
)
# 광역 단축명보다 좁은 범위는 시·군·구 행정 구역입니다. "도시" 처럼 기저가 한 글자인
# 낱말은 제외되도록 기저를 두 글자 이상 요구합니다.
ADMIN_DISTRICT_PATTERN = re.compile(r"^[가-힣]{2,8}(?:시|군|구)$")
ADMIN_REGION_OFFICE_SUFFIX = "청"
INSTITUTION_SUBUNIT_SUFFIXES = ("지역본부", "본부", "지사", "지부", "지점", "출장소", "사업단")
INSTITUTION_SCOPE_EXPLANATORY_MARKERS = (
    "왜",
    "어떻게",
    "방법",
    "의미",
    "설명",
    "절차",
    "규정",
)
# 어절에서 떼어 낼 조사·어미입니다. 행정 구역 접미사(도·시·군·구)와 겹치는 값은
# 원형이 먼저 판정되므로 여기서 문제되지 않습니다.
INSTITUTION_SCOPE_PARTICLES = (
    "해줘",
    "줄래요",
    "주세요",
    "볼래요",
    "줄래",
    "볼래",
    "에서",
    "으로",
    "께서",
    "에게",
    "은",
    "는",
    "이",
    "가",
    "을",
    "를",
    "의",
    "에",
    "로",
    "와",
    "과",
    "만",
    "좀",
    "도",
    "요",
    "줘",
)
# 행정 구역 접미사와 같은 글자로 끝나는 일반 명사입니다. 이 목록이 없으면
# "도시", "지구", "연구" 같은 낱말이 기관 범위로 승격됩니다.
INSTITUTION_SCOPE_EXCLUDED_TERMS = frozenset(
    {
        "시장",
        "시설",
        "시험",
        "시공",
        "시행",
        "구매",
        "구축",
        "구입",
        "군수",
        "도로",
        "도급",
        "시스템",
        "구조",
        "지구",
        "도시",
        "당시",
        "무시",
        "개시",
        "실시",
        "임시",
        "표시",
        "제시",
        "명시",
        "비상시",
        "연도",
        "년도",
        "회계연도",
        "연구",
        "도구",
        "가구",
        "기구",
        "농구",
        "야구",
        "축구",
        "배구",
        "투구",
        "제도",
        "정도",
        "속도",
        "태도",
        "각도",
        "온도",
        "기도",
        "유도",
        "과도",
        "한도",
        "해군",
        "공군",
        "육군",
        "인입철도",
        "도시철도",
        "지하철도",
        "고속도",
        "궤도",
        "보도",
        "수도",
        "지도",
        "시도",
        "강도",
        "습도",
    }
)
INSTITUTION_SCOPE_EXCLUDED_SUFFIXES = (
    "지구",
    "일시",
    "도시",
    "수구",
    "입구",
    "출구",
    "창구",
    "풍구",
    "전구",
    "문구",
    "광구",
    "연구",
    "도구",
    "가구",
    "기구",
)


def _strip_institution_particle(token: str) -> str:
    for particle in INSTITUTION_SCOPE_PARTICLES:
        if token.endswith(particle) and len(token) > len(particle) + 1:
            return token[: -len(particle)]
    return token


def _admin_region_name(token: str) -> str:
    """행정 구역 형태의 토큰을 지명으로 정규화합니다.

    "공주시청" 처럼 뒤에 청이 붙으면 청을 떼고 다시 판정합니다. "시청"·"군청"·
    "구청" 단독은 지명이 없으므로 빈 문자열입니다.
    """
    if token in INSTITUTION_SCOPE_EXCLUDED_TERMS:
        return ""
    # 택지지구·배수구·개찰일시·해저도시처럼 행정 구역이 아닌 일반 명사가
    # 시·군·구·도 접미사와 같은 글자로 끝나는 경우를 걷어냅니다.
    if token.endswith(INSTITUTION_SCOPE_EXCLUDED_SUFFIXES):
        return ""
    if ADMIN_REGION_PATTERN.fullmatch(token):
        return token
    if token.endswith(ADMIN_REGION_OFFICE_SUFFIX) and len(token) > 2:
        stripped = token[: -len(ADMIN_REGION_OFFICE_SUFFIX)]
        if stripped not in INSTITUTION_SCOPE_EXCLUDED_TERMS and ADMIN_REGION_PATTERN.fullmatch(
            stripped
        ):
            return stripped
    return ""


def _institution_token_candidates(token: str, *, include_entity_org_tokens: bool) -> list[str]:
    """토큰 하나에서 기관 범위 후보를 뽑습니다. 원형을 먼저 보고 조사를 뗀 형태를 봅니다."""
    candidates: list[str] = []
    for value in (token, _strip_institution_particle(token)):
        if not value:
            continue
        corporations = _extract_public_corporation_tokens(value)
        if corporations:
            candidates.append(corporations[0])
        if (
            include_entity_org_tokens
            and len(value) > 2
            and value not in INSTITUTION_SCOPE_EXCLUDED_TERMS
            and any(
                value.endswith(suffix) and len(value) > len(suffix)
                for suffix in ENTITY_ORG_SUFFIXES
            )
        ):
            candidates.append(value)
        region = _admin_region_name(value)
        if region:
            candidates.append(region)
        if value in REGION_ALIASES and value not in candidates:
            candidates.append(value)
    return candidates


# 기관을 둘 이상 나열할 때 쓰는 연결어입니다. "이랑" 은 "랑" 보다 먼저 떼어야
# "공주시이랑" 이 "공주시이" 로 잘리지 않습니다.
INSTITUTION_ENUM_CONNECTORS = ("이랑", "랑", "하고", "와", "과", "및")
# 연결어 하나만 있는 어절은 기관 이름이 아니라 나열 표지입니다.
INSTITUTION_ENUM_STANDALONE_CONNECTORS = frozenset({"및", "와", "과", "랑", "이랑", "하고"})
# 쉼표도 나열 표지입니다. 어절 안에 붙은 쉽표는 어절 분리 단계에서 떨어집니다.
INSTITUTION_ENUM_SEPARATORS = (",", "·", "/")


def _institution_scope_name(token: str, *, include_entity_org_tokens: bool) -> str:
    """어절 하나에서 대표 기관 범위 이름을 고릅니다. 없으면 빈 문자열입니다."""
    best = ""
    for candidate in _institution_token_candidates(
        token, include_entity_org_tokens=include_entity_org_tokens
    ):
        if candidate.endswith("도") and candidate not in OFFICIAL_PROVINCE_NAMES:
            continue
        if len(candidate) > len(best):
            best = candidate
    return best


def _institution_enumeration_token_pairs(query: str) -> list[tuple[str, str]]:
    """어절과 그 앞 구분자를 순서대로 돌려줍니다.

    쉼표로 나열한 "공주시, 서산시" 와 공백으로 나열한 "대전 유성구" 를
    구분해야 하므로 구분자 문자열을 함께 남깁니다.
    """
    normalized = _normalize_text(query)
    pairs: list[tuple[str, str]] = []
    position = 0
    separator = ""
    for match in RESULT_LIST_TOKEN_SPLIT_PATTERN.finditer(normalized):
        token = normalized[position : match.start()]
        if token:
            pairs.append((token, separator))
        separator = match.group(0)
        position = match.end()
    token = normalized[position:]
    if token:
        pairs.append((token, separator))
    return pairs


def _split_institution_enum_connector(token: str) -> tuple[str, str]:
    """어절 끝의 나열 연결어를 떼어 (기관 어절, 연결어)를 돌려줍니다."""
    for connector in INSTITUTION_ENUM_CONNECTORS:
        if token.endswith(connector) and len(token) > len(connector) + 1:
            return token[: -len(connector)], connector
    return token, ""


def _extract_enumerated_institution_names(
    query: str, *, include_entity_org_tokens: bool = True
) -> list[str]:
    """나열 연결어로 이어진 기관 이름을 질의 순서대로 돌려줍니다.

    "공주시와 서산시의 ...", "공주시랑 서산시 ...", "한국전력공사와
    한국농어촌공사 ..." 처럼 와·과·랑·이랑·하고·및·쉼표로 기관이 이어질 때만
    동작합니다. 기관이 아닌 낱말이 끼면 그 자리에서 나열 구간이 끝나므로
    "대전 유성구" 나 "결과" 안의 "과" 를 나열로 오인하지 않습니다.
    """
    names: list[str] = []
    previous_connector = False
    pending_connector = False
    for token, separator in _institution_enumeration_token_pairs(query):
        if token in INSTITUTION_ENUM_STANDALONE_CONNECTORS:
            pending_connector = True
            continue
        body, connector = _split_institution_enum_connector(token)
        name = _institution_scope_name(body, include_entity_org_tokens=include_entity_org_tokens)
        if not name:
            if names:
                break
            previous_connector = False
            pending_connector = False
            continue
        if names:
            separated = (
                pending_connector
                or previous_connector
                or any(marker in separator for marker in INSTITUTION_ENUM_SEPARATORS)
            )
            if not separated:
                break
        if name not in names:
            names.append(name)
        previous_connector = bool(connector)
        pending_connector = False
    return names if len(names) >= 2 else []


def extract_institution_scope(
    query: str,
    *,
    include_entity_org_tokens: bool = True,
    multiple: bool = False,
) -> dict[str, Any]:
    """목록·집계 질의에서 기관·지역 범위를 뽑습니다.

    공공기관 접미사 토큰을 먼저 보고, 다음으로 행정 구역(시·군·구·도)을 봅니다.
    "공주시청" 은 "공주시" 로 정규화하고, "시장"·"시설"·"지구" 같은 일반 명사는
    제외합니다. 광역 단축명은 정식 명칭과 함께 institution_aliases 로 돌려줍니다.
    기본값은 기관 하나를 가장 긴 이름으로 채택하는 기존 동작입니다. multiple 이
    참이면 와·과·랑·이랑·하고·및·쉼표로 나열한 기관을 모두 institution_names 로
    돌려줍니다.
    """
    normalized = _normalize_text(query)
    if multiple:
        enumerated = _extract_enumerated_institution_names(
            normalized, include_entity_org_tokens=include_entity_org_tokens
        )
        if enumerated:
            return {"institution_names": enumerated}
    tokens = [token for token in RESULT_LIST_TOKEN_SPLIT_PATTERN.split(normalized) if token]

    best_name = ""
    best_aliases: tuple[str, ...] = ()
    for index, token in enumerate(tokens):
        for candidate in _institution_token_candidates(
            token, include_entity_org_tokens=include_entity_org_tokens
        ):
            # "도" 접미사는 공식 광역 도 명칭만 행정 구역으로 인정합니다. 이 검사가
            # 없으면 "경북 인입철도 공사" 의 "인입철도" 나 "도시철도 공사" 의
            # "도시철도" 가 기관 범위로 승격됩니다.
            if candidate.endswith("도") and candidate not in OFFICIAL_PROVINCE_NAMES:
                continue
            name = candidate
            if candidate in _extract_public_corporation_tokens(candidate) and index + 1 < len(
                tokens
            ):
                following = _strip_institution_particle(tokens[index + 1])
                if (
                    following
                    and following not in INSTITUTION_SCOPE_EXCLUDED_TERMS
                    and any(
                        following.endswith(suffix) and len(following) > len(suffix)
                        for suffix in INSTITUTION_SUBUNIT_SUFFIXES
                    )
                ):
                    name = f"{candidate} {following}"
            if len(name) > len(best_name):
                best_name = name
                best_aliases = REGION_ALIASES.get(name, ())

    if not best_name:
        return {}

    scope: dict[str, Any] = {"institution_name": best_name}
    if len(best_aliases) > 1:
        scope["institution_aliases"] = list(best_aliases)
    return scope


def _is_broad_region_name(name: str) -> bool:
    """광역 단축명이나 그 행정 접미사형인지 판정합니다.

    "광주" 와 "광주시", "충남" 과 "충청남도" 는 같은 광역 범위입니다. 이런 값은
    더 좁은 기관 범위가 아니므로 광역 사전 대체 값을 바꾸지 않습니다.
    """
    if name in REGION_ALIASES:
        return True
    if any(name in aliases for aliases in REGION_ALIASES.values()):
        return True
    for suffix in ("특별자치시", "특별자치도", "특별시", "광역시", "도", "시"):
        if name.endswith(suffix) and name[: -len(suffix)] in REGION_ALIASES:
            return True
    return False


def _is_specific_institution_scope(name: str) -> bool:
    """광역 사전 대체 값보다 구체적인 기관 범위인지 판정합니다.

    시·군·구 행정 구역과 공공기관, 기관 접미사 토큰은 광역 사전이 먼저 넣은
    값보다 구체적이므로 대체 대상입니다. 광역 범위 자체는 대체하지 않되,
    "경기도"·"제주특별자치도" 처럼 광역 단축명의 공식 도 명칭은 표기가 더
    정확하므로 대체합니다.
    """
    normalized = _normalize_text(name)
    if not normalized:
        return False
    if normalized in OFFICIAL_PROVINCE_NAMES:
        return True
    if _is_broad_region_name(normalized):
        return False
    if _extract_public_corporation_tokens(normalized):
        return True
    # "인입철도" 처럼 도 접미사로 끝나는 사업명은 행정 구역이 아닙니다. 시·군·구만
    # 광역보다 좁은 행정 구역으로 인정합니다.
    if ADMIN_DISTRICT_PATTERN.fullmatch(normalized):
        return True
    return any(
        normalized.endswith(suffix) and len(normalized) > len(suffix)
        for suffix in ENTITY_ORG_SUFFIXES
    )


def _extract_public_corporation_tokens(text: str) -> list[str]:
    """공기업 이름 토큰을 추출합니다.

    공백·쉼표·조사로 끊은 토큰이 '공사'로 끝나고, PUBLIC_CORPORATION_PREFIXES 중 하나로 시작하며,
    접두어와 '공사' 사이가 PUBLIC_CORPORATION_STEMS 중 하나와 정확히 같으면 공기업 이름으로 판정합니다.
    토큰의 조사('의', '와', '과', '은', '는', '이', '가')는 떼고 판정합니다.
    """
    tokens = re.split(r"[\s,]+", text)
    found: list[str] = []
    for raw in tokens:
        cleaned = raw.strip(" \t\r\n,.'\"`[]()<>《》「」『』")
        for josa in PUBLIC_CORP_JOSA:
            if cleaned.endswith(josa) and len(cleaned) > len(josa):
                cleaned = cleaned[: -len(josa)]
                break
        if cleaned.endswith("공사"):
            for prefix in PUBLIC_CORPORATION_PREFIXES:
                if cleaned.startswith(prefix):
                    between = cleaned[len(prefix) : -2]
                    if between in PUBLIC_CORPORATION_STEMS:
                        found.append(cleaned)
                        break
    return found


# 업체명은 법인 형태 표지가 앞에 붙거나 업종 접미사로 끝나는 토큰으로 드러납니다.
# 접미사 자체("건설", "기술")는 업체명이 아니므로 앞부분이 남는 토큰만 인정합니다.
WINNER_CORPORATE_PREFIX_PATTERN = re.compile(
    r"(?:주식회사|\(주\)|㈜|유한회사|합자회사)\s*(?P<name>[가-힣A-Za-z0-9]{2,20})"
)
WINNER_NAME_SUFFIXES = (
    "종합건설",
    "엔지니어링",
    "건설",
    "산업",
    "기술",
    "개발",
)
# 업종 접미사 앞부분이 일반 업종 낱말뿐이면 업체명이 아니라 분야어입니다.
# "종합건설", "전문건설", "지역건설" 은 업체가 아니지만 "가나종합건설" 은
# 앞부분이 고유명사이므로 업체입니다. 법인 표지가 붙은 경우는 앞부분이
# 일반어여도 업체로 봅니다("주식회사 종합건설").
WINNER_GENERIC_INDUSTRY_STEMS = frozenset(
    {
        "종합",
        "전문",
        "일반",
        "지역",
        "토목",
        "건축",
        "전기",
        "통신",
        "소방",
        "정보",
        "환경",
        "조경",
        "시설",
        "설비",
    }
)
# "<업체>이/가 ... 낙찰", "<업체>의 ... 낙찰" 구조에서 업체명을 뽑습니다. 업체명과
# 낙찰 표지 사이에는 기간 표현만 끼도록 제한합니다. 아무 낱말이나 허용하면
# "...공사의 공고번호, 수요기관, 낙찰업체" 처럼 공고명·지표가 업체명으로 읽힙니다.
WINNER_WINDOW_FRAGMENT = (
    r"(?:올해|금년|작년|지난해|전년|재작년|최근|요즘|이번|지난|오늘|어제|"
    r"\d{1,4}\s*년|\d{1,2}\s*월|\d{1,2}\s*일|\d{1,2}\s*개월|\d{1,2}\s*분기|"
    r"개월|동안|기준|사이|이후|이전|분기)"
    r"(?:에는|에|부터|까지)?"
)
WINNER_ACTIVITY_WINDOW = rf"(?:{WINNER_WINDOW_FRAGMENT}\s+){{0,3}}"
# "낙찰률" 은 지표 질의이지 업체의 낙찰 활동이 아닙니다.
WINNER_ACTIVITY_PATTERN = r"(?:낙찰(?!률)|수주)"
WINNER_SUBJECT_PATTERN = re.compile(
    r"(?<![가-힣A-Za-z0-9])(?P<name>[가-힣A-Za-z0-9]{2,20})(?:이|가)\s+"
    + WINNER_ACTIVITY_WINDOW
    + WINNER_ACTIVITY_PATTERN
)
WINNER_POSSESSIVE_PATTERN = re.compile(
    r"(?<![가-힣A-Za-z0-9])(?P<name>[가-힣A-Za-z0-9]{2,20})의\s*"
    + WINNER_ACTIVITY_WINDOW
    + WINNER_ACTIVITY_PATTERN
)
# 업체명이 아니라 사업명·공고명 조각입니다. 사업명은 "...공사의 낙찰업체" 처럼
# 속성 지목 구조에 자주 등장합니다.
WINNER_NAME_REJECTED_SUFFIXES = ("공사", "공고", "사업", "용역", "물품", "공정", "시설")
# 지표·기간·분류 낱말은 업체명 자리에 와도 업체가 아닙니다.
WINNER_NAME_EXCLUDED_TERMS = frozenset(
    {
        "낙찰",
        "수주",
        "공고",
        "입찰",
        "개찰",
        "결과",
        "내역",
        "이력",
        "목록",
        "리스트",
        "건수",
        "통계",
        "평균",
        "낙찰률",
        "업체",
        "기업",
        "회사",
        "분야",
        "전체",
        "모든",
        "최근",
        "요즘",
        "오늘",
        "어제",
        "이번",
        "지난",
        "올해",
        "작년",
        "재작년",
        "금년",
        "전년",
        "동안",
        "관련",
        "진행",
        "참여",
        "계약",
        "정보",
        "자료",
        "현황",
        "순위",
        "상위",
        "최다",
        "최고",
        "사업",
        "임의",
        "이전",
        "구매",
        "용역",
    }
)


WINNER_TRAILING_PARTICLES = ("이", "가", "은", "는", "을", "를", "의")


def _strip_winner_particle(name: str) -> str:
    """토큰 끝에 붙은 조사를 뗍니다. 조사를 뗀 뒤 두 글자 이상이 남을 때만 뗍니다."""
    for particle in WINNER_TRAILING_PARTICLES:
        if name.endswith(particle) and len(name) > len(particle) + 1:
            return name[: -len(particle)]
    return name


def _is_generic_industry_name(name: str) -> bool:
    """업종 접미사 앞부분이 일반 업종 낱말뿐인지 판정합니다.

    "종합건설" 은 접미사 "건설" 을 떼면 "종합" 만 남으므로 분야어입니다.
    "가나종합건설" 은 "가나" 가 남으므로 업체명입니다.
    """
    for suffix in WINNER_NAME_SUFFIXES:
        if not name.endswith(suffix) or len(name) <= len(suffix):
            continue
        if name[: -len(suffix)] in WINNER_GENERIC_INDUSTRY_STEMS:
            return True
    return False


def _winner_candidate_allowed(
    name: str,
    institution_name: str,
    institution_names: frozenset[str],
    *,
    corporate_marker: bool = False,
) -> bool:
    """뽑은 문자열을 업체명으로 인정할지 판정합니다."""
    if len(name) < 2:
        return False
    if name in WINNER_NAME_EXCLUDED_TERMS:
        return False
    if not corporate_marker and _is_generic_industry_name(name):
        return False
    if name in CATEGORY_KEYWORDS or name in REGION_KEYWORDS:
        return False
    if COUNT_PATTERN.fullmatch(name):
        return False
    if name in NON_INSTITUTION_TERMS or name.endswith(NON_INSTITUTION_SUFFIXES):
        return False
    if name.endswith(WINNER_NAME_REJECTED_SUFFIXES):
        return False
    if name in institution_names:
        return False
    return not (institution_name and (name in institution_name or institution_name in name))


def extract_winner_name(query: str) -> str:
    """질의가 지목한 낙찰 업체명을 뽑습니다.

    업체 순위 질의("가장 많이 낙찰받은 업체", "업체별")는 특정 업체를 지목한
    조회가 아니므로 업체명을 뽑지 않습니다. 공공기관·행정 구역으로 판정되는
    토큰은 업체가 아니므로 기관으로 남깁니다("한국농어촌공사" 는 업체가 아닙니다).
    """
    normalized = _normalize_text(query)
    lowered = normalized.lower()
    if any(marker in lowered for marker in AGGREGATE_AXIS_MARKERS["winner"]):
        return ""
    if WINNER_AXIS_PATTERN.search(lowered):
        return ""

    institution_name = _normalize_text(
        str(extract_institution_scope(normalized).get("institution_name") or "")
    )
    institution_names = frozenset(
        _normalize_text(name) for name in _extract_institution_list(normalized)
    )

    # 법인 표지가 앞에 붙은 후보는 앞부분이 일반 업종어여도 업체로 봅니다.
    candidates: list[tuple[str, bool]] = []
    for pattern in (
        WINNER_CORPORATE_PREFIX_PATTERN,
        WINNER_SUBJECT_PATTERN,
        WINNER_POSSESSIVE_PATTERN,
    ):
        has_corporate_marker = pattern is WINNER_CORPORATE_PREFIX_PATTERN
        candidates.extend(
            (match.group("name"), has_corporate_marker) for match in pattern.finditer(normalized)
        )
    for token in RESULT_LIST_TOKEN_SPLIT_PATTERN.split(normalized):
        for suffix in WINNER_NAME_SUFFIXES:
            if token.endswith(suffix) and len(token) > len(suffix):
                candidates.append((token, False))
                break

    for raw, corporate_marker in candidates:
        candidate = _strip_winner_particle(raw)
        if _winner_candidate_allowed(
            candidate,
            institution_name,
            institution_names,
            corporate_marker=corporate_marker,
        ):
            return candidate
    return ""


INSTITUTION_CANDIDATE_PATTERN = re.compile(r"^[가-힣a-zA-Z0-9]{2,20}$")
FIRST_NOUN_PHRASE_OF_PATTERN = re.compile(r"^(.*?)(?<!\s)의(?:\s|[,\.?!]|$)")
INSTITUTION_LIST_SPLIT_PATTERN = re.compile(
    r"\s*,\s*|\s*(?:와|과)\s+|(?<=[가-힣a-zA-Z0-9])(?:와|과)(?=[가-힣a-zA-Z0-9])"
)
NON_INSTITUTION_TERMS = frozenset(
    {
        "낙찰금액",
        "추정가격",
        "예정가격",
        "기초금액",
        "투찰금액",
        "입찰금액",
        "공고금액",
        "낙찰률",
        "투찰률",
        "사정률",
        "경쟁률",
        "낙찰자",
        "낙찰업체",
        "수요기관",
        "공고번호",
        "공고명",
    }
)
NON_INSTITUTION_SUFFIXES = ("금액", "가격", "낙찰률", "투찰률", "사정률", "경쟁률")

COMPARISON_MARKERS = ("비교", "대비", "차이", "vs")
# 비교 질의라도 입찰 지표를 묻지 않으면 지역·기관 비교가 아닙니다.
# "부산이랑 대구 여행 코스 비교" 같은 질의를 통계 비교로 오인하지 않습니다.
COMPARISON_DOMAIN_MARKERS = ("공고", "낙찰", "입찰", "개찰", "유찰")
COMPARISON_TARGET_CONNECTOR_PATTERN = re.compile(r"\s*(?:이랑|랑|하고|와|과|,)\s*")
# 대상 구간은 지표·도메인 표지 앞까지만 봅니다. leftmost 일치가 곧 절단 위치입니다.
COMPARISON_TARGET_STOP_PATTERN = re.compile(
    r"공고\s*건수|낙찰\s*결과|낙찰\s*건수|낙찰\s*공고|낙찰률|평균|건수|결과|통계|순위|"
    r"공고|낙찰|입찰|개찰|유찰|비교|대비|차이|vs",
    re.IGNORECASE,
)
REGION_ADMIN_SUFFIXES = ("특별자치시", "특별자치도", "특별시", "광역시", "시", "도")
COMPARISON_TARGET_TRAILING_PARTICLES = ("의", "은", "는", "이", "가", "을", "를", "만")

# 기간·분류 비교는 두 대상을 같은 지표로 집계합니다. 기간 표현과 분야어를
# 기관명 후보로 넘기면 기관 비교 경로가 이름을 해석하지 못해 빈 결과가 됩니다.
COMPARISON_PERIOD_PATTERN = re.compile(
    r"(?P<jaeyear>재작년)|"
    r"(?P<lastyear>작년|지난해|지난\s*해|전년)|"
    r"(?P<thisyear>올해|금년|이번\s*해)|"
    r"(?P<lastmonth>지난\s*달)|"
    r"(?P<thismonth>이번\s*달|이번달|이번\s*월)|"
    r"(?P<lastquarter>지난\s*분기)|"
    r"(?P<thisquarter>이번\s*분기)|"
    r"(?P<year>\d{4})\s*년"
)
COMPARISON_PERIOD_TOKEN_PATTERN = re.compile(
    r"^(?:재작년|작년|지난해|지난\s*해|전년|올해|금년|이번\s*해|"
    r"이번\s*달|이번달|이번\s*월|지난\s*달|지난\s*분기|이번\s*분기|\d{4}\s*년)$"
)
# "공사" 는 공기업 이름(한국전력공사)의 일부로도 흔히 나옵니다. 낱말 경계와
# 뒤따르는 조사·연결어를 함께 요구해 이름 속 글자를 분야어로 읽지 않습니다.
COMPARISON_CATEGORY_TOKENS = {
    "공사": "Cnstwk",
    "건설": "Cnstwk",
    "용역": "Servc",
    "물품": "Thng",
    "외자": "Frgcpt",
}
COMPARISON_CATEGORY_PATTERN = re.compile(
    r"(?<![가-힣A-Za-z0-9])(?P<word>공사|건설|용역|물품|외자)"
    r"(?=\s|랑|이랑|하고|와|과|,|낙찰|평균|공고|건수|수|를|을|의|$)"
)
# 기간·분류 대상 구간은 지표·도메인 표지 앞까지만 봅니다. "대비"·"비교" 는 두
# 대상을 잇는 표지이므로 절단 위치가 아닙니다. 이 표지를 절단 위치로 쓰면
# "용역 대비 공사" 처럼 표지가 두 분야어 사이에 있을 때 두 번째 분야어가 잘립니다.
COMPARISON_METRIC_STOP_PATTERN = re.compile(
    r"공고\s*건수|낙찰\s*결과|낙찰\s*건수|낙찰\s*공고|낙찰률|평균|건수|결과|통계|순위|"
    r"공고|낙찰|입찰|개찰|유찰",
    re.IGNORECASE,
)
COMPARISON_BETWEEN_TARGETS_PATTERN = re.compile(
    r"^[\s,/·]*(?:이랑|랑|하고|와|과|대비|비교|차이|vs)[\s,/·]*$", re.IGNORECASE
)


def _strip_comparison_particle(text: str) -> str:
    cleaned = text.strip()
    for particle in COMPARISON_TARGET_TRAILING_PARTICLES:
        if cleaned.endswith(particle) and len(cleaned) > len(particle):
            return cleaned[: -len(particle)].strip()
    return cleaned


def _match_comparison_region(text: str) -> str:
    """구간이 지역명과 행정 접미사로만 되어 있으면 대표 지역명을 돌려줍니다.

    "서울시" 는 "서울", "충청북도" 는 "충북" 으로 정규화해야 기관명 부분 일치와
    같은 값 체계를 씁니다. "대구 여행 코스" 처럼 뒤에 다른 낱말이 붙으면 지역
    대상이 아닙니다.
    """
    for label, aliases in REGION_ALIASES.items():
        for alias in sorted(aliases, key=len, reverse=True):
            if not text.startswith(alias):
                continue
            remainder = text[len(alias) :]
            if not remainder or remainder in REGION_ADMIN_SUFFIXES:
                return label
    return ""


def _comparison_period_label(
    *,
    kind: str,
    year: int,
    start: date,
    end: date,
    ongoing: bool,
    month: int = 0,
    quarter: int = 0,
) -> str:
    if kind == "year":
        if ongoing:
            return f"{year}년({start.month}월 {start.day}일~{end.month}월 {end.day}일)"
        return f"{year}년(1년 전체)"
    if kind == "month":
        if ongoing:
            return f"{year}년 {month}월({month}월 1일~{month}월 {end.day}일)"
        return f"{year}년 {month}월(1개월 전체)"
    if ongoing:
        return f"{year}년 {quarter}분기({start.month}월 1일~{end.month}월 {end.day}일)"
    return f"{year}년 {quarter}분기(3개월 전체)"


def _comparison_period_target(match: re.Match[str]) -> dict[str, Any]:
    """기간 표현 하나를 같은 산식의 창과 표시 라벨로 바꿉니다.

    _parse_time_window 와 같은 달력 산식을 쓰되, 비교에는 두 창이 필요하므로
    각 표현을 따로 해석합니다.
    """
    today = date.today()
    group = match.lastgroup
    kind = "year"
    month = 0
    quarter = 0
    ongoing = False

    if group == "jaeyear":
        year = today.year - 2
        start, end = date(year, 1, 1), date(year, 12, 31)
        key = str(year)
    elif group == "lastyear":
        year = today.year - 1
        start, end = date(year, 1, 1), date(year, 12, 31)
        key = str(year)
    elif group == "thisyear":
        year = today.year
        start, end = date(year, 1, 1), today
        ongoing = True
        key = str(year)
    elif group == "lastmonth":
        last_prev_day = today.replace(day=1) - timedelta(days=1)
        year, month = last_prev_day.year, last_prev_day.month
        start = date(year, month, 1)
        end = last_prev_day
        kind = "month"
        key = f"{year}-{month:02d}"
    elif group == "thismonth":
        year, month = today.year, today.month
        start, end = date(year, month, 1), today
        kind = "month"
        ongoing = True
        key = f"{year}-{month:02d}"
    elif group == "lastquarter":
        quarter = (today.month - 1) // 3 + 1
        quarter -= 1
        year = today.year
        if quarter == 0:
            quarter = 4
            year -= 1
        start = date(year, QUARTER_MONTHS[quarter][0], 1)
        end = _month_end(year, QUARTER_MONTHS[quarter][1])
        kind = "quarter"
        key = f"{year}-Q{quarter}"
    elif group == "thisquarter":
        quarter = (today.month - 1) // 3 + 1
        year = today.year
        start = date(year, QUARTER_MONTHS[quarter][0], 1)
        end = today
        kind = "quarter"
        ongoing = True
        key = f"{year}-Q{quarter}"
    else:
        year_match = re.search(r"\d{4}", match.group())
        year = int(year_match.group()) if year_match else today.year
        start, end = date(year, 1, 1), date(year, 12, 31)
        key = str(year)

    label = _comparison_period_label(
        kind=kind,
        year=year,
        start=start,
        end=end,
        ongoing=ongoing,
        month=month,
        quarter=quarter,
    )
    return {
        "key": key,
        "label": label,
        "date_from": start.isoformat(),
        "date_to": end.isoformat(),
        "ongoing": ongoing,
    }


def _comparison_targets_are_connected(between: str) -> bool:
    """두 대상 사이가 연결어·비교 표지뿐인지 확인합니다."""
    return bool(COMPARISON_BETWEEN_TARGETS_PATTERN.match(between))


def _comparison_period_targets(query: str) -> list[dict[str, Any]]:
    """기간 표현 두 개가 연결어로 묶이면 기간 비교 대상으로 돌려줍니다.

    지표·도메인 표지 앞 구간만 보므로 "작년 대비 올해 용역 공고 건수" 처럼
    분야어가 섞여도 기간 두 개를 찾습니다. 두 기간의 산식은 _parse_time_window
    와 같습니다.
    """
    lowered = _query_lower(query)
    if not any(marker in lowered for marker in COMPARISON_DOMAIN_MARKERS):
        return []
    stop = COMPARISON_METRIC_STOP_PATTERN.search(lowered)
    prefix = lowered[: stop.start()] if stop else lowered
    matches = list(COMPARISON_PERIOD_PATTERN.finditer(prefix))
    if len(matches) != 2:
        return []
    between = prefix[matches[0].end() : matches[1].start()]
    # "공주시 이번 달 지난달 낙찰 건수 비교" 처럼 연결어 없이 두 기간이 나란히
    # 오는 표현도 비교 표지가 있으면 기간 비교로 봅니다. 사이에 다른 낱말이
    # 끼면 비교 대상이 아니므로 그대로 둡니다.
    if not _comparison_targets_are_connected(between) and (
        between.strip() or not any(marker in lowered for marker in COMPARISON_MARKERS)
    ):
        return []
    targets = [_comparison_period_target(match) for match in matches]
    if targets[0]["key"] == targets[1]["key"]:
        return []
    return targets


def _comparison_category_targets(query: str) -> list[dict[str, Any]]:
    """분야어 두 개가 연결어로 묶이면 분류 비교 대상으로 돌려줍니다.

    "한국전력공사와 한국농어촌공사" 처럼 기관명 속 글자는 낱말 경계 조건에서
    걸러지므로 기관 비교 판정을 빼앗지 않습니다.
    """
    lowered = _query_lower(query)
    if not any(marker in lowered for marker in COMPARISON_DOMAIN_MARKERS):
        return []
    stop = COMPARISON_METRIC_STOP_PATTERN.search(lowered)
    prefix = lowered[: stop.start()] if stop else lowered
    matches = list(COMPARISON_CATEGORY_PATTERN.finditer(prefix))
    if len(matches) != 2:
        return []
    if not _comparison_targets_are_connected(prefix[matches[0].end() : matches[1].start()]):
        return []
    keys = [COMPARISON_CATEGORY_TOKENS[match.group("word")] for match in matches]
    if len(set(keys)) != 2:
        return []
    return [{"key": key, "label": _category_label(key)} for key in keys]


COMPARISON_INSTITUTION_UNRESOLVED_SUFFIXES = ("공사", "공단")


def _comparison_unresolved_institution_candidate(query: str) -> str:
    """기간 비교에서 해석되지 않은 기관 후보 낱말을 찾습니다.

    기간 표현·분야어·지표어는 기관 후보가 아니며, "공사" 한 낱말도 분야어이므로
    제외합니다. 공기업·공단 이름 모양의 낱말이 남으면 그 이름을 공통 기관 조건으로
    써서 전체 기관 값으로 조용히 넓어지지 않게 합니다.
    """
    normalized = _normalize_text(query)
    for token in RESULT_LIST_TOKEN_SPLIT_PATTERN.split(normalized):
        cleaned = _strip_institution_particle(token)
        if len(cleaned) <= 2:
            continue
        if COMPARISON_PERIOD_TOKEN_PATTERN.fullmatch(cleaned):
            continue
        if cleaned in COMPARISON_CATEGORY_TOKENS:
            continue
        if cleaned in NON_INSTITUTION_TERMS or cleaned.endswith(NON_INSTITUTION_SUFFIXES):
            continue
        if cleaned.endswith(COMPARISON_INSTITUTION_UNRESOLVED_SUFFIXES):
            return cleaned
    return ""


def _normalize_comparison_target(text: str) -> tuple[str, str] | None:
    cleaned = _strip_comparison_particle(text)
    if not cleaned:
        return None
    if COMPARISON_PERIOD_TOKEN_PATTERN.fullmatch(cleaned) or cleaned in COMPARISON_CATEGORY_TOKENS:
        return None
    region = _match_comparison_region(cleaned)
    if region:
        return "region", region
    if not INSTITUTION_CANDIDATE_PATTERN.fullmatch(cleaned):
        return None
    if cleaned in NON_INSTITUTION_TERMS or cleaned.endswith(NON_INSTITUTION_SUFFIXES):
        return None
    return "institution", cleaned


def _extract_comparison_targets(query: str) -> tuple[list[str], list[str]]:
    """비교 질의에서 지역명과 정확 기관명 대상을 추출합니다.

    "비교/대비/차이/vs" 표지와 입찰 도메인 표지가 함께 있을 때만 동작합니다.
    지표·도메인 표지 앞 구간을 연결어(이랑·랑·하고·와·과·쉼표)로 나눠 정확히
    두 대상이 나올 때만 비교로 봅니다. 연결어가 없는 "부산 대구 공고 건수 비교"
    는 공백 토큰 두 개가 모두 대상일 때만 인정합니다. 지역과 기관이 섞이거나
    "낙찰금액과 추정가격" 처럼 지표 이름이 대상 자리에 오면 비교가 아닙니다.

    반환값은 (지역명 목록, 정확 기관명 목록)이며 둘 중 하나만 채워집니다.
    """
    normalized = _normalize_text(query)
    lowered = normalized.lower()
    if not any(marker in lowered for marker in COMPARISON_MARKERS):
        return [], []
    if not any(marker in lowered for marker in COMPARISON_DOMAIN_MARKERS):
        return [], []

    # 기간·분류 비교의 두 대상은 기관명 후보가 아닙니다. "이번 분기 대비 지난 분기"
    # 를 어절 단위로 나누면 [이번, 분기] 가 기관명으로 승격되어 기관 비교 경로가
    # 빈 표를 내므로, 전용 판정이 성립하면 여기서 끝냅니다.
    if _comparison_period_targets(normalized) or _comparison_category_targets(normalized):
        return [], []

    stop = COMPARISON_TARGET_STOP_PATTERN.search(lowered)
    prefix = normalized[: stop.start()] if stop else normalized
    parts = [
        part.strip(" \t\r\n.,;:!?~()[]{}'\"·/|\\-")
        for part in COMPARISON_TARGET_CONNECTOR_PATTERN.split(prefix)
    ]
    parts = [part for part in parts if part]
    if len(parts) != 2:
        tokens = [token for token in re.split(r"\s+", prefix.strip()) if token]
        if len(tokens) != 2:
            return [], []
        parts = tokens

    targets: list[tuple[str, str]] = []
    for part in parts:
        target = _normalize_comparison_target(part)
        if target is None:
            return [], []
        targets.append(target)

    kinds = {target[0] for target in targets}
    if len(kinds) != 1:
        return [], []
    if len({target[1] for target in targets}) != 2:
        return [], []
    kind = next(iter(kinds))
    labels = [target[1] for target in targets]
    if kind == "region":
        return labels, []
    return [], labels


def _extract_institution_list(query: str) -> list[str]:
    """질의에서 여러 기관을 나열해 비교·구분을 요청하는 기관 후보 목록을 추출합니다.

    질의에서 "의" 로 끝나는 첫 명사구 바로 앞 구간만 봅니다.
    그 구간을 쉼표 또는 "와 "/"과 "/"와"/"과"(바로 뒤가 다음 이름) 로 나눠 두 개 이상이고,
    각 부분이 공백·괄호·대괄호가 없는 2~20자 한글·영문·숫자 문자열일 때만 후보 목록을 반환합니다.
    조건을 하나라도 어기면 빈 목록을 반환합니다.
    """
    normalized = _normalize_text(query)
    match = FIRST_NOUN_PHRASE_OF_PATTERN.search(normalized)
    if not match:
        return []

    prefix = match.group(1).strip()
    if not prefix:
        return []

    parts = INSTITUTION_LIST_SPLIT_PATTERN.split(prefix)
    if len(parts) < 2:
        return []

    candidates: list[str] = []
    for part in parts:
        cleaned = part.strip()
        if not INSTITUTION_CANDIDATE_PATTERN.fullmatch(cleaned):
            return []
        if cleaned in NON_INSTITUTION_TERMS or cleaned.endswith(NON_INSTITUTION_SUFFIXES):
            return []
        candidates.append(cleaned)

    return candidates


def _normalize_text(value: str | None) -> str:
    return unicodedata.normalize("NFC", (value or "").strip())


def _mask_non_category_construction(text: str) -> str:
    """분야어가 아닌 건설(업체·기관·사업명 내부)을 공백으로 가립니다."""
    category_starts = {match.start() for match in CONSTRUCTION_CATEGORY_PATTERN.finditer(text)}

    def _keep_or_mask(match: re.Match[str]) -> str:
        if match.start() in category_starts:
            return match.group(0)
        return " " * len(match.group(0))

    return re.sub("건설", _keep_or_mask, text)


def _mask_category_scope_tokens(normalized: str) -> str:
    """분야 키워드로 오인되는 공기업·행정구역 이름을 공백으로 가립니다.

    "한국전력공사" 의 공사 나 "대전광역시 종합건설본부" 의 기관명처럼 분야
    키워드를 품은 이름을 먼저 지워, 이름 안의 글자를 분야로 읽지 않게 합니다.
    사업명 접미사(도로공사 등)로 끝나는 이름은 기관 범위에서 빼야 합니다.
    "부산신항배후도로공사" 를 지우면 실제 분야어인 공사까지 사라집니다.
    """
    masked = normalized.lower()
    names = list(_extract_public_corporation_tokens(normalized))
    scope = extract_institution_scope(normalized, include_entity_org_tokens=False)
    if scope.get("institution_name"):
        names.append(str(scope["institution_name"]))
    for name in sorted(set(names), key=len, reverse=True):
        token = name.lower()
        if token:
            masked = masked.replace(token, " " * len(token))
    return masked


def extract_category(query: str) -> tuple[str, str]:
    """질의의 분야 키워드와 분야 코드를 판정합니다.

    업체명·기관명·사업명에 붙은 건설(대한건설, 종합건설본부, 주택건설공사)은
    분야어가 아니고, 공기업 이름의 공사(한국전력공사)도 분야어가 아닙니다.
    분야어가 여럿이면 한국어 명사구의 핵어 규칙에 따라 문장에서 가장 뒤에 나온
    것을 씁니다. RAG 플래너와 채팅 플래너가 이 함수 하나를 함께 씁니다.
    """
    masked = _mask_non_category_construction(_mask_category_scope_tokens(_normalize_text(query)))
    last_position = -1
    matched_keyword = ""
    matched_category = ""
    for keyword, category in CATEGORY_KEYWORDS.items():
        position = masked.rfind(keyword)
        if position > last_position:
            last_position = position
            matched_keyword = keyword
            matched_category = category
    return matched_keyword, matched_category


def _category_label(category: str | None) -> str:
    category_code = _normalize_text(str(category or ""))
    return CATEGORY_LABELS.get(category_code, category_code or "-")


def _query_lower(query: str) -> str:
    return _normalize_text(query).lower()


# 공고 종류는 공고명 안 낱말과 겹칩니다. "재공고 방지 용역" 처럼 사업 명사가
# 앞에 붙은 제목을 재공고 질의로 읽지 않도록, 종류 표기 바로 뒤에 오는
# 금지 낱말을 확인합니다.
NOTICE_KIND_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?<![가-힣])취소\s*된\s*공고"), "취소공고"),
    (re.compile(r"(?<![가-힣])변경\s*된\s*공고"), "변경공고"),
    (re.compile(r"(?<![가-힣])취소\s*공고"), "취소공고"),
    (re.compile(r"(?<![가-힣])정정\s*공고"), "변경공고"),
    (re.compile(r"(?<![가-힣])변경\s*공고"), "변경공고"),
    (re.compile(r"(?<![가-힣])신규\s*공고"), "등록공고"),
    (re.compile(r"(?<![가-힣])등록\s*공고"), "등록공고"),
    (re.compile(r"(?<![가-힣])재\s*공고"), "재공고"),
)
NOTICE_KIND_IGNORED_FOLLOWERS = ("방지", "금지")


def extract_notice_kind(query: str) -> str:
    """질의가 지목한 공고 종류(ntce_kind_nm)를 돌려줍니다.

    "재공고", "취소공고", "변경공고", "등록공고" 만 인정하고, 표기가 없으면
    빈 문자열입니다. "변경 사항", "취소 방법" 처럼 종류 표기가 아닌 일반어와,
    "재공고 방지 용역" 처럼 사업 명사가 결합한 제목 속 낱말은 무시합니다.
    종류가 여러 번 나오면 가장 앞의 표기를 씁니다.
    """
    normalized = _normalize_text(query)
    if not normalized:
        return ""

    best_position = len(normalized)
    best_kind = ""
    for pattern, kind in NOTICE_KIND_PATTERNS:
        for match in pattern.finditer(normalized):
            remainder = normalized[match.end() :].lstrip()
            if any(remainder.startswith(word) for word in NOTICE_KIND_IGNORED_FOLLOWERS):
                continue
            if match.start() < best_position:
                best_position = match.start()
                best_kind = kind
            break
    return best_kind


def _is_count_statistics_query(query: str) -> bool:
    """건수 표현만으로 통계 질의인지 판정합니다.

    "몇 건", "몇 개", "총 몇", "얼마나 올라/있" 은 목록 요청에도 쓰입니다.
    공고·낙찰 도메인 표지가 함께 있을 때만 정형 집계 대상으로 봅니다.
    """
    lowered = _query_lower(query)
    if any(marker in lowered for marker in LIST_REQUEST_MARKERS):
        return False
    if not COUNT_QUERY_PATTERN.search(lowered):
        return False
    return any(marker in lowered for marker in COUNT_QUERY_DOMAIN_MARKERS)


QUOTED_TITLE_PATTERN = re.compile(
    r'["\'\u2018\u201c\u300c\u300e\[]([^"\'\u2019\u201d\u300d\u300f\]]{2,})["\'\u2019\u201d\u300d\u300f\]]'
)


def is_entity_specific_query(query: str) -> bool:
    """특정 공고나 사업, 기관, 업체를 지목하는 개체 조회 질의인지 판정합니다.

    속성어(낙찰금액, 낙찰업체 등)의 단순 출현이나 단순 카테고리 괄호는 개체로 판정하지 않으며,
    구조적 개체 식별 신호(인용구, 공고번호 패턴, 기관/법인 형태, '~의 [속성]' 지목 수식 구조)가
    존재할 때만 True를 반환합니다.
    """
    normalized = _normalize_text(query)
    lowered = normalized.lower()

    # 1. 따옴표나 각괄호 인용구 (예: "안녕 자두야", '도로 포장', [소방설비], 「...」, 『...』)
    if QUOTED_TITLE_PATTERN.search(normalized):
        return True

    # 2. 공고번호 또는 문서 ID 패턴 (예: R26BK01659912-001, bid_10015925)
    if re.search(r"\b(?:[A-Za-z0-9]{8,15}-\d{2,3}|bid_\d{6,10})\b", lowered):
        return True

    # 3. 법인 형태 또는 공공/교육/의료 기관 접미사 지목
    if any(suffix in lowered for suffix in ENTITY_ORG_SUFFIXES):
        return True

    # 4. 대상 지목 수식 구조 ('...의 [속성]': 예: '...공사의 수요기관', '...용역의 낙찰업체', '...사업의 입찰 참가 조건')
    return bool(
        re.search(
            r"(?:용역|공사|구매|사업|제작|설치|공고|입찰|권)\s*의\s*(?:공고번호|수요기관|낙찰업체|낙찰자|최종\s*낙찰|낙찰금액|예정가격|1순위|입찰\s*참가|참가자격)",
            lowered,
        )
        or re.search(
            r"\b\S+\s*의\s*(?:공고번호|수요기관|낙찰업체|낙찰자|최종\s*낙찰자|1순위\s*낙찰업체|입찰\s*참가\s*조건)",
            lowered,
        )
    )


RESULT_ATTRIBUTE_PATTERN = re.compile(
    r"(?:최종\s*낙찰(?:자)?|낙찰\s*업체|낙찰업체|낙찰\s*자|낙찰자|낙찰\s*금액|낙찰금액|1순위\s*낙찰(?:업체)?|낙찰\s*내역|낙찰내역)"
)


def is_result_query(query: str) -> bool:
    """질의가 낙찰 결과(낙찰업체, 낙찰자, 낙찰금액, 낙찰률 등)를 묻는지 판정합니다.

    기존 결과 질의 마커(RESULT_QUERY_MARKERS), 통계 키워드(낙찰률), 개체 속성 지목 패턴을 재사용합니다.
    """
    lowered = _query_lower(query)
    if any(marker in lowered for marker in RESULT_QUERY_MARKERS):
        return True
    if "낙찰률" in lowered:
        return True
    return bool(RESULT_ATTRIBUTE_PATTERN.search(lowered))


def is_multi_institution_result_list_query(query: str) -> bool:
    """기관 둘 이상을 나열한 낙찰 결과 목록 질의인지 판정합니다.

    "한국전력공사와 한국농어촌공사 낙찰 결과 5건" 은 기관 접미사만 보면 개체
    지정 질의로 판정되어 기존 목록 판정이 거짓이 됩니다. 기관을 둘 이상
    나열했다면 개체 하나를 지목한 질의가 아니므로, 기존 목록 판정을 바꾸지
    않고 이 함수로 목록 경로에 보냅니다.
    """
    lowered = _query_lower(query)
    if not _extract_enumerated_institution_names(_normalize_text(query)):
        return False
    if not is_result_query(query):
        return False
    if COUNT_PATTERN.search(lowered):
        return True
    return any(marker in lowered for marker in RESULT_LIST_MARKERS)


def is_multi_institution_announcement_list_query(query: str) -> bool:
    """기관 둘 이상을 나열한 공고 목록 질의인지 판정합니다.

    "공주시 및 서산시 및 천안시 공고", "공주시, 서산시, 천안시 공고" 처럼 개수나
    목록 표지가 없어 기존 공고 목록 판정이 거짓이 되는 질의를 목록 경로에
    보냅니다. 기존 판정을 바꾸지 않고 기관 나열이 확인될 때만 참을 돌려줍니다.
    지역 비교("부산이랑 대구 공고 건수 비교")와 통계·설명 질의, 낙찰 결과 질의는
    각자의 기존 경로가 맡도록 거짓입니다.
    """
    normalized = _normalize_text(query)
    lowered = _query_lower(query)
    if len(_extract_enumerated_institution_names(normalized)) < 2:
        return False
    if not any(marker in lowered for marker in COUNT_QUERY_DOMAIN_MARKERS):
        return False
    comparison_regions, comparison_institutions = _extract_comparison_targets(normalized)
    if comparison_regions or comparison_institutions:
        return False
    if _has_excluded_list_marker(lowered):
        return False
    if any(marker in lowered for marker in ANNOUNCEMENT_RESULT_STATUS_MARKERS):
        return False
    return not any(marker in lowered for marker in ANNOUNCEMENT_EXPLANATION_MARKERS)


# 요청 어미는 어절마다 나열하지 않고 한 번에 뗍니다. 띄어 쓴 "줄 수 있어" 처럼
# 여러 어절로 갈라지는 꼬리는 어절 분리 전에 문자열 단위로 지웁니다.
RESULT_LIST_REQUEST_TAIL_PATTERN = re.compile(
    r"(?:보여\s*줄\s*수\s*있\S*|줄\s*수\s*있\S*|볼\s*수\s*있\S*|"
    r"보여\s*줄래\S*|보여\s*줘|알려\s*줄래\S*|알려\s*줘|"
    r"줄래\S*|볼래\S*|부탁\S*|가르쳐\S*|보내\S*|해\s*줘)"
)
RESULT_LIST_REQUEST_TAILS = (
    "해줘",
    "줄래요",
    "주세요",
    "볼래요",
    "줄래",
    "볼래",
    "부탁해요",
    "부탁해",
    "부탁드려요",
    "부탁",
    "가르쳐줘",
    "가르쳐",
    "보내줘",
    "보내",
)


def _strip_request_tail(token: str) -> str:
    """어절 꼬리에 붙은 요청 어미를 한 번에 떼어 냅니다."""
    for tail in RESULT_LIST_REQUEST_TAILS:
        if token == tail:
            return ""
        if token.endswith(tail) and len(token) > len(tail):
            return token[: -len(tail)]
    return token


def extract_bid_ntce_no(query: str) -> str:
    """질의에 등장한 공고번호를 대문자로 정규화해 돌려줍니다.

    엄격형 패턴에 맞는 값만 인정하므로 접수번호나 금액 숫자는 빈 문자열입니다.
    """
    match = BID_NTCE_NO_PATTERN.search(_normalize_text(query))
    return match.group("bid_ntce_no").upper() if match else ""


def is_bid_number_query(query: str) -> bool:
    """공고번호 하나를 지목한 단건 조회 질의인지 판정합니다.

    공고번호 형식이 있고, 계산 방법이나 의미를 묻는 설명형 표지가 없을 때만
    참입니다. 설명형은 기존 LLM 경로가 맡습니다.
    """
    normalized = _normalize_text(query)
    if not BID_NTCE_NO_PATTERN.search(normalized):
        return False
    lowered = normalized.lower()
    return not any(marker in lowered for marker in BID_NTCE_NO_EXPLANATION_MARKERS)


def _result_list_token_allowed(token: str) -> bool:
    """어절에서 조사·어미를 뗀 어간이 모두 허용 어휘인지 판정합니다."""
    if token in RESULT_LIST_VOCABULARY_WORDS:
        return True
    if any(pattern.fullmatch(token) for pattern in RESULT_LIST_VOCABULARY_PATTERNS):
        return True

    current = _strip_request_tail(token)
    while current:
        if current in RESULT_LIST_VOCABULARY_WORDS:
            return True
        if any(pattern.fullmatch(current) for pattern in RESULT_LIST_VOCABULARY_PATTERNS):
            return True
        for suffix in RESULT_LIST_TOKEN_SUFFIXES:
            if current.endswith(suffix):
                current = current[: -len(suffix)]
                break
        else:
            return False
    return True


def _has_only_result_list_vocabulary(lowered: str) -> bool:
    """질의의 모든 어절이 기간·분류·낙찰 표지·요청 동사 어간으로만 되어 있는지 판정합니다."""
    normalized = lowered
    for spaced, compact in RESULT_LIST_SPACED_PERIOD_REPLACEMENTS:
        normalized = normalized.replace(spaced, compact)
    normalized = RESULT_LIST_REQUEST_TAIL_PATTERN.sub(" ", normalized)
    tokens = [token for token in RESULT_LIST_TOKEN_SPLIT_PATTERN.split(normalized) if token]
    return bool(tokens) and all(_result_list_token_allowed(token) for token in tokens)


def _has_excluded_list_marker(lowered: str) -> bool:
    """목록 판정에서 제외할 통계·모호 수량 표지가 있는지 확인합니다.

    낙찰 결과 목록과 공고 목록이 같은 표지 집합과 같은 정규식 규칙을 쓰도록
    한 곳에 모읍니다. "몇 건"·"몇 개" 는 띄어 쓴 형태와 붙여 쓴 형태를 모두
    표지로 봅니다.
    """
    return any(marker in lowered for marker in RESULT_LIST_EXCLUDED_MARKERS) or bool(
        RESULT_LIST_EXCLUDED_PATTERN.search(lowered)
    )


# 마감일 창·금액 조건·정렬 표지는 목록의 범위를 좁히는 표지입니다. 개수나
# 목록·리스트 같은 목록 신호가 없어도 조건이 대상을 한정하므로, 결과·공고를
# 요청하는 표현과 요청 동사가 함께 있으면 목록 요청으로 봅니다. 통계 표현
# (몇 건·건수·평균)이 있으면 목록이 아니라 통계로 남깁니다.
LIST_SCOPE_RESULT_MARKERS = ("낙찰 결과", "낙찰결과", "낙찰 내역", "낙찰내역")
LIST_SCOPE_ANNOUNCEMENT_MARKER = "공고"
LIST_SCOPE_STATISTICS_PATTERN = re.compile(r"몇\s*(?:건|개)|건수|평균")
CONDITION_LIST_SCOPE_RESULT = "result"
CONDITION_LIST_SCOPE_ANNOUNCEMENT = "announcement"


def _has_parsed_list_scope_conditions(query: str) -> bool:
    """이 브랜치가 파싱한 마감일 창·금액 조건·정렬 표지가 있는지 판정합니다."""
    if _parse_close_window(query) is not None:
        return True
    amount_filters = extract_amount_filters(query)
    if amount_filters.get("min_amount") is not None or amount_filters.get("max_amount") is not None:
        return True
    return bool(extract_sort_filters(query))


def _condition_list_scope(query: str) -> str:
    """조건 표지가 붙은 목록 요청의 도메인을 돌려줍니다.

    "낙찰 결과"·"낙찰 내역" 을 요청하면 낙찰 결과 목록, "공고" 를 요청하면 공고
    목록입니다. 요청 동사가 없거나 파싱된 조건이 없으면 빈 문자열입니다. 통계
    표현(몇 건·건수·평균)이 함께 있으면 목록이 아니라 통계 질의로 남깁니다.
    """
    lowered = _query_lower(query)
    if LIST_SCOPE_STATISTICS_PATTERN.search(lowered):
        return ""
    if not RESULT_LIST_REQUEST_VERB_PATTERN.search(lowered):
        return ""
    if not _has_parsed_list_scope_conditions(query):
        return ""
    if any(marker in lowered for marker in LIST_SCOPE_RESULT_MARKERS):
        return CONDITION_LIST_SCOPE_RESULT
    if LIST_SCOPE_ANNOUNCEMENT_MARKER in lowered:
        return CONDITION_LIST_SCOPE_ANNOUNCEMENT
    return ""


def is_result_list_query(query: str) -> bool:
    """낙찰 결과를 개별 목록으로 요청하는 질의인지 판정합니다.

    결과 마커에 목록 신호가 붙은 기존 형태 외에, 목록 신호 없이 요청 동사
    (보여·알려·줘 등)만 붙은 요청과 낙찰 단독 표현에 개수가 붙은 요청도
    목록 질의로 봅니다. 요청 동사만으로 판정하는 경로는 질의의 모든 어절이
    허용 어휘(기간·분류·낙찰 표지·요청 동사 어간·수량)일 때만 적용해,
    업체명·기관명·지역명이 섞인 질의가 전체 최신 목록으로 새지 않게 합니다.
    통계 표지, 공고번호 단건, 설명형 질의는 각자의 경로가 맡도록 거짓을
    반환하고, 개체를 지목한 질의도 기존 개체 조회 경로를 그대로 쓰도록
    거짓을 반환합니다. 마감일 창·금액 조건·정렬 표지가 파싱됐고 "낙찰 결과"·
    "낙찰 내역" 과 요청 동사가 함께 있으면 그 조건을 목록의 범위 표지로 인정해
    참을 반환합니다. 조건이 없는 "낙찰 결과 보여줘" 의 판정은 그대로입니다.
    """
    lowered = _query_lower(query)
    has_result_marker = any(marker in lowered for marker in RESULT_QUERY_MARKERS)
    has_count = bool(COUNT_PATTERN.search(lowered))
    has_list_marker = any(marker in lowered for marker in RESULT_LIST_MARKERS) or has_count
    has_request_verb = bool(RESULT_LIST_REQUEST_VERB_PATTERN.search(lowered))
    has_vocabulary_only = (
        has_result_marker
        and has_request_verb
        and not has_list_marker
        and _has_only_result_list_vocabulary(lowered)
    )
    matched = (
        (has_result_marker and has_list_marker)
        or has_vocabulary_only
        or ("낙찰" in lowered and has_count)
        or _condition_list_scope(query) == CONDITION_LIST_SCOPE_RESULT
    )
    if not matched:
        return False
    if _has_excluded_list_marker(lowered):
        return False
    if RESULT_LIST_BID_NUMBER_PATTERN.search(lowered):
        return False
    if any(marker in lowered for marker in RESULT_LIST_EXPLANATION_MARKERS):
        return False
    return not is_entity_specific_query(query)


ANNOUNCEMENT_FRESHNESS_MARKERS = ("올라온", "등록된", "게시된", "신규", "최신")
# 공고번호·공고명은 필드 이름입니다. 필드 이름이 질의 앞에 오면 '공고' 뒤를 보는
# 부정 전방 탐색이 거르지 못하므로 목록 판정 전체에서 먼저 배제합니다.
ANNOUNCEMENT_FIELD_MARKER_PATTERN = re.compile(r"공고\s*(?:번호|명)")
ANNOUNCEMENT_LIST_REQUEST_VERB_FRAGMENT = (
    r"(?:보여|알려|뽑아|나열|줄\s*수\s*있|볼\s*수\s*있|줄래|볼래|부탁|가르쳐|보내|줘)"
)
ANNOUNCEMENT_LIST_PATTERN = re.compile(
    r"공고(?!\s*(?:번호|명)|된|되는|하는|할|될|하였|했)[^.!?\n]{0,20}?"
    r"(?:"
    + COUNT_PATTERN_FRAGMENT
    + r"|"
    + "|".join(RESULT_LIST_MARKERS)
    + r"|"
    + ANNOUNCEMENT_LIST_REQUEST_VERB_FRAGMENT
    + r"|"
    + "|".join(ANNOUNCEMENT_FRESHNESS_MARKERS)
    + r")"
)
ANNOUNCEMENT_QUERY_COUNT_PATTERN = COUNT_PATTERN
ANNOUNCEMENT_EXPLANATION_MARKERS = (
    "방법",
    "규정",
    "설명",
    "어디서",
    "어떻게",
    "기능",
    "가능",
    "보는 법",
    "뭐야",
    "의미",
    "절차",
    "이란",
    "란",
)
ANNOUNCEMENT_RESULT_STATUS_MARKERS = ("낙찰", "유찰", "개찰")


def _has_announcement_list_scope(lowered: str) -> bool:
    """요청 동사만 있는 공고 목록 질의에 신선도 표지가 함께 있는지 봅니다.

    분류나 연도만 있는 "서울의 2026년 ... 용역 공고를 알려줘" 는 지목형 조회이지
    최신 목록 요청이 아니고, "최근"·"요즘" 같은 막연한 표현도 범위를 정하지
    못합니다. 그래서 동사 단독 경로는 올라온·등록된·게시된·신규·최신 표지를
    요구하고, 나머지는 기존 최신성 힌트 경로에 남깁니다.
    """
    return any(marker in lowered for marker in ANNOUNCEMENT_FRESHNESS_MARKERS)


def is_announcement_list_query(query: str) -> bool:
    """낙찰 표지 없이 공고 자체를 개별 목록으로 요청하는 질의인지 판정합니다.

    목록 신호가 '공고' 바로 뒤에 붙어야 합니다. '공고번호'나 띄어 쓴 '공고 번호',
    '공고 명'처럼 공고가 필드 이름의 일부이거나, 목록 신호가 문장 멀리 떨어진
    일반 질의는 여기에 해당하지 않습니다.
    낙찰·유찰·개찰처럼 결과 상태를 가리키는 질의는 기존 낙찰 결과 목록 경로가
    그대로 맡도록 거짓을 반환합니다.
    설명·방법·기능·가능 여부를 묻는 질의는 목록 요청이 아니므로 LLM 경로로 남깁니다.
    개수나 '목록'·'리스트' 표지가 있으면 참이고, 요청 동사만 있으면 신선도
    표지(올라온·등록된·게시된·신규·최신)를 함께 요구해 범위 없는 "공고 알려줘" 가
    전체 최신 목록으로 새지 않게 합니다. 마감일 창·금액 조건·정렬 표지가
    파싱됐고 요청 동사가 함께 있으면 그 조건을 목록의 범위 표지로 인정해
    참을 반환합니다. 조건이 없는 "공고 보여줘" 의 판정은 그대로입니다.
    """
    lowered = _query_lower(query)
    if ANNOUNCEMENT_FIELD_MARKER_PATTERN.search(lowered):
        return False
    # 신선도 표지나 요청 동사만으로 통계 질의가 공고 목록으로 새지 않도록,
    # 낙찰 결과 목록과 같은 통계 제외 표지를 먼저 검사합니다. "두 건" 의 "건" 은
    # 개수 단위이지 "건수" 통계 표지가 아닙니다.
    if _has_excluded_list_marker(lowered):
        return False
    if any(marker in lowered for marker in ANNOUNCEMENT_RESULT_STATUS_MARKERS):
        return False
    if any(marker in lowered for marker in ANNOUNCEMENT_EXPLANATION_MARKERS):
        return False
    if (
        not ANNOUNCEMENT_LIST_PATTERN.search(lowered)
        and _condition_list_scope(query) != CONDITION_LIST_SCOPE_ANNOUNCEMENT
    ):
        return False
    if is_result_list_query(query):
        return False
    if ANNOUNCEMENT_QUERY_COUNT_PATTERN.search(lowered):
        return True
    if any(marker in lowered for marker in RESULT_LIST_MARKERS):
        return True
    if _condition_list_scope(query) == CONDITION_LIST_SCOPE_ANNOUNCEMENT:
        return not is_entity_specific_query(query)
    if not _has_announcement_list_scope(lowered):
        return False
    # 신선도 표지만 있는 경로는 범위가 없는 전체 최신 목록입니다. 기관명을
    # 지목한 질의까지 참이 되면 기관 조건 없이 전체 목록을 내게 되므로,
    # 낙찰 결과 목록과 같은 개체 지정 판정으로 걸러 기존 개체 조회 경로에
    # 맡깁니다.
    return not is_entity_specific_query(query)


# 개수 단위 뒤에 비교·범위 표지가 붙은 수는 목록 개수가 아니라 조건 수치입니다.
# "참가업체 수 10개 이상" 의 10개를 목록 크기로 읽으면 조건이 사라진 10행 표가 나옵니다.
COUNT_CONDITION_SUFFIX_PATTERN = re.compile(r"\s*(?:이상|이하|초과|미만|넘는|넘게|넘)")
# 조건 수치 판정은 수치 앞에 붙은 속성 명사로 가릅니다. "공고 10건 이상",
# "낙찰 결과 10개 이상" 은 목록 개수이고, "참가업체 수 10개 이상" 만 조건입니다.
COUNT_ATTRIBUTE_PREFIX_PATTERN = re.compile(
    r"(?:참가\s*업체|참여\s*업체|업체\s*수|추정\s*가격|기초\s*금액|낙찰\s*금액|금액)\s*$"
)


def extract_result_limit(query: str, default: int = 5, maximum: int = 20) -> int:
    """목록 질의의 요청 건수를 안전한 범위로 정규화합니다.

    숫자와 한글 수사(한~스무)를 같은 자리에서 읽고, 단위(개/건)가 붙은 형태만
    개수로 인정합니다. 범위는 1 이상 maximum 이하로 자릅니다. 단위 뒤에 비교
    표지가 붙어도 수치 앞이 속성 명사(참가업체 수·추정가격·금액 등)이면 조건
    수치이므로 목록 개수로 읽지 않습니다.
    """
    lowered = _query_lower(query)
    for match in COUNT_PATTERN.finditer(lowered):
        if COUNT_CONDITION_SUFFIX_PATTERN.match(
            lowered, match.end()
        ) and COUNT_ATTRIBUTE_PREFIX_PATTERN.search(lowered[: match.start()]):
            continue
        numeral = re.sub(r"\s*(?:개|건)$", "", match.group(0)).strip()
        value = int(numeral) if numeral.isdigit() else KOREAN_NUMERALS.get(numeral)
        if value is None:
            continue
        return min(max(value, 1), maximum)
    return default


# 마감 표지는 기간 표현을 공고일이 아니라 마감일 창으로 바꾸는 신호입니다.
# 표지가 있어도 아래 상대 기간 표현이 함께 있어야 창이 확정됩니다.
CLOSE_MARKER_PATTERN = re.compile(r"마감")
CLOSE_IMMINENT_PATTERN = re.compile(r"마감\s*임박")
CLOSE_WINDOW_DAYS = 3
# 정렬을 뜻하는 표지(순·순서·순으로·정렬)가 마감 표지에 붙으면 그 표현은 기간
# 창이 아니라 정렬 요청입니다. 창을 판정하기 전에 이 표현을 걷어냅니다.
CLOSE_SORT_PATTERN = re.compile(
    r"마감(?:\s*(?:이|가))?"
    r"(?:\s*(?:임박|빠른|일|날짜))?"
    r"(?:\s*(?:한|인|하는|되는))?"
    r"\s*(?:순서|순으로|순|정렬)"
)

AMOUNT_UNIT_MULTIPLIERS: dict[str, int] = {
    "억": 100_000_000,
    "천만": 10_000_000,
    "백만": 1_000_000,
    "만": 10_000,
    "천": 1_000,
    "원": 1,
}
# 금액 비교 표지는 최장 일치를 먼저 두어 "넘는" 이 "넘" 으로 잘리지 않게 합니다.
AMOUNT_COMPARATOR_PATTERN = re.compile(r"이상|이하|초과|미만|넘는|넘게|넘")
AMOUNT_MIN_COMPARATORS = ("이상", "초과", "넘는", "넘게", "넘")
AMOUNT_MAX_COMPARATORS = ("이하", "미만")
AMOUNT_UNIT_PATTERN = re.compile(r"억|천만|백만|만|천|원")
AMOUNT_TOKEN_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*(억|천만|백만|만|천)?")
# 비교 표지 바로 앞이 금액 표기로 끝날 때만 금액 조건으로 읽습니다.
# "10개 이상" 의 "10개" 처럼 단위가 아닌 글자로 끝나면 금액이 아닙니다.
AMOUNT_TOKEN_SEQUENCE_PATTERN = re.compile(r"((?:\d+(?:\.\d+)?\s*(?:억|천만|백만|만|천)?\s*)+원?)$")
# 단위 없는 수는 금액이 아닙니다. "5 이상 공고" 의 5 는 금액 하한이 아니라
# 범위 없는 조건 수치이므로, 금액 명사가 수치 바로 앞에 붙은 경우에만 금액으로
# 읽습니다. 이 규칙이 없으면 금액 조건이 없던 기존 질의에 min_amount 5 가 붙습니다.
AMOUNT_NOUN_PREFIX_PATTERN = re.compile(
    r"(?:추정\s*가격|추정\s*금액|기초\s*금액|낙찰\s*금액|낙찰가|금액|예산)\s*$"
)
AMOUNT_FIELD_MARKERS: tuple[tuple[str, str], ...] = (
    ("낙찰금액", "sucsf_bid_amt"),
    ("낙찰가", "sucsf_bid_amt"),
    ("기초금액", "base_amount"),
    ("추정가격", "presmpt_prce"),
    ("추정 금액", "presmpt_prce"),
)
DEFAULT_AMOUNT_FIELD = "presmpt_prce"
# 낙찰 결과 조회에 걸 금액 축의 기본 컬럼입니다. 공고 조회는 추정가격이
# 기본이지만 낙찰 테이블에는 추정가격 컬럼이 없으므로 낙찰금액을 씁니다.
RESULT_AMOUNT_FIELD = "sucsf_bid_amt"
# 낙찰 결과 테이블(bid_results)에는 추정가격·기초금액·마감일 열이 없습니다. 조건이
# 걸렸는데 조회 계층이 조용히 빼면 사용자는 조건이 적용된 줄 압니다. 적용하지 못한
# 조건을 응답에 밝힐 수 있도록 지원 여부를 한 곳에서 판정합니다.
RESULT_UNSUPPORTED_AMOUNT_FIELDS = ("presmpt_prce", "base_amount")
RESULT_UNSUPPORTED_SORT_FIELDS = ("bid_clse_dt", "presmpt_prce", "base_amount")
UNSUPPORTED_CONDITION_LABELS = {
    "presmpt_prce": "추정가격",
    "base_amount": "기초금액",
    "bid_clse_dt": "마감일",
}


def collect_unapplied_result_conditions(
    filters: dict[str, Any] | None,
) -> list[dict[str, str]]:
    """낙찰 결과 조회가 적용하지 못한 금액·정렬 조건을 모읍니다.

    낙찰 결과 테이블에는 추정가격·기초금액·마감일 열이 없습니다. 금액 조건이나
    정렬 표지가 그 축을 가리키면 조건을 버리지 않고 목록으로 남겨 응답 단계가
    "그 조건 없이 조회했다"고 밝히게 합니다. 낙찰금액 조건과 개찰일 정렬처럼
    지원되는 축은 담지 않습니다.
    """
    if not filters:
        return []
    conditions: list[dict[str, str]] = []
    has_amount_bound = (
        filters.get("min_amount") is not None or filters.get("max_amount") is not None
    )
    amount_field = _normalize_text(str(filters.get("amount_field") or ""))
    if has_amount_bound and amount_field in RESULT_UNSUPPORTED_AMOUNT_FIELDS:
        conditions.append({"kind": "amount", "field": amount_field})
    order_by = _normalize_text(str(filters.get("order_by") or ""))
    if order_by in RESULT_UNSUPPORTED_SORT_FIELDS:
        conditions.append({"kind": "order", "field": order_by})
    has_close_window = bool(filters.get("close_from") or filters.get("close_to"))
    if has_close_window and not any(
        condition["field"] == "bid_clse_dt" for condition in conditions
    ):
        conditions.append({"kind": "close_window", "field": "bid_clse_dt"})
    return conditions


def unapplied_result_condition_notice(conditions: list[dict[str, str]] | None) -> str:
    """적용하지 못한 조건을 한 줄 안내 문장으로 만듭니다."""
    labels: list[str] = []
    for condition in conditions or []:
        label = UNSUPPORTED_CONDITION_LABELS.get(str(condition.get("field") or ""))
        if label and label not in labels:
            labels.append(label)
    if not labels:
        return ""
    return (
        f"낙찰 결과에는 {'·'.join(labels)} 정보가 없어 그 조건 없이 조회했습니다. "
        "낙찰금액 기준 조건이나 개찰일 순 정렬은 적용할 수 있습니다."
    )


SORT_AMOUNT_DESC_MARKERS = (
    "높은순",
    "높은 순",
    "큰순",
    "큰 순",
    "많은순",
    "많은 순",
    "비싼순",
    "비싼 순",
    "금액순",
    "금액 순",
    "가장 큰",
    "가장 높은",
)
SORT_AMOUNT_ASC_MARKERS = ("낮은순", "낮은 순", "적은순", "적은 순")


def _compact_text(value: str) -> str:
    return re.sub(r"\s+", "", value)


def _parse_close_window(query: str) -> tuple[str, str] | None:
    """마감 표지와 상대 기간 표현으로 마감일 창을 계산합니다.

    마감 표지가 있어도 함께 쓰인 상대 기간 표현이 아래 네 가지일 때만 창을
    확정합니다. 확정하지 못하면 기존 기간 해석(공고일 창)을 그대로 둡니다.

    | 표현 | 마감일 창 |
    | --- | --- |
    | `마감 임박` | 오늘 ~ 오늘+3일 |
    | `오늘 마감` | 오늘 |
    | `내일 마감` | 내일 |
    | `이번 주 마감` | 이번 주 월요일 ~ 일요일 |

    `마감 임박순`, `마감 빠른 순`, `마감일 순` 처럼 정렬 표지가 붙은 마감
    표현은 창을 만들지 않습니다. 그 표현은 정렬 요청이므로 창으로 읽으면
    정렬 대상이 오늘 이후 사흘로 잘립니다.
    """
    lowered = _query_lower(query)
    scope = CLOSE_SORT_PATTERN.sub(" ", lowered)
    if not CLOSE_MARKER_PATTERN.search(scope):
        return None
    today = date.today()
    if CLOSE_IMMINENT_PATTERN.search(scope):
        return today.isoformat(), (today + timedelta(days=CLOSE_WINDOW_DAYS)).isoformat()
    if "오늘" in scope:
        return today.isoformat(), today.isoformat()
    if "내일" in scope:
        tomorrow = today + timedelta(days=1)
        return tomorrow.isoformat(), tomorrow.isoformat()
    if "이번 주" in scope or "이번주" in scope:
        week_start = today - timedelta(days=today.weekday())
        week_end = week_start + timedelta(days=6)
        return week_start.isoformat(), week_end.isoformat()
    return None


def _amount_value(text: str) -> int | None:
    """금액 표기 문자열을 원 단위 정수로 바꿉니다.

    "5억" 은 500,000,000, "1억 5천만" 은 150,000,000, "300000000원" 은
    300,000,000 입니다. 단위가 없으면 원 단위로 읽습니다.
    """
    cleaned = text.strip()
    if cleaned.endswith("원"):
        cleaned = cleaned[: -len("원")].strip()
    tokens = AMOUNT_TOKEN_PATTERN.findall(cleaned)
    if not tokens:
        return None
    total = 0.0
    for raw_number, unit in tokens:
        total += float(raw_number) * AMOUNT_UNIT_MULTIPLIERS[unit or "원"]
    value = round(total)
    return value or None


def extract_amount_field(query: str, default: str = DEFAULT_AMOUNT_FIELD) -> str:
    """질의가 지목한 금액 컬럼을 돌려줍니다. 지목이 없으면 default 입니다."""
    lowered = _query_lower(query)
    for marker, field in AMOUNT_FIELD_MARKERS:
        if marker in lowered:
            return field
    return default


def has_explicit_amount_field(query: str) -> bool:
    """질의가 금액 컬럼을 낱말로 지목했는지 판정합니다.

    "낙찰 결과" 처럼 결과 도메인만 말하고 금액 축을 지목하지 않은 질의와
    "낙찰금액" 처럼 축을 직접 말한 질의를 가릅니다.
    """
    lowered = _query_lower(query)
    return any(marker in lowered for marker, _ in AMOUNT_FIELD_MARKERS)


def extract_amount_filters(query: str) -> dict[str, Any]:
    """질의의 금액 하한·상한과 대상 컬럼을 읽습니다.

    금액 표기 바로 뒤에 비교 표지(이상·이하·초과·미만·넘는·넘게)가 붙은 경우만
    조건으로 봅니다. 이상은 경계 포함, 초과·넘는·넘게는 경계 제외이므로 제외
    조건의 하한은 1원을 더합니다. "10개 이상" 처럼 금액 단위가 없는 수는
    조건으로 읽지 않습니다. 단위 없는 수라도 금액 명사(추정가격·기초금액·
    낙찰금액·금액·예산)가 바로 앞에 있으면 금액으로 읽습니다.
    """
    lowered = _query_lower(query)
    filters: dict[str, Any] = {}
    for match in AMOUNT_COMPARATOR_PATTERN.finditer(lowered):
        prefix = lowered[: match.start()].rstrip()
        token_match = AMOUNT_TOKEN_SEQUENCE_PATTERN.search(prefix)
        if not token_match:
            continue
        raw_sequence = token_match.group(1)
        if not AMOUNT_UNIT_PATTERN.search(raw_sequence) and not AMOUNT_NOUN_PREFIX_PATTERN.search(
            prefix[: token_match.start()]
        ):
            continue
        value = _amount_value(raw_sequence)
        if value is None:
            continue
        comparator = match.group(0)
        if comparator in AMOUNT_MIN_COMPARATORS:
            candidate = value if comparator == "이상" else value + 1
            current = filters.get("min_amount")
            filters["min_amount"] = max(current, candidate) if current is not None else candidate
        elif comparator in AMOUNT_MAX_COMPARATORS:
            candidate = value if comparator == "이하" else value - 1
            current = filters.get("max_amount")
            filters["max_amount"] = min(current, candidate) if current is not None else candidate
        else:
            continue
        filters["amount_field"] = extract_amount_field(lowered)
    return filters


def extract_sort_filters(query: str) -> dict[str, str]:
    """질의의 정렬 축과 방향을 읽습니다.

    금액 정렬(높은 순·큰 순·많은 순·비싼 순·금액순)은 대상 금액 컬럼의 내림차순,
    낮은 순·적은 순은 오름차순입니다. 마감 임박순·마감 빠른 순처럼 마감 표지에
    정렬 표지가 붙으면 마감일 오름차순입니다. 표지가 없으면 빈 사전을 돌려주어
    기존 정렬을 유지합니다.

    낙찰 결과 질의가 금액 축을 낱말로 지목하지 않았으면 금액 조건과 같은 규칙
    (is_result_amount_scope)을 정렬 축에도 적용해 낙찰금액을 씁니다. 추정가격을
    명시한 질의는 그 축을 그대로 두어 미적용 안내도 유지합니다.
    """
    lowered = _query_lower(query)
    compact = _compact_text(lowered)
    if CLOSE_SORT_PATTERN.search(lowered):
        return {"order_by": "bid_clse_dt", "order_dir": "asc"}
    amount_field = extract_amount_field(lowered)
    if not has_explicit_amount_field(lowered) and is_result_amount_scope(lowered):
        amount_field = RESULT_AMOUNT_FIELD
    if any(_compact_text(marker) in compact for marker in SORT_AMOUNT_ASC_MARKERS):
        return {"order_by": amount_field, "order_dir": "asc"}
    if any(_compact_text(marker) in compact for marker in SORT_AMOUNT_DESC_MARKERS):
        return {"order_by": amount_field, "order_dir": "desc"}
    return {}


def _month_end(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def _parse_year_month_window(lowered: str) -> tuple[date, date, bool] | None:
    """일자 없이 연도와 월만 지정한 표현을 기간으로 바꿉니다.

    반환값의 셋째 항목은 그 표현이 **명시적 기간 한정 표현**인지 여부입니다.
    `2025년 1월부터 3월까지` 처럼 범위를 나타내는 조사가 붙으면 참이고,
    `2025년` 이나 `2026년 9월분` 처럼 연월이 그냥 등장하면 거짓입니다.
    후자는 공고명의 일부(사업연도, 대상월)일 수 있어 호출부가 다르게 다룹니다.

    지원하는 형태입니다.

    | 표현 | 해석 |
    | --- | --- |
    | `2025년 1월부터 3월까지` | 2025-01-01 ~ 2025-03-31 |
    | `2024년 11월부터 2025년 2월까지` | 2024-11-01 ~ 2025-02-28 |
    | `2025년 3월` | 2025-03-01 ~ 2025-03-31 |
    | `2025년` | 2025-01-01 ~ 2025-12-31 |

    월을 넘길 때 30일을 더하는 방식은 말일이 어긋나므로 달력 말일을 씁니다.
    """
    # 연도가 양쪽에 다 붙은 경우를 먼저 봅니다. 뒤 연도를 앞 연도를 덮어쓰면
    # 해를 넘기는 기간이 뒤집힙니다.
    cross_year = re.search(
        r"(\d{4})\s*년\s*(\d{1,2})\s*월\s*(?:부터|~|-)\s*(\d{4})\s*년\s*(\d{1,2})\s*월", lowered
    )
    if cross_year:
        y1, m1, y2, m2 = (int(g) for g in cross_year.groups())
        if 1 <= m1 <= 12 and 1 <= m2 <= 12:
            start, end = sorted((date(y1, m1, 1), date(y2, m2, 1)))
            return start, _month_end(end.year, end.month), True

    same_year = re.search(r"(\d{4})\s*년\s*(\d{1,2})\s*월\s*(?:부터|~|-)\s*(\d{1,2})\s*월", lowered)
    if same_year:
        year, m1, m2 = (int(g) for g in same_year.groups())
        if 1 <= m1 <= 12 and 1 <= m2 <= 12:
            first, second = sorted((m1, m2))
            return date(year, first, 1), _month_end(year, second), True

    single_month = re.search(r"(\d{4})\s*년\s*(\d{1,2})\s*월", lowered)
    if single_month:
        year, month = (int(g) for g in single_month.groups())
        if 1 <= month <= 12:
            return date(year, month, 1), _month_end(year, month), False

    # 연도만 말한 경우입니다. 네 자리 숫자면 무엇이든 연도로 보면 금액이나
    # 공고번호가 걸리므로 "년" 글자가 붙은 것만 인정합니다.
    year_only = re.search(r"(\d{4})\s*년", lowered)
    if year_only:
        year = int(year_only.group(1))
        if 1900 <= year <= 2999:
            return date(year, 1, 1), date(year, 12, 31), False

    return None


QUARTER_MONTHS = {
    1: (1, 3),
    2: (4, 6),
    3: (7, 9),
    4: (10, 12),
}


def _quarter_window(year: int, start_q: int, end_q: int, explicit: bool) -> tuple[date, date, bool]:
    s_first, s_last = sorted((start_q, end_q))
    start_month = QUARTER_MONTHS[s_first][0]
    end_month = QUARTER_MONTHS[s_last][1]
    return date(year, start_month, 1), _month_end(year, end_month), explicit


def _parse_quarter_window(lowered: str) -> tuple[date, date, bool] | None:
    """분기 및 상반기/하반기 표현을 기간으로 바꿉니다.

    두 분기를 잇는 범위 표현만 explicit_range=True 이고,
    단독 분기나 상/하반기는 explicit_range=False 입니다.
    """
    # 1. 크로스 연도 분기 범위 (예: 2025년 4분기부터 2026년 1분기)
    cross_quarter = re.search(
        r"(\d{4})\s*년\s*([1-4])\s*분기(?:\s*\([^)]*\))?\s*(?:부터|와|과|및|~|-|,|\s+)\s*(\d{4})\s*년\s*([1-4])\s*분기",
        lowered,
    )
    if cross_quarter:
        y1, q1, y2, q2 = (int(g) for g in cross_quarter.groups())
        if 1 <= q1 <= 4 and 1 <= q2 <= 4:
            s_date = date(y1, QUARTER_MONTHS[q1][0], 1)
            e_date = _month_end(y2, QUARTER_MONTHS[q2][1])
            start, end = sorted((s_date, e_date))
            return start, end, True

    # 2. 동일 연도 분기 범위 (예: 2026년 1분기(1월~3월)와 2분기(4월~6월), 2026년 1분기와 2분기, 1분기~2분기 등)
    same_year_quarter = re.search(
        r"(\d{4})\s*년\s*([1-4])\s*분기(?:\s*\([^)]*\))?\s*(?:부터|와|과|및|~|-|,|\s+)\s*([1-4])\s*분기",
        lowered,
    )
    if same_year_quarter:
        year, q1, q2 = (int(g) for g in same_year_quarter.groups())
        if 1 <= q1 <= 4 and 1 <= q2 <= 4:
            return _quarter_window(year, q1, q2, True)

    # 3. 단독 분기 (예: 2026년 1분기)
    single_quarter = re.search(r"(\d{4})\s*년\s*([1-4])\s*분기", lowered)
    if single_quarter:
        year, q = (int(g) for g in single_quarter.groups())
        if 1 <= q <= 4:
            return _quarter_window(year, q, q, False)

    # 4. 상반기 / 하반기 (예: 2026년 상반기, 2026년 하반기, 하반기)
    half_with_year = re.search(r"(\d{4})\s*년\s*(상반기|하반기)", lowered)
    if half_with_year:
        year = int(half_with_year.group(1))
        half = half_with_year.group(2)
        if half == "상반기":
            return date(year, 1, 1), date(year, 6, 30), False
        return date(year, 7, 1), date(year, 12, 31), False

    half_standalone = re.search(r"(?<![가-힣])(상반기|하반기)(?![가-힣])", lowered)
    if half_standalone:
        year = date.today().year
        half = half_standalone.group(1)
        if half == "상반기":
            return date(year, 1, 1), date(year, 6, 30), False
        return date(year, 7, 1), date(year, 12, 31), False

    return None


def _parse_time_window(query: str) -> tuple[str, str, str, bool]:
    """질의에서 기간을 뽑습니다.

    넷째 반환값은 그 기간이 명시적 기간 한정 표현에서 나왔는지 여부입니다.
    거짓이면 연월이 공고명 일부일 수 있으므로 호출부가 hard filter 승격을
    보류할 수 있습니다.
    """
    lowered = _query_lower(query)
    today = date.today()

    def _to_iso(start: date, end: date) -> tuple[str, str]:
        return start.isoformat(), end.isoformat()

    korean_dates = [
        date(int(year), int(month), int(day))
        for year, month, day in re.findall(
            r"(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일", lowered
        )
    ]
    if len(korean_dates) >= 2:
        start_date, end_date = sorted((korean_dates[0], korean_dates[1]))
        start, end = _to_iso(start_date, end_date)
        return start, end, "recent", True

    iso_dates = [
        date(int(year), int(month), int(day))
        for year, month, day in re.findall(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", lowered)
    ]
    if len(iso_dates) >= 2:
        start_date, end_date = sorted((iso_dates[0], iso_dates[1]))
        start, end = _to_iso(start_date, end_date)
        return start, end, "recent", True

    # 분기 및 상반기/하반기 표현 (월 표현이 함께 포함된 경우 예: "1분기(1월~3월)" 대비 분기 규칙 우선 적용)
    quarter_window = _parse_quarter_window(lowered)
    if quarter_window is not None:
        window_start, window_end, explicit_range = quarter_window
        start, end = _to_iso(window_start, window_end)
        return start, end, "recent", explicit_range

    # 일자 없이 연/월만 말하는 표현입니다. 위의 완전한 날짜 쌍보다 뒤에 두어야
    # "2026년 4월 19일부터 2026년 4월 25일까지" 가 연월 규칙에 먼저 잡히지 않습니다.
    year_month_window = _parse_year_month_window(lowered)
    if year_month_window is not None:
        window_start, window_end, explicit_range = year_month_window
        start, end = _to_iso(window_start, window_end)
        return start, end, "recent", explicit_range

    if "오늘" in lowered:
        start, end = _to_iso(today, today)
        return start, end, "today", True

    if "어제" in lowered:
        yesterday = today - timedelta(days=1)
        start, end = _to_iso(yesterday, yesterday)
        return start, end, "recent", True

    if "이번 주" in lowered:
        week_start = today - timedelta(days=today.weekday())
        start, end = _to_iso(week_start, today)
        return start, end, "recent", True

    if "이번 달" in lowered or "이번 월" in lowered or "이번달" in lowered:
        start, end = _to_iso(today.replace(day=1), today)
        return start, end, "recent", True

    if "지난달" in lowered:
        first_this_month = today.replace(day=1)
        last_prev_month = first_this_month - timedelta(days=1)
        first_prev_month = last_prev_month.replace(day=1)
        start, end = _to_iso(first_prev_month, last_prev_month)
        return start, end, "recent", True

    # "재작년" 은 "작년" 을 포함하므로 먼저 판정합니다.
    if "재작년" in lowered:
        start, end = _to_iso(date(today.year - 2, 1, 1), date(today.year - 2, 12, 31))
        return start, end, "recent", True

    if "올해" in lowered or "금년" in lowered or "이번 해" in lowered:
        start, end = _to_iso(date(today.year, 1, 1), today)
        return start, end, "recent", True

    if "작년" in lowered or "지난해" in lowered or "지난 해" in lowered or "전년" in lowered:
        start, end = _to_iso(date(today.year - 1, 1, 1), date(today.year - 1, 12, 31))
        return start, end, "recent", True

    day_match = re.search(r"(?:최근|지난)\s*(\d+)\s*일", lowered)
    if day_match:
        days = max(int(day_match.group(1)), 1)
        start, end = _to_iso(today - timedelta(days=days - 1), today)
        return start, end, "recent", True

    month_match = re.search(r"(?:최근|지난)\s*(\d+)\s*(?:개월|달)", lowered)
    if month_match:
        months = max(int(month_match.group(1)), 1)
        start, end = _to_iso(today - timedelta(days=(30 * months) - 1), today)
        return start, end, "recent", True

    year_match = re.search(r"(?:최근|지난)\s*(\d+)\s*(?:년|해)", lowered)
    if year_match:
        years = max(int(year_match.group(1)), 1)
        is_half = re.match(r"\s*반", lowered[year_match.end() :]) is not None
        offset_days = (365 * years) + 182 if is_half else (365 * years) - 1
        start, end = _to_iso(today - timedelta(days=offset_days), today)
        return start, end, "recent", True

    week_match = re.search(r"(?:최근|지난)\s*(\d+)\s*주(?!년)", lowered)
    if week_match:
        weeks = max(int(week_match.group(1)), 1)
        start, end = _to_iso(today - timedelta(days=(7 * weeks) - 1), today)
        return start, end, "recent", True

    if "최근 한 달" in lowered or "최근 1달" in lowered or "최근 한달" in lowered:
        start, end = _to_iso(today - timedelta(days=29), today)
        return start, end, "recent", True

    if "최근" in lowered or "요즘" in lowered:
        start, end = _to_iso(today - timedelta(days=6), today)
        return start, end, "recent", True

    return "", "", "", False


def _requested_group_limit(lowered: str) -> int:
    """축 표에 요청된 행 수를 읽습니다. 없으면 기본 상한입니다.

    "상위 N" 처럼 행 수가 명시된 표기를 먼저 읽고, 그 다음 "가장 많이",
    "최다", "1위" 처럼 첫 행만 요청한 표현을 1행으로 읽습니다.
    """
    for pattern in (GROUP_TOP_PATTERN, GROUP_RANK_COUNT_PATTERN):
        match = pattern.search(lowered)
        if not match:
            continue
        raw = match.group("count")
        value = int(raw) if raw.isdigit() else KOREAN_NUMERALS.get(raw)
        if value is not None:
            return min(max(value, 1), MAX_GROUP_LIMIT)
    if GROUP_FIRST_PATTERN.search(lowered):
        return 1
    if any(marker in lowered for marker in GROUP_SINGLE_TOP_MARKERS):
        return 1
    return DEFAULT_GROUP_LIMIT


def extract_aggregate_filters(query: str, filters: dict[str, Any] | None = None) -> dict[str, Any]:
    """질의에서 축별 집계의 축(group_by)과 지표(metric)를 읽습니다.

    목록 질의(result_limit)에는 축을 붙이지 않습니다. 목록과 축 표가 한 응답에서
    충돌하기 때문입니다. 축 마커가 없어도 분기 버킷이 있는 건수 질의는 축을
    "time" 으로 기록해 응답 단계가 낙찰 건수 대신 공고 건수를 고르게 합니다.
    업체 축은 낙찰 결과 테이블에만 있으므로 지표를 낙찰 건수로 두되, "낙찰률"
    표지가 있으면 기존 축과 같은 규칙으로 평균 낙찰률을 씁니다.
    "1위"·"상위 N"·"가장 많이" 표현은 축 표의 행 수로 읽습니다.
    """
    lowered = _query_lower(query)
    metric = ""
    if any(marker in lowered for marker in AGGREGATE_RATE_MARKERS):
        metric = "avg_rate"
    elif (
        any(marker in lowered for marker in AGGREGATE_BID_MARKERS)
        and "낙찰률" not in lowered
        and "평균" not in lowered
    ):
        metric = "bid_count"
    elif any(marker in lowered for marker in AGGREGATE_ANNOUNCEMENT_MARKERS):
        metric = "announcement_count"

    group_by = ""
    for axis, markers in AGGREGATE_AXIS_MARKERS.items():
        if any(marker in lowered for marker in markers):
            group_by = axis
            break
    if not group_by and WINNER_AXIS_PATTERN.search(lowered):
        group_by = "winner"

    current = filters or {}
    if group_by and current.get("result_limit"):
        group_by = ""
    if not group_by and metric and current.get("time_bucket") == "quarter":
        group_by = "time"
    if not group_by:
        return {}

    if group_by == "winner" and metric != "avg_rate":
        metric = "bid_count"

    aggregate: dict[str, Any] = {
        "group_by": group_by,
        "metric": metric or "announcement_count",
    }
    if group_by != "time":
        aggregate["group_limit"] = _requested_group_limit(lowered)
    return aggregate


def _requested_metric(lowered: str) -> str:
    """비교 응답이 낼 지표를 축별 집계와 같은 마커 우선순위로 읽습니다.

    축 마커가 없는 비교 질의에도 filters["metric"] 을 채워, 응답 단계가 요청한
    지표 하나만 표로 내게 합니다. 새 키를 만들지 않고 축별 집계와 같은 키를
    씁니다.
    """
    if any(marker in lowered for marker in AGGREGATE_RATE_MARKERS):
        return "avg_rate"
    if (
        any(marker in lowered for marker in AGGREGATE_BID_MARKERS)
        and "낙찰률" not in lowered
        and "평균" not in lowered
    ):
        return "bid_count"
    if any(marker in lowered for marker in AGGREGATE_ANNOUNCEMENT_MARKERS):
        return "announcement_count"
    return "bid_count" if "낙찰" in lowered else "announcement_count"


def _single_metric(lowered: str) -> str:
    """단일 지표 질의의 지표를 축별 집계와 같은 우선순위로 정합니다.

    extract_aggregate_filters 의 지표 결정 규칙(낙찰률 > 낙찰 > 공고)을 따르되,
    도메인 표지가 전혀 없으면 지표를 정하지 않고 빈 문자열을 돌려줍니다.
    """
    if any(marker in lowered for marker in AGGREGATE_RATE_MARKERS):
        return "avg_rate"
    if (
        any(marker in lowered for marker in AGGREGATE_BID_MARKERS)
        and "낙찰률" not in lowered
        and "평균" not in lowered
    ):
        return "bid_count"
    if any(marker in lowered for marker in AGGREGATE_ANNOUNCEMENT_MARKERS):
        return "announcement_count"
    if "낙찰" in lowered:
        return "bid_count"
    return ""


def is_result_amount_scope(query: str) -> bool:
    """금액 필드를 지목하지 않은 질의가 낙찰 결과 대상을 읽는지 판정합니다.

    낙찰 결과 목록뿐 아니라 낙찰 건수·평균 낙찰률·낙찰 금액 합계처럼 낙찰 결과를
    집계하는 통계 질의도 같은 테이블을 읽습니다. 이런 질의의 금액 축 기본값은
    추정가격이 아니라 낙찰금액입니다. 공고 목록·공고 통계는 추정가격을 그대로
    씁니다.
    """
    if is_result_query(query):
        return True
    return _single_metric(_query_lower(query)) in ("bid_count", "avg_rate")


def build_retrieval_plan(query: str) -> RetrievalPlan:
    normalized_query = _normalize_text(query)
    lowered = normalized_query.lower()

    is_entity = is_entity_specific_query(normalized_query)
    result_list_query = is_result_list_query(normalized_query)
    announcement_list_query = is_announcement_list_query(
        normalized_query
    ) or is_multi_institution_announcement_list_query(normalized_query)
    has_stat_keywords = any(keyword in lowered for keyword in STATISTICS_KEYWORDS) or (
        _is_count_statistics_query(normalized_query)
    )
    has_semantic_keywords = any(keyword in lowered for keyword in SEMANTIC_KEYWORDS)
    use_kb_status = any(keyword in lowered for keyword in KB_KEYWORDS)
    is_bid_number = is_bid_number_query(normalized_query)
    bid_ntce_no = extract_bid_ntce_no(normalized_query) if is_bid_number else ""

    if is_bid_number:
        use_sql = True
        use_vector = has_semantic_keywords
    elif is_entity:
        use_sql = True
        use_vector = True
    elif announcement_list_query or result_list_query or has_stat_keywords:
        use_sql = True
        use_vector = has_semantic_keywords
    elif has_semantic_keywords:
        use_sql = False
        use_vector = True
    elif use_kb_status:
        use_sql = False
        use_vector = False
    else:
        # 일반/기본 질의는 기본 벡터 검색
        use_sql = False
        use_vector = True

    inst_candidates = _extract_institution_list(normalized_query)
    enumerated_names = _extract_enumerated_institution_names(normalized_query)
    multi_result_list = is_multi_institution_result_list_query(normalized_query)
    comparison_regions, comparison_institutions = _extract_comparison_targets(normalized_query)
    comparison_dimension = ""
    comparison_targets: list[dict[str, Any]] = []
    if not comparison_regions and not comparison_institutions:
        period_targets = _comparison_period_targets(normalized_query)
        if period_targets:
            comparison_dimension = "time"
            comparison_targets = period_targets
        else:
            category_targets = _comparison_category_targets(normalized_query)
            if category_targets:
                comparison_dimension = "category"
                comparison_targets = category_targets
    if (
        inst_candidates
        or enumerated_names
        or comparison_regions
        or comparison_institutions
        or comparison_dimension
    ):
        use_sql = True

    date_from, date_to, time_bias, explicit_range = _parse_time_window(normalized_query)
    close_window = _parse_close_window(normalized_query)

    # 공고명에는 사업연도와 대상월이 흔히 들어갑니다. "2026년 9월분 학교급식물품"
    # 의 9월은 급식 대상 월이지 공고 게시월이 아니고, "(긴급)2025년 조사료
    # 지원사업" 의 2025년도 사업연도입니다. 이것을 게시 기간 hard filter 로
    # 승격하면 정답 공고가 검색에서 배제됩니다. 2026-08-27 측정에서 q24 는
    # 검색 결과가 0건이 됐고 q02 는 엉뚱한 연도의 공고를 가져왔으며, 필터만
    # 제거하면 둘 다 1위로 적중했습니다
    # (docs/analysis/retrieval_miss_investigation_20260827.md).
    #
    # 그래서 개체를 지목한 질의에서는 명시적 기간 한정 표현일 때만 필터로
    # 씁니다. time_bias 는 그대로 두어 최신성 힌트는 유지합니다.
    suppress_implicit_window = is_entity and not explicit_range
    if suppress_implicit_window:
        date_from, date_to = "", ""
    # 마감 표지와 상대 기간 표현이 함께 있으면 같은 기간을 공고일이 아니라
    # 마감일 창으로 읽습니다. 확정된 마감 창이 있을 때만 공고일 필터를 비웁니다.
    # 기간 비교는 대상마다 다른 창을 씁니다. 질의 전체에 한 창을 걸면 두 번째
    # 기간이 사라지므로 공통 기간 필터를 두지 않습니다.
    close_scope_applicable = close_window is not None and not is_entity
    if close_scope_applicable or comparison_dimension == "time":
        date_from, date_to = "", ""

    filters: dict[str, Any] = {}
    # 공고번호 단건은 다른 조건과 달리 목록·집계 경로로 새지 않게 전용 필터로
    # 넘깁니다. 값이 비어 있으면 키를 만들지 않습니다.
    if bid_ntce_no:
        filters["bid_ntce_no"] = bid_ntce_no
    if date_from:
        filters["date_from"] = date_from
    if date_to:
        filters["date_to"] = date_to
    if close_scope_applicable and close_window is not None:
        filters["close_from"], filters["close_to"] = close_window
    amount_filters = extract_amount_filters(normalized_query)
    # 낙찰 결과 질의가 금액 축을 낱말로 지목하지 않았으면 낙찰금액으로 읽습니다.
    # 공고 질의의 기본값(추정가격)을 그대로 두면 낙찰 테이블에 그 컬럼이 없어
    # 조회 계층이 조건을 버리고, "3억 넘는 낙찰 결과" 가 전체 낙찰로 넓어집니다.
    # 목록과 통계를 같은 규칙으로 판정해야 "3억 넘는 낙찰 건수" 도 조건이 걸립니다.
    if (
        "amount_field" in amount_filters
        and not has_explicit_amount_field(normalized_query)
        and is_result_amount_scope(normalized_query)
    ):
        amount_filters["amount_field"] = RESULT_AMOUNT_FIELD
    filters.update(amount_filters)
    filters.update(extract_sort_filters(normalized_query))

    # 특정 업체를 지목한 낙찰 이력 질문은 그 업체 조건을 SQL 로 넘깁니다. 조건을
    # 빼면 전체 최신 목록이 그 업체 실적처럼 답해집니다(조용한 범위 확대).
    # 아직 낙찰 전인 공고 목록에는 업체 조건을 걸지 않습니다.
    winner_name = extract_winner_name(normalized_query)
    if winner_name and (result_list_query or "낙찰" in lowered or "수주" in lowered):
        filters["winner_name"] = winner_name

    # 분기 비교 및 time_bucket 판정: 분기가 둘 이상이거나 "분기별"이 포함된 경우 quarter 버킷 활성화
    quarter_matches = re.findall(r"[1-4]\s*분기", lowered)
    is_multi_quarter = len(quarter_matches) >= 2 or bool(
        re.search(
            r"([1-4])\s*분기(?:\s*\([^)]*\))?\s*(?:부터|와|과|및|~|-|,|\s+)\s*([1-4])\s*분기",
            lowered,
        )
    )
    has_quarter_bucket = is_multi_quarter or ("분기별" in lowered)
    if has_quarter_bucket and not suppress_implicit_window:
        filters["time_bucket"] = "quarter"

    # 공기업·기관 이름과 업체명·기관명·사업명에 붙은 건설을 지운 뒤, 한국어
    # 명사구의 핵어 규칙에 따라 가장 뒤에 나온 분야어를 채택합니다.
    _, matched_category = extract_category(normalized_query)
    if matched_category:
        filters["category"] = matched_category
    # 분류 비교는 두 분야를 대상으로 삼으므로 마지막 분야 하나를 공통 조건으로
    # 남기지 않습니다.
    if comparison_dimension == "category":
        filters.pop("category", None)

    # 공고 종류 조건은 공고 목록·건수 질의에만 겁니다. 낙찰 결과 질의에 걸면
    # 결과 테이블에 없는 조건이 되어 답이 비거나, 결과와 무관한 종류로 범위를
    # 좁히게 됩니다.
    notice_kind = extract_notice_kind(normalized_query)
    if (
        notice_kind
        and (announcement_list_query or has_stat_keywords)
        and not result_list_query
        and not is_result_query(normalized_query)
    ):
        filters["notice_kind"] = notice_kind

    region_fallback_name = ""
    # 기관 나열은 목록 질의이거나, 공고·낙찰 도메인 표지가 있는 집계 질의에서만
    # 범위로 승격합니다. "부산이랑 대구 여행 코스 비교" 처럼 통계 표지("비교")만
    # 있는 비입찰 질의는 기관 조건을 만들지 않습니다.
    enumerated_scope = bool(
        announcement_list_query
        or result_list_query
        or multi_result_list
        or (has_stat_keywords and any(marker in lowered for marker in COUNT_QUERY_DOMAIN_MARKERS))
    )
    if comparison_dimension:
        filters["comparison_dimension"] = comparison_dimension
        filters["comparison_targets"] = comparison_targets
        # "한국전력공사 작년 대비 올해 공고 건수" 처럼 기관·지역 하나가 기간
        # 비교와 섞이면 그 범위를 두 대상 모두의 공통 조건으로 남깁니다.
        # 이 값을 버리면 비교가 전체 기관 기준 값으로 조용히 넓어집니다.
        if comparison_dimension == "time":
            shared_scope = extract_institution_scope(normalized_query)
            shared_name = _normalize_text(str(shared_scope.get("institution_name") or ""))
            if not shared_name:
                # 기관명을 해석하지 못했다고 전체 기관 값으로 넓히지 않습니다. 기관
                # 후보 낱말을 공통 조건으로 남겨 비교 아닌 같은 질문과 같은 결과를 냅니다.
                shared_name = _comparison_unresolved_institution_candidate(normalized_query)
            if shared_name:
                filters["institution_name"] = shared_name
                shared_aliases = shared_scope.get("institution_aliases")
                # 광역 지역명은 비교 아닌 질문과 같은 이름·별칭 조건을 씁니다.
                if (
                    not shared_aliases
                    and _is_broad_region_name(shared_name)
                    and shared_name not in OFFICIAL_PROVINCE_NAMES
                ):
                    shared_aliases = REGION_ALIASES.get(_match_comparison_region(shared_name), ())
                if shared_aliases:
                    filters["institution_aliases"] = list(shared_aliases)
    elif comparison_regions:
        filters["region_names"] = comparison_regions
    elif comparison_institutions:
        filters["institution_names"] = comparison_institutions
    elif inst_candidates:
        filters["institution_names"] = inst_candidates
    elif enumerated_names and enumerated_scope:
        # 기관을 둘 이상 지목하면 하나만 남기지 않고 모두 담습니다. 비교 표지가
        # 있으면 위 비교 경로가 먼저 잡으므로 목록으로 바꾸지 않습니다.
        filters["institution_names"] = enumerated_names
    elif not is_bid_number:
        for region in REGION_KEYWORDS:
            if region in lowered:
                filters["institution_name"] = region
                region_fallback_name = region
                break

    # 기관 범위는 목록·집계·개체 지정 질의에서만 붙입니다. 설명형 질의에 붙으면
    # 의미 검색이 기관 하나로 좁혀지고, 추출만으로 use_sql 이 켜지면 안 됩니다.
    # 기관 상세 조회에는 학교·병원 같은 개체 접미사 토큰을 기관 조건으로 승격하지
    # 않습니다. 그 토큰은 공고명의 일부인 경우가 많습니다.
    list_intent = announcement_list_query or result_list_query
    scope_applicable = bool(list_intent or has_stat_keywords or multi_result_list)
    scope_explanatory = any(marker in lowered for marker in INSTITUTION_SCOPE_EXPLANATORY_MARKERS)
    if (
        scope_applicable
        and not scope_explanatory
        and not filters.get("institution_names")
        and not filters.get("region_names")
    ):
        scope = extract_institution_scope(
            normalized_query,
            include_entity_org_tokens=list_intent,
            multiple=bool(list_intent or multi_result_list),
        )
        scope_name = str(scope.get("institution_name") or "")
        existing_name = _normalize_text(str(filters.get("institution_name") or ""))
        # 광역 사전 대체 경로는 "대전 유성구" 에서 먼저 "대전" 을 넣습니다. 추출기가
        # 더 좁은 범위를 돌려주면 그 값으로 바꿔야 채팅 경로와 같은 기관 조건이
        # 걸립니다. 사용자나 상위 계층이 명시한 값은 대체 경로 값이 아니므로
        # 그대로 둡니다.
        replace_region_fallback = bool(
            region_fallback_name
            and existing_name == region_fallback_name
            and scope_name != existing_name
            and _is_specific_institution_scope(scope_name)
        )
        if scope_name and (not existing_name or replace_region_fallback):
            filters["institution_name"] = scope_name
            existing_name = scope_name
        if scope.get("institution_aliases") and (not existing_name or existing_name == scope_name):
            filters["institution_aliases"] = list(scope["institution_aliases"])

    # 광역 단축명이 최종 기관 조건으로 남으면 정식 명칭 별칭을 함께 넘깁니다.
    # 목록·집계 표지가 없는 질의도 광역 사전 대체 경로에서 단축명을 얻으므로,
    # "경북 인입철도 공사 공고" 에서 별칭 없이 "경북" 만 남지 않게 합니다.
    if region_fallback_name and filters.get("institution_name") == region_fallback_name:
        fallback_aliases = REGION_ALIASES.get(region_fallback_name, ())
        if len(fallback_aliases) > 1 and not filters.get("institution_aliases"):
            filters["institution_aliases"] = list(fallback_aliases)

    # 비교 대상이 확정되면 목록 제한은 의미가 없습니다. "부산이랑 대구 공고 5건
    # 비교" 처럼 개수가 붙은 비교 질의가 공고 목록 응답으로 새는 것을 막습니다.
    # 공고번호 단건도 같은 이유로 목록 제한을 두지 않습니다.
    has_comparison = bool(comparison_regions or comparison_institutions or comparison_dimension)
    if (result_list_query or multi_result_list) and not has_comparison and not is_bid_number:
        filters["result_limit"] = extract_result_limit(normalized_query)

    if announcement_list_query and not has_comparison and not is_bid_number:
        filters["announcement_limit"] = extract_result_limit(normalized_query)

    if any(keyword in lowered for keyword in TREND_KEYWORDS):
        filters["analysis_mode"] = "trend"

    aggregate_filters = extract_aggregate_filters(normalized_query, filters)
    # 특정 업체명을 지목한 질의는 그 업체의 실적 조회이지 순위 집계가 아닙니다.
    # is_entity_specific_query 판정을 먼저 적용해 winner 축으로 새지 않게 합니다.
    if is_entity and aggregate_filters.get("group_by") == "winner":
        aggregate_filters = {}
    filters.update(aggregate_filters)
    if has_comparison and not filters.get("group_by"):
        filters["metric"] = _requested_metric(lowered)

    route_reason_parts = []
    if is_bid_number:
        route_reason_parts.append("공고번호 단건 질의")
    if is_entity:
        route_reason_parts.append("개체 지정 질의")
    if result_list_query:
        route_reason_parts.append("낙찰 결과 목록 질의")
    if announcement_list_query:
        route_reason_parts.append("공고 목록 질의")
    if has_stat_keywords:
        route_reason_parts.append("정형 통계 질의")
    if has_semantic_keywords:
        route_reason_parts.append("문맥/의미 질의")
    if use_kb_status:
        route_reason_parts.append("KB 상태 질의")

    route_reason = ", ".join(route_reason_parts)
    if not route_reason:
        route_reason = "기본 벡터 질의"

    quote_match = QUOTED_TITLE_PATTERN.search(normalized_query)
    has_quoted_title = bool(quote_match)
    use_lexical = is_entity or has_quoted_title
    lexical_query = (
        quote_match.group(1).strip() if quote_match else (normalized_query if is_entity else None)
    )

    plan = RetrievalPlan(
        use_sql=use_sql,
        use_vector=use_vector,
        use_kb_status=use_kb_status,
        use_lexical=use_lexical,
        lexical_query=lexical_query,
        filters=filters,
        semantic_query=normalized_query,
        top_k=DEFAULT_VECTOR_TOP_K,
        time_bias=time_bias,
        route_reason=route_reason,
    )

    if use_sql and not filters.get("date_from") and not filters.get("close_from"):
        plan.insufficiency_hints.append(
            "기간 조건이 명시되지 않아 전체 기준 통계를 사용할 수 있습니다."
        )
    if use_vector and not time_bias:
        plan.insufficiency_hints.append(
            "최신성 조건이 명확하지 않아 일반 문맥 검색으로 처리합니다."
        )
    return plan


WHOLE_PERIOD_HINT_MARKER = "전체 기준"


def apply_default_statistics_window(
    filters: dict[str, Any], *, time_bucket_aware: bool = True
) -> dict[str, Any]:
    """기간을 말하지 않은 통계 질의에 기본 창(최근 5년)을 채웁니다.

    명시 기간이 항상 이기고, 분기 버킷의 연도 미지정 기본값과 명시적 전체
    기간(`relative_years` 가 이미 있는 경우, 예: years=0)은 그대로 둡니다.
    원본 dict 는 바꾸지 않고 사본을 돌려줍니다.
    """
    windowed = dict(filters)
    if windowed.get("date_from") or windowed.get("date_to"):
        return windowed
    if "relative_years" in windowed:
        return windowed
    if time_bucket_aware and str(windowed.get("time_bucket") or "") == "quarter":
        return windowed
    windowed["relative_years"] = DEFAULT_STATISTICS_WINDOW_YEARS
    return windowed


def replace_whole_period_insufficiency_hint(hints: list[str], filters: dict[str, Any]) -> list[str]:
    """창이 걸린 계획의 '전체 기준' 안내를 실제 기간 안내로 바꿉니다.

    명시 기간은 원래 안내가 붙지 않고, `relative_years` 가 없거나 0 이면
    전체 기간 질의이므로 안내를 유지합니다.
    """
    if filters.get("date_from") or filters.get("date_to"):
        return list(hints)
    years = int(filters.get("relative_years") or 0)
    if not years:
        return list(hints)
    replacement = f"기간을 지정하지 않아 최근 {years}년 기준으로 집계했습니다."
    return [replacement if WHOLE_PERIOD_HINT_MARKER in str(hint) else hint for hint in hints]

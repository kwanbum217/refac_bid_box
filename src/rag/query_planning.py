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

# 기존 import 경로(src.rag.query_planning)를 유지하기 위해 이름을 그대로 재노출합니다.
from src.rag.query_lexicon import (  # noqa: F401
    ADMIN_DISTRICT_PATTERN,
    ADMIN_REGION_OFFICE_SUFFIX,
    ADMIN_REGION_PATTERN,
    AGGREGATE_ANNOUNCEMENT_MARKERS,
    AGGREGATE_AWARD_AMOUNT_MARKERS,
    AGGREGATE_AXIS_MARKERS,
    AGGREGATE_BID_MARKERS,
    AGGREGATE_RATE_MARKERS,
    AXIS_RANKING_MARKERS,
    BID_NTCE_NO_EXPLANATION_MARKERS,
    BID_NTCE_NO_PATTERN,
    CATEGORY_KEYWORDS,
    CONSTRUCTION_CATEGORY_PATTERN,
    COUNT_PATTERN,
    COUNT_PATTERN_FRAGMENT,
    COUNT_QUERY_DOMAIN_MARKERS,
    COUNT_QUERY_PATTERN,
    COUNT_UNIT_BOUNDARY_PATTERN,
    DEFAULT_GROUP_LIMIT,
    ENTITY_ORG_SUFFIXES,
    GROUP_FIRST_PATTERN,
    GROUP_RANK_COUNT_PATTERN,
    GROUP_SINGLE_TOP_MARKERS,
    GROUP_TOP_PATTERN,
    INSTITUTION_SCOPE_EXCLUDED_SUFFIXES,
    INSTITUTION_SCOPE_EXCLUDED_TERMS,
    INSTITUTION_SCOPE_EXPLANATORY_MARKERS,
    INSTITUTION_SCOPE_PARTICLES,
    INSTITUTION_SUBUNIT_SUFFIXES,
    KB_KEYWORDS,
    KOREAN_NUMERAL_FRAGMENT,
    KOREAN_NUMERALS,
    LIST_REQUEST_MARKERS,
    MAX_GROUP_LIMIT,
    OFFICIAL_BROAD_REGION_NAMES,
    OFFICIAL_DISTRICT_ENUM_CONNECTORS,
    OFFICIAL_DISTRICT_PATTERN,
    OFFICIAL_PROVINCE_NAMES,
    PUBLIC_CORP_JOSA,
    PUBLIC_CORPORATION_PREFIXES,
    PUBLIC_CORPORATION_STEMS,
    REGION_ALIASES,
    REGION_KEYWORDS,
    RESULT_LIST_BID_NUMBER_PATTERN,
    RESULT_LIST_EXCLUDED_MARKERS,
    RESULT_LIST_EXCLUDED_PATTERN,
    RESULT_LIST_EXPLANATION_MARKERS,
    RESULT_LIST_MARKERS,
    RESULT_LIST_REQUEST_VERB_PATTERN,
    RESULT_LIST_SPACED_PERIOD_REPLACEMENTS,
    RESULT_LIST_TOKEN_SPLIT_PATTERN,
    RESULT_LIST_TOKEN_SUFFIXES,
    RESULT_LIST_VOCABULARY_PATTERNS,
    RESULT_LIST_VOCABULARY_WORDS,
    RESULT_QUERY_MARKERS,
    SEMANTIC_KEYWORDS,
    STATISTICS_KEYWORDS,
    STATS_SINGLE_METRIC_EXCLUDED_MARKERS,
    STATS_SINGLE_METRIC_RATE_TERMS,
    TREND_KEYWORDS,
    TREND_LIST_MARKERS,
    TREND_TITLE_FOLLOWER_PATTERN,
    WINNER_AXIS_PATTERN,
)
from src.rag.schemas import (
    DEFAULT_STATISTICS_WINDOW_YEARS,
    DEFAULT_VECTOR_TOP_K,
    RetrievalPlan,
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


def _official_district_name(token: str) -> str:
    """정식 광역 명칭 뒤에 오는 시·군·구 어절을 지명으로 정규화합니다."""
    if token in OFFICIAL_BROAD_REGION_NAMES:
        return ""
    value = _strip_institution_particle(token)
    if value.endswith(ADMIN_REGION_OFFICE_SUFFIX) and len(value) > 2:
        value = value[: -len(ADMIN_REGION_OFFICE_SUFFIX)]
    if not value or value in INSTITUTION_SCOPE_EXCLUDED_TERMS:
        return ""
    if value.endswith(INSTITUTION_SCOPE_EXCLUDED_SUFFIXES):
        return ""
    if not OFFICIAL_DISTRICT_PATTERN.fullmatch(value):
        return ""
    return value


def _strip_official_district_connector(token: str) -> str:
    """어절 끝에 붙은 나열·비교 연결어를 떼어 냅니다."""
    for connector in OFFICIAL_DISTRICT_ENUM_CONNECTORS:
        if len(token) > len(connector) and token.endswith(connector):
            return token[: -len(connector)]
    return token


def _official_district_enum_name(token: str) -> str:
    """나열·비교 연결어를 떼어 낸 어절의 시·군·구 지명을 돌려줍니다."""
    return _official_district_name(_strip_official_district_connector(token))


def _official_region_name(token: str) -> str:
    """어절이 가리키는 광역 명칭이나 시·군·구 지명을 돌려줍니다."""
    value = _strip_official_district_connector(token)
    for name in (value, _strip_institution_particle(value)):
        if name in OFFICIAL_BROAD_REGION_NAMES:
            return name
    return _official_district_name(value)


def _official_province_district_enumerated(pairs: list[tuple[str, str]]) -> bool:
    """시·군·구가 둘 이상 나열·비교됐는지 판정합니다.

    지명이 둘 이상이면 첫 구역만 남기면 나머지 구역이 유실됩니다. 지명 하나가
    연결어나 쉼표로 다른 행정 구역과 이어지는 경우("중구와 부산광역시")도
    비교·나열로 봅니다. 기간 비교("중구 작년 대비 올해")는 연결어가 지명 바로
    뒤에 오지 않으므로 해당하지 않습니다.
    """
    if len({_official_district_enum_name(token) for token, _ in pairs} - {""}) >= 2:
        return True
    for index, (token, _separator) in enumerate(pairs):
        if not _official_district_enum_name(token) or index + 1 >= len(pairs):
            continue
        following, separator = pairs[index + 1]
        attached = _strip_official_district_connector(token) != token
        separated = any(marker in separator for marker in INSTITUTION_ENUM_SEPARATORS)
        if (attached or separated) and _official_region_name(following):
            return True
        if (
            following in OFFICIAL_DISTRICT_ENUM_CONNECTORS
            and index + 2 < len(pairs)
            and _official_region_name(pairs[index + 2][0])
        ):
            return True
    return False


def _official_province_district_scope(query: str) -> str:
    """정식 광역 명칭 바로 뒤 시·군·구를 '<광역> <시·군·구>' 범위로 돌려줍니다.

    "서울특별시 중구", "부산광역시 해운대구", "경기도 수원시" 처럼 정식 광역
    명칭과 시·군·구가 이어지면 광역 전체가 아니라 그 구역 기관 범위입니다.
    띄어 쓴 형태와 붙여 쓴 형태를 모두 받고, 정식 명칭만 있는 질의는 빈
    문자열을 돌려 기존 광역 동작을 유지합니다. 시·군·구가 둘 이상 나열·비교된
    질의도 첫 구역만 남기지 않도록 빈 문자열을 돌려 기존 지역 경로를 씁니다.
    """
    tokens = [
        token for token in RESULT_LIST_TOKEN_SPLIT_PATTERN.split(_normalize_text(query)) if token
    ]
    if _official_province_district_enumerated(_institution_enumeration_token_pairs(query)):
        return ""
    for index, token in enumerate(tokens):
        province = token
        if province not in OFFICIAL_BROAD_REGION_NAMES:
            province = _strip_institution_particle(token)
        if province not in OFFICIAL_BROAD_REGION_NAMES:
            continue
        if index + 1 < len(tokens):
            district = _official_district_name(tokens[index + 1])
            if district:
                return f"{province} {district}"
    for token in tokens:
        for province in sorted(OFFICIAL_BROAD_REGION_NAMES, key=len, reverse=True):
            if token == province or not token.startswith(province):
                continue
            district = _official_district_name(token[len(province) :])
            if district:
                return f"{province} {district}"
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
    official_district = _official_province_district_scope(normalized)
    if official_district:
        return {"institution_name": official_district}
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
    if _official_province_district_scope(normalized):
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
NON_INSTITUTION_SUFFIXES = (
    "금액",
    "가격",
    "낙찰률",
    "투찰률",
    "사정률",
    "경쟁률",
    "낙찰제",
    "심사",
    "계약방식",
    "입찰방식",
)

COMPARISON_MARKERS = ("비교", "대비", "차이", "vs")
# 비교 질의라도 입찰 지표를 묻지 않으면 지역·기관 비교가 아닙니다.
# "부산이랑 대구 여행 코스 비교" 같은 질의를 통계 비교로 오인하지 않습니다.
COMPARISON_DOMAIN_MARKERS = ("공고", "낙찰", "입찰", "개찰", "유찰")
COMPARISON_TARGET_CONNECTOR_PATTERN = re.compile(r"\s*(?:이랑|랑|하고|와|과|및|,)\s*")
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


# 기간 비교의 기관 후보에서 걸러 낼 지표·도메인·비교 표지와 요청 표현입니다.
# 후보를 "공사"·"공단" 접미사로만 남기면 기금·진흥원·연구원처럼 접미사가 다른
# 실제 기관이 빠져 전체 기관 값으로 조용히 넓어집니다. 그래서 후보는 접미사와
# 무관하게 남기고, 이 목록에 드는 낱말만 지웁니다.
COMPARISON_INSTITUTION_UNRESOLVED_EXCLUDED_TERMS = frozenset(
    {
        *COMPARISON_DOMAIN_MARKERS,
        *COMPARISON_MARKERS,
        "건수",
        "결과",
        "통계",
        "순위",
        "평균",
        "낙찰률",
        "투찰률",
        "비율",
        "분포",
        "추이",
        "기간",
        "분기",
        "연도",
        "년도",
        "월별",
        "주별",
        "일별",
        "알려줘",
        "보여줘",
        "뽑아줘",
        "말해줘",
        "찾아줘",
    }
)
# 비교 대상 연결어는 조사와 달리 기관 후보에서 떼어 내야 합니다. "공사랑 용역"
# 처럼 분야어에 붙은 연결어를 남기면 "공사랑" 이 기관 후보가 됩니다.
COMPARISON_INSTITUTION_UNRESOLVED_CONNECTORS = ("이랑", "랑", "하고")


def _strip_comparison_connector(token: str) -> str:
    for connector in COMPARISON_INSTITUTION_UNRESOLVED_CONNECTORS:
        if token.endswith(connector) and len(token) > len(connector):
            return token[: -len(connector)]
    return token


# 관형형 어미로 끝나는 활용형은 명사를 수식하는 서술어이지 기관 이름이 아닙니다.
# "최근 7일 동안 올라온 공고" 의 "올라온" 을 기관 후보로 남기면 카탈로그 해석에
# 실패해 미해석 안내로 빠집니다. 서술격 조사 "인"(마감인·진행중인)도 같은 이유로
# 뺍니다.
INSTITUTION_CANDIDATE_PREDICATE_ENDINGS = frozenset(
    {"된", "한", "온", "난", "은", "는", "던", "할", "될", "인"}
)
# 부사·수량어는 기관 이름이 아닙니다. 짧은 낱말은 후보 길이 검사에서 먼저
# 걸리지만, "전체"·"모두" 처럼 길이 검사를 넘는 값도 있어 상수 목록으로 함께
# 뺍니다.
INSTITUTION_CANDIDATE_ADVERB_TERMS = frozenset(
    {"총", "전체", "모두", "다", "전부", "대략", "약", "혹시", "좀"}
)
# 실제 기관명은 ㄴ·ㄹ 받침으로 끝나기도 합니다. 기관 지정 접미사로 끝나는 이름은
# 어미 규칙에서 제외해 후보를 잃지 않게 합니다.
INSTITUTION_CANDIDATE_NAME_ENDINGS = ("원", "단")
HANGUL_WORD_PATTERN = re.compile(r"^[가-힣]{2,}$")
KOREAN_FINAL_CONSONANT_N = 4
KOREAN_FINAL_CONSONANT_L = 8


def _korean_final_consonant(syllable: str) -> int:
    """한글 음절의 종성 인덱스를 돌려줍니다. 한글이 아니면 0 입니다."""
    if not syllable:
        return 0
    code = ord(syllable) - 0xAC00
    if 0 <= code < 11172:
        return code % 28
    return 0


def _is_institution_candidate_modifier(token: str) -> bool:
    """관형형·부사·수량어라서 기관 이름이 될 수 없는 어절인지 판정합니다.

    "올라온", "등록된", "마감인", "새로운" 처럼 명사를 수식하는 활용형은 기관명이
    아닙니다. 받침 ㄴ·ㄹ 로 끝나는 어절 가운데 앞 음절이 모음으로 끝나면 관형형
    어미가 붙은 형태로 봅니다. 다만 "진흥원"·"공단" 처럼 기관 지정 접미사로
    끝나는 이름은 실제 기관일 수 있으므로 남깁니다.
    """
    if token in INSTITUTION_CANDIDATE_ADVERB_TERMS:
        return True
    if not HANGUL_WORD_PATTERN.fullmatch(token):
        return False
    if token.endswith(INSTITUTION_CANDIDATE_NAME_ENDINGS):
        return False
    if token[-1] in INSTITUTION_CANDIDATE_PREDICATE_ENDINGS:
        return True
    if _korean_final_consonant(token[-1]) not in (
        KOREAN_FINAL_CONSONANT_N,
        KOREAN_FINAL_CONSONANT_L,
    ):
        return False
    return _korean_final_consonant(token[-2]) == 0


def _comparison_institution_candidate_excluded(token: str) -> bool:
    """기관 후보로 쓸 수 없는 낱말인지 확인합니다.

    연결어를 뗀 형태까지 함께 보므로 "공사랑" 이 분야어 "공사" 로 걸러집니다.
    """
    for value in (token, _strip_comparison_connector(token)):
        if value in COMPARISON_CATEGORY_TOKENS:
            return True
        if value in COMPARISON_INSTITUTION_UNRESOLVED_EXCLUDED_TERMS:
            return True
        if value in REGION_ALIASES or _match_comparison_region(value):
            return True
        if value in INSTITUTION_SCOPE_EXCLUDED_TERMS or value.endswith(
            INSTITUTION_SCOPE_EXCLUDED_SUFFIXES
        ):
            return True
        if value in NON_INSTITUTION_TERMS or value.endswith(NON_INSTITUTION_SUFFIXES):
            return True
    return False


def _comparison_unresolved_institution_candidate(query: str) -> str:
    """기간 비교에서 해석되지 않은 기관 후보 낱말을 찾습니다.

    기관 후보를 공사·공단 접미사로만 남기면 기금·진흥원·연구원처럼 접미사가 다른
    실제 기관이 후보에서 빠지고, 공통 범위가 비어 전체 기관 값으로 조용히
    넓어집니다. 기간 표현·분야어·지표어·도메인 표지·비교 표지·지역명을 지운 뒤
    남는 명사구를 접미사와 무관하게 돌려 카탈로그 해석에 맡깁니다. 해석에
    실패하면 응답 단계가 전체 값 대신 미해석 안내를 냅니다.
    """
    lowered = _query_lower(query)
    stop = COMPARISON_METRIC_STOP_PATTERN.search(lowered)
    prefix = lowered[: stop.start()] if stop else lowered
    remaining = COMPARISON_PERIOD_PATTERN.sub(" ", prefix)
    for token in RESULT_LIST_TOKEN_SPLIT_PATTERN.split(remaining):
        cleaned = _strip_institution_particle(token)
        if _is_institution_candidate_modifier(cleaned):
            continue
        if len(cleaned) <= 2:
            continue
        if COMPARISON_PERIOD_TOKEN_PATTERN.fullmatch(cleaned):
            continue
        if _comparison_institution_candidate_excluded(cleaned):
            continue
        return cleaned
    return ""


def _stats_institution_candidate_is_domain_phrase(name: str) -> bool:
    """기관 접미사와 같은 글자로 끝나지만 분야어·사업명인 낱말인지 확인합니다.

    "도로공사", "건설공사", "인입철도공사" 는 공사 종류·사업명이지 기관 이름이
    아닙니다. 공기업 이름으로 확인되는 낱말은 분야어로 보지 않습니다.
    """
    if _extract_public_corporation_tokens(name):
        return False
    return bool(extract_category(name)[1])


STATS_SINGLE_METRIC_PERIOD_NOISE = re.compile(r"^(?:최근|현재|\d+\s*(?:년|개월|달|일|주))$")


def _stats_single_metric_institution_candidate(query: str) -> str:
    """단일 지표 질의에서 기관 이름 하나로 볼 수 있는 후보만 돌려줍니다.

    기간 비교 후보 추출은 접미사와 무관하게 첫 명사구를 돌려주므로, 사업명이
    길게 이어지는 질의("부산항 신항 ... 인입철도 건설공사")에서는 사업명 일부를
    기관으로 오인합니다. 단일 지표 질의에서는 기관 이름이 지표 앞의 마지막
    명사구여야 하므로 그 조건을 만족할 때만 후보를 남깁니다.
    """
    candidate = _comparison_unresolved_institution_candidate(query)
    if not candidate:
        return ""
    lowered = _query_lower(query)
    stop = COMPARISON_METRIC_STOP_PATTERN.search(lowered)
    prefix = lowered[: stop.start()] if stop else lowered
    remaining = COMPARISON_PERIOD_PATTERN.sub(" ", prefix)
    tokens = [
        token
        for token in RESULT_LIST_TOKEN_SPLIT_PATTERN.split(remaining)
        if token
        and not COMPARISON_PERIOD_TOKEN_PATTERN.fullmatch(token)
        and not STATS_SINGLE_METRIC_PERIOD_NOISE.fullmatch(token)
    ]
    if not tokens:
        return ""
    if tokens[-1] in INSTITUTION_SCOPE_EXCLUDED_TERMS:
        return ""
    stripped = _strip_institution_particle(tokens[-1])
    if stripped == tokens[-1] and any(
        tokens[-1].endswith(particle) and len(tokens[-1]) > len(particle)
        for particle in INSTITUTION_SCOPE_PARTICLES
    ):
        # "공사 쪽에서" 의 "쪽에서" 처럼 조사만 붙은 지시어는 기관 이름이
        # 아닙니다. _strip_institution_particle 은 기저가 한 글자면 떼지
        # 않으므로 여기서 따로 걸러 냅니다.
        return ""
    return candidate if stripped == candidate else ""


def _normalize_enumerated_regions(names: list[str]) -> list[str]:
    """나열된 이름이 모두 광역 지역이면 대표 지역명을 질의 순서대로 돌려줍니다.

    "부산 및 대구", "서울시와 경기도" 처럼 비교 표지 없이 지역명만 나열한
    질의를 기관명 등호 조건이 아니라 지역 합집합 조건으로 다루기 위한 정규화
    입니다. 지역이 아닌 이름이 하나라도 섞이면 빈 목록을 돌려 기존 기관 경로를
    그대로 쓰게 합니다.
    """
    regions: list[str] = []
    for name in names:
        region = _match_comparison_region(name)
        if not region:
            return []
        if region not in regions:
            regions.append(region)
    return regions if len(regions) >= 2 else []


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
    차수 접미사가 붙어 있어도 공고번호 부분만 돌려줍니다(호출부 호환).
    """
    match = BID_NTCE_NO_PATTERN.search(_normalize_text(query))
    return match.group("bid_ntce_no").upper() if match else ""


def extract_bid_ntce_ord(query: str) -> str:
    """질의의 공고번호에 붙은 차수를 세 자리로 돌려줍니다.

    "R26BK01788962-001" 이면 "001" 입니다. 접미사가 없거나 세 자리가 아니면
    빈 문자열이며, 그때는 기존처럼 공고번호만으로 단건 조회합니다.
    """
    match = BID_NTCE_NO_PATTERN.search(_normalize_text(query))
    return (match.group("bid_ntce_ord") or "") if match else ""


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
# '나온'·'들어온' 은 "공고가 나온 배경", "들어온 공고 요점" 처럼 사건이나 문맥을
# 가리키는 설명형 질의에도 등장합니다. 낱말 하나만으로 목록 판정을 켜면 설명형을
# 막을 명사 목록을 계속 늘려야 하므로, 이 두 표지는 "나온·들어온 + 분야어 + 공고
# + 개수 + 목록 요청" 구조가 바로 이어질 때만 공고 목록 신선도 표지로 인정합니다.
ANNOUNCEMENT_ADDED_FRESHNESS_LIST_PATTERN = re.compile(
    r"(?<![가-힣])(?:나온|들어온)\s*"
    r"(?:공사|용역|물품|외자|건설)?\s*"
    r"(?:입찰\s*)?공고(?:를|을)?\s*"
    r"(?:\d+\s*(?:건|개)\s*(?:만)?\s*)?"
    r"(?:좀\s*)?"
    r"(?:보여|찾아|알려|뽑아|리스트|목록)"
)
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
# 기관·지역 범위와 요청 동사가 함께 있는 공고 질의는 개수·목록·신선도 표지가
# 없어도 목록 요청입니다. 다만 설명형(절차·방법·기준·이유 등)과 통계형
# (몇 건·건수·평균·비율) 표지가 있으면 목록이 아닙니다.
ANNOUNCEMENT_SCOPED_LIST_EXPLANATION_MARKERS = (
    *ANNOUNCEMENT_EXPLANATION_MARKERS,
    "이유",
    "뜻",
    "기준",
    "왜",
)
ANNOUNCEMENT_SCOPED_LIST_STATISTICS_PATTERN = re.compile(r"몇\s*(?:건|개)|건수|평균|비율")
# 부정·대조 표현이 있는 질의는 특정 범위의 목록 요청이 아니라 앞선 대상을
# 배제하라는 교정 요청입니다. 기관 이름이 섞여 있어도 목록으로 바꾸지 않습니다.
ANNOUNCEMENT_SCOPED_LIST_NEGATION_MARKERS = (
    "안 돼",
    "안돼",
    "말고",
    "아니라",
    "대신",
    "하지 마",
    "하지마",
)
# 연도·월·일을 직접 지목한 질의는 기간이 한정된 지목형 조회입니다. 기존 요청
# 동사 단독 경로가 신선도 표지를 요구하는 이유와 같으므로 이 분기에서도 목록으로
# 바꾸지 않습니다.
ANNOUNCEMENT_SCOPED_LIST_EXPLICIT_PERIOD_PATTERN = re.compile(
    r"\d{4}\s*년|\d{1,2}\s*월|\d{1,2}\s*일|\d{1,2}\s*분기"
)
# 기관 접미사 사전에 없는 중앙행정기관 이름(조달청 등)은 분야어 바로 앞 낱말을
# 후보로 남겨 응답 단계의 기관 카탈로그 정확 일치에 맡깁니다. 일반 수식어가
# 기관 조건으로 승격되지 않도록 기관 표지 접미사가 있는 낱말만 인정합니다.
SCOPED_LIST_INSTITUTION_SUFFIXES = (
    "위원회",
    "연구원",
    "진흥원",
    "공단",
    "공사",
    "재단",
    "협회",
    "조합",
    "은행",
    "본부",
    "센터",
    "청",
    "부",
    "처",
)


def _scoped_list_institution_candidate(query: str) -> str:
    """범위 추출기가 놓친 중앙행정기관 후보를 분야어 앞에서 찾습니다.

    "조달청 용역 공고" 처럼 접미사 사전에 없는 기관 이름을 버리면 기관 조건이
    사라진 전체 목록으로 조용히 넓어집니다. 분야어 바로 앞 낱말이 기관 표지
    접미사로 끝날 때만 후보로 남기고, 실제 이름 일치는 응답 단계의 기관
    카탈로그에 맡깁니다.
    """
    normalized = _normalize_text(query)
    masked = _mask_non_category_construction(_mask_category_scope_tokens(normalized))
    category_position = -1
    for keyword in CATEGORY_KEYWORDS:
        position = masked.rfind(keyword)
        if position > category_position:
            category_position = position
    if category_position <= 0:
        return ""
    tokens = [
        token
        for token in RESULT_LIST_TOKEN_SPLIT_PATTERN.split(normalized[:category_position])
        if token
    ]
    if not tokens:
        return ""
    candidate = _strip_institution_particle(tokens[-1])
    if len(candidate) < 3 or candidate in INSTITUTION_SCOPE_EXCLUDED_TERMS:
        return ""
    if (
        candidate in COMPARISON_INSTITUTION_UNRESOLVED_EXCLUDED_TERMS
        or candidate in REGION_ALIASES
        or _match_comparison_region(candidate)
    ):
        return ""
    if not any(
        candidate.endswith(suffix) and len(candidate) > len(suffix) + 1
        for suffix in SCOPED_LIST_INSTITUTION_SUFFIXES
    ):
        return ""
    return candidate


def _is_scoped_announcement_list_request(query: str) -> bool:
    """기관·지역 범위와 요청 동사만 있는 공고 목록 질의인지 판정합니다.

    개수·목록·신선도 표지가 없어도 대상이 기관·지역으로 한정되고 공고 뒤에
    요청 동사가 있으면 목록입니다. 설명형·통계형 표지가 있으면 목록이 아니며,
    신선도 표지가 있는 질의는 기존 신선도 분기가 그대로 맡습니다. 마감 창을
    확정하지 못하는 마감 표지(마감 기한·마감일 등)도 목록 범위 표지가 아닙니다.
    창 없이 승격하면 범위 질의가 마감 조건 없는 전체 최신 목록으로 넓어집니다.
    """
    normalized = _normalize_text(query)
    lowered = normalized.lower()
    if any(marker in lowered for marker in ANNOUNCEMENT_FRESHNESS_MARKERS):
        return False
    if CLOSE_MARKER_PATTERN.search(lowered) and _parse_close_window(query) is None:
        return False
    if _has_excluded_list_marker(lowered):
        return False
    if ANNOUNCEMENT_SCOPED_LIST_STATISTICS_PATTERN.search(lowered):
        return False
    if any(marker in lowered for marker in ANNOUNCEMENT_SCOPED_LIST_NEGATION_MARKERS):
        return False
    if ANNOUNCEMENT_SCOPED_LIST_EXPLICIT_PERIOD_PATTERN.search(lowered):
        return False
    if any(marker in lowered for marker in ANNOUNCEMENT_SCOPED_LIST_EXPLANATION_MARKERS):
        return False
    if any(marker in lowered for marker in ANNOUNCEMENT_RESULT_STATUS_MARKERS):
        return False
    if not ANNOUNCEMENT_LIST_PATTERN.search(lowered):
        return False
    if extract_institution_scope(normalized, include_entity_org_tokens=True).get(
        "institution_name"
    ):
        return True
    return bool(_scoped_list_institution_candidate(normalized))


def _has_announcement_list_scope(lowered: str) -> bool:
    """요청 동사만 있는 공고 목록 질의에 목록 범위를 정하는 표지가 있는지 봅니다.

    분류나 연도만 있는 "서울의 2026년 ... 용역 공고를 알려줘" 는 지목형 조회이지
    최신 목록 요청이 아니고, "최근"·"요즘" 같은 막연한 표현도 범위를 정하지
    못합니다. 그래서 동사 단독 경로는 올라온·등록된·게시된·신규·최신 표지를
    요구하고, 나머지는 기존 최신성 힌트 경로에 남깁니다. '나온'·'들어온' 은
    표지 낱말이 아니라 "나온·들어온 + 분야어 + 공고 + 개수 + 목록 요청" 구조가
    바로 이어질 때만 같은 범위 표지로 봅니다.
    """
    if any(marker in lowered for marker in ANNOUNCEMENT_FRESHNESS_MARKERS):
        return True
    return bool(ANNOUNCEMENT_ADDED_FRESHNESS_LIST_PATTERN.search(lowered))


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
    전체 최신 목록으로 새지 않게 합니다. '나온'·'들어온' 은 표지 낱말이 아니라
    "나온·들어온 + 분야어 + 공고 + 개수 + 목록 요청" 구조가 바로 이어질 때만
    범위 표지로 인정하므로, "공고가 나온 배경" 같은 설명형 질의는 남깁니다.
    마감일 창·금액 조건·정렬 표지가 파싱됐고 요청 동사가 함께 있으면 그 조건을
    목록의 범위 표지로 인정해 참을 반환합니다. 조건이 없는 "공고 보여줘" 의
    판정은 그대로입니다.
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
    if _is_scoped_announcement_list_request(query):
        return True
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
CLOSE_THIS_WEEK_DAYS = 7
# 이번 달·지난달 마감 표지와 함께 쓰인 지난 마감 표지입니다. "이번 달 마감되는"
# 처럼 앞으로의 마감을 가리키는 표현과 "이번 달 마감된" 을 가릅니다.
CLOSE_PAST_MARKER_PATTERN = re.compile(r"지난|지났|마감된|마감한")
# 기간을 말하지 않은 공고 건수와 금액 정렬 공고 목록의 기본 창입니다. 오늘을
# 포함해 30일이므로 시작일은 오늘 - 29일입니다.
RECENT_ANNOUNCEMENT_WINDOW_DAYS = 30
# 금액 정렬 기본 창을 적용할 공고 금액 축입니다. 낙찰금액 정렬은 낙찰 결과
# 테이블의 기존 5년 기본 창을 그대로 씁니다.
ANNOUNCEMENT_AMOUNT_SORT_FIELDS = ("presmpt_prce", "base_amount")
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
# 공고 금액 최댓값·최솟값 질문은 정렬 목록이 아니라 값 하나를 묻는 질의입니다.
# 금액 축을 낱말로 지목한 질의에서만 이 표지를 인정해, "가장 큰 기관" 같은
# 금액 축 없는 순위 질의를 SQL 단건 경로로 끌어오지 않습니다.
ANNOUNCEMENT_AMOUNT_EXTREME_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"가장\s*큰|가장\s*비싼|가장\s*높은"), "max"),
    (re.compile(r"가장\s*작은|가장\s*싼|가장\s*낮은"), "min"),
    (re.compile(r"최댓값|최대값"), "max"),
    (re.compile(r"최솟값|최소값"), "min"),
    (re.compile(r"최대|최고"), "max"),
    (re.compile(r"최소|최저"), "min"),
)
ANNOUNCEMENT_EXTREME_AMOUNT_FIELDS: tuple[tuple[str, str], ...] = (
    ("기초금액", "base_amount"),
    ("추정가격", "presmpt_prce"),
    ("추정금액", "presmpt_prce"),
    ("금액", "presmpt_prce"),
)
BARE_EXTREME_MARKERS = ("최대", "최소", "최고", "최저")
EXTREME_LIST_LIMIT_PATTERN = re.compile(r"\d+\s*(?:개|건)")


def _compact_text(value: str) -> str:
    return re.sub(r"\s+", "", value)


def _parse_close_window(query: str) -> tuple[str, str] | None:
    """마감 표지와 상대 기간 표현으로 마감일 창을 계산합니다.

    마감 표지가 있어도 함께 쓰인 상대 기간 표현이 아래 일곱 가지일 때만 창을
    확정합니다. 확정하지 못하면 기존 기간 해석(공고일 창)을 그대로 둡니다.

    | 표현 | 마감일 창 |
    | --- | --- |
    | `마감 임박` | 오늘 ~ 오늘+3일 |
    | `오늘 마감` | 오늘 |
    | `내일 마감` | 내일 |
    | `이번 주 마감` | 오늘 ~ 오늘+6일 |
    | `이번 달 마감일이 지난` | 이번 달 1일 ~ 어제 |
    | `이번 달 마감된` | 이번 달 1일 ~ 어제 |
    | `이번 달에 마감한` | 이번 달 1일 ~ 어제 |
    | `지난달 마감` | 지난달 1일 ~ 지난달 말일 |

    `이번 주` 는 달력 주(월~일)가 아니라 오늘부터 7일 창입니다. 일요일에
    "이번 주 마감" 을 물으면 달력 주는 이미 지난 마감만 남으므로, 앞으로의
    마감을 답하려면 오늘부터 세어야 합니다.

    `마감 임박순`, `마감 빠른 순`, `마감일 순` 처럼 정렬 표지가 붙은 마감
    표현은 창을 만들지 않습니다. 그 표현은 정렬 요청이므로 창으로 읽으면
    정렬 대상이 오늘 이후 사흘로 잘립니다.
    """
    lowered = _query_lower(query)
    scope = CLOSE_SORT_PATTERN.sub(" ", lowered)
    if not CLOSE_MARKER_PATTERN.search(scope):
        return None
    today = date.today()
    if "지난달" in scope or "지난 달" in scope:
        last_prev_month = today.replace(day=1) - timedelta(days=1)
        return last_prev_month.replace(day=1).isoformat(), last_prev_month.isoformat()
    if (
        "이번 달" in scope or "이번달" in scope or "이번 월" in scope
    ) and CLOSE_PAST_MARKER_PATTERN.search(scope):
        return today.replace(day=1).isoformat(), (today - timedelta(days=1)).isoformat()
    if CLOSE_IMMINENT_PATTERN.search(scope):
        return today.isoformat(), (today + timedelta(days=CLOSE_WINDOW_DAYS)).isoformat()
    if "오늘" in scope:
        return today.isoformat(), today.isoformat()
    if "내일" in scope:
        tomorrow = today + timedelta(days=1)
        return tomorrow.isoformat(), tomorrow.isoformat()
    if "이번 주" in scope or "이번주" in scope:
        return today.isoformat(), (today + timedelta(days=CLOSE_THIS_WEEK_DAYS - 1)).isoformat()
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


def extract_amount_extreme(query: str) -> dict[str, Any]:
    """공고 금액 최댓값·최솟값 질문을 단건 정렬 조회 조건으로 바꿉니다.

    금액 축을 낱말로 지목하고 공고를 묻는 질의에서만 최댓값·최솟값 표지를
    인정합니다. "가장 큰 기관" 처럼 금액 축이 없는 순위 질의와 "최대 5개" 처럼
    개수를 가리키는 표지는 제외합니다. 기간을 말하지 않은 질의의 30일 기본 창은
    order_by 를 보는 기존 apply_default_statistics_window 가 채웁니다.
    """
    lowered = _query_lower(query)
    if "공고" not in lowered:
        return {}
    if any(marker in lowered for marker in LIST_REQUEST_MARKERS):
        return {}
    if EXTREME_LIST_LIMIT_PATTERN.search(lowered):
        return {}

    compact = _compact_text(lowered)
    amount_field = ""
    for marker, field in ANNOUNCEMENT_EXTREME_AMOUNT_FIELDS:
        if marker in compact:
            amount_field = field
            break
    if not amount_field:
        return {}

    direction = ""
    for pattern, candidate in ANNOUNCEMENT_AMOUNT_EXTREME_PATTERNS:
        match = pattern.search(lowered)
        if match is None:
            continue
        if match.group(0) in BARE_EXTREME_MARKERS and re.match(
            r"(?:최대|최소|최고|최저)\s*\d", lowered[match.start() :]
        ):
            continue
        direction = candidate
        break
    if not direction:
        return {}

    return {
        "amount_extreme": direction,
        "order_by": amount_field,
        "order_dir": "desc" if direction == "max" else "asc",
        "amount_field": amount_field,
        "announcement_limit": 1,
    }


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

    if "이번 주" in lowered or "이번주" in lowered:
        start, end = _to_iso(today - timedelta(days=6), today)
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
    elif any(marker in lowered for marker in AGGREGATE_AWARD_AMOUNT_MARKERS):
        metric = "award_amount"
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

    if group_by == "winner" and metric not in ("avg_rate", "award_amount"):
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

    extract_aggregate_filters 의 지표 결정 규칙(낙찰률 > 낙찰 금액 > 낙찰 >
    공고)을 따르되, 도메인 표지가 전혀 없으면 지표를 정하지 않고 빈 문자열을
    돌려줍니다.
    """
    if any(marker in lowered for marker in AGGREGATE_RATE_MARKERS):
        return "avg_rate"
    if any(marker in lowered for marker in AGGREGATE_AWARD_AMOUNT_MARKERS):
        return "award_amount"
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
    return _single_metric(_query_lower(query)) in ("bid_count", "avg_rate", "award_amount")


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
    bid_ntce_ord = extract_bid_ntce_ord(normalized_query) if is_bid_number else ""

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
    enumerated_regions = _normalize_enumerated_regions(enumerated_names)
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
    # 넘깁니다. 값이 비어 있으면 키를 만들지 않습니다. 차수 접미사가 있으면
    # 같은 공고의 그 회차만 읽도록 차수를 함께 넘깁니다.
    if bid_ntce_no:
        filters["bid_ntce_no"] = bid_ntce_no
    if bid_ntce_ord:
        filters["bid_ntce_ord"] = bid_ntce_ord
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
    elif enumerated_regions and any(marker in lowered for marker in COMPARISON_DOMAIN_MARKERS):
        # 비교 표지 없이 광역 지역명만 나열한 목록·건수·통계 질의는 기관명 등호
        # 조건이 아니라 나열 지역 전체의 합집합 지역 조건으로 다룹니다. 지역이
        # 아닌 이름이 섞이면 위 정규화가 빈 목록을 돌려 기존 기관 경로를 씁니다.
        filters["region_scope_names"] = enumerated_regions
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
    # 정식 광역 명칭 뒤 시·군·구는 목록·집계 표지가 없어도 그 구역 기관 범위입니다.
    # 공고·사업명을 지목한 개체 질의는 이름 속 행정 구역이 범위 지목이 아니므로
    # 기존 기관 동작을 그대로 둡니다.
    official_district_scope = (
        "" if is_entity else _official_province_district_scope(normalized_query)
    )
    scope_applicable = bool(
        list_intent or has_stat_keywords or multi_result_list or official_district_scope
    )
    scope_explanatory = any(marker in lowered for marker in INSTITUTION_SCOPE_EXPLANATORY_MARKERS)
    # 공고·낙찰 도메인 표지가 있는 통계 질의는 기관 하나를 지목한 경우가 많습니다.
    # "서울대학교병원 올해 공고 건수" 의 병원처럼 개체 접미사를 기관 조건으로
    # 승격해야 이름 속 지역명(서울)으로 범위가 조용히 넓어지지 않습니다.
    stats_domain_scope = bool(
        has_stat_keywords
        and not list_intent
        and not filters.get("winner_name")
        and not any(marker in lowered for marker in STATS_SINGLE_METRIC_EXCLUDED_MARKERS)
        and not RESULT_ATTRIBUTE_PATTERN.search(lowered)
        and "공고번호" not in lowered
        and sum(1 for term in STATS_SINGLE_METRIC_RATE_TERMS if term in lowered) <= 1
        and any(marker in lowered for marker in COUNT_QUERY_DOMAIN_MARKERS)
    )
    if (
        scope_applicable
        and not scope_explanatory
        and not filters.get("institution_names")
        and not filters.get("region_names")
        and not filters.get("region_scope_names")
    ):
        scope = extract_institution_scope(
            normalized_query,
            include_entity_org_tokens=bool(list_intent or stats_domain_scope),
            multiple=bool(list_intent or multi_result_list),
        )
        scope_name = str(scope.get("institution_name") or "")
        if (
            stats_domain_scope
            and scope_name
            and _stats_institution_candidate_is_domain_phrase(scope_name)
        ):
            scope_name = ""
            scope = {}
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
        if (
            not scope_name
            and stats_domain_scope
            and (not existing_name or existing_name == region_fallback_name)
        ):
            # 접미사 목록에 없는 기금·진흥원·연구원 이름도 후보로 남겨 카탈로그
            # 해석에 맡깁니다. 해석에 실패하면 응답 단계가 전체 값 대신 미해석
            # 안내를 냅니다. 이름 일부에 지역명이 있어도 후보가 이깁니다.
            candidate = _stats_single_metric_institution_candidate(normalized_query)
            if candidate and not _stats_institution_candidate_is_domain_phrase(candidate):
                scope_name = candidate
                replace_region_fallback = True
        if (
            not scope_name
            and announcement_list_query
            and _is_scoped_announcement_list_request(normalized_query)
        ):
            # 조달청처럼 접미사 사전에 없는 기관 이름은 분야어 앞 후보를 남겨
            # 카탈로그 정확 일치에 맡깁니다. 후보를 버리면 기관 조건이 사라진
            # 전체 공고 목록으로 조용히 넓어집니다.
            candidate = _scoped_list_institution_candidate(normalized_query)
            if candidate:
                scope_name = candidate
                replace_region_fallback = True
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

    # 금액 최댓값·최솟값 질문은 목록이 아니라 값 하나를 묻습니다. 정렬 조건만
    # 싣고 벡터 경로로 보내면 LLM 이 검색 문맥의 다른 금액을 답할 수 있으므로,
    # SQL 단건 조회로 보내고 결정론적 문장이 답하게 합니다.
    amount_extreme: dict[str, Any] = {}
    if not result_list_query and not is_result_amount_scope(normalized_query):
        amount_extreme = extract_amount_extreme(normalized_query)
    if amount_extreme:
        filters.update(amount_extreme)
        use_sql = True
        use_vector = False

    trend_marker = next((keyword for keyword in TREND_KEYWORDS if keyword in lowered), "")
    # "동향" 은 입찰 도메인 표지가 함께 있을 때만 추이 질의입니다. "동향이 무슨
    # 뜻이야" 같은 설명형 질의는 기존 의미 검색 경로에 남깁니다. 같은 낱말이
    # 공고명에 쓰인 목록 질의("시장 동향 보고서 공고", "동향 분석 용역 공고
    # 보여줘")도 목록·의미 검색 경로에 남깁니다.
    trend_title_word = trend_marker == "동향" and (
        bool(TREND_TITLE_FOLLOWER_PATTERN.search(lowered))
        or any(marker in lowered for marker in TREND_LIST_MARKERS)
        or bool(COUNT_PATTERN.search(lowered))
    )
    trend_applicable = bool(trend_marker) and (
        trend_marker != "동향"
        or (
            any(marker in lowered for marker in COUNT_QUERY_DOMAIN_MARKERS) and not trend_title_word
        )
    )
    if trend_applicable:
        filters["analysis_mode"] = "trend"
        if trend_marker == "동향":
            # 추이 응답은 지표 하나만 냅니다. 기존 지표 판정과 같은 순서로 지표를
            # 정하고, 시계열 조회가 SQL 로 실행되도록 라우팅합니다.
            use_sql = True
            if not has_semantic_keywords and not is_entity:
                use_vector = False
            if not filters.get("metric"):
                filters["metric"] = _requested_metric(lowered)

    aggregate_filters = extract_aggregate_filters(normalized_query, filters)
    # 특정 업체명을 지목한 질의는 그 업체의 실적 조회이지 순위 집계가 아닙니다.
    # is_entity_specific_query 판정을 먼저 적용해 winner 축으로 새지 않게 합니다.
    if is_entity and aggregate_filters.get("group_by") == "winner":
        aggregate_filters = {}
    filters.update(aggregate_filters)
    # 축이 정해진 금액 순위와, 공고·낙찰 도메인 표지가 있는 순위 질의는 정형
    # 집계로 답합니다. 지표 표지가 없어도 축과 순위 표지만으로 SQL 경로를 켭니다.
    if filters.get("group_by") and (
        filters.get("metric") == "award_amount"
        or (
            any(marker in lowered for marker in AXIS_RANKING_MARKERS)
            and any(marker in lowered for marker in COUNT_QUERY_DOMAIN_MARKERS)
        )
    ):
        use_sql = True
        if not has_semantic_keywords and not is_entity:
            use_vector = False
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
    if amount_extreme:
        route_reason_parts.append(
            "공고 금액 최댓값 질의"
            if amount_extreme.get("amount_extreme") == "max"
            else "공고 금액 최솟값 질의"
        )
    if has_stat_keywords:
        route_reason_parts.append("정형 통계 질의")
    if has_semantic_keywords:
        route_reason_parts.append("문맥/의미 질의")
    if use_kb_status:
        route_reason_parts.append("KB 상태 질의")

    # 위 분기 밖에서 SQL 이 켜지는 경로가 있습니다. 추이 질의의 시계열 조회,
    # 축별 집계의 그룹 조회, 기관·비교 조건 추출이 그렇습니다. 이때 사유가 비면
    # "기본 벡터 질의" 로 떨어져 진단 문구가 실행 판정과 어긋납니다. 실행 판정을
    # 바꾸지 않고, 실제로 SQL 을 켠 조건만 사유에 남깁니다.
    sql_route_reason = any(
        (
            is_bid_number,
            is_entity,
            result_list_query,
            announcement_list_query,
            amount_extreme,
            has_stat_keywords,
        )
    )
    if use_sql and not sql_route_reason:
        if filters.get("analysis_mode") == "trend":
            route_reason_parts.append("추이 질의")
        elif filters.get("group_by"):
            route_reason_parts.append("축별 집계 질의")
        elif has_comparison:
            route_reason_parts.append("비교 질의")
        elif filters.get("institution_names") or filters.get("institution_name"):
            route_reason_parts.append("기관 조건 질의")
        else:
            route_reason_parts.append("정형 조회 질의")

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


def uses_recent_announcement_window(filters: dict[str, Any] | None, query: str) -> bool:
    """기간 없는 질의가 공고 30일 기본 창 대상인지 판정합니다.

    대상은 공고 건수 단일 지표와 추정가격·기초금액 정렬 공고 목록입니다.
    낙찰 통계·추이·축 집계·비교는 기존 5년 기본 창을 유지하므로 제외합니다.
    마감 창이 걸린 질의도 공고일 기본 창을 만들지 않습니다.
    """
    lowered = _query_lower(query)
    if not lowered:
        return False
    current = filters or {}
    if current.get("date_from") or current.get("date_to"):
        return False
    if current.get("close_from") or current.get("close_to"):
        return False
    if str(current.get("time_bucket") or "") == "quarter":
        return False
    if current.get("group_by") or current.get("analysis_mode") == "trend":
        return False
    # 비교 질의는 축 없이 metric 만 남습니다. 비교 판정은 기존 5년 창을 씁니다.
    if current.get("metric"):
        return False

    order_by = _normalize_text(str(current.get("order_by") or ""))
    if order_by in ANNOUNCEMENT_AMOUNT_SORT_FIELDS:
        if current.get("result_limit") or is_result_query(lowered):
            return False
        return not is_result_amount_scope(lowered)

    if current.get("result_limit") or current.get("announcement_limit"):
        return False
    if is_result_query(lowered):
        return False
    return _single_metric(lowered) == "announcement_count"


def apply_default_statistics_window(
    filters: dict[str, Any], *, time_bucket_aware: bool = True, query: str = ""
) -> dict[str, Any]:
    """기간을 말하지 않은 통계 질의에 기본 창을 채웁니다.

    공고 건수와 금액 정렬 공고 목록은 최근 30일, 그 밖의 통계는 최근 5년입니다.
    명시 기간이 항상 이기고, 분기 버킷의 연도 미지정 기본값과 명시적 전체
    기간(`relative_years` 가 이미 있는 경우, 예: years=0)은 그대로 둡니다.
    마감 창이 걸린 질의에는 공고일 기본 창을 겹쳐 걸지 않습니다.
    원본 dict 는 바꾸지 않고 사본을 돌려줍니다.
    """
    windowed = dict(filters)
    if windowed.get("date_from") or windowed.get("date_to"):
        return windowed
    if windowed.get("close_from") or windowed.get("close_to"):
        return windowed
    if "relative_years" in windowed:
        return windowed
    if time_bucket_aware and str(windowed.get("time_bucket") or "") == "quarter":
        return windowed
    if uses_recent_announcement_window(windowed, query):
        today = date.today()
        windowed["recent_days"] = RECENT_ANNOUNCEMENT_WINDOW_DAYS
        windowed["date_from"] = (
            today - timedelta(days=RECENT_ANNOUNCEMENT_WINDOW_DAYS - 1)
        ).isoformat()
        windowed["date_to"] = today.isoformat()
        return windowed
    windowed["relative_years"] = DEFAULT_STATISTICS_WINDOW_YEARS
    return windowed


def replace_whole_period_insufficiency_hint(hints: list[str], filters: dict[str, Any]) -> list[str]:
    """창이 걸린 계획의 '전체 기준' 안내를 실제 기간 안내로 바꿉니다.

    명시 기간은 원래 안내가 붙지 않고, `relative_years` 가 없거나 0 이면
    전체 기간 질의이므로 안내를 유지합니다. 30일 기본 창은 날짜 범위로
    해석되므로 `recent_days` 를 먼저 봅니다.
    """
    recent_days = int(filters.get("recent_days") or 0)
    if recent_days:
        replacement = f"기간을 지정하지 않아 최근 {recent_days}일 기준으로 집계했습니다."
        return [replacement if WHOLE_PERIOD_HINT_MARKER in str(hint) else hint for hint in hints]
    if filters.get("date_from") or filters.get("date_to"):
        return list(hints)
    years = int(filters.get("relative_years") or 0)
    if not years:
        return list(hints)
    replacement = f"기간을 지정하지 않아 최근 {years}년 기준으로 집계했습니다."
    return [replacement if WHOLE_PERIOD_HINT_MARKER in str(hint) else hint for hint in hints]

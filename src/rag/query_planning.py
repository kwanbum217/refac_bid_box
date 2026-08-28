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
}
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
TREND_KEYWORDS = ("추세", "흐름", "변화")

RESULT_QUERY_MARKERS = (
    "낙찰된",
    "낙찰 결과",
    "낙찰정보",
    "낙찰 정보",
    "낙찰 사업",
    "낙찰 업체",
)
RESULT_LIST_MARKERS = ("리스트", "목록", "나열", "뽑아", "골라")

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


def _normalize_text(value: str | None) -> str:
    return unicodedata.normalize("NFC", (value or "").strip())


def _category_label(category: str | None) -> str:
    category_code = _normalize_text(str(category or ""))
    return CATEGORY_LABELS.get(category_code, category_code or "-")


def _query_lower(query: str) -> str:
    return _normalize_text(query).lower()


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


def is_result_list_query(query: str) -> bool:
    """낙찰 결과를 개별 목록으로 요청하는 질의인지 판정합니다."""
    lowered = _query_lower(query)
    has_result_marker = any(marker in lowered for marker in RESULT_QUERY_MARKERS)
    has_list_marker = any(marker in lowered for marker in RESULT_LIST_MARKERS) or bool(
        re.search(r"\d+\s*(?:개|건)", lowered)
    )
    return has_result_marker and has_list_marker


def extract_result_limit(query: str, default: int = 5, maximum: int = 20) -> int:
    """목록 질의의 요청 건수를 안전한 범위로 정규화합니다."""
    match = re.search(r"(\d+)\s*(?:개|건)", _query_lower(query))
    if not match:
        return default
    return min(max(int(match.group(1)), 1), maximum)


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

    if "지난달" in lowered:
        first_this_month = today.replace(day=1)
        last_prev_month = first_this_month - timedelta(days=1)
        first_prev_month = last_prev_month.replace(day=1)
        start, end = _to_iso(first_prev_month, last_prev_month)
        return start, end, "recent", True

    day_match = re.search(r"최근\s*(\d+)\s*일", lowered)
    if day_match:
        days = max(int(day_match.group(1)), 1)
        start, end = _to_iso(today - timedelta(days=days - 1), today)
        return start, end, "recent", True

    month_match = re.search(r"최근\s*(\d+)\s*(?:개월|달)", lowered)
    if month_match:
        months = max(int(month_match.group(1)), 1)
        start, end = _to_iso(today - timedelta(days=(30 * months) - 1), today)
        return start, end, "recent", True

    if "최근 한 달" in lowered or "최근 1달" in lowered or "최근 한달" in lowered:
        start, end = _to_iso(today - timedelta(days=29), today)
        return start, end, "recent", True

    if "최근" in lowered or "요즘" in lowered:
        start, end = _to_iso(today - timedelta(days=6), today)
        return start, end, "recent", True

    return "", "", "", False


def build_retrieval_plan(query: str) -> RetrievalPlan:
    normalized_query = _normalize_text(query)
    lowered = normalized_query.lower()

    is_entity = is_entity_specific_query(normalized_query)
    result_list_query = is_result_list_query(normalized_query)
    has_stat_keywords = any(keyword in lowered for keyword in STATISTICS_KEYWORDS)
    has_semantic_keywords = any(keyword in lowered for keyword in SEMANTIC_KEYWORDS)
    use_kb_status = any(keyword in lowered for keyword in KB_KEYWORDS)

    if is_entity:
        use_sql = True
        use_vector = True
    elif result_list_query or has_stat_keywords:
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

    date_from, date_to, time_bias, explicit_range = _parse_time_window(normalized_query)

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

    filters: dict[str, Any] = {}
    if date_from:
        filters["date_from"] = date_from
    if date_to:
        filters["date_to"] = date_to

    # 한국어 명사구 구조상 수식어 뒤에 오는 마지막 카테고리 단어가 핵어(예: "~공사 감리 용역" -> 용역)이므로
    # 질의에서 가장 뒤에 나타나는 카테고리 키워드를 채택합니다.
    last_cat_pos = -1
    matched_category = None
    for keyword, category in CATEGORY_KEYWORDS.items():
        pos = lowered.rfind(keyword)
        if pos > last_cat_pos:
            last_cat_pos = pos
            matched_category = category

    if matched_category is not None:
        filters["category"] = matched_category

    for region in REGION_KEYWORDS:
        if region in lowered:
            filters["institution_name"] = region
            break

    if result_list_query:
        filters["result_limit"] = extract_result_limit(normalized_query)

    if any(keyword in lowered for keyword in TREND_KEYWORDS):
        filters["analysis_mode"] = "trend"

    route_reason_parts = []
    if is_entity:
        route_reason_parts.append("개체 지정 질의")
    if result_list_query:
        route_reason_parts.append("낙찰 결과 목록 질의")
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

    if use_sql and not filters.get("date_from"):
        plan.insufficiency_hints.append(
            "기간 조건이 명시되지 않아 전체 기준 통계를 사용할 수 있습니다."
        )
    if use_vector and not time_bias:
        plan.insufficiency_hints.append(
            "최신성 조건이 명확하지 않아 일반 문맥 검색으로 처리합니다."
        )
    return plan

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


def _normalize_text(value: str | None) -> str:
    return unicodedata.normalize("NFC", (value or "").strip())


def _category_label(category: str | None) -> str:
    category_code = _normalize_text(str(category or ""))
    return CATEGORY_LABELS.get(category_code, category_code or "-")


def _query_lower(query: str) -> str:
    return _normalize_text(query).lower()


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


def _parse_year_month_window(lowered: str) -> tuple[date, date] | None:
    """일자 없이 연도와 월만 지정한 표현을 기간으로 바꿉니다.

    지원하는 형태입니다.

    | 표현 | 해석 |
    | --- | --- |
    | `2025년 1월부터 3월까지` | 2025-01-01 ~ 2025-03-31 |
    | `2024년 11월부터 2025년 2월까지` | 2024-11-01 ~ 2025-02-28 |
    | `2025년 3월` | 2025-03-01 ~ 2025-03-31 |
    | `2025년` | 2025-01-01 ~ 2025-12-31 |

    월을 넘길 때 30일을 더하는 방식은 말일이 어긋나므로 달력 말일을 씁니다.
    """
    # 연도가 양쪽에 다 붙은 경우를 먼저 봅니다. 뒤 연도를 앞 연도로 덮어쓰면
    # 해를 넘기는 기간이 뒤집힙니다.
    cross_year = re.search(
        r"(\d{4})\s*년\s*(\d{1,2})\s*월\s*(?:부터|~|-)\s*(\d{4})\s*년\s*(\d{1,2})\s*월", lowered
    )
    if cross_year:
        y1, m1, y2, m2 = (int(g) for g in cross_year.groups())
        if 1 <= m1 <= 12 and 1 <= m2 <= 12:
            start, end = sorted((date(y1, m1, 1), date(y2, m2, 1)))
            return start, _month_end(end.year, end.month)

    same_year = re.search(r"(\d{4})\s*년\s*(\d{1,2})\s*월\s*(?:부터|~|-)\s*(\d{1,2})\s*월", lowered)
    if same_year:
        year, m1, m2 = (int(g) for g in same_year.groups())
        if 1 <= m1 <= 12 and 1 <= m2 <= 12:
            first, second = sorted((m1, m2))
            return date(year, first, 1), _month_end(year, second)

    single_month = re.search(r"(\d{4})\s*년\s*(\d{1,2})\s*월", lowered)
    if single_month:
        year, month = (int(g) for g in single_month.groups())
        if 1 <= month <= 12:
            return date(year, month, 1), _month_end(year, month)

    # 연도만 말한 경우입니다. 네 자리 숫자면 무엇이든 연도로 보면 금액이나
    # 공고번호가 걸리므로 "년" 글자가 붙은 것만 인정합니다.
    year_only = re.search(r"(\d{4})\s*년", lowered)
    if year_only:
        year = int(year_only.group(1))
        if 1900 <= year <= 2999:
            return date(year, 1, 1), date(year, 12, 31)

    return None


def _parse_time_window(query: str) -> tuple[str, str, str]:
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
        return start, end, "recent"

    iso_dates = [
        date(int(year), int(month), int(day))
        for year, month, day in re.findall(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", lowered)
    ]
    if len(iso_dates) >= 2:
        start_date, end_date = sorted((iso_dates[0], iso_dates[1]))
        start, end = _to_iso(start_date, end_date)
        return start, end, "recent"

    # 일자 없이 연/월만 말하는 표현입니다. 위의 완전한 날짜 쌍보다 뒤에 두어야
    # "2026년 4월 19일부터 2026년 4월 25일까지" 가 연월 규칙에 먼저 잡히지 않습니다.
    year_month_window = _parse_year_month_window(lowered)
    if year_month_window is not None:
        start, end = _to_iso(*year_month_window)
        return start, end, "recent"

    if "오늘" in lowered:
        start, end = _to_iso(today, today)
        return start, end, "today"

    if "어제" in lowered:
        yesterday = today - timedelta(days=1)
        start, end = _to_iso(yesterday, yesterday)
        return start, end, "recent"

    if "이번 주" in lowered:
        week_start = today - timedelta(days=today.weekday())
        start, end = _to_iso(week_start, today)
        return start, end, "recent"

    if "지난달" in lowered:
        first_this_month = today.replace(day=1)
        last_prev_month = first_this_month - timedelta(days=1)
        first_prev_month = last_prev_month.replace(day=1)
        start, end = _to_iso(first_prev_month, last_prev_month)
        return start, end, "recent"

    day_match = re.search(r"최근\s*(\d+)\s*일", lowered)
    if day_match:
        days = max(int(day_match.group(1)), 1)
        start, end = _to_iso(today - timedelta(days=days - 1), today)
        return start, end, "recent"

    month_match = re.search(r"최근\s*(\d+)\s*(?:개월|달)", lowered)
    if month_match:
        months = max(int(month_match.group(1)), 1)
        start, end = _to_iso(today - timedelta(days=(30 * months) - 1), today)
        return start, end, "recent"

    if "최근 한 달" in lowered or "최근 1달" in lowered or "최근 한달" in lowered:
        start, end = _to_iso(today - timedelta(days=29), today)
        return start, end, "recent"

    if "최근" in lowered or "요즘" in lowered:
        start, end = _to_iso(today - timedelta(days=6), today)
        return start, end, "recent"

    return "", "", ""


def build_retrieval_plan(query: str) -> RetrievalPlan:
    normalized_query = _normalize_text(query)
    lowered = normalized_query.lower()

    result_list_query = is_result_list_query(normalized_query)
    use_sql = result_list_query or any(keyword in lowered for keyword in STATISTICS_KEYWORDS)
    use_vector = not result_list_query and any(keyword in lowered for keyword in SEMANTIC_KEYWORDS)
    use_kb_status = any(keyword in lowered for keyword in KB_KEYWORDS)

    if not any((use_sql, use_vector, use_kb_status)):
        use_vector = True

    date_from, date_to, time_bias = _parse_time_window(normalized_query)
    filters: dict[str, Any] = {}
    if date_from:
        filters["date_from"] = date_from
    if date_to:
        filters["date_to"] = date_to

    for keyword, category in CATEGORY_KEYWORDS.items():
        if keyword in lowered:
            filters["category"] = category
            break

    for region in REGION_KEYWORDS:
        if region in lowered:
            filters["institution_name"] = region
            break

    if result_list_query:
        filters["result_limit"] = extract_result_limit(normalized_query)

    if any(keyword in lowered for keyword in TREND_KEYWORDS):
        filters["analysis_mode"] = "trend"

    route_reason_parts = []
    if result_list_query:
        route_reason_parts.append("낙찰 결과 목록 질의")
    if use_sql:
        route_reason_parts.append("정형 통계 질의")
    if use_vector:
        route_reason_parts.append("문맥/의미 질의")
    if use_kb_status:
        route_reason_parts.append("KB 상태 질의")

    plan = RetrievalPlan(
        use_sql=use_sql,
        use_vector=use_vector,
        use_kb_status=use_kb_status,
        filters=filters,
        semantic_query=normalized_query,
        top_k=DEFAULT_VECTOR_TOP_K,
        time_bias=time_bias,
        route_reason=", ".join(route_reason_parts) or "기본 벡터 질의",
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

"""
src/rag/engine.py

하이브리드 RAG 엔진 (원본 apps/chatbot/services/rag_engine.py 1:1 이식).
라우팅 규칙, 기간 파싱, Source 인용 체계, Answer Guard, 근거(Provenance) 구성을
원본과 동일하게 유지하며, FastAPI 용 비동기 진입점을 함께 제공합니다.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
import unicodedata
from collections.abc import AsyncIterator
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from src.app.models.bids import CATEGORY_LABELS
from src.rag.llm import build_backend
from src.rag.schemas import AnswerBundle, EvidenceItem, Provenance, RetrievalPlan
from src.rag.structured_data import retrieve_structured_data
from src.rag.vector_store import retrieve_semantic_context

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


def _normalize_text(value: str | None) -> str:
    return unicodedata.normalize("NFC", (value or "").strip())


def _category_label(category: str | None) -> str:
    category_code = _normalize_text(str(category or ""))
    return CATEGORY_LABELS.get(category_code, category_code or "-")


def _query_lower(query: str) -> str:
    return _normalize_text(query).lower()


def _format_filters_for_prompt(filters: dict | None) -> str:
    if not filters:
        return ""

    labels = {
        "institution_name": "기관/지역",
        "date_from": "시작일",
        "date_to": "종료일",
        "relative_years": "최근 연수",
        "analysis_mode": "분석 모드",
    }
    lines = []
    for key, value in filters.items():
        if value in (None, ""):
            continue
        if key == "category":
            lines.append(f"- 분야: {_category_label(str(value))}")
            continue
        lines.append(f"- {labels.get(key, key)}: {value}")
    return "\n".join(lines)


def _normalize_category_wording(answer_text: str, plan: RetrievalPlan) -> str:
    """분야 코드(Servc)가 사용자 답변에 노출되지 않도록 교정합니다."""
    category = str((plan.filters or {}).get("category") or "")
    if category != "Servc":
        return answer_text

    normalized = str(answer_text or "")
    replacements = (
        (r"서비스\s*\(\s*Servc\s*\)", "용역"),
        (r"Service\s*\(\s*Servc\s*\)", "용역"),
        (r"\bServc\b", "용역"),
        (r"서비스\s*분야", "용역 분야"),
        (r"서비스\s*공고", "용역 공고"),
    )
    for pattern, replacement in replacements:
        normalized = re.sub(pattern, replacement, normalized, flags=re.IGNORECASE)
    return normalized


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

    use_sql = any(keyword in lowered for keyword in STATISTICS_KEYWORDS)
    use_vector = any(keyword in lowered for keyword in SEMANTIC_KEYWORDS)
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

    if any(keyword in lowered for keyword in TREND_KEYWORDS):
        filters["analysis_mode"] = "trend"

    route_reason_parts = []
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
        top_k=5 if use_vector else 3,
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


def _extract_statistical_snapshot(structured_data: dict | None) -> str:
    if not structured_data:
        return ""

    summary = structured_data.get("summary") or {}
    lines = [
        "정형 데이터 집계:",
        f"- 낙찰 결과 수: {summary.get('total_bids', 0)}",
        f"- 공고 수: {summary.get('announcement_count', 0)}",
        f"- 평균 낙찰률: {summary.get('average_winning_rate', 0)}",
        f"- 총 낙찰 금액: {summary.get('total_winning_amount', 0)}",
    ]

    top_winners = summary.get("top_winners") or []
    if top_winners:
        winner_snapshot = ", ".join(
            f"{item.get('bidwinnr_nm') or '-'}({item.get('win_count', 0)}건)"
            for item in top_winners[:3]
        )
        lines.append(f"- 상위 낙찰 업체: {winner_snapshot}")

    top_institutions = summary.get("top_institutions") or []
    if top_institutions:
        inst_snapshot = ", ".join(
            f"{item.get('dminstt_nm') or '-'}({item.get('ntce_count', 0)}건)"
            for item in top_institutions[:3]
        )
        lines.append(f"- 빈번 공고 기관: {inst_snapshot}")

    top_announcements = summary.get("top_announcements") or []
    if top_announcements:
        ntce_snapshot = ", ".join(
            f"{item.get('bid_ntce_nm') or '-'}({item.get('ntce_count', 0)}건)"
            for item in top_announcements[:3]
        )
        lines.append(f"- 자주 올라오는 공고 명칭: {ntce_snapshot}")

    time_series = summary.get("time_series") or []
    if time_series:
        period_label = "일별" if (time_series[0].get("period") == "day") else "월별"
        lines.append(f"- {period_label} 추세:")
        for row in time_series[-6:]:
            lines.append(
                f"  - {row.get('label') or row.get('month')}: "
                f"avg_rate={row.get('avg_rate', 0)}, bid_count={row.get('bid_count', 0)}"
            )

    for item in structured_data.get("insufficiency_hints") or []:
        lines.append(f"- 한계: {item}")
    return "\n".join(lines)


def _extract_semantic_snapshot(vector_docs: list[dict]) -> str:
    if not vector_docs:
        return ""

    lines = ["문맥 검색 결과:"]
    for item in vector_docs[:3]:
        snippet = _normalize_text(str(item.get("document") or ""))
        if len(snippet) > 220:
            snippet = f"{snippet[:220]}..."
        lines.append(f"- {snippet}")
    return "\n".join(lines)


def _extract_kb_snapshot(kb_status: dict | None) -> str:
    if not kb_status:
        return ""

    return "\n".join(
        [
            "KB 색인 상태:",
            f"- 상태: {kb_status.get('status') or 'unknown'}",
            f"- 색인된 원본 문서 수: {kb_status.get('source_bid_count', 0)}",
            f"- 마지막 파이프라인: {kb_status.get('last_pipeline_run_id') or '-'}",
        ]
    )


def _extract_trend_snapshot(trend_analysis: dict | None) -> str:
    if not trend_analysis:
        return ""

    lines = ["추세 분석:"]
    summary_text = str(trend_analysis.get("summary_text") or "").strip()
    if summary_text:
        lines.append(f"- {summary_text}")

    direction = str(trend_analysis.get("direction") or "").strip()
    if direction:
        lines.append(f"- 방향: {direction}")

    peak = trend_analysis.get("peak") or {}
    trough = trend_analysis.get("trough") or {}
    if peak:
        lines.append(f"- 최고 구간: {peak.get('label') or '-'} / {peak.get('value', 0)}")
    if trough:
        lines.append(f"- 최저 구간: {trough.get('label') or '-'} / {trough.get('value', 0)}")
    return "\n".join(lines)


def _compose_context_text(
    plan: RetrievalPlan,
    structured_data: dict | None,
    vector_docs: list[dict],
    kb_status: dict | None,
) -> str:
    sections = [f"검색 라우팅: {plan.route_reason}"]
    formatted_filters = _format_filters_for_prompt(plan.filters)
    if formatted_filters:
        sections.append(f"적용 필터:\n{formatted_filters}")

    # 통계 및 수치 데이터 (Source [1])
    statistical_snapshot = _extract_statistical_snapshot(structured_data)
    if statistical_snapshot:
        sections.append(f"Source [1] (통계/수치):\n{statistical_snapshot}")

    # 추세 분석 (Source [2])
    trend_snapshot = _extract_trend_snapshot(
        (structured_data or {}).get("trend_analysis") if structured_data else None
    )
    if trend_snapshot:
        sections.append(f"Source [2] (추세 분석):\n{trend_snapshot}")

    # 문맥/의미 검색 결과 (Source [3], [4], [5])
    if vector_docs:
        semantic_lines = ["문맥 검색 결과:"]
        for i, item in enumerate(vector_docs[:3], start=3):
            snippet = _normalize_text(str(item.get("document") or ""))
            if len(snippet) > 250:
                snippet = f"{snippet[:250]}..."
            semantic_lines.append(f"Source [{i}]: {snippet}")
        sections.append("\n".join(semantic_lines))

    # KB 메타데이터 (Source [6])
    kb_snapshot = _extract_kb_snapshot(kb_status)
    if kb_snapshot:
        sections.append(f"Source [6] (지식베이스 상태):\n{kb_snapshot}")

    insufficiency_hints = list(plan.insufficiency_hints)
    if structured_data:
        insufficiency_hints.extend(structured_data.get("insufficiency_hints") or [])
    if not vector_docs and plan.use_vector:
        insufficiency_hints.append("문맥 검색 결과가 충분하지 않습니다.")

    if insufficiency_hints:
        sections.append(
            "한계 및 주의:\n"
            + "\n".join(f"- {item}" for item in dict.fromkeys(insufficiency_hints))
        )

    return "\n\n".join(section for section in sections if section)


def _build_source_citation_from_context(
    structured_data: dict | None,
    vector_docs: list[dict],
    kb_status: dict | None,
) -> str:
    if structured_data and vector_docs:
        return "\n\n근거: 혼합 근거"
    if vector_docs:
        return "\n\n근거: Chroma 문맥 기반"
    if structured_data or kb_status:
        return "\n\n근거: DB 집계 기반"
    return ""


def _normalize_tool_context(
    tool_context: dict | None,
) -> tuple[dict | None, list[dict], dict | None]:
    if not tool_context:
        return None, [], None

    tool_results = tool_context.get("tool_results") or {}
    structured_data = None
    vector_docs: list[dict] = []
    kb_status = None

    bid_query_result = tool_results.get("bid_query")
    if isinstance(bid_query_result, dict):
        structured_data = bid_query_result.get("result") or bid_query_result

    trend_analysis = tool_results.get("trend_analysis")
    if isinstance(trend_analysis, dict):
        structured_data = dict(structured_data or {})
        structured_data["trend_analysis"] = trend_analysis

    semantic_result = tool_results.get("semantic_search")
    if isinstance(semantic_result, dict):
        if isinstance(semantic_result.get("documents"), list):
            vector_docs = semantic_result["documents"]
        elif semantic_result.get("document"):
            vector_docs = [
                {"document": semantic_result["document"], "metadata": {}, "distance": None}
            ]

    kb_result = tool_results.get("kb_status")
    if isinstance(kb_result, dict):
        kb_status = kb_result.get("kb_status") or kb_result

    return structured_data, vector_docs, kb_status


def get_bidding_statistics(
    db: Session,
    institution_name: str = "",
    category: str = "",
    years: int = 5,
    date_from: str = "",
    date_to: str = "",
    query: str = "",
) -> str:
    filters: dict[str, Any] = {}
    if institution_name:
        filters["institution_name"] = institution_name
    if category:
        filters["category"] = category
    if date_from:
        filters["date_from"] = date_from
    if date_to:
        filters["date_to"] = date_to
    if query and any(keyword in _query_lower(query) for keyword in TREND_KEYWORDS):
        filters["analysis_mode"] = "trend"
    if not filters.get("date_from") and not filters.get("date_to") and years:
        today = date.today()
        filters["date_from"] = (today - timedelta(days=(365 * years) - 1)).isoformat()
        filters["date_to"] = today.isoformat()

    plan = RetrievalPlan(
        use_sql=True,
        filters=filters,
        semantic_query=_normalize_text(query),
        time_bias="recent" if filters.get("date_from") else "",
        route_reason="정형 통계 함수 호출",
    )
    return json.dumps(retrieve_structured_data(db, plan), ensure_ascii=False, default=str)


def search_recent_details(query: str, top_k: int = 3) -> str:
    plan = RetrievalPlan(
        use_vector=True,
        semantic_query=_normalize_text(query),
        top_k=max(int(top_k or 3), 1),
        route_reason="문맥 검색 함수 호출",
    )
    documents = retrieve_semantic_context(plan)
    if not documents:
        return "최근 문맥에서 관련된 상세 문서를 찾지 못했습니다."
    top_document = documents[0].get("document") or ""
    return json.dumps(_normalize_text(top_document), ensure_ascii=False)


def _fallback_answer(
    query: str,
    plan: RetrievalPlan,
    structured_data: dict | None,
    vector_docs: list[dict],
    kb_status: dict | None,
) -> str:
    lines = [f"질문: {query}"]
    summary = structured_data.get("summary") if structured_data else {}

    if summary:
        lines.append(
            f"- 낙찰 결과 {summary.get('total_bids', 0)}건, "
            f"공고 {summary.get('announcement_count', 0)}건, "
            f"평균 낙찰률 {summary.get('average_winning_rate', 0)}"
        )
        top_winners = summary.get("top_winners") or []
        if top_winners:
            top_line = ", ".join(
                f"{item.get('bidwinnr_nm') or '-'} {item.get('win_count', 0)}건"
                for item in top_winners[:3]
            )
            lines.append(f"- 상위 낙찰 업체: {top_line}")

    if vector_docs:
        snippet = _normalize_text(str(vector_docs[0].get("document") or ""))
        if len(snippet) > 200:
            snippet = f"{snippet[:200]}..."
        lines.append(f"- 문맥 참고: {snippet}")

    if kb_status:
        lines.append(
            f"- KB 색인 상태: {kb_status.get('status') or 'unknown'} / "
            f"원본 문서 {kb_status.get('source_bid_count', 0)}건"
        )

    insufficiency_hints = list(plan.insufficiency_hints)
    if structured_data:
        insufficiency_hints.extend(structured_data.get("insufficiency_hints") or [])
    if insufficiency_hints:
        lines.append("- 한계: " + " / ".join(dict.fromkeys(insufficiency_hints)))

    return "\n".join(lines) + _build_source_citation_from_context(
        structured_data, vector_docs, kb_status
    )


def _build_evidence_items(
    structured_data: dict | None,
    vector_docs: list[dict],
    kb_status: dict | None,
) -> list[EvidenceItem]:
    items: list[EvidenceItem] = []
    if structured_data:
        summary = structured_data.get("summary") or {}
        items.append(
            EvidenceItem(
                id="sql_summary",
                type="sql_stats",
                content=summary,
                metadata={
                    "filters": structured_data.get("filters", {}),
                    "citation_number": 1,
                    "citation_label": "Source [1]",
                    "citation_role": "통계/수치",
                },
            )
        )
        for i, sample in enumerate(summary.get("sample_announcements") or []):
            items.append(
                EvidenceItem(
                    id=f"bid_{sample.get('bid_ntce_no', i)}",
                    type="sql_stats",
                    content=sample,
                    metadata={
                        "source": "BidAnnouncement",
                        "citation_number": 1,
                        "citation_label": "Source [1]",
                        "citation_role": "통계/수치 상세 공고",
                    },
                )
            )
        trend_analysis = structured_data.get("trend_analysis") or {}
        if trend_analysis:
            items.append(
                EvidenceItem(
                    id="trend_analysis",
                    type="sql_stats",
                    content=trend_analysis,
                    metadata={
                        "source": "TrendAnalysis",
                        "citation_number": 2,
                        "citation_label": "Source [2]",
                        "citation_role": "추세 분석",
                    },
                )
            )

    for i, doc in enumerate(vector_docs):
        metadata = dict(doc.get("metadata") or {})
        citation_number = i + 3
        metadata.update(
            {
                "citation_number": citation_number,
                "citation_label": f"Source [{citation_number}]",
                "citation_role": "문맥 검색",
            }
        )
        items.append(
            EvidenceItem(
                id=f"vec_{i}",
                type="vector_snippet",
                content=doc.get("document", ""),
                metadata=metadata,
                relevance_score=doc.get("distance"),
            )
        )

    if kb_status:
        items.append(
            EvidenceItem(
                id="kb_meta",
                type="kb_metadata",
                content=kb_status,
                metadata={
                    "citation_number": 6,
                    "citation_label": "Source [6]",
                    "citation_role": "지식베이스 상태",
                },
            )
        )
    return items


SYSTEM_PROMPT = (
    "당신은 BIDBOX의 전문 입찰 분석 어시스턴트입니다. "
    "반드시 제공된 '검색 컨텍스트'의 Source 정보를 기반으로 답변하세요. "
    "문장 끝마다 해당 문장의 근거가 되는 소스 번호를 [1], [2]와 같이 인라인 인용으로 표시하세요. "
    "통계 수치(낙찰 수, 상위 업체, 빈번 공고 기관 등)는 Source [1]을, 추세 분석은 Source [2]를, "
    "상세 문맥은 Source [3], [4], [5]를 인용하세요. "
    "특히 '자주 올라오는 공고'나 '빈번한 기관'에 대한 질문에는 Source [1]의 '빈번 공고 기관' 및 "
    "'자주 올라오는 공고 명칭' 데이터를 활용하여 구체적인 수치와 함께 답변하세요. "
    "분야 코드는 내부 식별자입니다. 최종 답변에는 Servc, Thng, Cnstwk, Frgcpt 같은 코드를 쓰지 말고 "
    "용역, 물품, 공사, 외자처럼 사용자용 분류명만 쓰세요. "
    "시각화가 유용하면 아래 형식의 canvas 태그를 본문 끝에 포함할 수 있습니다. "
    "<canvas class='chat-chart' data-type='bar' data-labels='가,나,다' data-values='10,20,30' "
    "data-title='차트 제목'></canvas>"
)


class HybridRAGEngine:
    def __init__(self, provider: str | None = None):
        self._provider = provider
        self._backend: Any = None
        self._backend_resolved = False

    @property
    def backend(self):
        """백엔드는 최초 호출 시 1회만 탐색합니다 (시동 지연 방지)."""
        if not self._backend_resolved:
            self._backend_resolved = True
            self._backend = build_backend(self._provider)
        return self._backend

    @property
    def backend_name(self) -> str:
        return getattr(self.backend, "name", "fallback")

    def _prepare_context(
        self,
        user_query: str,
        db: Session | None = None,
        history: list[dict] | None = None,
        tool_context: dict | None = None,
    ) -> tuple:
        """검색 계획 수립과 컨텍스트 조회를 수행합니다."""
        plan = build_retrieval_plan(user_query)
        structured_data, vector_docs, kb_status = _normalize_tool_context(tool_context)

        if plan.use_sql and structured_data is None and db is not None:
            structured_data = retrieve_structured_data(db, plan)
        if plan.use_vector and not vector_docs:
            vector_docs = retrieve_semantic_context(plan)
        if plan.use_kb_status and kb_status is None and db is not None:
            from src.app.services.tools.kb_status_tool import get_latest_kb_status_payload

            kb_status = get_latest_kb_status_payload(db)

        trace_id = datetime.now().strftime("%Y%m%d%H%M%S") + os.urandom(4).hex()
        evidence_items = _build_evidence_items(structured_data, vector_docs, kb_status)

        provenance = Provenance(
            trace_id=trace_id,
            retrieval_mode=plan.route_reason,
            items=evidence_items,
            insufficiency_hints=list(
                dict.fromkeys(
                    plan.insufficiency_hints
                    + (structured_data.get("insufficiency_hints", []) if structured_data else [])
                )
            ),
            kb_version=str(kb_status.get("updated_at", "")) if kb_status else None,
        )

        context_text = _compose_context_text(plan, structured_data, vector_docs, kb_status)

        messages = [
            {"role": item["role"], "content": item["text"]} for item in history or []
        ]
        messages.append({"role": "user", "content": f"검색 컨텍스트:\n{context_text}"})
        messages.append({"role": "user", "content": _normalize_text(user_query)})

        return plan, structured_data, vector_docs, kb_status, provenance, context_text, messages

    def _apply_answer_guard(
        self,
        answer_text: str,
        structured_data: dict | None,
        plan: Any,
    ) -> str:
        """Answer Guard: 데이터가 있는데 없다고 답한 경우 강제 교정."""
        summary_data = (structured_data or {}).get("summary", {})
        total_bids = summary_data.get("total_bids", 0)
        total_ntce = summary_data.get("announcement_count", 0)
        if "데이터가 없습니다" in answer_text and (total_bids > 0 or total_ntce > 0):
            stats_msg = f"분석 결과 낙찰 {total_bids}건, 공고 {total_ntce}건이 확인되었습니다. "
            answer_text = (
                stats_msg
                + answer_text.replace("데이터가 없습니다", "")
                .replace("관련 정보를 찾을 수 없습니다", "")
                .strip()
            )
        return _normalize_category_wording(answer_text, plan)

    def get_answer_sync(
        self,
        user_query: str,
        db: Session | None = None,
        history: list[dict] | None = None,
        tool_context: dict | None = None,
    ) -> AnswerBundle:
        started = time.time()
        (
            plan,
            structured_data,
            vector_docs,
            kb_status,
            provenance,
            _context_text,
            messages,
        ) = self._prepare_context(user_query, db=db, history=history, tool_context=tool_context)

        def _bundle(answer: str, citations: list[str] | None = None) -> AnswerBundle:
            return AnswerBundle(
                answer=answer,
                provenance=provenance,
                citations=citations or [],
                retrieved_docs=vector_docs,
                latency_ms=(time.time() - started) * 1000.0,
            )

        backend = self.backend
        if backend is None:
            fallback_text = _fallback_answer(
                user_query, plan, structured_data, vector_docs, kb_status
            )
            return _bundle(_normalize_category_wording(fallback_text, plan))

        try:
            answer_text = backend.generate(SYSTEM_PROMPT, messages)
            answer_text = self._apply_answer_guard(answer_text, structured_data, plan)
            citation_suffix = _build_source_citation_from_context(
                structured_data, vector_docs, kb_status
            )
            return _bundle(
                f"{answer_text}{citation_suffix}",
                [citation_suffix.strip()] if citation_suffix.strip() else [],
            )
        except Exception:
            fallback_text = _fallback_answer(
                user_query, plan, structured_data, vector_docs, kb_status
            )
            return _bundle(_normalize_category_wording(fallback_text, plan))

    async def get_answer(
        self,
        user_query: str,
        db: Session | None = None,
        history: list[dict] | None = None,
        tool_context: dict | None = None,
    ) -> AnswerBundle:
        """이벤트 루프를 막지 않도록 동기 경로를 스레드로 오프로드합니다."""
        return await asyncio.to_thread(
            self.get_answer_sync, user_query, db, history, tool_context
        )

    async def stream_tokens(
        self,
        user_query: str,
        db: Session | None = None,
        history: list[dict] | None = None,
        tool_context: dict | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Ollama/Gemini 스트리밍 API 를 사용해 실제 실시간 토큰을 반환합니다.

        Answer Guard 와 카테고리 정규화는 완성된 답변에 대해 마지막에 적용됩니다.
        교정이 필요하면 `done` 이벤트에 `corrected_answer` 필드로 내려갑니다.
        """
        (
            plan,
            structured_data,
            vector_docs,
            kb_status,
            provenance,
            _context_text,
            messages,
        ) = self._prepare_context(user_query, db=db, history=history, tool_context=tool_context)

        yield {"type": "docs", "docs": vector_docs}

        backend = self.backend
        if backend is None:
            fallback_text = _fallback_answer(
                user_query, plan, structured_data, vector_docs, kb_status
            )
            normalized = _normalize_category_wording(fallback_text, plan)
            yield {"type": "token", "text": normalized}
            citation_suffix = _build_source_citation_from_context(
                structured_data, vector_docs, kb_status
            )
            yield {
                "type": "done",
                "citations": [citation_suffix.strip()] if citation_suffix.strip() else [],
                "trace_id": provenance.trace_id,
            }
            return

        try:
            raw_answer = ""
            token_gen = backend.stream_generate(SYSTEM_PROMPT, messages)
            while True:
                token = await asyncio.to_thread(next, token_gen, None)
                if token is None:
                    break
                raw_answer += token
                yield {"type": "token", "text": token}

            corrected_answer = self._apply_answer_guard(raw_answer, structured_data, plan)
            citation_suffix = _build_source_citation_from_context(
                structured_data, vector_docs, kb_status
            )
            final_answer = f"{corrected_answer}{citation_suffix}"
            final_citations = [citation_suffix.strip()] if citation_suffix.strip() else []

            done_event: dict[str, Any] = {
                "type": "done",
                "citations": final_citations,
                "trace_id": provenance.trace_id,
            }
            if corrected_answer != raw_answer:
                done_event["corrected_answer"] = final_answer
            yield done_event
        except Exception:
            fallback_text = _fallback_answer(
                user_query, plan, structured_data, vector_docs, kb_status
            )
            normalized = _normalize_category_wording(fallback_text, plan)
            yield {"type": "token", "text": normalized}
            yield {
                "type": "done",
                "citations": [],
                "trace_id": provenance.trace_id,
            }


rag_engine = HybridRAGEngine()


def get_chatbot_response(
    user_message: str,
    db: Session | None = None,
    history: list[dict] | None = None,
    tool_context: dict | None = None,
) -> AnswerBundle:
    return rag_engine.get_answer_sync(
        user_message, db=db, history=history, tool_context=tool_context
    )

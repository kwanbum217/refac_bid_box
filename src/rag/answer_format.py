"""
src/rag/answer_format.py

RAG 응답 포매팅, Markdown 테이블 조립, Source 인용 생성, Evidence 및 fallback 답변 빌더.
"""

from __future__ import annotations

import re
from typing import Any

from src.rag.query_planning import (
    _category_label,
    _normalize_text,
)
from src.rag.schemas import (
    EvidenceItem,
    RetrievalPlan,
)
from src.rag.snapshots import (
    _extract_kb_snapshot,
    _extract_statistical_snapshot,
    _extract_trend_snapshot,
)


def _format_filters_for_prompt(filters: dict | None) -> str:
    if not filters:
        return ""

    labels = {
        "institution_name": "기관/지역",
        "date_from": "시작일",
        "date_to": "종료일",
        "relative_years": "최근 연수",
        "analysis_mode": "분석 모드",
        "result_limit": "요청 목록 수",
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


def _markdown_result_cell(value: Any) -> str:
    return str(value or "-").replace("|", "\\|").replace("\n", " ").strip()


def _format_result_amount(value: Any) -> str:
    try:
        return f"{int(value):,}원"
    except (TypeError, ValueError):
        return "-"


def _format_result_rate(value: Any) -> str:
    try:
        return f"{float(value):.4f}%"
    except (TypeError, ValueError):
        return "-"


def _build_result_list_answer(
    plan: RetrievalPlan,
    structured_data: dict | None,
) -> str:
    """목록 질의는 LLM 추측 없이 DB 결과를 그대로 표시합니다."""
    result_limit = (plan.filters or {}).get("result_limit")
    if not result_limit or not structured_data:
        return ""

    summary = structured_data.get("summary") or {}
    results = summary.get("recent_results") or []
    category_label = (structured_data.get("filters") or {}).get("category_label") or "조건"
    if not results:
        latest = summary.get("latest_available_result_at")
        answer = f"요청하신 기간에 조건에 맞는 최근 {category_label} 낙찰 결과는 0건입니다."
        if latest:
            answer += f"\n현재 DB에서 확인 가능한 해당 분야의 최신 개찰일은 {latest}입니다."
        return answer

    lines = [
        f"최근 {category_label} 낙찰 결과 {len(results)}건입니다.",
        "",
        "| # | 공고명 | 수요기관 | 낙찰업체 | 낙찰금액 | 낙찰률 | 개찰일 |",
        "| ---: | --- | --- | --- | ---: | ---: | --- |",
    ]
    for index, item in enumerate(results, start=1):
        lines.append(
            f"| {index} | {_markdown_result_cell(item.get('bid_ntce_nm'))} "
            f"({_markdown_result_cell(item.get('bid_ntce_no'))}) | "
            f"{_markdown_result_cell(item.get('dminstt_nm'))} | "
            f"{_markdown_result_cell(item.get('bidwinnr_nm'))} | "
            f"{_format_result_amount(item.get('sucsf_bid_amt'))} | "
            f"{_format_result_rate(item.get('sucsf_bid_rate'))} | "
            f"{_markdown_result_cell(item.get('rl_openg_dt'))} |"
        )
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
    has_sql_evidence = bool(structured_data and not structured_data.get("query_skipped"))
    if has_sql_evidence and vector_docs:
        return "\n\n근거: 혼합 근거"
    if vector_docs:
        return "\n\n근거: Chroma 문맥 기반"
    if has_sql_evidence or kb_status:
        return "\n\n근거: DB 집계 기반"
    return ""


def _fallback_answer(
    query: str,
    plan: RetrievalPlan,
    structured_data: dict | None,
    vector_docs: list[dict],
    kb_status: dict | None,
) -> str:
    lines = [f"질문: {query}"]
    query_skipped = bool(structured_data and structured_data.get("query_skipped"))
    summary = structured_data.get("summary") if structured_data else {}

    if query_skipped:
        lines.append("- 조회를 수행하지 않아 통계가 없습니다.")
    elif summary:
        lines.append(
            f"- 낙찰 결과 {_stat_text(summary.get('total_bids'))}건, "
            f"공고 {_stat_text(summary.get('announcement_count'))}건, "
            f"평균 낙찰률 {_stat_text(summary.get('average_winning_rate'))}"
        )
        top_winners = summary.get("top_winners") or []
        if top_winners:
            top_line = ", ".join(
                f"{item.get('bidwinnr_nm') or '-'} {item.get('win_count', 0)}건"
                for item in top_winners[:3]
            )
            lines.append(f"- 상위 낙찰 업체: {top_line}")

        recent_results = summary.get("recent_results") or []
        latest_available_result_at = summary.get("latest_available_result_at")
        if latest_available_result_at:
            lines.append(f"- DB 최신 개찰일: {latest_available_result_at}")
        if recent_results:
            lines.append("- 최근 낙찰 결과:")
            for index, item in enumerate(recent_results, start=1):
                lines.append(
                    f"  {index}. {item.get('bid_ntce_nm') or '-'} | "
                    f"{item.get('dminstt_nm') or '-'} | "
                    f"{item.get('bidwinnr_nm') or '-'} | "
                    f"{item.get('sucsf_bid_amt') or '-'}원 | "
                    f"{item.get('sucsf_bid_rate') or '-'}%"
                )

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


def _stat_text(value) -> str:
    """0 은 측정값, None 은 값 없음. 값 없음을 0 으로 표기하지 않습니다."""
    return "확인되지 않음" if value is None else str(value)


def _build_evidence_items(
    structured_data: dict | None,
    vector_docs: list[dict],
    kb_status: dict | None,
) -> list[EvidenceItem]:
    items: list[EvidenceItem] = []
    # 조회를 수행하지 않았는데 통계 Source 를 만들면, 모델과 사용자 모두
    # "조회했더니 이런 값이 나왔다" 로 읽습니다. 근거가 없으므로 만들지 않습니다.
    # 건너뛴 사유는 Provenance 의 insufficiency_hints 로 이미 전달됩니다.
    if structured_data and not structured_data.get("query_skipped"):
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
        for i, result in enumerate(summary.get("recent_results") or []):
            items.append(
                EvidenceItem(
                    id=f"result_{result.get('bid_ntce_no') or i}",
                    type="sql_stats",
                    content=result,
                    metadata={
                        "source": "BidResult",
                        "citation_number": 1,
                        "citation_label": "Source [1]",
                        "citation_role": "최근 낙찰 결과 목록",
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

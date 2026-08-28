"""
src/rag/engine.py

하이브리드 RAG 엔진 (원본 apps/chatbot/services/rag_engine.py 1:1 이식).
라우팅 규칙, 기간 파싱, Source 인용 체계, Answer Guard, 근거(Provenance) 구성을
원본과 동일하게 유지하며, FastAPI 용 비동기 진입점을 함께 제공합니다.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from collections.abc import AsyncIterator
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from src.app.core.config import settings
from src.rag.answer_format import (
    _build_evidence_items,
    _build_result_list_answer,
    _build_source_citation_from_context,
    _compose_context_text,
    _fallback_answer,
    _format_filters_for_prompt,
    _format_result_amount,
    _format_result_rate,
    _markdown_result_cell,
    _normalize_category_wording,
)
from src.rag.llm import build_backend
from src.rag.query_planning import (
    CATEGORY_KEYWORDS,
    KB_KEYWORDS,
    REGION_KEYWORDS,
    RESULT_LIST_MARKERS,
    RESULT_QUERY_MARKERS,
    SEMANTIC_KEYWORDS,
    STATISTICS_KEYWORDS,
    TREND_KEYWORDS,
    _category_label,
    _month_end,
    _normalize_text,
    _parse_time_window,
    _parse_year_month_window,
    _query_lower,
    build_retrieval_plan,
    extract_result_limit,
    is_result_list_query,
)
from src.rag.schemas import (
    DEFAULT_VECTOR_TOP_K,
    AnswerBundle,
    EvidenceItem,
    Provenance,
    RetrievalPlan,
)
from src.rag.snapshots import (
    _extract_kb_snapshot,
    _extract_semantic_snapshot,
    _extract_statistical_snapshot,
    _extract_trend_snapshot,
)
from src.rag.structured_data import retrieve_structured_data
from src.rag.vector_store import (
    SemanticSearchResult,
    _extract_doc_sort_key,
    _normalize_match_key,
    extract_document_title,
    retrieve_semantic_context,
)

SYSTEM_PROMPT = (
    "당신은 BIDBOX의 전문 입찰 분석 어시스턴트입니다. "
    "반드시 제공된 '검색 컨텍스트'의 Source 정보를 기반으로 답변하세요. "
    "문장 끝마다 해당 문장의 근거가 되는 소스 번호를 [1], [2]와 같이 인라인 인용으로 표시하세요. "
    "통계 수치(낙찰 수, 상위 업체, 빈번 공고 기관 등)는 Source [1]을, 추세 분석은 Source [2]를, "
    "상세 문맥은 Source [3], [4], [5]를 인용하세요. "
    "특히 '자주 올라오는 공고'나 '빈번한 기관'에 대한 질문에는 Source [1]의 '빈번 공고 기관' 및 "
    "'자주 올라오는 공고 명칭' 데이터를 활용하여 구체적인 수치와 함께 답변하세요. "
    "'최근 낙찰 결과', '낙찰된 사업 목록'처럼 개별 목록을 요청하면 Source [1]의 '최근 낙찰 결과 목록'을 "
    "그대로 사용하여 요청한 개수만큼 공고명, 기관, 낙찰업체, 금액, 낙찰률을 나열하세요. "
    "개별 공고 질의나 여러 공고 간 비교 질의에서도 검색 컨텍스트에 존재하는 낙찰금액과 낙찰률을 어느 한쪽만 언급하여 누락하지 말고 빠짐없이 모두 명시하세요. "
    "여러 공고를 비교할 때는 각 공고의 값(낙찰금액, 낙찰률, 개찰일시 등)을 해당 공고를 담은 Source에서만 가져오고 다른 Source의 값을 섞지 마세요. 각 비교 항목마다 출처 소스 번호를 명확히 붙이세요. "
    "목록 데이터가 컨텍스트에 있으면 검색 결과가 없다고 말하지 마세요. "
    "요청 기간에 목록이 없으면 컨텍스트 부족이라고 하지 말고, 요청 기간의 0건과 DB 최신 개찰일을 명확히 설명하세요. "
    "미개찰 공고, 개찰 전 또는 미래 시점 질의처럼 아직 개찰되지 않았거나 확정되지 않은 예정가격, 1순위 낙찰업체, 낙찰금액, 낙찰률 등의 정보는 "
    "컨텍스트에 근거가 없다면 절대로 추정하거나 임의 예시로 제시하지 말고 확인 불가함을 명시하여 답변을 거절하세요. "
    "거절할 때는 개찰 전 미확정 정보이거나 비공개 내부 정보여서 제공할 수 없다는 사유를 한 문장으로 명확히 밝히세요. "
    "다만 제공된 검색 컨텍스트에 실제 근거가 있으면 위 거절 지시를 적용하지 말고 정상적으로 답변하세요. "
    "분야 코드는 내부 식별자입니다. 최종 답변에는 Servc, Thng, Cnstwk, Frgcpt 같은 코드를 쓰지 말고 "
    "용역, 물품, 공사, 외자처럼 사용자용 분류명만 쓰세요. "
    "시각화가 유용하면 아래 형식의 canvas 태그를 본문 끝에 포함할 수 있습니다. "
    "<canvas class='chat-chart' data-type='bar' data-labels='가,나,다' data-values='10,20,30' "
    "data-title='차트 제목'></canvas>"
)


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


def search_recent_details(query: str, top_k: int = DEFAULT_VECTOR_TOP_K) -> str:
    plan = RetrievalPlan(
        use_vector=True,
        semantic_query=_normalize_text(query),
        top_k=max(int(top_k or DEFAULT_VECTOR_TOP_K), 1),
        route_reason="문맥 검색 함수 호출",
    )
    result = retrieve_semantic_context(plan)
    if not result.ok:
        return "지식베이스 검색에 실패해 상세 문서를 확인하지 못했습니다."
    if not result.documents:
        return "최근 문맥에서 관련된 상세 문서를 찾지 못했습니다."
    top_document = result.documents[0].get("document") or ""
    return json.dumps(_normalize_text(top_document), ensure_ascii=False)


logger = logging.getLogger(__name__)


def _safe_perf_counter() -> float:
    """계측 예외가 주 실행 경로를 중단하지 않도록 보호하는 안전한 time.perf_counter 래퍼입니다."""
    try:
        return time.perf_counter()
    except Exception as exc:
        logger.warning("RAG 구간 계측 시계 조회 중 예외 발생 (무시됨): %s", exc)
        return 0.0


def _contains_bounded_number(answer_text: str, candidate: str) -> bool:
    """후보 문자열 앞뒤에 숫자, 쉼표, 마침표가 붙어 있지 않은 독립 수치인지 확인합니다."""
    if not candidate:
        return False
    pattern = r"(?<![0-9,.])" + re.escape(candidate) + r"(?![0-9,.])"
    return bool(re.search(pattern, answer_text))


def extract_numeric_context_values(context_text: str) -> dict[str, Any]:
    """검색 컨텍스트에서 Source 단위로 낙찰금액([낙찰금액])과 낙찰률([낙찰률]) 값 및 출처 라벨을 추출합니다."""
    if not context_text:
        return {
            "amounts": [],
            "rates": [],
            "amount_sources": {},
            "rate_sources": {},
        }

    # 'Source [n]' 머리글로 블록 분할
    parts = re.split(r"(Source\s*\[\d+\])", context_text)
    blocks: list[tuple[str, str]] = []
    if parts and parts[0]:
        blocks.append(("unknown", parts[0]))
    for i in range(1, len(parts), 2):
        raw_header = parts[i].strip()
        m = re.search(r"Source\s*\[(\d+)\]", raw_header)
        header = f"Source [{m.group(1)}]" if m else raw_header
        content = parts[i + 1] if (i + 1) < len(parts) else ""
        blocks.append((header, content))

    amounts: list[str] = []
    rates: list[str] = []
    amount_sources: dict[str, list[str]] = {}
    rate_sources: dict[str, list[str]] = {}

    for source_label, block_text in blocks:
        amt_matches = re.findall(r"\[낙찰금액\]\s*([0-9,]+)", block_text)
        for m in amt_matches:
            val = m.strip()
            if not val:
                continue
            if val not in amounts:
                amounts.append(val)
            if val not in amount_sources:
                amount_sources[val] = []
            if source_label not in amount_sources[val]:
                amount_sources[val].append(source_label)

        rate_matches = re.findall(r"\[낙찰률\]\s*([0-9]+(?:\.[0-9]+)?)", block_text)
        for r in rate_matches:
            val = r.strip()
            if not val:
                continue
            if val not in rates:
                rates.append(val)
            if val not in rate_sources:
                rate_sources[val] = []
            if source_label not in rate_sources[val]:
                rate_sources[val].append(source_label)

    return {
        "amounts": amounts,
        "rates": rates,
        "amount_sources": amount_sources,
        "rate_sources": rate_sources,
    }


def _extract_target_identifiers_from_plan(plan: RetrievalPlan | None) -> set[str]:
    """RetrievalPlan 에서 질의가 지목하는 특정 공고 식별자나 공고명을 추출합니다."""
    if plan is None:
        return set()
    targets: set[str] = set()

    # 1. filters 내 공고 식별자/명칭 추출
    if plan.filters:
        for key in (
            "bid_ntce_no",
            "announcement_no",
            "announcement_id",
            "bid_ntce_nm",
            "announcement_name",
        ):
            val = plan.filters.get(key)
            if val and isinstance(val, str) and val.strip():
                targets.add(val.strip().lower())

    # 2. semantic_query 에서 공고번호 패턴 및 인용구 추출
    query = getattr(plan, "semantic_query", "") or ""
    if query:
        # 공고번호 또는 문서 ID 패턴 (예: R26BK0001, R26BK01659912-001, bid_10015925)
        for m in re.finditer(
            r"\b(?:[A-Za-z0-9]{6,20}-\d{2,3}|bid_\d{6,10}|[A-Z0-9]{8,20})\b",
            query,
            re.IGNORECASE,
        ):
            token = m.group(0).strip()
            # 단순 연도-월 날짜 형식(2026-08 등)은 제외
            if re.match(r"^\d{4}-\d{2}$", token):
                continue
            targets.add(token.lower())

        # 인용구 (따옴표 또는 각괄호)
        for m in re.finditer(
            r'["\'\u2018\u201c\u300c\u300e\[]([^"\'\u2019\u201d\u300d\u300f\]]{2,})["\'\u2019\u201d\u300d\u300f\]]',
            query,
        ):
            token = m.group(1).strip()
            if token:
                targets.add(token.lower())

    return targets


def _find_target_matching_sources(
    targets: set[str],
    context_text: str,
    provenance: Provenance | None,
) -> set[str]:
    """추출된 대상 식별자/명칭과 일치하는 Source 라벨 집합을 찾습니다."""
    if not targets:
        return set()

    matching_sources: set[str] = set()

    # 1. provenance.items 에서 메타데이터 및 콘텐츠 매칭
    if provenance is not None and getattr(provenance, "items", None) is not None:
        for item in provenance.items:
            source_label = ""
            if isinstance(item, EvidenceItem):
                source_label = item.metadata.get("citation_label") or (
                    f"Source [{item.metadata['citation_number']}]"
                    if "citation_number" in item.metadata
                    else ""
                )
                meta_str = " ".join(str(v) for v in item.metadata.values()).lower()
                content_str = str(item.content).lower()
                item_id = str(item.id).lower()
            elif isinstance(item, dict):
                meta = item.get("metadata") or {}
                source_label = meta.get("citation_label") or (
                    f"Source [{meta['citation_number']}]" if "citation_number" in meta else ""
                )
                meta_str = " ".join(str(v) for v in meta.values()).lower()
                content_str = str(item.get("content", "")).lower()
                item_id = str(item.get("id", "")).lower()
            else:
                continue

            for t in targets:
                if (t in meta_str or t in content_str or t in item_id) and source_label:
                    matching_sources.add(source_label)

    # 2. context_text 의 Source 블록 텍스트에서 매칭
    parts = re.split(r"(Source\s*\[\d+\])", context_text)
    for i in range(1, len(parts), 2):
        raw_header = parts[i].strip()
        m = re.search(r"Source\s*\[(\d+)\]", raw_header)
        header = f"Source [{m.group(1)}]" if m else raw_header
        block_text = parts[i + 1].lower() if (i + 1) < len(parts) else ""
        for t in targets:
            if t in block_text or t in header.lower():
                matching_sources.add(header)

    return matching_sources


def check_numeric_omissions(
    context_text: str,
    answer_text: str,
    trace_id: str = "",
    plan: RetrievalPlan | None = None,
    provenance: Provenance | None = None,
) -> dict[str, Any] | None:
    """검색 컨텍스트에 존재하는 낙찰금액·낙찰률이 최종 답변에 누락되었는지 결정론적으로 검출해 로깅합니다.

    plan 과 provenance 가 주어지면 질의 의도 및 실제 근거에 부합하는 수치만 expected-fact 로 선별합니다.
    """
    if not getattr(settings, "NUMERIC_OMISSION_DETECTION", False):
        return None

    if not context_text or not answer_text:
        return None

    extracted = extract_numeric_context_values(context_text)
    amounts = extracted.get("amounts", [])
    rates = extracted.get("rates", [])
    amount_sources = extracted.get("amount_sources", {})
    rate_sources = extracted.get("rate_sources", {})

    if not amounts and not rates:
        return None

    # Provenance 기반 유효 출처 라벨 집합 구성
    valid_provenance_sources: set[str] | None = None
    if provenance is not None and getattr(provenance, "items", None) is not None:
        collected_sources: set[str] = set()
        for item in provenance.items:
            if isinstance(item, EvidenceItem):
                lbl = item.metadata.get("citation_label")
                if lbl:
                    collected_sources.add(lbl)
                elif "citation_number" in item.metadata:
                    collected_sources.add(f"Source [{item.metadata['citation_number']}]")
            elif isinstance(item, dict):
                meta = item.get("metadata") or {}
                lbl = meta.get("citation_label")
                if lbl:
                    collected_sources.add(lbl)
                elif "citation_number" in meta:
                    collected_sources.add(f"Source [{meta['citation_number']}]")
        if collected_sources:
            valid_provenance_sources = collected_sources

    # Plan 기반 대상 공고 Source 집합 식별
    targets = _extract_target_identifiers_from_plan(plan)
    target_matching_sources: set[str] | None = None
    if targets:
        matched = _find_target_matching_sources(targets, context_text, provenance)
        if matched:
            target_matching_sources = matched

    def _is_expected(val: str, sources: list[str]) -> bool:
        # 출처를 특정할 수 없는 unknown 은 보수적으로 기대 사실에 남김
        if not sources or "unknown" in sources:
            return True

        # (1) Provenance 검사: provenance 가 제공된 경우 적어도 하나의 source 가 근거 항목에 포함되어야 함
        if valid_provenance_sources is not None and not any(
            s in valid_provenance_sources for s in sources
        ):
            return False

        # (2) Plan 의도 검사: 대상 공고가 특정된 경우 적어도 하나의 source 가 대상 공고 source 에 포함되어야 함
        if target_matching_sources is not None:
            return any(s in target_matching_sources for s in sources)

        return True

    expected_amounts: list[str] = []
    filtered_amounts: list[str] = []
    filtered_amount_sources: dict[str, list[str]] = {}
    for amt in amounts:
        srcs = amount_sources.get(amt, [])
        if _is_expected(amt, srcs):
            expected_amounts.append(amt)
        else:
            filtered_amounts.append(amt)
            filtered_amount_sources[amt] = srcs

    expected_rates: list[str] = []
    filtered_rates: list[str] = []
    filtered_rate_sources: dict[str, list[str]] = {}
    for r in rates:
        srcs = rate_sources.get(r, [])
        if _is_expected(r, srcs):
            expected_rates.append(r)
        else:
            filtered_rates.append(r)
            filtered_rate_sources[r] = srcs

    missing_amounts: list[str] = []
    missing_amount_sources: dict[str, list[str]] = {}
    for amt in expected_amounts:
        digits = amt.replace(",", "")
        candidates = {amt, digits}
        if digits.isdigit():
            candidates.add(f"{int(digits):,}")
        if not any(_contains_bounded_number(answer_text, cand) for cand in candidates):
            missing_amounts.append(amt)
            missing_amount_sources[amt] = amount_sources.get(amt, ["unknown"])

    missing_rates: list[str] = []
    missing_rate_sources: dict[str, list[str]] = {}
    for r in expected_rates:
        candidates = {r}
        try:
            val = float(r)
            candidates.add(f"{val:g}")
            candidates.add(f"{val:.4f}".rstrip("0").rstrip("."))
            candidates.add(f"{val:.2f}")
        except ValueError:
            pass
        if not any(_contains_bounded_number(answer_text, cand) for cand in candidates):
            missing_rates.append(r)
            missing_rate_sources[r] = rate_sources.get(r, ["unknown"])

    missing_types: list[str] = []
    if missing_amounts:
        missing_types.append("amount")
    if missing_rates:
        missing_types.append("rate")

    total_missing_count = len(missing_amounts) + len(missing_rates)

    if total_missing_count > 0:
        logger.warning(
            "rag_numeric_omission: trace_id=%s missing_types=%s missing_count=%d missing_amounts=%s missing_rates=%s missing_amount_sources=%s missing_rate_sources=%s filtered_amounts=%s filtered_rates=%s filtered_amount_sources=%s filtered_rate_sources=%s",
            trace_id,
            missing_types,
            total_missing_count,
            missing_amounts,
            missing_rates,
            missing_amount_sources,
            missing_rate_sources,
            filtered_amounts,
            filtered_rates,
            filtered_amount_sources,
            filtered_rate_sources,
            extra={
                "trace_id": trace_id,
                "omission_detected": True,
                "missing_types": missing_types,
                "missing_count": total_missing_count,
                "missing_amounts": missing_amounts,
                "missing_rates": missing_rates,
                "missing_amount_sources": missing_amount_sources,
                "missing_rate_sources": missing_rate_sources,
                "filtered_amounts": filtered_amounts,
                "filtered_rates": filtered_rates,
                "filtered_amount_sources": filtered_amount_sources,
                "filtered_rate_sources": filtered_rate_sources,
            },
        )

    return {
        "omission_detected": total_missing_count > 0,
        "missing_types": missing_types,
        "missing_count": total_missing_count,
        "missing_amounts": missing_amounts,
        "missing_rates": missing_rates,
        "missing_amount_sources": missing_amount_sources,
        "missing_rate_sources": missing_rate_sources,
        "filtered_amounts": filtered_amounts,
        "filtered_rates": filtered_rates,
        "filtered_amount_sources": filtered_amount_sources,
        "filtered_rate_sources": filtered_rate_sources,
    }


class PreparedContext(tuple):
    """_prepare_context 반환 튜플 (기존 7개 요소와 세부 구간 계측 정보 보존)."""

    timings: dict[str, float]

    def __new__(
        cls,
        plan: Any,
        structured_data: Any,
        vector_docs: Any,
        kb_status: Any,
        provenance: Any,
        context_text: Any,
        messages: Any,
        timings: dict[str, float] | None = None,
    ) -> PreparedContext:
        instance = super().__new__(
            cls,
            (
                plan,
                structured_data,
                vector_docs,
                kb_status,
                provenance,
                context_text,
                messages,
            ),
        )
        instance.timings = timings or {}
        return instance

    @property
    def plan(self) -> Any:
        return self[0]

    @property
    def structured_data(self) -> Any:
        return self[1]

    @property
    def vector_docs(self) -> Any:
        return self[2]

    @property
    def kb_status(self) -> Any:
        return self[3]

    @property
    def provenance(self) -> Any:
        return self[4]

    @property
    def context_text(self) -> Any:
        return self[5]

    @property
    def messages(self) -> Any:
        return self[6]


def retrieve_lexical_context(
    plan: RetrievalPlan,
    db: Session | None = None,
) -> list[dict[str, Any]]:
    """Meilisearch 어휘(Lexical) 인덱스에서 공고명(bid_ntce_nm) 일치 문서를 검색합니다.

    비활성화(MEILI_ENABLED=False), 서버 미기동, 타임아웃, 예외 발생 시 빈 리스트를 반환하여
    호출부가 안전하게 기존 벡터 검색 결과로 폴백할 수 있게 합니다.
    """
    if not getattr(settings, "MEILI_ENABLED", False):
        return []

    lexical_query = plan.lexical_query or plan.semantic_query
    if not lexical_query:
        return []

    try:
        from src.app.services.search_index import INDEX_UID, MeiliSearchClient

        client = MeiliSearchClient()
        filters = ['dataset = "announcement"']

        category = plan.filters.get("category")
        if category:
            filters.append(f"category = {json.dumps(category, ensure_ascii=False)}")

        institution = plan.filters.get("institution_name")
        if institution:
            from src.app.services.search_index import _region_codes

            regions = _region_codes(institution)
            if regions:
                filters.append(f"region_codes = {json.dumps(regions[0], ensure_ascii=False)}")

        fetch_limit = max(plan.top_k or DEFAULT_VECTOR_TOP_K, 10)

        payload = client._request(
            "POST",
            f"/indexes/{INDEX_UID}/search",
            json={
                "q": lexical_query,
                "filter": " AND ".join(filters),
                "limit": fetch_limit,
                "attributesToRetrieve": [
                    "id",
                    "source_id",
                    "dataset",
                    "bid_ntce_no",
                    "bid_ntce_nm",
                    "dminstt_nm",
                    "ntce_instt_nm",
                    "category",
                    "bid_ntce_dt",
                    "bid_clse_dt",
                    "base_amount",
                    "collected_at",
                ],
            },
        )
        hits = payload.get("hits", [])
        if not hits:
            return []

        results: list[dict[str, Any]] = []
        for hit in hits:
            bid_ntce_nm = hit.get("bid_ntce_nm") or ""
            dminstt_nm = hit.get("dminstt_nm") or hit.get("ntce_instt_nm") or ""
            bid_ntce_dt = hit.get("bid_ntce_dt") or ""
            bid_ntce_no = hit.get("bid_ntce_no") or ""
            category_val = hit.get("category") or ""

            doc_lines = []
            if dminstt_nm:
                doc_lines.append(f"[수요기관] {dminstt_nm}")
            if bid_ntce_nm:
                doc_lines.append(f"[공고명] {bid_ntce_nm}")
            if bid_ntce_dt:
                doc_lines.append(f"[공고일시] {bid_ntce_dt}")

            doc_text = "\n".join(doc_lines)

            results.append(
                {
                    "id": hit.get("id") or f"announcement_{category_val}_{bid_ntce_no}",
                    "document": doc_text,
                    "content": doc_text,
                    "metadata": {
                        "bid_ntce_no": bid_ntce_no,
                        "bid_ntce_nm": bid_ntce_nm,
                        "dminstt_nm": dminstt_nm,
                        "category": category_val,
                        "bid_ntce_dt": bid_ntce_dt,
                        "source_id": hit.get("source_id"),
                        "id": hit.get("id"),
                    },
                    "distance": 0.0,
                    "source": "meilisearch_lexical",
                }
            )
        return results
    except Exception as exc:
        logger.warning("Meilisearch 어휘 검색 중 오류 발생 (벡터 경로로 폴백): %s", exc)
        return []


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
    ) -> PreparedContext:
        """검색 계획 수립과 컨텍스트 조회를 수행하고 세부 구간을 계측합니다."""
        t_prep_start = _safe_perf_counter()

        t_plan_start = _safe_perf_counter()
        plan = build_retrieval_plan(user_query)
        plan_elapsed_ms = (_safe_perf_counter() - t_plan_start) * 1000.0

        structured_data, vector_docs, kb_status = _normalize_tool_context(tool_context)
        vector_failed = False

        sql_elapsed_ms = 0.0
        if plan.use_sql and structured_data is None and db is not None:
            t_sql_start = _safe_perf_counter()
            structured_data = retrieve_structured_data(db, plan)
            sql_elapsed_ms = (_safe_perf_counter() - t_sql_start) * 1000.0

        lexical_elapsed_ms = 0.0
        vector_elapsed_ms = 0.0
        vector_hints: list[str] = []
        vector_filter_provenance: dict[str, Any] | None = None

        # 1. Lexical (Meilisearch) 어휘 채널 선행 호출 및 정확 일치 검사
        if plan.use_lexical and not vector_docs:
            t_lex_start = _safe_perf_counter()
            lexical_candidates = retrieve_lexical_context(plan, db=db)
            lexical_elapsed_ms = (_safe_perf_counter() - t_lex_start) * 1000.0

            if lexical_candidates:
                query_key = _normalize_match_key(plan.lexical_query or plan.semantic_query)
                exact_lexical_matches: list[dict[str, Any]] = []

                for doc in lexical_candidates:
                    raw_doc_meta = doc.get("metadata")
                    doc_meta: dict[str, Any] = (
                        raw_doc_meta if isinstance(raw_doc_meta, dict) else {}
                    )
                    doc_title = doc_meta.get("bid_ntce_nm") or extract_document_title(
                        doc.get("document")
                    )
                    if doc_title and _normalize_match_key(doc_title) == query_key:
                        exact_lexical_matches.append(doc)

                if exact_lexical_matches:
                    exact_lexical_matches.sort(key=_extract_doc_sort_key, reverse=True)
                    target_k = plan.top_k or DEFAULT_VECTOR_TOP_K
                    vector_docs = exact_lexical_matches[:target_k]
                    logger.info(
                        "Meilisearch 어휘 채널 정확 일치 문서 %d건 우선 채택 완료 (ChromaDB 벡터 검색 생략, 총 %d건)",
                        len(exact_lexical_matches),
                        len(vector_docs),
                    )

        # 2. Vector (ChromaDB) 의미 검색 (Lexical 정확 일치가 없을 때만 실행)
        if plan.use_vector and not vector_docs:
            t_vector_start = _safe_perf_counter()
            result = retrieve_semantic_context(plan)
            vector_elapsed_ms = (_safe_perf_counter() - t_vector_start) * 1000.0
            vector_docs = result.documents
            if not result.ok:
                vector_failed = True
            else:
                vector_filter_provenance = result.as_filter_provenance()
                if result.filter_relaxed:
                    vector_hints.append(
                        "지식베이스 검색 필터가 완화되어 필터 조건 밖 문서가 반환되었을 수 있습니다."
                    )
                if result.unsupported_filters:
                    unsupported_keys = ", ".join(sorted(result.unsupported_filters))
                    vector_hints.append(
                        f"지식베이스 검색에서 지원되지 않아 적용되지 않은 필터: {unsupported_keys}"
                    )
                if result.effective_filters and not result.documents:
                    vector_hints.append(
                        "지식베이스 필터 조건에 맞는 문서가 0건이라 문맥 없이 답변합니다."
                    )

        kb_status_elapsed_ms = 0.0
        if plan.use_kb_status and kb_status is None and db is not None:
            t_kb_start = _safe_perf_counter()
            from src.app.services.tools.kb_status_tool import get_latest_kb_status_payload

            kb_status = get_latest_kb_status_payload(db)
            kb_status_elapsed_ms = (_safe_perf_counter() - t_kb_start) * 1000.0

        t_assembly_start = _safe_perf_counter()
        trace_id = datetime.now().strftime("%Y%m%d%H%M%S") + os.urandom(4).hex()
        evidence_items = _build_evidence_items(structured_data, vector_docs, kb_status)

        hints = list(
            dict.fromkeys(
                plan.insufficiency_hints
                + (structured_data.get("insufficiency_hints", []) if structured_data else [])
                + vector_hints
            )
        )
        if vector_failed:
            failure_hint = "지식베이스 문맥 검색에 실패해 문맥 없이 답변합니다."
            if failure_hint not in hints:
                hints.append(failure_hint)

        provenance = Provenance(
            trace_id=trace_id,
            retrieval_mode=plan.route_reason,
            items=evidence_items,
            insufficiency_hints=hints,
            kb_version=str(kb_status.get("updated_at", "")) if kb_status else None,
            vector_filter_provenance=vector_filter_provenance,
        )

        context_text = _compose_context_text(plan, structured_data, vector_docs, kb_status)

        messages = [{"role": item["role"], "content": item["text"]} for item in history or []]
        messages.append({"role": "user", "content": f"검색 컨텍스트:\n{context_text}"})
        messages.append({"role": "user", "content": _normalize_text(user_query)})
        assembly_elapsed_ms = (_safe_perf_counter() - t_assembly_start) * 1000.0

        prepare_total_ms = (_safe_perf_counter() - t_prep_start) * 1000.0

        try:
            timings = {
                "plan_ms": round(plan_elapsed_ms, 2),
                "sql_ms": round(sql_elapsed_ms, 2),
                "vector_ms": round(vector_elapsed_ms, 2),
                "lexical_ms": round(lexical_elapsed_ms, 2),
                "kb_status_ms": round(kb_status_elapsed_ms, 2),
                "assembly_ms": round(assembly_elapsed_ms, 2),
                "prepare_total_ms": round(prepare_total_ms, 2),
            }
        except Exception as exc:
            logger.warning("RAG 준비 구간 계측 중 예외 발생 (무시됨): %s", exc)
            timings = {
                "plan_ms": 0.0,
                "sql_ms": 0.0,
                "vector_ms": 0.0,
                "lexical_ms": 0.0,
                "kb_status_ms": 0.0,
                "assembly_ms": 0.0,
                "prepare_total_ms": 0.0,
            }

        return PreparedContext(
            plan,
            structured_data,
            vector_docs,
            kb_status,
            provenance,
            context_text,
            messages,
            timings=timings,
        )

    def _apply_answer_guard(
        self,
        answer_text: str,
        structured_data: dict | None,
        plan: Any,
        context_text: str = "",
        trace_id: str = "",
        provenance: Any = None,
    ) -> str:
        """Answer Guard: 데이터가 있는데 없다고 답한 경우 강제 교정 및 최종 답변 기준 수치 누락 검출."""
        if (structured_data or {}).get("query_skipped"):
            # 조회를 하지 않았으면 교정할 근거가 없습니다. 없다고 답한 것이 맞습니다.
            final_answer = _normalize_category_wording(answer_text, plan)
        else:
            summary_data = (structured_data or {}).get("summary") or {}
            # 키는 있는데 값이 None 인 경우가 있습니다. get 의 기본값은 그때 쓰이지
            # 않으므로 None 이 그대로 비교로 들어가 TypeError 가 납니다.
            total_bids = summary_data.get("total_bids") or 0
            total_ntce = summary_data.get("announcement_count") or 0
            if "데이터가 없습니다" in answer_text and (total_bids > 0 or total_ntce > 0):
                stats_msg = f"분석 결과 낙찰 {total_bids}건, 공고 {total_ntce}건이 확인되었습니다. "
                answer_text = (
                    stats_msg
                    + answer_text.replace("데이터가 없습니다", "")
                    .replace("관련 정보를 찾을 수 없습니다", "")
                    .strip()
                )
            final_answer = _normalize_category_wording(answer_text, plan)

        if context_text:
            check_numeric_omissions(
                context_text,
                final_answer,
                trace_id=trace_id,
                plan=plan if isinstance(plan, RetrievalPlan) else None,
                provenance=provenance if isinstance(provenance, Provenance) else None,
            )

        return final_answer

    def get_answer_sync(
        self,
        user_query: str,
        db: Session | None = None,
        history: list[dict] | None = None,
        tool_context: dict | None = None,
    ) -> AnswerBundle:
        t_start = _safe_perf_counter()
        prepared = self._prepare_context(
            user_query, db=db, history=history, tool_context=tool_context
        )
        (
            plan,
            structured_data,
            vector_docs,
            kb_status,
            provenance,
            _context_text,
            messages,
        ) = prepared

        timings = getattr(prepared, "timings", {})
        plan_ms = float(timings.get("plan_ms", 0.0))
        sql_ms = float(timings.get("sql_ms", 0.0))
        vector_ms = float(timings.get("vector_ms", 0.0))
        lexical_ms = float(timings.get("lexical_ms", 0.0))
        kb_status_ms = float(timings.get("kb_status_ms", 0.0))
        assembly_ms = float(timings.get("assembly_ms", 0.0))
        prepare_total_ms = float(
            timings.get("prepare_total_ms", (_safe_perf_counter() - t_start) * 1000.0)
        )

        def _calc_segment_metrics(
            llm_ms: float, guard_ms: float, total_ms: float
        ) -> dict[str, float]:
            try:
                return {
                    "plan_ms": round(plan_ms, 2),
                    "sql_ms": round(sql_ms, 2),
                    "vector_ms": round(vector_ms, 2),
                    "lexical_ms": round(lexical_ms, 2),
                    "kb_status_ms": round(kb_status_ms, 2),
                    "assembly_ms": round(assembly_ms, 2),
                    "prepare_total_ms": round(prepare_total_ms, 2),
                    "llm_ms": round(llm_ms, 2),
                    "guard_ms": round(guard_ms, 2),
                    "total_ms": round(total_ms, 2),
                }
            except Exception as exc:
                logger.warning("RAG 구간 지표 계산 중 예외 발생 (무시됨): %s", exc)
                return {
                    "sql_ms": 0.0,
                    "vector_ms": 0.0,
                    "lexical_ms": 0.0,
                    "llm_ms": 0.0,
                    "total_ms": 0.0,
                }

        def _log_latency(
            status: str,
            llm_ms: float,
            guard_ms: float,
            total_ms: float,
            backend_name: str,
        ) -> None:
            if not getattr(settings, "LATENCY_SEGMENT_LOGGING", False):
                return
            try:
                logger.info(
                    "rag_engine_latency: trace_id=%s status=%s route=%s use_sql=%s use_vector=%s use_lexical=%s use_kb=%s "
                    "plan_ms=%.2f sql_ms=%.2f vector_ms=%.2f lexical_ms=%.2f kb_ms=%.2f assembly_ms=%.2f prepare_ms=%.2f "
                    "llm_ms=%.2f guard_ms=%.2f total_ms=%.2f backend=%s",
                    provenance.trace_id,
                    status,
                    plan.route_reason or "unknown",
                    plan.use_sql,
                    plan.use_vector,
                    getattr(plan, "use_lexical", False),
                    plan.use_kb_status,
                    plan_ms,
                    sql_ms,
                    vector_ms,
                    lexical_ms,
                    kb_status_ms,
                    assembly_ms,
                    prepare_total_ms,
                    llm_ms,
                    guard_ms,
                    total_ms,
                    backend_name,
                    extra={
                        "trace_id": provenance.trace_id,
                        "status": status,
                        "route": plan.route_reason,
                        "use_sql": plan.use_sql,
                        "use_vector": plan.use_vector,
                        "use_lexical": getattr(plan, "use_lexical", False),
                        "use_kb_status": plan.use_kb_status,
                        "plan_ms": plan_ms,
                        "sql_ms": sql_ms,
                        "vector_ms": vector_ms,
                        "lexical_ms": lexical_ms,
                        "kb_status_ms": kb_status_ms,
                        "assembly_ms": assembly_ms,
                        "prepare_ms": prepare_total_ms,
                        "llm_ms": llm_ms,
                        "guard_ms": guard_ms,
                        "total_ms": total_ms,
                        "backend": backend_name,
                    },
                )
            except Exception as exc:
                logger.warning("RAG 레이턴시 로깅 중 예외 발생 (무시됨): %s", exc)

        def _bundle(
            answer: str,
            citations: list[str] | None = None,
            total_elapsed_ms: float | None = None,
            segment_metrics: dict[str, float] | None = None,
        ) -> AnswerBundle:
            elapsed = (
                total_elapsed_ms
                if total_elapsed_ms is not None
                else (_safe_perf_counter() - t_start) * 1000.0
            )
            expose_flag = getattr(settings, "RAG_EXPOSE_SEGMENT_METRICS", False)
            metrics_to_include = (
                segment_metrics if (expose_flag and segment_metrics is not None) else None
            )
            return AnswerBundle(
                answer=answer,
                provenance=provenance,
                citations=citations or [],
                retrieved_docs=vector_docs,
                latency_ms=elapsed,
                segment_metrics=metrics_to_include,
            )

        t_direct_start = _safe_perf_counter()
        direct_result_list_answer = _build_result_list_answer(plan, structured_data)
        if direct_result_list_answer:
            citation_suffix = _build_source_citation_from_context(
                structured_data, vector_docs, kb_status
            )
            guard_elapsed_ms = (_safe_perf_counter() - t_direct_start) * 1000.0
            total_elapsed_ms = (_safe_perf_counter() - t_start) * 1000.0
            _log_latency(
                status="direct_result_list",
                llm_ms=0.0,
                guard_ms=guard_elapsed_ms,
                total_ms=total_elapsed_ms,
                backend_name="none",
            )
            seg_metrics = _calc_segment_metrics(0.0, guard_elapsed_ms, total_elapsed_ms)
            return _bundle(
                f"{direct_result_list_answer}{citation_suffix}",
                [citation_suffix.strip()] if citation_suffix.strip() else [],
                total_elapsed_ms=total_elapsed_ms,
                segment_metrics=seg_metrics,
            )

        backend = self.backend
        if backend is None:
            t_fallback_start = _safe_perf_counter()
            fallback_text = _fallback_answer(
                user_query, plan, structured_data, vector_docs, kb_status
            )
            normalized = _normalize_category_wording(fallback_text, plan)
            guard_elapsed_ms = (_safe_perf_counter() - t_fallback_start) * 1000.0
            total_elapsed_ms = (_safe_perf_counter() - t_start) * 1000.0
            _log_latency(
                status="fallback_no_backend",
                llm_ms=0.0,
                guard_ms=guard_elapsed_ms,
                total_ms=total_elapsed_ms,
                backend_name="fallback",
            )
            seg_metrics = _calc_segment_metrics(0.0, guard_elapsed_ms, total_elapsed_ms)
            return _bundle(
                normalized,
                total_elapsed_ms=total_elapsed_ms,
                segment_metrics=seg_metrics,
            )

        backend_name = getattr(backend, "name", "unknown")
        t_llm_start = _safe_perf_counter()
        try:
            answer_text = backend.generate(SYSTEM_PROMPT, messages)
            llm_elapsed_ms = (_safe_perf_counter() - t_llm_start) * 1000.0

            t_guard_start = _safe_perf_counter()
            answer_text = self._apply_answer_guard(
                answer_text,
                structured_data,
                plan,
                context_text=_context_text,
                trace_id=provenance.trace_id,
                provenance=provenance,
            )
            citation_suffix = _build_source_citation_from_context(
                structured_data, vector_docs, kb_status
            )
            guard_elapsed_ms = (_safe_perf_counter() - t_guard_start) * 1000.0

            total_elapsed_ms = (_safe_perf_counter() - t_start) * 1000.0
            _log_latency(
                status="success",
                llm_ms=llm_elapsed_ms,
                guard_ms=guard_elapsed_ms,
                total_ms=total_elapsed_ms,
                backend_name=backend_name,
            )
            seg_metrics = _calc_segment_metrics(llm_elapsed_ms, guard_elapsed_ms, total_elapsed_ms)
            return _bundle(
                f"{answer_text}{citation_suffix}",
                [citation_suffix.strip()] if citation_suffix.strip() else [],
                total_elapsed_ms=total_elapsed_ms,
                segment_metrics=seg_metrics,
            )
        except Exception as exc:
            llm_elapsed_ms = (_safe_perf_counter() - t_llm_start) * 1000.0
            t_fallback_start = _safe_perf_counter()
            fallback_text = _fallback_answer(
                user_query, plan, structured_data, vector_docs, kb_status
            )
            normalized = _normalize_category_wording(fallback_text, plan)
            guard_elapsed_ms = (_safe_perf_counter() - t_fallback_start) * 1000.0
            total_elapsed_ms = (_safe_perf_counter() - t_start) * 1000.0
            logger.warning(
                "LLM 생성 실패로 fallback 전환 (trace_id=%s, backend=%s, error=%s)",
                provenance.trace_id,
                backend_name,
                exc,
            )
            _log_latency(
                status="fallback_error",
                llm_ms=llm_elapsed_ms,
                guard_ms=guard_elapsed_ms,
                total_ms=total_elapsed_ms,
                backend_name=backend_name,
            )
            seg_metrics = _calc_segment_metrics(llm_elapsed_ms, guard_elapsed_ms, total_elapsed_ms)
            return _bundle(
                normalized,
                total_elapsed_ms=total_elapsed_ms,
                segment_metrics=seg_metrics,
            )

    async def get_answer(
        self,
        user_query: str,
        db: Session | None = None,
        history: list[dict] | None = None,
        tool_context: dict | None = None,
    ) -> AnswerBundle:
        """이벤트 루프를 막지 않도록 동기 경로를 스레드로 오프로드합니다."""
        return await asyncio.to_thread(self.get_answer_sync, user_query, db, history, tool_context)

    async def stream_tokens(
        self,
        user_query: str,
        db: Session | None = None,
        history: list[dict] | None = None,
        tool_context: dict | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Ollama/Gemini 스트리밍 API 를 사용해 실제 실시간 토큰을 반환합니다.

        클라이언트 필수 계약:

        `token` 이벤트는 LLM 원문이라 Answer Guard 와 카테고리 정규화를 거치지
        않은 상태입니다. 두 교정은 답변이 완성돼야 판단할 수 있어 `done` 시점에
        적용됩니다. 교정이 발생하면 `done` 이벤트에 `corrected_answer` 가 실립니다.

        **`corrected_answer` 가 있으면 클라이언트는 지금까지 그린 본문을 이 값으로
        교체해야 합니다.** 무시하면 데이터가 있는데도 "데이터가 없습니다" 라고
        답한 원문이 그대로 남습니다. Answer Guard 가 막으려던 바로 그 상황입니다.

        `done` 은 항상 `final_answer` 를 싣습니다. 교정 여부와 출처 표기까지 반영한
        정본 본문이므로, 토큰을 이어붙여 직접 조립하지 말고 이 값을 쓰십시오.

        주의: 이 경로는 RAG 답변만 흘립니다. 플래너, 자동화 확인, 차트 페이로드,
        세션 저장은 POST /api/v1/chatbot/chat/stream 이 담당합니다.
        """
        # tool_context 가 비어 있으면 여기서 동기 DB 질의와 ChromaDB 임베딩 검색이
        # 일어납니다. SSE 제너레이터는 이벤트 루프에서 돌므로 스레드로 넘깁니다.
        t_stream_start = _safe_perf_counter()
        prepared = await asyncio.to_thread(
            self._prepare_context,
            user_query,
            db=db,
            history=history,
            tool_context=tool_context,
        )
        (
            plan,
            structured_data,
            vector_docs,
            kb_status,
            provenance,
            _context_text,
            messages,
        ) = prepared

        timings = getattr(prepared, "timings", {})
        plan_ms = float(timings.get("plan_ms", 0.0))
        sql_ms = float(timings.get("sql_ms", 0.0))
        vector_ms = float(timings.get("vector_ms", 0.0))
        lexical_ms = float(timings.get("lexical_ms", 0.0))
        kb_status_ms = float(timings.get("kb_status_ms", 0.0))
        assembly_ms = float(timings.get("assembly_ms", 0.0))
        prepare_total_ms = float(timings.get("prepare_total_ms", 0.0))

        def _calc_stream_metrics(llm_ms: float, guard_ms: float) -> dict[str, float]:
            try:
                total_ms = (_safe_perf_counter() - t_stream_start) * 1000.0
                return {
                    "plan_ms": round(plan_ms, 2),
                    "sql_ms": round(sql_ms, 2),
                    "vector_ms": round(vector_ms, 2),
                    "lexical_ms": round(lexical_ms, 2),
                    "kb_status_ms": round(kb_status_ms, 2),
                    "assembly_ms": round(assembly_ms, 2),
                    "prepare_total_ms": round(prepare_total_ms, 2),
                    "llm_ms": round(llm_ms, 2),
                    "guard_ms": round(guard_ms, 2),
                    "total_ms": round(total_ms, 2),
                }
            except Exception as exc:
                logger.warning("RAG 스트림 구간 지표 계산 중 예외 발생 (무시됨): %s", exc)
                return {
                    "sql_ms": 0.0,
                    "vector_ms": 0.0,
                    "lexical_ms": 0.0,
                    "llm_ms": 0.0,
                    "total_ms": 0.0,
                }

        yield {"type": "docs", "docs": vector_docs}

        direct_result_list_answer = _build_result_list_answer(plan, structured_data)
        if direct_result_list_answer:
            citation_suffix = _build_source_citation_from_context(
                structured_data, vector_docs, kb_status
            )
            final_answer = f"{direct_result_list_answer}{citation_suffix}"
            yield {"type": "token", "text": final_answer}
            done_event = {
                "type": "done",
                "citations": [citation_suffix.strip()] if citation_suffix.strip() else [],
                "trace_id": provenance.trace_id,
                "final_answer": final_answer,
            }
            if getattr(settings, "RAG_EXPOSE_SEGMENT_METRICS", False):
                done_event["segment_metrics"] = _calc_stream_metrics(0.0, 0.0)
            yield done_event
            return

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
            done_event = {
                "type": "done",
                "citations": [citation_suffix.strip()] if citation_suffix.strip() else [],
                "trace_id": provenance.trace_id,
                "final_answer": f"{normalized}{citation_suffix}",
            }
            if getattr(settings, "RAG_EXPOSE_SEGMENT_METRICS", False):
                done_event["segment_metrics"] = _calc_stream_metrics(0.0, 0.0)
            yield done_event
            return

        try:
            raw_answer = ""
            t_llm_stream_start = _safe_perf_counter()
            token_gen = backend.stream_generate(SYSTEM_PROMPT, messages)
            while True:
                token = await asyncio.to_thread(next, token_gen, None)
                if token is None:
                    break
                raw_answer += token
                yield {"type": "token", "text": token}

            llm_stream_elapsed_ms = (_safe_perf_counter() - t_llm_stream_start) * 1000.0
            t_guard_stream_start = _safe_perf_counter()
            corrected_answer = self._apply_answer_guard(
                raw_answer,
                structured_data,
                plan,
                context_text=_context_text,
                trace_id=provenance.trace_id,
                provenance=provenance,
            )
            citation_suffix = _build_source_citation_from_context(
                structured_data, vector_docs, kb_status
            )
            guard_stream_elapsed_ms = (_safe_perf_counter() - t_guard_stream_start) * 1000.0
            final_answer = f"{corrected_answer}{citation_suffix}"
            final_citations = [citation_suffix.strip()] if citation_suffix.strip() else []

            done_event = {
                "type": "done",
                "citations": final_citations,
                "trace_id": provenance.trace_id,
                "final_answer": final_answer,
            }
            if corrected_answer != raw_answer:
                done_event["corrected_answer"] = final_answer
            if getattr(settings, "RAG_EXPOSE_SEGMENT_METRICS", False):
                done_event["segment_metrics"] = _calc_stream_metrics(
                    llm_stream_elapsed_ms, guard_stream_elapsed_ms
                )
            yield done_event
        except Exception:
            fallback_text = _fallback_answer(
                user_query, plan, structured_data, vector_docs, kb_status
            )
            normalized = _normalize_category_wording(fallback_text, plan)
            yield {"type": "token", "text": normalized}
            done_event = {
                "type": "done",
                "citations": [],
                "trace_id": provenance.trace_id,
                "final_answer": normalized,
            }
            if getattr(settings, "RAG_EXPOSE_SEGMENT_METRICS", False):
                done_event["segment_metrics"] = _calc_stream_metrics(0.0, 0.0)
            yield done_event


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


__all__ = [
    "CATEGORY_KEYWORDS",
    "KB_KEYWORDS",
    "REGION_KEYWORDS",
    "RESULT_LIST_MARKERS",
    "RESULT_QUERY_MARKERS",
    "SEMANTIC_KEYWORDS",
    "STATISTICS_KEYWORDS",
    "SYSTEM_PROMPT",
    "TREND_KEYWORDS",
    "HybridRAGEngine",
    "PreparedContext",
    "SemanticSearchResult",
    "_build_evidence_items",
    "_build_result_list_answer",
    "_build_source_citation_from_context",
    "_category_label",
    "_compose_context_text",
    "_extract_kb_snapshot",
    "_extract_semantic_snapshot",
    "_extract_statistical_snapshot",
    "_extract_trend_snapshot",
    "_fallback_answer",
    "_format_filters_for_prompt",
    "_format_result_amount",
    "_format_result_rate",
    "_markdown_result_cell",
    "_month_end",
    "_normalize_category_wording",
    "_normalize_text",
    "_normalize_tool_context",
    "_parse_time_window",
    "_parse_year_month_window",
    "_query_lower",
    "build_retrieval_plan",
    "check_numeric_omissions",
    "extract_numeric_context_values",
    "extract_result_limit",
    "get_bidding_statistics",
    "get_chatbot_response",
    "is_result_list_query",
    "rag_engine",
    "retrieve_semantic_context",
    "retrieve_structured_data",
    "search_recent_details",
]

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
import time
from collections.abc import AsyncIterator
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

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
from src.rag.vector_store import retrieve_semantic_context

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
    "목록 데이터가 컨텍스트에 있으면 검색 결과가 없다고 말하지 마세요. "
    "요청 기간에 목록이 없으면 컨텍스트 부족이라고 하지 말고, 요청 기간의 0건과 DB 최신 개찰일을 명확히 설명하세요. "
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
    documents = retrieve_semantic_context(plan)
    if not documents:
        return "최근 문맥에서 관련된 상세 문서를 찾지 못했습니다."
    top_document = documents[0].get("document") or ""
    return json.dumps(_normalize_text(top_document), ensure_ascii=False)


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

        messages = [{"role": item["role"], "content": item["text"]} for item in history or []]
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

        direct_result_list_answer = _build_result_list_answer(plan, structured_data)
        if direct_result_list_answer:
            citation_suffix = _build_source_citation_from_context(
                structured_data, vector_docs, kb_status
            )
            return _bundle(
                f"{direct_result_list_answer}{citation_suffix}",
                [citation_suffix.strip()] if citation_suffix.strip() else [],
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
        (
            plan,
            structured_data,
            vector_docs,
            kb_status,
            provenance,
            _context_text,
            messages,
        ) = await asyncio.to_thread(
            self._prepare_context,
            user_query,
            db=db,
            history=history,
            tool_context=tool_context,
        )

        yield {"type": "docs", "docs": vector_docs}

        direct_result_list_answer = _build_result_list_answer(plan, structured_data)
        if direct_result_list_answer:
            citation_suffix = _build_source_citation_from_context(
                structured_data, vector_docs, kb_status
            )
            final_answer = f"{direct_result_list_answer}{citation_suffix}"
            yield {"type": "token", "text": final_answer}
            yield {
                "type": "done",
                "citations": [citation_suffix.strip()] if citation_suffix.strip() else [],
                "trace_id": provenance.trace_id,
                "final_answer": final_answer,
            }
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
            yield {
                "type": "done",
                "citations": [citation_suffix.strip()] if citation_suffix.strip() else [],
                "trace_id": provenance.trace_id,
                "final_answer": f"{normalized}{citation_suffix}",
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
                "final_answer": final_answer,
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
                "final_answer": normalized,
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
    "extract_result_limit",
    "get_bidding_statistics",
    "get_chatbot_response",
    "is_result_list_query",
    "rag_engine",
    "retrieve_semantic_context",
    "retrieve_structured_data",
    "search_recent_details",
]

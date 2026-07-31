"""
src/rag/engine.py

하이브리드 RAG 엔진 (원본 bid_box chatbot/services/rag_engine.py FastAPI 이식).
"""

from __future__ import annotations

import asyncio
import os
import time
import unicodedata
from datetime import date, timedelta
from typing import Any, AsyncIterator, Optional

from sqlalchemy.orm import Session

from src.app.core.config import settings
from src.rag.schemas import AnswerBundle, RetrievalPlan
from src.rag.structured_data import retrieve_structured_data
from src.rag.vector_store import vector_store

STATISTICS_KEYWORDS = ("통계", "평균", "추세", "비교", "건수", "낙찰률", "경쟁률", "집계", "흐름", "변화")
SEMANTIC_KEYWORDS = ("사례", "상세", "특징", "문맥", "위험", "리스크", "어떤", "왜", "의미")
KB_KEYWORDS = ("kb", "지식베이스", "벡터", "임베딩", "인덱스")
CATEGORY_KEYWORDS = {"공사": "Cnstwk", "물품": "Thng", "용역": "Servc", "외자": "Frgcpt"}
REGION_KEYWORDS = (
    "서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종",
    "경기", "강원", "충북", "충남", "전북", "전남", "경북", "경남", "제주",
)
TREND_KEYWORDS = ("추세", "흐름", "변화")


def _normalize_text(value: str | None) -> str:
    return unicodedata.normalize("NFC", (value or "").strip())


def _query_lower(query: str) -> str:
    return _normalize_text(query).lower()


def _parse_time_window(query: str) -> tuple[str, str, str]:
    lowered = _query_lower(query)
    today = date.today()

    if "최근" in lowered or "요즘" in lowered:
        start = (today - timedelta(days=6)).isoformat()
        return start, today.isoformat(), "recent"
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

    route_parts = []
    if use_sql:
        route_parts.append("정형 통계 질의")
    if use_vector:
        route_parts.append("문맥/의미 질의")
    if use_kb_status:
        route_parts.append("KB 상태 질의")

    plan = RetrievalPlan(
        use_sql=use_sql,
        use_vector=use_vector,
        use_kb_status=use_kb_status,
        filters=filters,
        semantic_query=normalized_query,
        top_k=5 if use_vector else 3,
        time_bias=time_bias,
        route_reason=", ".join(route_parts) or "기본 벡터 질의",
    )
    return plan


def _fallback_answer(
    query: str,
    plan: RetrievalPlan,
    structured_data: dict | None,
    vector_docs: list[dict],
) -> str:
    lines = [f"질문: {query}"]
    summary = (structured_data or {}).get("summary") or {}
    if summary:
        lines.append(
            f"- 낙찰 결과 {summary.get('total_bids', 0)}건, 공고 {summary.get('announcement_count', 0)}건, "
            f"평균 낙찰률 {summary.get('average_winning_rate', 0)}"
        )
    if vector_docs:
        snippet = _normalize_text(str(vector_docs[0].get("content") or vector_docs[0].get("document") or ""))
        if len(snippet) > 200:
            snippet = f"{snippet[:200]}..."
        lines.append(f"- 문맥 참고: {snippet}")
    if plan.insufficiency_hints:
        lines.append("- 한계: " + " / ".join(plan.insufficiency_hints))
    return "\n".join(lines)


def _compose_context_text(
    plan: RetrievalPlan,
    structured_data: dict | None,
    vector_docs: list[dict],
) -> str:
    sections = [f"검색 라우팅: {plan.route_reason}"]
    if structured_data:
        summary = structured_data.get("summary") or {}
        sections.append(
            "Source [1] (통계/수치):\n"
            f"- 낙찰 결과 수: {summary.get('total_bids', 0)}\n"
            f"- 공고 수: {summary.get('announcement_count', 0)}\n"
            f"- 평균 낙찰률: {summary.get('average_winning_rate', 0)}"
        )
    if vector_docs:
        semantic_lines = ["문맥 검색 결과:"]
        for i, item in enumerate(vector_docs[:3], start=3):
            snippet = _normalize_text(str(item.get("content") or item.get("document") or ""))
            if len(snippet) > 220:
                snippet = f"{snippet[:220]}..."
            semantic_lines.append(f"Source [{i}]: {snippet}")
        sections.append("\n".join(semantic_lines))
    return "\n\n".join(sections)


class HybridRAGEngine:
    def __init__(self):
        self.client = None
        api_key = settings.GEMINI_API_KEY or os.getenv("GEMINI_API_KEY", "")
        if api_key:
            try:
                from google import genai

                self.client = genai.Client(api_key=api_key)
            except ImportError:
                print("[RAG] google-genai 미설치 - fallback 모드")

    async def get_answer(self, user_query: str, db: Optional[Session] = None) -> AnswerBundle:
        start = time.time()
        plan = build_retrieval_plan(user_query)
        structured_data = None
        vector_docs: list[dict] = []

        if plan.use_sql and db is not None:
            structured_data = await asyncio.to_thread(retrieve_structured_data, db, plan)
            plan.insufficiency_hints.extend(structured_data.get("insufficiency_hints") or [])

        if plan.use_vector:
            vector_docs = await vector_store.search_similar_docs(plan.semantic_query, top_k=plan.top_k)

        if self.client:
            context_text = _compose_context_text(plan, structured_data, vector_docs)
            system_prompt = (
                "당신은 BIDBOX의 전문 입찰 분석 어시스턴트입니다. "
                "제공된 검색 컨텍스트를 기반으로 한국어로 답변하세요."
            )
            try:
                from google.genai import types

                response = await asyncio.to_thread(
                    self.client.models.generate_content,
                    model="gemini-2.0-flash",
                    contents=[
                        types.Content(role="user", parts=[types.Part.from_text(text=f"검색 컨텍스트:\n{context_text}")]),
                        types.Content(role="user", parts=[types.Part.from_text(text=_normalize_text(user_query))]),
                    ],
                    config=types.GenerateContentConfig(system_instruction=system_prompt),
                )
                answer_text = response.text or _fallback_answer(user_query, plan, structured_data, vector_docs)
            except Exception:
                answer_text = _fallback_answer(user_query, plan, structured_data, vector_docs)
        else:
            answer_text = _fallback_answer(user_query, plan, structured_data, vector_docs)

        latency_ms = (time.time() - start) * 1000.0
        return AnswerBundle(
            answer=answer_text,
            retrieved_docs=vector_docs,
            route_reason=plan.route_reason,
            latency_ms=latency_ms,
        )

    async def stream_tokens(self, user_query: str, db: Optional[Session] = None) -> AsyncIterator[dict[str, Any]]:
        bundle = await self.get_answer(user_query, db=db)
        yield {"type": "docs", "docs": bundle.retrieved_docs}
        chunk_size = 40
        text = bundle.answer
        for i in range(0, len(text), chunk_size):
            yield {"type": "token", "text": text[i : i + chunk_size]}
            await asyncio.sleep(0.05)
        yield {"type": "done"}


rag_engine = HybridRAGEngine()

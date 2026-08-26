"""
src/rag/vector_store.py

ChromaDB 검색 래퍼 (원본 rag_engine.retrieve_semantic_context 이식 + 비동기 래퍼).
컬렉션명(bidding_kb)과 반환 스키마(document/metadata/distance)를 원본과 동일하게 유지합니다.
"""

from __future__ import annotations

import asyncio
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

from src.app.core.config import PROJECT_ROOT, settings
from src.rag.embeddings import get_collection
from src.rag.query_planning import is_result_query
from src.rag.schemas import DEFAULT_VECTOR_TOP_K, RetrievalPlan

logger = logging.getLogger(__name__)

DEFAULT_COLLECTION = "bidding_kb"

# bidding_kb 메타데이터에서 ChromaDB where 절로 표현 가능한 필드
SUPPORTED_METADATA_KEYS = frozenset({"category", "has_result", "type", "id", "doc_hash", "fmt"})

# Chroma 검색 후 본문 파싱으로 post-filter 적용 가능한 필터 키
POST_FILTER_KEYS = frozenset({"institution_name", "date_from", "date_to"})

# post-filter 적용 시 top_k 보충을 위해 검색 단계에서 추가로 가져올 배수
POST_FILTER_FETCH_MULTIPLIER = 3


@dataclass
class SemanticSearchResult:
    ok: bool
    documents: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    relaxed: bool = False
    original_filters: dict[str, Any] = field(default_factory=dict)
    effective_filters: dict[str, Any] = field(default_factory=dict)
    unsupported_filters: dict[str, Any] = field(default_factory=dict)
    applied_post_filters: dict[str, Any] = field(default_factory=dict)
    post_filtered_count: int = 0

    @property
    def filter_relaxed(self) -> bool:
        return self.relaxed

    def as_filter_provenance(self) -> dict[str, Any]:
        """필터 원본·유효·지원 불가·완화 상태 및 post-filter 적용 상태를 복원 가능한 딕셔너리로 노출합니다."""
        return {
            "original_filters": dict(self.original_filters),
            "effective_filters": dict(self.effective_filters),
            "unsupported_filters": dict(self.unsupported_filters),
            "filter_relaxed": self.filter_relaxed,
            "applied_post_filters": dict(self.applied_post_filters),
            "post_filtered_count": self.post_filtered_count,
        }


def _normalize_text(value: str | None) -> str:
    return unicodedata.normalize("NFC", (value or "").strip())


# 문서 본문 대괄호 키 파싱 정규식
INSTITUTION_PATTERN = re.compile(r"\[수요기관\]\s*([^\r\n]+)")
NOTICE_DATE_PATTERN = re.compile(r"\[공고일시\]\s*([^\r\n]+)")
OPENING_DATE_PATTERN = re.compile(r"\[개찰일시\]\s*([^\r\n]+)")
DATE_ISO_PATTERN = re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})")


def _parse_iso_date(value: str | None) -> date | None:
    """문자열에서 YYYY-MM-DD 형식의 날짜를 파싱합니다.
    파싱 실패 시 예외 없이 None 을 반환합니다.
    """
    if not value:
        return None
    try:
        match = DATE_ISO_PATTERN.search(str(value).strip())
        if match:
            year, month, day = (int(g) for g in match.groups())
            return date(year, month, day)
    except Exception:
        return None
    return None


def extract_document_institution(document_text: str | None) -> str | None:
    """문서 본문에서 [수요기관] 값을 추출합니다.
    형식이 다르거나 없으면 예외 없이 None 을 반환합니다.
    """
    if not document_text:
        return None
    try:
        match = INSTITUTION_PATTERN.search(str(document_text))
        if match:
            val = _normalize_text(match.group(1))
            return val if val else None
    except Exception:
        return None
    return None


def extract_document_dates(document_text: str | None) -> tuple[date | None, date | None]:
    """문서 본문에서 [공고일시], [개찰일시]를 추출하여 (공고일시, 개찰일시) date 튜플로 반환합니다.
    각 항목이 없거나 파싱 불가하면 None 을 반환합니다.
    """
    if not document_text:
        return None, None
    notice_date: date | None = None
    opening_date: date | None = None
    text_str = str(document_text)
    try:
        n_match = NOTICE_DATE_PATTERN.search(text_str)
        if n_match:
            notice_date = _parse_iso_date(n_match.group(1))
    except Exception:
        notice_date = None

    try:
        o_match = OPENING_DATE_PATTERN.search(text_str)
        if o_match:
            opening_date = _parse_iso_date(o_match.group(1))
    except Exception:
        opening_date = None

    return notice_date, opening_date


def extract_effective_document_date(document_text: str | None) -> date | None:
    """날짜 비교 기준: 개찰일시가 있으면 개찰일시, 없으면 공고일시.
    어느 쪽도 파싱되지 않으면 None 을 반환합니다.
    """
    notice_date, opening_date = extract_document_dates(document_text)
    if opening_date is not None:
        return opening_date
    return notice_date


def _parse_filter_date(value: Any) -> date | None:
    """필터에 전달된 날짜 값을 date 객체로 파싱합니다."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return _parse_iso_date(value)
    return None


def _matches_post_filters(
    doc_text: str,
    target_institution: str | None,
    filter_date_from: date | None,
    filter_date_to: date | None,
) -> bool:
    """단일 문서 본문이 post-filter(기관명, 기간) 조건을 만족하는지 판정합니다.
    파싱 실패 시 조건을 만족하지 않는 것으로 보고 제외(fail-closed)합니다.
    """
    # 1. 수요기관 필터 (부분 문자열 포함, fail-closed)
    if target_institution:
        doc_inst = extract_document_institution(doc_text)
        if not doc_inst:
            return False
        if target_institution not in _normalize_text(doc_inst):
            return False

    # 2. 날짜 필터 (date_from 이상, date_to 이하, fail-closed)
    if filter_date_from is not None or filter_date_to is not None:
        doc_date = extract_effective_document_date(doc_text)
        if doc_date is None:
            return False
        if filter_date_from is not None and doc_date < filter_date_from:
            return False
        if filter_date_to is not None and doc_date > filter_date_to:
            return False

    return True


def build_vector_where(
    plan_or_filters: RetrievalPlan | dict[str, Any] | None = None,
    query: str | None = None,
    *,
    filters: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """RetrievalPlan 또는 필터 딕셔너리를 ChromaDB where 절 문법으로 변환합니다.

    - bidding_kb 메타데이터로 표현 가능한 키(category 등)만 where 절에 포함합니다.
    - 날짜(date_from/date_to), 기관명(institution_name) 등 메타데이터에 없는 필터는
      조용히 누락되지 않도록 디버그/추적 로그를 남기고 where 절에서 제외합니다.
    - 낙찰 결과를 묻는 질의이거나 필터에 has_result 가 지정된 경우 has_result 조건을 반영합니다.
    - 조건이 2개 이상이면 ChromaDB 표준인 {"$and": [...]} 로 결합합니다.
    """
    if isinstance(plan_or_filters, RetrievalPlan):
        raw_filters = dict(plan_or_filters.filters or {})
        effective_query = query if query is not None else plan_or_filters.semantic_query
    elif isinstance(plan_or_filters, dict):
        raw_filters = dict(plan_or_filters)
        effective_query = query or ""
    elif filters is not None:
        raw_filters = dict(filters)
        effective_query = query or ""
    else:
        raw_filters = {}
        effective_query = query or ""

    # 메타데이터로 표현 불가능한 키 기록
    unsupported_keys = [k for k in raw_filters if k not in SUPPORTED_METADATA_KEYS]
    if unsupported_keys:
        logger.debug(
            "ChromaDB bidding_kb 메타데이터에 없어 where 절에서 제외된 필터: %s (전체 필터=%s)",
            unsupported_keys,
            raw_filters,
        )

    conditions: list[dict[str, Any]] = []

    # 1. category 필터
    if raw_filters.get("category"):
        category_val = str(raw_filters["category"]).strip()
        if category_val:
            conditions.append({"category": category_val})

    # 2. has_result 필터 (명시적 필터 또는 질의 신호)
    if "has_result" in raw_filters and raw_filters["has_result"] is not None:
        conditions.append({"has_result": bool(raw_filters["has_result"])})
    elif effective_query and is_result_query(effective_query):
        conditions.append({"has_result": True})

    # 3. 기타 지원 메타데이터 키 (type, id 등)
    if raw_filters.get("type"):
        conditions.append({"type": str(raw_filters["type"])})
    if raw_filters.get("id") is not None:
        conditions.append({"id": raw_filters["id"]})

    if not conditions:
        return None
    if len(conditions) == 1:
        return conditions[0]
    return {"$and": conditions}


def retrieve_semantic_context(plan: RetrievalPlan) -> SemanticSearchResult:
    """원본 rag_engine.retrieve_semantic_context 와 동일한 동기 검색 경로.

    where 절 필터링 및 검색 후 post-filter(기간, 기관명)를 적용하며, 필터 검색
    결과가 0건이면 필터를 해제한 재검색으로 다른 문서를 반환하지 않고 빈
    결과(empty success)로 처리합니다(fail-closed).
    반환 오류와 빈 결과를 구분하도록 ok/error 필드로 상태를 남기고, 원본·유효·지원
    불가 필터, post-filter 적용 현황과 완화 여부를 SemanticSearchResult 에 기록해
    상위 계층이 provenance 로 전달할 수 있게 합니다.
    """
    semantic_query = _normalize_text(plan.semantic_query)
    if not semantic_query:
        return SemanticSearchResult(ok=True, documents=[], error=None, relaxed=False)

    original_filters = dict(plan.filters or {})
    where = build_vector_where(plan)
    unsupported_filters = {
        key: value for key, value in original_filters.items() if key not in SUPPORTED_METADATA_KEYS
    }

    # post-filter 대상 키 식별
    applied_post_filters: dict[str, Any] = {}
    target_institution: str | None = None
    if "institution_name" in original_filters and original_filters["institution_name"] is not None:
        inst_val = _normalize_text(str(original_filters["institution_name"]))
        if inst_val:
            applied_post_filters["institution_name"] = original_filters["institution_name"]
            target_institution = inst_val

    filter_date_from: date | None = None
    if "date_from" in original_filters and original_filters["date_from"] is not None:
        parsed_from = _parse_filter_date(original_filters["date_from"])
        if parsed_from is not None:
            applied_post_filters["date_from"] = original_filters["date_from"]
            filter_date_from = parsed_from

    filter_date_to: date | None = None
    if "date_to" in original_filters and original_filters["date_to"] is not None:
        parsed_to = _parse_filter_date(original_filters["date_to"])
        if parsed_to is not None:
            applied_post_filters["date_to"] = original_filters["date_to"]
            filter_date_to = parsed_to

    has_post_filter = bool(applied_post_filters)
    query_top_k = (
        max(int(plan.top_k or DEFAULT_VECTOR_TOP_K), 1) * POST_FILTER_FETCH_MULTIPLIER
        if has_post_filter
        else max(int(plan.top_k or DEFAULT_VECTOR_TOP_K), 1)
    )

    try:
        import chromadb

        client = chromadb.PersistentClient(path=str(settings.CHROMA_DB_PATH))
        # 색인과 같은 임베딩 함수로 열어야 합니다. 그냥 get_collection 을 부르면
        # ChromaDB 가 기본 함수를 끼워 넣어, 실패 없이 결과만 엉뚱해집니다.
        collection = get_collection(client, DEFAULT_COLLECTION)

        if where is not None:
            results = collection.query(
                query_texts=[semantic_query],
                n_results=query_top_k,
                where=where,
            )
            raw_docs = (results.get("documents") or [[]])[0] if results else []
            if not raw_docs:
                logger.info(
                    "ChromaDB 필터 적용 결과 0건 (where=%s, query=%s) — 필터 해제 재검색 없이 빈 결과로 처리",
                    where,
                    semantic_query,
                )
        else:
            results = collection.query(query_texts=[semantic_query], n_results=query_top_k)

    except Exception as exc:
        # 오류 문구를 문서로 돌려주면 안 됩니다. 그 문자열이 그대로 LLM 프롬프트에
        # 실려 검색이 성공한 것처럼 보이고, 화면과 로그 어디에도 실패가 남지
        # 않습니다. 2026-08-05 에 ChromaDB 컬렉션 설정이 깨져 닷새 동안 챗봇이
        # 지식베이스 없이 답하고 있었는데 아무도 몰랐던 것이 이 때문입니다.
        logger.exception("ChromaDB 검색 실패 (collection=%s)", DEFAULT_COLLECTION)
        return SemanticSearchResult(
            ok=False,
            documents=[],
            error=str(exc) or exc.__class__.__name__,
            relaxed=False,
            original_filters=original_filters,
            effective_filters=where or {},
            unsupported_filters=unsupported_filters,
            applied_post_filters=applied_post_filters,
            post_filtered_count=0,
        )

    documents = (results.get("documents") or [[]])[0] if results else []
    metadatas = (results.get("metadatas") or [[]])[0] if results else []
    distances = (results.get("distances") or [[]])[0] if results else []

    structured_documents = []
    filtered_out_count = 0

    for index, document in enumerate(documents):
        normalized_document = _normalize_text(str(document))

        if has_post_filter and not _matches_post_filters(
            normalized_document,
            target_institution,
            filter_date_from,
            filter_date_to,
        ):
            filtered_out_count += 1
            continue

        structured_documents.append(
            {
                "document": normalized_document,
                "content": normalized_document,
                "metadata": metadatas[index] if index < len(metadatas) else {},
                "distance": distances[index] if index < len(distances) else None,
            }
        )

    target_top_k = max(int(plan.top_k or DEFAULT_VECTOR_TOP_K), 1)
    final_documents = structured_documents[:target_top_k]

    if has_post_filter and not final_documents and documents:
        logger.info(
            "post-filter 적용 결과 0건 (applied_post_filters=%s, query=%s, 원본 후보=%d건) — 빈 결과로 처리 (fail-closed)",
            applied_post_filters,
            semantic_query,
            len(documents),
        )

    return SemanticSearchResult(
        ok=True,
        documents=final_documents,
        error=None,
        relaxed=False,
        original_filters=original_filters,
        effective_filters=where or {},
        unsupported_filters=unsupported_filters,
        applied_post_filters=applied_post_filters,
        post_filtered_count=filtered_out_count,
    )


class AsyncVectorStore:
    """이벤트 루프를 막지 않도록 ChromaDB 조회를 스레드로 오프로드합니다."""

    def __init__(self, chroma_dir: str | Path | None = None):
        self.chroma_path = Path(chroma_dir or PROJECT_ROOT / "chroma_db")

    async def search_similar_docs(
        self,
        query: str,
        top_k: int = DEFAULT_VECTOR_TOP_K,
        filters: dict[str, Any] | None = None,
    ) -> SemanticSearchResult:
        plan = RetrievalPlan(
            use_vector=True,
            semantic_query=query,
            top_k=max(int(top_k or DEFAULT_VECTOR_TOP_K), 1),
            filters=filters or {},
        )
        return await asyncio.to_thread(retrieve_semantic_context, plan)


vector_store = AsyncVectorStore()

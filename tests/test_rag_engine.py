"""
tests/test_rag_engine.py

원본 apps/chatbot/tests.py HybridRAGStructuredDataTests 이식.
 - _normalize_category_wording: 내부 카테고리 코드 숨김
 - build_kb_status_summary: KB 상태 요약 문구
 - _build_evidence_items: 근거 항목 인라인 인용 번호
"""

import logging
from datetime import datetime, timedelta

import pytest

from src.app.core.timeutil import utcnow
from src.app.models.bids import BidAnnouncement, BidResult
from src.app.services.tools.kb_status_tool import build_kb_status_summary
from src.rag.engine import (
    SYSTEM_PROMPT,
    PreparedContext,
    _build_evidence_items,
    _build_result_list_answer,
    _normalize_category_wording,
    build_retrieval_plan,
    check_numeric_omissions,
    extract_numeric_context_values,
    rag_engine,
)
from src.rag.schemas import Provenance, RetrievalPlan
from src.rag.structured_data import retrieve_structured_data
from src.rag.vector_store import SemanticSearchResult


class _FakeStreamingBackend:
    name = "fake"

    def available(self):
        return True

    def generate(self, system_prompt, messages):
        return "동기 답변"

    def stream_generate(self, system_prompt, messages):
        yield "안녕"
        yield "하세요"
        yield "입니다"


def test_category_wording_hides_internal_service_code():
    plan = RetrievalPlan(use_sql=True, filters={"category": "Servc"})
    answer = _normalize_category_wording(
        "서비스(Servc) 분야와 서비스 공고를 분석했습니다.",
        plan,
    )
    assert "용역 분야" in answer
    assert "용역 공고" in answer
    assert "서비스(Servc)" not in answer
    assert "Servc" not in answer


def test_result_list_answer_uses_structured_rows_without_llm():
    plan = build_retrieval_plan("최근 낙찰된 용역 사업 2개만 리스트")
    answer = _build_result_list_answer(
        plan,
        {
            "filters": {"category_label": "용역"},
            "summary": {
                "recent_results": [
                    {
                        "bid_ntce_no": "SERVC-001",
                        "bid_ntce_nm": "용역 목록 테스트",
                        "dminstt_nm": "테스트 기관",
                        "bidwinnr_nm": "테스트 업체",
                        "sucsf_bid_amt": 1000000,
                        "sucsf_bid_rate": 98.1234,
                        "rl_openg_dt": "2026-08-03 11:00:00",
                    }
                ]
            },
        },
    )

    assert "용역 낙찰 결과 1건" in answer
    assert "SERVC-001" in answer
    assert "98.1234%" in answer


def test_kb_status_summary_explains_source_bid_count_meaning():
    summary = build_kb_status_summary(
        {
            "status": "ready",
            "kb_version": "bidding_kb",
            "source_bid_count": 10,
            "last_embedding_at": "2026-04-30T03:36:15+00:00",
        }
    )
    assert "색인된 원본 문서 수" in summary
    assert "답변에서 분석한 공고 수가 아니라" in summary
    assert "반영 공고 수" not in summary


def test_evidence_items_include_inline_citation_numbers():
    items = _build_evidence_items(
        {
            "filters": {"category": "Servc"},
            "summary": {
                "sample_announcements": [
                    {"bid_ntce_no": "R26BK01498991", "bid_ntce_nm": "테스트 공고"}
                ]
            },
            "trend_analysis": {"direction": "up"},
        },
        [{"document": "위험 사례 문맥", "metadata": {"doc_id": "risk-001"}}],
        {"status": "ready", "source_bid_count": 10},
    )
    by_id = {item.id: item for item in items}
    assert by_id["sql_summary"].metadata["citation_number"] == 1
    assert by_id["bid_R26BK01498991"].metadata["citation_number"] == 1


@pytest.mark.asyncio
async def test_stream_tokens_uses_backend_stream_generate():
    rag_engine._backend = _FakeStreamingBackend()
    rag_engine._backend_resolved = True

    events = []
    async for event in rag_engine.stream_tokens("테스트 질문"):
        events.append(event)

    assert events[0]["type"] == "docs"
    tokens = [e["text"] for e in events if e["type"] == "token"]
    assert tokens == ["안녕", "하세요", "입니다"]
    assert events[-1]["type"] == "done"
    assert "trace_id" in events[-1]


class _DenyingStreamingBackend(_FakeStreamingBackend):
    """데이터가 있는데도 없다고 답하는 백엔드."""

    def stream_generate(self, system_prompt, messages):
        yield "관련 "
        yield "데이터가 없습니다"


@pytest.mark.asyncio
async def test_stream_tokens_reports_answer_guard_correction():
    """token 이벤트는 원문이므로 교정 결과가 done 에 실려야 합니다.

    이 필드가 사라지면 Answer Guard 가 스트리밍 경로에서 무력해집니다.
    데이터가 있는데 "데이터가 없습니다" 라고 답한 원문이 화면에 남습니다.
    """
    rag_engine._backend = _DenyingStreamingBackend()
    rag_engine._backend_resolved = True

    tool_context = {
        "tool_results": {
            "bid_query": {"result": {"summary": {"total_bids": 12, "announcement_count": 5}}},
        },
    }

    events = []
    async for event in rag_engine.stream_tokens("테스트 질문", tool_context=tool_context):
        events.append(event)

    streamed = "".join(e["text"] for e in events if e["type"] == "token")
    assert "데이터가 없습니다" in streamed

    done = events[-1]
    assert "corrected_answer" in done, "교정 결과가 클라이언트에 전달되지 않습니다"
    assert "낙찰 12건" in done["corrected_answer"]
    assert "데이터가 없습니다" not in done["corrected_answer"]


# --------------------------------------------------------------------------- #
# HybridRAGStructuredDataTests (DB 기반)
# --------------------------------------------------------------------------- #


def _seed_bid_result(db, **overrides):
    defaults = {
        "bid_ntce_no": "BID-001",
        "bid_ntce_ord": "00",
        "bidwinnr_nm": "서울건설",
        "sucsf_bid_amt": 1000000,
        "sucsf_bid_rate": 98.1234,
        "rl_openg_dt": utcnow() - timedelta(days=2),
        "dminstt_nm": "서울특별시청",
        "category": "Cnstwk",
    }
    defaults.update(overrides)
    db.add(BidResult(**defaults))


def _seed_announcement(db, **overrides):
    defaults = {
        "bid_ntce_no": "ANN-001",
        "bid_ntce_ord": "000",
        "bid_ntce_nm": "서울 도로 정비 공사",
        "dminstt_nm": "서울특별시청",
        "bid_ntce_dt": utcnow() - timedelta(days=2),
        "category": "Cnstwk",
        "raw_data": None,
    }
    defaults.update(overrides)
    db.add(BidAnnouncement(**defaults))


def test_retrieve_structured_data_returns_summary_and_samples(isolated_db):
    _seed_bid_result(isolated_db)
    _seed_announcement(isolated_db)
    isolated_db.commit()

    plan = build_retrieval_plan("최근 7일 서울 공사의 낙찰률 추세를 알려줘")
    data = retrieve_structured_data(isolated_db, plan)
    assert data["summary"]["total_bids"] >= 1
    assert data["summary"]["announcement_count"] >= 1
    assert data["summary"]["sample_announcements"]
    assert data["summary"]["time_series"]


def test_retrieve_structured_data_adds_human_category_label(isolated_db):
    _seed_bid_result(isolated_db, category="Servc")
    isolated_db.commit()

    plan = RetrievalPlan(use_sql=True, filters={"category": "Servc"})
    data = retrieve_structured_data(isolated_db, plan)
    assert data["filters"]["category"] == "Servc"
    assert data["filters"]["category_label"] == "용역"


def test_retrieve_structured_data_returns_recent_result_list(isolated_db):
    _seed_bid_result(
        isolated_db,
        bid_ntce_no="SERVC-001",
        bid_ntce_nm="용역 목록 테스트",
        bidwinnr_nm="테스트 업체",
        category="Servc",
        rl_openg_dt=utcnow(),
    )
    isolated_db.commit()

    plan = RetrievalPlan(use_sql=True, filters={"category": "Servc", "result_limit": 1})
    data = retrieve_structured_data(isolated_db, plan)

    recent_results = data["summary"]["recent_results"]
    assert len(recent_results) == 1
    assert recent_results[0]["bid_ntce_no"] == "SERVC-001"
    assert recent_results[0]["category_label"] == "용역"


def test_retrieve_structured_data_reports_latest_available_date_when_window_is_empty(
    isolated_db,
):
    _seed_bid_result(
        isolated_db,
        bid_ntce_no="SERVC-OLD-001",
        bid_ntce_nm="이전 용역 결과",
        category="Servc",
        rl_openg_dt=datetime(2025, 4, 7, 15, 0),
    )
    isolated_db.commit()

    plan = RetrievalPlan(
        use_sql=True,
        filters={
            "category": "Servc",
            "date_from": "2026-07-28",
            "date_to": "2026-08-03",
            "result_limit": 5,
        },
    )
    data = retrieve_structured_data(isolated_db, plan)

    assert data["summary"]["recent_results"] == []
    assert data["summary"]["latest_available_result_at"] == "2025-04-07 15:00:00"
    assert any("최신 개찰일" in hint for hint in data["insufficiency_hints"])


def test_retrieve_structured_data_uses_daily_buckets_for_short_trend_range(isolated_db):
    now = utcnow()
    for index, days_ago in enumerate((1, 0), start=2):
        _seed_bid_result(
            isolated_db,
            bid_ntce_no=f"BID-00{index}",
            bidwinnr_nm=f"서울업체{index}",
            sucsf_bid_amt=1000000 + index,
            sucsf_bid_rate=90 + index,
            rl_openg_dt=now - timedelta(days=days_ago),
        )
    isolated_db.commit()

    plan = build_retrieval_plan("최근 7일 서울 공사의 낙찰률 추세를 알려줘")
    data = retrieve_structured_data(isolated_db, plan)
    series = data["summary"]["time_series"]
    assert len(series) >= 2
    assert all(item["period"] == "day" for item in series)
    assert all(len(item["label"]) == 10 for item in series)


@pytest.mark.asyncio
async def test_stream_tokens_prepares_context_off_loop_thread(monkeypatch):
    """컨텍스트 조회가 이벤트 루프 스레드에서 실행되지 않습니다.

    _prepare_context 는 tool_context 가 비면 동기 DB 질의와 ChromaDB 임베딩
    검색을 수행합니다. SSE 제너레이터가 루프 스레드에서 이를 수행하면 그 사이
    다른 모든 요청과 진행 중인 스트림이 함께 멈춥니다.

    판정: 오프로드된 스레드에는 실행 중인 루프가 없어
    asyncio.get_running_loop() 이 RuntimeError 를 냅니다.
    """
    import asyncio

    rag_engine._backend = _FakeStreamingBackend()
    rag_engine._backend_resolved = True

    observed: list[bool] = []
    original = rag_engine._prepare_context

    def _spy(*args, **kwargs):
        try:
            asyncio.get_running_loop()
            observed.append(True)
        except RuntimeError:
            observed.append(False)
        return original(*args, **kwargs)

    monkeypatch.setattr(rag_engine, "_prepare_context", _spy)

    async for _event in rag_engine.stream_tokens("테스트 질문"):
        pass

    assert observed == [False], "_prepare_context 가 이벤트 루프 스레드에서 실행되었습니다"


# --------------------------------------------------------------------------- #
# RAG 레이턴시 계측 및 구조화 로그 검증 테스트
# --------------------------------------------------------------------------- #


class _ErrorBackend(_FakeStreamingBackend):
    """생성 시 예외를 발생시키는 백엔드."""

    def generate(self, system_prompt, messages):
        raise RuntimeError("LLM 백엔드 연결 오류 (테스트)")


def test_prepare_context_returns_prepared_context_with_timings():
    prepared = rag_engine._prepare_context("테스트 질문")
    assert isinstance(prepared, PreparedContext)
    assert isinstance(prepared, tuple)
    assert len(prepared) == 7

    # 7개 요소 언패킹 보존 검증
    plan, _structured_data, _vector_docs, _kb_status, provenance, _context_text, messages = prepared
    assert plan is not None
    assert provenance is not None
    assert isinstance(messages, list)

    timings = prepared.timings
    assert isinstance(timings, dict)
    for key in (
        "plan_ms",
        "sql_ms",
        "vector_ms",
        "kb_status_ms",
        "assembly_ms",
        "prepare_total_ms",
    ):
        assert key in timings
        assert isinstance(timings[key], float)
        assert timings[key] >= 0.0


def test_prepare_context_timings_respects_skipped_stages():
    # tool_context 에 결과가 모두 있으면 SQL, 벡터, KB_status 조회가 실행되지 않고 0.0 으로 남아야 합니다.
    tool_context = {
        "tool_results": {
            "bid_query": {"result": {"summary": {"total_bids": 1}}},
            "semantic_search": {
                "documents": [{"document": "문맥", "metadata": {}, "distance": 0.1}]
            },
            "kb_status": {"kb_status": {"status": "ready"}},
        }
    }
    prepared = rag_engine._prepare_context("테스트 질문", tool_context=tool_context)
    timings = prepared.timings
    assert timings["sql_ms"] == 0.0
    assert timings["vector_ms"] == 0.0
    assert timings["kb_status_ms"] == 0.0
    assert timings["plan_ms"] >= 0.0
    assert timings["assembly_ms"] >= 0.0
    assert timings["prepare_total_ms"] >= 0.0


def test_prepare_context_propagates_vector_filter_provenance(monkeypatch):
    """필터 원본·유효·지원 불가·완화 상태가 Provenance 와 insufficiency_hints 로 전달되어야 합니다."""
    captured_plans: list[RetrievalPlan] = []

    def mock_retrieve(plan: RetrievalPlan) -> SemanticSearchResult:
        captured_plans.append(plan)
        return SemanticSearchResult(
            ok=True,
            documents=[],
            relaxed=False,
            original_filters={"category": "Frgcpt", "date_from": "2026-01-01"},
            effective_filters={"$and": [{"category": "Frgcpt"}, {"has_result": True}]},
            unsupported_filters={"date_from": "2026-01-01"},
        )

    monkeypatch.setattr("src.rag.engine.retrieve_semantic_context", mock_retrieve)

    prepared = rag_engine._prepare_context("희귀 특수 공사의 낙찰업체와 낙찰금액")
    plan, _structured_data, vector_docs, _kb_status, provenance, _context_text, _messages = prepared

    assert plan.use_vector is True
    assert vector_docs == []
    assert isinstance(provenance, Provenance)

    assert provenance.vector_filter_provenance is not None
    filter_prov = provenance.vector_filter_provenance
    assert filter_prov["original_filters"]["category"] == "Frgcpt"
    assert filter_prov["effective_filters"] == {
        "$and": [{"category": "Frgcpt"}, {"has_result": True}]
    }
    assert filter_prov["unsupported_filters"] == {"date_from": "2026-01-01"}
    assert filter_prov["filter_relaxed"] is False

    hint_text = "\n".join(provenance.insufficiency_hints)
    assert "지원되지 않아 적용되지 않은 필터" in hint_text
    assert "date_from" in hint_text
    assert "필터 조건에 맞는 문서가 0건" in hint_text


def test_get_answer_sync_logs_latency_success_path(caplog, monkeypatch):
    monkeypatch.setattr("src.rag.engine.settings.LATENCY_SEGMENT_LOGGING", True)
    rag_engine._backend = _FakeStreamingBackend()
    rag_engine._backend_resolved = True

    with caplog.at_level(logging.INFO, logger="src.rag.engine"):
        bundle = rag_engine.get_answer_sync("적격심사 기준 안내")

    assert bundle.answer is not None
    assert bundle.latency_ms >= 0.0

    latency_logs = [r for r in caplog.records if "rag_engine_latency:" in r.message]
    assert len(latency_logs) == 1
    log_record = latency_logs[0]
    msg = log_record.message
    assert "status=success" in msg
    assert "backend=fake" in msg
    assert "plan_ms=" in msg
    assert "sql_ms=" in msg
    assert "vector_ms=" in msg
    assert "kb_ms=" in msg
    assert "assembly_ms=" in msg
    assert "prepare_ms=" in msg
    assert "llm_ms=" in msg
    assert "guard_ms=" in msg
    assert "total_ms=" in msg


def test_get_answer_sync_logs_latency_direct_result_list(caplog, monkeypatch):
    monkeypatch.setattr("src.rag.engine.settings.LATENCY_SEGMENT_LOGGING", True)
    rag_engine._backend = _FakeStreamingBackend()
    rag_engine._backend_resolved = True

    tool_context = {
        "tool_results": {
            "bid_query": {
                "result": {
                    "filters": {"category_label": "용역"},
                    "summary": {
                        "recent_results": [
                            {
                                "bid_ntce_no": "SERVC-001",
                                "bid_ntce_nm": "용역 공고",
                                "dminstt_nm": "테스트 기관",
                                "bidwinnr_nm": "테스트 업체",
                                "sucsf_bid_amt": 1000000,
                                "sucsf_bid_rate": 98.12,
                                "rl_openg_dt": "2026-08-01 10:00:00",
                            }
                        ]
                    },
                }
            }
        }
    }

    with caplog.at_level(logging.INFO, logger="src.rag.engine"):
        bundle = rag_engine.get_answer_sync(
            "최근 낙찰된 용역 사업 1개만 리스트", tool_context=tool_context
        )

    assert "SERVC-001" in bundle.answer
    assert bundle.latency_ms >= 0.0

    latency_logs = [r for r in caplog.records if "rag_engine_latency:" in r.message]
    assert len(latency_logs) == 1
    msg = latency_logs[0].message
    assert "status=direct_result_list" in msg
    assert "llm_ms=0.00" in msg
    assert "backend=none" in msg


def test_get_answer_sync_logs_latency_fallback_no_backend(caplog, monkeypatch):
    monkeypatch.setattr("src.rag.engine.settings.LATENCY_SEGMENT_LOGGING", True)
    rag_engine._backend = None
    rag_engine._backend_resolved = True

    with caplog.at_level(logging.INFO, logger="src.rag.engine"):
        bundle = rag_engine.get_answer_sync("일반 질문입니다")

    assert bundle.answer is not None
    assert bundle.latency_ms >= 0.0

    latency_logs = [r for r in caplog.records if "rag_engine_latency:" in r.message]
    assert len(latency_logs) == 1
    msg = latency_logs[0].message
    assert "status=fallback_no_backend" in msg
    assert "llm_ms=0.00" in msg
    assert "backend=fallback" in msg


def test_get_answer_sync_logs_latency_fallback_on_exception(caplog, monkeypatch):
    monkeypatch.setattr("src.rag.engine.settings.LATENCY_SEGMENT_LOGGING", True)
    rag_engine._backend = _ErrorBackend()
    rag_engine._backend_resolved = True

    with caplog.at_level(logging.INFO, logger="src.rag.engine"):
        bundle = rag_engine.get_answer_sync("일반 질문입니다")

    assert bundle.answer is not None
    assert bundle.latency_ms >= 0.0

    latency_logs = [r for r in caplog.records if "rag_engine_latency:" in r.message]
    assert len(latency_logs) == 1
    msg = latency_logs[0].message
    assert "status=fallback_error" in msg
    assert "backend=fake" in msg


def test_latency_logs_do_not_leak_user_query_or_documents(caplog, monkeypatch):
    monkeypatch.setattr("src.rag.engine.settings.LATENCY_SEGMENT_LOGGING", True)
    rag_engine._backend = _FakeStreamingBackend()
    rag_engine._backend_resolved = True

    private_query = "CONFIDENTIAL_USER_QUERY_DATA_XYZ_999"
    with caplog.at_level(logging.INFO, logger="src.rag.engine"):
        rag_engine.get_answer_sync(private_query)

    latency_logs = [r for r in caplog.records if "rag_engine_latency:" in r.message]
    assert len(latency_logs) == 1
    record = latency_logs[0]
    assert private_query not in record.message
    for _key, value in getattr(record, "extra", {}).items():
        assert private_query not in str(value)


def test_system_prompt_refusal_instructions_unopened_and_unconfirmed():
    """미개찰·개찰 전·미확정 정보 거절 지시 및 사유 명시 지시가 SYSTEM_PROMPT에 존재해야 합니다."""
    assert "미개찰" in SYSTEM_PROMPT
    assert "개찰 전" in SYSTEM_PROMPT
    assert "미래 시점" in SYSTEM_PROMPT
    assert "예정가격" in SYSTEM_PROMPT
    assert "낙찰업체" in SYSTEM_PROMPT
    assert "낙찰금액" in SYSTEM_PROMPT
    assert "낙찰률" in SYSTEM_PROMPT
    assert "확인 불가" in SYSTEM_PROMPT
    assert "거절" in SYSTEM_PROMPT
    assert "사유" in SYSTEM_PROMPT


def test_system_prompt_refusal_exception_when_evidence_present():
    """컨텍스트에 근거가 존재할 때는 거절하지 않고 정상 답변한다는 조건이 명시되어야 합니다."""
    assert (
        "다만 제공된 검색 컨텍스트에 실제 근거가 있으면 위 거절 지시를 적용하지 말고 정상적으로 답변하세요."
    ) in SYSTEM_PROMPT


def test_system_prompt_preserves_existing_instructions_and_zero_count():
    """기존 목록 답변 지시 및 0건 설명 지시가 훼손 없이 보존되어야 합니다."""
    assert "목록 데이터가 컨텍스트에 있으면 검색 결과가 없다고 말하지 마세요." in SYSTEM_PROMPT
    assert (
        "요청 기간에 목록이 없으면 컨텍스트 부족이라고 하지 말고, "
        "요청 기간의 0건과 DB 최신 개찰일을 명확히 설명하세요."
    ) in SYSTEM_PROMPT
    assert "'최근 낙찰 결과', '낙찰된 사업 목록'처럼 개별 목록을 요청하면" in SYSTEM_PROMPT
    assert "Source [1]의 '최근 낙찰 결과 목록'을 그대로 사용하여" in SYSTEM_PROMPT


def test_system_prompt_preserves_category_wording_and_canvas_instructions():
    """분야 코드 노출 금지 및 canvas 태그 지시가 보존되어야 합니다."""
    assert (
        "분야 코드는 내부 식별자입니다. 최종 답변에는 Servc, Thng, Cnstwk, Frgcpt 같은 코드를 쓰지 말고"
    ) in SYSTEM_PROMPT
    assert "용역, 물품, 공사, 외자처럼 사용자용 분류명만 쓰세요." in SYSTEM_PROMPT
    assert "data-type='bar'" in SYSTEM_PROMPT


def test_system_prompt_mandates_both_winning_amount_and_rate_in_detail_and_comparison():
    """개별 공고 및 비교 질의에서 컨텍스트의 낙찰금액과 낙찰률을 모두 명시하도록 지시해야 합니다."""
    assert "개별 공고 질의나 여러 공고 간 비교 질의에서도" in SYSTEM_PROMPT
    assert "검색 컨텍스트에 존재하는 낙찰금액과 낙찰률" in SYSTEM_PROMPT
    assert "누락하지 말고 빠짐없이 모두 명시" in SYSTEM_PROMPT


def test_system_prompt_mandates_source_isolation_in_comparison_queries():
    """여러 공고 비교 시 각 공고의 값은 해당 공고 Source에서만 가져오고 소스 번호를 붙이도록 지시해야 합니다."""
    assert "여러 공고를 비교할 때는" in SYSTEM_PROMPT
    assert "해당 공고를 담은 Source에서만 가져오고 다른 Source의 값을 섞지 마세요" in SYSTEM_PROMPT
    assert "각 비교 항목마다 출처 소스 번호를 명확히 붙이세요" in SYSTEM_PROMPT


# --------------------------------------------------------------------------- #
# 낙찰금액·낙찰률 누락 결정론적 검출기 테스트
# --------------------------------------------------------------------------- #


def test_extract_numeric_context_values():
    """검색 컨텍스트 내 대괄호 라벨의 낙찰금액과 낙찰률을 정확히 추출해야 합니다."""
    context = (
        "Source [3] (공고 R26BK0001):\n"
        "[공고명] 2026 도로 정비 사업\n"
        "[낙찰금액] 1074000원\n"
        "[낙찰률] 90.1950%\n\n"
        "Source [4] (공고 R26BK0002):\n"
        "[공고명] 2026 하천 정비 사업\n"
        "[낙찰금액] 5,200,000\n"
        "[낙찰률] 87.745%\n"
    )
    result = extract_numeric_context_values(context)
    assert result["amounts"] == ["1074000", "5,200,000"]
    assert result["rates"] == ["90.1950", "87.745"]


def test_extract_numeric_context_values_empty_and_no_match():
    """빈 컨텍스트나 라벨이 없는 컨텍스트에서는 빈 목록 및 빈 딕셔너리를 반환해야 합니다."""
    empty_res = extract_numeric_context_values("")
    assert empty_res["amounts"] == []
    assert empty_res["rates"] == []
    assert empty_res["amount_sources"] == {}
    assert empty_res["rate_sources"] == {}

    no_match_res = extract_numeric_context_values("일반 텍스트만 있는 컨텍스트")
    assert no_match_res["amounts"] == []
    assert no_match_res["rates"] == []
    assert no_match_res["amount_sources"] == {}
    assert no_match_res["rate_sources"] == {}


def test_check_numeric_omissions_disabled_by_default(caplog):
    """설정 플래그가 꺼져 있을 때는 검출 및 로깅이 전혀 발생하지 않아야 합니다."""
    context = "[낙찰금액] 1074000원 [낙찰률] 90.1950%"
    answer = "낙찰자는 (주)테스트입니다."  # 금액과 낙찰률 모두 누락됨

    with caplog.at_level(logging.WARNING, logger="src.rag.engine"):
        res = check_numeric_omissions(context, answer, trace_id="test-trace-1")

    assert res is None
    omission_logs = [r for r in caplog.records if "rag_numeric_omission:" in r.message]
    assert len(omission_logs) == 0


def test_check_numeric_omissions_all_present(caplog, monkeypatch):
    """금액과 낙찰률이 모두 답변에 명시된 경우 누락 없음으로 판정되어야 합니다."""
    monkeypatch.setattr("src.rag.engine.settings.NUMERIC_OMISSION_DETECTION", True)

    context = "[낙찰금액] 1074000원 [낙찰률] 90.1950%"
    # 콤마 포함 금액 및 소수점 낙찰률 포함
    answer = "낙찰금액은 1,074,000원이고 낙찰률은 90.1950%입니다."

    with caplog.at_level(logging.WARNING, logger="src.rag.engine"):
        res = check_numeric_omissions(context, answer, trace_id="test-trace-2")

    assert res is not None
    assert res["omission_detected"] is False
    assert res["missing_count"] == 0
    assert res["missing_types"] == []
    omission_logs = [r for r in caplog.records if "rag_numeric_omission:" in r.message]
    assert len(omission_logs) == 0


def test_check_numeric_omissions_detects_amount_omission(caplog, monkeypatch):
    """낙찰금액만 답변에서 누락된 경우 amount 누락을 검출하고 구조화 로그를 남겨야 합니다."""
    monkeypatch.setattr("src.rag.engine.settings.NUMERIC_OMISSION_DETECTION", True)

    context = "[낙찰금액] 1074000원 [낙찰률] 90.1950%"
    answer = "낙찰률은 90.1950%로 확인되었습니다."  # 금액 누락

    with caplog.at_level(logging.WARNING, logger="src.rag.engine"):
        res = check_numeric_omissions(context, answer, trace_id="trace-amount-missing")

    assert res is not None
    assert res["omission_detected"] is True
    assert res["missing_types"] == ["amount"]
    assert res["missing_count"] == 1
    assert res["missing_amounts"] == ["1074000"]
    assert res["missing_rates"] == []

    omission_logs = [r for r in caplog.records if "rag_numeric_omission:" in r.message]
    assert len(omission_logs) == 1
    record = omission_logs[0]
    assert "missing_types=['amount']" in record.message
    assert "missing_count=1" in record.message
    assert getattr(record, "omission_detected", False) is True
    assert getattr(record, "missing_types", None) == ["amount"]


def test_check_numeric_omissions_detects_rate_omission(caplog, monkeypatch):
    """낙찰률만 답변에서 누락된 경우 rate 누락을 검출하고 구조화 로그를 남겨야 합니다."""
    monkeypatch.setattr("src.rag.engine.settings.NUMERIC_OMISSION_DETECTION", True)

    context = "[낙찰금액] 1074000원 [낙찰률] 90.1950%"
    answer = "낙찰금액은 1074000원입니다."  # 낙찰률 누락

    with caplog.at_level(logging.WARNING, logger="src.rag.engine"):
        res = check_numeric_omissions(context, answer, trace_id="trace-rate-missing")

    assert res is not None
    assert res["omission_detected"] is True
    assert res["missing_types"] == ["rate"]
    assert res["missing_count"] == 1
    assert res["missing_rates"] == ["90.1950"]
    assert res["missing_amounts"] == []


def test_check_numeric_omissions_detects_both_omissions(caplog, monkeypatch):
    """금액과 낙찰률이 모두 누락된 경우 누락 건수 2와 구조화 로그를 남겨야 합니다."""
    monkeypatch.setattr("src.rag.engine.settings.NUMERIC_OMISSION_DETECTION", True)

    context = "[낙찰금액] 1074000원 [낙찰률] 90.1950%"
    answer = "낙찰업체는 (주)한국건설입니다."  # 둘 다 누락

    with caplog.at_level(logging.WARNING, logger="src.rag.engine"):
        res = check_numeric_omissions(context, answer, trace_id="trace-both-missing")

    assert res is not None
    assert res["omission_detected"] is True
    assert set(res["missing_types"]) == {"amount", "rate"}
    assert res["missing_count"] == 2
    assert res["missing_amounts"] == ["1074000"]
    assert res["missing_rates"] == ["90.1950"]


def test_apply_answer_guard_never_mutates_answer_text_for_omission_detection(monkeypatch):
    """검출기가 동작하더라도 _apply_answer_guard는 답변 텍스트를 임의로 교정하거나 변경하지 않아야 합니다."""
    monkeypatch.setattr("src.rag.engine.settings.NUMERIC_OMISSION_DETECTION", True)

    context = "[낙찰금액] 1074000원 [낙찰률] 90.1950%"
    raw_answer = "낙찰자는 테스트업체입니다."
    plan = RetrievalPlan(use_sql=True, filters={})

    guarded = rag_engine._apply_answer_guard(
        raw_answer,
        structured_data=None,
        plan=plan,
        context_text=context,
        trace_id="test-guard-trace",
    )

    assert guarded == raw_answer, "답변 텍스트가 변경되어서는 안 됩니다."


def test_get_answer_sync_with_numeric_omission_detection(caplog, monkeypatch):
    """get_answer_sync 통합 호출 경로에서 누락 검출기가 올바르게 동작해야 합니다."""
    monkeypatch.setattr("src.rag.engine.settings.NUMERIC_OMISSION_DETECTION", True)

    class _MissingBackend:
        name = "missing_test"

        def available(self):
            return True

        def generate(self, system_prompt, messages):
            # 컨텍스트에 있는 수치 정보 대신 단순 텍스트만 생성
            return "분석 결과 낙찰업체는 테스트기업입니다."

    rag_engine._backend = _MissingBackend()
    rag_engine._backend_resolved = True

    tool_context = {
        "tool_results": {
            "semantic_search": {
                "documents": [
                    {
                        "document": "Source [3]:\n[공고명] 도로공사\n[낙찰금액] 1074000원\n[낙찰률] 90.1950%",
                        "metadata": {},
                    }
                ]
            }
        }
    }

    with caplog.at_level(logging.WARNING, logger="src.rag.engine"):
        bundle = rag_engine.get_answer_sync("도로공사 결과 알려줘", tool_context=tool_context)

    assert "분석 결과 낙찰업체는 테스트기업입니다." in bundle.answer
    omission_logs = [r for r in caplog.records if "rag_numeric_omission:" in r.message]
    assert len(omission_logs) == 1
    assert "missing_count=2" in omission_logs[0].message

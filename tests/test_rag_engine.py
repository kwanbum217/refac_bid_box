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
    PreparedContext,
    _build_evidence_items,
    _build_result_list_answer,
    _normalize_category_wording,
    build_retrieval_plan,
    rag_engine,
)
from src.rag.schemas import RetrievalPlan
from src.rag.structured_data import retrieve_structured_data


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


def test_get_answer_sync_logs_latency_success_path(caplog):
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


def test_get_answer_sync_logs_latency_direct_result_list(caplog):
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


def test_get_answer_sync_logs_latency_fallback_no_backend(caplog):
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


def test_get_answer_sync_logs_latency_fallback_on_exception(caplog):
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


def test_latency_logs_do_not_leak_user_query_or_documents(caplog):
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

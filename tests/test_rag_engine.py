"""
tests/test_rag_engine.py

원본 apps/chatbot/tests.py HybridRAGStructuredDataTests 이식.
 - _normalize_category_wording: 내부 카테고리 코드 숨김
 - build_kb_status_summary: KB 상태 요약 문구
 - _build_evidence_items: 근거 항목 인라인 인용 번호
"""

from datetime import datetime, timedelta

import pytest

from src.app.models.bids import BidAnnouncement, BidResult
from src.app.services.tools.kb_status_tool import build_kb_status_summary
from src.rag.engine import (
    _build_evidence_items,
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
        "rl_openg_dt": datetime.utcnow() - timedelta(days=2),
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
        "bid_ntce_dt": datetime.utcnow() - timedelta(days=2),
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


def test_retrieve_structured_data_uses_daily_buckets_for_short_trend_range(isolated_db):
    now = datetime.utcnow()
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

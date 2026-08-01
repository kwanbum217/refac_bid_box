"""
tests/test_rag_engine.py

원본 apps/chatbot/tests.py HybridRAGStructuredDataTests 중 순수 함수 이식.
 - _normalize_category_wording: 내부 카테고리 코드 숨김
 - build_kb_status_summary: KB 상태 요약 문구
 - _build_evidence_items: 근거 항목 인라인 인용 번호
"""

from src.rag.engine import _build_evidence_items, _normalize_category_wording
from src.rag.schemas import RetrievalPlan
from src.app.services.tools.kb_status_tool import build_kb_status_summary


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
    assert by_id["trend_analysis"].metadata["citation_number"] == 2
    assert by_id["vec_0"].metadata["citation_number"] == 3
    assert by_id["kb_meta"].metadata["citation_number"] == 6

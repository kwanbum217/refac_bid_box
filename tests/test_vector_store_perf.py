"""
tests/test_vector_store_perf.py

벡터 저장소 최적화 안전장치 및 검색 결과 출력 불변(Output Invariance) 강제 검증 테스트.

검증 항목:
1. 핵심 불변 상수 검증 (DEFAULT_CANDIDATE_POOL_SIZE=30, RERANK_MIN_TITLE_LENGTH=5, POST_FILTER_FETCH_MULTIPLIER=3)
2. 문자열 정규화 및 키 생성 출력 동일성 (_normalize_text, _normalize_match_key)
3. 날짜 추출 및 유효 날짜 판정 출력 동일성 (extract_document_dates, extract_effective_document_date)
4. post-filter 판정 출력 동일성 (_matches_post_filters)
5. 정확 공고명 재순위(_rerank_by_exact_title) 고정 30건 풀 순서 불변성 (q21 질의, 다중 일치 동점해소, 짧은 질의 조기반환, 미일치 거리보존)
6. retrieve_semantic_context 전체 경로 출력 불변성 (ChromaDB 주입 모의)
"""

from datetime import date
from typing import Any

import pytest

from src.rag.schemas import RetrievalPlan
from src.rag.vector_store import (
    DEFAULT_CANDIDATE_POOL_SIZE,
    POST_FILTER_FETCH_MULTIPLIER,
    RERANK_MIN_TITLE_LENGTH,
    _matches_post_filters,
    _normalize_match_key,
    _normalize_text,
    _rerank_by_exact_title,
    extract_document_dates,
    extract_effective_document_date,
    retrieve_semantic_context,
)

# ---------------------------------------------------------------------------
# 1. 핵심 불변 상수 검증
# ---------------------------------------------------------------------------


def test_vector_store_invariants_constants():
    """검색 결과 변경을 유발하는 핵심 상수가 변경되지 않았음을 검증합니다."""
    assert DEFAULT_CANDIDATE_POOL_SIZE == 30, (
        "DEFAULT_CANDIDATE_POOL_SIZE 가 30에서 변경되었습니다. q21 정답 누락 회귀 방지를 위해 30을 유지해야 합니다."
    )
    assert RERANK_MIN_TITLE_LENGTH == 5, (
        "RERANK_MIN_TITLE_LENGTH 가 5에서 변경되었습니다. 단어 오탐 방지를 위해 5를 유지해야 합니다."
    )
    assert POST_FILTER_FETCH_MULTIPLIER == 3, (
        "POST_FILTER_FETCH_MULTIPLIER 가 3에서 변경되었습니다."
    )


# ---------------------------------------------------------------------------
# 2. 문자열 및 매칭 키 정규화 출력 불변성 검증
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw_input,expected",
    [
        (None, ""),
        ("", ""),
        ("   ", ""),
        ("\t\n", ""),
        ("일반 문자열", "일반 문자열"),
        ("  앞뒤 공백 제거  ", "앞뒤 공백 제거"),
        ("가\u1100\u1161", "가가"),  # NFD 분해된 한글 결합
    ],
)
def test_normalize_text_invariance(raw_input: str | None, expected: str):
    """_normalize_text 의 출력이 기대값과 정확히 일치함을 확인합니다."""
    assert _normalize_text(raw_input) == expected


@pytest.mark.parametrize(
    "raw_input,expected",
    [
        (None, ""),
        ("", ""),
        ("   ", ""),
        ("2026년 조림지 풀베기사업 2차(동부지구)", "2026년조림지풀베기사업2차(동부지구)"),
        ("2026년 조림지 풀베기사업 2차 [동부지구]", "2026년조림지풀베기사업2차(동부지구)"),
        ("2026년 조림지 풀베기사업 2차 {동부지구}", "2026년조림지풀베기사업2차(동부지구)"),
        ("2026년 조림지 풀베기사업 2차【동부지구】", "2026년조림지풀베기사업2차(동부지구)"),
        ("공사 (1차) 사업", "공사(1차)사업"),
        ("공사 1차 사업", "공사1차사업"),
    ],
)
def test_normalize_match_key_invariance(raw_input: str | None, expected: str):
    """_normalize_match_key 의 괄호 표준화 및 공백 제거가 정확히 동작함을 확인합니다."""
    assert _normalize_match_key(raw_input) == expected


# ---------------------------------------------------------------------------
# 3. 날짜 추출 및 유효 날짜 판정 출력 불변성 검증
# ---------------------------------------------------------------------------


def test_extract_document_dates_and_effective_date_invariance():
    """개찰일시 우선 및 공고일시 폴백 유효 날짜 판정이 정확함을 확인합니다."""
    # 개찰일시와 공고일시가 둘 다 있는 경우 -> 개찰일시 반환
    text_both = "[공고명] 시험 공고\n[공고일시] 2026-08-01 10:00:00\n[개찰일시] 2026-08-10 14:00:00"
    n_date, o_date = extract_document_dates(text_both)
    assert n_date == date(2026, 8, 1)
    assert o_date == date(2026, 8, 10)
    assert extract_effective_document_date(text_both) == date(2026, 8, 10)

    # 공고일시만 있는 경우 -> 공고일시 반환
    text_notice_only = "[공고명] 시험 공고\n[공고일시] 2026-08-05 09:00:00"
    n_date2, o_date2 = extract_document_dates(text_notice_only)
    assert n_date2 == date(2026, 8, 5)
    assert o_date2 is None
    assert extract_effective_document_date(text_notice_only) == date(2026, 8, 5)

    # 개찰일시만 있는 경우 -> 개찰일시 반환
    text_opening_only = "[공고명] 시험 공고\n[개찰일시] 2026-08-15 11:00:00"
    n_date3, o_date3 = extract_document_dates(text_opening_only)
    assert n_date3 is None
    assert o_date3 == date(2026, 8, 15)
    assert extract_effective_document_date(text_opening_only) == date(2026, 8, 15)

    # 둘 다 없는 경우 -> None 반환
    text_none = "[공고명] 날짜 없는 공고"
    assert extract_effective_document_date(text_none) is None
    assert extract_effective_document_date(None) is None


# ---------------------------------------------------------------------------
# 4. Post-filter 판정 출력 불변성 검증
# ---------------------------------------------------------------------------


def test_matches_post_filters_invariance():
    """_matches_post_filters 의 기관명 및 기간 필터 판정이 정확함을 확인합니다."""
    doc_valid = (
        "[공고명] 도로포장 공사\n"
        "[수요기관] 경상남도 거제시청\n"
        "[공고일시] 2026-08-10 10:00:00\n"
        "[개찰일시] 2026-08-20 14:00:00"
    )

    # 기관명 매칭 성공
    assert _matches_post_filters(
        doc_valid,
        target_institution="거제시",
        filter_date_from=date(2026, 8, 1),
        filter_date_to=date(2026, 8, 31),
    )

    # 기관명 불일치 -> False
    assert not _matches_post_filters(
        doc_valid,
        target_institution="서울시",
        filter_date_from=date(2026, 8, 1),
        filter_date_to=date(2026, 8, 31),
    )

    # 기간 이전 탈락 -> False
    assert not _matches_post_filters(
        doc_valid,
        target_institution="거제시",
        filter_date_from=date(2026, 8, 25),
        filter_date_to=date(2026, 8, 31),
    )

    # 기간 이후 탈락 -> False
    assert not _matches_post_filters(
        doc_valid,
        target_institution="거제시",
        filter_date_from=date(2026, 8, 1),
        filter_date_to=date(2026, 8, 15),
    )


# ---------------------------------------------------------------------------
# 5. 고정 30건 후보 풀 대상 _rerank_by_exact_title 순서 불변성 검증
# ---------------------------------------------------------------------------


def _generate_30_mock_documents() -> list[dict[str, Any]]:
    """ChromaDB 에서 반환되는 전형적인 30건 후보 문서 풀을 생성합니다."""
    docs = []
    for i in range(1, 31):
        if i == 9:
            # q21 대상 문서 (9위에 위치)
            title = "2026년 조림지 풀베기사업 2차(동부지구)"
            notice_dt = "2026-08-13 20:01:17"
            opening_dt = "2026-08-20 10:00:00"
        elif i == 15:
            # 과거 연도 동일 공고명 (동점 해소용)
            title = "2026년 조림지 풀베기사업 2차(동부지구)"
            notice_dt = "2025-08-10 10:00:00"
            opening_dt = "2025-08-18 10:00:00"
        else:
            title = f"산림 정비 사업 제{i}구구 공사"
            notice_dt = f"2026-08-{i:02d} 09:00:00"
            opening_dt = f"2026-08-{(i + 5):02d} 10:00:00"

        doc_text = (
            f"[공고명] {title}\n"
            f"[수요기관] 테스트기관_{i:02d}\n"
            f"[공고일시] {notice_dt}\n"
            f"[개찰일시] {opening_dt}"
        )
        docs.append(
            {
                "id": f"bid_100000{i:02d}",
                "document": doc_text,
                "content": doc_text,
                "metadata": {
                    "bid_ntce_no": f"20260800{i:02d}",
                    "bid_ntce_nm": title,
                    "bid_ntce_dt": notice_dt,
                    "rl_openg_dt": opening_dt,
                },
                "distance": 0.20 + (i * 0.01),
            }
        )
    return docs


def test_rerank_30_candidates_q21_exact_match_order_invariance():
    """q21 질의에서 30건 후보 풀 중 9위(2026년)와 15위(2025년)가 1, 2위로 승격되고 최신순으로 정렬됨을 검증합니다."""
    candidates = _generate_30_mock_documents()
    query = "2026년 조림지 풀베기사업 2차(동부지구)의 공고번호, 수요기관, 낙찰금액을 알려줘"

    reranked = _rerank_by_exact_title(candidates, query)

    assert len(reranked) == 30
    # 1위: 9위였던 2026년 공고
    assert reranked[0]["id"] == "bid_10000009"
    assert reranked[0]["metadata"]["bid_ntce_nm"] == "2026년 조림지 풀베기사업 2차(동부지구)"
    assert reranked[0]["metadata"]["bid_ntce_dt"] == "2026-08-13 20:01:17"

    # 2위: 15위였던 2025년 공고 (동점 해소로 과거 공고가 2위)
    assert reranked[1]["id"] == "bid_10000015"
    assert reranked[1]["metadata"]["bid_ntce_nm"] == "2026년 조림지 풀베기사업 2차(동부지구)"
    assert reranked[1]["metadata"]["bid_ntce_dt"] == "2025-08-10 10:00:00"

    # 나머지 28개 문서는 기존 거리 순서 보존
    expected_remaining_ids = [
        c["id"] for c in candidates if c["id"] not in ("bid_10000009", "bid_10000015")
    ]
    actual_remaining_ids = [r["id"] for r in reranked[2:]]
    assert actual_remaining_ids == expected_remaining_ids


def test_rerank_short_query_fast_path_invariance():
    """질의 길이가 RERANK_MIN_TITLE_LENGTH(5자) 미만일 때 원본 30건 순서가 100% 보존됨을 확인합니다."""
    candidates = _generate_30_mock_documents()
    short_query = "공사"  # 2자 (5자 미만)

    reranked = _rerank_by_exact_title(candidates, short_query)

    assert len(reranked) == 30
    assert [r["id"] for r in reranked] == [c["id"] for c in candidates]


def test_rerank_no_match_preserves_original_order():
    """일치하는 제목이 전혀 없을 때 30건 원본 거리 순서가 100% 보존됨을 확인합니다."""
    candidates = _generate_30_mock_documents()
    unrelated_query = "완전히 다른 분야인 인공지능 빅데이터 소프트웨어 개발 용역 공고"

    reranked = _rerank_by_exact_title(candidates, unrelated_query)

    assert len(reranked) == 30
    assert [r["id"] for r in reranked] == [c["id"] for c in candidates]


# ---------------------------------------------------------------------------
# 6. retrieve_semantic_context 전체 경로 출력 불변성 검증 (Mock Chroma)
# ---------------------------------------------------------------------------


def test_retrieve_semantic_context_deterministic_output(monkeypatch):
    """retrieve_semantic_context 가 주입된 ChromaDB 출력에 대해 정확하고 일관된 문서를 반환함을 검증합니다."""
    mock_docs_30 = _generate_30_mock_documents()
    raw_texts = [d["document"] for d in mock_docs_30]
    raw_metas = [d["metadata"] for d in mock_docs_30]
    raw_dists = [d["distance"] for d in mock_docs_30]

    class MockCollection:
        @staticmethod
        def query(query_texts, n_results, where=None):
            return {
                "documents": [raw_texts[:n_results]],
                "metadatas": [raw_metas[:n_results]],
                "distances": [raw_dists[:n_results]],
            }

    class MockChromaClient:
        @staticmethod
        def PersistentClient(path):
            return MockChromaClient()

    monkeypatch.setitem(__import__("sys").modules, "chromadb", MockChromaClient)
    monkeypatch.setattr(
        "src.rag.vector_store.get_collection", lambda client, name: MockCollection()
    )

    # 1. q21 검색 (top_k=5)
    plan_q21 = RetrievalPlan(
        semantic_query="2026년 조림지 풀베기사업 2차(동부지구)의 공고번호 및 낙찰금액",
        top_k=5,
    )
    result_q21 = retrieve_semantic_context(plan_q21)

    assert result_q21.ok is True
    assert len(result_q21.documents) == 5
    # 1위는 9위였던 bid_10000009
    assert result_q21.documents[0]["metadata"]["bid_ntce_no"] == "2026080009"
    # 2위는 15위였던 bid_10000015
    assert result_q21.documents[1]["metadata"]["bid_ntce_no"] == "2026080015"
    # 3위는 원본 1위였던 bid_10000001
    assert result_q21.documents[2]["metadata"]["bid_ntce_no"] == "2026080001"

    # 2. post-filter 검색 (기관명 = 테스트기관_09)
    plan_post_filter = RetrievalPlan(
        semantic_query="2026년 조림지 풀베기사업",
        filters={"institution_name": "테스트기관_09"},
        top_k=5,
    )
    result_pf = retrieve_semantic_context(plan_post_filter)

    assert result_pf.ok is True
    assert len(result_pf.documents) == 1
    assert result_pf.documents[0]["metadata"]["bid_ntce_no"] == "2026080009"
    assert result_pf.applied_post_filters == {"institution_name": "테스트기관_09"}
    assert result_pf.post_filtered_count == 29

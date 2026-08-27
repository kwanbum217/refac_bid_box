"""
tests/test_numeric_omission_detector.py

RAG 낙찰금액·낙찰률 수치 누락 검출기(Numeric Omission Detector) 단위 테스트:
 1. 90 이 90.1 안에서 매치되지 않는 경계 인식 매칭 검증
 2. _apply_answer_guard 후처리(카테고리 정규화, 데이터 부재 교정) 후 최종 답변 검사 검증
 3. Source [n] 블록 단위 출처 라벨 추출 및 unknown 라벨 처리 검증
 4. 기존 amounts / rates 키 형태 및 하위 호환성 유지 검증
 5. settings.NUMERIC_OMISSION_DETECTION 기본값 False 유지 검증
"""

import logging

from src.app.core.config import settings
from src.rag.engine import (
    _contains_bounded_number,
    check_numeric_omissions,
    extract_numeric_context_values,
    rag_engine,
)
from src.rag.schemas import RetrievalPlan


def test_default_numeric_omission_detection_is_false():
    """기본 설정에서 수치 누락 검출 플래그가 False 로 유지되어야 합니다."""
    assert settings.NUMERIC_OMISSION_DETECTION is False


def test_boundary_matching_rejects_substring_in_float():
    """후보 '90' 이 '90.1' 또는 '90.1950' 안에서 부분 매치되어 누락이 미탐되는 현상을 방지해야 합니다."""
    assert _contains_bounded_number("낙찰률은 90.1%입니다.", "90") is False
    assert _contains_bounded_number("낙찰률은 90.1950%입니다.", "90") is False
    assert _contains_bounded_number("낙찰률은 90.0%입니다.", "90") is False

    # 정확한 매치 케이스
    assert _contains_bounded_number("낙찰률은 90%입니다.", "90") is True
    assert _contains_bounded_number("낙찰률은 90.1950%입니다.", "90.1950") is True
    assert _contains_bounded_number("낙찰률은 90.1%입니다.", "90.1") is True


def test_boundary_matching_rejects_substring_in_large_number():
    """후보 '740' 또는 '1074' 가 '1,074,000' 안에서 부분 매치되지 않아야 합니다."""
    assert _contains_bounded_number("낙찰금액은 1,074,000원입니다.", "740") is False
    assert _contains_bounded_number("낙찰금액은 1,074,000원입니다.", "1074") is False
    assert _contains_bounded_number("낙찰금액은 1,074,000원입니다.", "1,074") is False

    # 정확한 매치 케이스
    assert _contains_bounded_number("낙찰금액은 1,074,000원입니다.", "1,074,000") is True
    assert _contains_bounded_number("낙찰금액은 1074000원입니다.", "1074000") is True


def test_check_numeric_omissions_detects_omission_when_only_subvalue_present(monkeypatch):
    """컨텍스트에 '90' 이 있고 답변에 '90.1' 만 있을 때 '90' 누락이 올바르게 검출되어야 합니다."""
    monkeypatch.setattr("src.rag.engine.settings.NUMERIC_OMISSION_DETECTION", True)

    context = "Source [3]:\n[낙찰금액] 1000000원\n[낙찰률] 90%"
    answer = "낙찰금액은 1,000,000원이며 낙찰률은 90.1%입니다."

    res = check_numeric_omissions(context, answer, trace_id="trace-test-subvalue")
    assert res is not None
    assert res["omission_detected"] is True
    assert res["missing_rates"] == ["90"]
    assert res["missing_rate_sources"] == {"90": ["Source [3]"]}
    assert res["missing_amounts"] == []


def test_extract_numeric_context_values_attaches_source_labels():
    """각 낙찰금액 및 낙찰률 값에 해당하는 Source 라벨이 정상 추출되어야 합니다."""
    context = (
        "검색 라우팅: 정형 통계\n"
        "[낙찰금액] 99999\n"  # Source 머리글 이전 -> unknown
        "Source [1] (통계/수치):\n"
        "[공고명] 2026 유지보수\n"
        "[낙찰금액] 1000000\n"
        "[낙찰률] 88.5\n\n"
        "Source [3] (공고 R26BK0001):\n"
        "[공고명] 2026 도로 정비 사업\n"
        "[낙찰금액] 5,200,000\n"
        "[낙찰금액] 1000000\n"  # Source [1]과 중복 등장
        "[낙찰률] 90.1950%\n"
    )
    result = extract_numeric_context_values(context)

    # 기존 키 하위 호환성 검증
    assert isinstance(result["amounts"], list)
    assert isinstance(result["rates"], list)
    assert result["amounts"] == ["99999", "1000000", "5,200,000"]
    assert result["rates"] == ["88.5", "90.1950"]

    # 출처 정보 키 검증
    assert result["amount_sources"]["99999"] == ["unknown"]
    assert result["amount_sources"]["1000000"] == ["Source [1]", "Source [3]"]
    assert result["amount_sources"]["5,200,000"] == ["Source [3]"]
    assert result["rate_sources"]["88.5"] == ["Source [1]"]
    assert result["rate_sources"]["90.1950"] == ["Source [3]"]


def test_check_numeric_omissions_includes_source_labels_in_log_and_result(caplog, monkeypatch):
    """누락 검출 결과와 로그에 누락 값별 Source 출처 라벨이 포함되어야 합니다."""
    monkeypatch.setattr("src.rag.engine.settings.NUMERIC_OMISSION_DETECTION", True)

    context = (
        "Source [1]:\n"
        "[낙찰금액] 1000000\n"
        "[낙찰률] 88.5\n\n"
        "Source [4]:\n"
        "[낙찰금액] 2000000\n"
        "[낙찰률] 95.0\n"
    )
    # 1000000과 88.5만 언급하고 Source [4]의 2000000과 95.0 누락
    answer = "Source [1]의 낙찰금액은 1,000,000원이고 낙찰률은 88.5%입니다."

    with caplog.at_level(logging.WARNING, logger="src.rag.engine"):
        res = check_numeric_omissions(context, answer, trace_id="trace-source-log-test")

    assert res is not None
    assert res["omission_detected"] is True
    assert res["missing_count"] == 2
    assert res["missing_amounts"] == ["2000000"]
    assert res["missing_amount_sources"] == {"2000000": ["Source [4]"]}
    assert res["missing_rates"] == ["95.0"]
    assert res["missing_rate_sources"] == {"95.0": ["Source [4]"]}

    omission_logs = [r for r in caplog.records if "rag_numeric_omission:" in r.message]
    assert len(omission_logs) == 1
    record = omission_logs[0]
    assert "missing_amount_sources={'2000000': ['Source [4]']}" in record.message
    assert "missing_rate_sources={'95.0': ['Source [4]']}" in record.message
    assert getattr(record, "missing_amount_sources", None) == {"2000000": ["Source [4]"]}
    assert getattr(record, "missing_rate_sources", None) == {"95.0": ["Source [4]"]}


def test_apply_answer_guard_inspects_final_postprocessed_answer(monkeypatch):
    """_apply_answer_guard 에서 후처리가 완료된 최종 문자열을 기준으로 검출기가 호출되어야 합니다."""
    monkeypatch.setattr("src.rag.engine.settings.NUMERIC_OMISSION_DETECTION", True)

    inspected_answers: list[str] = []

    def mock_check(context_text: str, answer_text: str, trace_id: str = ""):
        inspected_answers.append(answer_text)

    monkeypatch.setattr("src.rag.engine.check_numeric_omissions", mock_check)

    plan = RetrievalPlan(use_sql=True, filters={"category": "Servc"})
    structured_data = {
        "summary": {
            "total_bids": 5,
            "announcement_count": 2,
        }
    }
    raw_answer = "데이터가 없습니다. Servc 분야 분석 결과입니다."
    context = "Source [1]:\n[낙찰금액] 1000000\n[낙찰률] 90.0"

    final_result = rag_engine._apply_answer_guard(
        raw_answer,
        structured_data=structured_data,
        plan=plan,
        context_text=context,
        trace_id="test-guard-final-trace",
    )

    # 1. 후처리 확인: '데이터가 없습니다' 교정 및 'Servc' -> '용역' 정규화
    assert "낙찰 5건, 공고 2건" in final_result
    assert "용역 분야" in final_result
    assert "Servc" not in final_result
    assert "데이터가 없습니다" not in final_result

    # 2. check_numeric_omissions에 전달된 문자열이 최종 결과와 일치하는지 확인
    assert len(inspected_answers) == 1
    assert inspected_answers[0] == final_result
    assert "용역 분야" in inspected_answers[0]
    assert "Servc" not in inspected_answers[0]


def test_apply_answer_guard_inspects_final_answer_on_skipped_query(monkeypatch):
    """query_skipped 분기에서도 후처리를 거친 최종 문자열을 검사해야 합니다."""
    monkeypatch.setattr("src.rag.engine.settings.NUMERIC_OMISSION_DETECTION", True)

    inspected_answers: list[str] = []

    def mock_check(context_text: str, answer_text: str, trace_id: str = ""):
        inspected_answers.append(answer_text)

    monkeypatch.setattr("src.rag.engine.check_numeric_omissions", mock_check)

    plan = RetrievalPlan(use_sql=True, filters={"category": "Servc"})
    structured_data = {"query_skipped": True}
    raw_answer = "서비스(Servc) 조회를 건너뛰었습니다."
    context = "Source [3]:\n[낙찰금액] 500000"

    final_result = rag_engine._apply_answer_guard(
        raw_answer,
        structured_data=structured_data,
        plan=plan,
        context_text=context,
        trace_id="test-guard-skipped-trace",
    )

    assert final_result == "용역 조회를 건너뛰었습니다."
    assert len(inspected_answers) == 1
    assert inspected_answers[0] == "용역 조회를 건너뛰었습니다."

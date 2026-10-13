"""
tests/test_document_extraction_parser.py

신용평가등급확인서 파서(순수 함수) 단위 시험.

실제 등급확인서를 쓰지 않고 시험 코드 안에서 만든 한국어 문장만 사용합니다.
등급 값은 반드시 CREDIT_GRADE_CHOICES 안의 코드여야 합니다.
"""

from __future__ import annotations

import pytest

from src.app.services.auth_forms import CREDIT_GRADE_CHOICES
from src.app.services.document_extraction.credit_certificate import (
    DOCUMENT_TYPE_CREDIT_RATING_CERTIFICATE,
    MAX_EVIDENCE_LENGTH,
    parse_credit_certificate,
)
from src.app.services.evaluation_rules import find_credit_grade

GRADE_CODES = frozenset(code for code, _ in CREDIT_GRADE_CHOICES)


def test_extracts_grade_and_date_with_evidence() -> None:
    text = "신용평가등급확인서\n신용등급 : AA-\n평가일 : 2026-03-15"
    result = parse_credit_certificate([text])

    assert result.status == "extracted"
    assert result.document_type == DOCUMENT_TYPE_CREDIT_RATING_CERTIFICATE
    assert result.credit_grade is not None
    assert result.credit_grade.value == "AA-"
    assert result.credit_grade.confidence == "high"
    assert result.credit_grade.page == 1
    assert result.credit_grade.text == "신용평가등급확인서 신용등급 : AA- 평가일 : 2026-03-15"
    assert result.credit_evaluated_on is not None
    assert result.credit_evaluated_on.value == "2026-03-15"
    assert result.credit_evaluated_on.confidence == "high"


@pytest.mark.parametrize(
    "date_text",
    ["2026-03-15", "2026.03.15", "2026/03/15", "2026년 3월 15일"],
)
def test_recognizes_date_format_variants(date_text: str) -> None:
    result = parse_credit_certificate([f"신용등급 : A0\n평가일자 : {date_text}"])

    assert result.credit_evaluated_on is not None
    assert result.credit_evaluated_on.value == "2026-03-15"


@pytest.mark.parametrize(
    ("notation", "expected"),
    [
        ("AAA", "AAA"),
        ("AA+", "AA+"),
        ("AA-", "AA-"),
        ("A0", "A0"),
        ("A", "A0"),
        ("AA", "AA0"),
        ("BBB", "BBB0"),
        ("BB", "BB0"),
        ("B", "B0"),
        ("CCC+", "CCC+"),
        ("D", "D"),
    ],
)
def test_grade_values_are_registered_codes(notation: str, expected: str) -> None:
    result = parse_credit_certificate([f"신용등급 : {notation}"])

    assert result.credit_grade is not None
    assert result.credit_grade.value == expected
    assert result.credit_grade.value in GRADE_CODES
    assert find_credit_grade(result.credit_grade.value) is not None


def test_plain_label_is_preferred_over_instrument_label() -> None:
    pages = ["회사채 신용등급 : BBB+\n신용등급 : A0\n평가일 : 2026-03-15"]
    result = parse_credit_certificate(pages)

    assert result.credit_grade is not None
    assert result.credit_grade.value == "A0"
    assert result.credit_grade.confidence == "high"


def test_instrument_only_grade_confidence_is_capped() -> None:
    result = parse_credit_certificate(["기업어음 신용등급 : A+"])

    assert result.credit_grade is not None
    assert result.credit_grade.value == "A+"
    assert result.credit_grade.confidence == "medium"


def test_repeated_same_grade_lowers_confidence_to_medium() -> None:
    pages = ["신용등급 : A0\n평가일 : 2026-03-15", "신용등급 : A0"]
    result = parse_credit_certificate(pages)

    assert result.credit_grade is not None
    assert result.credit_grade.value == "A0"
    assert result.credit_grade.confidence == "medium"


def test_conflicting_grades_lower_confidence_to_low() -> None:
    pages = ["신용등급 : A+\n신용등급 : BBB-"]
    result = parse_credit_certificate(pages)

    assert result.credit_grade is not None
    assert result.credit_grade.value in GRADE_CODES
    assert result.credit_grade.confidence == "low"


def test_next_line_values_are_recognized() -> None:
    pages = ["신용등급\nAA-\n평가일자\n2026-03-15"]
    result = parse_credit_certificate(pages)

    assert result.credit_grade is not None
    assert result.credit_grade.value == "AA-"
    assert result.credit_evaluated_on is not None
    assert result.credit_evaluated_on.value == "2026-03-15"


def test_evaluation_date_is_preferred_over_issuance_date() -> None:
    pages = ["신용등급 : A0\n발급일 : 2026-02-01\n평가일 : 2026-03-15"]
    result = parse_credit_certificate(pages)

    assert result.credit_evaluated_on is not None
    assert result.credit_evaluated_on.value == "2026-03-15"
    assert result.credit_evaluated_on.confidence == "low"


def test_issuance_date_is_used_when_evaluation_date_is_absent() -> None:
    result = parse_credit_certificate(["신용등급 : A0\n발급일자 : 2026년 3월 15일"])

    assert result.credit_evaluated_on is not None
    assert result.credit_evaluated_on.value == "2026-03-15"


def test_page_number_is_one_based() -> None:
    result = parse_credit_certificate(["", "평가일 : 2026-03-15\n신용등급 : BB+"])

    assert result.credit_grade is not None
    assert result.credit_grade.page == 2
    assert result.credit_evaluated_on is not None
    assert result.credit_evaluated_on.page == 2


def test_evidence_is_capped_at_120_characters() -> None:
    long_prefix = "가" * 200
    result = parse_credit_certificate([f"{long_prefix} 신용등급 : AA-"])

    assert result.credit_grade is not None
    assert len(result.credit_grade.text) <= MAX_EVIDENCE_LENGTH


def test_unrecognized_when_grade_is_missing() -> None:
    result = parse_credit_certificate(["이 문서에는 등급 표기가 없습니다."])

    assert result.status == "unrecognized"
    assert result.document_type is None
    assert result.credit_grade is None
    assert result.credit_evaluated_on is None


def test_unrecognized_scan_returns_null_fields() -> None:
    result = parse_credit_certificate(["", "   "])

    assert result.status == "unrecognized"
    assert result.document_type is None
    assert result.credit_grade is None
    assert result.credit_evaluated_on is None


def test_unrecognized_keeps_date_when_only_grade_is_missing() -> None:
    result = parse_credit_certificate(["평가일 : 2026-03-15"])

    assert result.status == "unrecognized"
    assert result.document_type is None
    assert result.credit_grade is None
    assert result.credit_evaluated_on is not None
    assert result.credit_evaluated_on.value == "2026-03-15"


def test_invalid_date_is_ignored() -> None:
    result = parse_credit_certificate(["신용등급 : A0\n평가일 : 2026-13-40"])

    assert result.status == "extracted"
    assert result.credit_evaluated_on is None


def test_fullwidth_notation_is_normalized() -> None:
    text = "신용등급：ＡＡ－\n평가일：２０２６－０３－１５"  # noqa: RUF001 - 전각 표기 정규화 검증용
    result = parse_credit_certificate([text])

    assert result.credit_grade is not None
    assert result.credit_grade.value == "AA-"
    assert result.credit_evaluated_on is not None
    assert result.credit_evaluated_on.value == "2026-03-15"


def test_empty_page_list_is_unrecognized() -> None:
    result = parse_credit_certificate([])

    assert result.status == "unrecognized"
    assert result.credit_grade is None
    assert result.credit_evaluated_on is None


def test_definition_table_is_not_returned_as_grade() -> None:
    text = (
        "기업신용평가등급 확인서\n"
        "기업명 (주)가상기업 기업신용평가등급\n"
        "대표자 홍길동\n"
        "사업자등록번호 000-00-00000\n"
        "AA+\n"
        "등급평가일 2026년 03월 15일\n"
        "기업신용평가등급의 정의\n"
        "등 급 등급의 정의\n"
        "AAA 전반적인 신용도가 매우 우수하며 장래 환경변화에 대한 안정성이 매우 높은 수준임\n"
        "AA 전반적인 신용도가 우수하며 장래 환경변화에 대한 안정성이 높은 수준임\n"
    )
    result = parse_credit_certificate([text])

    assert result.credit_grade is not None
    assert result.credit_grade.value == "AA+"
    assert result.credit_grade.confidence == "high"


def test_boilerplate_grade_sentence_is_not_demoted() -> None:
    text = "상기등급은 회사채에 대한\n신용평가등급 AA+에 준하는 등급임"
    result = parse_credit_certificate([text])

    assert result.credit_grade is not None
    assert result.credit_grade.value == "AA+"
    assert result.credit_grade.confidence == "high"


def test_grade_value_several_lines_below_label_is_detected() -> None:
    text = "기업신용평가등급\n가상기업\n사업자등록번호 000-00-00000\nAA-\n평가일 : 2026-03-15"
    result = parse_credit_certificate([text])

    assert result.credit_grade is not None
    assert result.credit_grade.value == "AA-"
    assert result.credit_grade.confidence == "high"
    assert result.credit_evaluated_on is not None
    assert result.credit_evaluated_on.value == "2026-03-15"


def test_proprietary_evaluator_grade_is_not_returned() -> None:
    text = "신용평가등급 e-5+\n평가일 : 2026-03-15\n기업신용평가등급\nBBB+"
    result = parse_credit_certificate([text])

    assert result.credit_grade is not None
    assert result.credit_grade.value == "BBB+"
    assert result.credit_grade.value in GRADE_CODES


def test_effective_period_value_is_not_evaluation_date() -> None:
    text = "신용등급 : AA-\n등급평가일\n유효기간 2018년 06월 30일"
    result = parse_credit_certificate([text])

    assert result.credit_grade is not None
    assert result.credit_grade.value == "AA-"
    assert result.credit_evaluated_on is None

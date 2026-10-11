"""
src/app/services/document_extraction/__init__.py

업로드된 문서 바이트에서 미리 채우기용 값을 추출하는 서비스 공개 API 입니다.

원본은 호출 안에서만 메모리로 다뤄지며 디스크·Redis·DB·로그 어디에도 남기지
않습니다. 반환값에는 값·신뢰도·근거 조각만 담고 추출 텍스트 전체는 담지 않습니다.
"""

from __future__ import annotations

from src.app.services.document_extraction import credit_certificate, pdf_text
from src.app.services.document_extraction.credit_certificate import (
    DOCUMENT_TYPE_CREDIT_RATING_CERTIFICATE,
    CreditCertificateResult,
    FieldResult,
    parse_credit_certificate,
)
from src.app.services.document_extraction.pdf_text import (
    PDF_MAGIC,
    EncryptedPdfError,
    InvalidPdfError,
    PdfTooLargeError,
    PdfValidationError,
    TooManyPagesError,
)

__all__ = [
    "DOCUMENT_TYPE_CREDIT_RATING_CERTIFICATE",
    "PDF_MAGIC",
    "CreditCertificateResult",
    "EncryptedPdfError",
    "FieldResult",
    "InvalidPdfError",
    "PdfTooLargeError",
    "PdfValidationError",
    "TooManyPagesError",
    "credit_certificate",
    "extract_credit_certificate",
    "parse_credit_certificate",
    "pdf_text",
]


def extract_credit_certificate(data: bytes) -> CreditCertificateResult:
    """PDF 바이트에서 신용등급·평가일을 추출합니다. 원본은 저장하지 않습니다."""
    pages = pdf_text.extract_page_texts(data)
    return credit_certificate.parse_credit_certificate(pages)

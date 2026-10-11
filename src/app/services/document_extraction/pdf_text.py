"""
src/app/services/document_extraction/pdf_text.py

업로드된 PDF 바이트를 디스크에 쓰지 않고 메모리에서만 검증·추출합니다.

검증 순서는 크기, 매직, 암호화, 쪽수입니다. pdfplumber 는 io.BytesIO 로만 열고
임시 파일을 만들지 않습니다. 여기서 만드는 예외는 라우터가 계약된 상태 코드와
한국어 문구로 변환하며, 예외 원문은 응답에 담지 않습니다.
"""

from __future__ import annotations

import io

import pdfplumber
from pdfminer.pdfdocument import PDFPasswordIncorrect
from pdfminer.pdfexceptions import PDFException
from pdfplumber.utils.exceptions import PdfminerException

PDF_MAGIC = b"%PDF-"
MAX_PDF_BYTES = 5 * 1024 * 1024
MAX_PDF_PAGES = 10


class PdfValidationError(Exception):
    """업로드된 PDF 의 로컬 검증 실패. 라우터가 상태 코드와 문구로 변환합니다."""

    status_code = 400
    detail = "PDF 파일을 처리할 수 없습니다."


class PdfTooLargeError(PdfValidationError):
    status_code = 413
    detail = "PDF 파일 크기가 제한을 초과했습니다."


class InvalidPdfError(PdfValidationError):
    status_code = 400
    detail = "PDF 파일을 열 수 없습니다. 손상되었거나 PDF 형식이 아닙니다."


class EncryptedPdfError(PdfValidationError):
    status_code = 400
    detail = "암호화된 PDF 파일은 처리할 수 없습니다."


class TooManyPagesError(PdfValidationError):
    status_code = 400
    detail = "PDF 페이지 수가 제한을 초과했습니다."


def validate_pdf_bytes(data: bytes) -> None:
    """크기와 매직 바이트를 검사합니다. 손상·암호화·쪽수는 열면서 판정합니다."""
    if len(data) > MAX_PDF_BYTES:
        raise PdfTooLargeError
    if not data.startswith(PDF_MAGIC):
        raise InvalidPdfError


def _chain_contains_password_error(exc: BaseException) -> bool:
    """예외 원인·문맥 사슬에 PDFPasswordIncorrect 가 있는지 봅니다.

    pdfplumber 는 pdfminer 의 PDFPasswordIncorrect 를 PdfminerException 으로
    감싸므로 isinstance 만으로는 암호화 PDF 를 구분할 수 없습니다.
    """
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        if isinstance(current, PDFPasswordIncorrect):
            return True
        seen.add(id(current))
        current = current.__cause__ or current.__context__
    return False


def extract_page_texts(data: bytes) -> list[str]:
    """PDF 바이트를 쪽별 텍스트 목록(1쪽부터)으로 바꿉니다.

    텍스트가 없는 스캔본 쪽은 빈 문자열이 됩니다. 원본은 io.BytesIO 안에서만
    다루며 디스크·캐시에 남기지 않습니다.
    """
    validate_pdf_bytes(data)
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            if getattr(pdf.doc, "encryption", None) is not None:
                raise EncryptedPdfError
            pages = pdf.pages
            if len(pages) > MAX_PDF_PAGES:
                raise TooManyPagesError
            return [page.extract_text() or "" for page in pages]
    except PdfValidationError:
        raise
    except (PdfminerException, PDFException) as exc:
        if _chain_contains_password_error(exc):
            raise EncryptedPdfError from exc
        raise InvalidPdfError from exc
    except Exception as exc:
        # 손상 파일은 라이브러리 버전에 따라 다른 예외로 떨어집니다. 어떤 경우에도
        # 500 으로 새지 않게 400 으로 좁히고 원문은 응답에 담지 않습니다.
        raise InvalidPdfError from exc

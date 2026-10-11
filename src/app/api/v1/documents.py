"""
src/app/api/v1/documents.py

신용평가등급확인서 PDF 에서 등급·평가일을 추출하는 API 입니다.

텍스트 PDF 는 pdfplumber 로 바로 읽고, 등급을 찾지 못한 스캔본은
DOCUMENT_OCR_ENABLED 가 켜져 있을 때만 로컬 OCR 로 한 번 더 읽습니다. 업로드
원본은 요청 안에서만 메모리로 처리하고 디스크·Redis·DB·로그 어디에도 저장하지
않습니다. 추출은 스레드로 넘기되 10초 제한을 두며, 제한 시간을 넘기면 422 로
끝냅니다. 오류 응답에는 예외 원문을 담지 않고 한국어 문구만 담습니다.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from src.app.api.v1.accounts import require_current_user
from src.app.core.config import settings
from src.app.core.security import enforce_document_extraction_quota
from src.app.models.accounts import CustomUser
from src.app.services.document_extraction import (
    CreditCertificateResult,
    FieldResult,
    PdfValidationError,
    extract_credit_certificate,
    ocr,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["Documents"])

EXTRACTION_TIMEOUT_SECONDS = 10.0
PDF_MEDIA_TYPE = "application/pdf"

DOCUMENT_EXTRACTION_DISABLED_DETAIL = "문서 추출 기능이 비활성화되어 있습니다."
UNSUPPORTED_MEDIA_TYPE_DETAIL = "PDF 파일만 업로드할 수 있습니다."
EXTRACTION_TIMEOUT_DETAIL = "문서 처리 시간이 초과되었습니다. 잠시 후 다시 시도해 주십시오."
EXTRACTION_FAILED_DETAIL = "문서 처리 중 오류가 발생했습니다."
EXTRACTION_NOTICE = "추출값은 확인이 필요합니다. 저장 전에 원문과 대조하십시오."


class FieldEvidence(BaseModel):
    page: int
    text: str


class ExtractedField(BaseModel):
    value: str
    confidence: Literal["high", "medium", "low"]
    evidence: FieldEvidence


class DocumentFields(BaseModel):
    credit_grade: ExtractedField | None = None
    credit_evaluated_on: ExtractedField | None = None


class DocumentExtractionResponse(BaseModel):
    status: Literal["extracted", "unrecognized"]
    document_type: Literal["credit_rating_certificate"] | None = None
    fields: DocumentFields
    notice: str


def _media_type(content_type: str) -> str:
    """Content-Type 헤더에서 미디어 타입만 뽑습니다."""
    return content_type.split(";", 1)[0].strip().lower()


def _serialize_field(field: FieldResult | None) -> ExtractedField | None:
    if field is None:
        return None
    return ExtractedField(
        value=field.value,
        confidence=field.confidence,
        evidence=FieldEvidence(page=field.page, text=field.text),
    )


def _serialize(result: CreditCertificateResult) -> DocumentExtractionResponse:
    document_type: Literal["credit_rating_certificate"] | None
    if result.document_type == "credit_rating_certificate":
        document_type = "credit_rating_certificate"
    else:
        document_type = None
    return DocumentExtractionResponse(
        status=result.status,
        document_type=document_type,
        fields=DocumentFields(
            credit_grade=_serialize_field(result.credit_grade),
            credit_evaluated_on=_serialize_field(result.credit_evaluated_on),
        ),
        notice=EXTRACTION_NOTICE,
    )


def _extract(data: bytes) -> CreditCertificateResult:
    """텍스트 추출을 먼저 쓰고, 등급을 못 찾으면 토글이 켜진 경우에만 OCR 로 더 읽습니다.

    OCR 경로는 근거가 약하므로 신뢰도 상한이 적용되며, 엔진·모델을 쓸 수 없거나
    읽기에 실패하면 텍스트 추출 결과를 그대로 돌려줍니다.
    """
    result = extract_credit_certificate(data)
    if result.status == "extracted" or not settings.DOCUMENT_OCR_ENABLED:
        return result
    scanned = ocr.extract_scanned_certificate(data)
    return scanned if scanned is not None else result


@router.post("/extract", response_model=DocumentExtractionResponse)
async def extract_document(
    request: Request,
    user: CustomUser = Depends(require_current_user),
) -> DocumentExtractionResponse:
    """로그인 회원의 PDF 에서 등급·평가일을 추출해 미리 채우기용으로 돌려줍니다."""
    if not settings.DOCUMENT_EXTRACTION_ENABLED:
        raise HTTPException(status_code=404, detail=DOCUMENT_EXTRACTION_DISABLED_DETAIL)
    enforce_document_extraction_quota(request, user)
    if _media_type(request.headers.get("content-type", "")) != PDF_MEDIA_TYPE:
        raise HTTPException(status_code=415, detail=UNSUPPORTED_MEDIA_TYPE_DETAIL)

    started = time.perf_counter()
    data = await request.body()
    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(_extract, data),
            timeout=EXTRACTION_TIMEOUT_SECONDS,
        )
    except PdfValidationError as exc:
        logger.info(
            "event=document_extraction, status=rejected, status_code=%d, bytes=%d, elapsed_ms=%.2f",
            exc.status_code,
            len(data),
            (time.perf_counter() - started) * 1000.0,
        )
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except TimeoutError as exc:
        logger.info(
            "event=document_extraction, status=timeout, bytes=%d, elapsed_ms=%.2f",
            len(data),
            (time.perf_counter() - started) * 1000.0,
        )
        raise HTTPException(status_code=422, detail=EXTRACTION_TIMEOUT_DETAIL) from exc
    except Exception as exc:
        logger.warning(
            "event=document_extraction, status=failed, error_type=%s, bytes=%d, elapsed_ms=%.2f",
            type(exc).__name__,
            len(data),
            (time.perf_counter() - started) * 1000.0,
        )
        raise HTTPException(status_code=500, detail=EXTRACTION_FAILED_DETAIL) from exc

    logger.info(
        "event=document_extraction, status=%s, bytes=%d, elapsed_ms=%.2f",
        result.status,
        len(data),
        (time.perf_counter() - started) * 1000.0,
    )
    return _serialize(result)

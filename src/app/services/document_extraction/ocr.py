"""
src/app/services/document_extraction/ocr.py

스캔본(이미지) PDF 를 로컬 OCR 로 읽는 경로입니다.

업로드 원본은 io.BytesIO 안에서만 다루고, 렌더링한 이미지와 인식 텍스트를
디스크·Redis·DB·로그 어디에도 남기지 않습니다. pdfium 으로 페이지를 메모리에서
이미지로 바꾸고 rapidocr(onnxruntime) 로 글자를 읽어 기존 정규식 파서에 넘깁니다.

엔진은 첫 호출 때 한 번만 만들어 재사용하며(스레드 안전), 인식 모델은 실행 중에
내려받지 않고 DOCUMENT_OCR_MODEL_DIR 에 미리 받아 둔 파일만 씁니다. 모델이 없거나
해시가 다르면 OCR 경로를 끄고 경고 로그만 남깁니다. 로그에는 사용 여부·쪽수·소요
시간만 남기고 인식 텍스트는 담지 않습니다.
"""

from __future__ import annotations

import hashlib
import io
import logging
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import pypdfium2 as pdfium

from src.app.core.config import settings
from src.app.services.document_extraction.credit_certificate import (
    Confidence,
    CreditCertificateResult,
    cap_confidence,
    parse_credit_certificate,
)

if TYPE_CHECKING:
    from rapidocr import RapidOCR

logger = logging.getLogger(__name__)

OCR_MAX_PAGES = 3
OCR_RENDER_SCALE = 2.0
OCR_MAX_RENDER_SIDE = 2000
OCR_CONFIDENCE_CEILING: Confidence = "medium"

# scripts/fetch_ocr_models.py 가 고정 URL 에서 받아 두는 인식 모델입니다.
# 두 곳의 정의가 어긋나면 런타임이 해시 대조에서 OCR 경로를 꺼 버리므로,
# tests/test_fetch_ocr_models.py 가 두 정의의 일치를 검사합니다.
MODEL_FILES: tuple[tuple[str, str], ...] = (
    (
        "korean_PP-OCRv5_rec_mobile.onnx",
        "cd6e2ea50f6943ca7271eb8c56a877a5a90720b7047fe9c41a2e541a25773c9b",
    ),
)
REC_MODEL_LANG = "korean"

_engine: RapidOCR | None = None
_engine_unavailable = False
_engine_lock = threading.Lock()


class OcrUnavailableError(RuntimeError):
    """OCR 엔진이나 인식 모델을 쓸 수 없을 때. 호출자는 OCR 을 건너뜁니다."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_model_files(model_dir: str | Path) -> None:
    """인식 모델 파일이 모두 있고 해시가 맞는지 확인합니다.

    해시를 맞춰 두면 실행 중에 모델을 내려받지 않는다는 사실도 함께 보증됩니다.
    """
    directory = Path(model_dir)
    for filename, expected in MODEL_FILES:
        path = directory / filename
        if not path.is_file():
            raise OcrUnavailableError(f"OCR 모델 파일이 없습니다: {path}")
        if _sha256(path) != expected:
            raise OcrUnavailableError(f"OCR 모델 파일 해시가 다릅니다: {path}")


def _create_engine(model_dir: Path) -> RapidOCR:
    from rapidocr import ModelType, OCRVersion, RapidOCR

    verify_model_files(model_dir)
    return RapidOCR(
        params={
            "Global.log_level": "error",
            "Rec.ocr_version": OCRVersion.PPOCRV5,
            "Rec.lang_type": REC_MODEL_LANG,
            "Rec.model_type": ModelType.MOBILE,
            "Rec.model_path": str(model_dir / MODEL_FILES[0][0]),
        }
    )


def get_engine() -> RapidOCR:
    """OCR 엔진을 지연 로드해 재사용합니다. 쓸 수 없으면 OcrUnavailableError 입니다.

    실패는 프로세스당 한 번만 기록하고 이후 호출은 곧바로 건너뜁니다. 모델 파일이
    없는 개발·배포 환경에서도 앱 기동과 나머지 기능은 그대로 동작합니다.
    """
    global _engine, _engine_unavailable
    if _engine is not None:
        return _engine
    with _engine_lock:
        if _engine is not None:
            return _engine
        if _engine_unavailable:
            raise OcrUnavailableError("OCR 엔진을 사용할 수 없습니다.")
        try:
            _engine = _create_engine(Path(settings.DOCUMENT_OCR_MODEL_DIR))
        except Exception as exc:
            _engine_unavailable = True
            logger.warning(
                "event=document_ocr, status=unavailable, error_type=%s", type(exc).__name__
            )
            raise OcrUnavailableError("OCR 엔진을 만들지 못했습니다.") from exc
    return _engine


def _render_scale(width: float, height: float) -> float:
    """긴 변이 OCR 최대 크기를 넘지 않도록 렌더링 배율을 줄입니다.

    PDF 는 최대 14400 포인트까지 허용하므로 배율을 그대로 쓰면 페이지 하나가
    수 GB 메모리를 요구할 수 있습니다.
    """
    longest = max(width, height)
    if longest <= 0:
        return OCR_RENDER_SCALE
    return min(OCR_RENDER_SCALE, OCR_MAX_RENDER_SIDE / longest)


def render_page_images(data: bytes, max_pages: int = OCR_MAX_PAGES) -> list[np.ndarray]:
    """PDF 앞쪽 max_pages 쪽을 BGR 배열로 렌더링합니다. 임시 파일을 만들지 않습니다."""
    images: list[np.ndarray] = []
    with pdfium.PdfDocument(io.BytesIO(data)) as pdf:
        for page_index in range(min(len(pdf), max_pages)):
            page = pdf[page_index]
            try:
                bitmap = page.render(scale=_render_scale(page.get_width(), page.get_height()))
                try:
                    # to_numpy 는 비트맵 버퍼를 그대로 보므로 닫기 전에 복사합니다.
                    image = np.array(bitmap.to_numpy())
                finally:
                    bitmap.close()
            finally:
                page.close()
            if image.ndim == 3 and image.shape[2] > 3:
                image = image[:, :, :3]
            images.append(np.ascontiguousarray(image))
    return images


def recognize_page_texts(data: bytes, max_pages: int = OCR_MAX_PAGES) -> list[str]:
    """PDF 앞쪽 쪽들을 OCR 로 읽어 쪽별 텍스트 목록으로 돌려줍니다."""
    engine = get_engine()
    texts: list[str] = []
    for image in render_page_images(data, max_pages=max_pages):
        result = engine(image)
        lines = getattr(result, "txts", None) or ()
        texts.append("\n".join(str(line) for line in lines))
    return texts


def extract_scanned_certificate(
    data: bytes, max_pages: int = OCR_MAX_PAGES
) -> CreditCertificateResult | None:
    """스캔본을 OCR 로 읽어 등급·평가일을 파싱합니다.

    OCR 을 쓸 수 없거나 읽기에 실패하면 None 을 돌려주고 호출자가 텍스트 추출
    결과를 그대로 쓰게 합니다. 얻은 값은 근거가 약하므로 신뢰도를 medium 이하로
    낮춥니다.
    """
    try:
        started = time.perf_counter()
        pages = recognize_page_texts(data, max_pages=max_pages)
    except OcrUnavailableError:
        return None
    except Exception as exc:
        logger.warning("event=document_ocr, status=failed, error_type=%s", type(exc).__name__)
        return None
    logger.info(
        "event=document_ocr, status=used, pages=%d, elapsed_ms=%.2f",
        len(pages),
        (time.perf_counter() - started) * 1000.0,
    )
    if not any(page.strip() for page in pages):
        return None
    return cap_confidence(parse_credit_certificate(pages), OCR_CONFIDENCE_CEILING)

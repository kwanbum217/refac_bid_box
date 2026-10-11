"""
tests/test_document_extraction_ocr.py

스캔본(이미지) PDF 의 OCR 경로 시험.

실제 등급확인서나 회사명은 쓰지 않습니다. 시험 코드 안에서 만든 합성 이미지 PDF
(숫자·영문만 그린 JPEG 페이지)를 쓰고, OCR 엔진은 대역으로 바꿔 인식 결과를
고정합니다. 실제 엔진 시험 1건은 인식 모델이 있는 환경에서만 돌고 없으면
건너뜁니다. 어느 시험도 인터넷에서 모델을 내려받지 않습니다.
"""

from __future__ import annotations

import tempfile
import time
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw, ImageFont

from src.app.api.v1 import documents
from src.app.api.v1.accounts import require_current_user
from src.app.core.config import settings
from src.app.main import app
from src.app.services.document_extraction import credit_certificate, ocr
from src.app.services.document_extraction.credit_certificate import (
    CreditCertificateResult,
    FieldResult,
)

EXTRACT_URL = "/api/v1/documents/extract"
PDF_HEADERS = {"Content-Type": "application/pdf"}
PAGE_WIDTH, PAGE_HEIGHT = 1240, 1754
SCAN_LINES = ("CREDIT RATING CERTIFICATE", "Credit Rating : AA-", "2026-03-15")
KOREAN_CERTIFICATE_LINES = ("신용평가등급확인서", "신용등급 : AA-", "평가일 : 2026-03-15")
OCR_MARKER = "MARKER-98765"


def _draw_scan(lines: tuple[str, ...] = SCAN_LINES, size: int = 40) -> Image.Image:
    """숫자·영문만 그린 스캔 페이지 한 장을 만듭니다."""
    image = Image.new("RGB", (PAGE_WIDTH, PAGE_HEIGHT), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=size)
    y = 200
    for line in lines:
        draw.text((120, y), line, fill="black", font=font)
        y += size + 40
    return image


def _build_image_pdf(images: list[Image.Image]) -> bytes:
    """JPEG 이미지만 담은 PDF(텍스트 레이어 없음)를 바이트로 만듭니다."""
    objects: dict[int, bytes] = {}
    page_ids: list[int] = []
    for index, image in enumerate(images):
        content_id = 3 + index * 3
        image_id = content_id + 1
        page_id = content_id + 2
        page_ids.append(page_id)
        buffer = BytesIO()
        image.save(buffer, format="JPEG", quality=85)
        jpeg = buffer.getvalue()
        content = f"q {PAGE_WIDTH} 0 0 {PAGE_HEIGHT} 0 0 cm /Im0 Do Q".encode("latin-1")
        objects[content_id] = (
            b"<< /Length "
            + str(len(content)).encode()
            + b" >>\nstream\n"
            + content
            + b"\nendstream"
        )
        objects[image_id] = (
            b"<< /Type /XObject /Subtype /Image /Width "
            + str(image.width).encode()
            + b" /Height "
            + str(image.height).encode()
            + b" /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length "
            + str(len(jpeg)).encode()
            + b" >>\nstream\n"
            + jpeg
            + b"\nendstream"
        )
        objects[page_id] = (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 "
            + str(PAGE_WIDTH).encode()
            + b" "
            + str(PAGE_HEIGHT).encode()
            + b"] /Resources << /XObject << /Im0 "
            + str(image_id).encode()
            + b" 0 R >> >> /Contents "
            + str(content_id).encode()
            + b" 0 R >>"
        )
    kids = b" ".join(str(pid).encode() + b" 0 R" for pid in page_ids)
    objects[1] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objects[2] = (
        b"<< /Type /Pages /Count " + str(len(images)).encode() + b" /Kids [" + kids + b"] >>"
    )
    out = bytearray(b"%PDF-1.4\n")
    offsets: dict[int, int] = {}
    for obj_id in sorted(objects):
        offsets[obj_id] = len(out)
        out += f"{obj_id} 0 obj\n".encode("latin-1") + objects[obj_id] + b"\nendobj\n"
    size = max(objects) + 1
    xref_offset = len(out)
    out += f"xref\n0 {size}\n".encode("latin-1")
    out += b"0000000000 65535 f \n"
    for obj_id in range(1, size):
        out += f"{offsets[obj_id]:010d} 00000 n \n".encode("latin-1")
    out += b"trailer\n<< /Size " + str(size).encode() + b" /Root 1 0 R >>\n"
    out += b"startxref\n" + str(xref_offset).encode() + b"\n%%EOF\n"
    return bytes(out)


class _FakeEngine:
    """rapidocr 대역. 쪽마다 같은 인식 결과를 돌려주고 호출 수를 셉니다."""

    def __init__(
        self, lines: tuple[str, ...] = KOREAN_CERTIFICATE_LINES, delay: float = 0.0
    ) -> None:
        self.lines = lines
        self.delay = delay
        self.calls = 0

    def __call__(self, image) -> SimpleNamespace:
        self.calls += 1
        if self.delay:
            time.sleep(self.delay)
        return SimpleNamespace(txts=self.lines)


@pytest.fixture(autouse=True)
def _reset_ocr_engine(monkeypatch):
    """엔진 싱글톤과 사용 불가 표시를 시험마다 초기 상태로 되돌립니다."""
    monkeypatch.setattr(ocr, "_engine", None)
    monkeypatch.setattr(ocr, "_engine_unavailable", False)


@pytest.fixture
def extraction_enabled(monkeypatch):
    monkeypatch.setattr(settings, "DOCUMENT_EXTRACTION_ENABLED", True)


@pytest.fixture
def ocr_enabled(monkeypatch):
    monkeypatch.setattr(settings, "DOCUMENT_OCR_ENABLED", True)


@pytest.fixture
def authenticated():
    app.dependency_overrides[require_current_user] = lambda: SimpleNamespace(id=7, is_active=True)
    yield
    app.dependency_overrides.pop(require_current_user, None)


@pytest.fixture
def api(client: TestClient, extraction_enabled, authenticated, monkeypatch) -> TestClient:
    """제한기는 이 시험의 대상이 아니므로 통과시킵니다."""
    monkeypatch.setattr(documents, "enforce_document_extraction_quota", lambda *a, **k: None)
    return client


def _use_engine(monkeypatch, engine: _FakeEngine) -> _FakeEngine:
    monkeypatch.setattr(ocr, "get_engine", lambda: engine)
    return engine


def test_scanned_pdf_is_unrecognized_without_ocr_toggle(api, monkeypatch) -> None:
    monkeypatch.setattr(
        ocr, "get_engine", lambda: pytest.fail("토글이 꺼져 있으면 OCR 을 부르면 안 됩니다")
    )
    response = api.post(EXTRACT_URL, content=_build_image_pdf([_draw_scan()]), headers=PDF_HEADERS)

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "unrecognized"
    assert payload["document_type"] is None
    assert payload["fields"] == {"credit_grade": None, "credit_evaluated_on": None}


def test_scanned_pdf_is_extracted_by_ocr_when_enabled(api, ocr_enabled, monkeypatch) -> None:
    _use_engine(monkeypatch, _FakeEngine())
    response = api.post(EXTRACT_URL, content=_build_image_pdf([_draw_scan()]), headers=PDF_HEADERS)

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "extracted"
    assert payload["document_type"] == "credit_rating_certificate"

    grade = payload["fields"]["credit_grade"]
    assert grade["value"] == "AA-"
    assert grade["confidence"] == "medium"
    assert grade["evidence"]["page"] == 1
    assert "신용등급" in grade["evidence"]["text"]

    evaluated_on = payload["fields"]["credit_evaluated_on"]
    assert evaluated_on["value"] == "2026-03-15"
    assert evaluated_on["confidence"] == "medium"


def test_ocr_reads_at_most_three_pages(api, ocr_enabled, monkeypatch) -> None:
    engine = _use_engine(monkeypatch, _FakeEngine())
    content = _build_image_pdf([_draw_scan() for _ in range(4)])
    response = api.post(EXTRACT_URL, content=content, headers=PDF_HEADERS)

    assert response.status_code == 200
    assert response.json()["status"] == "extracted"
    assert engine.calls == ocr.OCR_MAX_PAGES == 3


def test_ocr_path_creates_no_temporary_file(api, ocr_enabled, monkeypatch) -> None:
    _use_engine(monkeypatch, _FakeEngine())

    def _forbidden(*args, **kwargs):
        raise AssertionError("OCR 경로에서 임시 파일을 만들면 안 됩니다")

    monkeypatch.setattr(tempfile, "mkstemp", _forbidden)
    monkeypatch.setattr(tempfile, "NamedTemporaryFile", _forbidden)
    monkeypatch.setattr(tempfile, "TemporaryFile", _forbidden)
    monkeypatch.setattr(tempfile, "SpooledTemporaryFile", _forbidden)
    monkeypatch.setattr(Path, "write_bytes", _forbidden)
    monkeypatch.setattr(Path, "write_text", _forbidden)

    response = api.post(EXTRACT_URL, content=_build_image_pdf([_draw_scan()]), headers=PDF_HEADERS)

    assert response.status_code == 200
    assert response.json()["status"] == "extracted"


def test_ocr_timeout_is_422(api, ocr_enabled, monkeypatch) -> None:
    _use_engine(monkeypatch, _FakeEngine(delay=0.3))
    monkeypatch.setattr(documents, "EXTRACTION_TIMEOUT_SECONDS", 0.05)

    response = api.post(EXTRACT_URL, content=_build_image_pdf([_draw_scan()]), headers=PDF_HEADERS)

    assert response.status_code == 422
    assert response.json() == {
        "detail": "문서 처리 시간이 초과되었습니다. 잠시 후 다시 시도해 주십시오."
    }


def test_recognized_text_is_not_logged(api, ocr_enabled, monkeypatch, caplog) -> None:
    lines = (*KOREAN_CERTIFICATE_LINES, OCR_MARKER)
    _use_engine(monkeypatch, _FakeEngine(lines=lines))

    with caplog.at_level("INFO"):
        response = api.post(
            EXTRACT_URL, content=_build_image_pdf([_draw_scan()]), headers=PDF_HEADERS
        )

    assert response.status_code == 200
    used = [record for record in caplog.records if "event=document_ocr" in record.getMessage()]
    assert any("status=used" in record.getMessage() for record in used)
    assert any("pages=1" in record.getMessage() for record in used)
    assert OCR_MARKER not in caplog.text
    assert "신용등급" not in caplog.text
    assert "AA-" not in caplog.text


def test_ocr_success_without_grade_keeps_unrecognized(api, ocr_enabled, monkeypatch) -> None:
    _use_engine(monkeypatch, _FakeEngine(lines=("THIS DOCUMENT HAS NO GRADE",)))
    response = api.post(EXTRACT_URL, content=_build_image_pdf([_draw_scan()]), headers=PDF_HEADERS)

    assert response.status_code == 200
    assert response.json()["status"] == "unrecognized"


def test_missing_model_disables_ocr_once(api, ocr_enabled, monkeypatch, tmp_path, caplog) -> None:
    monkeypatch.setattr(settings, "DOCUMENT_OCR_MODEL_DIR", str(tmp_path / "empty"))
    content = _build_image_pdf([_draw_scan()])

    with caplog.at_level("WARNING"):
        first = api.post(EXTRACT_URL, content=content, headers=PDF_HEADERS)
        second = api.post(EXTRACT_URL, content=content, headers=PDF_HEADERS)

    assert first.status_code == second.status_code == 200
    assert first.json()["status"] == "unrecognized"
    assert second.json()["status"] == "unrecognized"
    unavailable = [
        record for record in caplog.records if "status=unavailable" in record.getMessage()
    ]
    assert len(unavailable) == 1


def test_mismatched_model_hash_disables_ocr(api, ocr_enabled, monkeypatch, tmp_path) -> None:
    model_dir = tmp_path / "ocr_models"
    model_dir.mkdir()
    filename = ocr.MODEL_FILES[0][0]
    (model_dir / filename).write_bytes(b"not a real model")
    monkeypatch.setattr(settings, "DOCUMENT_OCR_MODEL_DIR", str(model_dir))

    response = api.post(EXTRACT_URL, content=_build_image_pdf([_draw_scan()]), headers=PDF_HEADERS)

    assert response.status_code == 200
    assert response.json()["status"] == "unrecognized"


def test_text_extraction_result_skips_ocr(monkeypatch, ocr_enabled) -> None:
    text_result = CreditCertificateResult(
        status="extracted",
        document_type=credit_certificate.DOCUMENT_TYPE_CREDIT_RATING_CERTIFICATE,
        credit_grade=FieldResult(value="A0", confidence="high", page=1, text="신용등급 : A0"),
        credit_evaluated_on=None,
    )
    monkeypatch.setattr(documents, "extract_credit_certificate", lambda data: text_result)
    monkeypatch.setattr(
        ocr, "get_engine", lambda: pytest.fail("텍스트 추출이 성공하면 OCR 을 부르면 안 됩니다")
    )

    assert documents._extract(b"%PDF-1.4") is text_result


def test_real_engine_reads_digits_from_scanned_pdf() -> None:
    try:
        ocr.verify_model_files(settings.DOCUMENT_OCR_MODEL_DIR)
    except ocr.OcrUnavailableError as exc:
        pytest.skip(f"OCR 인식 모델이 없어 실제 엔진 시험을 건너뜁니다: {exc}")

    data = _build_image_pdf([_draw_scan(lines=("20260315", "AA-"), size=48)])
    pages = ocr.recognize_page_texts(data)
    recognized = "".join("".join(pages).split())

    assert "20260315" in recognized.replace("-", "")

"""
tests/test_document_extraction_api.py

POST /api/v1/documents/extract 계약 시험.

실제 등급확인서나 회사명을 쓰지 않고, 시험 코드 안에서 만든 합성 PDF
(ToUnicode CMap 기반 최소 PDF, 암호화 사전 첨부본, 11쪽, 손상본)만 사용합니다.
"""

from __future__ import annotations

import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.app.api.v1 import documents
from src.app.api.v1.accounts import require_current_user
from src.app.core import security
from src.app.core.config import settings
from src.app.main import app
from src.app.services.auth_forms import CREDIT_GRADE_CHOICES
from src.app.services.document_extraction import credit_certificate

EXTRACT_URL = "/api/v1/documents/extract"
PDF_HEADERS = {"Content-Type": "application/pdf"}
GRADE_CODES = frozenset(code for code, _ in CREDIT_GRADE_CHOICES)
EXTRACTION_NOTICE = "추출값은 확인이 필요합니다. 저장 전에 원문과 대조하십시오."
KOREAN_CERTIFICATE = "신용평가등급확인서\n신용등급 : AA-\n평가일 : 2026-03-15"


def _build_pdf(pages: list[str], *, encrypted: bool = False) -> bytes:
    """한글 텍스트를 담은 최소 PDF 를 바이트로 만듭니다.

    글꼴은 Helvetica(Type1)이고 각 문자를 0x80 이상 코드에 매핑한 ToUnicode CMap 을
    붙여 pdfminer 가 텍스트를 정확히 추출하게 합니다. 뷰어 표시 품질은 보장하지
    않으며 시험 추출용입니다.
    """
    char_map: dict[str, int] = {" ": 0x20}
    for text in pages:
        for char in text:
            if char in char_map:
                continue
            next_code = 0x80 + (len(char_map) - 1)
            if next_code > 0xFF:
                raise ValueError("시험 PDF 의 고유 문자가 너무 많습니다")
            char_map[char] = next_code
    bfchars = "\n".join(f"<{code:02X}> <{ord(char):04X}>" for char, code in char_map.items())
    cmap = (
        b"/CIDInit /ProcSet findresource begin\n"
        b"12 dict begin\nbegincmap\n"
        b"/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def\n"
        b"/CMapName /Adobe-Identity-UCS def\n/CMapType 2 def\n"
        b"1 begincodespacerange\n<00> <FF>\nendcodespacerange\n"
        + f"{len(char_map)} beginbfchar\n{bfchars}\nendbfchar\n".encode("latin-1")
        + b"endcmap\nCMapName currentdict /CMap defineresource pop\nend\nend"
    )

    objects: dict[int, bytes] = {}
    page_ids: list[int] = []
    for index, text in enumerate(pages):
        content_id = 5 + index * 2
        page_id = 6 + index * 2
        page_ids.append(page_id)
        hex_body = "".join(f"{char_map[char]:02X}" for char in text)
        stream = f"BT /F1 12 Tf 72 720 Td <{hex_body}> Tj ET".encode("latin-1")
        objects[content_id] = (
            b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream"
        )
        objects[page_id] = (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 3 0 R >> >> /Contents "
            + str(content_id).encode()
            + b" 0 R >>"
        )
    kids = b" ".join(str(pid).encode() + b" 0 R" for pid in page_ids)
    objects[1] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objects[2] = (
        b"<< /Type /Pages /Count " + str(len(pages)).encode() + b" /Kids [" + kids + b"] >>"
    )
    objects[3] = (
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
        b"/Encoding /WinAnsiEncoding /ToUnicode 4 0 R >>"
    )
    objects[4] = b"<< /Length " + str(len(cmap)).encode() + b" >>\nstream\n" + cmap + b"\nendstream"

    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
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
    encrypt = b""
    if encrypted:
        encrypt = (
            b"/Encrypt << /Filter /Standard /V 1 /R 2 /Length 40 "
            b"/O <" + b"aa" * 32 + b"> /U <" + b"bb" * 32 + b"> /P -44 >> "
        )
    out += b"trailer\n<< /Size " + str(size).encode() + b" /Root 1 0 R " + encrypt + b">>\n"
    out += b"startxref\n" + str(xref_offset).encode() + b"\n%%EOF\n"
    return bytes(out)


class _FakePipeline:
    """문서 추출 제한기가 쓰는 incr·expire 만 지원하는 인메모리 pipeline 대역."""

    def __init__(self, client: _FakeRedisClient) -> None:
        self._client = client
        self._ops: list[tuple[str, str, int]] = []

    def incr(self, key: str, amount: int = 1) -> _FakePipeline:
        self._ops.append(("incr", key, amount))
        return self

    def expire(self, key: str, seconds: int) -> _FakePipeline:
        self._ops.append(("expire", key, seconds))
        return self

    def execute(self) -> list[int]:
        results: list[int] = []
        for op, key, value in self._ops:
            if op == "incr":
                current = int(self._client.store.get(key, "0")) + value
                self._client.store[key] = str(current)
                results.append(current)
            else:
                self._client.ttls[key] = value
                results.append(1)
        self._ops.clear()
        return results


class _FakeRedisClient:
    """제한기 운영 계약(get, pipeline)을 지원하는 인메모리 Redis 대역."""

    def __init__(self, counts: dict[str, int] | None = None) -> None:
        self.store: dict[str, str] = {key: str(value) for key, value in (counts or {}).items()}
        self.ttls: dict[str, int] = {}

    def get(self, key: str) -> str | None:
        return self.store.get(key)

    def pipeline(self) -> _FakePipeline:
        return _FakePipeline(self)


@pytest.fixture
def extraction_enabled(monkeypatch):
    monkeypatch.setattr(settings, "DOCUMENT_EXTRACTION_ENABLED", True)


@pytest.fixture
def authenticated():
    app.dependency_overrides[require_current_user] = lambda: SimpleNamespace(id=7, is_active=True)
    yield
    app.dependency_overrides.pop(require_current_user, None)


@pytest.fixture
def rate_limit_store(monkeypatch):
    fake = _FakeRedisClient()
    monkeypatch.setattr(security.document_extraction_rate_limiter._conn, "client", lambda: fake)
    return fake


@pytest.fixture
def api(client, extraction_enabled, authenticated, rate_limit_store):
    return client, rate_limit_store


def test_extract_returns_contract_json(api) -> None:
    client, _ = api
    response = client.post(
        EXTRACT_URL, content=_build_pdf([KOREAN_CERTIFICATE]), headers=PDF_HEADERS
    )

    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {"status", "document_type", "fields", "notice"}
    assert payload["status"] == "extracted"
    assert payload["document_type"] == "credit_rating_certificate"
    assert payload["notice"] == EXTRACTION_NOTICE
    assert set(payload["fields"]) == {"credit_grade", "credit_evaluated_on"}

    grade = payload["fields"]["credit_grade"]
    assert grade["value"] == "AA-"
    assert grade["value"] in GRADE_CODES
    assert grade["confidence"] == "high"
    assert grade["evidence"] == {
        "page": 1,
        "text": "신용평가등급확인서 신용등급 : AA- 평가일 : 2026-03-15",
    }

    evaluated_on = payload["fields"]["credit_evaluated_on"]
    assert evaluated_on["value"] == "2026-03-15"
    assert evaluated_on["confidence"] == "high"
    assert evaluated_on["evidence"]["page"] == 1


def test_page_without_text_is_unrecognized(api) -> None:
    client, _ = api
    response = client.post(EXTRACT_URL, content=_build_pdf([""]), headers=PDF_HEADERS)

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "unrecognized"
    assert payload["document_type"] is None
    assert payload["fields"] == {"credit_grade": None, "credit_evaluated_on": None}
    assert payload["notice"] == EXTRACTION_NOTICE


def test_text_without_grade_is_unrecognized(api) -> None:
    client, _ = api
    response = client.post(
        EXTRACT_URL, content=_build_pdf(["이 문서에는 등급 표기가 없습니다."]), headers=PDF_HEADERS
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "unrecognized"
    assert payload["document_type"] is None
    assert payload["fields"]["credit_grade"] is None


def test_second_page_fields_report_page_number(api) -> None:
    client, _ = api
    content = _build_pdf(["표지", "평가일 : 2026-03-15\n신용등급 : BBB0"])
    response = client.post(EXTRACT_URL, content=content, headers=PDF_HEADERS)

    assert response.status_code == 200
    fields = response.json()["fields"]
    assert fields["credit_grade"]["value"] == "BBB0"
    assert fields["credit_grade"]["evidence"]["page"] == 2
    assert fields["credit_evaluated_on"]["value"] == "2026-03-15"


def test_non_pdf_content_type_is_415(api) -> None:
    client, _ = api
    response = client.post(
        EXTRACT_URL, content=b"%PDF-1.4", headers={"Content-Type": "application/json"}
    )

    assert response.status_code == 415
    assert response.json() == {"detail": "PDF 파일만 업로드할 수 있습니다."}


def test_missing_content_type_is_415(api) -> None:
    client, _ = api
    response = client.post(EXTRACT_URL, content=b"%PDF-1.4")

    assert response.status_code == 415


def test_magicless_body_is_400(api) -> None:
    client, _ = api
    response = client.post(EXTRACT_URL, content=b"not a pdf at all", headers=PDF_HEADERS)

    assert response.status_code == 400
    assert response.json() == {
        "detail": "PDF 파일을 열 수 없습니다. 손상되었거나 PDF 형식이 아닙니다."
    }


def test_corrupt_pdf_is_400(api) -> None:
    client, _ = api
    truncated = _build_pdf([KOREAN_CERTIFICATE])[:120]
    response = client.post(EXTRACT_URL, content=truncated, headers=PDF_HEADERS)

    assert response.status_code == 400
    assert response.json() == {
        "detail": "PDF 파일을 열 수 없습니다. 손상되었거나 PDF 형식이 아닙니다."
    }


def test_encrypted_pdf_is_400(api) -> None:
    client, _ = api
    response = client.post(
        EXTRACT_URL, content=_build_pdf([KOREAN_CERTIFICATE], encrypted=True), headers=PDF_HEADERS
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "암호화된 PDF 파일은 처리할 수 없습니다."}


def test_more_than_ten_pages_is_400(api) -> None:
    client, _ = api
    response = client.post(
        EXTRACT_URL, content=_build_pdf(["신용등급 : AA-"] * 11), headers=PDF_HEADERS
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "PDF 페이지 수가 제한을 초과했습니다."}


def test_oversized_body_is_413(api) -> None:
    client, _ = api
    body = b"%PDF-" + b"0" * (5 * 1024 * 1024)
    response = client.post(EXTRACT_URL, content=body, headers=PDF_HEADERS)

    assert response.status_code == 413
    assert response.json() == {"detail": "PDF 파일 크기가 제한을 초과했습니다."}


def test_unauthenticated_request_is_401(client, extraction_enabled) -> None:
    response = client.post(
        EXTRACT_URL, content=_build_pdf([KOREAN_CERTIFICATE]), headers=PDF_HEADERS
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "로그인이 필요합니다."}


def test_disabled_toggle_is_404(client, authenticated, monkeypatch) -> None:
    monkeypatch.setattr(settings, "DOCUMENT_EXTRACTION_ENABLED", False)
    response = client.post(
        EXTRACT_URL, content=_build_pdf([KOREAN_CERTIFICATE]), headers=PDF_HEADERS
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "문서 추출 기능이 비활성화되어 있습니다."}


def test_user_rate_limit_exceeded_is_429(api) -> None:
    client, store = api
    store.store[f"{security.DOCUMENT_EXTRACTION_RATE_LIMIT_USER_PREFIX}7"] = "10"
    response = client.post(
        EXTRACT_URL, content=_build_pdf([KOREAN_CERTIFICATE]), headers=PDF_HEADERS
    )

    assert response.status_code == 429
    assert response.json() == {"detail": "요청이 너무 많습니다. 잠시 후 다시 시도해 주십시오."}
    assert store.store[f"{security.DOCUMENT_EXTRACTION_RATE_LIMIT_USER_PREFIX}7"] == "10"


def test_ip_rate_limit_exceeded_is_429(api) -> None:
    client, store = api
    first = client.post(EXTRACT_URL, content=_build_pdf([KOREAN_CERTIFICATE]), headers=PDF_HEADERS)
    assert first.status_code == 200
    ip_key = next(
        key
        for key in store.store
        if key.startswith(security.DOCUMENT_EXTRACTION_RATE_LIMIT_IP_PREFIX)
    )
    store.store[ip_key] = "30"

    response = client.post(
        EXTRACT_URL, content=_build_pdf([KOREAN_CERTIFICATE]), headers=PDF_HEADERS
    )

    assert response.status_code == 429


def test_rate_limit_counters_have_ttl_and_no_payload(api) -> None:
    client, store = api
    response = client.post(
        EXTRACT_URL, content=_build_pdf([KOREAN_CERTIFICATE]), headers=PDF_HEADERS
    )
    assert response.status_code == 200

    prefixes = (
        security.DOCUMENT_EXTRACTION_RATE_LIMIT_USER_PREFIX,
        security.DOCUMENT_EXTRACTION_RATE_LIMIT_IP_PREFIX,
    )
    assert store.store
    for key, value in store.store.items():
        assert key.startswith(prefixes)
        assert value.isdigit()
        assert store.ttls.get(key) == security.DOCUMENT_EXTRACTION_RATE_LIMIT_WINDOW_SECONDS
    joined = " ".join((*store.store, *store.store.values()))
    assert "신용등급" not in joined
    assert "AA-" not in joined
    assert "%PDF" not in joined


def test_foreign_origin_is_rejected_with_403(
    client, extraction_enabled, authenticated, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "CORS_ALLOWED_ORIGINS", "https://app.example.com")
    response = client.post(
        EXTRACT_URL,
        content=_build_pdf([KOREAN_CERTIFICATE]),
        headers={
            **PDF_HEADERS,
            "Origin": "https://evil.example",
            "Cookie": "bidbox_session=test-session",
        },
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "허용되지 않은 출처의 요청입니다."}


def test_no_raw_file_is_persisted_during_extraction(api, monkeypatch) -> None:
    client, store = api

    def _forbidden(*args, **kwargs):
        raise AssertionError("문서 추출 중 임시 파일을 만들면 안 됩니다")

    monkeypatch.setattr(tempfile, "mkstemp", _forbidden)
    monkeypatch.setattr(tempfile, "NamedTemporaryFile", _forbidden)
    monkeypatch.setattr(tempfile, "TemporaryFile", _forbidden)
    monkeypatch.setattr(tempfile, "SpooledTemporaryFile", _forbidden)
    monkeypatch.setattr(Path, "write_bytes", _forbidden)
    monkeypatch.setattr(Path, "write_text", _forbidden)

    response = client.post(
        EXTRACT_URL, content=_build_pdf([KOREAN_CERTIFICATE]), headers=PDF_HEADERS
    )

    assert response.status_code == 200
    assert any(
        key.startswith(security.DOCUMENT_EXTRACTION_RATE_LIMIT_USER_PREFIX) for key in store.store
    )


def test_timeout_is_422(api, monkeypatch) -> None:
    client, _ = api
    monkeypatch.setattr(documents, "EXTRACTION_TIMEOUT_SECONDS", 0.05)

    def _slow_extract(data: bytes):
        time.sleep(0.3)
        return credit_certificate.parse_credit_certificate([KOREAN_CERTIFICATE])

    monkeypatch.setattr(documents, "extract_credit_certificate", _slow_extract)

    response = client.post(
        EXTRACT_URL, content=_build_pdf([KOREAN_CERTIFICATE]), headers=PDF_HEADERS
    )

    assert response.status_code == 422
    assert response.json() == {
        "detail": "문서 처리 시간이 초과되었습니다. 잠시 후 다시 시도해 주십시오."
    }


def test_error_body_does_not_leak_exception_text(api) -> None:
    client, _ = api
    response = client.post(
        EXTRACT_URL, content=_build_pdf([KOREAN_CERTIFICATE])[:120], headers=PDF_HEADERS
    )

    assert response.status_code == 400
    assert set(response.json()) == {"detail"}
    assert "Traceback" not in response.text
    assert "Exception" not in response.text
    assert "No /Root" not in response.text

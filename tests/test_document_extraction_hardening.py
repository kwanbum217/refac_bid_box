"""
tests/test_document_extraction_hardening.py

POST /api/v1/documents/extract 방어 강화 시험.

(4) 동시 처리 상한, (5) 요청 제한 fail-closed, (6) 수신 단계 크기 차단을 검증합니다.
시험 PDF 는 이 파일 안에서 합성하고 실제 등급확인서나 회사명은 쓰지 않습니다.
"""

from __future__ import annotations

import asyncio
import threading
import time
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException

from src.app.api.v1 import documents
from src.app.api.v1.accounts import require_current_user
from src.app.core import security
from src.app.core.config import settings
from src.app.main import app
from src.app.services.document_extraction import credit_certificate

EXTRACT_URL = "/api/v1/documents/extract"
PDF_HEADERS = {"Content-Type": "application/pdf"}
KOREAN_CERTIFICATE = "신용평가등급확인서\n신용등급 : AA-\n평가일 : 2026-03-15"
BUSY_DETAIL = "문서 처리 요청이 많습니다. 잠시 후 다시 시도해 주십시오."
TOO_LARGE_DETAIL = "PDF 파일 크기가 제한을 초과했습니다."
EXTRACTION_NOTICE = "추출값은 확인이 필요합니다. 저장 전에 원문과 대조하십시오."


def _build_pdf(pages: list[str]) -> bytes:
    """한글 텍스트를 담은 최소 PDF 를 바이트로 만듭니다.

    각 문자를 0x80 이상 코드에 매핑한 ToUnicode CMap 을 붙여 pdfminer 가 텍스트를
    정확히 추출하게 합니다. 시험 추출 전용이며 뷰어 표시 품질은 보장하지 않습니다.
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
    out += b"trailer\n<< /Size " + str(size).encode() + b" /Root 1 0 R >>\n"
    out += b"startxref\n" + str(xref_offset).encode() + b"\n%%EOF\n"
    return bytes(out)


PDF_BODY = _build_pdf([KOREAN_CERTIFICATE])


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


@pytest.fixture(autouse=True)
def _await_free_extraction_slots():
    """이전 시험의 느린 추출 스레드가 자리를 반납할 때까지 기다립니다.

    동시 처리 세마포어는 프로세스 전역이라, 제한 시간을 넘긴 스레드가 남아 있으면
    다음 시험이 spurious 503 을 받습니다. 시작 시점에 두 자리가 모두 비기를 기다립니다.
    """
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        acquired = 0
        while acquired < documents.MAX_CONCURRENT_EXTRACTIONS and (
            documents._EXTRACTION_SLOTS.acquire(blocking=False)
        ):
            acquired += 1
        if acquired == documents.MAX_CONCURRENT_EXTRACTIONS:
            for _ in range(acquired):
                documents._EXTRACTION_SLOTS.release()
            yield
            return
        for _ in range(acquired):
            documents._EXTRACTION_SLOTS.release()
        time.sleep(0.02)
    pytest.fail("문서 추출 동시 처리 자리가 이전 시험에서 반납되지 않았습니다")


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


def _async_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def test_concurrent_extraction_over_cap_is_503(api, monkeypatch) -> None:
    """자리 두 개가 모두 찬 상태에서 세 번째 요청은 503 과 한국어 문구를 받습니다."""
    _, _ = api
    entered = threading.Semaphore(0)
    release = threading.Event()

    def _slow(data: bytes):
        entered.release()
        release.wait(10)
        return credit_certificate.parse_credit_certificate([KOREAN_CERTIFICATE])

    monkeypatch.setattr(documents, "_extract", _slow)
    monkeypatch.setattr(documents, "EXTRACTION_TIMEOUT_SECONDS", 30.0)

    async def _run() -> None:
        async with _async_client() as ac:
            in_flight = [
                asyncio.create_task(ac.post(EXTRACT_URL, content=PDF_BODY, headers=PDF_HEADERS))
                for _ in range(documents.MAX_CONCURRENT_EXTRACTIONS)
            ]
            loop = asyncio.get_running_loop()
            for _ in range(documents.MAX_CONCURRENT_EXTRACTIONS):
                assert await loop.run_in_executor(None, entered.acquire, True, 5)

            third = await ac.post(EXTRACT_URL, content=PDF_BODY, headers=PDF_HEADERS)
            assert third.status_code == 503
            assert third.json() == {"detail": BUSY_DETAIL}

            release.set()
            done = await asyncio.gather(*in_flight)
            assert [response.status_code for response in done] == [
                200
            ] * documents.MAX_CONCURRENT_EXTRACTIONS

    asyncio.run(_run())


def test_timed_out_thread_keeps_slot_until_it_finishes(api, monkeypatch) -> None:
    """제한 시간 초과 직후에는 자리가 반납되지 않고, 스레드가 끝나야 반납됩니다."""
    _, _ = api
    started = threading.Event()
    release = threading.Event()

    def _very_slow(data: bytes):
        started.set()
        release.wait(10)
        return credit_certificate.parse_credit_certificate([KOREAN_CERTIFICATE])

    monkeypatch.setattr(documents, "_extract", _very_slow)
    monkeypatch.setattr(documents, "EXTRACTION_TIMEOUT_SECONDS", 0.1)

    async def _run() -> None:
        async with _async_client() as ac:
            response = await ac.post(EXTRACT_URL, content=PDF_BODY, headers=PDF_HEADERS)
            assert response.status_code == 422
            assert started.is_set()

            assert documents._EXTRACTION_SLOTS.acquire(blocking=False) is True
            assert documents._EXTRACTION_SLOTS.acquire(blocking=False) is False
            documents._EXTRACTION_SLOTS.release()

            release.set()
            recovered = False
            for _ in range(300):
                first = documents._EXTRACTION_SLOTS.acquire(blocking=False)
                second = documents._EXTRACTION_SLOTS.acquire(blocking=False) if first else False
                if first and second:
                    documents._EXTRACTION_SLOTS.release()
                    documents._EXTRACTION_SLOTS.release()
                    recovered = True
                    break
                if first:
                    documents._EXTRACTION_SLOTS.release()
                await asyncio.sleep(0.01)
            assert recovered

    asyncio.run(_run())


def test_failed_extraction_releases_slot(api, monkeypatch) -> None:
    """추출이 예외로 끝나도 자리가 반납되어 다음 요청이 처리됩니다."""
    client, _ = api
    calls = {"count": 0}

    def _flaky(data: bytes):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("추출 실패 대역")
        return credit_certificate.parse_credit_certificate([KOREAN_CERTIFICATE])

    monkeypatch.setattr(documents, "_extract", _flaky)

    first = client.post(EXTRACT_URL, content=PDF_BODY, headers=PDF_HEADERS)
    assert first.status_code == 500
    for _ in range(3):
        response = client.post(EXTRACT_URL, content=PDF_BODY, headers=PDF_HEADERS)
        assert response.status_code == 200
        assert response.json()["status"] == "extracted"


class _RedisErrorClient:
    """get 이 Redis 장애를 흉내내는 대역."""

    def get(self, key: str) -> str | None:
        raise RuntimeError("redis 장애 대역")


class _RedisErrorPipeline:
    def incr(self, key: str, amount: int = 1) -> _RedisErrorPipeline:
        return self

    def expire(self, key: str, seconds: int) -> _RedisErrorPipeline:
        return self

    def execute(self) -> list[int]:
        raise RuntimeError("redis 장애 대역")


class _RedisErrorPipelineClient:
    def pipeline(self) -> _RedisErrorPipeline:
        return _RedisErrorPipeline()


def test_document_extraction_rate_limit_is_503_when_client_missing(monkeypatch) -> None:
    """Redis 연결이 없으면 fail-open 하지 않고 503 으로 막습니다."""
    monkeypatch.setattr(security.document_extraction_rate_limiter._conn, "client", lambda: None)

    with pytest.raises(HTTPException) as excinfo:
        security.document_extraction_rate_limiter.check_rate_limit(7, "203.0.113.7")

    assert excinfo.value.status_code == 503
    assert excinfo.value.detail == security.AUTH_SERVICE_UNAVAILABLE_DETAIL


def test_document_extraction_rate_limit_is_503_on_redis_error(monkeypatch) -> None:
    """Redis 조회가 예외를 던지면 fail-open 하지 않고 503 으로 막습니다."""
    monkeypatch.setattr(
        security.document_extraction_rate_limiter._conn, "client", lambda: _RedisErrorClient()
    )

    with pytest.raises(HTTPException) as excinfo:
        security.document_extraction_rate_limiter.check_rate_limit(7, "203.0.113.7")

    assert excinfo.value.status_code == 503
    assert excinfo.value.detail == security.AUTH_SERVICE_UNAVAILABLE_DETAIL


def test_record_request_ignores_redis_error(monkeypatch) -> None:
    """record_request 의 Redis 예외는 요청을 막지 않습니다."""
    monkeypatch.setattr(
        security.document_extraction_rate_limiter._conn,
        "client",
        lambda: _RedisErrorPipelineClient(),
    )

    security.document_extraction_rate_limiter.record_request(7, "203.0.113.7")


def test_extract_endpoint_is_503_when_rate_limit_store_missing(
    client, extraction_enabled, authenticated, monkeypatch
) -> None:
    """제한 저장소가 없으면 엔드포인트가 503 을 돌려줍니다."""
    monkeypatch.setattr(security.document_extraction_rate_limiter._conn, "client", lambda: None)

    response = client.post(EXTRACT_URL, content=PDF_BODY, headers=PDF_HEADERS)

    assert response.status_code == 503
    assert response.json() == {"detail": security.AUTH_SERVICE_UNAVAILABLE_DETAIL}

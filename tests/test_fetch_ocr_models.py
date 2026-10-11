"""
tests/test_fetch_ocr_models.py

OCR 인식 모델 고정 다운로드 스크립트 시험.

실제 URL 로는 내려받지 않습니다. 대역 opener 로 바이트만 흘려보내 해시 대조,
건너뛰기, 실패 시 잔여 파일 제거를 확인하고, 스크립트의 고정 값이 런타임 검증기
(src/app/services/document_extraction/ocr.py)와 어긋나지 않는지 함께 봅니다.
"""

from __future__ import annotations

import hashlib
from io import BytesIO
from pathlib import Path

import pytest

from scripts import fetch_ocr_models
from src.app.services.document_extraction import ocr

PAYLOAD = b"fake model weights"


class _FakeResponse(BytesIO):
    """urlopen 응답 대역. 컨텍스트 매니저로만 쓰입니다."""

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *exc_info: object) -> bool:
        self.close()
        return False


def _opener(payload: bytes, requests: list[str] | None = None):
    def opener(request, timeout=None):
        if requests is not None:
            requests.append(request.full_url)
        return _FakeResponse(payload)

    return opener


def _forbidden_opener(*args, **kwargs):
    raise AssertionError("이미 검증된 파일은 다시 내려받지 않아야 합니다")


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def test_pinned_sources_match_runtime_verifier() -> None:
    assert {(name, sha) for name, _, sha in fetch_ocr_models.MODEL_SOURCES} == set(ocr.MODEL_FILES)
    assert fetch_ocr_models.MODEL_SOURCES[0][1].startswith("https://")


def test_fetch_model_downloads_and_saves(tmp_path: Path) -> None:
    requests: list[str] = []
    target = fetch_ocr_models.fetch_model(
        "model.onnx",
        "https://example.invalid/model.onnx",
        _sha256(PAYLOAD),
        tmp_path,
        opener=_opener(PAYLOAD, requests),
    )

    assert target == tmp_path / "model.onnx"
    assert target.read_bytes() == PAYLOAD
    assert requests == ["https://example.invalid/model.onnx"]
    assert list(tmp_path.glob("*.part")) == []


def test_fetch_model_skips_when_hash_matches(tmp_path: Path) -> None:
    (tmp_path / "model.onnx").write_bytes(PAYLOAD)

    target = fetch_ocr_models.fetch_model(
        "model.onnx",
        "https://example.invalid/model.onnx",
        _sha256(PAYLOAD),
        tmp_path,
        opener=_forbidden_opener,
    )

    assert target.read_bytes() == PAYLOAD


def test_fetch_model_rejects_hash_mismatch(tmp_path: Path) -> None:
    with pytest.raises(fetch_ocr_models.FetchError):
        fetch_ocr_models.fetch_model(
            "model.onnx",
            "https://example.invalid/model.onnx",
            "0" * 64,
            tmp_path,
            opener=_opener(PAYLOAD),
        )

    assert list(tmp_path.iterdir()) == []


def test_fetch_all_uses_pinned_sources(tmp_path: Path, monkeypatch) -> None:
    source = ("model.onnx", "https://example.invalid/model.onnx", _sha256(PAYLOAD))
    monkeypatch.setattr(fetch_ocr_models, "MODEL_SOURCES", (source,))
    requests: list[str] = []

    paths = fetch_ocr_models.fetch_all(tmp_path, opener=_opener(PAYLOAD, requests))

    assert paths == [tmp_path / "model.onnx"]
    assert requests == [source[1]]


def test_main_fails_without_leaving_partial_file(tmp_path: Path, monkeypatch) -> None:
    source = ("model.onnx", "https://example.invalid/model.onnx", "0" * 64)
    monkeypatch.setattr(fetch_ocr_models, "MODEL_SOURCES", (source,))
    monkeypatch.setattr(fetch_ocr_models.urllib.request, "urlopen", _opener(PAYLOAD))

    exit_code = fetch_ocr_models.main(["--dest", str(tmp_path)])

    assert exit_code == 1
    assert list(tmp_path.iterdir()) == []

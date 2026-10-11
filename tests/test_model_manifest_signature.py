"""서빙 모델 무결성 manifest 의 HMAC-SHA256 서명 계약 시험.

모델 디렉터리에 쓸 수 있는 공격자가 가중치와 manifest 를 함께 바꾸고 해시까지
다시 계산해도, 서명 키 없이는 통과하지 못해야 합니다. 환경별 규칙 (a)~(d) 와
오류 메시지에 키·서명 값이 드러나지 않는 것도 함께 고정합니다. 임시 디렉터리
가짜 모델만 쓰며 실제 서명 키나 운영 가중치는 쓰지 않습니다.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from pathlib import Path

import pytest

from src.app.core.config import settings
from src.ml.model_integrity import (
    MANIFEST_FILENAME,
    SIGNATURE_ALGORITHM,
    SIGNATURE_FIELD,
    ModelIntegrityError,
    load_manifest,
    verify_file,
    write_manifest,
)

MODEL_NAME = "signature_model"
SIGNING_KEY = "unit-test-signing-key-0123456789abcdef"


def _write_model_dir(root: Path, *, weights: bytes = b"model-weights-v1") -> Path:
    model_dir = root / MODEL_NAME
    model_dir.mkdir(parents=True, exist_ok=True)
    (model_dir / "model.bin").write_bytes(weights)
    (model_dir / "metadata.json").write_text(
        json.dumps({"name": MODEL_NAME, "version": "v1", "model_file": "model.bin"}),
        encoding="utf-8",
    )
    return model_dir


def _read_manifest(model_dir: Path) -> dict:
    return json.loads((model_dir / MANIFEST_FILENAME).read_text(encoding="utf-8"))


def _write_manifest_json(model_dir: Path, payload: dict) -> None:
    (model_dir / MANIFEST_FILENAME).write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _enable_signing(
    monkeypatch, *, key: str = SIGNING_KEY, environment: str = "development"
) -> None:
    monkeypatch.setattr(settings, "MODEL_MANIFEST_SIGNING_KEY", key)
    monkeypatch.setattr(settings, "ENVIRONMENT", environment)


@pytest.mark.parametrize("environment", ["development", "production", "staging"])
def test_signed_manifest_roundtrip(tmp_path, monkeypatch, environment):
    """키가 있으면 서명이 기록되고, 계약한 정규 바이트로 검증을 통과한다."""
    _enable_signing(monkeypatch, environment=environment)
    model_dir = _write_model_dir(tmp_path)

    payload = write_manifest(model_dir)

    signature = payload[SIGNATURE_FIELD]
    assert signature["alg"] == SIGNATURE_ALGORITHM
    stored = _read_manifest(model_dir)
    canonical = json.dumps(
        {"schema": stored["schema"], "files": stored["files"]},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    expected = hmac.new(SIGNING_KEY.encode("utf-8"), canonical, hashlib.sha256).hexdigest()
    assert stored[SIGNATURE_FIELD] == {"alg": SIGNATURE_ALGORITHM, "value": expected}

    assert load_manifest(model_dir) == stored
    verify_file(model_dir, "model.bin")


@pytest.mark.parametrize("environment", ["development", "production", "staging"])
def test_forged_manifest_with_recomputed_hash_is_rejected(tmp_path, monkeypatch, environment):
    """가중치와 해시를 함께 바꾼 위조 manifest 는 서명 불일치로 거부된다."""
    _enable_signing(monkeypatch, environment=environment)
    model_dir = _write_model_dir(tmp_path)
    write_manifest(model_dir)

    forged = b"forged-weights"
    (model_dir / "model.bin").write_bytes(forged)
    manifest = _read_manifest(model_dir)
    manifest["files"]["model.bin"] = {
        "sha256": hashlib.sha256(forged).hexdigest(),
        "bytes": len(forged),
    }
    _write_manifest_json(model_dir, manifest)

    with pytest.raises(ModelIntegrityError, match="서명이 일치하지 않습니다"):
        verify_file(model_dir, "model.bin")


@pytest.mark.parametrize("environment", ["development", "production", "staging"])
def test_tampered_signature_value_is_rejected(tmp_path, monkeypatch, environment):
    """서명 값만 바꿔도 환경과 무관하게 거부된다."""
    _enable_signing(monkeypatch, environment=environment)
    model_dir = _write_model_dir(tmp_path)
    write_manifest(model_dir)

    manifest = _read_manifest(model_dir)
    value = manifest[SIGNATURE_FIELD]["value"]
    manifest[SIGNATURE_FIELD]["value"] = ("0" if value[0] != "0" else "1") + value[1:]
    _write_manifest_json(model_dir, manifest)

    with pytest.raises(ModelIntegrityError, match="서명이 일치하지 않습니다"):
        verify_file(model_dir, "model.bin")


@pytest.mark.parametrize("environment", ["production", "staging"])
def test_protected_environment_without_key_is_rejected(tmp_path, monkeypatch, environment):
    """규칙 (a): production·staging 에서 서명 키가 비어 있으면 거부한다."""
    _enable_signing(monkeypatch, key="", environment=environment)
    model_dir = _write_model_dir(tmp_path)
    write_manifest(model_dir)

    with pytest.raises(ModelIntegrityError, match="서명 키가 없어"):
        verify_file(model_dir, "model.bin")


@pytest.mark.parametrize("environment", ["production", "staging"])
def test_protected_environment_rejects_unsigned_manifest(tmp_path, monkeypatch, environment):
    """규칙 (b): production·staging 에서 서명 없는 manifest 는 거부한다."""
    monkeypatch.setattr(settings, "MODEL_MANIFEST_SIGNING_KEY", "")
    model_dir = _write_model_dir(tmp_path)
    write_manifest(model_dir)
    _enable_signing(monkeypatch, environment=environment)

    with pytest.raises(ModelIntegrityError, match="서명이 없어"):
        load_manifest(model_dir)
    with pytest.raises(ModelIntegrityError, match="서명이 없어"):
        verify_file(model_dir, "model.bin")


def test_development_without_key_warns_and_passes(tmp_path, monkeypatch, caplog):
    """규칙 (d): development 에서 키가 없으면 경고 후 해시 검증만 한다."""
    _enable_signing(monkeypatch, key="", environment="development")
    model_dir = _write_model_dir(tmp_path)
    write_manifest(model_dir)

    with caplog.at_level(logging.WARNING, logger="src.ml.model_integrity"):
        verify_file(model_dir, "model.bin")

    assert any("서명 키가 없어" in record.getMessage() for record in caplog.records)


def test_development_with_key_but_unsigned_manifest_warns_and_passes(tmp_path, monkeypatch, caplog):
    """규칙 (d): development 에서 서명이 없으면 경고 후 해시 검증만 한다."""
    monkeypatch.setattr(settings, "MODEL_MANIFEST_SIGNING_KEY", "")
    model_dir = _write_model_dir(tmp_path)
    write_manifest(model_dir)
    monkeypatch.setattr(settings, "MODEL_MANIFEST_SIGNING_KEY", SIGNING_KEY)

    with caplog.at_level(logging.WARNING, logger="src.ml.model_integrity"):
        verify_file(model_dir, "model.bin")

    assert any("서명이 없어" in record.getMessage() for record in caplog.records)


def test_signed_manifest_is_reproducible(tmp_path, monkeypatch):
    """같은 파일 세트를 두 번 봉인하면 서명을 포함해 같은 바이트가 나온다."""
    _enable_signing(monkeypatch)
    model_dir = _write_model_dir(tmp_path)

    first = write_manifest(model_dir)
    first_bytes = (model_dir / MANIFEST_FILENAME).read_bytes()
    second = write_manifest(model_dir)

    assert first == second
    assert (model_dir / MANIFEST_FILENAME).read_bytes() == first_bytes


def test_errors_and_manifest_do_not_leak_key_or_signature(tmp_path, monkeypatch, caplog):
    """오류 메시지·로그·manifest 어디에도 키 값과 서명 값이 드러나지 않는다."""
    _enable_signing(monkeypatch)
    model_dir = _write_model_dir(tmp_path)
    write_manifest(model_dir)

    manifest = _read_manifest(model_dir)
    signature_value = manifest[SIGNATURE_FIELD]["value"]
    manifest[SIGNATURE_FIELD]["value"] = (
        "0" if signature_value[0] != "0" else "1"
    ) + signature_value[1:]
    _write_manifest_json(model_dir, manifest)

    with (
        caplog.at_level(logging.WARNING, logger="src.ml.model_integrity"),
        pytest.raises(ModelIntegrityError) as excinfo,
    ):
        verify_file(model_dir, "model.bin")

    message = str(excinfo.value)
    manifest_text = (model_dir / MANIFEST_FILENAME).read_text(encoding="utf-8")
    logs = "\n".join(record.getMessage() for record in caplog.records)
    assert SIGNING_KEY not in message
    assert SIGNING_KEY not in manifest_text
    assert SIGNING_KEY not in logs
    assert signature_value not in message

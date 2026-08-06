"""모델 가중치 번들 배포 스크립트 회귀 테스트.

배포 경로가 없으면 새 장비에서 예측 API 가 뜨지 않고 G1 검증도 통과하지
못합니다. 여기서 고정하는 것은 번들이 **무손실로 왕복하는가**, 그리고
**손상된 번들을 배치하지 않는가** 입니다.
"""

from __future__ import annotations

import gzip
import importlib
import json
import tarfile
from pathlib import Path

import pytest

sync_model_files = importlib.import_module("scripts.sync_model_files")


@pytest.fixture()
def asset_roots(tmp_path, monkeypatch):
    """가중치 3종 경로를 임시 디렉터리로 돌립니다."""
    files = tmp_path / "model_files"
    backups = tmp_path / "model_backups"
    metrics = tmp_path / "model_metrics"

    (files / "demo_model").mkdir(parents=True)
    (files / "demo_model" / "model.bin").write_bytes(b"weights-payload")
    (files / "demo_model" / "metadata.json").write_text('{"name": "demo"}', encoding="utf-8")
    # 재생성되는 캐시는 번들에서 빠져야 합니다.
    (files / "demo_model" / "__pycache__").mkdir()
    (files / "demo_model" / "__pycache__" / "x.pyc").write_bytes(b"cache")

    (backups / "demo_model").mkdir(parents=True)
    (backups / "demo_model" / "model.bin").write_bytes(b"original-weights")

    metrics.mkdir(parents=True)
    (metrics / "demo_model.json").write_text('{"mae": 1.0}', encoding="utf-8")

    monkeypatch.setattr(
        sync_model_files,
        "BUNDLE_MEMBERS",
        (
            ("model_files", lambda: files),
            ("model_backups", lambda: backups),
            ("model_metrics", lambda: metrics),
        ),
    )
    return files, backups, metrics


def _export(tmp_path) -> Path:
    bundle = tmp_path / "bundle.tar.gz"
    args = type("Args", (), {"output": bundle})()
    assert sync_model_files.cmd_export(args) == 0
    return bundle


def test_export_includes_backups_and_metrics(asset_roots, tmp_path):
    """백업을 빼면 승격된 모델의 G1 기준선을 대조할 수 없습니다."""
    bundle = _export(tmp_path)
    manifest = sync_model_files.read_bundle_manifest(bundle)
    names = set(manifest["files"])

    assert "model_files/demo_model/model.bin" in names
    assert "model_backups/demo_model/model.bin" in names
    assert "model_metrics/demo_model.json" in names


def test_export_excludes_pycache(asset_roots, tmp_path):
    bundle = _export(tmp_path)
    manifest = sync_model_files.read_bundle_manifest(bundle)
    assert not any("__pycache__" in name for name in manifest["files"])


def test_bundle_keys_use_posix_separator(asset_roots, tmp_path):
    """Windows 에서 만든 번들을 macOS 에서 풀 수 있어야 합니다."""
    bundle = _export(tmp_path)
    manifest = sync_model_files.read_bundle_manifest(bundle)
    assert all("\\" not in name for name in manifest["files"])


def test_roundtrip_preserves_content(asset_roots, tmp_path, monkeypatch):
    files, backups, metrics = asset_roots
    bundle = _export(tmp_path)

    dest = tmp_path / "restored"
    monkeypatch.setattr(
        sync_model_files,
        "BUNDLE_MEMBERS",
        (
            ("model_files", lambda: dest / "model_files"),
            ("model_backups", lambda: dest / "model_backups"),
            ("model_metrics", lambda: dest / "model_metrics"),
        ),
    )
    args = type("Args", (), {"input": bundle, "force": False})()
    assert sync_model_files.cmd_import(args) == 0

    assert (dest / "model_files" / "demo_model" / "model.bin").read_bytes() == b"weights-payload"
    assert (dest / "model_backups" / "demo_model" / "model.bin").read_bytes() == b"original-weights"
    assert json.loads((dest / "model_metrics" / "demo_model.json").read_text()) == {"mae": 1.0}


def test_verify_detects_tampered_payload(asset_roots, tmp_path):
    """내용이 바뀐 번들은 통과하면 안 됩니다."""
    bundle = _export(tmp_path)
    manifest = sync_model_files.read_bundle_manifest(bundle)

    tampered = tmp_path / "tampered.tar.gz"
    with tarfile.open(bundle, "r:gz") as src, tarfile.open(tampered, "w:gz") as dst:
        for member in src.getmembers():
            handle = src.extractfile(member)
            payload = handle.read() if handle else b""
            if member.name == "model_files/demo_model/model.bin":
                payload = b"corrupted-payload"
                member.size = len(payload)
            import io

            dst.addfile(member, io.BytesIO(payload))
    # 사이드카는 원본 것을 그대로 두어 내용 위조만 검사합니다.
    sidecar = tampered.with_suffix(tampered.suffix + ".sha256")
    sidecar.write_text(f"{sync_model_files.sha256_file(tampered)}  {tampered.name}\n")

    args = type("Args", (), {"input": tampered})()
    assert sync_model_files.cmd_verify(args) == 1
    assert manifest["files"]["model_files/demo_model/model.bin"]["sha256"]


def test_verify_detects_transport_corruption(asset_roots, tmp_path):
    """전송 중 손상은 사이드카 체크섬에서 걸려야 합니다."""
    bundle = _export(tmp_path)
    raw = bundle.read_bytes()
    bundle.write_bytes(raw[:-64])

    args = type("Args", (), {"input": bundle})()
    assert sync_model_files.cmd_verify(args) == 1


def test_import_refuses_overwrite_without_force(asset_roots, tmp_path):
    """기존 서빙본을 조용히 덮으면 안 됩니다."""
    files, _, _ = asset_roots
    bundle = _export(tmp_path)

    args = type("Args", (), {"input": bundle, "force": False})()
    assert sync_model_files.cmd_import(args) == 1
    # 중단했으므로 기존 파일은 그대로입니다.
    assert (files / "demo_model" / "model.bin").read_bytes() == b"weights-payload"


def test_import_rejects_corrupted_bundle_before_writing(asset_roots, tmp_path, monkeypatch):
    """손상된 번들은 배치 전에 막아야 합니다. 풀고 나서 알면 이미 늦습니다."""
    bundle = _export(tmp_path)
    with gzip.open(bundle, "rb") as handle:
        raw = handle.read()
    bundle.write_bytes(gzip.compress(raw[: len(raw) // 2]))

    dest = tmp_path / "untouched"
    monkeypatch.setattr(
        sync_model_files,
        "BUNDLE_MEMBERS",
        (("model_files", lambda: dest / "model_files"),),
    )
    args = type("Args", (), {"input": bundle, "force": True})()
    assert sync_model_files.cmd_import(args) == 1
    assert not dest.exists()

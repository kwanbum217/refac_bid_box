from pathlib import Path

import pytest


def _skip_if_missing(path: Path, reason: str) -> None:
    if not path.exists():
        pytest.skip(reason)


def test_data_assets_manifest_exists():
    manifest = Path("data/backups/data_assets_checksums.json")
    _skip_if_missing(manifest, "로컬 데이터 자산 manifest 없음 (CI에서는 데이터 보존 검증 생략)")
    assert "quantum_leap_v25_pro" in manifest.read_text(encoding="utf-8")


def test_model_bin_files_exist():
    root = Path("data/model_files")
    first_model = root / "v25" / "model.bin"
    _skip_if_missing(first_model, "로컬 model.bin 없음 (CI에서는 데이터 보존 검증 생략)")
    for model in ("v25", "quantum_leap_v25_pro", "ssh_hist_premium", "v13_hybrid"):
        assert (root / model / "model.bin").exists()


def test_chroma_db_exists():
    chroma = Path("chroma_db")
    dirs = [p for p in chroma.iterdir() if p.is_dir()] if chroma.exists() else []
    if not dirs:
        pytest.skip("로컬 chroma_db 없음 (CI에서는 데이터 보존 검증 생략)")
    assert len(dirs) >= 1

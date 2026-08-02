"""
tests/test_data_preservation.py

G1(데이터 무손실) 검증. 로컬 데이터 자산이 실재하는지 단언합니다.

자산이 없으면 반드시 실패해야 합니다. 없을 때 skip 으로 넘어가면
자산이 사라진 상태에서도 초록으로 나와 검증 자체가 무의미해집니다.
데이터 자산이 없는 환경(CI 등)에서는 아래 마커로 제외하십시오.

    pytest -m "not data_assets"
"""

from pathlib import Path

import pytest

pytestmark = pytest.mark.data_assets


def test_data_assets_manifest_exists():
    manifest = Path("data/backups/data_assets_checksums.json")
    assert manifest.exists(), f"데이터 자산 manifest 없음: {manifest}"
    assert "quantum_leap_v25_pro" in manifest.read_text(encoding="utf-8")


def test_model_bin_files_exist():
    root = Path("data/model_files")
    for model in ("v25", "quantum_leap_v25_pro", "ssh_hist_premium", "v13_hybrid"):
        assert (root / model / "model.bin").exists(), f"모델 가중치 없음: {model}/model.bin"


def test_chroma_db_exists():
    chroma = Path("chroma_db")
    assert chroma.exists(), "chroma_db 디렉터리 없음"
    dirs = [p for p in chroma.iterdir() if p.is_dir()]
    assert len(dirs) >= 1, "chroma_db 안에 컬렉션 디렉터리가 없음"

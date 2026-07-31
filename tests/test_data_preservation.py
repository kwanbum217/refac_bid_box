from pathlib import Path


def test_data_assets_manifest_exists():
    manifest = Path("data/backups/data_assets_checksums.json")
    assert manifest.exists()
    assert "quantum_leap_v25_pro" in manifest.read_text(encoding="utf-8")


def test_model_bin_files_exist():
    root = Path("data/model_files")
    for model in ("v25", "quantum_leap_v25_pro", "ssh_hist_premium", "v13_hybrid"):
        assert (root / model / "model.bin").exists()


def test_chroma_db_exists():
    chroma = Path("chroma_db")
    assert chroma.exists()
    dirs = [p for p in chroma.iterdir() if p.is_dir()]
    assert len(dirs) >= 1

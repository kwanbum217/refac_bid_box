#!/usr/bin/env python3
"""
bid_box 원본 데이터 자산 이전 및 SHA256 체크섬 기록 스크립트.

사용:
  python3 scripts/import_data_assets.py [--source /path/to/bid_box]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE = PROJECT_ROOT.parent / "bid_box"

MODEL_NAMES = ("v25", "quantum_leap_v25_pro", "ssh_hist_premium", "v13_hybrid")
WEIGHT_PATTERNS = ("model.bin", "v25_lgbm_final.joblib", "v25_cat_final.bin", "metadata.json", "preprocess.py", "champion_summary.json")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def copy_tree(source: Path, dest: Path) -> None:
    if not source.exists():
        raise FileNotFoundError(f"원본 경로 없음: {source}")
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, dest, dirs_exist_ok=True)


def collect_checksums(base: Path, relative_prefix: str) -> dict[str, dict]:
    records: dict[str, dict] = {}
    if not base.exists():
        return records
    for path in sorted(base.rglob("*")):
        if not path.is_file():
            continue
        rel = str(path.relative_to(PROJECT_ROOT))
        records[rel] = {
            "sha256": sha256_file(path),
            "bytes": path.stat().st_size,
        }
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description="bid_box 데이터 자산 이전")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    args = parser.parse_args()
    source_root: Path = args.source

    model_src = source_root / "apps" / "predictions" / "model_files"
    chroma_src = source_root / "chroma_db"
    model_dest = PROJECT_ROOT / "data" / "model_files"
    chroma_dest = PROJECT_ROOT / "chroma_db"
    backup_dir = PROJECT_ROOT / "data" / "backups"

    print(f"[1/3] ML model_files 복사: {model_src} -> {model_dest}")
    copy_tree(model_src, model_dest)

    print(f"[2/3] chroma_db 복사: {chroma_src} -> {chroma_dest}")
    copy_tree(chroma_src, chroma_dest)

    print("[3/3] SHA256 체크섬 manifest 생성...")
    manifest = {
        "generated_at": datetime.now(UTC).isoformat(),
        "source_repo": str(source_root),
        "models": {},
        "chroma_db": collect_checksums(chroma_dest, "chroma_db"),
    }
    for model in MODEL_NAMES:
        model_dir = model_dest / model
        if model_dir.exists():
            manifest["models"][model] = {
                name: {
                    "sha256": sha256_file(model_dir / name),
                    "bytes": (model_dir / name).stat().st_size,
                }
                for name in WEIGHT_PATTERNS
                if (model_dir / name).exists()
            }

    backup_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = backup_dir / "data_assets_checksums.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"      manifest: {manifest_path.relative_to(PROJECT_ROOT)}")
    print(f"      models: {len(manifest['models'])} / chroma files: {len(manifest['chroma_db'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

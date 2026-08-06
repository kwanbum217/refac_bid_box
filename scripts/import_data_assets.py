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
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE = PROJECT_ROOT.parent / "bid_box"

MODEL_NAMES = ("v25", "quantum_leap_v25_pro", "ssh_hist_premium", "v13_hybrid")
WEIGHT_PATTERNS = (
    "model.bin",
    "v25_lgbm_final.joblib",
    "v25_cat_final.bin",
    "metadata.json",
    "preprocess.py",
    "champion_summary.json",
)


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
        # 매니페스트 키는 as_posix 로 고정합니다. str() 은 Windows 에서
        # 역슬래시를 내므로, 한 플랫폼에서 만든 매니페스트를 다른 플랫폼에서
        # 대조할 수 없게 됩니다 (G1 검증이 플랫폼에 묶입니다).
        rel = (Path(relative_prefix) / path.relative_to(base)).as_posix()
        records[rel] = {
            "sha256": sha256_file(path),
            "bytes": path.stat().st_size,
        }
    return records


def collect_chroma_baseline(chroma_dir: Path) -> dict:
    sqlite_path = chroma_dir / "chroma.sqlite3"
    connection = sqlite3.connect(f"file:{sqlite_path}?mode=ro", uri=True)
    try:
        cursor = connection.cursor()
        cursor.execute("SELECT name FROM collections ORDER BY name")
        collections = [row[0] for row in cursor.fetchall()]
        cursor.execute("SELECT COUNT(*) FROM embeddings")
        embedding_count = int(cursor.fetchone()[0])
    finally:
        connection.close()
    return {
        "collections": collections,
        "embedding_count": embedding_count,
        "sqlite_sha256": sha256_file(sqlite_path),
    }


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
    chroma_source_backup = backup_dir / "chroma_source"

    print(f"[1/4] ML model_files 복사: {model_src} -> {model_dest}")
    copy_tree(model_src, model_dest)

    backup_dir.mkdir(parents=True, exist_ok=True)
    if chroma_source_backup.exists():
        print(f"[2/4] ChromaDB 원본 스냅샷 유지: {chroma_source_backup}")
    else:
        print(f"[2/4] ChromaDB 원본 스냅샷 생성: {chroma_src} -> {chroma_source_backup}")
        copy_tree(chroma_src, chroma_source_backup)

    print(f"[3/4] 운영 chroma_db 복사: {chroma_src} -> {chroma_dest}")
    copy_tree(chroma_src, chroma_dest)

    print("[4/4] SHA256 체크섬 manifest 생성...")
    manifest = {
        "generated_at": datetime.now(UTC).isoformat(),
        "source_repo": str(source_root),
        "chroma_baseline": collect_chroma_baseline(chroma_source_backup),
        "models": {},
        "chroma_db": collect_checksums(chroma_source_backup, "chroma_db"),
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

    manifest_path = backup_dir / "data_assets_checksums.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"      manifest: {manifest_path.relative_to(PROJECT_ROOT)}")
    print(f"      models: {len(manifest['models'])} / chroma files: {len(manifest['chroma_db'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

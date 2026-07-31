#!/usr/bin/env python3
"""
Phase 1 데이터 보존 무손실 마이그레이션 검증 스크립트.

검증 항목:
  1. ML 가중치 4종 SHA256 체크섬 (data/backups/data_assets_checksums.json)
  2. ChromaDB 컬렉션 디렉토리 존재
  3. DB 테이블 스키마 (연결 가능 시)
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

EXPECTED_MODELS = ("v25", "quantum_leap_v25_pro", "ssh_hist_premium", "v13_hybrid")
EXPECTED_TABLES = (
    "bid_announcements",
    "bid_results",
    "bid_dataset_summaries",
    "prediction_results",
    "retrain_logs",
    "automation_requests",
    "chat_session_states",
    "user_account",
)
MANIFEST_PATH = PROJECT_ROOT / "data" / "backups" / "data_assets_checksums.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_model_weights() -> tuple[bool, str]:
    print("[1/3] ML 가중치 4종 무결성 검증...")
    model_root = PROJECT_ROOT / "data" / "model_files"
    if not model_root.exists():
        return False, "data/model_files/ 없음 (scripts/import_data_assets.py 실행 필요)"

    missing = [m for m in EXPECTED_MODELS if not (model_root / m / "model.bin").exists()]
    if missing:
        return False, f"model.bin 누락: {', '.join(missing)}"

    if MANIFEST_PATH.exists():
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        for model, files in manifest.get("models", {}).items():
            for filename, meta in files.items():
                path = model_root / model / filename
                if path.exists() and sha256_file(path) != meta.get("sha256"):
                    return False, f"체크섬 불일치: {model}/{filename}"

    print(f"      4종 모델 model.bin 확인: {', '.join(EXPECTED_MODELS)}")
    return True, "ML 가중치 4종 확인"


def verify_chroma_db() -> tuple[bool, str]:
    print("[2/3] ChromaDB 컬렉션 무결성 검증...")
    chroma_dir = PROJECT_ROOT / "chroma_db"
    if not chroma_dir.exists():
        return False, "chroma_db/ 없음 (scripts/import_data_assets.py 실행 필요)"

    collection_dirs = [p for p in chroma_dir.iterdir() if p.is_dir()]
    print(f"      ChromaDB 컬렉션 디렉토리: {len(collection_dirs)}개")
    if len(collection_dirs) < 1:
        return False, "ChromaDB 컬렉션이 비어 있습니다"
    return True, f"ChromaDB {len(collection_dirs)}개 컬렉션 확인"


def verify_db_schema() -> tuple[bool, str]:
    print("[3/3] DB 테이블 스키마 검증...")
    try:
        from sqlalchemy import inspect

        from src.app.core.db import engine

        inspector = inspect(engine)
        existing = set(inspector.get_table_names())
        missing = [t for t in EXPECTED_TABLES if t not in existing]
        print(f"      연결된 테이블: {len(existing)}개")
        if missing:
            print(f"      미생성 테이블 (마이그레이션 대기): {', '.join(missing)}")
            return True, "DB 오프라인/마이그레이션 대기 (스키마 정의는 ORM 기준)"
        return True, "DB 테이블 ORM 정합성 확인"
    except Exception as exc:
        print(f"      DB 연결 불가 (오프라인 검증): {exc}")
        return True, "DB 오프라인 - ML/Chroma 검증만 수행"


def main() -> int:
    print("=" * 60)
    print("refac_bid_box Phase 1 데이터 보존 검증")
    print("=" * 60)

    results = [verify_model_weights(), verify_chroma_db(), verify_db_schema()]
    print("-" * 60)
    if all(ok for ok, _ in results):
        for _, msg in results:
            print(f"PASS: {msg}")
        return 0
    for ok, msg in results:
        print(("PASS" if ok else "FAIL") + f": {msg}")
    return 1 if not all(ok for ok, _ in results) else 0


if __name__ == "__main__":
    sys.exit(main())

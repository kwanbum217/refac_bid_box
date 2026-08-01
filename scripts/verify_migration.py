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
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

EXPECTED_MODELS = ("v25", "quantum_leap_v25_pro", "ssh_hist_premium", "v13_hybrid")
EXPECTED_TABLES = (
    # 원본 bid_box 에서 보존해야 하는 테이블
    "accounts_customuser",
    "automation_requests",
    "automation_subscriptions",
    "bid_announcements",
    "bid_dataset_summaries",
    "bid_results",
    "chat_session_states",
    "knowledge_base_status",
    "pipeline_executions",
    "prediction_results",
    # 리팩토링에서 추가된 MLOps 테이블
    "retrain_logs",
)
MANIFEST_PATH = PROJECT_ROOT / "data" / "backups" / "data_assets_checksums.json"

# 유실 전 원본 DB 기준선 (bid_box/.django_cache 2026-06-07 집계 스냅샷)
BASELINE_ROW_COUNTS = {
    "bid_announcements": 1_698_014,
    "bid_results": 2_996_476,
}
MIN_ROW_COUNT_RATIO = 95.0


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_model_weights() -> tuple[bool, str]:
    print("[1/4] ML 가중치 4종 무결성 검증...")
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
    """디렉토리 개수가 아니라 실제 컬렉션과 임베딩 건수를 셉니다.

    chroma_db/ 하위 UUID 디렉토리에는 삭제된 옛 컬렉션 잔재가 남아 있어,
    디렉토리 수를 컬렉션 수로 보고하면 실제보다 크게 부풀려집니다.
    """
    print("[2/4] ChromaDB 컬렉션 무결성 검증...")
    chroma_dir = PROJECT_ROOT / "chroma_db"
    sqlite_path = chroma_dir / "chroma.sqlite3"
    if not sqlite_path.exists():
        return False, "chroma_db/chroma.sqlite3 없음 (scripts/import_data_assets.py 실행 필요)"

    connection = sqlite3.connect(f"file:{sqlite_path}?mode=ro", uri=True)
    try:
        cursor = connection.cursor()
        cursor.execute("SELECT name FROM collections")
        collections = [row[0] for row in cursor.fetchall()]
        cursor.execute("SELECT COUNT(*) FROM embeddings")
        embedding_count = cursor.fetchone()[0]
    finally:
        connection.close()

    print(f"      컬렉션: {len(collections)}개 ({', '.join(collections) or '-'})")
    print(f"      임베딩: {embedding_count}건")
    if not collections or embedding_count <= 0:
        return False, "ChromaDB 컬렉션 또는 임베딩이 비어 있습니다"
    return True, f"ChromaDB {len(collections)}개 컬렉션 / 임베딩 {embedding_count}건 확인"


def verify_db_schema() -> tuple[bool, str]:
    """스키마 존재 여부를 실제로 판정합니다.

    이전 구현은 테이블이 없어도, 연결이 실패해도 무조건 통과를 반환해
    행 수 대조 없이 '무손실 검증 통과'로 보고되는 결함이 있었습니다.
    """
    print("[3/4] DB 테이블 스키마 검증...")
    try:
        from sqlalchemy import inspect

        from src.app.core.db import engine

        inspector = inspect(engine)
        existing = set(inspector.get_table_names())
    except Exception as exc:
        print(f"      DB 연결 실패: {exc}")
        return False, f"DB 연결 실패로 스키마를 검증하지 못했습니다: {exc}"

    missing = [t for t in EXPECTED_TABLES if t not in existing]
    print(f"      연결된 테이블: {len(existing)}개")
    if missing:
        print(f"      누락 테이블: {', '.join(missing)}")
        return False, f"필수 테이블 누락: {', '.join(missing)}"
    return True, "DB 테이블 ORM 정합성 확인"


def verify_row_counts() -> tuple[bool, str]:
    """핵심 테이블의 실제 행 수를 세고 기준선과 대조합니다."""
    print("[4/4] 데이터 행 수 검증...")
    try:
        from sqlalchemy import func, select

        from src.app.core.db import SessionLocal
        from src.app.models.bids import BidAnnouncement, BidResult
    except Exception as exc:
        return False, f"행 수 검증 준비 실패: {exc}"

    session = SessionLocal()
    try:
        announcements = session.scalar(select(func.count(BidAnnouncement.id))) or 0
        results = session.scalar(select(func.count(BidResult.id))) or 0
    except Exception as exc:
        print(f"      행 수 조회 실패: {exc}")
        return False, f"행 수 조회 실패: {exc}"
    finally:
        session.close()

    failures = []
    for label, actual, baseline in (
        ("bid_announcements", announcements, BASELINE_ROW_COUNTS["bid_announcements"]),
        ("bid_results", results, BASELINE_ROW_COUNTS["bid_results"]),
    ):
        ratio = (actual / baseline * 100) if baseline else 0.0
        print(f"      {label}: {actual:,}행 (기준선 {baseline:,} 대비 {ratio:.1f}%)")
        if ratio < MIN_ROW_COUNT_RATIO:
            failures.append(f"{label} {ratio:.1f}%")

    if failures:
        return False, f"기준선 대비 행 수 부족: {', '.join(failures)}"
    return True, f"공고 {announcements:,}행 / 낙찰 {results:,}행 확인"


def main() -> int:
    print("=" * 60)
    print("refac_bid_box Phase 1 데이터 보존 검증")
    print("=" * 60)

    results = [
        verify_model_weights(),
        verify_chroma_db(),
        verify_db_schema(),
        verify_row_counts(),
    ]
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

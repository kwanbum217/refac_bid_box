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
import os
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
ASSET_ROOT = Path(os.environ.get("DATA_ASSET_ROOT", PROJECT_ROOT))
CHROMA_DB_PATH = Path(os.environ.get("CHROMA_DB_PATH", ASSET_ROOT / "chroma_db"))
CHROMA_SOURCE_BACKUP_PATH = Path(
    os.environ.get(
        "CHROMA_SOURCE_BACKUP_PATH",
        ASSET_ROOT / "data" / "backups" / "chroma_source",
    )
)

# 유실 전 원본 DB 기준선 (bid_box/.django_cache 2026-06-07 집계 스냅샷)
BASELINE_ROW_COUNTS = {
    "bid_announcements": 1_698_014,
    "bid_results": 2_996_476,
}
MIN_ROW_COUNT_RATIO = 100.0


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_manifest() -> dict:
    if not MANIFEST_PATH.exists():
        raise FileNotFoundError(f"체크섬 manifest 없음: {MANIFEST_PATH}")
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def read_chroma_stats(sqlite_path: Path) -> tuple[list[str], int]:
    connection = sqlite3.connect(f"file:{sqlite_path}?mode=ro", uri=True)
    try:
        cursor = connection.cursor()
        cursor.execute("SELECT name FROM collections ORDER BY name")
        collections = [row[0] for row in cursor.fetchall()]
        cursor.execute("SELECT COUNT(*) FROM embeddings")
        embedding_count = int(cursor.fetchone()[0])
    finally:
        connection.close()
    return collections, embedding_count


def verify_checksum_records(
    root: Path,
    records: dict[str, dict],
    *,
    prefix: str,
) -> list[str]:
    failures: list[str] = []
    for manifest_name, meta in records.items():
        if not manifest_name.startswith(prefix):
            failures.append(f"manifest 경로 오류: {manifest_name}")
            continue
        path = root / manifest_name.removeprefix(prefix)
        if not path.is_file():
            failures.append(f"파일 누락: {path}")
            continue
        expected = meta.get("sha256")
        if not expected or sha256_file(path) != expected:
            failures.append(f"체크섬 불일치: {path}")
    return failures


def verify_model_weights() -> tuple[bool, str]:
    print("[1/4] ML 가중치 4종 무결성 검증...")
    model_root = ASSET_ROOT / "data" / "model_files"
    backup_root = ASSET_ROOT / "data" / "model_backups"
    if not model_root.exists():
        return False, "data/model_files/ 없음 (scripts/import_data_assets.py 실행 필요)"

    try:
        manifest = load_manifest()
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        return False, str(exc)

    manifest_models = manifest.get("models", {})
    for model in EXPECTED_MODELS:
        records = manifest_models.get(model)
        if not records or "model.bin" not in records:
            return False, f"manifest 모델 기준선 누락: {model}"
        serving_failures = verify_checksum_records(
            model_root / model,
            {f"{model}/{name}": meta for name, meta in records.items()},
            prefix=f"{model}/",
        )
        if not serving_failures:
            continue

        # 재학습 champion을 승격하면 운영 슬롯은 의도적으로 원본과 달라집니다.
        # promotion은 직전 서빙본을 model_backups에 보존하므로, 원본 기준선은
        # 그쪽에서 계속 검증해야 합니다. 둘 다 어긋날 때만 G1 실패입니다.
        backup_failures = verify_checksum_records(
            backup_root / model,
            {f"{model}/{name}": meta for name, meta in records.items()},
            prefix=f"{model}/",
        )
        if backup_failures:
            return False, f"{serving_failures[0]}; 백업도 불일치: {backup_failures[0]}"
        print(f"      {model}: 운영본 교체, 원본 백업 체크섬 일치")

    print(f"      4종 모델 manifest 체크섬 일치: {', '.join(EXPECTED_MODELS)}")
    return True, "ML 가중치 4종 체크섬 일치"


def verify_chroma_db() -> tuple[bool, str]:
    """원본 스냅샷을 보존하고 운영 ChromaDB의 구조를 별도로 검증합니다.

    chroma_db/ 하위 UUID 디렉토리에는 삭제된 옛 컬렉션 잔재가 남아 있어,
    디렉토리 수를 컬렉션 수로 보고하면 실제보다 크게 부풀려집니다.
    """
    print("[2/4] ChromaDB 컬렉션 무결성 검증...")
    operational_sqlite = CHROMA_DB_PATH / "chroma.sqlite3"
    source_sqlite = CHROMA_SOURCE_BACKUP_PATH / "chroma.sqlite3"
    if not operational_sqlite.exists():
        return False, "chroma_db/chroma.sqlite3 없음 (scripts/import_data_assets.py 실행 필요)"
    if not source_sqlite.exists():
        return False, f"원본 ChromaDB 스냅샷 없음: {CHROMA_SOURCE_BACKUP_PATH}"

    try:
        manifest = load_manifest()
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        return False, str(exc)

    chroma_records = manifest.get("chroma_db", {})
    baseline = manifest.get("chroma_baseline", {})
    expected_collections = sorted(baseline.get("collections", []))
    expected_embeddings = baseline.get("embedding_count")
    if not chroma_records or not expected_collections or expected_embeddings is None:
        return False, "manifest ChromaDB 기준선 누락"

    failures = verify_checksum_records(
        CHROMA_SOURCE_BACKUP_PATH,
        chroma_records,
        prefix="chroma_db/",
    )
    if failures:
        return False, failures[0]

    source_collections, source_embeddings = read_chroma_stats(source_sqlite)
    operational_collections, operational_embeddings = read_chroma_stats(operational_sqlite)
    if source_collections != expected_collections or source_embeddings != expected_embeddings:
        return False, (
            "원본 ChromaDB 논리 기준선 불일치: "
            f"컬렉션 {source_collections}, 임베딩 {source_embeddings}건"
        )
    if operational_collections != expected_collections or operational_embeddings <= 0:
        return False, (
            "운영 ChromaDB 구조 불일치: "
            f"컬렉션 {operational_collections}, 임베딩 {operational_embeddings}건"
        )

    print(
        f"      원본 스냅샷: {len(source_collections)}개 컬렉션 / "
        f"임베딩 {source_embeddings}건 (체크섬 일치)"
    )
    print(
        f"      운영 데이터: {len(operational_collections)}개 컬렉션 / "
        f"임베딩 {operational_embeddings}건"
    )

    # sqlite 를 직접 읽는 것만으로는 부족합니다. 2026-08-05 에 컬렉션 설정
    # JSON 이 비어 chromadb 클라이언트가 컬렉션을 열지 못하는 동안에도 이
    # 검증은 통과했고, 챗봇은 닷새간 지식베이스 없이 답했습니다.
    # 행이 있는 것과 읽히는 것은 다릅니다.
    readable, detail = probe_chroma_query()
    if not readable:
        return False, f"운영 ChromaDB 조회 불가: {detail}"
    print(f"      조회 경로: {detail}")

    return True, (
        f"ChromaDB 원본 {source_embeddings}건 보존 / 운영 {operational_embeddings}건 확인"
    )


def probe_chroma_query() -> tuple[bool, str]:
    """운영 컬렉션을 실제 클라이언트로 열고 한 번 질의해 봅니다."""
    try:
        import chromadb

        client = chromadb.PersistentClient(path=str(CHROMA_DB_PATH))
        collection = client.get_collection("bidding_kb")
        results = collection.query(query_texts=["입찰 공고"], n_results=1)
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"

    documents = (results.get("documents") or [[]])[0]
    if not documents:
        return False, "질의 결과 0건 (컬렉션이 비었거나 색인이 깨졌습니다)"
    return True, f"bidding_kb 질의 정상 ({collection.count()}건 색인)"


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

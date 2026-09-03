#!/usr/bin/env python3
"""
Phase 1 데이터 보존 무손실 마이그레이션 검증 스크립트.

검증 항목:
  1. ML 가중치 4종 SHA256 체크섬 (data/backups/data_assets_checksums.json)
  2. ChromaDB 컬렉션 디렉토리 존재 및 쿼리 무결성
  3. DB 필수 테이블 존재 여부
  4. DB 전 테이블 스키마 서명 (컬럼명, 타입, nullable, PK, FK, 인덱스) 정합성
  5. 데이터 행 수 하한 검증
  6. G1 reconciliation: collected_at 기준 이행 원본/수집 성장분 분리 대조
     (수집이 늘어도 원본 구간이 줄면 즉시 실패)
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import importlib
import json
import os
import sqlite3
import subprocess  # nosec B404
import sys
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

EXPECTED_MODELS = ("v25", "quantum_leap_v25_pro", "ssh_hist_premium", "v13_hybrid")
G1_TOOL_VERSION = "2.0.0"
# ORM에 포함되지 않는 외부 테이블은 이 목록에 명시적으로 승인해야 합니다.
# 목록 밖의 테이블은 검증 보고서에 경고를 남기고 실패 처리합니다.
APPROVED_EXTERNAL_TABLES: frozenset[str] = frozenset()
MANIFEST_PATH = PROJECT_ROOT / "data" / "backups" / "data_assets_checksums.json"
SCHEMA_BASELINE_PATH = PROJECT_ROOT / "data" / "backups" / "schema_signature_baseline.json"
DEFAULT_REPORT_PATH = PROJECT_ROOT / "data" / "backups" / "data_preservation_report.json"
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

# G1 Reconciliation — 이행 시점 경계의 단일 출처.
#
# 한 곳에 두어 여러 모듈에 하드코딩되지 않도록 한다. 운영 환경에서 실측으로
# 더 정확한 시점이 확인되면 MIGRATION_CUTOVER_BASELINE_PATH 파일로 갱신한다.
# 1차 기준 근거: data/backups/data_assets_checksums.json 의
# generated_at = "2026-07-31T06:20:49.674634+00:00" — 원본 bid_box 자산을
# 동결·체크섬화한 시점이며, 이 시점 이전에 수집된 행이 "이행 원본"이다.
MIGRATION_CUTOVER_TS: datetime = datetime(2026, 7, 31, 6, 20, 49, tzinfo=UTC)
MIGRATION_CUTOVER_BASELINE_PATH: Path = (
    PROJECT_ROOT / "data" / "backups" / "row_count_reconciliation_baseline.json"
)
RECONCILIATION_TABLES: tuple[str, ...] = (
    "bid_announcements",
    "bid_results",
)


def get_orm_table_names() -> set[str]:
    """모든 등록된 SQLAlchemy ORM 테이블 이름을 반환합니다."""
    # models 패키지 초기화 과정에서 모든 선언형 모델을 등록합니다.
    from src.app.core.db import Base

    importlib.import_module("src.app.models")
    return set(Base.metadata.tables)


def _database_identifier(engine_or_inspector: object = None) -> str:
    """비밀번호를 숨긴 DB URL을 기준선 출처 식별자로 반환합니다."""
    candidate = engine_or_inspector
    if candidate is not None and hasattr(candidate, "bind"):
        candidate = candidate.bind
    url = getattr(candidate, "url", None)
    if url is None:
        try:
            from src.app.core.db import engine as default_engine

            url = default_engine.url
        except Exception:
            return "unknown"
    try:
        return url.render_as_string(hide_password=True)
    except Exception:
        return str(url).replace(str(getattr(url, "password", "")), "***")


def build_source_metadata(engine_or_inspector: object = None) -> dict[str, str]:
    """기준선 생성 시점의 출처 메타데이터를 생성합니다."""
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "database_identifier": _database_identifier(engine_or_inspector),
        "generated_by": getpass.getuser(),
        "tool_version": G1_TOOL_VERSION,
        "git_head": get_head_commit_sha(),
    }


def validate_source_metadata(payload: object) -> str | None:
    """기준선 출처 메타데이터가 완전한지 검증하고 오류를 반환합니다."""
    if not isinstance(payload, dict):
        return "기준선 메타데이터 형식 오류"
    metadata = payload.get("metadata")
    if not isinstance(metadata, dict):
        return "기준선 메타데이터 누락"
    required = (
        "generated_at",
        "database_identifier",
        "generated_by",
        "tool_version",
        "git_head",
    )
    missing = [
        key for key in required if not isinstance(metadata.get(key), str) or not metadata[key]
    ]
    if missing:
        return f"기준선 메타데이터 필드 누락: {', '.join(missing)}"
    return None


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
        # 살아 있는 컬렉션의 세그먼트만 셉니다. embeddings 를 통째로 세면
        # 삭제된 옛 컬렉션의 고아 레코드까지 잡혀 실제보다 부풀려집니다
        # (2026-08-06 확인: 컬렉션 500건인데 1,500건으로 보고되고 있었습니다).
        cursor.execute(
            """
            SELECT COUNT(*) FROM embeddings e
            JOIN segments s ON e.segment_id = s.id
            JOIN collections c ON s.collection = c.id
            """
        )
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
    print("[1/5] ML 가중치 4종 무결성 검증...")
    # 가중치 위치는 설정으로 옮길 수 있으므로(MODEL_FILES_DIR) 여기서도 같은
    # 환경변수를 따릅니다. 경로를 옮긴 뒤 이 스크립트만 옛 자리를 보면
    # 무결성 검증이 조용히 파일 누락으로 떨어집니다.
    model_root = Path(os.environ.get("MODEL_FILES_DIR", ASSET_ROOT / "data" / "model_files"))
    backup_root = Path(os.environ.get("MODEL_BACKUPS_DIR", ASSET_ROOT / "data" / "model_backups"))
    if not model_root.exists():
        return False, f"{model_root} 없음 (scripts/sync_model_files.py import 실행 필요)"

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
    print("[2/5] ChromaDB 컬렉션 무결성 검증...")
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

        from src.rag.embeddings import get_collection

        client = chromadb.PersistentClient(path=str(CHROMA_DB_PATH))
        # 운영 경로와 같은 임베딩 함수로 열어야 실제 질의를 재현합니다.
        collection = get_collection(client, "bidding_kb")
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
    print("[3/5] DB 필수 테이블 존재 검증...")
    try:
        from sqlalchemy import inspect

        from src.app.core.db import engine

        inspector = inspect(engine)
        existing = set(inspector.get_table_names())
        orm_tables = get_orm_table_names()
    except Exception as exc:
        print(f"      DB 연결 실패: {exc}")
        return False, f"DB 연결 실패로 스키마를 검증하지 못했습니다: {exc}"

    missing = sorted(orm_tables - existing)
    db_only = sorted(existing - orm_tables)
    unapproved = sorted(set(db_only) - APPROVED_EXTERNAL_TABLES)
    print(f"      ORM 테이블: {len(orm_tables)}개 / 연결된 테이블: {len(existing)}개")
    if missing:
        print(f"      누락 테이블: {', '.join(missing)}")
    if db_only:
        print(f"      DB에만 존재하는 테이블: {', '.join(db_only)}")
    if unapproved:
        print(f"      [경고] 승인되지 않은 DB 테이블: {', '.join(unapproved)}")
    if missing or unapproved:
        details = []
        if missing:
            details.append(f"ORM에 있으나 DB에 없는 테이블: {', '.join(missing)}")
        if unapproved:
            details.append(f"DB에만 있고 승인되지 않은 테이블: {', '.join(unapproved)}")
        return False, "; ".join(details)
    if db_only:
        return True, f"ORM 테이블 존재 확인 (승인된 외부 테이블 {len(db_only)}개 포함)"
    return True, "ORM 전체 테이블 존재 확인"


def normalize_type_string(col_type: object) -> str:
    """SQLAlchemy type 객체를 표준 대문자 문자열로 정규화합니다."""
    return str(col_type).upper() if col_type is not None else ""


def extract_table_signature(inspector: object, table_name: str) -> dict:
    """단일 테이블의 컬럼, 기본키, 외래키, 인덱스를 추출하여 정렬된 서명 딕셔너리를 생성합니다."""
    raw_columns = inspector.get_columns(table_name)
    pk_constraint = inspector.get_pk_constraint(table_name) or {}
    pk_cols = set(pk_constraint.get("constrained_columns") or [])

    columns = []
    for col in raw_columns:
        col_name = str(col.get("name") or "")
        col_type_str = normalize_type_string(col.get("type"))
        nullable = bool(col.get("nullable", True))
        is_pk = bool(col.get("primary_key", False) or col_name in pk_cols)
        default_val = col.get("default")
        default_str = str(default_val) if default_val is not None else None

        columns.append(
            {
                "name": col_name,
                "type": col_type_str,
                "nullable": nullable,
                "primary_key": is_pk,
                "default": default_str,
            }
        )
    # 컬럼 순서에 무관하도록 컬럼명 기준 정렬
    columns.sort(key=lambda c: c["name"])

    # Primary Key
    sorted_pk = sorted([str(c) for c in pk_cols if c is not None])

    # Foreign Keys
    raw_fks = inspector.get_foreign_keys(table_name) or []
    formatted_fks = []
    for fk in raw_fks:
        formatted_fks.append(
            {
                "name": str(fk.get("name") or ""),
                "constrained_columns": sorted(
                    [str(c) for c in (fk.get("constrained_columns") or []) if c is not None]
                ),
                "referred_table": str(fk.get("referred_table") or ""),
                "referred_columns": sorted(
                    [str(c) for c in (fk.get("referred_columns") or []) if c is not None]
                ),
            }
        )
    formatted_fks.sort(
        key=lambda x: (
            x["referred_table"],
            tuple(x["constrained_columns"]),
            tuple(x["referred_columns"]),
            x["name"],
        )
    )

    # Indexes
    raw_indexes = inspector.get_indexes(table_name) or []
    formatted_indexes = []
    for idx in raw_indexes:
        formatted_indexes.append(
            {
                "name": str(idx.get("name") or ""),
                "column_names": [str(c) for c in (idx.get("column_names") or []) if c is not None],
                "unique": bool(idx.get("unique", False)),
            }
        )
    formatted_indexes.sort(
        key=lambda x: (
            x["name"],
            tuple(x["column_names"]),
            x["unique"],
        )
    )

    table_dict = {
        "name": table_name,
        "columns": columns,
        "primary_key": sorted_pk,
        "foreign_keys": formatted_fks,
        "indexes": formatted_indexes,
    }
    canonical_json = json.dumps(table_dict, sort_keys=True, separators=(",", ":"))
    table_hash = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()

    return {
        **table_dict,
        "hash": table_hash,
    }


def generate_schema_signature(
    engine_or_inspector: object = None,
    tables: tuple[str, ...] | list[str] | None = None,
) -> dict:
    """전체 대상 테이블의 정렬된 스키마 서명 및 전체 해시를 생성합니다."""
    if engine_or_inspector is None:
        from sqlalchemy import inspect

        from src.app.core.db import engine

        inspector = inspect(engine)
    elif hasattr(engine_or_inspector, "get_table_names"):
        inspector = engine_or_inspector
    else:
        from sqlalchemy import inspect

        inspector = inspect(engine_or_inspector)

    existing_tables = set(inspector.get_table_names())
    orm_tables = get_orm_table_names() if tables is None else set(tables)
    target_tables = sorted(orm_tables | existing_tables)

    tables_sig: dict[str, dict | None] = {}
    table_hashes: dict[str, str | None] = {}
    for table_name in target_tables:
        if table_name in existing_tables:
            t_sig = extract_table_signature(inspector, table_name)
            tables_sig[table_name] = t_sig
            table_hashes[table_name] = t_sig["hash"]
        else:
            tables_sig[table_name] = None
            table_hashes[table_name] = None

    schema_manifest = {
        "version": "1.0.0",
        "tables": tables_sig,
        "table_hashes": table_hashes,
    }
    canonical_json = json.dumps(schema_manifest, sort_keys=True, separators=(",", ":"))
    overall_hash = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
    schema_manifest["overall_hash"] = overall_hash
    schema_manifest["orm_tables"] = sorted(orm_tables)
    schema_manifest["database_tables"] = sorted(existing_tables)
    schema_manifest["metadata"] = build_source_metadata(engine_or_inspector)
    return schema_manifest


def compare_schema_signatures(
    baseline: dict,
    current: dict,
) -> tuple[bool, list[str], dict]:
    """기준 서명과 현재 서명을 대조하여 불일치 항목을 상세 추출합니다."""
    diff_messages: list[str] = []
    diff_details: dict[str, object] = {
        "missing_tables": [],
        "added_tables": [],
        "table_diffs": {},
    }

    baseline_tables = baseline.get("tables", {})
    current_tables = current.get("tables", {})

    all_table_names = sorted(set(baseline_tables.keys()) | set(current_tables.keys()))

    for tbl in all_table_names:
        base_t = baseline_tables.get(tbl)
        curr_t = current_tables.get(tbl)

        if base_t is None and curr_t is not None:
            msg = f"테이블 추가: {tbl}"
            diff_messages.append(msg)
            diff_details["added_tables"].append(tbl)
            continue
        if base_t is not None and curr_t is None:
            msg = f"테이블 누락: {tbl}"
            diff_messages.append(msg)
            diff_details["missing_tables"].append(tbl)
            continue
        if base_t is None and curr_t is None:
            continue

        if base_t.get("hash") == curr_t.get("hash"):
            continue

        t_diffs: list[str] = []

        # 1. 컬럼 비교
        base_cols = {c["name"]: c for c in base_t.get("columns", [])}
        curr_cols = {c["name"]: c for c in curr_t.get("columns", [])}

        all_col_names = sorted(set(base_cols.keys()) | set(curr_cols.keys()))
        for col_name in all_col_names:
            b_c = base_cols.get(col_name)
            c_c = curr_cols.get(col_name)

            if b_c is None and c_c is not None:
                msg = f"{tbl}.{col_name}: 컬럼 추가"
                diff_messages.append(msg)
                t_diffs.append(msg)
            elif b_c is not None and c_c is None:
                msg = f"{tbl}.{col_name}: 컬럼 삭제"
                diff_messages.append(msg)
                t_diffs.append(msg)
            elif b_c is not None and c_c is not None:
                if b_c.get("type") != c_c.get("type"):
                    msg = f"{tbl}.{col_name}: 타입 변경 (기준선: {b_c.get('type')} -> 현재: {c_c.get('type')})"
                    diff_messages.append(msg)
                    t_diffs.append(msg)
                if b_c.get("nullable") != c_c.get("nullable"):
                    msg = f"{tbl}.{col_name}: nullable 변경 (기준선: {b_c.get('nullable')} -> 현재: {c_c.get('nullable')})"
                    diff_messages.append(msg)
                    t_diffs.append(msg)
                if b_c.get("primary_key") != c_c.get("primary_key"):
                    msg = f"{tbl}.{col_name}: primary_key 변경 (기준선: {b_c.get('primary_key')} -> 현재: {c_c.get('primary_key')})"
                    diff_messages.append(msg)
                    t_diffs.append(msg)

        # 2. 기본키 비교
        if base_t.get("primary_key") != curr_t.get("primary_key"):
            msg = f"{tbl}: 기본키 제약조건 변경 (기준선: {base_t.get('primary_key')} -> 현재: {curr_t.get('primary_key')})"
            diff_messages.append(msg)
            t_diffs.append(msg)

        # 3. 외래키 비교
        if base_t.get("foreign_keys") != curr_t.get("foreign_keys"):
            msg = f"{tbl}: 외래키 제약조건 변경"
            diff_messages.append(msg)
            t_diffs.append(msg)

        # 4. 인덱스 비교
        if base_t.get("indexes") != curr_t.get("indexes"):
            msg = f"{tbl}: 인덱스 제약조건 변경"
            diff_messages.append(msg)
            t_diffs.append(msg)

        if t_diffs:
            diff_details["table_diffs"][tbl] = t_diffs

    is_match = len(diff_messages) == 0
    return is_match, diff_messages, diff_details


def verify_schema_signature(
    engine: object = None,
    baseline_path: Path | None = None,
    auto_save_baseline: bool = False,
    tables: tuple[str, ...] | list[str] | None = None,
) -> tuple[bool, str]:
    """전 테이블 스키마 서명을 생성하고 기준선과 비교 검증합니다."""
    print("[4/5] DB 전 테이블 스키마 서명 검증...")
    path = baseline_path or SCHEMA_BASELINE_PATH
    if not path.exists():
        return False, f"기준 서명 파일 없음: {path} (명시적 기준선 생성 명령 필요)"

    try:
        current_sig = generate_schema_signature(engine_or_inspector=engine, tables=tables)
    except Exception as exc:
        print(f"      스키마 서명 생성 실패: {exc}")
        return False, f"스키마 서명 생성 실패: {exc}"

    try:
        baseline_sig = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return False, f"기준 서명 파일 로드 실패: {exc}"

    metadata_error = validate_source_metadata(baseline_sig)
    if metadata_error:
        return False, metadata_error

    is_match, diff_messages, _ = compare_schema_signatures(baseline_sig, current_sig)
    if not is_match:
        for d in diff_messages:
            print(f"      [서명 차이] {d}")
        return (
            False,
            f"DB 스키마 서명 불일치 ({len(diff_messages)}건): {'; '.join(diff_messages[:3])}",
        )

    print(f"      전 테이블 스키마 서명 일치 (해시: {current_sig.get('overall_hash', '')[:16]}...)")
    return True, "DB 스키마 서명 일치 (전 테이블 컬럼·타입·제약조건 무손실)"


def verify_row_counts() -> tuple[bool, str]:
    """핵심 테이블의 실제 행 수를 세고 기준선과 대조합니다."""
    print("[5/5] 데이터 행 수 검증...")
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


def _count_rows_by_cutover(
    session: object,
    model_cls: type,
    table_label: str,
) -> tuple[int, int]:
    """이행 시점 기준 원본/성장분 행 수를 한 번의 라운드트립으로 셉니다.

    운영 경로에서는 누적 행 수가 매우 크므로(수백만 행) 두 번 셀 필요 없이
    GROUP BY 절로 한 번에 집계한다. 테스트 경로의 SQLite 인메모리도 같은
    쿼리로 검증한다.
    """
    from sqlalchemy import case, func, select

    # 원본 = collected_at < MIGRATION_CUTOVER_TS, 성장분 = 그 외.
    # DEFAULT 를 utcnow 로 두는 컬럼이지만 안전을 위해 NULL 은 성장분으로 본다
    # (이행 시점 이전에 NULL 이 있었던 경우는 운영 데이터에서 관찰되지 않았다).
    original_count = func.sum(
        case(
            (model_cls.collected_at < MIGRATION_CUTOVER_TS, 1),
            else_=0,
        )
    )
    stmt = select(
        func.count(model_cls.id).label("total"),
        original_count.label("original"),
    )
    row = session.execute(stmt).one()
    total = int(row.total or 0)
    original = int(row.original or 0)
    growth = total - original
    return original, growth


def verify_reconciliation(
    session_factory: object | None = None,
    baseline_path: Path | None = None,
    auto_save_baseline: bool = False,
) -> tuple[bool, str]:
    """이행 시점 이전에 수집된 행의 수를 baseline 과 대조합니다.

    5단계 누적 하한 검사는 수집이 늘면 그대로 통과하므로, 이행 시점 유실을
    성장분이 가리는 결함이 있다. 이 검증은 collected_at 으로 원본 구간을
    따로 세어 baseline 과 비교한다. 원본이 줄면 즉시 실패하고, 성장분
    증가는 검증 결과에 영향을 주지 않는다(관측값으로만 출력).

    동작 규약:
      - DB 조회 실패는 FAIL 로 보고하여 통과로 위장하지 않는다.
      - baseline 파일이 없으면 FAIL 한다. 기준선 생성은 명시적 생성 명령에서만
        수행하며 검증 경로에서는 파일을 기록하지 않는다.
      - baseline 메타데이터가 없거나 불완전하면 FAIL 한다.
      - baseline 과 비교해 부족하면 FAIL, 같거나 많으면 PASS 한다.
      - 두 테이블 모두 누적 0(즉, DB 가 비어있음)이면 baseline 비교 대상이
        의미 없으므로 "DB 가 비어있어 reconciliation 건너뜀" 메시지를 남기고
        PASS 한다(누적 0 은 통과로 위장하지 않으며, 빈 DB 자체의 판정은
        5단계가 담당한다).

    읽기 전용이며 DDL 이나 DML 을 실행하지 않는다.
    """
    print("[6/6] G1 reconciliation: 원본/수집 성장분 분리 대조...")

    if session_factory is None:
        try:
            from src.app.core.db import SessionLocal
        except Exception as exc:
            print(f"      DB 세션 팩토리 로드 실패: {exc}")
            return False, f"reconciliation DB 세션 로드 실패: {exc}"
        session_factory = SessionLocal

    if baseline_path is None:
        baseline_path = MIGRATION_CUTOVER_BASELINE_PATH

    if not baseline_path.exists():
        return False, f"기준선 파일 없음: {baseline_path} (명시적 기준선 생성 명령 필요)"

    try:
        baseline_payload = json.loads(baseline_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return False, f"reconciliation baseline 로드 실패: {exc}"

    metadata_error = validate_source_metadata(baseline_payload)
    if metadata_error:
        return False, metadata_error
    baseline_tables = baseline_payload.get("tables")
    if not isinstance(baseline_tables, dict):
        return False, "reconciliation baseline 테이블 형식 오류"
    malformed_tables = [
        table_label
        for table_label in RECONCILIATION_TABLES
        if not isinstance(baseline_tables.get(table_label), int)
    ]
    if malformed_tables:
        return False, f"reconciliation baseline 형식 오류: {', '.join(malformed_tables)}"

    try:
        from src.app.models.bids import BidAnnouncement, BidResult
    except Exception as exc:
        return False, f"reconciliation 모델 로드 실패: {exc}"

    models = (
        (RECONCILIATION_TABLES[0], BidAnnouncement),
        (RECONCILIATION_TABLES[1], BidResult),
    )

    session = session_factory()
    try:
        original_counts: dict[str, int] = {}
        growth_counts: dict[str, int] = {}
        for table_label, model_cls in models:
            try:
                original, growth = _count_rows_by_cutover(session, model_cls, table_label)
            except Exception as exc:
                print(f"      DB 조회 실패 ({table_label}): {exc}")
                return False, f"reconciliation DB 조회 실패 ({table_label}): {exc}"
            original_counts[table_label] = original
            growth_counts[table_label] = growth
    finally:
        # 운영 경로(SessionLocal) 는 close() 가 정의되어 있다. 테스트 픽스처가
        # # session.close() 가 없는 가짜 팩토리를 넘기는 경우를 대비해
        # close 가 없으면(=없으면) 조용히 건너뛴다. read-only 검증 경로이므로
        # DB 자원 해제는 부차적이다.
        close = getattr(session, "close", None)
        if callable(close):
            close()

    total_now = sum(original_counts.values()) + sum(growth_counts.values())

    # 누적 0 인 경우 — 두 테이블 모두 0행이면 빈 DB 또는 부재 상황이다.
    # 5단계가 누적 하한을 별도로 보고하므로 여기서는 baseline 대조가
    # 무의미함을 알리고 PASS 한다(통과로 위장하지 않음).
    if total_now == 0:
        print("      DB 가 비어있어 reconciliation 건너뜀 (누적 0행, baseline 대조 의미 없음)")
        return True, "DB 가 비어있어 reconciliation 건너뜀 (누적 0행)"

    failures: list[str] = []
    for table_label, _model in models:
        baseline_value = baseline_tables[table_label]
        current_value = original_counts[table_label]
        growth = growth_counts[table_label]
        if current_value < baseline_value:
            failures.append(
                f"{table_label} 원본 {current_value:,}행 < baseline {baseline_value:,}행"
            )
        else:
            print(
                f"      {table_label}: 원본 {current_value:,}행 "
                f"(baseline {baseline_value:,}), 성장분 {growth:,}행"
            )

    if failures:
        return False, f"이행 원본 행 수 부족: {', '.join(failures)}"
    return True, (
        f"원본/성장분 대조 일치 — "
        f"{RECONCILIATION_TABLES[0]} {original_counts[RECONCILIATION_TABLES[0]]:,}행 / "
        f"{RECONCILIATION_TABLES[1]} {original_counts[RECONCILIATION_TABLES[1]]:,}행"
    )


def get_head_commit_sha() -> str:
    """현재 HEAD 커밋 SHA 를 조회합니다."""
    try:
        result = subprocess.run(  # nosec B603, B607
            ["git", "rev-parse", "HEAD"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        return "unknown"
    return "unknown"


def generate_reconciliation_baseline(
    session_factory: object | None = None,
    baseline_path: Path | None = None,
) -> tuple[bool, str]:
    """현재 DB의 reconciliation 기준선을 명시적으로 생성합니다."""
    if session_factory is None:
        try:
            from src.app.core.db import SessionLocal
        except Exception as exc:
            return False, f"reconciliation DB 세션 로드 실패: {exc}"
        session_factory = SessionLocal
    path = baseline_path or MIGRATION_CUTOVER_BASELINE_PATH

    try:
        from src.app.models.bids import BidAnnouncement, BidResult
    except Exception as exc:
        return False, f"reconciliation 모델 로드 실패: {exc}"

    models = (
        (RECONCILIATION_TABLES[0], BidAnnouncement),
        (RECONCILIATION_TABLES[1], BidResult),
    )
    session = session_factory()
    try:
        original_counts: dict[str, int] = {}
        for table_label, model_cls in models:
            original, _growth = _count_rows_by_cutover(session, model_cls, table_label)
            original_counts[table_label] = original
        bind = getattr(session, "bind", None)
        if bind is None:
            factory_options = getattr(session_factory, "kw", {})
            bind = factory_options.get("bind")
        payload = {
            "schema_version": "1.0.0",
            "cutover_timestamp": MIGRATION_CUTOVER_TS.isoformat(),
            "rationale": ("명시적 기준선 생성 명령으로 수집한 이행 시점 이전 원본 행 수입니다."),
            "tables": original_counts,
            "metadata": build_source_metadata(bind),
        }
    except Exception as exc:
        return False, f"reconciliation 기준선 생성 실패: {exc}"
    finally:
        close = getattr(session, "close", None)
        if callable(close):
            close()

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as exc:
        return False, f"reconciliation 기준선 기록 실패: {exc}"
    return True, f"reconciliation 기준선 생성 완료: {path}"


def generate_verification_report(
    results: list[tuple[str, bool, str]],
    output_path: Path | None = None,
) -> dict:
    """검증 결과를 날짜, HEAD 커밋, 항목별 판정이 담긴 보고서로 생성 및 저장합니다."""
    from datetime import datetime

    now_iso = datetime.now(UTC).isoformat()
    head_sha = get_head_commit_sha()
    all_passed = all(ok for _, ok, _ in results)

    items = []
    for name, ok, msg in results:
        items.append(
            {
                "name": name,
                "status": "PASS" if ok else "FAIL",
                "message": msg,
            }
        )

    report = {
        "generated_at": now_iso,
        "head_commit": head_sha,
        "overall_verdict": "PASS" if all_passed else "FAIL",
        "passed_count": sum(1 for _, ok, _ in results if ok),
        "total_count": len(results),
        "results": items,
    }

    target_path = output_path or DEFAULT_REPORT_PATH
    try:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(
            json.dumps(report, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"      검증 보고서 저장 완료: {target_path}")
    except Exception as exc:
        print(f"      보고서 저장 실패 ({target_path}): {exc}")

    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase 1 데이터 보존 무손실 마이그레이션 검증")
    parser.add_argument(
        "--report-path",
        type=Path,
        default=DEFAULT_REPORT_PATH,
        help="검증 보고서 저장 경로 (기본값: data/backups/data_preservation_report.json)",
    )
    parser.add_argument(
        "--baseline-path",
        type=Path,
        default=SCHEMA_BASELINE_PATH,
        help="스키마 서명 기준선 파일 경로 (기본값: data/backups/schema_signature_baseline.json)",
    )
    parser.add_argument(
        "--generate-schema-baseline",
        "--update-baseline",
        dest="generate_schema_baseline",
        action="store_true",
        help="현재 DB 스키마 서명으로 기준선을 생성하고 검증 없이 종료",
    )
    parser.add_argument(
        "--generate-reconciliation-baseline",
        action="store_true",
        help="현재 DB 원본 행 수로 reconciliation 기준선을 생성하고 검증 없이 종료",
    )
    parser.add_argument(
        "--reconciliation-baseline-path",
        type=Path,
        default=MIGRATION_CUTOVER_BASELINE_PATH,
        help="reconciliation 원본 행 수 기준선 파일 경로",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("refac_bid_box Phase 1 데이터 보존 무손실 검증")
    print("=" * 60)

    if args.generate_schema_baseline or args.generate_reconciliation_baseline:
        generation_results: list[tuple[bool, str]] = []
        if args.generate_schema_baseline:
            try:
                sig = generate_schema_signature()
                args.baseline_path.parent.mkdir(parents=True, exist_ok=True)
                args.baseline_path.write_text(
                    json.dumps(sig, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
                generation_results.append((True, f"스키마 기준선 생성 완료: {args.baseline_path}"))
            except Exception as exc:
                generation_results.append((False, f"스키마 기준선 생성 실패: {exc}"))
        if args.generate_reconciliation_baseline:
            generation_results.append(
                generate_reconciliation_baseline(
                    baseline_path=args.reconciliation_baseline_path,
                )
            )
        for ok, message in generation_results:
            print(("PASS" if ok else "FAIL") + f": {message}")
        return 0 if all(ok for ok, _ in generation_results) else 1

    step1_ok, step1_msg = verify_model_weights()
    step2_ok, step2_msg = verify_chroma_db()
    step3_ok, step3_msg = verify_db_schema()
    step4_ok, step4_msg = verify_schema_signature(baseline_path=args.baseline_path)
    step5_ok, step5_msg = verify_row_counts()
    # 6단계: 5단계가 PASS 일 때만 reconciliation 을 수행한다.
    # 5단계가 FAIL 이면 누적 행이 부족한 상태이므로 reconciliation 의
    # baseline 비교도 같은 원인이 두 번 보고되어 판정을 흐린다. 원인을
    # 단일화하기 위해 6단계를 생략하고 5단계의 FAIL 만 남긴다.
    if step5_ok:
        step6_ok, step6_msg = verify_reconciliation(
            baseline_path=args.reconciliation_baseline_path,
        )
    else:
        step6_ok = False
        step6_msg = "5단계 실패로 reconciliation 생략 (누적 행 수 부족 판정 유지)"

    named_results = [
        ("ML 가중치 4종 무결성", step1_ok, step1_msg),
        ("ChromaDB 컬렉션 무결성", step2_ok, step2_msg),
        ("DB 테이블 존재 여부", step3_ok, step3_msg),
        ("DB 전 테이블 스키마 서명 정합성", step4_ok, step4_msg),
        ("데이터 행 수 하한 검증", step5_ok, step5_msg),
        ("G1 reconciliation: 원본/성장분 분리 대조", step6_ok, step6_msg),
    ]

    report = generate_verification_report(named_results, output_path=args.report_path)

    print("-" * 60)
    for name, ok, msg in named_results:
        status_label = "PASS" if ok else "FAIL"
        print(f"{status_label}: [{name}] {msg}")

    all_passed = report["overall_verdict"] == "PASS"
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())

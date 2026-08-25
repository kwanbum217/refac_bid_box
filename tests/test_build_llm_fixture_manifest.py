"""
tests/test_build_llm_fixture_manifest.py

LLM 품질 평가 fixture 의 경량 evidence manifest 생성기 (scripts/build_llm_fixture_manifest.py) 단위 테스트.
- 실제 ChromaDB 4개 테이블 스키마(collections, segments, embeddings, embedding_metadata)를 반영한 mock 검증
- ChromaDB 가 없을 때 0이 아닌 종료 코드로 끝나고 파일을 쓰지 않는지 (fail-closed)
- fixture 가 참조하는 ID 만 담는지 (컬렉션 전체 덤프 방지)
- ChromaDB 에 일부 ID 가 누락되었을 때 부분 manifest 를 쓰지 않고 실패하는지
- fixture 파일 부재 시 exit code 2 반환
- CLI 실행 규약 검증
"""

import hashlib
import json
import sqlite3
import subprocess  # nosec B404
import sys
from pathlib import Path

from scripts.build_llm_fixture_manifest import (
    build_manifest_file,
    extract_required_evidence_ids,
)


def _create_mock_chroma_sqlite(
    db_path: Path,
    collection_name: str = "bidding_kb",
    collection_id: str = "867aac54-322c-4aff-95b3-f3d4dce62109",
    segment_id: str = "seg_001",
    records: list[tuple[str, str]] | None = None,
) -> None:
    """실제 ChromaDB 스키마를 반영한 테스트용 모의 SQLite 데이터베이스를 생성합니다."""
    if records is None:
        records = [
            ("bid_10015927", "봉화 공설운동장 감리 용역 문서 본문"),
            ("bid_10015878", "안녕 자두야 포스트프로덕션 용역 문서 본문"),
            ("bid_unreferenced_999", "fixture 에서 참조하지 않는 임의 문서 본문"),
        ]

    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute("CREATE TABLE collections (id TEXT PRIMARY KEY, name TEXT)")
    cur.execute(
        "INSERT INTO collections (id, name) VALUES (?, ?)",
        (collection_id, collection_name),
    )
    cur.execute(
        "CREATE TABLE segments (id TEXT PRIMARY KEY, type TEXT, scope TEXT, collection TEXT)"
    )
    cur.execute(
        "INSERT INTO segments (id, type, scope, collection) VALUES (?, 'vector', 'VECTOR', ?)",
        (segment_id, collection_id),
    )
    cur.execute(
        "CREATE TABLE embeddings (id TEXT PRIMARY KEY, segment_id TEXT, embedding_id TEXT, seq_id INTEGER, created_at TEXT)"
    )
    cur.execute(
        "CREATE TABLE embedding_metadata (id TEXT, key TEXT, string_value TEXT, int_value INTEGER, float_value REAL, bool_value INTEGER)"
    )
    for idx, (ev_id, doc) in enumerate(records, start=1):
        emb_uuid = f"emb_uuid_{idx:04d}"
        cur.execute(
            "INSERT INTO embeddings (id, segment_id, embedding_id, seq_id, created_at) VALUES (?, ?, ?, ?, '2026-08-25T00:00:00Z')",
            (emb_uuid, segment_id, ev_id, idx),
        )
        cur.execute(
            "INSERT INTO embedding_metadata (id, key, string_value, int_value, float_value, bool_value) VALUES (?, 'chroma:document', ?, NULL, NULL, NULL)",
            (emb_uuid, doc),
        )
    conn.commit()
    conn.close()


def _create_mock_fixture(fixture_path: Path, evidence_ids: list[str]) -> None:
    """테스트용 모의 fixture JSON 파일을 생성합니다."""
    data = {
        "version": "2.0.0",
        "items": [
            {
                "id": f"q{i:02d}",
                "expected_evidence_ids": [ev_id],
                "context_sufficient": True,
            }
            for i, ev_id in enumerate(evidence_ids, start=1)
        ],
    }
    fixture_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def test_extract_required_evidence_ids():
    """fixture 데이터로부터 unique evidence ID 목록이 올바르게 추출되는지 확인합니다."""
    fixture_data = {
        "items": [
            {"id": "q01", "expected_evidence_ids": ["bid_1", "bid_2"]},
            {"id": "q02", "expected_evidence_ids": ["bid_2", "bid_3"]},
            {"id": "q03", "expected_evidence_ids": []},
            {"id": "q04"},
        ]
    }
    ids = extract_required_evidence_ids(fixture_data)
    assert ids == {"bid_1", "bid_2", "bid_3"}


def test_build_manifest_fails_when_chromadb_missing(tmp_path: Path):
    """ChromaDB 가 없으면 0이 아닌 종료 코드로 끝나고 manifest 를 생성하지 않는지 확인합니다."""
    fixture_file = tmp_path / "fixture.json"
    _create_mock_fixture(fixture_file, ["bid_10015927"])
    out_file = tmp_path / "manifest.json"

    # 존재하지 않는 경로 지정
    code = build_manifest_file(
        fixture_path=fixture_file,
        output_path=out_file,
        chroma_db_path=tmp_path / "non_existent_chroma",
        quiet=True,
    )
    assert code == 1
    assert not out_file.exists(), "ChromaDB 부재 시 manifest 파일이 생성되어서는 안 됩니다."


def test_build_manifest_extracts_only_fixture_referenced_ids(tmp_path: Path):
    """fixture 가 참조하는 ID 만 manifest 에 담기고 컬렉션 전체가 덤프되지 않는지 확인합니다."""
    mock_db = tmp_path / "chroma.sqlite3"
    _create_mock_chroma_sqlite(
        mock_db,
        collection_name="bidding_kb",
        records=[
            ("bid_10015927", "봉화 문서 본문"),
            ("bid_10015878", "자두야 문서 본문"),
            ("bid_unreferenced_1", "미참조 문서 1"),
            ("bid_unreferenced_2", "미참조 문서 2"),
        ],
    )

    fixture_file = tmp_path / "fixture.json"
    _create_mock_fixture(fixture_file, ["bid_10015927", "bid_10015878"])
    out_file = tmp_path / "manifest.json"

    code = build_manifest_file(
        fixture_path=fixture_file,
        output_path=out_file,
        chroma_db_path=mock_db,
        collection_name="bidding_kb",
        quiet=True,
    )
    assert code == 0
    assert out_file.exists()

    manifest_data = json.loads(out_file.read_text(encoding="utf-8"))
    assert manifest_data["schema_version"] == "1.0.0"
    assert manifest_data["collection_name"] == "bidding_kb"
    assert manifest_data["total_collection_documents"] == 4
    assert manifest_data["item_count"] == 2

    entries = manifest_data["entries"]
    entry_ids = [e["evidence_id"] for e in entries]
    assert entry_ids == ["bid_10015878", "bid_10015927"]

    # 해시 정합성 검증
    for entry in entries:
        if entry["evidence_id"] == "bid_10015927":
            expected_hash = "sha256:" + hashlib.sha256("봉화 문서 본문".encode()).hexdigest()
            assert entry["content_hash"] == expected_hash
            assert entry["doc_length"] == len("봉화 문서 본문")


def test_build_manifest_does_not_write_partial_manifest_on_missing_id(tmp_path: Path):
    """ChromaDB 에 fixture 요구 ID 중 일부가 누락되었을 때 부분 manifest 를 쓰지 않고 실패하는지 확인합니다."""
    mock_db = tmp_path / "chroma.sqlite3"
    _create_mock_chroma_sqlite(
        mock_db,
        records=[
            ("bid_10015927", "봉화 문서 본문"),
            # bid_10015878 누락
        ],
    )

    fixture_file = tmp_path / "fixture.json"
    _create_mock_fixture(fixture_file, ["bid_10015927", "bid_10015878"])
    out_file = tmp_path / "manifest.json"

    code = build_manifest_file(
        fixture_path=fixture_file,
        output_path=out_file,
        chroma_db_path=mock_db,
        quiet=True,
    )
    assert code == 1
    assert not out_file.exists(), "부분 ID 누락 시 부분 manifest 가 생성되어서는 안 됩니다."


def test_build_manifest_fails_on_missing_fixture(tmp_path: Path):
    """존재하지 않는 fixture 파일에 대해 exit code 2를 반환하는지 확인합니다."""
    code = build_manifest_file(
        fixture_path=tmp_path / "non_existent_fixture.json",
        output_path=tmp_path / "manifest.json",
        quiet=True,
    )
    assert code == 2


def test_cli_build_manifest_success(tmp_path: Path):
    """CLI 로 실행 시 정상 파일에 대해 exit code 0을 반환하고 manifest 를 생성하는지 확인합니다."""
    mock_db = tmp_path / "chroma.sqlite3"
    _create_mock_chroma_sqlite(mock_db, records=[("bid_01", "문서 내용")])

    fixture_file = tmp_path / "fixture.json"
    _create_mock_fixture(fixture_file, ["bid_01"])
    out_file = tmp_path / "manifest.json"

    cmd = [
        sys.executable,
        "scripts/build_llm_fixture_manifest.py",
        "--fixture",
        str(fixture_file),
        "--output",
        str(out_file),
        "--chroma-db-path",
        str(mock_db),
        "--quiet",
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=False)  # noqa: S603
    assert res.returncode == 0
    assert out_file.exists()

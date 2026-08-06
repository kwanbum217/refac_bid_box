import json
import sqlite3
from pathlib import Path

from scripts import import_data_assets, verify_migration


def _create_chroma(path: Path, embedding_count: int, orphan_count: int = 0) -> Path:
    """실제 ChromaDB 스키마(collections - segments - embeddings)를 흉내 냅니다.

    `orphan_count` 는 삭제된 옛 컬렉션이 남긴 고아 임베딩입니다. 실물 DB 에서
    실제로 관찰됐고(2026-08-06: 컬렉션 500건인데 1,500건으로 집계), 검증이
    이것까지 세면 운영 규모를 부풀려 보고합니다.
    """
    path.mkdir(parents=True)
    sqlite_path = path / "chroma.sqlite3"
    connection = sqlite3.connect(sqlite_path)
    try:
        connection.execute("CREATE TABLE collections (id TEXT PRIMARY KEY, name TEXT NOT NULL)")
        connection.execute("CREATE TABLE segments (id TEXT PRIMARY KEY, collection TEXT)")
        connection.execute("CREATE TABLE embeddings (id INTEGER PRIMARY KEY, segment_id TEXT)")
        connection.execute("INSERT INTO collections (id, name) VALUES ('col-1', 'bidding_kb')")
        connection.execute("INSERT INTO segments (id, collection) VALUES ('seg-live', 'col-1')")
        connection.executemany(
            "INSERT INTO embeddings (id, segment_id) VALUES (?, 'seg-live')",
            [(index,) for index in range(embedding_count)],
        )
        if orphan_count:
            # 세그먼트만 있고 컬렉션에 매달려 있지 않은 잔재입니다.
            connection.executemany(
                "INSERT INTO embeddings (id, segment_id) VALUES (?, 'seg-orphan')",
                [(embedding_count + index,) for index in range(orphan_count)],
            )
        connection.commit()
    finally:
        connection.close()
    return sqlite_path


def test_read_chroma_stats_ignores_orphan_embeddings(tmp_path):
    """삭제된 컬렉션 잔재를 세면 운영 규모가 부풀려집니다."""
    sqlite_path = _create_chroma(tmp_path / "chroma", embedding_count=500, orphan_count=1000)

    collections, count = verify_migration.read_chroma_stats(sqlite_path)

    assert collections == ["bidding_kb"]
    assert count == 500


def _configure_chroma_paths(monkeypatch, tmp_path: Path, operational_count: int = 500):
    source = tmp_path / "source"
    operational = tmp_path / "operational"
    source_sqlite = _create_chroma(source, 10)
    _create_chroma(operational, operational_count)
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "chroma_baseline": {
                    "collections": ["bidding_kb"],
                    "embedding_count": 10,
                },
                "chroma_db": {
                    "chroma_db/chroma.sqlite3": {
                        "sha256": verify_migration.sha256_file(source_sqlite),
                        "bytes": source_sqlite.stat().st_size,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(verify_migration, "MANIFEST_PATH", manifest_path)
    monkeypatch.setattr(verify_migration, "CHROMA_SOURCE_BACKUP_PATH", source)
    monkeypatch.setattr(verify_migration, "CHROMA_DB_PATH", operational)
    return source, operational


def _stub_probe(monkeypatch, result):
    """조회 검증은 실제 ChromaDB 클라이언트를 쓰므로 합성 sqlite 로는 못 돕니다."""
    monkeypatch.setattr(verify_migration, "probe_chroma_query", lambda: result)


def test_chroma_verification_preserves_source_and_allows_operational_growth(
    monkeypatch,
    tmp_path,
):
    _configure_chroma_paths(monkeypatch, tmp_path)
    _stub_probe(monkeypatch, (True, "bidding_kb 질의 정상 (500건 색인)"))

    passed, message = verify_migration.verify_chroma_db()

    assert passed is True
    assert "원본 10건 보존" in message
    assert "운영 500건" in message


def test_chroma_verification_fails_when_collection_cannot_be_queried(monkeypatch, tmp_path):
    """행이 있는 것과 읽히는 것은 다릅니다.

    2026-08-05 에 컬렉션 설정 JSON 이 비어 클라이언트가 컬렉션을 열지 못하는
    동안에도 이 검증은 통과했습니다. sqlite 행 수만 봤기 때문입니다.
    """
    _configure_chroma_paths(monkeypatch, tmp_path)
    _stub_probe(monkeypatch, (False, "KeyError: '_type'"))

    passed, message = verify_migration.verify_chroma_db()

    assert passed is False
    assert "조회 불가" in message


def test_chroma_verification_rejects_mutated_source_snapshot(monkeypatch, tmp_path):
    source, _ = _configure_chroma_paths(monkeypatch, tmp_path)
    (source / "chroma.sqlite3").write_bytes(b"corrupted")

    passed, message = verify_migration.verify_chroma_db()

    assert passed is False
    assert "체크섬 불일치" in message


def test_chroma_verification_requires_source_snapshot(monkeypatch, tmp_path):
    source, _ = _configure_chroma_paths(monkeypatch, tmp_path)
    (source / "chroma.sqlite3").unlink()

    passed, message = verify_migration.verify_chroma_db()

    assert passed is False
    assert "원본 ChromaDB 스냅샷 없음" in message


def test_row_count_gate_requires_full_baseline():
    assert verify_migration.MIN_ROW_COUNT_RATIO == 100.0


def test_import_collects_logical_chroma_baseline(tmp_path):
    source = tmp_path / "source"
    sqlite_path = _create_chroma(source, 10)

    baseline = import_data_assets.collect_chroma_baseline(source)

    assert baseline == {
        "collections": ["bidding_kb"],
        "embedding_count": 10,
        "sqlite_sha256": verify_migration.sha256_file(sqlite_path),
    }


def test_import_checksum_paths_use_stable_prefix(tmp_path):
    source = tmp_path / "outside-project" / "chroma_db"
    sqlite_path = _create_chroma(source, 10)

    records = import_data_assets.collect_checksums(source, "chroma_db")

    assert list(records) == ["chroma_db/chroma.sqlite3"]
    assert records["chroma_db/chroma.sqlite3"]["sha256"] == (
        verify_migration.sha256_file(sqlite_path)
    )


def _configure_promoted_model(monkeypatch, tmp_path: Path, backup_bytes: bytes):
    model = "promoted_model"
    serving = tmp_path / "data" / "model_files" / model
    backup = tmp_path / "data" / "model_backups" / model
    serving.mkdir(parents=True)
    backup.mkdir(parents=True)
    (serving / "model.bin").write_bytes(b"new champion")
    (backup / "model.bin").write_bytes(backup_bytes)
    original = tmp_path / "original.bin"
    original.write_bytes(b"original")
    manifest = tmp_path / "model_manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "models": {
                    model: {
                        "model.bin": {
                            "sha256": verify_migration.sha256_file(original),
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(verify_migration, "ASSET_ROOT", tmp_path)
    monkeypatch.setattr(verify_migration, "MANIFEST_PATH", manifest)
    monkeypatch.setattr(verify_migration, "EXPECTED_MODELS", (model,))


def test_model_verification_accepts_original_in_promotion_backup(monkeypatch, tmp_path):
    _configure_promoted_model(monkeypatch, tmp_path, b"original")

    passed, _ = verify_migration.verify_model_weights()

    assert passed is True


def test_model_verification_rejects_mutated_serving_and_backup(monkeypatch, tmp_path):
    _configure_promoted_model(monkeypatch, tmp_path, b"corrupted")

    passed, message = verify_migration.verify_model_weights()

    assert passed is False
    assert "백업도 불일치" in message

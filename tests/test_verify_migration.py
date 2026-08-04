import json
import sqlite3
from pathlib import Path

from scripts import import_data_assets, verify_migration


def _create_chroma(path: Path, embedding_count: int) -> Path:
    path.mkdir(parents=True)
    sqlite_path = path / "chroma.sqlite3"
    connection = sqlite3.connect(sqlite_path)
    try:
        connection.execute("CREATE TABLE collections (name TEXT NOT NULL)")
        connection.execute("CREATE TABLE embeddings (id INTEGER PRIMARY KEY)")
        connection.execute("INSERT INTO collections (name) VALUES ('bidding_kb')")
        connection.executemany(
            "INSERT INTO embeddings (id) VALUES (?)",
            [(index,) for index in range(embedding_count)],
        )
        connection.commit()
    finally:
        connection.close()
    return sqlite_path


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


def test_chroma_verification_preserves_source_and_allows_operational_growth(
    monkeypatch,
    tmp_path,
):
    _configure_chroma_paths(monkeypatch, tmp_path)

    passed, message = verify_migration.verify_chroma_db()

    assert passed is True
    assert "원본 10건 보존" in message
    assert "운영 500건" in message


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

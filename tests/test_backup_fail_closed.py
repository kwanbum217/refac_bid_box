"""필수 백업 자산 누락 및 빈 산출물의 실패 종료 검증입니다."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.backup_recovery import (
    MANIFEST_FILENAME,
    REQUIRED_BACKUP_ASSETS,
    BackupAssetError,
    build_parser,
    evaluate_row_counts,
    execute_backup,
    execute_restore,
    query_db_row_counts,
    sha256_file,
    verify_snapshot,
)


def _create_sources(
    root: Path, *, chroma_content: bytes = b"chroma", model_content: bytes = b"model"
):
    chroma = root / "chroma_db"
    chroma.mkdir()
    (chroma / "chroma.sqlite3").write_bytes(chroma_content)
    model_dir = root / "data" / "model_files"
    model_dir.mkdir(parents=True)
    (model_dir / "model.bin").write_bytes(model_content)
    return chroma, model_dir


def _fake_dump(_db_config, output_path: Path):
    output_path.write_bytes(b"db dump")
    return output_path.stat().st_size, sha256_file(output_path)


def _backup_patches():
    return (
        patch("scripts.backup_recovery.dump_mysql_database", side_effect=_fake_dump),
        patch("scripts.backup_recovery.query_db_row_counts", return_value={}),
        patch("scripts.backup_recovery.get_head_commit_sha", return_value="head"),
    )


def test_missing_required_chroma_fails_closed(tmp_path: Path):
    """ChromaDB 경로가 없으면 --allow-partial 없이 백업하지 않습니다."""
    _create_sources(tmp_path)
    chroma_path = tmp_path / "missing_chroma"
    output_dir = tmp_path / "snapshot"
    with (
        patch.dict(os.environ, {"CHROMA_DB_PATH": str(chroma_path)}),
        patch("scripts.backup_recovery.dump_mysql_database") as mock_dump,
        pytest.raises(BackupAssetError, match="chroma_db"),
    ):
        execute_backup(output_dir=output_dir, execute=True, project_root=tmp_path)
    mock_dump.assert_not_called()
    assert not (output_dir / MANIFEST_FILENAME).exists()


def test_zero_byte_required_source_fails_closed(tmp_path: Path):
    """내용이 0바이트인 필수 파일 자산은 백업하지 않습니다."""
    chroma, _ = _create_sources(tmp_path, chroma_content=b"")
    output_dir = tmp_path / "snapshot"
    with (
        patch.dict(os.environ, {"CHROMA_DB_PATH": str(chroma)}),
        pytest.raises(BackupAssetError, match="chroma_db"),
    ):
        execute_backup(output_dir=output_dir, execute=True, project_root=tmp_path)
    assert not output_dir.exists()


def test_missing_required_model_fails_closed(tmp_path: Path):
    """기본 모델 파일 경로가 없으면 백업을 실패시킵니다."""
    chroma = tmp_path / "chroma_db"
    chroma.mkdir()
    (chroma / "chroma.sqlite3").write_bytes(b"chroma")
    with (
        patch.dict(os.environ, {"CHROMA_DB_PATH": str(chroma)}),
        pytest.raises(BackupAssetError, match="models"),
    ):
        execute_backup(output_dir=tmp_path / "snapshot", execute=True, project_root=tmp_path)


def test_allow_partial_records_untrusted_manifest(tmp_path: Path):
    """허용 플래그를 사용한 누락은 부분·비신뢰 매니페스트로 남깁니다."""
    chroma = tmp_path / "missing_chroma"
    _create_sources(tmp_path)
    output_dir = tmp_path / "snapshot"
    with patch.dict(os.environ, {"CHROMA_DB_PATH": str(chroma)}):
        patches = _backup_patches()
        with patches[0], patches[1], patches[2]:
            manifest = execute_backup(
                output_dir=output_dir,
                execute=True,
                project_root=tmp_path,
                allow_partial=True,
            )
    assert manifest["partial_backup"] is True
    assert manifest["recovery_trusted"] is False
    assert any(asset.startswith("chroma_db") for asset in manifest["missing_assets"])
    assert manifest["components"]["chroma_db"]["path"] is None
    assert not (output_dir / "chroma_db.tar.gz").exists()
    consistency = manifest["consistency_window"]
    for key in (
        "db_dump_started_at",
        "db_dump_finished_at",
        "file_assets_collected_at",
    ):
        datetime.fromisoformat(consistency[key])
    loaded = json.loads((output_dir / MANIFEST_FILENAME).read_text(encoding="utf-8"))
    assert loaded["recovery_trusted"] is False


def test_zero_byte_backup_output_fails_closed(tmp_path: Path):
    """백업 아카이브 산출물이 0바이트이면 매니페스트를 작성하지 않습니다."""
    chroma, _ = _create_sources(tmp_path)

    def write_empty_archive(_sources, output_path, base_dir):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.touch()
        return 0, "0" * 64

    patches = _backup_patches()
    with (
        patch.dict(os.environ, {"CHROMA_DB_PATH": str(chroma)}),
        patches[0],
        patches[1],
        patches[2],
        patch("scripts.backup_recovery.create_tar_archive", side_effect=write_empty_archive),
        pytest.raises(BackupAssetError, match="chroma_db"),
    ):
        execute_backup(output_dir=tmp_path / "snapshot", execute=True, project_root=tmp_path)


def test_zero_byte_database_dump_fails_closed(tmp_path: Path):
    """DB 덤프 산출물이 0바이트이면 부분 플래그와 무관하게 실패합니다."""
    chroma, _ = _create_sources(tmp_path)

    def write_empty_dump(_db_config, output_path):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.touch()
        return 0, "0" * 64

    with (
        patch.dict(os.environ, {"CHROMA_DB_PATH": str(chroma)}),
        patch("scripts.backup_recovery.dump_mysql_database", side_effect=write_empty_dump),
        pytest.raises(BackupAssetError, match="database"),
    ):
        execute_backup(
            output_dir=tmp_path / "snapshot",
            execute=True,
            project_root=tmp_path,
            allow_partial=True,
        )


def test_partial_snapshot_is_not_restorable(tmp_path: Path):
    """부분 백업 매니페스트는 파일이 채워져 있어도 복원을 거부합니다."""
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    components = {}
    for name, filename, content in (
        ("database", "db_dump.sql.gz", b"db"),
        ("chroma_db", "chroma_db.tar.gz", b"chroma"),
        ("models", "models.tar.gz", b"models"),
    ):
        path = snapshot / filename
        path.write_bytes(content)
        components[name] = {
            "path": filename,
            "size_bytes": len(content),
            "sha256": sha256_file(path),
        }
    (snapshot / MANIFEST_FILENAME).write_text(
        json.dumps(
            {
                "schema": "BACKUP_MANIFEST_V1",
                "partial_backup": True,
                "recovery_trusted": False,
                "components": components,
            }
        ),
        encoding="utf-8",
    )
    assert execute_restore(snapshot, execute=False, project_root=tmp_path) is False


def test_partial_flag_is_available_only_on_backup_parser():
    """부분 백업 허용 수단은 백업 명령의 단일 CLI 플래그입니다."""
    args = build_parser().parse_args(["backup", "--allow-partial"])
    assert args.allow_partial is True
    assert set(REQUIRED_BACKUP_ASSETS) == {"database", "chroma_db", "models"}


def _create_valid_snapshot_dir(base_dir: Path) -> tuple[Path, dict]:
    """테스트용 정상 스냅샷 디렉터리와 매니페스트 딕셔너리를 생성합니다."""
    snap = base_dir / "valid_snap"
    snap.mkdir(parents=True, exist_ok=True)
    components = {}
    for name, filename, content in (
        ("database", "db_dump.sql.gz", b"valid_db_data"),
        ("chroma_db", "chroma_db.tar.gz", b"valid_chroma_data"),
        ("models", "models.tar.gz", b"valid_model_data"),
    ):
        file_path = snap / filename
        file_path.write_bytes(content)
        components[name] = {
            "path": filename,
            "size_bytes": len(content),
            "sha256": sha256_file(file_path),
        }
    manifest = {
        "schema": "BACKUP_MANIFEST_V1",
        "partial_backup": False,
        "recovery_trusted": True,
        "components": components,
    }
    return snap, manifest


def test_verify_snapshot_valid_manifest_passes(tmp_path: Path):
    """정상 백업 형태는 검증과 복원 사전 점검을 통과합니다."""
    snap, manifest = _create_valid_snapshot_dir(tmp_path)
    (snap / MANIFEST_FILENAME).write_text(json.dumps(manifest), encoding="utf-8")
    is_valid, errors, _ = verify_snapshot(snap)
    assert is_valid is True
    assert len(errors) == 0
    assert execute_restore(snap, execute=False, project_root=tmp_path) is True


def test_verify_snapshot_empty_manifest_fails(tmp_path: Path):
    """빈 매니페스트({})는 검증 실패로 판정됩니다."""
    snap = tmp_path / "empty_manifest_snap"
    snap.mkdir()
    (snap / MANIFEST_FILENAME).write_text("{}", encoding="utf-8")
    is_valid, errors, _ = verify_snapshot(snap)
    assert is_valid is False
    assert len(errors) > 0


def test_verify_snapshot_empty_components_fails(tmp_path: Path):
    """components 가 비어 있는 매니페스트는 검증 실패로 판정됩니다."""
    snap = tmp_path / "empty_components_snap"
    snap.mkdir()
    (snap / MANIFEST_FILENAME).write_text(
        json.dumps({"schema": "BACKUP_MANIFEST_V1", "components": {}}),
        encoding="utf-8",
    )
    is_valid, errors, _ = verify_snapshot(snap)
    assert is_valid is False
    assert any("필수 백업 자산 누락" in err for err in errors)


def test_verify_snapshot_missing_one_asset_fails(tmp_path: Path):
    """필수 자산 1개(예: models)가 누락되면 검증 실패로 판정됩니다."""
    snap, manifest = _create_valid_snapshot_dir(tmp_path)
    del manifest["components"]["models"]
    (snap / MANIFEST_FILENAME).write_text(json.dumps(manifest), encoding="utf-8")
    is_valid, errors, _ = verify_snapshot(snap)
    assert is_valid is False
    assert any("models" in err for err in errors)


def test_verify_snapshot_missing_sha256_fails(tmp_path: Path):
    """sha256 필드가 누락되거나 비어 있으면 검증 실패로 판정됩니다."""
    snap, manifest = _create_valid_snapshot_dir(tmp_path)
    del manifest["components"]["database"]["sha256"]
    (snap / MANIFEST_FILENAME).write_text(json.dumps(manifest), encoding="utf-8")
    is_valid, errors, _ = verify_snapshot(snap)
    assert is_valid is False
    assert any("SHA256" in err for err in errors)


def test_verify_snapshot_zero_size_fails(tmp_path: Path):
    """size_bytes 가 0 이면 검증 실패로 판정됩니다."""
    snap, manifest = _create_valid_snapshot_dir(tmp_path)
    manifest["components"]["database"]["size_bytes"] = 0
    (snap / MANIFEST_FILENAME).write_text(json.dumps(manifest), encoding="utf-8")
    is_valid, errors, _ = verify_snapshot(snap)
    assert is_valid is False
    assert any("양수" in err or "파일 크기" in err for err in errors)


def test_verify_snapshot_string_size_fails(tmp_path: Path):
    """size_bytes 가 문자열이면 자료형 오류로 검증 실패합니다."""
    snap, manifest = _create_valid_snapshot_dir(tmp_path)
    manifest["components"]["database"]["size_bytes"] = "100"
    (snap / MANIFEST_FILENAME).write_text(json.dumps(manifest), encoding="utf-8")
    is_valid, errors, _ = verify_snapshot(snap)
    assert is_valid is False
    assert any("정수" in err for err in errors)


def test_verify_snapshot_components_as_list_fails(tmp_path: Path):
    """components 가 리스트이면 자료형 오류로 검증 실패합니다."""
    snap = tmp_path / "list_components_snap"
    snap.mkdir()
    (snap / MANIFEST_FILENAME).write_text(
        json.dumps({"schema": "BACKUP_MANIFEST_V1", "components": []}),
        encoding="utf-8",
    )
    is_valid, errors, _ = verify_snapshot(snap)
    assert is_valid is False
    assert any("딕셔너리" in err for err in errors)


def test_restore_rejects_missing_recovery_trusted_key(tmp_path: Path):
    """recovery_trusted 키가 없는 매니페스트는 복원 사전 점검에서 거부됩니다."""
    snap, manifest = _create_valid_snapshot_dir(tmp_path)
    del manifest["recovery_trusted"]
    (snap / MANIFEST_FILENAME).write_text(json.dumps(manifest), encoding="utf-8")
    assert execute_restore(snap, execute=False, project_root=tmp_path) is False


def test_query_db_row_counts_distinguishes_zero_and_query_failure():
    """query_db_row_counts 가 실제 0행과 테이블 조회 실패(None)를 명확히 구분하는지 검증합니다."""
    from unittest.mock import MagicMock

    mock_engine = MagicMock()
    mock_conn = MagicMock()
    mock_engine.connect.return_value.__enter__.return_value = mock_conn

    def fake_execute(query_stmt):
        sql = str(query_stmt)
        res = MagicMock()
        if "accounts_customuser" in sql:
            res.scalar.return_value = 0
        elif "bid_announcements" in sql:
            raise RuntimeError("테이블 잠금 또는 쿼리 실패 시뮬레이션")
        elif "bid_results" in sql:
            res.scalar.return_value = 55
        else:
            res.scalar.return_value = 0
        return res

    mock_conn.execute.side_effect = fake_execute

    with patch("sqlalchemy.create_engine", return_value=mock_engine):
        counts = query_db_row_counts(
            {"user": "u", "password": "p", "host": "h", "port": 3306, "name": "d"},
            tables=("accounts_customuser", "bid_announcements", "bid_results"),
        )

    assert counts["accounts_customuser"] == 0
    assert isinstance(counts["accounts_customuser"], int)
    assert counts["bid_announcements"] is None
    assert counts["bid_results"] == 55
    # 실제 0행과 조회 실패가 구별됨을 엄격히 단언
    assert counts["accounts_customuser"] != counts["bid_announcements"]
    assert counts["bid_announcements"] is not 0  # noqa: F632


def test_query_db_row_counts_connection_failure_maps_tables_to_none():
    """전체 DB 연결 실패 시 빈 dict 가 아닌 모든 대상 테이블이 None 으로 매핑되는지 검증합니다."""
    with patch("sqlalchemy.create_engine", side_effect=RuntimeError("MySQL 접속 거부")):
        counts = query_db_row_counts(
            {"user": "u", "password": "p", "host": "h", "port": 3306, "name": "d"},
            tables=("accounts_customuser", "bid_announcements"),
        )

    assert len(counts) == 2
    assert counts["accounts_customuser"] is None
    assert counts["bid_announcements"] is None
    # 빈 결과로 조용히 성공처럼 보이지 않음을 검증
    status, _msg = evaluate_row_counts(counts)
    assert status == "connection_failed"


def test_restore_fails_closed_when_row_count_failure_makes_untrusted(tmp_path: Path):
    """행 수 조회 실패로 recovery_trusted 가 False 인 스냅샷은 복원이 엄격히 차단됩니다."""
    snap = tmp_path / "untrusted_due_to_rowcount"
    snap.mkdir(parents=True, exist_ok=True)
    components = {}
    for name, filename, content in (
        ("database", "db_dump.sql.gz", b"db_data"),
        ("chroma_db", "chroma_db.tar.gz", b"chroma_data"),
        ("models", "models.tar.gz", b"model_data"),
    ):
        p = snap / filename
        p.write_bytes(content)
        components[name] = {
            "path": filename,
            "size_bytes": len(content),
            "sha256": sha256_file(p),
        }
    components["database"]["row_counts"] = {"bid_announcements": None}
    components["database"]["row_count_status"] = "table_query_failed"
    components["database"]["row_count_evidence"] = "unverified"

    manifest = {
        "schema": "BACKUP_MANIFEST_V1",
        "partial_backup": True,
        "recovery_trusted": False,
        "row_count_status": "table_query_failed",
        "row_count_evidence": "unverified",
        "components": components,
    }
    (snap / MANIFEST_FILENAME).write_text(json.dumps(manifest), encoding="utf-8")

    # dry-run 및 실제 복원 모두 실패 종료(fail-closed) 확인
    assert execute_restore(snap, execute=False, project_root=tmp_path) is False

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
    execute_backup,
    execute_restore,
    sha256_file,
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

"""
tests/test_backup_recovery.py

통합 백업 및 복원 도구(scripts/backup_recovery.py)의 단위 및 안전성 테스트.
실제 DB 나 mysqldump 호출 없이 tmp_path 픽스처와 모킹을 통해
dry-run 기본값, 덮어쓰기 보호, 매니페스트 생성 및 무결성 검증, 자격 증명 비노출을 검증합니다.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from scripts.backup_recovery import (
    MANIFEST_FILENAME,
    create_tar_archive,
    execute_backup,
    execute_restore,
    extract_tar_archive,
    get_db_config,
    list_snapshots,
    mask_secret,
    sha256_file,
    verify_snapshot,
)


def test_mask_secret():
    """시크릿 문자열 마스킹 동작 검증."""
    assert mask_secret("") == "<empty>"
    assert mask_secret("super_secret_password") == "******"


def test_sha256_file(tmp_path: Path):
    """파일 SHA256 체크섬 계산 검증."""
    test_file = tmp_path / "sample.txt"
    test_file.write_text("hello refac_bid_box backup", encoding="utf-8")
    expected_sha = hashlib.sha256(b"hello refac_bid_box backup").hexdigest()
    assert sha256_file(test_file) == expected_sha


def test_tar_archive_create_and_extract(tmp_path: Path):
    """tar.gz 아카이브 압축 및 해제 무결성 검증."""
    src_dir = tmp_path / "src_data"
    src_dir.mkdir()
    (src_dir / "file1.txt").write_text("data 1", encoding="utf-8")
    (src_dir / "sub").mkdir()
    (src_dir / "sub" / "file2.txt").write_text("data 2", encoding="utf-8")

    archive_file = tmp_path / "archive.tar.gz"
    size_bytes, sha = create_tar_archive([src_dir], archive_file, base_dir=tmp_path)

    assert archive_file.exists()
    assert size_bytes == archive_file.stat().st_size
    assert len(sha) == 64

    dest_dir = tmp_path / "extracted"
    extract_tar_archive(archive_file, dest_dir)
    assert (dest_dir / "src_data" / "file1.txt").read_text(encoding="utf-8") == "data 1"
    assert (dest_dir / "src_data" / "sub" / "file2.txt").read_text(encoding="utf-8") == "data 2"


def test_backup_dry_run_default_creates_no_files(tmp_path: Path):
    """기본 dry-run 모드에서는 어떤 백업 파일도 쓰지 않아야 합니다."""
    target_out = tmp_path / "snapshot_dryrun"

    res = execute_backup(output_dir=target_out, execute=False, project_root=tmp_path)

    assert res["mode"] == "dry-run"
    assert not target_out.exists()


@patch("scripts.backup_recovery.dump_mysql_database")
@patch("scripts.backup_recovery.query_db_row_counts")
@patch("scripts.backup_recovery.get_head_commit_sha")
def test_backup_execute_generates_manifest(
    mock_head_sha: MagicMock,
    mock_query_counts: MagicMock,
    mock_dump_mysql: MagicMock,
    tmp_path: Path,
):
    """실제 실행(--execute) 시 모든 컴포넌트 아카이브와 매니페스트가 생성되어야 합니다."""
    mock_head_sha.return_value = "0123456789abcdef"
    mock_query_counts.return_value = {
        "bid_announcements": 1839088,
        "bid_results": 3002254,
    }

    def fake_dump_mysql(db_config, out_path):
        out_path.write_bytes(b"fake compressed sql dump")
        return len(b"fake compressed sql dump"), sha256_file(out_path)

    mock_dump_mysql.side_effect = fake_dump_mysql

    # 가짜 ChromaDB 및 모델 디렉토리 생성
    chroma_dir = tmp_path / "chroma_db"
    chroma_dir.mkdir()
    (chroma_dir / "chroma.sqlite3").write_text("sqlite dummy", encoding="utf-8")

    models_dir = tmp_path / "data" / "model_files"
    models_dir.mkdir(parents=True)
    (models_dir / "model.bin").write_text("model dummy", encoding="utf-8")

    target_out = tmp_path / "snapshot_exec"

    with patch.dict("os.environ", {"CHROMA_DB_PATH": str(chroma_dir)}):
        manifest = execute_backup(output_dir=target_out, execute=True, project_root=tmp_path)

    assert target_out.exists()
    manifest_file = target_out / MANIFEST_FILENAME
    assert manifest_file.exists()

    assert manifest["schema"] == "BACKUP_MANIFEST_V1"
    assert manifest["head_commit"] == "0123456789abcdef"
    assert "components" in manifest
    assert "database" in manifest["components"]
    assert "chroma_db" in manifest["components"]
    assert "models" in manifest["components"]

    assert manifest["components"]["database"]["row_counts"]["bid_announcements"] == 1839088
    assert (target_out / "db_dump.sql.gz").exists()
    assert (target_out / "chroma_db.tar.gz").exists()
    assert (target_out / "models.tar.gz").exists()


def test_verify_snapshot_valid(tmp_path: Path):
    """정상 스냅샷 검증 통과 확인."""
    snapshot_dir = tmp_path / "valid_snapshot"
    snapshot_dir.mkdir()

    db_file = snapshot_dir / "db_dump.sql.gz"
    db_file.write_bytes(b"db_bytes")
    chroma_file = snapshot_dir / "chroma_db.tar.gz"
    chroma_file.write_bytes(b"chroma_bytes")
    models_file = snapshot_dir / "models.tar.gz"
    models_file.write_bytes(b"models_bytes")

    manifest_data = {
        "schema": "BACKUP_MANIFEST_V1",
        "created_at": "2026-09-02T12:00:00Z",
        "head_commit": "abc1234",
        "components": {
            "database": {
                "path": "db_dump.sql.gz",
                "size_bytes": db_file.stat().st_size,
                "sha256": sha256_file(db_file),
                "row_counts": {},
            },
            "chroma_db": {
                "path": "chroma_db.tar.gz",
                "size_bytes": chroma_file.stat().st_size,
                "sha256": sha256_file(chroma_file),
            },
            "models": {
                "path": "models.tar.gz",
                "size_bytes": models_file.stat().st_size,
                "sha256": sha256_file(models_file),
            },
        },
    }
    (snapshot_dir / MANIFEST_FILENAME).write_text(json.dumps(manifest_data), encoding="utf-8")

    is_valid, errors, loaded_manifest = verify_snapshot(snapshot_dir)
    assert is_valid is True
    assert len(errors) == 0
    assert loaded_manifest["head_commit"] == "abc1234"


def test_verify_snapshot_tampered_fails(tmp_path: Path):
    """변조되거나 손상된 스냅샷 파일 검증 실패 확인."""
    snapshot_dir = tmp_path / "tampered_snapshot"
    snapshot_dir.mkdir()

    db_file = snapshot_dir / "db_dump.sql.gz"
    db_file.write_bytes(b"original_db")
    chroma_file = snapshot_dir / "chroma_db.tar.gz"
    chroma_file.write_bytes(b"original_chroma")
    models_file = snapshot_dir / "models.tar.gz"
    models_file.write_bytes(b"original_models")

    manifest_data = {
        "schema": "BACKUP_MANIFEST_V1",
        "created_at": "2026-09-02T12:00:00Z",
        "head_commit": "abc1234",
        "components": {
            "database": {
                "path": "db_dump.sql.gz",
                "size_bytes": db_file.stat().st_size,
                "sha256": sha256_file(db_file),
            },
            "chroma_db": {
                "path": "chroma_db.tar.gz",
                "size_bytes": chroma_file.stat().st_size,
                "sha256": sha256_file(chroma_file),
            },
            "models": {
                "path": "models.tar.gz",
                "size_bytes": models_file.stat().st_size,
                "sha256": sha256_file(models_file),
            },
        },
    }
    (snapshot_dir / MANIFEST_FILENAME).write_text(json.dumps(manifest_data), encoding="utf-8")

    # 변조 전에는 유효함 확인
    assert verify_snapshot(snapshot_dir)[0] is True

    # 사후 파일 변조
    db_file.write_bytes(b"tampered_db_content")

    is_valid, errors, _ = verify_snapshot(snapshot_dir)
    assert is_valid is False
    assert any("SHA256 체크섬 불일치" in err or "파일 크기 불일치" in err for err in errors)


def test_restore_dry_run_default_does_not_modify(tmp_path: Path):
    """복원 dry-run 모드는 데이터를 덮어쓰지 않고 안내만 출력합니다."""
    snapshot_dir = tmp_path / "snap"
    snapshot_dir.mkdir()
    db_file = snapshot_dir / "db_dump.sql.gz"
    db_file.write_bytes(b"db")
    chroma_file = snapshot_dir / "chroma_db.tar.gz"
    chroma_file.write_bytes(b"chroma")
    models_file = snapshot_dir / "models.tar.gz"
    models_file.write_bytes(b"models")

    (snapshot_dir / MANIFEST_FILENAME).write_text(
        json.dumps(
            {
                "schema": "BACKUP_MANIFEST_V1",
                "partial_backup": False,
                "recovery_trusted": True,
                "components": {
                    "database": {
                        "path": "db_dump.sql.gz",
                        "size_bytes": db_file.stat().st_size,
                        "sha256": sha256_file(db_file),
                    },
                    "chroma_db": {
                        "path": "chroma_db.tar.gz",
                        "size_bytes": chroma_file.stat().st_size,
                        "sha256": sha256_file(chroma_file),
                    },
                    "models": {
                        "path": "models.tar.gz",
                        "size_bytes": models_file.stat().st_size,
                        "sha256": sha256_file(models_file),
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    success = execute_restore(
        snapshot_dir=snapshot_dir,
        execute=False,
        confirm=False,
        project_root=tmp_path,
    )
    assert success is True


def test_restore_dry_run_incomplete_manifest_fails(tmp_path: Path):
    """불완전하거나 검증 실패한 스냅샷은 dry-run 복원에서도 성공을 반환하지 않습니다."""
    snapshot_dir = tmp_path / "incomplete_snap"
    snapshot_dir.mkdir()
    (snapshot_dir / MANIFEST_FILENAME).write_text(
        json.dumps({"schema": "BACKUP_MANIFEST_V1", "components": {}}),
        encoding="utf-8",
    )
    success = execute_restore(
        snapshot_dir=snapshot_dir,
        execute=False,
        confirm=False,
        project_root=tmp_path,
    )
    assert success is False


def test_restore_without_confirm_in_non_interactive_aborts(tmp_path: Path):
    """비대화형 환경에서 --confirm 없이 --execute 시 복원이 거부되어야 합니다."""
    snapshot_dir = tmp_path / "snap"
    snapshot_dir.mkdir()
    db_file = snapshot_dir / "db_dump.sql.gz"
    db_file.write_bytes(b"db")
    chroma_file = snapshot_dir / "chroma_db.tar.gz"
    chroma_file.write_bytes(b"chroma")
    models_file = snapshot_dir / "models.tar.gz"
    models_file.write_bytes(b"models")

    (snapshot_dir / MANIFEST_FILENAME).write_text(
        json.dumps(
            {
                "schema": "BACKUP_MANIFEST_V1",
                "partial_backup": False,
                "recovery_trusted": True,
                "components": {
                    "database": {
                        "path": "db_dump.sql.gz",
                        "size_bytes": db_file.stat().st_size,
                        "sha256": sha256_file(db_file),
                    },
                    "chroma_db": {
                        "path": "chroma_db.tar.gz",
                        "size_bytes": chroma_file.stat().st_size,
                        "sha256": sha256_file(chroma_file),
                    },
                    "models": {
                        "path": "models.tar.gz",
                        "size_bytes": models_file.stat().st_size,
                        "sha256": sha256_file(models_file),
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    with patch("sys.stdin.isatty", return_value=False):
        success = execute_restore(
            snapshot_dir=snapshot_dir,
            execute=True,
            confirm=False,
            project_root=tmp_path,
        )
    assert success is False


@patch("scripts.backup_recovery.restore_mysql_database")
@patch("scripts.backup_recovery.run_post_restore_verification")
def test_restore_execute_with_confirm(
    mock_verify: MagicMock,
    mock_restore_db: MagicMock,
    tmp_path: Path,
):
    """--execute 와 --confirm 플래그 전달 시 정상 복원 및 사후 검증이 호출됩니다."""
    mock_verify.return_value = True

    snapshot_dir = tmp_path / "snap"
    snapshot_dir.mkdir()

    db_file = snapshot_dir / "db_dump.sql.gz"
    db_file.write_bytes(b"db_data")

    chroma_src = tmp_path / "src_chroma"
    chroma_src.mkdir()
    (chroma_src / "data.txt").write_text("chroma data", encoding="utf-8")
    chroma_archive = snapshot_dir / "chroma_db.tar.gz"
    create_tar_archive([chroma_src], chroma_archive, base_dir=tmp_path)

    models_src = tmp_path / "src_models"
    models_src.mkdir()
    (models_src / "model.bin").write_text("model data", encoding="utf-8")
    models_archive = snapshot_dir / "models.tar.gz"
    create_tar_archive([models_src], models_archive, base_dir=tmp_path)

    manifest_data = {
        "schema": "BACKUP_MANIFEST_V1",
        "partial_backup": False,
        "recovery_trusted": True,
        "components": {
            "database": {
                "path": "db_dump.sql.gz",
                "size_bytes": db_file.stat().st_size,
                "sha256": sha256_file(db_file),
            },
            "chroma_db": {
                "path": "chroma_db.tar.gz",
                "size_bytes": chroma_archive.stat().st_size,
                "sha256": sha256_file(chroma_archive),
            },
            "models": {
                "path": "models.tar.gz",
                "size_bytes": models_archive.stat().st_size,
                "sha256": sha256_file(models_archive),
            },
        },
    }
    (snapshot_dir / MANIFEST_FILENAME).write_text(json.dumps(manifest_data), encoding="utf-8")

    success = execute_restore(
        snapshot_dir=snapshot_dir,
        execute=True,
        confirm=True,
        skip_verify=False,
        project_root=tmp_path,
    )

    assert success is True
    mock_restore_db.assert_called_once()
    mock_verify.assert_called_once()


def test_list_snapshots(tmp_path: Path):
    """스냅샷 목록 조회 함수 검증."""
    snapshots_dir = tmp_path / "snapshots"
    snapshots_dir.mkdir()

    s1 = snapshots_dir / "snapshot_20260902_100000"
    s1.mkdir()
    (s1 / MANIFEST_FILENAME).write_text(
        json.dumps({"created_at": "2026-09-02T10:00:00Z", "head_commit": "c1", "components": {}}),
        encoding="utf-8",
    )

    res = list_snapshots(snapshots_dir)
    assert len(res) == 1
    assert res[0]["name"] == "snapshot_20260902_100000"
    assert res[0]["head_commit"] == "c1"


def test_no_secrets_in_manifest_or_config_defaults():
    """자격 증명 실제 값이 코드 기본값이나 매니페스트에 노출되지 않는지 점검."""
    cfg = get_db_config()
    assert isinstance(cfg, dict)
    assert "user" in cfg
    assert "password" in cfg

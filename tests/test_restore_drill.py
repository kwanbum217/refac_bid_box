"""복원 리허설(restore drill) 실측 도구 단위 및 격리 안전성 테스트.

아카이브 해제, DB import, G1 무손실 검증 재사용, 소요 시간 및 RPO 차이 계측,
격리 가드(경로 및 DB), 산출물 정리(cleanup) 및 명시 보존 플래그를 검증합니다.
실제 MySQL 및 Docker 서비스는 호출하지 않고 대역(Mock)을 통해 안전하게 검증합니다.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts.backup_recovery import (
    MANIFEST_FILENAME,
    PROJECT_ROOT,
    build_parser,
    cleanup_drill_target_dir,
    run_drill_g1_verification,
    run_restore_drill,
    sha256_file,
)
from scripts.backup_recovery_core import (
    create_mysql_database,
    drop_mysql_database,
)


def _create_valid_snapshot(
    snapshot_dir: Path,
    *,
    created_at: str = "2026-09-03T10:00:00+00:00",
    partial: bool = False,
    trusted: bool = True,
) -> Path:
    """테스트용 유효한 통합 백업 스냅샷을 생성합니다."""
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    db_dump = snapshot_dir / "db_dump.sql.gz"
    db_dump.write_bytes(b"dummy_compressed_sql_dump")

    chroma_tar = snapshot_dir / "chroma_db.tar.gz"
    chroma_tar.write_bytes(b"dummy_chroma_archive")

    models_tar = snapshot_dir / "models.tar.gz"
    models_tar.write_bytes(b"dummy_models_archive")

    manifest_data = {
        "schema": "BACKUP_MANIFEST_V1",
        "created_at": created_at,
        "head_commit": "abcdef1234567890",
        "partial_backup": partial,
        "recovery_trusted": trusted,
        "consistency_window": {
            "db_dump_started_at": "2026-09-03T09:59:40+00:00",
            "db_dump_finished_at": "2026-09-03T09:59:55+00:00",
            "file_assets_collected_at": "2026-09-03T10:00:00+00:00",
        },
        "components": {
            "database": {
                "path": "db_dump.sql.gz",
                "size_bytes": db_dump.stat().st_size,
                "sha256": sha256_file(db_dump),
                "row_counts": {"bid_announcements": 100, "bid_results": 200},
            },
            "chroma_db": {
                "path": "chroma_db.tar.gz",
                "size_bytes": chroma_tar.stat().st_size,
                "sha256": sha256_file(chroma_tar),
                "status": "available",
            },
            "models": {
                "path": "models.tar.gz",
                "size_bytes": models_tar.stat().st_size,
                "sha256": sha256_file(models_tar),
                "status": "available",
            },
        },
    }
    manifest_file = snapshot_dir / MANIFEST_FILENAME
    manifest_file.write_text(
        json.dumps(manifest_data, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return snapshot_dir


def test_drill_path_isolation_guards(tmp_path: Path):
    """프로젝트 루트, 루트 상위, 루트 내부 등 격리되지 않은 디렉토리 지정을 거부합니다."""
    project_root = tmp_path / "fake_repo"
    project_root.mkdir()
    snapshot_dir = _create_valid_snapshot(tmp_path / "snapshot")

    # 1. 빈 문자열
    with pytest.raises(ValueError, match="대상 디렉토리를 지정해야 합니다"):
        run_restore_drill(snapshot_dir, Path(""), project_root=project_root)

    # 2. 현재 디렉토리 점(".")
    with pytest.raises(ValueError, match="대상 디렉토리를 지정해야 합니다"):
        run_restore_drill(snapshot_dir, Path("."), project_root=project_root)

    # 3. 프로젝트 루트 동일 경로
    with pytest.raises(ValueError, match="격리 디렉토리여야 합니다"):
        run_restore_drill(snapshot_dir, project_root, project_root=project_root)

    # 4. 프로젝트 루트의 상위 경로
    with pytest.raises(ValueError, match="격리 디렉토리여야 합니다"):
        run_restore_drill(snapshot_dir, project_root.parent, project_root=project_root)

    # 5. 프로젝트 루트 내부 서브디렉토리
    inside_dir = project_root / "subdir"
    with pytest.raises(ValueError, match="격리 디렉토리여야 합니다"):
        run_restore_drill(snapshot_dir, inside_dir, project_root=project_root)


def test_drill_db_isolation_guards(tmp_path: Path):
    """운영 DB와 동일한 이름 또는 동일한 접속 대상에 대한 리허설을 거부합니다."""
    project_root = tmp_path / "fake_repo"
    project_root.mkdir()
    isolated_target = tmp_path / "isolated_drill_target"
    snapshot_dir = _create_valid_snapshot(tmp_path / "snapshot")

    fake_prod_db = {
        "host": "localhost",
        "port": 3306,
        "user": "root",
        "password": "secret_password",
        "name": "procurement",
    }

    with patch("scripts.backup_recovery.get_db_config", return_value=fake_prod_db):
        # 1. 빈 DB 이름
        with pytest.raises(ValueError, match="DB 이름을 지정해야 합니다"):
            run_restore_drill(
                snapshot_dir,
                isolated_target,
                drill_db_config={"name": "", "host": "localhost", "port": 3306},
                project_root=project_root,
            )

        # 2. 운영 DB와 이름 동일
        with pytest.raises(ValueError, match="운영 DB와 동일할 수 없습니다"):
            run_restore_drill(
                snapshot_dir,
                isolated_target,
                drill_db_config={"name": "procurement", "host": "other_host", "port": 3306},
                project_root=project_root,
            )

        # 3. 운영 DB와 접속 대상 전체 일치
        with pytest.raises(ValueError, match="운영 DB와 동일"):
            run_restore_drill(
                snapshot_dir,
                isolated_target,
                drill_db_config=fake_prod_db,
                project_root=project_root,
            )


def test_drill_rejects_partial_or_untrusted_snapshot(tmp_path: Path):
    """부분 백업이거나 신뢰할 수 없는 스냅샷은 실제 복원을 수행하지 않고 실패합니다."""
    project_root = tmp_path / "fake_repo"
    project_root.mkdir()
    isolated_target = tmp_path / "drill_target"
    snapshot_dir = _create_valid_snapshot(tmp_path / "snapshot", partial=True, trusted=False)

    with (
        patch("scripts.backup_recovery.extract_tar_archive") as mock_extract,
        patch("scripts.backup_recovery.create_mysql_database") as mock_create_db,
        patch("scripts.backup_recovery.restore_mysql_database") as mock_restore_db,
    ):
        report = run_restore_drill(snapshot_dir, isolated_target, project_root=project_root)

    assert report["schema"] == "RESTORE_DRILL_REPORT_V2"
    assert report["success"] is False
    assert report["snapshot_valid"] is False
    assert any("부분 백업은 복구용으로 신뢰할 수 없습니다" in err for err in report["errors"])
    mock_extract.assert_not_called()
    mock_create_db.assert_not_called()
    mock_restore_db.assert_not_called()


def test_drill_executes_extraction_db_import_and_g1_verification(tmp_path: Path):
    """유효한 스냅샷에 대해 실제로 아카이브를 풀고 DB를 import하며 G1 검증을 수행합니다."""
    project_root = tmp_path / "fake_repo"
    project_root.mkdir()
    isolated_target = tmp_path / "drill_target"
    snapshot_dir = _create_valid_snapshot(tmp_path / "snapshot")

    fake_prod_db = {
        "host": "localhost",
        "port": 3306,
        "user": "root",
        "password": "pwd",
        "name": "procurement",
    }
    drill_db = {
        "host": "localhost",
        "port": 3306,
        "user": "root",
        "password": "pwd",
        "name": "procurement_restore_drill",
    }

    mock_g1_report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "overall_verdict": "PASS",
        "results": [
            {"name": "ML 가중치 4종 무결성", "status": "PASS"},
            {"name": "ChromaDB 컬렉션 무결성", "status": "PASS"},
            {"name": "DB 테이블 존재 여부", "status": "PASS"},
            {"name": "DB 전 테이블 스키마 서명 정합성", "status": "PASS"},
            {"name": "데이터 행 수 하한 검증", "status": "PASS"},
            {"name": "G1 reconciliation: 원본/성장분 분리 대조", "status": "PASS"},
        ],
    }

    with (
        patch("scripts.backup_recovery.get_db_config", return_value=fake_prod_db),
        patch("scripts.backup_recovery.create_mysql_database") as mock_create_db,
        patch("scripts.backup_recovery.restore_mysql_database") as mock_restore_db,
        patch("scripts.backup_recovery.drop_mysql_database") as mock_drop_db,
        patch("scripts.backup_recovery.extract_tar_archive") as mock_extract,
        patch(
            "scripts.backup_recovery.run_drill_g1_verification",
            return_value=(True, "G1 무손실 검증 통과", mock_g1_report),
        ) as mock_g1,
    ):
        report = run_restore_drill(
            snapshot_dir=snapshot_dir,
            target_dir=isolated_target,
            drill_db_config=drill_db,
            keep_artifacts=False,
            project_root=project_root,
        )

    assert report["schema"] == "RESTORE_DRILL_REPORT_V2"
    assert report["success"] is True
    assert report["snapshot_valid"] is True
    assert "chroma_db" in report["extracted_components"]
    assert "models" in report["extracted_components"]

    # 실제 추출 및 DB 복원, G1 검증 호출 확인
    assert mock_extract.call_count == 2
    mock_create_db.assert_called_once_with(drill_db)
    mock_restore_db.assert_called_once_with(drill_db, snapshot_dir / "db_dump.sql.gz")
    mock_g1.assert_called_once()
    mock_drop_db.assert_called_once()


def test_drill_records_timings_and_rpo_measurements_without_threshold_verdict(tmp_path: Path):
    """단계별 시작·종료 시각과 RPO 소요시간 차이를 기록하되, 목표값 비교 판정은 하지 않습니다."""
    project_root = tmp_path / "fake_repo"
    project_root.mkdir()
    isolated_target = tmp_path / "drill_target"
    snapshot_dir = _create_valid_snapshot(
        tmp_path / "snapshot", created_at="2026-09-03T08:00:00+00:00"
    )

    with (
        patch("scripts.backup_recovery.create_mysql_database"),
        patch("scripts.backup_recovery.restore_mysql_database"),
        patch("scripts.backup_recovery.drop_mysql_database"),
        patch("scripts.backup_recovery.extract_tar_archive"),
        patch(
            "scripts.backup_recovery.run_drill_g1_verification",
            return_value=(True, "G1 통과", {"overall_verdict": "PASS"}),
        ),
    ):
        report = run_restore_drill(
            snapshot_dir=snapshot_dir,
            target_dir=isolated_target,
            project_root=project_root,
        )

    # 1. 단계별 소요 시간 구조 검증
    timings = report["timings"]
    for step in (
        "snapshot_verification",
        "archive_extraction",
        "database_import",
        "g1_verification",
        "cleanup",
    ):
        assert step in timings, f"{step} 단계가 timings 에 누락되었습니다."
        assert timings[step]["started_at"] is not None
        assert timings[step]["finished_at"] is not None
        assert isinstance(timings[step]["duration_seconds"], float)
        assert timings[step]["status"] in ("PASS", "FAIL", "SKIPPED", "KEPT")

    # 2. RPO 관련 측정값 구조 검증
    rpo = report["rpo_measurements"]
    assert "snapshot_created_at" in rpo
    assert "consistency_window" in rpo
    assert "drill_started_at" in rpo
    assert isinstance(rpo["created_at_to_drill_start_seconds"], float)
    assert isinstance(rpo["db_dump_finished_to_drill_start_seconds"], float)
    assert isinstance(rpo["file_assets_to_drill_start_seconds"], float)

    # 3. 목표값 비교 판정 부재 검증 (SLA, threshold, pass/fail 판정 필드가 없어야 함)
    assert "rpo_sla_met" not in rpo
    assert "rto_sla_met" not in rpo
    assert "threshold" not in rpo
    assert "verdict" not in rpo


def test_drill_cleanup_performed_on_success_and_failure(tmp_path: Path):
    """기본 모드에서는 성공 및 실패 시 모두 산출물을 정리하고, keep_artifacts 시 보존합니다."""
    project_root = tmp_path / "fake_repo"
    project_root.mkdir()
    snapshot_dir = _create_valid_snapshot(tmp_path / "snapshot")

    # 1. 성공 시 자동 정리
    target1 = tmp_path / "target_success"
    with (
        patch("scripts.backup_recovery.create_mysql_database"),
        patch("scripts.backup_recovery.restore_mysql_database"),
        patch("scripts.backup_recovery.drop_mysql_database") as mock_drop_1,
        patch("scripts.backup_recovery.extract_tar_archive"),
        patch(
            "scripts.backup_recovery.run_drill_g1_verification",
            return_value=(True, "통과", {}),
        ),
    ):
        report1 = run_restore_drill(
            snapshot_dir, target1, keep_artifacts=False, project_root=project_root
        )
    assert report1["timings"]["cleanup"]["status"] == "PASS"
    mock_drop_1.assert_called_once()
    assert not target1.exists()

    # 2. 실패(예외 발생) 시에도 자동 정리
    target2 = tmp_path / "target_failure"
    with (
        patch("scripts.backup_recovery.create_mysql_database"),
        patch(
            "scripts.backup_recovery.restore_mysql_database",
            side_effect=RuntimeError("DB 복원 중단"),
        ),
        patch("scripts.backup_recovery.drop_mysql_database") as mock_drop_2,
        patch("scripts.backup_recovery.extract_tar_archive"),
    ):
        report2 = run_restore_drill(
            snapshot_dir, target2, keep_artifacts=False, project_root=project_root
        )
    assert report2["success"] is False
    assert report2["timings"]["cleanup"]["status"] == "PASS"
    mock_drop_2.assert_called_once()
    assert not target2.exists()

    # 3. keep_artifacts=True 시 보존
    target3 = tmp_path / "target_kept"
    with (
        patch("scripts.backup_recovery.create_mysql_database"),
        patch("scripts.backup_recovery.restore_mysql_database"),
        patch("scripts.backup_recovery.drop_mysql_database") as mock_drop_3,
        patch("scripts.backup_recovery.extract_tar_archive"),
        patch(
            "scripts.backup_recovery.run_drill_g1_verification",
            return_value=(True, "통과", {}),
        ),
    ):
        report3 = run_restore_drill(
            snapshot_dir, target3, keep_artifacts=True, project_root=project_root
        )
    assert report3["timings"]["cleanup"]["status"] == "KEPT"
    mock_drop_3.assert_not_called()
    assert target3.exists()


def test_drill_fails_if_g1_verification_fails(tmp_path: Path):
    """G1 무손실 검증이 실패하면 전체 리허설은 실패(success: False)로 판정됩니다."""
    project_root = tmp_path / "fake_repo"
    project_root.mkdir()
    isolated_target = tmp_path / "drill_target"
    snapshot_dir = _create_valid_snapshot(tmp_path / "snapshot")

    with (
        patch("scripts.backup_recovery.create_mysql_database"),
        patch("scripts.backup_recovery.restore_mysql_database"),
        patch("scripts.backup_recovery.drop_mysql_database"),
        patch("scripts.backup_recovery.extract_tar_archive"),
        patch(
            "scripts.backup_recovery.run_drill_g1_verification",
            return_value=(False, "행 수 불일치: 10건 누락", {}),
        ),
    ):
        report = run_restore_drill(
            snapshot_dir=snapshot_dir,
            target_dir=isolated_target,
            project_root=project_root,
        )

    assert report["success"] is False
    assert report["timings"]["g1_verification"]["status"] == "FAIL"
    assert any("G1 무손실 검증 실패" in err for err in report["errors"])


def test_drop_mysql_database_guard():
    """drop_mysql_database 가 운영 DB에 대해 호출되면 즉시 거부합니다."""
    prod_db = {"host": "localhost", "port": 3306, "user": "root", "name": "procurement"}
    with pytest.raises(ValueError, match=r"운영 DB.*삭제할 수 없습니다"):
        drop_mysql_database(prod_db, prod_config=prod_db)


def test_create_and_drop_mysql_database_subprocesses():
    """create_mysql_database 및 drop_mysql_database 가 subprocess 를 올바르게 호출합니다."""
    drill_db = {
        "host": "localhost",
        "port": 3306,
        "user": "root",
        "password": "pwd",
        "name": "procurement_restore_drill",
    }
    prod_db = {"host": "localhost", "port": 3306, "user": "root", "name": "procurement"}

    with patch("subprocess.run") as mock_run:
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_run.return_value = mock_proc

        create_mysql_database(drill_db)
        assert mock_run.call_count == 1
        create_args = mock_run.call_args[0][0]
        assert any(
            "CREATE DATABASE IF NOT EXISTS `procurement_restore_drill`" in str(arg)
            for arg in create_args
        )

        drop_mysql_database(drill_db, prod_config=prod_db)
        assert mock_run.call_count == 2
        drop_args = mock_run.call_args[0][0]
        assert any(
            "DROP DATABASE IF EXISTS `procurement_restore_drill`" in str(arg) for arg in drop_args
        )


def test_run_drill_g1_verification_subprocess(tmp_path: Path):
    """run_drill_g1_verification 이 verify_migration.py 를 올바른 격리 환경변수로 호출합니다."""
    target_dir = tmp_path / "drill_target"
    target_dir.mkdir()
    report_file = target_dir / "report.json"
    report_file.write_text(json.dumps({"overall_verdict": "PASS"}), encoding="utf-8")

    drill_db = {
        "host": "localhost",
        "port": 3306,
        "user": "root",
        "password": "pwd",
        "name": "procurement_restore_drill",
    }

    with patch("subprocess.run") as mock_run:
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "PASS"
        mock_run.return_value = mock_proc

        ok, msg, rep = run_drill_g1_verification(
            target_dir=target_dir,
            drill_db_config=drill_db,
            report_path=report_file,
        )

        assert ok is True
        assert "G1 무손실 검증 통과" in msg
        assert rep.get("overall_verdict") == "PASS"

        # 환경변수 전달 확인
        env_passed = mock_run.call_args[1]["env"]
        assert env_passed["DB_NAME"] == "procurement_restore_drill"
        assert env_passed["DATA_ASSET_ROOT"] == str(target_dir)
        assert env_passed["CHROMA_DB_PATH"] == str(target_dir / "chroma_db")


def test_drill_cli_parser_and_arguments():
    """drill 서브커맨드의 인자 파싱을 검증합니다."""
    parser = build_parser()
    args = parser.parse_args(
        [
            "drill",
            "--snapshot-dir",
            "/tmp/snapshot",
            "--target-dir",
            "/tmp/drill_target",
            "--report-path",
            "/tmp/report.json",
            "--db-name",
            "custom_drill_db",
            "--keep-artifacts",
        ]
    )
    assert args.command == "drill"
    assert args.snapshot_dir == Path("/tmp/snapshot")
    assert args.target_dir == Path("/tmp/drill_target")
    assert args.report_path == Path("/tmp/report.json")
    assert args.db_name == "custom_drill_db"
    assert args.keep_artifacts is True


def test_cleanup_drill_target_dir_refuses_non_isolated_paths(tmp_path: Path):
    """정리 함수가 비정상 경로, 프로젝트 루트, 작업 디렉토리, 상위/하위 경로를 받았을 때 지우지 않고 거부합니다."""
    # 1. 빈 문자열 및 점 경로 거부
    for invalid in ("", " ", ".", "./", "..", "../", "/"):
        with pytest.raises(ValueError, match=r"격리되지 않은|정리할 수 없습니다"):
            cleanup_drill_target_dir(Path(invalid))

    # 2. 운영 프로젝트 루트(PROJECT_ROOT) 거부
    with pytest.raises(ValueError, match=r"격리되지 않은|정리할 수 없습니다"):
        cleanup_drill_target_dir(PROJECT_ROOT)

    # 3. 운영 프로젝트 루트 내부 하위 디렉토리(scripts 등) 거부
    with pytest.raises(ValueError, match=r"격리되지 않은|정리할 수 없습니다"):
        cleanup_drill_target_dir(PROJECT_ROOT / "scripts")

    # 4. 운영 프로젝트 루트의 상위 경로 거부
    with pytest.raises(ValueError, match=r"격리되지 않은|정리할 수 없습니다"):
        cleanup_drill_target_dir(PROJECT_ROOT.parent)

    # 5. 현재 작업 디렉토리(Path.cwd()) 거부
    with pytest.raises(ValueError, match=r"격리되지 않은|정리할 수 없습니다"):
        cleanup_drill_target_dir(Path.cwd())

    # 6. 사용자 정의 project_root 에 대한 거부
    fake_root = tmp_path / "fake_custom_root"
    fake_root.mkdir()
    (fake_root / "sample.txt").write_text("keep", encoding="utf-8")
    with pytest.raises(ValueError, match="정리할 수 없습니다"):
        cleanup_drill_target_dir(fake_root, project_root=fake_root)
    assert fake_root.exists()

    with pytest.raises(ValueError, match="정리할 수 없습니다"):
        cleanup_drill_target_dir(fake_root / "sub", project_root=fake_root)

    # 7. 완벽하게 격리된 임시 디렉토리는 안전하게 삭제 완료
    isolated_dir = tmp_path / "isolated_drill_to_delete"
    isolated_dir.mkdir()
    (isolated_dir / "data.txt").write_text("delete_me", encoding="utf-8")
    assert isolated_dir.exists()

    cleanup_drill_target_dir(isolated_dir, project_root=tmp_path / "other_root")
    assert not isolated_dir.exists()

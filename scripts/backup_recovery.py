#!/usr/bin/env python3
"""
refac_bid_box 통합 백업 및 복원 도구 (Backup & Recovery Tool)

운영 DB(MySQL), ChromaDB, 서빙 모델 및 레지스트리를
단일 복구 단위(Unified Recovery Unit)로 묶어 백업/복원/검증을 수행합니다.

안전 규칙:
  1. dry-run 이 기본값이며, 실제 실행은 --execute 플래그를 요구합니다.
  2. 복원 시 덮어쓸 대상을 먼저 출력하고 --confirm 플래그(또는 대화형 확인) 없이는 진행되지 않습니다.
  3. 백업 시 생성 시각, 대상별 경로/크기/체크섬, DB 행 수 요약, Git HEAD 커밋이 담긴 매니페스트를 기록합니다.
  4. 복원 완료 후 scripts/verify_migration.py 를 재사용해 무손실 무결성을 검증합니다.
"""

from __future__ import annotations

import argparse
import json
import subprocess  # nosec B404
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts.backup_recovery_core import (
    DEFAULT_SNAPSHOTS_DIR,
    MANIFEST_FILENAME,
    PROJECT_ROOT,
    REQUIRED_BACKUP_ASSETS,
    REQUIRED_MODEL_SOURCE_PATH,
    REQUIRED_SOURCE_ASSETS,
    BackupAssetError,
    create_tar_archive,
    dump_mysql_database,
    extract_tar_archive,
    get_asset_state,
    get_chroma_source_path,
    get_db_config,
    get_head_commit_sha,
    get_model_source_paths,
    query_db_row_counts,
    restore_mysql_database,
    sha256_file,
    validate_backup_output,
)
from scripts.backup_snapshots import (
    list_snapshots,
    prune_snapshots,
    verify_snapshot,
)

__all__ = [
    "DEFAULT_SNAPSHOTS_DIR",
    "MANIFEST_FILENAME",
    "PROJECT_ROOT",
    "REQUIRED_BACKUP_ASSETS",
    "REQUIRED_MODEL_SOURCE_PATH",
    "REQUIRED_SOURCE_ASSETS",
    "BackupAssetError",
    "create_tar_archive",
    "dump_mysql_database",
    "execute_backup",
    "execute_restore",
    "extract_tar_archive",
    "get_chroma_source_path",
    "get_db_config",
    "get_head_commit_sha",
    "get_model_source_paths",
    "list_snapshots",
    "mask_secret",
    "prune_snapshots",
    "query_db_row_counts",
    "restore_mysql_database",
    "run_post_restore_verification",
    "run_restore_drill",
    "sha256_file",
    "verify_snapshot",
]


def mask_secret(value: str) -> str:
    """비밀번호 등 시크릿 문자열을 마스킹 처리합니다."""
    if not value:
        return "<empty>"
    return "******"


def execute_backup(
    output_dir: Path | None = None,
    execute: bool = False,
    project_root: Path | None = None,
    allow_partial: bool = False,
) -> dict[str, Any]:
    """운영 DB, ChromaDB, 서빙 모델을 단일 복구 단위로 백업합니다."""
    root = project_root or PROJECT_ROOT
    db_config = get_db_config()
    chroma_path = get_chroma_source_path(root)
    model_paths = get_model_source_paths(root)
    asset_states = dict(
        zip(
            REQUIRED_SOURCE_ASSETS,
            (get_asset_state(path) for path in (chroma_path, root / REQUIRED_MODEL_SOURCE_PATH)),
            strict=True,
        )
    )
    missing_assets = [
        f"{name} ({state})" for name, state in asset_states.items() if state != "available"
    ]
    timestamp_str = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    target_dir = output_dir or (DEFAULT_SNAPSHOTS_DIR / f"snapshot_{timestamp_str}")
    print("=" * 60)
    print("refac_bid_box 통합 백업 (Unified Backup)")
    print("=" * 60)
    print(f"  실행 모드: {'[실제 실행 (EXECUTE)]' if execute else '[사전 점검 (DRY-RUN)]'}")
    print(f"  대상 스냅샷 경로: {target_dir}")
    print(
        f"  DB 대상: {db_config['user']}@{db_config['host']}:{db_config['port']}/{db_config['name']}"
    )
    print(f"  ChromaDB 대상: {chroma_path} ({'존재' if chroma_path.exists() else '미존재'})")
    print(
        f"  모델/MLOps 대상: {len(model_paths)}개 디렉토리 ({', '.join(p.name for p in model_paths)})"
    )
    if not execute:
        print("-" * 60)
        print("[DRY-RUN] 백업 대상과 경로를 확인했습니다. 파일 쓰기는 수행되지 않았습니다.")
        print("[DRY-RUN] 실제 백업을 실행하려면 --execute 플래그를 추가하십시오.")
        return {
            "mode": "dry-run",
            "target_dir": str(target_dir),
            "db_target": f"{db_config['user']}@{db_config['host']}:{db_config['port']}/{db_config['name']}",
            "chroma_path": str(chroma_path),
            "model_paths": [str(p) for p in model_paths],
            "required_assets": asset_states,
        }
    if missing_assets and not allow_partial:
        raise BackupAssetError("필수 백업 자산을 확인할 수 없습니다: " + ", ".join(missing_assets))
    print("-" * 60)
    target_dir.mkdir(parents=True, exist_ok=True)
    head_commit = get_head_commit_sha(root)
    print(f"[1/4] Git HEAD 커밋 확인: {head_commit}")
    print(f"[2/4] MySQL DB 덤프 생성 중... ({db_config['name']})")
    db_dump_file = target_dir / "db_dump.sql.gz"
    db_dump_started_at = datetime.now(UTC).isoformat()
    dump_mysql_database(db_config, db_dump_file)
    db_dump_finished_at = datetime.now(UTC).isoformat()
    db_size, db_sha256 = validate_backup_output(db_dump_file, "database")
    row_counts = query_db_row_counts(db_config)
    print(
        f"      DB 덤프 완료: {db_dump_file.name} ({db_size:,} bytes, sha256: {db_sha256[:12]}...)"
    )
    print(f"[3/4] ChromaDB 아카이브 생성 중... ({chroma_path.name})")
    chroma_dump_file = target_dir / "chroma_db.tar.gz"
    if asset_states["chroma_db"] == "available":
        create_tar_archive([chroma_path], chroma_dump_file, base_dir=root)
        chroma_size, chroma_sha256 = validate_backup_output(chroma_dump_file, "chroma_db")
    else:
        chroma_size, chroma_sha256 = None, None
    print(f"      ChromaDB 아카이브 완료: {chroma_dump_file.name} ({chroma_size})")
    print(f"[4/4] 모델 및 레지스트리 아카이브 생성 중... ({len(model_paths)}개 경로)")
    models_dump_file = target_dir / "models.tar.gz"
    if asset_states["models"] == "available":
        create_tar_archive(model_paths, models_dump_file, base_dir=root)
        models_size, models_sha256 = validate_backup_output(models_dump_file, "models")
    else:
        models_size, models_sha256 = None, None
    print(f"      모델 아카이브 완료: {models_dump_file.name} ({models_size})")
    file_assets_collected_at = datetime.now(UTC).isoformat()
    manifest_data = {
        "schema": "BACKUP_MANIFEST_V1",
        "created_at": datetime.now(UTC).isoformat(),
        "head_commit": head_commit,
        "partial_backup": bool(missing_assets),
        "recovery_trusted": not missing_assets,
        "required_assets": list(REQUIRED_BACKUP_ASSETS),
        "missing_assets": missing_assets,
        "consistency_window": {
            "db_dump_started_at": db_dump_started_at,
            "db_dump_finished_at": db_dump_finished_at,
            "file_assets_collected_at": file_assets_collected_at,
        },
        "components": {
            "database": {
                "path": db_dump_file.name,
                "size_bytes": db_size,
                "sha256": db_sha256,
                "row_counts": row_counts,
            },
            "chroma_db": {
                "path": chroma_dump_file.name if chroma_size is not None else None,
                "size_bytes": chroma_size,
                "sha256": chroma_sha256,
                "status": asset_states["chroma_db"],
                "source_path": str(chroma_path.relative_to(root))
                if chroma_path.is_relative_to(root)
                else str(chroma_path),
            },
            "models": {
                "path": models_dump_file.name if models_size is not None else None,
                "size_bytes": models_size,
                "sha256": models_sha256,
                "status": asset_states["models"],
                "source_paths": [
                    str(p.relative_to(root)) if p.is_relative_to(root) else str(p)
                    for p in model_paths
                ],
            },
        },
    }
    manifest_file = target_dir / MANIFEST_FILENAME
    manifest_file.write_text(
        json.dumps(manifest_data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print("-" * 60)
    print(f"통합 백업 스냅샷 생성 완료: {target_dir}")
    print(f"매니페스트: {manifest_file.name}")
    return manifest_data


def run_restore_drill(snapshot_dir: Path, target_dir: Path) -> dict[str, Any]:
    """격리 대상에 대한 복원 계획만 검증합니다.

    대상 디렉토리는 필수이며 프로젝트 루트 또는 운영 경로를 지정할 수 없습니다.
    아카이브를 해제하거나 DB 클라이언트를 호출하지 않아 실제 복원이 발생하지 않습니다.
    """
    if not str(target_dir).strip():
        raise ValueError("복원 리허설 대상 디렉토리를 지정해야 합니다.")
    target = target_dir.resolve()
    root = PROJECT_ROOT.resolve()
    if target == root or root in target.parents:
        raise ValueError("복원 리허설 대상은 프로젝트 루트 밖의 격리 디렉토리여야 합니다.")
    valid, errors, manifest = verify_snapshot(snapshot_dir)
    components = manifest.get("components", {})
    if manifest.get("partial_backup") or manifest.get("recovery_trusted") is False:
        errors.append("부분 백업은 복구용으로 신뢰할 수 없습니다.")
        valid = False
    return {
        "schema": "RESTORE_DRILL_REPORT_V1",
        "mode": "dry-run",
        "snapshot_dir": str(snapshot_dir),
        "target_dir": str(target),
        "snapshot_valid": valid,
        "components": sorted(components),
        "errors": errors,
        "success": valid,
    }


def run_post_restore_verification(project_root: Path | None = None) -> bool:
    """복원 후 scripts/verify_migration.py 를 실행하여 데이터 무손실 검증을 수행합니다."""
    root = project_root or PROJECT_ROOT
    verify_script = root / "scripts" / "verify_migration.py"
    if not verify_script.exists():
        print(f"      [오류] 검증 스크립트 없음: {verify_script}")
        return False

    print("=" * 60)
    print("복원 후 무손실 마이그레이션 검증 (scripts/verify_migration.py 재사용)")
    print("=" * 60)

    try:
        result = subprocess.run(  # nosec B603, B607
            [sys.executable, str(verify_script)],
            cwd=str(root),
            capture_output=False,
            text=True,
            check=False,
        )
        return result.returncode == 0
    except Exception as exc:
        print(f"검증 스크립트 실행 실패: {exc}")
        return False


def execute_restore(
    snapshot_dir: Path,
    execute: bool = False,
    confirm: bool = False,
    skip_verify: bool = False,
    project_root: Path | None = None,
) -> bool:
    """단일 복구 단위 스냅샷으로부터 DB, ChromaDB, 모델을 복원합니다."""
    root = project_root or PROJECT_ROOT
    db_config = get_db_config()
    chroma_path = get_chroma_source_path(root)
    model_paths = get_model_source_paths(root)
    print("=" * 60)
    print("refac_bid_box 통합 복원 (Unified Recovery)")
    print("=" * 60)
    print(f"  복원 소스 스냅샷: {snapshot_dir}")
    print(f"  실행 모드: {'[실제 실행 (EXECUTE)]' if execute else '[사전 점검 (DRY-RUN)]'}")
    # 1. 스냅샷 무결성 사전 검증
    is_valid, errors, manifest = verify_snapshot(snapshot_dir)
    if not is_valid:
        print("[오류] 스냅샷 매니페스트 무결성 검증 실패:")
        for err in errors:
            print(f"  - {err}")
        return False

    if manifest.get("partial_backup") or manifest.get("recovery_trusted") is False:
        print("[오류] 부분 백업 스냅샷은 복구용으로 신뢰할 수 없습니다.")
        return False

    components = manifest.get("components", {})
    created_at = manifest.get("created_at", "unknown")
    head_commit = manifest.get("head_commit", "unknown")

    print("-" * 60)
    print(f"  스냅샷 생성 시각: {created_at}")
    print(f"  스냅샷 기준 커밋: {head_commit}")
    print("-" * 60)
    print("[경고] 복원 시 아래 대상의 기존 데이터가 덮어써집니다:")
    print(
        f"  1. MySQL 운영 DB: {db_config['user']}@{db_config['host']}:{db_config['port']}/{db_config['name']}"
    )
    print(f"  2. ChromaDB 디렉토리: {chroma_path}")
    print("  3. 모델 및 MLOps 레지스트리 디렉토리:")
    for p in model_paths:
        print(f"     - {p}")
    print("-" * 60)
    if not execute:
        print(
            "[DRY-RUN] 복원 계획 및 덮어쓸 대상을 확인했습니다. 실제 데이터는 변경되지 않았습니다."
        )
        print("[DRY-RUN] 실제 복원을 진행하려면 --execute 및 --confirm 플래그를 지정하십시오.")
        return True

    # 2. 명시 확인 검사
    if not confirm:
        if sys.stdin.isatty():
            try:
                user_input = (
                    input("기존 데이터를 덮어쓰고 복원을 진행하시겠습니까? (yes/no): ")
                    .strip()
                    .lower()
                )
                if user_input != "yes":
                    print("복원 작업이 사용자에 의해 취소되었습니다.")
                    return False
            except (KeyboardInterrupt, EOFError):
                print("\n복원 작업이 취소되었습니다.")
                return False
        else:
            print("[오류] 비대화형 환경에서 실제 복원을 실행하려면 --confirm 플래그가 필수입니다.")
            return False
    # 3. 실제 복원 실행
    # 3.1 DB 복원
    db_dump_file = snapshot_dir / components["database"]["path"]
    print(f"[1/3] MySQL DB 복원 중... ({db_dump_file.name})")
    restore_mysql_database(db_config, db_dump_file)
    print("      MySQL DB 복원 완료")
    # 3.2 ChromaDB 복원
    chroma_dump_file = snapshot_dir / components["chroma_db"]["path"]
    print(f"[2/3] ChromaDB 복원 중... ({chroma_dump_file.name})")
    extract_tar_archive(chroma_dump_file, target_base_dir=root)
    print("      ChromaDB 복원 완료")
    # 3.3 모델 아카이브 복원
    models_dump_file = snapshot_dir / components["models"]["path"]
    print(f"[3/3] 모델 및 레지스트리 복원 중... ({models_dump_file.name})")
    extract_tar_archive(models_dump_file, target_base_dir=root)
    print("      모델 및 레지스트리 복원 완료")
    print("-" * 60)
    print("통합 복원 완료. 사후 무손실 검증을 시작합니다.")

    # 4. 사후 무손실 검증
    if not skip_verify:
        verify_ok = run_post_restore_verification(root)
        if not verify_ok:
            print("[경고] 복원 후 무손실 마이그레이션 검증에 실패했습니다. 로그를 확인하십시오.")
            return False
        print("[성공] 복원 후 무손실 마이그레이션 검증을 통과했습니다.")
    return True


def build_parser() -> argparse.ArgumentParser:
    """CLI 인자 파서를 구성합니다."""
    parser = argparse.ArgumentParser(
        description="refac_bid_box 통합 백업 및 복원 도구 (Unified Backup & Recovery Tool)"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # backup
    backup_parser = subparsers.add_parser("backup", help="운영 DB, ChromaDB, 모델 통합 백업")
    backup_parser.add_argument(
        "--execute",
        action="store_true",
        help="실제 백업 실행 (미지정 시 dry-run 으로 동작)",
    )
    backup_parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="백업 스냅샷 생성 경로 (기본값: data/backups/snapshots/snapshot_YYYYMMDD_HHMMSS)",
    )
    backup_parser.add_argument(
        "--allow-partial", action="store_true", help="누락 자산을 부분 백업으로 기록하도록 허용"
    )

    # restore
    restore_parser = subparsers.add_parser("restore", help="통합 백업 스냅샷 복원")
    restore_parser.add_argument(
        "--snapshot-dir",
        type=Path,
        required=True,
        help="복원할 스냅샷 디렉토리 경로 (manifest 파일 위치)",
    )
    restore_parser.add_argument(
        "--execute",
        action="store_true",
        help="실제 복원 실행 (미지정 시 dry-run 으로 동작)",
    )
    restore_parser.add_argument(
        "--confirm",
        action="store_true",
        help="데이터 덮어쓰기 명시 확인 (비대화형 환경에서 필수)",
    )
    restore_parser.add_argument(
        "--skip-verify",
        action="store_true",
        help="복원 후 scripts/verify_migration.py 검증 건너뛰기",
    )

    # verify
    verify_parser = subparsers.add_parser("verify", help="스냅샷 매니페스트 및 체크섬 무결성 검증")
    verify_parser.add_argument(
        "--snapshot-dir",
        type=Path,
        required=True,
        help="검증할 스냅샷 디렉토리 경로",
    )

    # list
    subparsers.add_parser("list", help="저장된 백업 스냅샷 목록 조회")

    # restore drill
    drill_parser = subparsers.add_parser("drill", help="격리 대상 복원 리허설(dry-run)")
    drill_parser.add_argument("--snapshot-dir", type=Path, required=True)
    drill_parser.add_argument(
        "--target-dir", type=Path, required=True, help="프로젝트 루트 밖 격리 대상 디렉토리"
    )
    drill_parser.add_argument("--report-path", type=Path, default=None)

    prune_parser = subparsers.add_parser("prune", help="스냅샷 개수 기준 보존 점검")
    prune_parser.add_argument("--snapshots-dir", type=Path, default=DEFAULT_SNAPSHOTS_DIR)
    prune_parser.add_argument("--retain-count", type=int, default=7)
    prune_parser.add_argument("--delete", action="store_true", help="삭제를 명시적으로 승인")

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.command == "backup":
        execute_backup(
            output_dir=args.output_dir, execute=args.execute, allow_partial=args.allow_partial
        )
        return 0
    if args.command == "restore":
        success = execute_restore(
            snapshot_dir=args.snapshot_dir,
            execute=args.execute,
            confirm=args.confirm,
            skip_verify=args.skip_verify,
        )
        return 0 if success else 1

    if args.command == "verify":
        is_valid, errors, manifest = verify_snapshot(args.snapshot_dir)
        print("=" * 60)
        print(f"스냅샷 무결성 검증: {args.snapshot_dir}")
        print("=" * 60)
        if is_valid:
            print("[PASS] 매니페스트 및 모든 컴포넌트 아카이브 무결성 일치")
            print(f"  생성 시각: {manifest.get('created_at')}")
            print(f"  HEAD 커밋: {manifest.get('head_commit')}")
            return 0
        print("[FAIL] 스냅샷 무결성 오류 발견:")
        for err in errors:
            print(f"  - {err}")
        return 1

    if args.command == "list":
        list_snapshots()
        return 0

    if args.command == "drill":
        try:
            report = run_restore_drill(args.snapshot_dir, args.target_dir)
        except ValueError as exc:
            print(f"[오류] {exc}")
            return 1
        if args.report_path:
            args.report_path.parent.mkdir(parents=True, exist_ok=True)
            args.report_path.write_text(
                json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
            )
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0 if report["success"] else 1

    if args.command == "prune":
        try:
            prune_snapshots(args.snapshots_dir, args.retain_count, args.delete)
        except ValueError as exc:
            print(f"[오류] {exc}")
            return 1
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())

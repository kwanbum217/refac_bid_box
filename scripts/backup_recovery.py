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
import gzip
import hashlib
import json
import os
import shutil
import subprocess  # nosec B404
import sys
import tarfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DEFAULT_SNAPSHOTS_DIR = PROJECT_ROOT / "data" / "backups" / "snapshots"
MANIFEST_FILENAME = "backup_manifest.json"

DEFAULT_TABLES = (
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
    "retrain_logs",
)


def sha256_file(path: Path) -> str:
    """파일의 SHA256 해시를 계산합니다."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def get_head_commit_sha(project_root: Path | None = None) -> str:
    """현재 Git HEAD 커밋 SHA 를 조회합니다."""
    root = project_root or PROJECT_ROOT
    try:
        result = subprocess.run(  # nosec B603, B607
            ["git", "rev-parse", "HEAD"],
            cwd=str(root),
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        return "unknown"
    return "unknown"


def get_db_config() -> dict[str, Any]:
    """DB 접속 설정을 환경 변수 또는 settings 에서 안전하게 로드합니다."""
    try:
        from src.app.core.config import settings

        return {
            "host": settings.DB_HOST,
            "port": settings.DB_PORT,
            "user": settings.DB_USER,
            "password": settings.DB_PASSWORD,
            "name": settings.DB_NAME,
        }
    except Exception:
        return {
            "host": os.environ.get("DB_HOST", "localhost"),
            "port": int(os.environ.get("DB_PORT", "3306")),
            "user": os.environ.get("DB_USER", "root"),
            "password": os.environ.get("DB_PASSWORD", os.environ.get("MYSQL_ROOT_PASSWORD", "")),
            "name": os.environ.get("DB_NAME", "procurement"),
        }


def mask_secret(value: str) -> str:
    """비밀번호 등 시크릿 문자열을 마스킹 처리합니다."""
    if not value:
        return "<empty>"
    return "******"


def get_model_source_paths(project_root: Path | None = None) -> list[Path]:
    """백업 대상 모델 및 MLOps 디렉토리 목록을 반환합니다."""
    root = project_root or PROJECT_ROOT
    candidates = [
        root / "data" / "model_files",
        root / "data" / "model_backups",
        root / "data" / "model_metrics",
        root / "ml_registry",
    ]
    return [p for p in candidates if p.exists()]


def get_chroma_source_path(project_root: Path | None = None) -> Path:
    """ChromaDB 데이터 디렉토리 경로를 반환합니다."""
    root = project_root or PROJECT_ROOT
    chroma_env = os.environ.get("CHROMA_DB_PATH")
    if chroma_env:
        candidate = Path(chroma_env)
        if not candidate.is_absolute():
            candidate = root / candidate
        return candidate
    return root / "chroma_db"


def query_db_row_counts(
    db_config: dict[str, Any], tables: tuple[str, ...] = DEFAULT_TABLES
) -> dict[str, int]:
    """DB 테이블별 행 수를 조회합니다."""
    row_counts: dict[str, int] = {}
    try:
        from sqlalchemy import create_engine, text

        url = (
            f"mysql+pymysql://{db_config['user']}:{db_config['password']}"
            f"@{db_config['host']}:{db_config['port']}/{db_config['name']}"
        )
        engine = create_engine(url, connect_args={"connect_timeout": 5})
        with engine.connect() as conn:
            for tbl in tables:
                if tbl not in DEFAULT_TABLES:
                    continue
                try:
                    query = text(f"SELECT COUNT(*) FROM `{tbl}`")  # noqa: S608 # nosec B608
                    result = conn.execute(query)
                    row_counts[tbl] = int(result.scalar() or 0)
                except Exception:
                    row_counts[tbl] = 0
    except Exception as exc:
        print(f"      [주의] DB 행 수 조회 실패 ({exc})")
    return row_counts


def create_tar_archive(
    source_paths: list[Path],
    output_archive: Path,
    base_dir: Path | None = None,
) -> tuple[int, str]:
    """여러 디렉토리나 파일을 단일 tar.gz 아카이브로 묶고 크기와 SHA256을 반환합니다."""
    base = base_dir or PROJECT_ROOT
    output_archive.parent.mkdir(parents=True, exist_ok=True)

    with tarfile.open(output_archive, "w:gz") as tar:
        for src in source_paths:
            if src.exists():
                arcname = str(src.relative_to(base)) if src.is_relative_to(base) else src.name
                tar.add(src, arcname=arcname)

    size_bytes = output_archive.stat().st_size
    sha256 = sha256_file(output_archive)
    return size_bytes, sha256


def dump_mysql_database(
    db_config: dict[str, Any],
    output_gz_path: Path,
) -> tuple[int, str]:
    """mysqldump 를 실행하여 압축된 SQL 덤프 파일을 생성합니다."""
    output_gz_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "mysqldump",
        "-h",
        str(db_config["host"]),
        "-P",
        str(db_config["port"]),
        "-u",
        str(db_config["user"]),
        "--single-transaction",
        "--routines",
        "--triggers",
        "--default-character-set=utf8mb4",
        str(db_config["name"]),
    ]

    env = os.environ.copy()
    if db_config["password"]:
        env["MYSQL_PWD"] = str(db_config["password"])

    proc = subprocess.Popen(  # nosec B603, B607
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )

    with gzip.open(output_gz_path, "wb") as gz_out:
        if proc.stdout:
            shutil.copyfileobj(proc.stdout, gz_out)

    _, stderr_data = proc.communicate()
    if proc.returncode != 0:
        err_msg = stderr_data.decode("utf-8", errors="replace") if stderr_data else "mysqldump 실패"
        raise RuntimeError(f"mysqldump 실행 실패 (코드 {proc.returncode}): {err_msg}")

    size_bytes = output_gz_path.stat().st_size
    sha256 = sha256_file(output_gz_path)
    return size_bytes, sha256


def restore_mysql_database(
    db_config: dict[str, Any],
    input_gz_path: Path,
) -> None:
    """압축된 SQL 덤프 파일을 MySQL 에 복원합니다."""
    if not input_gz_path.exists():
        raise FileNotFoundError(f"복원할 DB 덤프 파일 없음: {input_gz_path}")

    cmd = [
        "mysql",
        "-h",
        str(db_config["host"]),
        "-P",
        str(db_config["port"]),
        "-u",
        str(db_config["user"]),
        "--default-character-set=utf8mb4",
        str(db_config["name"]),
    ]

    env = os.environ.copy()
    if db_config["password"]:
        env["MYSQL_PWD"] = str(db_config["password"])

    with gzip.open(input_gz_path, "rb") as gz_in:
        proc = subprocess.Popen(  # nosec B603, B607
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
        _, stderr_data = proc.communicate(input=gz_in.read())

    if proc.returncode != 0:
        err_msg = (
            stderr_data.decode("utf-8", errors="replace") if stderr_data else "mysql 복원 실패"
        )
        raise RuntimeError(f"mysql 복원 실행 실패 (코드 {proc.returncode}): {err_msg}")


def extract_tar_archive(
    archive_path: Path,
    target_base_dir: Path,
) -> None:
    """tar.gz 아카이브를 대상 디렉토리에 안전하게 해제합니다."""
    if not archive_path.exists():
        raise FileNotFoundError(f"복원할 아카이브 없음: {archive_path}")

    target_base_dir.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive_path, "r:gz") as tar:
        # 안전한 압축 해제: 상위 경로 탈출 방지
        for member in tar.getmembers():
            member_path = (target_base_dir / member.name).resolve()
            if not str(member_path).startswith(str(target_base_dir.resolve())):
                raise ValueError(f"안전하지 않은 아카이브 경로 감지: {member.name}")
        if hasattr(tarfile, "data_filter"):
            tar.extractall(path=target_base_dir, filter="data")  # nosec B202
        else:
            tar.extractall(path=target_base_dir)  # noqa: S202 # nosec B202


def execute_backup(
    output_dir: Path | None = None,
    execute: bool = False,
    project_root: Path | None = None,
) -> dict[str, Any]:
    """운영 DB, ChromaDB, 서빙 모델을 단일 복구 단위로 백업합니다."""
    root = project_root or PROJECT_ROOT
    db_config = get_db_config()
    chroma_path = get_chroma_source_path(root)
    model_paths = get_model_source_paths(root)

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
        }

    print("-" * 60)
    target_dir.mkdir(parents=True, exist_ok=True)
    head_commit = get_head_commit_sha(root)
    print(f"[1/4] Git HEAD 커밋 확인: {head_commit}")

    # 1. DB 덤프
    print(f"[2/4] MySQL DB 덤프 생성 중... ({db_config['name']})")
    db_dump_file = target_dir / "db_dump.sql.gz"
    db_size, db_sha256 = dump_mysql_database(db_config, db_dump_file)
    row_counts = query_db_row_counts(db_config)
    print(
        f"      DB 덤프 완료: {db_dump_file.name} ({db_size:,} bytes, sha256: {db_sha256[:12]}...)"
    )

    # 2. ChromaDB 아카이브
    print(f"[3/4] ChromaDB 아카이브 생성 중... ({chroma_path.name})")
    chroma_dump_file = target_dir / "chroma_db.tar.gz"
    if chroma_path.exists():
        chroma_size, chroma_sha256 = create_tar_archive(
            [chroma_path], chroma_dump_file, base_dir=root
        )
    else:
        # 빈 더미 아카이브
        chroma_dump_file.touch()
        chroma_size, chroma_sha256 = 0, hashlib.sha256(b"").hexdigest()
    print(f"      ChromaDB 아카이브 완료: {chroma_dump_file.name} ({chroma_size:,} bytes)")

    # 3. 모델 아카이브
    print(f"[4/4] 모델 및 레지스트리 아카이브 생성 중... ({len(model_paths)}개 경로)")
    models_dump_file = target_dir / "models.tar.gz"
    if model_paths:
        models_size, models_sha256 = create_tar_archive(
            model_paths, models_dump_file, base_dir=root
        )
    else:
        models_dump_file.touch()
        models_size, models_sha256 = 0, hashlib.sha256(b"").hexdigest()
    print(f"      모델 아카이브 완료: {models_dump_file.name} ({models_size:,} bytes)")

    # 4. 매니페스트 작성
    manifest_data = {
        "schema": "BACKUP_MANIFEST_V1",
        "created_at": datetime.now(UTC).isoformat(),
        "head_commit": head_commit,
        "components": {
            "database": {
                "path": db_dump_file.name,
                "size_bytes": db_size,
                "sha256": db_sha256,
                "row_counts": row_counts,
            },
            "chroma_db": {
                "path": chroma_dump_file.name,
                "size_bytes": chroma_size,
                "sha256": chroma_sha256,
                "source_path": str(chroma_path.relative_to(root))
                if chroma_path.is_relative_to(root)
                else str(chroma_path),
            },
            "models": {
                "path": models_dump_file.name,
                "size_bytes": models_size,
                "sha256": models_sha256,
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


def verify_snapshot(snapshot_dir: Path) -> tuple[bool, list[str], dict[str, Any]]:
    """스냅샷 디렉토리의 매니페스트 및 체크섬 무결성을 검증합니다."""
    manifest_file = snapshot_dir / MANIFEST_FILENAME
    if not manifest_file.exists():
        return False, [f"매니페스트 파일 없음: {manifest_file}"], {}

    try:
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    except Exception as exc:
        return False, [f"매니페스트 파싱 실패: {exc}"], {}

    errors: list[str] = []
    components = manifest.get("components", {})

    for comp_name, comp_info in components.items():
        rel_path = comp_info.get("path")
        if not rel_path:
            errors.append(f"{comp_name}: 매니페스트 내 파일 경로 정의 누락")
            continue

        file_path = snapshot_dir / rel_path
        if not file_path.exists():
            errors.append(f"{comp_name}: 아카이브 파일 누락 ({file_path.name})")
            continue

        expected_size = comp_info.get("size_bytes")
        if expected_size is not None and file_path.stat().st_size != expected_size:
            errors.append(
                f"{comp_name}: 파일 크기 불일치 (기대 {expected_size:,} vs 실제 {file_path.stat().st_size:,})"
            )

        expected_sha = comp_info.get("sha256")
        if expected_sha:
            actual_sha = sha256_file(file_path)
            if actual_sha != expected_sha:
                errors.append(
                    f"{comp_name}: SHA256 체크섬 불일치 ({actual_sha[:12]} vs {expected_sha[:12]})"
                )

    is_valid = len(errors) == 0
    return is_valid, errors, manifest


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
    if chroma_dump_file.exists() and chroma_dump_file.stat().st_size > 0:
        extract_tar_archive(chroma_dump_file, target_base_dir=root)
    print("      ChromaDB 복원 완료")

    # 3.3 모델 아카이브 복원
    models_dump_file = snapshot_dir / components["models"]["path"]
    print(f"[3/3] 모델 및 레지스트리 복원 중... ({models_dump_file.name})")
    if models_dump_file.exists() and models_dump_file.stat().st_size > 0:
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


def list_snapshots(snapshots_dir: Path | None = None) -> list[dict[str, Any]]:
    """생성된 백업 스냅샷 목록을 조회하여 출력합니다."""
    dir_path = snapshots_dir or DEFAULT_SNAPSHOTS_DIR
    print("=" * 60)
    print(f"refac_bid_box 백업 스냅샷 목록 ({dir_path})")
    print("=" * 60)

    if not dir_path.exists():
        print("  등록된 백업 스냅샷이 없습니다.")
        return []

    snapshots = []
    for item in sorted(dir_path.iterdir(), reverse=True):
        if item.is_dir():
            manifest_file = item / MANIFEST_FILENAME
            if manifest_file.exists():
                is_valid, _, manifest = verify_snapshot(item)
                snapshots.append(
                    {
                        "dir": str(item),
                        "name": item.name,
                        "created_at": manifest.get("created_at", "unknown"),
                        "head_commit": manifest.get("head_commit", "unknown"),
                        "valid": is_valid,
                    }
                )

    if not snapshots:
        print("  유효한 백업 스냅샷이 없습니다.")
        return []

    for s in snapshots:
        valid_tag = "[정상]" if s["valid"] else "[무결성 오류]"
        print(f"  - {s['name']} {valid_tag}")
        print(f"      생성 시각: {s['created_at']}")
        print(f"      HEAD 커밋: {s['head_commit']}")
        print(f"      경로: {s['dir']}")

    return snapshots


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

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "backup":
        execute_backup(output_dir=args.output_dir, execute=args.execute)
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

    return 1


if __name__ == "__main__":
    sys.exit(main())

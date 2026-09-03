#!/usr/bin/env python3
"""
scripts/backup_recovery_core.py

scripts/backup_recovery.py 에서 분할된 핵심 유틸리티 함수 모음입니다.
해시/경로/DB 설정/아카이브 처리 등 백업과 복원에 공통으로 쓰이는 저수준 함수를
이 모듈에 모아 순환 import 없이 재사용합니다.
"""

from __future__ import annotations

import gzip
import hashlib
import os
import shutil
import subprocess  # nosec B404
import sys
import tarfile
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DEFAULT_SNAPSHOTS_DIR = PROJECT_ROOT / "data" / "backups" / "snapshots"
MANIFEST_FILENAME = "backup_manifest.json"

REQUIRED_BACKUP_ASSETS = ("database", "chroma_db", "models")
REQUIRED_SOURCE_ASSETS = ("chroma_db", "models")
REQUIRED_MODEL_SOURCE_PATH = Path("data") / "model_files"

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


class BackupAssetError(RuntimeError):
    """백업에 필요한 자산이 유효하지 않을 때 발생하는 오류입니다."""


def get_asset_state(path: Path) -> str:
    if not path.exists():
        return "missing"
    if path.is_file():
        return "available" if path.stat().st_size > 0 else "empty"
    return (
        "available"
        if any(p.is_file() and p.stat().st_size > 0 for p in path.rglob("*"))
        else "empty"
    )


def validate_backup_output(path: Path, asset_name: str) -> tuple[int, str]:
    if not path.is_file() or path.stat().st_size <= 0:
        raise BackupAssetError(f"필수 백업 자산 산출물이 비어 있습니다: {asset_name} ({path})")
    return path.stat().st_size, sha256_file(path)


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

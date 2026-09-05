#!/usr/bin/env python3
"""scripts/backup_recovery_core.py: 백업/복원 저수준 유틸리티 함수 모음."""

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
EXPECTED_MANIFEST_SCHEMA = "BACKUP_MANIFEST_V1"
DEFAULT_TABLES = tuple(
    "accounts_customuser automation_requests automation_subscriptions bid_announcements bid_dataset_summaries bid_results chat_session_states knowledge_base_status pipeline_executions prediction_results retrain_logs".split()  # noqa: SIM905
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
    try:
        res = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(project_root or PROJECT_ROOT),
            capture_output=True,
            text=True,
            check=False,
        )  # nosec B603, B607
        return res.stdout.strip() if res.returncode == 0 else "unknown"
    except Exception:
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
    return "******" if value else "<empty>"


def get_model_source_paths(project_root: Path | None = None) -> list[Path]:
    root = project_root or PROJECT_ROOT
    candidates = [
        root / "data" / "model_files",
        root / "data" / "model_backups",
        root / "data" / "model_metrics",
        root / "ml_registry",
    ]
    return [p for p in candidates if p.exists()]


def get_chroma_source_path(project_root: Path | None = None) -> Path:
    root = project_root or PROJECT_ROOT
    chroma_env = os.environ.get("CHROMA_DB_PATH")
    if chroma_env:
        candidate = Path(chroma_env)
        return candidate if candidate.is_absolute() else (root / candidate)
    return root / "chroma_db"


def query_db_row_counts(
    db_config: dict[str, Any], tables: tuple[str, ...] = DEFAULT_TABLES
) -> dict[str, int | None]:
    row_counts: dict[str, int | None] = {}
    try:
        from sqlalchemy import create_engine, text

        url = f"mysql+pymysql://{db_config['user']}:{db_config['password']}@{db_config['host']}:{db_config['port']}/{db_config['name']}"
        with create_engine(url, connect_args={"connect_timeout": 5}).connect() as conn:
            for tbl in tables:
                if tbl in DEFAULT_TABLES:
                    try:
                        query = text(f"SELECT COUNT(*) FROM `{tbl}`")  # noqa: S608 # nosec B608
                        val = conn.execute(query).scalar()
                        row_counts[tbl] = int(val) if val is not None else 0
                    except Exception:
                        row_counts[tbl] = None
    except Exception as exc:
        print(f"      [주의] DB 행 수 조회 실패 ({exc})")
        return {tbl: None for tbl in tables if tbl in DEFAULT_TABLES}
    return row_counts


def evaluate_row_counts(
    row_counts: dict[str, int | None], tables: tuple[str, ...] = DEFAULT_TABLES
) -> tuple[str, str]:
    """행 수 딕셔너리를 평가하여 상태('verified' | 'table_query_failed' | 'connection_failed')와 사유를 반환합니다."""
    if not row_counts or (all(v is None for v in row_counts.values()) and len(row_counts) > 0):
        return "connection_failed", "DB 접속 또는 전체 행 수 조회 실패"
    if any(v is None for v in row_counts.values()):
        failed = [t for t, v in row_counts.items() if v is None]
        return "table_query_failed", f"일부 테이블 행 수 조회 실패: {', '.join(failed)}"
    return "verified", "모든 대상 테이블 행 수 정상 확인"


def create_tar_archive(
    source_paths: list[Path], output_archive: Path, base_dir: Path | None = None
) -> tuple[int, str]:
    base = base_dir or PROJECT_ROOT
    output_archive.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(output_archive, "w:gz") as tar:
        for src in source_paths:
            if src.exists():
                arcname = str(src.relative_to(base)) if src.is_relative_to(base) else src.name
                tar.add(src, arcname=arcname)
    return output_archive.stat().st_size, sha256_file(output_archive)


def mysql_client_command(
    binary: str, db_config: dict[str, Any]
) -> tuple[list[str], dict[str, str]]:
    """mysql 계열 클라이언트 실행 명령과 환경변수를 만듭니다.

    2026-09-03 실측: 호스트의 mysqldump 26.7 에는 mysql_native_password 플러그인이
    없습니다. 이 저장소의 compose 는 서버를 그 플러그인으로 띄우므로 호스트에서
    백업하면 'Authentication plugin cannot be loaded' 로 실패합니다. 이 구성에서는
    호스트 클라이언트로 백업할 수 없습니다.

    MYSQL_CLIENT_CONTAINER 를 지정하면 그 컨테이너 안의 클라이언트를 씁니다.
    DB 가 컨테이너에 있는 배포에서는 이것이 실제 경로입니다. 지정하지 않으면
    지금까지처럼 호스트 클라이언트를 씁니다.
    """
    container = os.environ.get("MYSQL_CLIENT_CONTAINER", "").strip()
    args = [
        binary,
        "-h",
        "127.0.0.1" if container else str(db_config["host"]),
        "-P",
        "3306" if container else str(db_config["port"]),
        "-u",
        str(db_config["user"]),
        # host 가 localhost 면 mysql 클라이언트는 포트를 무시하고 유닉스 소켓으로
        # 붙습니다. 포트를 지정한 이상 TCP 를 쓰는 것이 의도입니다.
        "--protocol=TCP",
    ]
    env = os.environ.copy()
    password = str(db_config.get("password") or "")
    if container:
        prefix = ["docker", "exec", "-i"]
        if password:
            prefix += ["-e", f"MYSQL_PWD={password}"]
        return [*prefix, container, *args], env
    if password:
        env["MYSQL_PWD"] = password
    return args, env


def dump_mysql_database(db_config: dict[str, Any], output_gz_path: Path) -> tuple[int, str]:
    output_gz_path.parent.mkdir(parents=True, exist_ok=True)
    cmd, env = mysql_client_command("mysqldump", db_config)
    cmd += [
        "--single-transaction",
        "--routines",
        "--triggers",
        "--default-character-set=utf8mb4",
        str(db_config["name"]),
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)  # nosec B603, B607
    with gzip.open(output_gz_path, "wb") as gz_out:
        if proc.stdout:
            shutil.copyfileobj(proc.stdout, gz_out)
    _, stderr_data = proc.communicate()
    if proc.returncode != 0:
        err = stderr_data.decode("utf-8", errors="replace") if stderr_data else "mysqldump 실패"
        raise RuntimeError(f"mysqldump 실행 실패 (코드 {proc.returncode}): {err}")
    return output_gz_path.stat().st_size, sha256_file(output_gz_path)


def restore_mysql_database(db_config: dict[str, Any], input_gz_path: Path) -> None:
    if not input_gz_path.exists():
        raise FileNotFoundError(f"복원할 DB 덤프 파일 없음: {input_gz_path}")
    cmd, env = mysql_client_command("mysql", db_config)
    cmd += [
        "--default-character-set=utf8mb4",
        str(db_config["name"]),
    ]
    with gzip.open(input_gz_path, "rb") as gz_in:
        proc = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env
        )  # nosec B603, B607
        _, stderr_data = proc.communicate(input=gz_in.read())
    if proc.returncode != 0:
        err = stderr_data.decode("utf-8", errors="replace") if stderr_data else "mysql 복원 실패"
        raise RuntimeError(f"mysql 복원 실행 실패 (코드 {proc.returncode}): {err}")


def extract_tar_archive(archive_path: Path, target_base_dir: Path) -> None:
    if not archive_path.exists():
        raise FileNotFoundError(f"복원할 아카이브 없음: {archive_path}")
    target_base_dir.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive_path, "r:gz") as tar:
        for member in tar.getmembers():
            member_path = (target_base_dir / member.name).resolve()
            if not str(member_path).startswith(str(target_base_dir.resolve())):
                raise ValueError(f"안전하지 않은 아카이브 경로 감지: {member.name}")
        if hasattr(tarfile, "data_filter"):
            tar.extractall(path=target_base_dir, filter="data")  # nosec B202
        else:
            tar.extractall(path=target_base_dir)  # noqa: S202 # nosec B202


def _run_mysql_cmd(db_config: dict[str, Any], sql: str, err_prefix: str) -> None:
    cmd = [
        "mysql",
        "-h",
        str(db_config["host"]),
        "-P",
        str(db_config["port"]),
        # host 가 localhost 면 mysql 클라이언트는 포트를 무시하고 유닉스 소켓으로
        # 붙습니다. DB 가 컨테이너에 있으면 그 소켓이 없어 백업과 복원이 모두
        # 실패합니다. 포트를 지정한 이상 TCP 를 쓰는 것이 의도입니다.
        "--protocol=TCP",
        "-u",
        str(db_config["user"]),
        "-e",
        sql,
    ]

    env = os.environ.copy()
    if db_config.get("password"):
        env["MYSQL_PWD"] = str(db_config["password"])
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env, check=False)  # nosec B603, B607
    if proc.returncode != 0:
        err = proc.stderr.strip() if proc.stderr else "실패"
        raise RuntimeError(f"{err_prefix} (코드 {proc.returncode}): {err}")


def create_mysql_database(db_config: dict[str, Any]) -> None:
    """MySQL 에 대상 데이터베이스를 생성합니다."""
    name = db_config.get("name")
    if not name:
        raise ValueError("생성할 DB 이름이 지정되지 않았습니다.")
    _run_mysql_cmd(
        db_config,
        f"CREATE DATABASE IF NOT EXISTS `{name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci",
        "MySQL DB 생성 실패",
    )


def drop_mysql_database(
    db_config: dict[str, Any], prod_config: dict[str, Any] | None = None
) -> None:
    """MySQL 에서 대상 데이터베이스를 삭제합니다 (운영 DB 절대 삭제 방지 가드 내장)."""
    name = str(db_config.get("name", "")).strip()
    if not name:
        raise ValueError("삭제할 DB 이름이 지정되지 않았습니다.")
    prod = prod_config or get_db_config()
    prod_name = str(prod.get("name", "")).strip()
    if name == prod_name or (
        str(db_config.get("host")) == str(prod.get("host"))
        and int(db_config.get("port", 3306)) == int(prod.get("port", 3306))
        and name == prod_name
    ):
        raise ValueError(f"운영 DB({name})는 삭제할 수 없습니다.")
    _run_mysql_cmd(db_config, f"DROP DATABASE IF EXISTS `{name}`", "MySQL DB 삭제 실패")


def cleanup_drill_target_dir(target_dir: Path, project_root: Path | None = None) -> None:
    """복원 리허설용 격리 대상 디렉토리를 안전하게 삭제 정리합니다."""
    raw = str(target_dir).strip()
    if not raw or raw in (".", "./", "..", "../", "/"):
        raise ValueError(f"격리되지 않은 비정상 경로에 대한 정리 요청은 거부됩니다: '{target_dir}'")
    target, real_root, cwd = target_dir.resolve(), PROJECT_ROOT.resolve(), Path.cwd().resolve()
    if target == target.parent or len(target.parts) <= 1:
        raise ValueError(f"루트 파일시스템 경로는 정리할 수 없습니다: {target}")
    for root in (real_root, cwd, project_root.resolve() if project_root else None):
        if root and (target == root or root in target.parents or target in root.parents):
            raise ValueError(f"격리되지 않은 경로는 정리할 수 없습니다: {target}")
    if target.is_dir():
        shutil.rmtree(target, ignore_errors=True)

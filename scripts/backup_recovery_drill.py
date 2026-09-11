#!/usr/bin/env python3
"""복원 리허설(restore drill) 전용 헬퍼."""

from __future__ import annotations

import json
import os
import subprocess  # nosec B404
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from scripts.backup_recovery_core import PROJECT_ROOT, mysql_client_command  # noqa: E402

DRILL_REDO_LOG_CAPACITY_BYTES = 8_589_934_592


def run_drill_g1_verification(
    target_dir: Path,
    drill_db_config: dict[str, Any],
    report_path: Path | None = None,
    project_root: Path | None = None,
    only_steps: str | None = None,
) -> tuple[bool, str, dict[str, Any]]:
    root = project_root or PROJECT_ROOT
    script = root / "scripts" / "verify_migration.py"
    if not script.exists():
        return False, f"검증 스크립트 없음: {script}", {}
    rep = report_path or (target_dir / "drill_g1_verification_report.json")
    env = {
        **os.environ,
        "DB_NAME": str(drill_db_config["name"]),
        "DB_HOST": str(drill_db_config["host"]),
        "DB_PORT": str(drill_db_config["port"]),
        "DB_USER": str(drill_db_config["user"]),
        "DATA_ASSET_ROOT": str(target_dir),
        "CHROMA_DB_PATH": str(target_dir / "chroma_db"),
        "MODEL_FILES_DIR": str(target_dir / "data" / "model_files"),
        "MODEL_BACKUPS_DIR": str(target_dir / "data" / "model_backups"),
    }
    env.setdefault(
        "CHROMA_SOURCE_BACKUP_PATH",
        str(root / "data" / "backups" / "chroma_source"),
    )
    if drill_db_config.get("password"):
        env["DB_PASSWORD"] = str(drill_db_config["password"])
    cmd = [sys.executable, str(script), "--report-path", str(rep)]
    if only_steps:
        cmd.extend(["--only-steps", only_steps])
    proc = subprocess.run(
        cmd,
        cwd=str(root),
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )  # nosec B603, B607
    try:
        rep_data = json.loads(rep.read_text(encoding="utf-8")) if rep.exists() else {}
    except Exception:
        rep_data = {}
    return (
        proc.returncode == 0,
        (
            "G1 무손실 검증 통과"
            if proc.returncode == 0
            else (proc.stderr or proc.stdout or "G1 검증 실패").strip()
        ),
        rep_data,
    )


def measure_rpo(manifest: dict[str, Any], st: datetime) -> dict[str, Any]:
    w, c = manifest.get("consistency_window", {}), manifest.get("created_at")

    def _diff(s: str | None) -> float | None:
        return (st - datetime.fromisoformat(s)).total_seconds() if s else None

    return {
        "snapshot_created_at": c,
        "consistency_window": w,
        "drill_started_at": st.isoformat(),
        "created_at_to_drill_start_seconds": _diff(c),
        "db_dump_finished_to_drill_start_seconds": _diff(w.get("db_dump_finished_at")),
        "file_assets_to_drill_start_seconds": _diff(w.get("file_assets_collected_at")),
    }


def record_timing(
    timings: dict[str, Any],
    name: str,
    start: datetime,
    end: datetime,
    status: str,
    err: Exception | None = None,
) -> None:
    timings[name] = {
        "started_at": start.isoformat(),
        "finished_at": end.isoformat(),
        "duration_seconds": (end - start).total_seconds(),
        "status": status,
        **({"error": str(err)} if err else {}),
    }


def mysql_exec(db_config: dict[str, Any], sql: str) -> str:
    cmd, env = mysql_client_command("mysql", db_config)
    cmd += ["-N", "-e", sql]
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env, check=False)  # nosec B603
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "실패").strip()
        raise RuntimeError(f"MySQL 실행 실패 (코드 {proc.returncode}): {err}")
    return proc.stdout.strip()


def combine_staged_g1(
    file_part: dict[str, Any],
    db_part: dict[str, Any],
) -> dict[str, Any]:
    """파일 단계와 DB 단계 G1 결과를 하나의 리포트 필드로 합칩니다."""
    file_ok = bool(file_part.get("success"))
    db_ok = bool(db_part.get("success"))
    messages = [
        part.get("message")
        for part in (file_part, db_part)
        if isinstance(part.get("message"), str) and part.get("message")
    ]
    if file_ok and db_ok:
        message = "G1 무손실 검증 통과 (파일·DB 단계 분리)"
    elif messages:
        message = " / ".join(messages)
    else:
        message = "G1 무손실 검증을 실행하지 않음"
    return {
        "success": file_ok and db_ok,
        "message": message,
        "file": file_part,
        "database": db_part,
    }

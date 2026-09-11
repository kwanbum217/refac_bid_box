"""복원 드릴 정례화 신선도 판정 및 점검 서비스 (단일 원천).

분기 1회 복구 드릴(Restore Drill)의 정례화 이행 여부를 기계적으로 강제하고 신선도를 점검한다.
드릴 보고서 목록을 읽어 가장 최근 성공한 복원 드릴로부터 경과일을 계산하고 신선도를 판정한다.

읽기 전용 보장:
- backup_recovery.py 의 drill 이나 restore(복원) 등 어떤 쓰기/복원 명령도 절대 호출하거나 실행하지 않는다.
- 오직 저장된 드릴 보고서(restore_drill_report_*.json) 파일의 메타데이터만 읽는다.
- 감지만 자동화하고 실제 복원 드릴의 승인 및 실행은 운영자/사람에게 남긴다.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

STATUS_OK = "OK"
STATUS_OVERDUE = "OVERDUE"
STATUS_UNDECIDABLE = "UNDECIDABLE"

EXIT_OK = 0
EXIT_OVERDUE = 1
EXIT_UNDECIDABLE = 2
EXIT_ERROR = 3

DEFAULT_CADENCE_DAYS = 90.0
DEFAULT_WARN_THRESHOLD_DAYS = 80.0

DEFAULT_REPORTS_DIR = Path("data/backups")
DEFAULT_REPORT_GLOB = "restore_drill_report_*.json"

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def parse_drill_timestamp(value: Any) -> datetime | None:
    """ISO 8601 문자열 또는 datetime 객체를 UTC timezone-aware datetime 으로 변환한다."""
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
    if isinstance(value, str):
        cleaned = value.strip()
        if not cleaned:
            return None
        # ISO 형식 끝의 Z 지원
        if cleaned.endswith("Z"):
            cleaned = cleaned[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(cleaned)
            if dt.tzinfo is None:
                return dt.replace(tzinfo=UTC)
            return dt.astimezone(UTC)
        except (ValueError, TypeError):
            return None
    return None


def extract_report_timestamp(report: dict[str, Any]) -> datetime | None:
    """드릴 보고서에서 실행 시각을 추출한다.

    1순위: 최상위 started_at
    2순위: 구 보고서 하위 호환을 위한 g1_verification.file.report.generated_at 중첩 시각
    주의: 파일명이나 파일 mtime 은 git 체크아웃 등으로 왜곡되므로 절대 사용하지 않는다.
    """
    if not isinstance(report, dict):
        return None

    # 1순위: started_at
    raw_started = report.get("started_at")
    dt = parse_drill_timestamp(raw_started)
    if dt is not None:
        return dt

    # 2순위: g1_verification.file.report.generated_at (하위 호환)
    g1 = report.get("g1_verification")
    if isinstance(g1, dict):
        file_part = g1.get("file")
        if isinstance(file_part, dict):
            file_rep = file_part.get("report")
            if isinstance(file_rep, dict):
                gen_at = file_rep.get("generated_at")
                dt = parse_drill_timestamp(gen_at)
                if dt is not None:
                    return dt

    return None


def compute_drill_elapsed_days(last_drill_at: datetime, now: datetime) -> float:
    """마지막 드릴 실행 시각으로부터 현재 시각까지의 경과일(일 단위)을 계산한다."""
    return (now - last_drill_at).total_seconds() / 86400.0


def evaluate_drill_freshness(
    latest_drill_at: datetime | None,
    now: datetime,
    warn_threshold_days: float = DEFAULT_WARN_THRESHOLD_DAYS,
    cadence_days: float = DEFAULT_CADENCE_DAYS,
    report_path: Path | str | None = None,
    total_candidates: int = 0,
    successful_candidates: int = 0,
) -> dict[str, Any]:
    """경과 시각과 임계값을 바탕으로 세 갈래 신선도(OK, OVERDUE, UNDECIDABLE)를 순수 판정한다."""
    now_utc = now if now.tzinfo is not None else now.replace(tzinfo=UTC)

    if latest_drill_at is None:
        if successful_candidates == 0:
            if total_candidates == 0:
                reason = "복원 드릴 보고서가 존재하지 않습니다."
            else:
                reason = "성공(success: true)한 복원 드릴 보고서가 존재하지 않습니다."
        else:
            reason = "성공한 드릴 보고서에서 유효한 실행 시각(started_at 또는 generated_at)을 판독할 수 없습니다."

        return {
            "status": STATUS_UNDECIDABLE,
            "is_overdue": False,
            "is_undecidable": True,
            "last_drill_at": None,
            "report_path": str(report_path) if report_path else None,
            "elapsed_days": None,
            "warn_threshold_days": warn_threshold_days,
            "cadence_days": cadence_days,
            "reason": reason,
            "checked_at": now_utc.isoformat(),
            "total_candidates": total_candidates,
            "successful_candidates": successful_candidates,
            "exit_code": EXIT_UNDECIDABLE,
        }

    latest_utc = (
        latest_drill_at
        if latest_drill_at.tzinfo is not None
        else latest_drill_at.replace(tzinfo=UTC)
    )
    elapsed_days = compute_drill_elapsed_days(latest_utc, now_utc)

    if elapsed_days <= warn_threshold_days:
        status = STATUS_OK
        reason = (
            f"마지막 성공 복원 드릴로부터 {elapsed_days:.1f}일 경과하여 "
            f"경고 임계({warn_threshold_days:.1f}일, 정례 주기 {cadence_days:.1f}일) 이내입니다."
        )
        is_overdue = False
        exit_code = EXIT_OK
    else:
        status = STATUS_OVERDUE
        reason = (
            f"마지막 성공 복원 드릴로부터 {elapsed_days:.1f}일 경과하여 "
            f"경고 임계({warn_threshold_days:.1f}일, 정례 주기 {cadence_days:.1f}일)를 초과했습니다."
        )
        is_overdue = True
        exit_code = EXIT_OVERDUE

    return {
        "status": status,
        "is_overdue": is_overdue,
        "is_undecidable": False,
        "last_drill_at": latest_utc.isoformat(),
        "report_path": str(report_path) if report_path else None,
        "elapsed_days": elapsed_days,
        "warn_threshold_days": warn_threshold_days,
        "cadence_days": cadence_days,
        "reason": reason,
        "checked_at": now_utc.isoformat(),
        "total_candidates": total_candidates,
        "successful_candidates": successful_candidates,
        "exit_code": exit_code,
    }


def find_latest_successful_drill(
    reports_dir: Path | str = DEFAULT_REPORTS_DIR,
    pattern: str = DEFAULT_REPORT_GLOB,
) -> tuple[datetime | None, Path | None, int, int]:
    """지정된 디렉터리의 보고서 파일 중 success 가 참인 보고서만 골라 가장 최근 실행 시각을 찾는다.

    반환값: (최신 실행 시각, 해당 보고서 경로, 전체 보고서 수, 성공 보고서 수)
    """
    target_dir = Path(reports_dir)
    if not target_dir.is_absolute():
        candidate_root = PROJECT_ROOT / target_dir
        target_dir = candidate_root if candidate_root.exists() else Path.cwd() / target_dir

    if not target_dir.exists() or not target_dir.is_dir():
        return None, None, 0, 0

    files = sorted(target_dir.glob(pattern))
    total_candidates = len(files)
    successful_candidates = 0

    latest_dt: datetime | None = None
    latest_path: Path | None = None

    for fpath in files:
        try:
            content = fpath.read_text(encoding="utf-8")
            data = json.loads(content)
        except Exception as exc:
            logger.warning("드릴 보고서 파일 읽기 실패 (%s): %s", fpath, exc)
            continue

        if not isinstance(data, dict):
            continue

        # success 가 True 인 성공 보고서만 후보로 삼는다
        if data.get("success") is not True:
            continue

        successful_candidates += 1
        dt = extract_report_timestamp(data)
        if dt is None:
            continue

        if latest_dt is None or dt > latest_dt:
            latest_dt = dt
            latest_path = fpath

    return latest_dt, latest_path, total_candidates, successful_candidates


def check_restore_drill_freshness(
    reports_dir: Path | str | None = None,
    now: datetime | None = None,
    warn_threshold_days: float = DEFAULT_WARN_THRESHOLD_DAYS,
    cadence_days: float = DEFAULT_CADENCE_DAYS,
) -> dict[str, Any]:
    """복원 드릴 신선도를 읽기 전용으로 점검한다.

    어떤 드릴/복원 명령도 실행하지 않으며, 오직 보고서 메타데이터를 읽어 판정한다.
    """
    check_now = now or datetime.now(UTC)
    dir_to_check = reports_dir if reports_dir is not None else DEFAULT_REPORTS_DIR

    latest_dt, latest_path, total_count, succ_count = find_latest_successful_drill(
        reports_dir=dir_to_check
    )

    return evaluate_drill_freshness(
        latest_drill_at=latest_dt,
        now=check_now,
        warn_threshold_days=warn_threshold_days,
        cadence_days=cadence_days,
        report_path=latest_path,
        total_candidates=total_count,
        successful_candidates=succ_count,
    )


__all__ = [
    "DEFAULT_CADENCE_DAYS",
    "DEFAULT_REPORTS_DIR",
    "DEFAULT_REPORT_GLOB",
    "DEFAULT_WARN_THRESHOLD_DAYS",
    "EXIT_ERROR",
    "EXIT_OK",
    "EXIT_OVERDUE",
    "EXIT_UNDECIDABLE",
    "STATUS_OK",
    "STATUS_OVERDUE",
    "STATUS_UNDECIDABLE",
    "check_restore_drill_freshness",
    "compute_drill_elapsed_days",
    "evaluate_drill_freshness",
    "extract_report_timestamp",
    "find_latest_successful_drill",
    "parse_drill_timestamp",
]

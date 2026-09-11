"""분기 복구 드릴 및 런북 문서 정합성 기계 고정 테스트.

런북(backup_recovery_runbook.md)의 RPO/RTO 확정값 반영 및 공란 표지 부재,
절차서(restore_drill_procedure_20260911.md)의 CLI 인자 완전성, 합격 기준(시간, 행 수, 스키마 대조),
격리 안전 가드 및 실패 판정 기록 위치를 기계적으로 검증합니다.
"""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RUNBOOK_PATH = PROJECT_ROOT / "docs" / "ops" / "backup_recovery_runbook.md"
PROCEDURE_PATH = PROJECT_ROOT / "docs" / "ops" / "restore_drill_procedure_20260911.md"


def test_runbook_rpo_rto_finalized() -> None:
    """런북에 RPO/RTO 확정값과 근거가 기재되어 있고 공란 표지가 없어야 합니다."""
    assert RUNBOOK_PATH.exists(), f"런북 파일 부재: {RUNBOOK_PATH}"
    content = RUNBOOK_PATH.read_text(encoding="utf-8")

    # 1. 확정값 및 확정일 검증
    assert "24시간" in content, "RPO 24시간 확정값이 런북에 명시되어야 합니다."
    assert "4시간" in content, "RTO 4시간 확정값이 런북에 명시되어야 합니다."
    assert "2026-09-06" in content, "RPO/RTO 확정일(2026-09-06)이 명시되어야 합니다."
    assert "docs/context/CURRENT_STATE.md" in content, "CURRENT_STATE.md 근거 링크가 있어야 합니다."

    # 2. 미확정 및 공란 표지 부재 검증
    forbidden_markers = [
        "기입 필요",
        "운영 담당자가 결정하여 기입",
        "인위적인 수치를 단정하지 않으며",
        "공란으로 둡니다",
        "목표값이 미확정",
    ]
    for marker in forbidden_markers:
        assert marker not in content, f"런북에 미확정/공란 표지가 남아 있습니다: '{marker}'"


def test_drill_procedure_cli_arguments() -> None:
    """절차서에 backup_recovery.py drill 서브커맨드의 필수 및 선택 인자가 모두 명시되어야 합니다."""
    assert PROCEDURE_PATH.exists(), f"절차서 파일 부재: {PROCEDURE_PATH}"
    content = PROCEDURE_PATH.read_text(encoding="utf-8")

    # 1. 서브커맨드 및 필수 인자
    assert "drill" in content, "drill 서브커맨드가 명시되어야 합니다."
    assert "--snapshot-dir" in content, "필수 인자 --snapshot-dir 가 명시되어야 합니다."
    assert "--target-dir" in content, "필수 인자 --target-dir 가 명시되어야 합니다."

    # 2. 선택 인자
    assert "--report-path" in content, "선택 인자 --report-path 가 명시되어야 합니다."
    assert "--db-name" in content, "선택 인자 --db-name 이 명시되어야 합니다."
    assert "--keep-artifacts" in content, "선택 인자 --keep-artifacts 가 명시되어야 합니다."


def test_drill_procedure_pass_criteria_comprehensive() -> None:
    """합격 기준에 단순 시간뿐 아니라 행 수 대조와 스키마 대조가 명시되어야 합니다."""
    assert PROCEDURE_PATH.exists(), f"절차서 파일 부재: {PROCEDURE_PATH}"
    content = PROCEDURE_PATH.read_text(encoding="utf-8")

    # 1. 시간 기준 (RTO 4시간)
    assert "4시간" in content, "RTO 4시간 기준이 명시되어야 합니다."
    assert "total_duration_seconds" in content, "총 소요 시간 실측 지표가 명시되어야 합니다."

    # 2. 데이터 무손실: 행 수 대조 및 스키마 대조
    assert "행 수" in content, "합격 기준에 행 수 대조가 명시되어야 합니다."
    assert "스키마" in content, "합격 기준에 스키마 대조가 명시되어야 합니다."
    assert "verify_migration.py" in content, (
        "무손실 검증 도구(verify_migration.py)가 명시되어야 합니다."
    )
    assert "g1_verification" in content, "G1 무손실 검증 항목이 명시되어야 합니다."


def test_drill_procedure_isolation_and_safety_guards() -> None:
    """운영 DB 및 운영 파일 미영향 근거(격리 안전 가드)가 명시되어야 합니다."""
    assert PROCEDURE_PATH.exists(), f"절차서 파일 부재: {PROCEDURE_PATH}"
    content = PROCEDURE_PATH.read_text(encoding="utf-8")

    # DB 격리 가드
    assert "restore_drill" in content, "격리 DB 명칭 규칙이 명시되어야 합니다."
    assert "drop_mysql_database" in content, "DB 삭제 안전 가드 함수가 명시되어야 합니다."

    # 경로 격리 가드
    assert "cleanup_drill_target_dir" in content, "경로 정리 안전 가드 함수가 명시되어야 합니다."


def test_drill_procedure_failure_handling_and_reporting() -> None:
    """실패 판정 조건과 결과 기록 위치(JSON 리포트)가 명시되어야 합니다."""
    assert PROCEDURE_PATH.exists(), f"절차서 파일 부재: {PROCEDURE_PATH}"
    content = PROCEDURE_PATH.read_text(encoding="utf-8")

    assert "RESTORE_DRILL_REPORT_V2" in content, "리포트 스키마 버전이 명시되어야 합니다."
    assert "report-path" in content, "리포트 저장 위치 인자가 명시되어야 합니다."
    assert "errors" in content, "에러 기록 필드가 명시되어야 합니다."


def test_no_emojis_in_docs() -> None:
    """작성 및 수정한 문서에 규칙상 금지된 이모지가 포함되지 않아야 합니다."""
    from scripts.validate_commit_message import contains_emoji

    for path in (RUNBOOK_PATH, PROCEDURE_PATH):
        content = path.read_text(encoding="utf-8")
        assert not contains_emoji(content), f"{path.name} 파일에 이모지가 발견되었습니다."

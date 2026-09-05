# Task task_3e6c7d5bf5c1: 백업 스냅샷 검증기 필수 자산 및 검증 필드 강제화 (R-01)

> **작성일**: 2026-09-05
> **태스크 ID**: task_3e6c7d5bf5c1
> **상태**: 완료 (succeeded)
> **역할**: 빌더 (builder)

---

## 1. 개요 및 배경

2026-09-05 외부 진단 보고서 R-01에 따라, 백업 스냅샷 검증기(`verify_snapshot`) 및 복원 사전 점검(`execute_restore`)의 결함을 해결했습니다.

기존 구현의 취약점:
1. `scripts/backup_snapshots.py`의 `verify_snapshot`은 매니페스트 내 `components` 항목만 순회하므로, 빈 매니페스트(`{}`) 또는 빈 컴포넌트(`{"components": {}}`)인 경우 에러 0건으로 `is_valid=True`를 반환했습니다.
2. `size_bytes`와 `sha256` 필드가 선택적으로 처리되어, 필드가 누락되더라도 검사가 생략되고 성공 판정이 났습니다.
3. 매니페스트 및 컴포넌트의 자료형(dict, int 등)을 엄격하게 검증하지 않았습니다.
4. `scripts/backup_recovery.py`의 복원 사전 점검(`execute_restore`)에서 `recovery_trusted is False`만 확인하여, `recovery_trusted` 키가 아예 없는 매니페스트를 차단하지 못했습니다.

이로 인해 잘못된 백업 스냅샷이 유효한 것으로 오인되어 복구 불가를 복구 가능으로 판단할 위험이 있었습니다.

---

## 2. 주요 변경 사항

### 2.1 스키마 상수 정의 (`scripts/backup_recovery_core.py`)
- `EXPECTED_MANIFEST_SCHEMA = "BACKUP_MANIFEST_V1"` 상수를 정의하여 매니페스트 스키마의 단일 진실 원천을 수립했습니다.
- 기존의 `REQUIRED_BACKUP_ASSETS = ("database", "chroma_db", "models")` 상수를 정본으로 재사용하도록 구조를 정돈했습니다.

### 2.2 스냅샷 무결성 검증 엄격화 (`scripts/backup_snapshots.py`)
- `verify_snapshot`이 컴포넌트 순회 전에 최상위 구조를 엄격히 검증하도록 수정했습니다:
  - 매니페스트 최상위 dict 타입 검증
  - `schema` 식별자가 `EXPECTED_MANIFEST_SCHEMA`와 일치하는지 검증
  - `components`가 dict 타입인지 검증
  - `REQUIRED_BACKUP_ASSETS`의 모든 필수 자산(`database`, `chroma_db`, `models`)이 `components`에 빠짐없이 존재하는지 검증
- 각 컴포넌트 정보에 대해:
  - 컴포넌트 정보 dict 타입 검증
  - `path` 필드의 비어있지 않은 문자열 여부 및 아카이브 파일 실제 존재 여부 검증
  - `size_bytes` 필드가 정수형(boolean 제외)이고 양수(> 0)인지 검증 및 실제 파일 크기와의 일치 여부 검증
  - `sha256` 필드가 유효한 64자 16진수 문자열인지 검증 및 실제 파일의 SHA256 체크섬과의 일치 여부 검증
- 필수 필드 누락 시 검사 생략이 아닌 명확한 검증 실패(`is_valid=False`)로 처리했습니다.

### 2.3 복원 사전 점검 및 리허설 신뢰성 강제 (`scripts/backup_recovery.py`)
- 매니페스트 생성 시 `EXPECTED_MANIFEST_SCHEMA` 상수를 사용하도록 통일했습니다.
- `execute_restore` 및 `run_restore_drill`에서 `recovery_trusted` 검사를 `is not True`로 변경하여, 키가 누락되었거나 `False`인 경우 복원을 엄격하게 차단하도록 수정했습니다.
- `EXPECTED_MANIFEST_SCHEMA`를 re-export 목록(`__all__`)에 추가했습니다.

### 2.4 단위 및 회귀 테스트 보강
- `tests/test_backup_recovery.py`:
  - `test_verify_snapshot_tampered_fails`, `test_restore_dry_run_default_does_not_modify`, `test_restore_without_confirm_in_non_interactive_aborts`, `test_restore_execute_with_confirm` 테스트 픽스처를 전체 필수 자산과 `recovery_trusted: True`를 갖춘 완전한 정상 스냅샷으로 업데이트했습니다.
  - `test_restore_dry_run_incomplete_manifest_fails`를 추가하여 불완전한 매니페스트로 dry-run 복원 시도시 실패함을 보증했습니다.
- `tests/test_backup_fail_closed.py`:
  - 빈 매니페스트 실패 (`test_verify_snapshot_empty_manifest_fails`)
  - 빈 components 실패 (`test_verify_snapshot_empty_components_fails`)
  - 필수 자산 1개 누락 실패 (`test_verify_snapshot_missing_one_asset_fails`)
  - sha256 누락 실패 (`test_verify_snapshot_missing_sha256_fails`)
  - size_bytes 0 실패 (`test_verify_snapshot_zero_size_fails`)
  - size_bytes 문자열 타입 오류 실패 (`test_verify_snapshot_string_size_fails`)
  - components 리스트 타입 오류 실패 (`test_verify_snapshot_components_as_list_fails`)
  - recovery_trusted 키 부재 복원 거부 (`test_restore_rejects_missing_recovery_trusted_key`)
  - 정상 백업 형태 검증 및 복원 사전 점검 통과 고정 (`test_verify_snapshot_valid_manifest_passes`)
- `tests/test_backup_recovery_split.py`:
  - `EXPECTED_MANIFEST_SCHEMA` re-export 심볼 검증 추가
  - 줄 수 상한(cap) 실측값(160줄) 반영 (cap: 170)
- `tests/test_backup_schedule.py`:
  - 빈 매니페스트 스냅샷 대상 `run_restore_drill` 수행 시 `snapshot_valid=False` 처리 검증 추가 (`test_restore_drill_rejects_empty_manifest_snapshot`)

---

## 3. 검증 결과

| 검증 항목 | 명령 | 결과 |
| --- | --- | --- |
| 백업 모듈 단위/회귀 테스트 | `uv run pytest tests/test_backup_recovery.py tests/test_backup_fail_closed.py tests/test_backup_recovery_split.py tests/test_backup_schedule.py -q` | 42 passed |
| 정적 타입 검사 | `uv run mypy src` | 0 errors (93 source files) |
| 에이전트 규칙 검증 | `python3 scripts/validate_agent_rules.py --quiet` | 20/20 PASS |

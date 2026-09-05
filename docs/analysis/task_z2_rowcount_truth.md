# R-09 백업 행 수 조회 실패와 실제 0행 구분 및 검증 정책 보고서

> **작성일**: 2026-09-05
> **Task ID**: task_943261d27926
> **상태**: 완료 (Implementation Verified)
> **관련 사양**: `.orca/capsules/task_z2_rowcount_truth/capsule.yaml`

---

## 1. 개요 및 배경

2026-09-05 외부 진단 보고서 R-09에 따르면, 기존 `scripts/backup_recovery_core.py`의 `query_db_row_counts` 함수는 테이블별 쿼리 실패 시 예외를 잡아 `row_counts[tbl] = 0`으로 기록하고, 전체 DB 연결 실패 시 빈 딕셔너리(`{}`)를 반환했습니다.
이로 인해 다음과 같은 심각한 정합성 결함이 존재했습니다:

1. **조회 실패와 실제 0행의 혼동**: 테이블이 비어 있는 실제 0행과, 쿼리 실패/테이블 부재/권한 오류 등으로 조회하지 못한 상태가 모두 `0`으로 기록되어 구별되지 않았습니다.
2. **연결 실패 은폐**: 전체 DB 연결이 실패하여 행 수를 전혀 확인하지 못한 경우에도 빈 딕셔너리가 전달되고, 매니페스트에는 `recovery_trusted: true`로 기록되어 증거 없는 백업이 정상 백업처럼 취급되었습니다.
3. **G1 무손실 근거 부재**: 복구 신뢰 플래그가 파일 자산 존재 여부만으로 판정되어, 행 수 무손실 검증이 결여된 백업이 신뢰 가능한 것으로 판정되었습니다.

본 작업에서는 조회 실패와 실제 0행을 명확히 분리하고, 연결 실패 가시화, 매니페스트 증거 상태 기록, 과거 백업 취급 정책, 덤프-조회 시점 차이 명시를 완료했습니다.

---

## 2. 핵심 변경 내용

### 2.1 테이블별 조회 실패와 실제 0행 분리 (`failure_vs_zero`)
- **실제 0행**: `SELECT COUNT(*)` 성공 시 `int(val)`(0 포함)을 기록합니다 (`type == int`, 값 `0`).
- **조회 실패**: 예외 발생 시 `0`이 아닌 `None`(JSON 직렬화 시 `null`)을 기록합니다 (`val is None`).
- **효과**: 실제 0행인 테이블(`0`)과 조회가 실패한 테이블(`null`)이 명확히 구분됩니다.

### 2.2 전체 DB 연결 실패 가시화 (`connection_failure_visible`)
- 연결 실패 시 빈 딕셔너리를 반환하던 동작을 개선하여, 요청된 모든 대상 테이블(`DEFAULT_TABLES`)에 대해 `None`을 매핑하여 반환합니다 (`{tbl: None for tbl in tables}`).
- `evaluate_row_counts` 헬퍼를 도입하여 빈 결과이거나 모든 테이블이 `None`인 경우 상태를 `"connection_failed"`로 판정합니다.

### 2.3 매니페스트 행 수 증거 기록 및 `recovery_trusted` 연계 (`evidence_absence_recorded`)
- 매니페스트 최상위 및 `components.database`에 다음 필드를 기록합니다:
  - `row_count_status`: `"verified"` | `"table_query_failed"` | `"connection_failed"`
  - `row_count_evidence`: `"verified"` | `"unverified"`
- 신규 백업 시 `recovery_trusted`는 필수 파일 자산 구비뿐만 아니라 `row_count_status == "verified"`일 때만 `True`로 설정됩니다 (`recovery_trusted = (not missing_assets) and has_row_count_evidence`).
- 행 수 조회가 실패한 신규 백업은 `recovery_trusted: false`, `partial_backup: true`로 저장되어 복원 시 실패 종료(fail-closed)됩니다.

### 2.4 과거(레거시) 백업 매니페스트 취급 정책 (`legacy_backup_policy`)
- **원칙**: 기존 정상 백업 매니페스트가 이번 변경으로 복원 불가가 되어서는 안 됩니다 (GT-42 준수).
- **정책**: `recovery_trusted: true`가 명시된 과거 백업 매니페스트에 행 수 증거가 없거나(`row_counts: {}`) 미완료 상태인 경우, **복원을 차단하지 않고 명시적 경고를 출력**한 뒤 복원을 계속 진행합니다:
  `[경고] 과거 백업 매니페스트: 행 수 증거가 없어 무손실 검증이 미완료 상태입니다. 복원을 계속 진행합니다.`
- 반면 `recovery_trusted`가 `False`이거나 결측된 비신뢰 스냅샷은 기존 fail-closed 규칙에 따라 복원이 차단됩니다.

### 2.5 덤프 시점과 행 수 조회 시점 차이 명시 (`dump_timing_documented`)
- `mysqldump` 완료 후 별도 커넥션으로 `COUNT(*)`를 조회하므로, 쓰기 트랜잭션이 활성화된 DB에서는 덤프 시점의 실제 행 수와 조회 시점의 행 수가 다를 수 있습니다.
- 이 한계를 매니페스트의 `consistency_window.timing_note` 및 `components.database.timing_note`에 기록하여 행 수를 절대적 무손실 증명으로 과대평가하지 않도록 명시했습니다:
  `"덤프 완료 후 별도 조회한 행 수는 쓰기 중인 DB 의 덤프 시점 행 수와 다를 수 있습니다."`

---

## 3. 상태 매트릭스 요약

| 케이스 | `row_counts` 값 | `row_count_status` | `row_count_evidence` | `recovery_trusted` (자산 정상 시) | 복원 허용 여부 |
| --- | --- | --- | --- | --- | --- |
| **실제 0행** | `{"tbl": 0}` | `"verified"` | `"verified"` | `True` | 허용 |
| **테이블 쿼리 실패** | `{"tbl": None}` | `"table_query_failed"` | `"unverified"` | `False` | 차단 (fail-closed) |
| **전체 연결 실패** | `{"tbl": None, ...}` | `"connection_failed"` | `"unverified"` | `False` | 차단 (fail-closed) |
| **과거 정상 백업** | `{}` | N/A | N/A | `True` (기존 플래그) | 허용 (경고 출력) |

---

## 4. 검증 결과

- `tests/test_backup_recovery.py`: 실제 0행 verified, 테이블 실패 None/untrusted, 연결 실패 connection_failed, 레거시 백업 경고 복원 테스트 통과.
- `tests/test_backup_fail_closed.py`: `query_db_row_counts` 0 vs None 단위 테스트, 연결 실패 None 매핑 테스트, 행 수 실패 시 복원 차단 fail-closed 테스트 통과.
- `tests/test_backup_recovery_split.py`: 모듈 줄 수 상한(cap) 및 re-export 정합성 테스트 통과.
- 전체 회귀 테스트: 44/44 전량 통과 (`uv run pytest tests/test_backup_recovery.py tests/test_backup_fail_closed.py tests/test_backup_recovery_split.py -q`).
- 타입 검사: `uv run mypy src` 0건 (Success: no issues found in 93 source files).
- 규칙 정합성: `python3 scripts/validate_agent_rules.py --quiet` 20/20 전량 통과.

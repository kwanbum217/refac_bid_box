# Orca Capsule 생성 계약 및 체크리스트 보존 개선 보고서

> **작성일**: 2026-08-24
> **작성자**: Antigravity Gemini Flash High (Worker)
> **작업 ID**: `task_239aeabe1de4`
> **관련 문서**: [`docs/context/CURRENT_STATE.md`](../context/CURRENT_STATE.md), [`docs/ops/orca_task_capsule_v2.md`](../ops/orca_task_capsule_v2.md)

---

## 1. 개요 및 배경

본 작업은 Orca 다중 에이전트 환경에서 발생한 두 가지 Task Capsule 생성 계약 결함을 해결하기 위해 수행되었습니다.

1. **Builder Intent 의 review_checklist 누락 결함**:
   - `expand_intent_to_capsule` 이 `review_checklist` 를 reviewer 역할에만 추가하여, builder Intent 에 명시된 5개 이상의 검토 항목이 생성 Capsule 에서 소실됨.
   - 이로 인해 후속 `finalize` 단계에서 Level 2 reviewer 가 checklist 부재로 종료 코드 2 에러를 반환하는 문제 발생.
2. **Task 생성 시 가계정 Task ID 와 실제 Orca Task ID 불일치 및 원자성 결여**:
   - `taskctl create` 호출 시 임시/가계정 `task_id` 로 Capsule 을 먼저 작성하고 `task-create` 를 호출하여, Orca 가 반환한 실제 Task ID(`created_id`)와 Capsule 내부 `task_id`/`report_path`/디렉터리명이 불일치함.
   - `task-create` 실패 시 디스크에 미완성(반쪽) Capsule 이 잔류하는 원자성 결여 문제 해결.

---

## 2. 결함 원인 분석 및 해결 방안

### 2.1 review_checklist 보존 단일화

| 항목 | 기존 동작 및 결함 | 개선 내용 |
| --- | --- | --- |
| 체크리스트 첨부 조건 | `if is_reviewer:` 조건문으로 인해 builder 등 비리뷰어 역할의 체크리스트가 누락됨 | `if review_checklist:` 로 변경하여 역할과 무관하게 Intent 에 정의된 모든 검토 항목을 Capsule 에 보존 |
| 체크리스트 필드 무결성 | 단일 필드 누락 시 파싱 실패 위험 | `id`, `question`, `defect_when`, `how` 전 필드 포맷팅 및 YAML 이스케이프 지원 유지 |

### 2.2 Orca 실제 Task ID 동기화 및 원자적 생성

| 항목 | 기존 동작 및 결함 | 개선 내용 |
| --- | --- | --- |
| Task ID 확정 시점 | `task-create` 호출 전 임시 ID 로 Capsule 고정 작성 | `task-create` 가 반환한 `created_id` 로 Capsule 내부 `task_id`, `report_path`, `artifact_paths`, 디렉터리 경로를 원자적으로 재확정 및 동기화 |
| 생성 실패 시 상태 | `task-create` 실패 시에도 임시 Capsule 파일 잔류 | `task-create` 실패 또는 Task ID 미획득 시 생성된 임시 파일/디렉터리를 즉시 정리(rollback)하고 종료 코드 1 반환 |
| 재사용 Dispatch 동기화 | `--capsule` 재사용 시 CLI `--task-id` 와의 불일치 가능성 | Capsule 파일 내부의 `task_id` 를 파싱하여 동기화 |

---

## 3. 구현 내역 상세

### 3.1 `scripts/orca_taskctl.py`
- `expand_intent_to_capsule`: `if review_checklist:` 조건으로 변경하여 builder/reviewer 모두 체크리스트 보존.
- `cmd_create`:
  - `orca orchestration task-create` 실행 후 반환된 `created_id` 를 획득.
  - 실제 Task ID 경로(`actual_capsule_dir / "capsule.yaml"`)로 Capsule 을 확정 작성하고, 기존 임시 경로 정리.
  - `task-create` 실패 또는 2차 확장 실패 시 잔류 임시 파일 안전 정리.
- `cmd_dispatch`: `--capsule` 인자 수신 시 Capsule 내부 `task_id` 와 자동 동기화.

### 3.2 `tests/test_orca_taskctl.py`
- `test_expand_builder_preserves_review_checklist_all_fields`: builder Intent 의 `review_checklist` 가 Capsule 에 완전 보존되고 `validate_review_report.parse_checklist` 로 정상 파싱되는지 검증.
- `test_cmd_create_syncs_actual_task_id_to_capsule_and_spec`: `task-create` 반환 ID 와 생성 Capsule 내부 `task_id`, `report_path`, `artifact_paths`, `spec` 의 일치성 및 임시 디렉터리 정리 검증.
- `test_cmd_create_atomic_cleanup_on_task_create_exit_failure`: `task-create` 종료 실패 시 잔류 파일 정리 검증.
- `test_cmd_create_atomic_cleanup_on_missing_task_id`: Task ID 누락 응답 시 잔류 파일 정리 검증.
- `test_cmd_create_atomic_cleanup_on_reexpansion_error`: 2차 확장 예외 발생 시 롤백 및 종료 코드 2 반환 검증.

---

## 4. 검증 결과

```text
============================== 검증 요약 ==============================
1. 단위 및 제어 평면 테스트 (pytest):
   - tests/test_orca_taskctl.py: 135 passed (100%)
   - tests/test_orca_trust_worktree.py: 10 passed (100%)
2. 린터 검증:
   - ruff check .: PASS
3. Level 1 기계 검증 게이트 (--base d6031ee):
   - 게이트 1 변경 파일: 3건 (PASS)
   - 게이트 2 범위 검증: allowed_write_files 범위 내 (PASS)
   - 게이트 4b 린터: ruff check 통과 (PASS)
4. 참고 사항 (SSOT 신선도):
   - CURRENT_STATE.md 의 source_commit (4161269) 신선도(6 커밋 뒤처짐)는 코디네이터 지침에 따라 본 Task 범위 밖의 알려진 상태로 유지하며, 모든 구현 병합 후 SSOT Task 에서 최종 통합 HEAD 로 일괄 갱신 예정.
======================================================================
```

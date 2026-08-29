# Task task_75eda04c0e78 — 모델 라우터 연동 및 재작업/모드 감지 개선 분석 보고서

> **작성일**: 2026-08-30
> **Task ID**: task_75eda04c0e78
> **작업자**: Builder

---

## 1. 개요 및 배경

- **목적**:
  1. `orca_taskctl.py` 의 `dispatch` 경로가 `orca_model_router` 의 배정표(`select_model`, `TIER_POLICY`)를 실제로 연동하여, Task 의 역할(`role`)과 위험도(`risk`)에 맞는 워커 모델을 기계적으로 자동 선택하도록 개선.
  2. 코디네이터가 상위 모델을 명시 지정(`--model`)할 경우 경고를 표준 오류 및 출력에 남겨 가시성을 확보하되 우선권을 보장.
  3. 반려 후 2차 `worker_done` 거부 제약을 우회하기 위해, 이전 이력(사유, 보고서)을 보존하고 새 보고 경로를 발급하는 `rework` 서브커맨드 구현.
  4. Antigravity CLI 화면 갱신/스피너 상태에서 `normal` 로 오판되어 불필요한 `shift+tab` 전송으로 plan 모드에 빠지는 결함을 해결하기 위해 `unknown` 상태 도입 및 fail-closed 처리.

---

## 2. 주요 변경 사항

### 2.1 모델 라우터 연동 (`resolve_dispatch_model`)
- **자동 모델 선택**: `--model` 미지정 시 Capsule 의 역할과 위험도로 `orca_model_router.select_model` 을 호출하여 최적 모델 자동 배정 (예: `builder` + `medium` -> `gemini-3.7-flash-medium`, `high` -> `gemini-3.7-flash-high`).
- **상위 모델 지정 경고**: 사용자가 `--model` 로 배정표 기준 권장 모델보다 상위 티어(`MODEL_TIER_RANK`) 모델을 지정한 경우 경고 메시지 출력 및 `warning` 필드 기록.
- **Fail-safe Fallback**: 라우터 조회 실패 시 기본값(`DEFAULT_MODEL = "gemini-3.7-flash-high"`)으로 안전하게 폴백.
- **Dry-run 정합성**: `cmd_dispatch` 의 `--dry-run` 에서도 실제 Dispatch 와 동일한 `resolve_dispatch_model` 을 호출하여 모델, 역할, 위험도, 배정 근거, 경고를 일관되게 출력/반환.

### 2.2 반려 후 재작업 Task 발급 명령 (`rework`)
- **서브커맨드 `orca_taskctl rework`**:
  - `--task-id`, `--reason` 을 필수로 접수.
  - 기존 Task 디렉터리에 `rejection.json` 으로 반려 일시, 사유, 이전 `worker_done.json` 전문을 원본 보존.
  - `create_rework_capsule` 을 통해 새 Task ID(`task_orig_rework` 등)와 새 보고 경로(`.orca/capsules/<new_task_id>/worker_done.json`)를 포함하는 Capsule 을 생성하고 `why_now`, `ground_truth`, `required_change` 에 반려 사유 및 이전 커밋 사실 주입.
  - 새 Task 생성(`orca orchestration task-create`)을 호출하고 결과 반환.

### 2.3 Antigravity 상태줄 감지 및 모드 보호 (`detect_antigravity_mode`)
- 화면 텍스트가 비어 있거나, 스피너(`⠋ Thinking...`) 등 상태줄이 식별되지 않는 상태를 `unknown` 으로 감지.
- `enable_file_edit_auto_approve` 에서 `not force and current_mode == "unknown"` 일 경우 키(`shift+tab`)를 전송하지 않고 fail-closed 로 건너뜀으로써 원치 않는 plan 모드 진입 방지.

---

## 3. 검증 결과

- `tests/test_orca_taskctl.py` 에 다음 회귀 테스트 추가 및 전량 통과:
  1. `test_resolve_dispatch_model_risk_medium`: risk medium -> flash-medium 자동 배정
  2. `test_resolve_dispatch_model_risk_high`: risk high -> flash-high 자동 배정
  3. `test_resolve_dispatch_model_explicit_override`: --model 명시 지정 최우선
  4. `test_resolve_dispatch_model_higher_model_warning`: 상위 모델 지정 시 경고 출력
  5. `test_dispatch_dry_run_matches_actual_resolution`: dry-run 과 실제 Dispatch 모델 결정 일치
  6. `test_resolve_dispatch_model_fallback_on_router_error`: 라우터 에러 시 기본값 fallback
  7. `test_cmd_rework_preserves_history_and_creates_new_task`: 반려 이력 보존 및 새 재작업 Task 발급
  8. `test_detect_antigravity_mode_unknown_and_spinner`: 빈 화면/스피너 unknown 판정
  9. `test_enable_file_edit_auto_approve_unknown_skips_keys`: unknown 시 키 전송 건너뜀
- `uv run ruff check src/ scripts/ tests/`: All checks passed.
- `python3 scripts/validate_agent_rules.py --quiet`: 12/12 검증 통과.

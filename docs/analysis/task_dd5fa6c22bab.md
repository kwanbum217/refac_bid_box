# Gemini 3.8 Flash 주력 워커 채택 및 라우터·도구·문서 정합성 보고서

> **작성일**: 2026-09-03
> **Task ID**: `task_dd5fa6c22bab`
> **Run ID**: `run_971584ddb4a0`
> **관련 파일**: [`../../scripts/orca_model_router.py`](../../scripts/orca_model_router.py), [`../../scripts/orca_taskctl.py`](../../scripts/orca_taskctl.py), [`../../scripts/orca_agy_launch.py`](../../scripts/orca_agy_launch.py), [`../../scripts/orca_run_reviewer.py`](../../scripts/orca_run_reviewer.py), [`../ops/orca_worker_model_pool.md`](../ops/orca_worker_model_pool.md), [`../ops/orca_orchestration_playbook.md`](../ops/orca_orchestration_playbook.md), [`../ops/agent_worker_launch_reference.md`](../ops/agent_worker_launch_reference.md), [`../ops/orca_control_plane_tools.md`](../ops/orca_control_plane_tools.md), [`../ops/orca_do_not_repeat.md`](../ops/orca_do_not_repeat.md)

---

## 1. 개요 및 배경

2026-09-03 Antigravity(agy) CLI 환경에서 `gemini-3.8-flash-high`, `gemini-3.8-flash-medium`, `gemini-3.8-flash-low` 세 가지 추론 등급이 정식 지원되었으며, 코디네이터의 실측 probe를 통해 세 모델 모두 정상 응답(`agy --print ping`)이 확인되었습니다.

기존 라우터(`scripts/orca_model_router.py`)는 Gemini 3.7 Flash 모델군에 고정되어 있어 자동 배정 시 구형 세대에 머물러 있었습니다. 이에 따라 본 작업에서는 최신 세대인 **Gemini 3.8 Flash를 주력 워커 등급으로 공식 채택**하고, 기존 3.7 모델은 롤백 및 비교 검증용으로 안전하게 보존하며, 관련 제어 평면 스크립트와 운영 문서를 정합하게 갱신하였습니다.

---

## 2. 설계 및 구현 세부 사항

### 2.1 모델 등록 및 TIER_POLICY 단순성 설계 판단

- **별칭 유지 및 3.8 매핑**:
  기존의 워커 풀 별칭 규칙인 `gemini-flash-high`, `gemini-flash-medium`, `gemini-flash-low`를 유지하고, 각각의 실제 모델 ID를 `gemini-3.8-flash-high`, `gemini-3.8-flash-medium`, `gemini-3.8-flash-low`로 갱신(`auto_selectable: True`)했습니다.
- **TIER_POLICY 무수정 근거**:
  `scripts/orca_model_router.py`의 `TIER_POLICY`는 구체 모델 ID 대신 풀 키/별칭(`gemini-flash-*`)을 기반으로 배정 규칙을 정의합니다. 별칭이 가리키는 ID를 3.8로 전환함으로써 `TIER_POLICY`의 복잡한 튜플 매핑(`("builder", "high")`, `("investigator", "low")` 등)을 일절 변경하지 않고도 모든 역할의 자동 배정이 자연스럽게 3.8로 연결됩니다. 이는 변경 범위를 최소화하고 회귀 위험을 원천 차단하는 가장 단순하고 견고한 설계입니다.
- **Gemini 3.7 Flash 보존**:
  `gemini-3.7-flash-high`, `gemini-3.7-flash-medium`, `gemini-3.7-flash-low` 항목을 `MODEL_POOL`에 신규 등록하되 `auto_selectable: False`로 설정하였습니다. 이를 통해 자동 배정에서는 제외되면서도 `--model` 명시 지정과 `WORKER_MODEL_NOTICE`를 통한 수동 호출 및 롤백 경로가 완벽히 보장됩니다.
- **리뷰어 및 Low 등급 불변조건 유지**:
  - 빌더가 Gemini 계열인 동안 리뷰어는 다른 계열이어야 한다는 원칙에 따라 `reviewer`의 주 모델은 여전히 `qwen-plus`로 유지되며 Gemini 계열로 변경되지 않습니다.
  - `gemini-flash-low`는 초안 및 빠른 분석 전용이므로 빌더와 리뷰어에 배정하지 않는다는 기존 제약이 3.8에서도 동일하게 유지됩니다.

### 2.2 제어 평면 스크립트 기본값 갱신

1. [`scripts/orca_taskctl.py`](../../scripts/orca_taskctl.py):
   - `DEFAULT_MODEL`을 `gemini-3.8-flash-high`로 갱신.
   - `MODEL_TIER_RANK`에 `gemini-3.8-flash-low: 1`, `gemini-3.8-flash-medium: 2`, `gemini-3.8-flash-high: 3`을 추가하고 3.7 순위도 보존.
2. [`scripts/orca_run_reviewer.py`](../../scripts/orca_run_reviewer.py):
   - `DEFAULT_MODEL`을 `gemini-3.8-flash-high`로 갱신.
3. [`scripts/orca_agy_launch.py`](../../scripts/orca_agy_launch.py):
   - 런처 docstring 예시 및 `--model` 도움말 텍스트를 `gemini-3.8-flash-medium`으로 갱신.

### 2.3 운영 문서 지침 갱신 및 과거 이력 보존

- **과거 사실 보존 원칙**:
  과거 측정 일자(`2026-08-14`, `2026-08-30` 등)가 명시된 실측 기록과 장애 분석 사례(`docs/ops/orca_do_not_repeat.md`, `docs/ops/orca_orchestration_playbook.md`)의 모델명은 역사적 사실로서 일절 수정하지 않고 그대로 보존하였습니다.
- **향후 지침 갱신**:
  앞으로의 운영 기준을 명시하는 지침과 표를 3.8 기준으로 갱신하였습니다.
  - [`docs/ops/orca_worker_model_pool.md`](../ops/orca_worker_model_pool.md): 등록 모델 풀 현황 표에 3.8 주력 등록 및 3.7 보조 모델 등록.
  - [`docs/ops/orca_orchestration_playbook.md`](../ops/orca_orchestration_playbook.md): 주력 워커 기본값 및 매트릭스를 `gemini-3.8-flash-medium`으로 갱신.
  - [`docs/ops/agent_worker_launch_reference.md`](../ops/agent_worker_launch_reference.md): 제공자 확인 ID 및 워커 기동 예시 명령을 3.8로 갱신.
  - [`docs/ops/orca_control_plane_tools.md`](../ops/orca_control_plane_tools.md): `MODEL_POOL` 제어 평면 명세표 갱신.
  - [`docs/ops/orca_do_not_repeat.md`](../ops/orca_do_not_repeat.md): 5.2절 현재 정본 정책 기술을 `gemini-3.8-flash-medium`으로 갱신.

---

## 3. 검증 결과

### 3.1 단위 테스트 실행 결과

관련 단위 테스트 파일 전량 수정 및 실행을 완료하였습니다:
- `tests/test_orca_model_router.py`: 140 passed
- `tests/test_orca_taskctl.py`: 205 passed
- `tests/test_orca_agy_launch.py`: 21 passed
- `tests/test_orca_run_reviewer.py`: 43 passed
- `tests/test_orca_worker_launch_common.py`: 11 passed
- `tests/test_validate_agent_rules.py`: 41 passed

### 3.2 다중 에이전트 규칙 검증

`python3 scripts/validate_agent_rules.py --quiet` 실행 결과 19개 전체 항목 통과:
- `[PASS] 워커 모델 배정표 정합성 (TIER_POLICY vs 문서)`
- `[PASS] AGENTS.md 워커 모델 배정표 부재`
- `검증 통과: 19/19 건.`

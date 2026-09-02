# PSI 드리프트 모니터링 lwlt 결측 집단 분리 분석 및 구현 보고서

> **작성일**: 2026-09-02
> **작성자**: Orca Worker (task_4ad3aa7470df)
> **정본 사양**: `.orca/capsules/task_d3_drift_subgroup/capsule.yaml`
> **대상 모듈**: `src/ml/monitoring.py`, `src/tasks/scheduled_tasks.py`, `src/tasks/notifier.py`, `tests/test_drift_subgroup.py`

---

## 1. 개요 및 배경

본 과업은 [`servc_missing_lwlt_policy_20260902.md`](servc_missing_lwlt_policy_20260902.md) 6.2절 및 [`psi_drift_wiring_20260902.md`](psi_drift_wiring_20260902.md) 설계를 바탕으로, 낙찰하한율(`lwlt_rate`)이 제도적으로 결측된 취약 하위 집단(`missing_lwlt`)의 PSI 드리프트 모니터링을 분리하여 정밀하게 판정하고 알림을 차별화하는 작업을 완수했습니다.

### 1.1 핵심 과업 목표
1. **Baseline 집단 분리 저장**: `lwlt_rate_missing` 특징(0.0/1.0)별로 baseline 분포를 `by_lwlt_missing` 키에 분리 저장.
2. **집단별 임계값 차등 적용**: `with_lwlt` 집단은 0.2, 산포가 큰 `missing_lwlt` 집단은 0.25로 완화 적용.
3. **종합 판정 규칙**: 두 집단 중 하나라도 임계를 초과하면 모델 전체 `TRIGGER_RETRAIN` / `DRIFT_DETECTED` 판정.
4. **차별화 알림**: `missing_lwlt` 단독 미달 시 "결측 집단 드리프트" 전용 라벨로 운영 알림 차별화.
5. **표본 독립 검증**: 최소 표본 100건 기준을 집단별로 독립 적용하여 데이터 부족 시 `INSUFFICIENT_DATA` 처리.
6. **하위 호환성 보장**: `by_lwlt_missing` 키가 없는 구형 baseline에서도 기존 단일 방식으로 안전하게 평가.
7. **특징 단일화 및 불변식 준수**: 단일 진실 공급원(`src/ml/features.py`)의 특징을 그대로 사용하여 train/serve skew 방지 및 DB 스키마 무수정 유지.

---

## 2. 주요 변경 사항 및 설계 구현

### 2.1 Baseline 아티팩트 스키마 확장 (`src/ml/monitoring.py`)

`save_baseline_distributions` 함수를 고도화하여 `lwlt_rate_missing` 컬럼이 존재하는 모델(Servc 등)의 경우 `by_lwlt_missing` 키를 생성하고 집단별 통계(표본 수, 히스토그램, 분위수)를 독립 저장합니다.

- **스키마 구조**:
  - `feature_distributions_v1.json`:
    - `features`: 전체 데이터셋 특징 분포 요약 (하위 호환성 유지)
    - `by_lwlt_missing`:
      - `"0.0"`: `with_lwlt` (정상 하한율 보유 집단) 통계
      - `"1.0"`: `missing_lwlt` (하한율 제도적 결측 집단) 통계
    - `psi_config.subgroup_thresholds`: `{"0.0": 0.2, "1.0": 0.25}`

### 2.2 집단 분리 드리프트 계산 엔진 (`src/ml/monitoring.py`)

`check_dataset_drift` 함수에서 다음 로직을 구현했습니다:

- `by_lwlt_missing` 키와 `lwlt_rate_missing` 특징이 모두 존재할 경우 집단 분리 모드로 진입.
- `with_lwlt`(`0.0`)와 `missing_lwlt`(`1.0`) 각각에 대해 `_evaluate_feature_drift_on_frame` 실행.
- 표본 수 100건 미만인 집단은 개별 `INSUFFICIENT_DATA`로 처리.
- 판정 합성:
  - `sub_0` 또는 `sub_1` 중 하나라도 드리프트 발생 시 전체 `TRIGGER_RETRAIN`.
  - `sub_1`만 드리프트 시 `drift_subgroup_type = "missing_lwlt_only"`.
  - `sub_0`만 드리프트 시 `drift_subgroup_type = "with_lwlt_only"`.
  - 둘 다 드리프트 시 `drift_subgroup_type = "both"`.
- 구형 baseline이거나 `lwlt_rate_missing` 특징이 없는 모델은 로깅 후 기존 단일 집단 방식으로 평가.

### 2.3 스케줄 태스크 및 알림 연동 (`src/tasks/scheduled_tasks.py`, `src/tasks/notifier.py`)

- `drift_monitor_task`에서 집단 분리 결과(`by_subgroup`, `drift_subgroup_type`)를 `retrain_logs`의 `metrics_summary`에 기록.
- `notify_drift_detected`에 `drift_by_subgroup`, `drift_subgroup_type` 인자를 추가하여:
  - `missing_lwlt_only`인 경우 제목을 `[조치 필요] {model_name} 결측 집단 드리프트 감지 (missing_lwlt)`로 발신.
  - 본문에 집단별 상태(표본 수, 임계값, 드리프트 특징 수)를 상세 보고.
  - 자동 재학습/자동 승격은 실행하지 않고 수동 검토 권고 유지.

---

## 3. 검증 결과

### 3.1 단위 및 통합 테스트 (`tests/test_drift_subgroup.py`, `tests/test_psi_drift_wiring.py`)
- `tests/test_drift_subgroup.py`: 8개 신규 테스트 작성 및 100% 통과
  - `test_baseline_saved_with_by_lwlt_missing_subgroups` (PASS)
  - `test_baseline_without_lwlt_missing_does_not_have_subgroups` (PASS)
  - `test_backward_compatibility_old_baseline_without_by_lwlt_missing` (PASS)
  - `test_subgroup_drift_thresholds_and_relaxation` (PASS)
  - `test_subgroup_either_group_triggers_overall_retrain` (PASS)
  - `test_subgroup_independent_sample_size_check` (PASS)
  - `test_missing_lwlt_only_drift_notification_label` (PASS)
  - `test_drift_monitor_task_end_to_end_subgroup` (PASS)
- 전체 테스트 스위트: `3170 passed, 25 skipped, 0 failed` (`uv run pytest tests/ -q -m 'not data_assets'`)

### 3.2 규칙 및 정합성 검증 (`scripts/validate_agent_rules.py`)
- `python3 scripts/validate_agent_rules.py --quiet`: `17/17 PASS`

---

## 4. 수용 기준 및 체크리스트 대조표

| 검토 항목 | 기대 사양 | 충족 여부 | 확인 근거 |
| --- | --- | --- | --- |
| **Baseline 분리 저장** | `by_lwlt_missing` 내 0.0/1.0 분리 저장 | 충족 | `save_baseline_distributions` 구현 및 `test_baseline_saved_with_by_lwlt_missing_subgroups` |
| **임계값 완화** | with_lwlt 0.2, missing_lwlt 0.25 적용 | 충족 | `SUBGROUP_THRESHOLDS` 상수 정의 및 `test_subgroup_drift_thresholds_and_relaxation` |
| **종합 판정** | 한 집단이라도 드리프트 시 TRIGGER_RETRAIN | 충족 | `test_subgroup_either_group_triggers_overall_retrain` |
| **알림 차별화** | missing_lwlt 단독 미달 시 결측 집단 라벨 | 충족 | `notify_drift_detected` 및 `test_missing_lwlt_only_drift_notification_label` |
| **표본 독립성** | 100건 기준 집단별 독립 적용 | 충족 | `test_subgroup_independent_sample_size_check` |
| **하위 호환성** | 옛 baseline에서 무중단 단일 평가 | 충족 | `test_backward_compatibility_old_baseline_without_by_lwlt_missing` |
| **모델 일반화** | 모델명 하드코딩 없이 특징 유무로 분기 | 충족 | `test_baseline_without_lwlt_missing_does_not_have_subgroups` |
| **특징 단일화** | `features.py` 단일 공급원 유지 | 충족 | `build_feature_frame` 그대로 활용 |
| **자동화 안전** | 자동 재학습/승격 미발생 (알림과 기록만) | 충족 | `test_drift_monitor_task_end_to_end_subgroup` |
| **스키마 보존** | DB 스키마 및 마이그레이션 변경 없음 | 충족 | DB 모델 및 마이그레이션 미수정 |

---

**끝.**

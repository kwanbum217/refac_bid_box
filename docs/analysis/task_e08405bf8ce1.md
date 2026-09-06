# R-14 드리프트 감시 활성화 보고서 (task_e08405bf8ce1)

> **작성일**: 2026-09-06
> **Task**: task_e08405bf8ce1
> **정본**: `.orca/capsules/task_e08405bf8ce1/capsule.yaml`

---

## 1. 판정: baseline이 없는 모델에서 드리프트 태스크는 안전합니다

`src/tasks/scheduled_tasks.py`의 `drift_monitor_task`는 카테고리별로 baseline을 조회한 뒤(`541행`), baseline이 없으면 다음 분기로 들어갑니다(`542행`).

- `543-548행`: baseline 부재 사실을 `logger.info`로 남기고 판정을 보류한다는 로그를 기록합니다.
- `554-561행`: `_record_drift_log`로 `retrain_logs`에 `status="INSUFFICIENT_DATA"` 기록을 남깁니다.
- `562-568행`: 해당 카테고리 결과를 `status="skipped"`, `reason="no_baseline"`으로 두고 `continue`로 다음 카테고리로 넘어갑니다.

따라서 baseline이 없는 모델(Thng `quantum_leap_v25_pro`)에 대해서는 예외로 실패하지 않으며, 거짓 드리프트를 보고하지도 않고, 평가용 데이터셋 조회(`build_training_dataset`)에도 들어가지 않습니다. `src/ml/monitoring.py`의 `load_baseline_distributions`는 파일이 없으면 `None`을 반환합니다(`208-217행`). 이 판정에 따라 `ML_DRIFT_MONITOR_ENABLED` 기본값을 활성으로 바꾸는 순서 조건이 충족되었습니다.

## 2. 변경 내용

- `src/app/core/config.py`: `ML_DRIFT_MONITOR_ENABLED` 기본값을 `False`에서 `True`로 바꾸고, 주석을 Servc baseline 존재와 Thng 건너뛰기 안전성 기준으로 갱신했습니다.
- `src/tasks/scheduled_tasks.py`: baseline 부재 분기에 동작 계약(예외 없이 건너뛰고 `INSUFFICIENT_DATA`로 기록)을 설명하는 주석만 추가했으며, 실행 로직은 바꾸지 않았습니다.
- `tests/test_psi_drift_wiring.py`: baseline 부재 시 안전 건너뛰기 테스트와 baseline 존재 시 평가 수행 테스트를 대역으로 추가했습니다. 실제 DB나 실제 `ml_registry`에 접속하지 않습니다.
- `docs/context/current_state_facts.yaml`과 `docs/context/CURRENT_STATE.md`: `drift_job` 사실을 활성 상태로, `coldsql_rerun` 사실을 2026-09-06 부분 재측정 결과로 갱신했으며, 두 문서를 같은 커밋에서 함께 고쳤습니다. `source_commit`은 건드리지 않았습니다.
- `docs/ops/psi_drift_monitoring.md`: 6장에 활성화 기본값과 baseline 현황, baseline 부재 모델의 건너뛰기 동작을 명시했습니다. 자동 재학습·자동 승격 연결은 추가하지 않았으며 인간 개입 원칙을 유지합니다.

## 3. 잔여 사항

- Thng(`quantum_leap_v25_pro`) baseline이 여전히 없으므로 해당 모델은 감시 대상이 아니며 건너뛰기가 계속 기록됩니다. Thng baseline 생성은 이 Task 범위 밖입니다.
- `coldsql_rerun` 재측정은 `partial`이며 정본 수치가 아니므로, 정본 측정은 별도 Task에서 canonical 게이트 충족 조건으로 진행해야 합니다.

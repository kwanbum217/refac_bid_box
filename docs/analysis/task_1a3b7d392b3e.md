# task_1a3b7d392b3e — 대형 모듈 기계적 분할

> **작성일**: 2026-09-03
> **상태**: 완료

## 요약

`src/tasks/automation_tasks.py`(717줄)와 `src/ml/monitoring.py`(664줄)를 chatbot API 분할 관례와 동일하게 형제 모듈로 기계 이동했습니다. 함수 본문·이름·시그니처는 변경하지 않았고, 기존 import 경로는 재수출로 유지했습니다.

## 분할 경계

| 원본 | 신규 | 이동 심볼 |
| --- | --- | --- |
| `src/tasks/automation_tasks.py` | `src/tasks/automation_steps.py` | `_step_collect`, `_step_rag`, `_step_search`, `_step_predict`, `_step_retrain`, `_check_chroma_vectors`, `_step_inspect` |
| `src/ml/monitoring.py` | `src/ml/psi.py` | `InsufficientSampleError`, `calculate_psi`, `calculate_categorical_psi`, `check_feature_drift` |

PSI 기본 상수(`DEFAULT_MIN_SAMPLES`, `DEFAULT_PSI_THRESHOLD`, `DEFAULT_NUM_BUCKETS`)는 이동 함수의 기본 인자로 쓰이므로 `psi.py`에 두고 `monitoring.py`에서 재수출했습니다. `psi` → `monitoring` 순환을 피하기 위한 한 방향 의존입니다.

## 줄 수 (실측 / 상한 = 실측 + 20)

| 파일 | 실측 | 상한 |
| --- | ---: | ---: |
| `src/tasks/automation_tasks.py` | 432 | 452 |
| `src/tasks/automation_steps.py` | 336 | 356 |
| `src/ml/monitoring.py` | 562 | 582 |
| `src/ml/psi.py` | 145 | 165 |

## 순환 import

- `automation_steps`는 `automation_tasks`를 import하지 않습니다.
- `psi`는 `monitoring`을 import하지 않습니다.
- `tests/test_large_module_split.py`가 AST로 단언합니다.

## 외부 호환

- `from src.tasks.automation_tasks import _step_*` / `_check_chroma_vectors` 재수출 유지.
- `from src.ml.monitoring import calculate_psi, ...` 재수출 유지.
- `tests/test_pipeline_step_status_fail_open.py`의 `_check_chroma_vectors` patch 경로만 `src.tasks.automation_steps`로 수정(코디네이터 승인). 동일 유형의 다른 테스트 파일은 없었습니다.

## 검증

```
uv run pytest tests/ -q -m 'not data_assets'
3339 passed, 35 skipped, 3 deselected, 320 warnings in 86.86s (0:01:26)

python3 scripts/validate_agent_rules.py --quiet
검증 통과: 19/19 건.
```

## 환경 메모

- 격리 워크트리에 `data/model_files`·`chroma_db`가 없어 `tests/test_data_preservation.py`의 자산 존재 검사 2건은 `-m 'not data_assets'`로 제외했습니다. 워커 결함이 아닙니다.
- 개선 후보(보고만): `automation_steps`의 `_check_chroma_vectors` 내부 `settings` 재import는 원본 그대로이며 정리하지 않았습니다.

## 변경 파일

- `src/tasks/automation_tasks.py`
- `src/tasks/automation_steps.py` (신규)
- `src/ml/monitoring.py`
- `src/ml/psi.py` (신규)
- `tests/test_large_module_split.py` (신규)
- `tests/test_pipeline_step_status_fail_open.py` (patch 경로만)
- `docs/analysis/task_1a3b7d392b3e.md`

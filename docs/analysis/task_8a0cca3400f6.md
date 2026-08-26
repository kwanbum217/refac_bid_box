# task_8a0cca3400f6: 마지막 11개 mypy special override 제거

> **작성일**: 2026-08-26
> **Task**: `task_8a0cca3400f6`
> **브랜치**: `kwanbum217/mypy-special-20260826`

---

## 요약

소유한 11개 `[[tool.mypy.overrides]]` 블록(13모듈)을 **전부 제거**했습니다. 국소 타입 보강만으로 `uv run mypy src/ scripts/` 가 통과하며, 존치 override 는 0건입니다.

| 항목 | 제거 전 | 제거 후 |
| --- | --- | --- |
| override 블록 | 11 | 0 |
| 소유 모듈 | 13 | 13 (타입 보강) |
| disable_error_code 합계 | 24 코드 | 0 |

---

## 모듈별 조치

| 모듈 | 제거한 override | 타입 보강 |
| --- | --- | --- |
| `scripts.orca_trust_worktree` | `attr-defined` | Windows `msvcrt` 접근을 `getattr` 로 분기 (macOS 에서는 `fcntl` 경로만 실행) |
| `scripts.benchmark_sse_gate` | `index` | `MetricStats`/`BenchmarkSummary` `TypedDict`, 단일 import 경로 |
| `scripts.measure_predict_rss` | `index`, `unused-ignore` | `RssReport`/`LatencyMs` `TypedDict`, psutil optional 모듈 바인딩 |
| `scripts.compare_servc_models_by_group` | `assignment`, `method-assign` | `_bind_registry_model_root()` + `object.__setattr__` |
| `scripts.compare_servc_models_paired` | (동일 블록) | (동일) |
| `scripts.diagnose_serving_vs_holdout_model` | `attr-defined`, `type-var` | `lgb.LGBMRegressor` 반환·`cast`, `np.float64` |
| `scripts.eval_servc_candidates_unbiased` | `arg-type`, `attr-defined`, `type-var` | `_huber_regressor()` 명시 kwargs |
| `scripts.eval_servc_refit_unbiased` | (동일 블록) | (동일) |
| `scripts.orca_level1_gate` | `union-attr`, `unused-ignore` | `prefix is not None` 가드, 불필요 `type: ignore` 제거 |
| `scripts.orca_metrics_ledger` | `no-redef`, `unused-ignore` | 루프 변수 `existing_row`, `ledger_row` 분리 |
| `scripts.orca_model_router` | `attr-defined`, `return-value`, `unused-ignore` | `msvcrt` `getattr`, 중복 관측 시 `dict` 반환 보장 |
| `scripts.restore_from_parquet` | `arg-type`, `list-item` | SQLAlchemy `Table` `cast` |
| `scripts.segment_servc_models` | `arg-type`, `return-value` | `LGBMRegressor` 명시 kwargs, `np.float64` predict |

---

## 스텁 한계로 존치한 override

없음. 이번 Task 소유 블록은 모두 코드 측 타입 보강으로 해소했습니다.

참고: `msvcrt`/`LightGBM **kwargs`/`SQLAlchemy FromClause` 는 스텁 한계가 있으나, 각 모듈에서 `getattr`·명시 kwargs·`cast(Table, ...)` 로 override 없이 통과했습니다.

---

## 검증

| 명령 | 결과 |
| --- | --- |
| `uv run mypy src/ scripts/` | Success (198 files) |
| `uv run pytest tests/ -q -m 'not data_assets'` | 2197 passed, 2 failed |
| `python3 scripts/validate_agent_rules.py --quiet` | FAIL (`CURRENT_STATE` `source_commit` 6커밋 지연, Task 범위 밖) |

실패 2건은 `docs/context/CURRENT_STATE.md` 갱신 지연(허용 5커밋 초과)으로, 본 Task `allowed_write_files` 밖입니다.

---

## 재개 조건

소유 11블록은 모두 제거 완료. 후속 Task 는 다른 override 블록(`arg-type` 전역 이전 잔여 6블록 등)을 대상으로 합니다.

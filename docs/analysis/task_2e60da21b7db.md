# task_2e60da21b7db — 첫 arg-type 블록 16모듈 타입 보강

> **작성일**: 2026-08-26
> **Task**: task_2e60da21b7db
> **브랜치**: kwanbum217/mypy-argtype-20260826

---

## 요약

첫 `[[tool.mypy.overrides]]` arg-type 블록(16모듈)을 전부 해소했습니다. override 제외 mypy 재측정 후 타입을 좁혔고, 해당 블록 자체를 `pyproject.toml`에서 제거했습니다.

| 항목 | 값 |
| --- | --- |
| 대상 모듈 | 16 |
| override 제거 | 16 |
| override 존치 | 0 |
| 런타임 동작 변경 | 없음 |

---

## 모듈별 조치

| 모듈 | arg-type 건수(override 제외) | 조치 |
| --- | ---: | --- |
| scripts.analyze_servc_error_concentration | 4 | `banded` 시그니처를 `Sequence`로 완화, `SAMPLE_BANDS` 경계를 float 리터럴로 통일 |
| scripts.benchmark_latency | 3 | provenance 메타데이터 해소 후 `None` 가드 추가 |
| src.app.services.collector_service | 4 | `resolve_collection_window` 반환값을 `resolved_start`/`resolved_end`로 분리 |
| src.app.main | 20 | FastAPI/CORS `**kwargs` 대신 명시 인자 전달, `_CorsKwargs` TypedDict |
| scripts.ablation_servc_features | 6 | `LGBMRegressor(**cast(_LGBMKwargs, ...))` |
| scripts.diagnose_holdout_serving_gap | 7 | 동일 TypedDict cast |
| scripts.eval_servc_excess_target | 15 | 동일 + `best_iteration_`/`n_estimators` int cast |
| scripts.eval_servc_flag_features | 15 | 동일 |
| scripts.eval_servc_interval_width | 5 | 분위 모델용 `_LGBMQuantileParams` cast |
| scripts.eval_servc_interval_width_by_group | 5 | 동일 |
| scripts.eval_servc_participant_effect | 8 | TypedDict cast + `np.asarray(predict)` |
| scripts.eval_servc_quantile_alpha | 16 | TypedDict cast + hyperparam alpha float cast |
| scripts.eval_servc_regime_lwlt_levels | 15 | TypedDict cast |
| scripts.eval_servc_rolling_institution | 7 | TypedDict cast |
| scripts.eval_servc_year_holdout | 8 | TypedDict cast + `np.asarray(predict)` |
| scripts.measure_servc_split_variance | 16 | TypedDict cast + hyperparam alpha float cast |

---

## 검증

| 명령 | 결과 |
| --- | --- |
| `uv run mypy src/ scripts/` | Success (198 files) |
| `uv run pytest tests/ -q -m 'not data_assets'` | 2197 passed, 2 failed (CURRENT_STATE 지연, Task 범위 밖) |
| `python3 scripts/validate_agent_rules.py --quiet` | CURRENT_STATE `source_commit` 6커밋 지연으로 FAIL (Task 범위 밖) |

---

## 비고

- `type: ignore`, `Any` 확산, `disable_error_code` 확대는 사용하지 않았습니다.
- LightGBM `**params` 는 파일 로컬 `TypedDict` + `cast`로 정적 검사만 보강했으며 런타임 dict 내용은 동일합니다.

# mypy module override 부채 인벤토리 (task_cd74b709edb0)

> **작성일**: 2026-08-26
> **작업 ID**: `task_cd74b709edb0`
> **범위**: 조사 전용 (`pyproject.toml`, `src/`, `scripts/` 수정 없음)

---

## 1. override 모듈 전체 목록 및 억제 error code

`pyproject.toml`의 `[[tool.mypy.overrides]]` 20개 블록, 55개 모듈.

| 모듈 | 억제 error code |
| --- | --- |
| scripts.ablation_servc_features | arg-type |
| scripts.analyze_servc_error_concentration | arg-type |
| scripts.arq_gate | arg-type, assignment |
| scripts.audit_model_inventory | operator, return-value |
| scripts.audit_servc_rawdata_regime_scan | assignment |
| scripts.benchmark_arq_container | arg-type, call-overload, misc, unused-ignore |
| scripts.benchmark_arq_throughput | call-overload |
| scripts.benchmark_latency | arg-type |
| scripts.benchmark_provenance | arg-type, dict-item, operator |
| scripts.benchmark_rag_segments | attr-defined |
| scripts.benchmark_sse_gate | index |
| scripts.compare_servc_models_by_group | assignment, method-assign |
| scripts.compare_servc_models_paired | assignment, method-assign |
| scripts.diagnose_holdout_serving_gap | arg-type |
| scripts.diagnose_serving_vs_holdout_model | attr-defined, type-var |
| scripts.eval_servc_api_path | arg-type |
| scripts.eval_servc_candidates_unbiased | arg-type, attr-defined, type-var |
| scripts.eval_servc_ensemble_headroom | call-overload |
| scripts.eval_servc_excess_target | arg-type |
| scripts.eval_servc_flag_features | arg-type |
| scripts.eval_servc_inst_clsfc_cross | operator |
| scripts.eval_servc_interval_by_group | arg-type |
| scripts.eval_servc_interval_width | arg-type |
| scripts.eval_servc_interval_width_by_group | arg-type |
| scripts.eval_servc_participant_effect | arg-type |
| scripts.eval_servc_prediction_interval | arg-type, assignment |
| scripts.eval_servc_quantile_alpha | arg-type |
| scripts.eval_servc_regime_lwlt_levels | arg-type |
| scripts.eval_servc_refit_unbiased | arg-type, attr-defined, type-var |
| scripts.eval_servc_rolling_institution | arg-type |
| scripts.eval_servc_year_holdout | arg-type |
| scripts.import_data_assets | index |
| scripts.measure_predict_rss | index, unused-ignore |
| scripts.measure_servc_split_variance | arg-type |
| scripts.orca_level1_gate | union-attr, unused-ignore |
| scripts.orca_metrics_ledger | no-redef, unused-ignore |
| scripts.orca_model_router | attr-defined, return-value, unused-ignore |
| scripts.orca_trust_worktree | attr-defined |
| scripts.repair_contract_method | attr-defined |
| scripts.restore_from_parquet | arg-type, list-item |
| scripts.run_p9_sse_parallel_bench | attr-defined |
| scripts.run_p9_sse_rebaseline | attr-defined |
| scripts.segment_servc_models | arg-type, return-value |
| scripts.summarize_worker_done | unused-ignore |
| src.app.api.v1.chatbot | arg-type |
| src.app.main | arg-type |
| src.app.services.collector_service | arg-type |
| src.app.services.conversation_state | assignment |
| src.app.services.home_context | arg-type |
| src.app.services.kb_builder | arg-type, assignment |
| src.app.services.tools.trend_analyzer | arg-type |
| src.ml.model_registry | assignment |
| src.ml.trainer | arg-type, assignment |
| src.rag.llm | arg-type, assignment |
| src.tasks.automation_tasks | arg-type, assignment |

---

## 2. 모듈별 실측 오류 건수

override를 제외한 설정으로 측정. override 대상 55개 파일에서 발생한 오류는 모두 해당 모듈의 `disable_error_code`에 해당하는 코드뿐.

| 모듈 | 건수 |
| --- | ---: |
| src.app.main | 20 |
| scripts.eval_servc_refit_unbiased | 18 |
| scripts.eval_servc_candidates_unbiased | 16 |
| scripts.eval_servc_quantile_alpha | 16 |
| scripts.measure_servc_split_variance | 16 |
| scripts.eval_servc_excess_target | 15 |
| scripts.eval_servc_flag_features | 15 |
| scripts.eval_servc_regime_lwlt_levels | 15 |
| scripts.benchmark_provenance | 9 |
| scripts.eval_servc_participant_effect | 8 |
| scripts.eval_servc_year_holdout | 8 |
| scripts.segment_servc_models | 8 |
| src.ml.model_registry | 8 |
| src.ml.trainer | 8 |
| scripts.diagnose_holdout_serving_gap | 7 |
| scripts.eval_servc_prediction_interval | 7 |
| scripts.eval_servc_rolling_institution | 7 |
| scripts.ablation_servc_features | 6 |
| scripts.orca_model_router | 6 |
| src.tasks.automation_tasks | 6 |
| scripts.benchmark_sse_gate | 5 |
| scripts.eval_servc_interval_width | 5 |
| scripts.eval_servc_interval_width_by_group | 5 |
| scripts.analyze_servc_error_concentration | 4 |
| scripts.benchmark_arq_container | 4 |
| scripts.measure_predict_rss | 4 |
| scripts.orca_metrics_ledger | 4 |
| scripts.orca_trust_worktree | 4 |
| src.app.services.collector_service | 4 |
| scripts.benchmark_latency | 3 |
| scripts.restore_from_parquet | 3 |
| src.app.services.kb_builder | 3 |
| src.rag.llm | 3 |
| scripts.audit_model_inventory | 2 |
| scripts.compare_servc_models_by_group | 2 |
| scripts.compare_servc_models_paired | 2 |
| scripts.diagnose_serving_vs_holdout_model | 2 |
| scripts.orca_level1_gate | 2 |
| scripts.arq_gate | 1 |
| scripts.audit_servc_rawdata_regime_scan | 1 |
| scripts.benchmark_arq_throughput | 1 |
| scripts.benchmark_rag_segments | 1 |
| scripts.eval_servc_api_path | 1 |
| scripts.eval_servc_ensemble_headroom | 1 |
| scripts.eval_servc_inst_clsfc_cross | 1 |
| scripts.eval_servc_interval_by_group | 1 |
| scripts.import_data_assets | 1 |
| scripts.repair_contract_method | 1 |
| scripts.run_p9_sse_parallel_bench | 1 |
| scripts.run_p9_sse_rebaseline | 1 |
| scripts.summarize_worker_done | 1 |
| src.app.api.v1.chatbot | 1 |
| src.app.services.conversation_state | 1 |
| src.app.services.home_context | 1 |
| src.app.services.tools.trend_analyzer | 1 |
| **총계** | **297** |

오류 코드별 합계: arg-type 217, assignment 21, attr-defined 16, index 9, unused-ignore 7, dict-item 6, type-var 4, return-value 3, operator 3, call-overload 3, misc 2, list-item 2, method-assign 2, union-attr 1, no-redef 1.

---

## 3. 실측에 사용한 mypy 명령

baseline (override 적용, 오류 0):

```bash
uv run mypy src/ scripts/
```

억제 오류 실측 (`pyproject.toml` 미수정, override 블록을 제외한 임시 설정 `/tmp/mypy_inventory_base.toml` 사용):

```bash
uv run mypy --config-file=/tmp/mypy_inventory_base.toml src/ scripts/
```

결과: **297 errors in 55 files** (checked 196 source files).

임시 설정은 `pyproject.toml`의 `[tool.mypy]` 기본 항목(`python_version`, `plugins`, `ignore_missing_imports` 등)만 복사하고 `[[tool.mypy.overrides]]`는 포함하지 않음.

---

## 4. 모듈별 대표 오류 메시지 및 해소 난이도

| 모듈 | 대표 오류 메시지 | 해소 난이도 |
| --- | --- | --- |
| scripts.summarize_worker_done | Unused "type: ignore" comment | 미사용 ignore 주석 제거만으로 즉시 해소 가능. |
| scripts.eval_servc_api_path | Argument 2 to "predict_price_api" has incompatible type "Session"; expected "Request" | 단일 인자 타입 정정으로 해소 가능. |
| scripts.eval_servc_interval_by_group | Argument 2 to "predict_price_api" has incompatible type "Session"; expected "Request" | 단일 인자 타입 정정으로 해소 가능. |
| scripts.eval_servc_inst_clsfc_cross | Unsupported operand types for < ("int" and "object") | 비교 연산 인자 한 줄 좁히기로 해소 가능. |
| scripts.eval_servc_ensemble_headroom | No overload variant of "min" matches argument types "object", "object" | min() 인자 타입 좁히기 한 줄로 해소 가능. |
| scripts.benchmark_arq_throughput | No overload variant of "int" matches argument type "object" | int() 인자 타입 좁히기 한 줄로 해소 가능. |
| scripts.benchmark_rag_segments | "object" has no attribute "get" | dict 타입 좁히기 한 줄로 해소 가능. |
| scripts.import_data_assets | Unsupported target for indexed assignment ("Collection[Any]") | 컬렉션 타입 좁히기 한 줄로 해소 가능. |
| scripts.repair_contract_method | "Result[Any]" has no attribute "rowcount" | SQLAlchemy Result 타입 명시로 해소 가능. |
| scripts.run_p9_sse_parallel_bench | Module "scripts.benchmark_sse_gate" has no attribute "get_git_sha" | 모듈 export 정리 한 곳으로 해소 가능. |
| scripts.run_p9_sse_rebaseline | Module "scripts.benchmark_sse_gate" has no attribute "get_git_sha" | 모듈 export 정리 한 곳으로 해소 가능. |
| scripts.audit_servc_rawdata_regime_scan | Incompatible types in assignment (expression has type "bool", variable has type "...") | 변수 타입 한 줄 수정으로 해소 가능. |
| scripts.arq_gate | Incompatible types in assignment (expression has type "ThroughputGateResult", ...) | 결과 타입 명시 한 줄로 해소 가능. |
| src.app.api.v1.chatbot | Argument "kb_status" to "_PendingRagAnswer" has incompatible type "dict[str, Any]" | 운영 API 단일 인자 타입 정정으로 해소 가능. |
| src.app.services.home_context | Argument 1 to "float" has incompatible type "Decimal \| None" | None 가드 한 줄로 해소 가능. |
| src.app.services.conversation_state | Incompatible types in assignment (expression has type "list[dict[Any, Any]]", ...) | SQLAlchemy JSON 컬럼 할당 타입 한 줄 수정으로 해소 가능. |
| src.app.services.tools.trend_analyzer | Argument 1 to "float" has incompatible type "object" | float 변환 인자 좁히기 한 줄로 해소 가능. |
| scripts.audit_model_inventory | Unsupported operand types for + ("str" and "int") | 연산자/반환 타입 국소 수정 2건으로 해소 가능. |
| scripts.compare_servc_models_by_group | Cannot assign to a method | 메서드 패치 패턴 리팩터링 2건으로 해소 가능. |
| scripts.compare_servc_models_paired | Cannot assign to a method | 메서드 패치 패턴 리팩터링 2건으로 해소 가능. |
| scripts.diagnose_serving_vs_holdout_model | Value of type variable "ScalarT" of "asarray" cannot be "float" | numpy 제네릭 타입 2건으로 해소 가능. |
| scripts.orca_level1_gate | Unused "type: ignore" comment | ignore 제거 후 union-attr 1건 추가 수정 필요. |
| scripts.benchmark_latency | Argument 1 to "verify_provenance_consistency" has incompatible type "dict[str, object]" | dict 타입 좁히기 3건으로 해소 가능. |
| scripts.restore_from_parquet | Argument 1 to "insert" has incompatible type "FromClause"; expected "TableClause" | SQLAlchemy insert 타입 3건으로 해소 가능. |
| src.app.services.kb_builder | Argument 2 to "_resolve_delta_announcements" has incompatible type "datetime \| None" | 운영 KB 경로 None/할당 3건 국소 수정으로 해소 가능. |
| src.rag.llm | Argument "contents" to "generate_content" has incompatible type "list[...]" | Gemini API 인자 타입 3건 보강으로 해소 가능. |
| scripts.analyze_servc_error_concentration | Argument 2 to "banded" has incompatible type "list[tuple[str, int, float]]" | scipy banded 호출 타입 4건 일괄 수정 필요. |
| scripts.benchmark_arq_container | Incompatible types in "await" (actual type "Awaitable[list[Any]] \| list[Any]", ...) | async 반환 타입 혼재 4건; ignore 제거 포함. |
| scripts.measure_predict_rss | Unused "type: ignore" comment | ignore 제거 후 index 3건 추가 수정 필요. |
| scripts.orca_metrics_ledger | Unused "type: ignore" comment | ignore 3건 제거 후 no-redef 1건 추가 수정 필요. |
| scripts.orca_trust_worktree | Module has no attribute "locking" | 플랫폼 분기(msvcrt/fcntl) stub 또는 TYPE_CHECKING 가드 4건 필요. |
| src.app.services.collector_service | Argument 1 to "stream_bid_announcements" has incompatible type "str \| None" | 운영 수집 경로 None 가드 4건 반복 패턴. |
| scripts.benchmark_sse_gate | Value of type "object" is not indexable | object 인덱싱 5건; 타입 좁히기 반복 필요. |
| scripts.eval_servc_interval_width | Argument 3 to "LGBMRegressor" has incompatible type "**dict[str, float]" | LGBM params 타입 선언으로 5건 일괄 해소 가능. |
| scripts.eval_servc_interval_width_by_group | Argument 3 to "LGBMRegressor" has incompatible type "**dict[str, float]" | LGBM params 타입 선언으로 5건 일괄 해소 가능. |
| scripts.ablation_servc_features | Argument 1 to "LGBMRegressor" has incompatible type "**dict[str, float]" | LGBM kwargs 6건; params 타입 선언으로 일괄 해소 가능. |
| scripts.orca_model_router | Unused "type: ignore" comment | ignore 제거 후 attr-defined 4건 + return-value 1건 수정 필요. |
| src.tasks.automation_tasks | Argument 1 to "signature" has incompatible type "function"; expected "Callable[...]" | 운영 태스크 Arq/Celery 시그니처 타입 6건 보강 필요. |
| scripts.diagnose_holdout_serving_gap | Argument 1 to "LGBMRegressor" has incompatible type "**dict[str, object]" | LGBM kwargs 7건 반복 패턴. |
| scripts.eval_servc_prediction_interval | Argument 3 to "LGBMRegressor" has incompatible type "**dict[str, object]" | LGBM kwargs 6건 + assignment 1건. |
| scripts.eval_servc_rolling_institution | Argument 1 to "LGBMRegressor" has incompatible type "**dict[str, object]" | LGBM kwargs 7건 반복 패턴. |
| src.ml.trainer | Argument 1 to "LGBMRegressor" has incompatible type "**dict[str, object]" | 운영 ML 경로 LGBM + 래퍼 할당 8건; Union/Protocol 필요. |
| src.ml.model_registry | Incompatible types in assignment (expression has type "V13HybridWrapper", ...) | 래퍼 다형 할당 8건; Union 또는 Protocol 정의 필요. |
| scripts.eval_servc_participant_effect | Argument 1 to "LGBMRegressor" has incompatible type "**dict[str, object]" | LGBM kwargs 8건 반복 패턴. |
| scripts.eval_servc_year_holdout | Argument 1 to "LGBMRegressor" has incompatible type "**dict[str, object]" | LGBM kwargs 8건 반복 패턴. |
| scripts.segment_servc_models | Argument 1 to "LGBMRegressor" has incompatible type "**dict[str, object]" | LGBM kwargs 7건 + return-value 1건. |
| scripts.benchmark_provenance | Argument 1 to "float" has incompatible type "object" | dict-item 6건 집중; 중첩 dict 타입 어노테이션 필요. |
| scripts.eval_servc_excess_target | Argument 1 to "LGBMRegressor" has incompatible type "**dict[str, object]" | LGBM kwargs 15건; 파일 단위 일괄 수정 필요. |
| scripts.eval_servc_flag_features | Argument 1 to "LGBMRegressor" has incompatible type "**dict[str, object]" | LGBM kwargs 15건; 파일 단위 일괄 수정 필요. |
| scripts.eval_servc_regime_lwlt_levels | Argument 1 to "LGBMRegressor" has incompatible type "**dict[str, object]" | LGBM kwargs 15건; 파일 단위 일괄 수정 필요. |
| scripts.eval_servc_quantile_alpha | Argument 1 to "float" has incompatible type "object" | float(object) 변환 16건 반복 패턴. |
| scripts.measure_servc_split_variance | Argument 1 to "float" has incompatible type "object" | float(object) 변환 16건 반복 패턴. |
| scripts.eval_servc_candidates_unbiased | Argument 1 to "LGBMRegressor" has incompatible type "**dict[str, object]" | LGBM + numpy 제네릭 16건; 파일 단위 리팩터링 필요. |
| scripts.eval_servc_refit_unbiased | Argument 1 to "LGBMRegressor" has incompatible type "**dict[str, object]" | LGBM + numpy 제네릭 18건; 파일 단위 리팩터링 필요. |
| src.app.main | Argument 5 to "FastAPI" has incompatible type "**dict[str, str \| None]" | FastAPI/Starlette 미들웨어 kwargs 설계 변경 필요; 최후순위. |

---

## 5. 해소 우선순위

원칙: 건수가 적고 패턴이 단순한 모듈 우선. 동일 건수이면 `src/` 운영 코드를 `scripts/`보다 우선.

| 순위 | 모듈 | 건수 | 근거 |
| ---: | --- | ---: | --- |
| 1 | scripts.summarize_worker_done | 1 | 미사용 ignore 주석 제거만으로 해소 |
| 2 | src.app.api.v1.chatbot | 1 | 운영 API 단일 인자 타입 정정 |
| 3 | src.app.services.home_context | 1 | None 가드 한 줄 |
| 4 | src.app.services.conversation_state | 1 | SQLAlchemy JSON 할당 한 줄 |
| 5 | src.app.services.tools.trend_analyzer | 1 | float 변환 좁히기 한 줄 |
| 6 | scripts.eval_servc_api_path | 1 | Session/Request 타입 정정 |
| 7 | scripts.eval_servc_interval_by_group | 1 | Session/Request 타입 정정 |
| 8 | scripts.eval_servc_inst_clsfc_cross | 1 | 비교 연산 인자 좁히기 |
| 9 | scripts.eval_servc_ensemble_headroom | 1 | min() 인자 좁히기 |
| 10 | scripts.benchmark_arq_throughput | 1 | int() 인자 좁히기 |
| 11 | scripts.benchmark_rag_segments | 1 | dict 타입 좁히기 |
| 12 | scripts.import_data_assets | 1 | 컬렉션 타입 좁히기 |
| 13 | scripts.repair_contract_method | 1 | SQLAlchemy Result 타입 |
| 14 | scripts.run_p9_sse_parallel_bench | 1 | 모듈 export 정리 |
| 15 | scripts.run_p9_sse_rebaseline | 1 | 모듈 export 정리 |
| 16 | scripts.audit_servc_rawdata_regime_scan | 1 | 변수 타입 한 줄 |
| 17 | scripts.arq_gate | 1 | 결과 타입 명시 |
| 18 | scripts.audit_model_inventory | 2 | 연산자/반환 타입 2건 |
| 19 | scripts.compare_servc_models_by_group | 2 | 메서드 패치 리팩터링 |
| 20 | scripts.compare_servc_models_paired | 2 | 메서드 패치 리팩터링 |
| 21 | scripts.diagnose_serving_vs_holdout_model | 2 | numpy 제네릭 2건 |
| 22 | scripts.orca_level1_gate | 2 | ignore 제거 + union-attr |
| 23 | scripts.benchmark_latency | 3 | dict 타입 좁히기 3건 |
| 24 | scripts.restore_from_parquet | 3 | SQLAlchemy insert 3건 |
| 25 | src.app.services.kb_builder | 3 | 운영 KB None/할당 3건 |
| 26 | src.rag.llm | 3 | Gemini API 인자 3건 |
| 27 | scripts.analyze_servc_error_concentration | 4 | scipy banded 4건 |
| 28 | scripts.benchmark_arq_container | 4 | async 타입 + ignore |
| 29 | scripts.measure_predict_rss | 4 | ignore 제거 + index 3건 |
| 30 | scripts.orca_metrics_ledger | 4 | ignore 3건 + no-redef |
| 31 | scripts.orca_trust_worktree | 4 | 플랫폼 분기 stub |
| 32 | src.app.services.collector_service | 4 | 운영 None 가드 4건 |
| 33 | scripts.benchmark_sse_gate | 5 | object 인덱싱 5건 |
| 34 | scripts.eval_servc_interval_width | 5 | LGBM params 타입 선언 |
| 35 | scripts.eval_servc_interval_width_by_group | 5 | LGBM params 타입 선언 |
| 36 | scripts.ablation_servc_features | 6 | LGBM kwargs 6건 |
| 37 | scripts.orca_model_router | 6 | ignore + attr-defined |
| 38 | src.tasks.automation_tasks | 6 | Arq 시그니처 6건 |
| 39 | scripts.diagnose_holdout_serving_gap | 7 | LGBM kwargs 7건 |
| 40 | scripts.eval_servc_prediction_interval | 7 | LGBM + assignment 7건 |
| 41 | scripts.eval_servc_rolling_institution | 7 | LGBM kwargs 7건 |
| 42 | src.ml.trainer | 8 | 운영 LGBM + 래퍼 8건 |
| 43 | src.ml.model_registry | 8 | 래퍼 Union/Protocol 8건 |
| 44 | scripts.eval_servc_participant_effect | 8 | LGBM kwargs 8건 |
| 45 | scripts.eval_servc_year_holdout | 8 | LGBM kwargs 8건 |
| 46 | scripts.segment_servc_models | 8 | LGBM + return-value 8건 |
| 47 | scripts.benchmark_provenance | 9 | dict-item 6건 집중 |
| 48 | scripts.eval_servc_excess_target | 15 | LGBM kwargs 15건 |
| 49 | scripts.eval_servc_flag_features | 15 | LGBM kwargs 15건 |
| 50 | scripts.eval_servc_regime_lwlt_levels | 15 | LGBM kwargs 15건 |
| 51 | scripts.eval_servc_quantile_alpha | 16 | float(object) 16건 |
| 52 | scripts.measure_servc_split_variance | 16 | float(object) 16건 |
| 53 | scripts.eval_servc_candidates_unbiased | 16 | LGBM + numpy 16건 |
| 54 | scripts.eval_servc_refit_unbiased | 18 | LGBM + numpy 18건 |
| 55 | src.app.main | 20 | FastAPI kwargs 설계 변경; 최후순위 |

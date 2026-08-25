# mypy 부채 현황 및 제거 계획 (mypy_debt_reduction)

> **작성일**: 2026-08-25
> **버전**: v1.0.0
> 이 문서는 mypy 전역 `disable_error_code` 를 제거하고 모듈별 `[[tool.mypy.overrides]]` 로 좁힌 뒤의 남은 부채를 기록합니다. 수치는 전부 `uv run mypy src/ scripts/` 를 직접 실행해 얻은 실측값입니다.

---

## 1. 배경과 목표

`pyproject.toml` 의 `[tool.mypy]` 에 `disable_error_code = ["assignment", "arg-type"]` 가 전역으로 설정되어 있어, 이미 통과하는 모듈까지 이 두 검사가 적용되지 않았습니다.

- **변경**: 전역 `disable_error_code` 를 제거하고, 실제로 오류가 나는 모듈에만 `[[tool.mypy.overrides]]` 로 해당 오류 코드를 좁혀 끕니다.
- **원칙**: 오류가 없는 모듈에는 override 를 붙이지 않습니다. `warn_unused_ignores` 취지에 따라 부채가 보이지 않게 하지 않습니다.
- **현재 상태**: `uv run mypy src/ scripts/` 오류 0. override 는 전부 개별 파일 단위(`module` 목록에 파일명 명시)이며, `scripts.*` 나 `src.*` 같은 광역 패턴은 사용하지 않습니다.

### 측정 전제

`assignment` 와 `arg-type` 을 전역에서 끈 상태(과거 설정)와 동일 소스로 재측정하면 다음 값이 나옵니다.

| 항목 | 값 |
| --- | --- |
| 오류 파일 수 | 55개 (총 194개 소스 중) |
| 총 오류 수 | 298건 |
| 코드별 분포 | arg-type 218, assignment 21, attr-defined 16, index 9, unused-ignore 7, dict-item 6, type-var 4, return-value 3, operator 3, call-overload 3, misc 2, list-item 2, method-assign 2, union-attr 1, no-redef 1 |
| scripts/ 분포 | 242건 |
| src/ 분포 | src/app 21, src/ml 16, src/app/services 10, src/tasks 6, src/rag 3 |
| 최다 파일 | src/app/main.py 20, scripts/eval_servc_refit_unbiased.py 18, scripts/eval_servc_quantile_alpha.py 16, scripts/eval_servc_candidates_unbiased.py 16, scripts/measure_servc_split_variance.py 16 |

---

## 2. override 목록 (모듈 / 오류 코드 / 실측 건수)

아래는 `pyproject.toml` 에 등록한 override 와 그 대상이 된 실측 오류입니다. 각 `disable_error_code` 는 해당 모듈에서 실제로 발생한 코드만 담고 있습니다.

### 2.1 arg-type 만 (159건)

| 모듈 | arg-type 건수 |
| --- | ---: |
| src.app.main | 20 |
| scripts.eval_servc_quantile_alpha | 16 |
| scripts.measure_servc_split_variance | 16 |
| scripts.eval_servc_excess_target | 15 |
| scripts.eval_servc_flag_features | 15 |
| scripts.eval_servc_regime_lwlt_levels | 15 |
| scripts.eval_servc_candidates_unbiased | 14 |
| scripts.eval_servc_refit_unbiased | 14 |
| scripts.eval_servc_participant_effect | 8 |
| scripts.eval_servc_year_holdout | 8 |
| scripts.diagnose_holdout_serving_gap | 7 |
| scripts.eval_servc_rolling_institution | 7 |
| scripts.ablation_servc_features | 6 |
| scripts.eval_servc_interval_width | 5 |
| scripts.eval_servc_interval_width_by_group | 5 |
| scripts.analyze_servc_error_concentration | 4 |
| src.app.services.collector_service | 4 |
| scripts.benchmark_latency | 3 |
| scripts.eval_servc_api_path | 1 |
| scripts.eval_servc_interval_by_group | 1 |
| src.app.services.home_context | 1 |
| src.app.services.tools.trend_analyzer | 1 |
| src.app.api.v1.chatbot | 1 |

override 설정:
```toml
[[tool.mypy.overrides]]
module = [
    "scripts.ablation_servc_features",
    "scripts.analyze_servc_error_concentration",
    "scripts.benchmark_latency",
    "scripts.diagnose_holdout_serving_gap",
    "scripts.eval_servc_api_path",
    "scripts.eval_servc_excess_target",
    "scripts.eval_servc_flag_features",
    "scripts.eval_servc_interval_by_group",
    "scripts.eval_servc_interval_width",
    "scripts.eval_servc_interval_width_by_group",
    "scripts.eval_servc_participant_effect",
    "scripts.eval_servc_quantile_alpha",
    "scripts.eval_servc_regime_lwlt_levels",
    "scripts.eval_servc_rolling_institution",
    "scripts.eval_servc_year_holdout",
    "scripts.measure_servc_split_variance",
    "src.app.api.v1.chatbot",
    "src.app.main",
    "src.app.services.collector_service",
    "src.app.services.home_context",
    "src.app.services.tools.trend_analyzer",
]
disable_error_code = ["arg-type"]
```

### 2.2 assignment 만 (10건)

| 모듈 | assignment 건수 |
| --- | ---: |
| src.ml.model_registry | 8 |
| scripts.audit_servc_rawdata_regime_scan | 1 |
| src.app.services.conversation_state | 1 |

### 2.3 arg-type + assignment (29건)

| 모듈 | arg-type | assignment |
| --- | ---: | ---: |
| src.tasks.automation_tasks | 3 | 3 |
| src.ml.trainer | 7 | 1 |
| src.app.services.kb_builder | 1 | 2 |
| src.rag.llm | 2 | 1 |
| scripts.eval_servc_prediction_interval | 6 | 1 |
| scripts.arq_gate | 1 | 1 |

### 2.4 그 외 코드 조합 (100건)

| 모듈 | 비활성 오류 코드 | 건수 |
| --- | --- | ---: |
| scripts.benchmark_provenance | arg-type, dict-item, operator | 9 |
| scripts.eval_servc_refit_unbiased | arg-type, attr-defined, type-var | 18 |
| scripts.eval_servc_candidates_unbiased | arg-type, attr-defined, type-var | 16 |
| scripts.segment_servc_models | arg-type, return-value | 8 |
| scripts.benchmark_sse_gate | index | 5 |
| scripts.measure_predict_rss | index, unused-ignore | 4 |
| scripts.orca_trust_worktree | attr-defined | 4 |
| scripts.orca_model_router | attr-defined, return-value, unused-ignore | 6 |
| scripts.orca_metrics_ledger | no-redef, unused-ignore | 4 |
| scripts.orca_level1_gate | union-attr, unused-ignore | 2 |
| scripts.restore_from_parquet | arg-type, list-item | 3 |
| scripts.compare_servc_models_by_group | assignment, method-assign | 2 |
| scripts.compare_servc_models_paired | assignment, method-assign | 2 |
| scripts.audit_model_inventory | operator, return-value | 2 |
| scripts.benchmark_arq_container | arg-type, call-overload, misc, unused-ignore | 4 |
| scripts.benchmark_arq_throughput | call-overload | 1 |
| scripts.eval_servc_ensemble_headroom | call-overload | 1 |
| scripts.eval_servc_inst_clsfc_cross | operator | 1 |
| scripts.diagnose_serving_vs_holdout_model | attr-defined, type-var | 2 |
| scripts.benchmark_rag_segments | attr-defined | 1 |
| scripts.import_data_assets | index | 1 |
| scripts.repair_contract_method | attr-defined | 1 |
| scripts.run_p9_sse_parallel_bench | attr-defined | 1 |
| scripts.run_p9_sse_rebaseline | attr-defined | 1 |
| scripts.summarize_worker_done | unused-ignore | 1 |

> **unused-ignore 주의**: 위 모듈 중 `unused-ignore` 를 끈 항목은 소스에 남은 `# type: ignore` 주석이 코드 비활성화로 인해 미사용이 되어 발생한 것입니다. 소스 수정 없이 오류 0 을 유지하려면 해당 코드를 함께 꺼야 합니다. 나중에 해당 `# type: ignore` 주석을 제거하면 `unused-ignore` 를 비활성 목록에서 뺄 수 있습니다.

---

## 3. 총괄 요약 (실측 기준)

| 오류 코드 | 전체 실측 | override 로 끈 건수 | 잔여 |
| --- | ---: | ---: | ---: |
| arg-type | 218 | 218 | 0 |
| assignment | 21 | 21 | 0 |
| attr-defined | 16 | 16 | 0 |
| index | 9 | 9 | 0 |
| unused-ignore | 7 | 7 | 0 |
| dict-item | 6 | 6 | 0 |
| type-var | 4 | 4 | 0 |
| return-value | 3 | 3 | 0 |
| operator | 3 | 3 | 0 |
| call-overload | 3 | 3 | 0 |
| misc | 2 | 2 | 0 |
| list-item | 2 | 2 | 0 |
| method-assign | 2 | 2 | 0 |
| union-attr | 1 | 1 | 0 |
| no-redef | 1 | 1 | 0 |
| **합계** | **298** | **298** | **0** |

`uv run mypy src/ scripts/` 결과: **Success, no issues found (194 source files)**.

---

## 4. 다음 제거 순서와 근거

override 를 없애는 순서는 "오류 수가 적고, 원인이 한두 줄에 국한되며, 소스 수정만으로 해결 가능한 것"부터 시작합니다. 소스 타입 보강은 별도 Task 로 분리 예정입니다.

1. **unused-ignore 7건** (scripts.summarize_worker_done, orca_level1_gate, orca_metrics_ledger, orca_model_router, measure_predict_rss, benchmark_arq_container)
   - 근거: 전부 미사용 `# type: ignore` 주석 하나 제거로 해결됩니다. 해당 주석은 더 이상 오류를 억제하지 않는 낡은 것입니다. 주석만 제거하면 `unused-ignore` 를 비활성 목록에서 뺄 수 있고, 나머지 오류 코드만 남습니다.
2. **단일 파일 단발 오류** (1건짜리 모듈들: eval_servc_api_path, eval_servc_interval_by_group, eval_servc_inst_clsfc_cross, eval_servc_ensemble_headroom, benchmark_arq_throughput, benchmark_rag_segments, import_data_assets, repair_contract_method, run_p9_sse_parallel_bench, run_p9_sse_rebaseline, src.app.api.v1.chatbot, src.app.services.home_context, src.app.services.tools.trend_analyzer, src.app.services.conversation_state, scripts.audit_servc_rawdata_regime_scan)
   - 근거: 파일당 1건이라 타입 주석 한 줄 보강으로 override 자체를 제거할 수 있습니다. 특히 src/ 에서 1건짜리 3개(src.app.api.v1.chatbot, home_context, conversation_state)는 운영 코드라 우선입니다.
3. **arg-type 218건 중 일부**
   - 근거: 대부분 `LGBMRegressor(**params)` 류 키워드 언패킹과 `float(x)` / `int(x)` 변환이 `object` 를 받는 패턴입니다. `dict[str, float]` 등으로 값 타입을 좁히면 한 파일의 오류 다수가 함께 사라지는 구조라, 파일 단위 효과가 큽니다. 다만 `src.app.main`(20건)은 FastAPI 생성자 키워드 언패킹이라 근본 수정이 필요해 후순위로 둡니다.
4. **attr-defined / index / dict-item 등** (orca_trust_worktree, benchmark_provenance 등)
   - 근거: 플랫폼 분기(`msvcrt` 등)와 타입 축소가 얽혀 있어 단순 보강보다 리팩터링이 필요합니다. 마지막에 처리합니다.

> **우선순위 원칙**: `src/` 운영 코드(총 56건)를 `scripts/`(총 242건)보다 먼저 정리합니다. 운영 경로 타입 안전성이 서비스 품질에 직접 영향을 주기 때문입니다. 그중 `src.app` 과 `src.app.services` 가 대부분입니다.

---

## 5. 검증 기록

| 검증 | 결과 |
| --- | --- |
| `uv run mypy src/ scripts/` | 오류 0 (194 source files) |
| `uv run ruff check src/ scripts/` | 통과 |
| `uv run pytest tests/ -q -m 'not data_assets'` | 2049 passed, 6 skipped |
| `python3 scripts/validate_agent_rules.py --quiet` | 통과 (12/12) |

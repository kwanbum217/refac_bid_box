# mypy mixed override 블록 현황 (2026-08-26)

> **갱신**: task_0806b3051833 + remediation (task_3d7bb40a0d2e) 후

---

## task_0806b3051833에서 제거된 블록 (4개)

1. `src.ml.model_registry` — assignment
2. arg-type+assignment 묶음 — `kb_builder`, `automation_tasks` (trainer·llm·eval_servc_prediction_interval은 스텁 한계로 override 복원)
3. `scripts.audit_model_inventory` — operator, return-value
4. `scripts.benchmark_arq_container` — arg-type, call-overload, misc, unused-ignore
5. `scripts.benchmark_provenance` — arg-type, dict-item, operator

상세는 `docs/analysis/task_0806b3051833.md` 참조.

---

## task_0806b3051833 remediation에서 복원된 블록 (1개)

| 모듈 | disable_error_code | 사유 |
| --- | --- | --- |
| `scripts.eval_servc_prediction_interval` | arg-type, assignment | LightGBM `**params` 스텁 |
| `src.ml.trainer` | arg-type, assignment | 동일 |
| `src.rag.llm` | arg-type, assignment | google-genai `contents` 스텁 |

---

## 잔여 override 블록 (pyproject.toml)

| 블록 | 모듈 수 | disable_error_code |
| --- | ---: | --- |
| arg-type (eval 스크립트·서비스) | 15 | arg-type |
| eval_servc_prediction_interval, trainer, llm | 3 | arg-type, assignment |
| orca_trust_worktree | 1 | attr-defined |
| benchmark_sse_gate | 1 | index |
| measure_predict_rss | 1 | index, unused-ignore |
| compare_servc_models | 2 | assignment, method-assign |
| diagnose_serving_vs_holdout_model | 1 | attr-defined, type-var |
| eval_servc unbiased | 2 | arg-type, attr-defined, type-var |
| orca_level1_gate | 1 | union-attr, unused-ignore |
| orca_metrics_ledger | 1 | no-redef, unused-ignore |
| orca_model_router | 1 | attr-defined, return-value, unused-ignore |
| restore_from_parquet | 1 | arg-type, list-item |
| segment_servc_models | 1 | arg-type, return-value |

# 수동 재학습 API 최신 main 재구현 계획

> **작성일**: 2026-08-13
> **작업**: Orca Task `task_d75dc4c7a5db` (B2 재학습 API 감사) — 읽기 전용 감사, 코드 구현 없음
> **기준**: `main` `11d302b`, 원격 브랜치 `origin/fix/arq-worker-compose` (`20f5692`, `2d5a0c8`)
> **후속 문서**: [`2026-08-13_branch_audit_report.md`](2026-08-13_branch_audit_report.md) 의 3.1 판정 후속
> **감사 커밋 범위**: 코드·Docker·DB·브랜치 변경 없음. 본 계획 문서만 작성
> **이행 결과**: 후속 Task `task_980457255d6e`에서 `4a03f94`로 9파일 최소 재구현 완료

---

## 1. 판정 요약

| 항목 | 판정 | 근거 |
| --- | --- | --- |
| `2d5a0c8` (Compose Arq worker) | **유지 불필요 (흡수 완료)** | main 은 worker 서비스 + `command: ["arq", "src.tasks.worker.WorkerSettings"]` 를 Meilisearch·CORS·healthcheck 등 더 발전된 계약으로 보유. `tests/test_worker_compose.py` 4개 테스트 존재 |
| `20f5692` (수동 재학습 API) | **재구현 완료** | 감사 당시에는 네 계약이 모두 없었으나 후속 `4a03f94`에서 최신 main에 수동 재적용 |
| 브랜치 전체 병합 | **금지** | merge-base `8d13dad` 가 main(`11d302b`)보다 오래됨. `.env.example`/`docker-compose.yml`/`Makefile` 은 main 과 구조가 달라 충돌·퇴행 위험. `20f5692` 만 최신 main 기준으로 재작성 |

---

## 2. 존재 여부 코드 확인 (측정 명령·결과)

| 확인 항목 | 명령 | 결과 |
| --- | --- | --- |
| `model_retrain` 액션 | `git grep -c "model_retrain" 11d302b -- src tests` | **부재** (docs 만 2건) |
| `/run/retrain` 라우터 | `git show 11d302b:src/app/api/v1/automation.py` | **부재** — `run/collect-bids`·`run/update-kb`·`run/predict`·`run/manual-full` 4개만 존재 |
| `retrain_only` run_mode | `git show 11d302b:src/tasks/run_mode_matrix.py` | **부재** — `RUN_MODE_STEP_ORDER` 에 없어 `get_run_mode_steps("retrain_only")` 가 `ValueError` |
| `manual_retrain_task` | `git show 11d302b:src/tasks/worker.py` | **부재** — functions 8개, `manual_retrain_task` 없음 |
| Arq worker 계약 | `git show 11d302b:src/tasks/worker.py` | `WorkerSettings`: functions 8개, cron 3건(개발 02:00·야간 02:00·주간 재학습 월 03:00), `job_timeout=1800`, `max_jobs=4`. `run_retrain_pipeline_task` 는 이미 등록됨 |
| 재학습 파이프라인 기반 | `git cat-file -e 11d302b:src/tasks/retrain_task.py` | 존재. `run_retrain_pipeline_task(ctx, trigger_source="manual", ...)` — `_step_retrain` 의 `({}, trigger_source="manual_api")` 호출과 시그니처 호환 |
| 테스트 | `git grep -n "retrain" 11d302b -- tests/test_automation_api.py tests/test_automation_bundle_parity.py` | **부재** (재학습 단위 테스트는 `test_champion_resolution.py` 등 파이프라인 계층만 존재) |
| 문서 | `git grep -n "retrain_only" 11d302b -- docs/design/REFACTORING_DESIGN.md` | **567행에 `retrain_only : (retrain,) ★ 신규` 이미 설계 문서화됨** — 구현 후 문서 추가 갱신 불필요 |

---

## 3. 유지/폐기 파일별 판단 (20f5692 대상)

| 파일 | 판단 | 이유 |
| --- | --- | --- |
| `src/app/api/v1/automation.py` | **재적용** | `run_manual_full_api` 아래 `/run/retrain` 라우터 + docstring 표 1행. `_run_automation_by_action` 시그니처 main 과 동일 |
| `src/app/services/action_catalog.py` | **재적용** | `model_retrain` 액션 11행. `AutomationAction` dataclass·`STAGING_PIPELINE_ID` main 과 동일. **CAPABILITY_REGISTRY 는 `_build_pipeline_capabilities()` 가 ACTION_CATALOG 에서 자동 파생** → 별도 레지스트리 수정 불필요 |
| `src/app/services/automation_orchestrator.py` | **재적용** | `RUN_MODE_TASKS` 에 `"retrain_only": "manual_retrain_task"` 1행 |
| `src/tasks/automation_tasks.py` | **재적용 (컨텍스트 주의)** | `_step_retrain`(2-tuple 반환)·`STEP_RUNNERS["retrain"]`·`manual_retrain_task`. main 의 `run_automation_pipeline` 은 2/3-tuple 결과를 모두 처리하므로 호환 |
| `src/tasks/run_mode_matrix.py` | **재적용** | `"retrain_only": ("retrain",)` 1행. 주의: main 의 `refresh_data`/`manual_full`/`nightly_schedule` 은 `search` 스텝 포함 — **기존 행은 건드리지 말 것** |
| `src/tasks/worker.py` | **재적용** | import + `functions` 에 `manual_retrain_task` 2행. main 의 `development_data_refresh_task`·cron 3건은 **유지** (브랜치처럼 제거 금지) |
| `tests/test_automation_api.py` | **재적용** | `test_manual_retrain_requires_confirmation` 1건 (confirmation 토큰 → confirm → `manual_retrain_task` enqueue 검증) |
| `tests/test_automation_bundle_parity.py` | **재적용** | `_recording_runners` 튜플에 `"retrain"` 추가 + `test_manual_retrain_runs_only_retrain_step` 1건 |
| `tests/test_chatbot_core.py` | **재적용** | `EXPECTED_CAPABILITIES` 에 `"model_retrain"` + run_mode 루프 튜플에 추가 |
| `docker-compose.yml`, `Makefile`, `.env.example` | **폐기** | main 이 더 발전된 형태 보유. 재적용 금지 |
| `tests/test_worker_compose.py` | **폐기** | main 에 동일 파일(4개 테스트, 확장판) 존재 |
| `docs/ops/environment_variables.md`, `docs/ops/cross_platform_guide.md`, `docs/changelogs/work_log.md` | **폐기** | main 문서가 더 최신. 재적용 시 퇴행 |

---

## 4. 최신 main 적용 최소 diff (9파일, +90/-2 행)

| 순서 | 파일 | 변경량 | 비고 |
| --- | --- | --- | --- |
| 1 | `src/tasks/run_mode_matrix.py` | +1 | `retrain_only` 키 추가 |
| 2 | `src/app/services/action_catalog.py` | +11 | `model_retrain` 액션 |
| 3 | `src/app/services/automation_orchestrator.py` | +1 | `RUN_MODE_TASKS` 매핑 |
| 4 | `src/tasks/automation_tasks.py` | +23 | `_step_retrain`·`STEP_RUNNERS`·`manual_retrain_task` |
| 5 | `src/tasks/worker.py` | +2 | import·functions 등록 |
| 6 | `src/app/api/v1/automation.py` | +11 | `/run/retrain` 라우터 |
| 7 | `tests/test_automation_api.py` | +21 | confirm 흐름 테스트 |
| 8 | `tests/test_automation_bundle_parity.py` | +18/-1 | parity 테스트 |
| 9 | `tests/test_chatbot_core.py` | +2/-1 | capability 목록 갱신 |

> **적용 방식**: cherry-pick `20f5692` 금지 — `run_mode_matrix.py`(search 스텝 컨텍스트)·`automation_tasks.py`(main 에 `_step_search` 존재)·`worker.py`(development 태스크)에서 충돌이 확정적. 위 9파일에 원본 변경을 수동으로 새 컨텍스트에 맞게 재작성.

**검증 절차**: `uv run pytest tests/test_automation_api.py tests/test_automation_bundle_parity.py tests/test_chatbot_core.py tests/test_worker_compose.py` → 전량 통과 후 전체 스위트(현행 963건) 회귀 확인 → `python scripts/validate_agent_rules.py` → `git diff --check` → 커밋·병합.

---

## 5. 예상 위험

| 위험 | 내용 | 대응 |
| --- | --- | --- |
| cherry-pick 충돌 | merge-base `8d13dad` 스테일로 3개 파일에서 충돌 | 수동 재작성(4장 절차)으로 회피. 기존 행(`search` 스텝, cron, development 태스크)은 보존 |
| `_step_retrain` 결과 계약 | 2-tuple 반환. main `run_automation_pipeline` 의 `len(res)==2` 분기에서 `metrics["status"]` 로 상태 결정 — `retrain` outcome 의 `status` 키 필수 | `_step_retrain` 은 outcome dict 그대로 반환하므로 호환. parity 테스트가 `calls == ["retrain"]` 로 검증 |
| 재학습 E2E 의존성 | `retrain` 스텝은 실제 DB·feature store 가 있어야 성공. 테스트는 mock/recording runner 사용 | 운영 E2E 는 데이터 자산 준비 후 별도 실행. API 계층 테스트만으로 병합 게이트 통과 |
| CAPABILITY 목록 | 레지스트리 자동 파생이라 소스 누락 시 `test_chatbot_core.py` 실패로 즉시 노출 | `model_retrain` 액션 등록과 테스트 갱신을 한 커밋으로 묶음 |
| 고비용 가드 | `high_cost=True` → confirmation 토큰 필수. `_enqueue_arq_job` 은 confirm 후에만 호출 | 기존 `manual_full` 흐름과 동일. 테스트가 `mock_enqueue.assert_not_called()` 로 가드 검증 |

---

## 6. 감사 시점 판단과 후속 이행

감사 시점에는 구현 Task가 없고 스테일 브랜치의 단순 병합이 위험해 다음 세션 이행을
권고했습니다. 코디네이터가 9파일 범위를 직접 검수한 뒤 같은 Run에 후속 Task를
추가했고, DeepSeek V4 Flash max 워커가 브랜치를 병합하지 않고 최신 코드에
재작성했습니다.

| 항목 | 결과 |
| --- | --- |
| 후속 Task | `task_980457255d6e` |
| 구현 커밋 | `4a03f94` |
| 표적 테스트 | 38 passed |
| 격리 트리 전체 검사 | 961 passed, 4 skipped, 자산 부재 2 failed |
| 자산 실패 대조 | 변경을 stash한 기준 상태에서도 같은 2건 실패 |
| 주 저장소 전체 회귀 | 965 passed, 2 skipped |

격리 트리의 실패는 `v25/model.bin`과 ChromaDB 컬렉션이 복제되지 않는 알려진
예외입니다. 자산이 있는 주 저장소에서 전체 회귀 965건을 통과했습니다.

---

## 7. 검증 결과

| 항목 | 결과 |
| --- | --- |
| `uv run python scripts/validate_agent_rules.py` | 통과 |
| `git diff --check` | 오류 없음 |
| 커밋 | `docs: 수동 재학습 API 재구현 계획을 기록한다` — 본 문서만 add |
| 푸시 | `kwanbum217/retrain-api-replan` (main `11d302b` 기준) |

후속 구현은 `4a03f94`로 같은 브랜치에 푸시됐고, 코드 9파일 외에는 변경하지
않았습니다.

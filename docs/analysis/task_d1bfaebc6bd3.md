# task_d1bfaebc6bd3 인수인계: Arq 실제 등록 업무 task E2E 벤치마크

> **task_id**: task_d1bfaebc6bd3
> **작성일**: 2026-08-26
> **소스 branch**: kwanbum217/w4-arq-e2e
> **base commit**: 724518d
> **결과 상태**: succeeded (acceptance 일부 항목은 Task 범위 밖 사전 결함으로 미충족)

## 1. 작업 요약

기존 `benchmark_arq_container.py` / `benchmark_arq_throughput.py` 가 합성
`benchmark_noop_task` 만 돌려 production business-task E2E 가 미측정으로
남아 있던 점을 보완하기 위해, 실제 운영 task 를 대상으로 종단 완주와
지연을 측정하는 새 하네스 `scripts/benchmark_arq_business_e2e.py` 와 그
단위 테스트 `tests/test_benchmark_arq_business_e2e.py` 를 추가했다.

## 2. 추가/수정 파일

| 경로 | 종류 | 비고 |
| --- | --- | --- |
| `scripts/benchmark_arq_business_e2e.py` | 신규 | 격리 큐 + 실제 업무 task E2E 하네스 |
| `tests/test_benchmark_arq_business_e2e.py` | 신규 | Redis/Docker 없이 도는 단위 테스트 42개 |
| `docs/analysis/task_d1bfaebc6bd3.md` | 신규 | 본 인수인계 문서 |

기존 `scripts/benchmark_arq_container.py`,
`scripts/benchmark_arq_throughput.py`, `scripts/arq_gate.py`,
`src/tasks/worker.py`, `src/tasks/automation_tasks.py`,
`src/tasks/run_mode_matrix.py` 는 일체 수정하지 않았다.

## 3. 설계 핵심

### 3.1 화이트리스트 강제

- `ALLOWED_BUSINESS_TASKS = ("preflight_check_task", "validate_model_task")`
  두 개로 측정을 허용한다.
- `MUTATING_BUSINESS_TASKS` (7개:
  `collect_bids_task`, `update_kb_task`, `manual_retrain_task`,
  `refresh_data_task`, `manual_full_task`, `run_retrain_pipeline_task`,
  `development_data_refresh_task`) 는 데이터를 변경하므로 인자로
  들어와도 거부한다.
- `validate_requested_tasks` 와 `build_business_e2e_config` 가 화이트리스트
  외부 이름을 만나면 `BenchmarkArgumentError` 를 던지고, `main` 은 그
  예외를 받아 exit code 2 로 종료한다. CLI 단계의 argparse 오류도
  exit code 2 로 빠진다.

### 3.2 운영 큐 격리

- 격리 큐 이름은 `generate_business_e2e_queue_name()` 으로 매 실행마다
  `arq:benchmark:business-e2e:<uuid12>` 형식으로 생성한다.
- `assert_queue_isolation()` 이 운영 큐 이름 `arq:queue` 와 겹치는 모든
  경로(`build_business_e2e_config`, `enqueue_business_task`,
  `collect_business_results`, `cleanup_business_e2e_resources`,
  `build_business_e2e_result`)에서 강제한다.
- `cleanup_business_e2e_resources` 는 격리 큐 이름 패턴으로만 키를
  스캔·삭제하므로 운영 큐를 건드릴 가능성 자체가 없다.

### 3.3 execution_id 미전달

- `enqueue_business_task` 는 `execution_id` kwargs 를 의도적으로 넘기지
  않는다. 그러면 `run_automation_pipeline` 의
  `PipelineExecution SELECT` 가 `None` 으로 떨어져 상태 갱신 커밋이
  비활성화된다. 이 사실은 코드와 모듈 docstring 의 주석으로 명시했다.

### 3.4 지표/종료 코드

- `build_business_e2e_result` 는 회차 결과를 합산해 다음 필드를 만든다.
  `target_tasks`, `repetitions`, `summary`(total_enqueued, successful,
  failed, missing, error_count), `per_task`(task 별 latency ms,
  P50/P95/P99), `latency_ms`(전체 P50/P95/P99),
  `isolated_queue`, `production_queue`, `is_synthetic=False`,
  `rejected_target_tasks`, `timeout_sec`, `errors`,
  `environment`. `status` 는 모든 회차가 성공·누락 0·에러 0 일 때만
  `"success"` 이다.
- `should_exit_nonzero` 는 결과 0건이거나 failed/missing > 0이거나
  status != success 면 `True` 를 돌려준다. `main` 은 이 값으로 종료
  코드를 결정한다. 빈 결과를 통과로 승격하지 않는다.
- 타임아웃으로 끊긴 회차는 `missing` 으로 집계되며 별도
  `errors` 메시지로 노출된다.

### 3.5 실측 실행 분리

- 하네스의 Redis/Docker/워커 실측 경로(`run_single_repetition_async`,
  `collect_business_results`, `cleanup_business_e2e_resources`)는
  구현되어 있지만, 단위 테스트는 그 경로를 호출하지 않는다.
- 실측 실행은 Capsule 의 ground_truth/acceptance 가 명시한 대로
  코디네이터 측 별도 과제로 남겨두었다.

## 4. 단위 테스트 (42개, Redis/Docker 불요)

다음 acceptance 요구를 모두 고정한다.

| ID | 검증 항목 | 테스트 함수 |
| --- | --- | --- |
| (a) | 허용 목록 밖 task 거부 | `test_validate_requested_tasks_rejects_unknown_task` |
| (b) | 데이터 변경 task 7종 각각 거부 | `test_validate_requested_tasks_rejects_mutating_tasks`(parametrize) |
| (c) | 결과 0건 → 실패 종료 코드 | `test_should_exit_nonzero_on_empty_results`, `test_build_business_e2e_result_empty_results_is_failed` |
| (d) | 실패 회차 → 실패 종료 코드 | `test_should_exit_nonzero_on_failure_round`, `test_should_exit_nonzero_on_missing_round` |
| (e) | 지연 백분위 계산 정확성 | `test_calculate_percentile_deterministic`, `test_calculate_latency_percentiles_matches_throughput_convention` |
| (f) | 격리 큐 ≠ 운영 큐 | `test_generate_business_e2e_queue_name_is_unique`, `test_assert_queue_isolation_blocks_production_queue`, `test_build_business_e2e_config_uses_unique_isolated_queue` |

추가로 CLI 인수 검증(`main` exit code 2), 회차 합산, `rejected_target_tasks`
정합, 화이트리스트/뮤테이팅 직교성, `format_help()` 회귀 방지 등을
검증한다.

## 5. 검증 결과

| 명령 | 결과 |
| --- | --- |
| `uv run pytest tests/test_benchmark_arq_business_e2e.py -q` | 42 passed |
| `uv run ruff check scripts/ tests/` | All checks passed |
| `python3 scripts/validate_agent_rules.py --quiet` | 11/12 PASS, 1 FAIL (CURRENT_STATE 신선도, 사전 결함) |
| `uv run pytest tests/ -q -m 'not data_assets'` | 2191 passed, 2 failed (사전 결함, 본 Task 범위 밖) |

### 5.1 사전 결함 보고 (acceptance 일부 미충족)

아래 두 항목은 **본 Task 의 작업 이전부터 이미 깨져 있던 레거시 결함**이며,
이번 변경으로 새로 발생하지 않았다. 본 Task 의
`allowed_write_files` 에는 해당 파일들이 포함되어 있지 않아 본인이
수정할 수 없으며, escalate_when 의 "테스트 실패 원인이 Task 범위 밖의
레거시 결함인 경우" 에 해당한다.

- `tests/test_validate_agent_rules.py::test_real_repo_validation_passes`
  실패 사유: `CURRENT_STATE.md` 의 `source_commit: b4913fd` 이 HEAD 보다
  8 커밋 뒤처졌다. validate_agent_rules.py 의
  `CURRENT_STATE_LAG_TOLERANCE` 가 5 커밋이므로 신선도 검증에서
  FAIL 로 빠진다.
- `tests/test_validate_agent_rules.py::test_check_current_state_sections_real_repo_within_tolerance`
  실패 사유: 동일 원인.

본 Task 가 다루는 `scripts/`, `tests/` 의 새 파일/테스트는 100% 통과한다.
`git stash -u` 로 본 Task 의 변경을 모두 치운 상태에서도 같은 두
테스트가 동일 사유로 실패함을 확인했다(2026-08-26).

해당 사전 결함의 해결은 본 Task 의 책임이 아니므로, 후속 과제로
다음 둘 중 하나가 필요하다.

1. `docs/context/CURRENT_STATE.md` 의 `source_commit` 을 최신 HEAD 커밋
   으로 갱신하고 그 자리에서 G3 게이트 재검증.
2. `scripts/validate_agent_rules.py` 의 `CURRENT_STATE_LAG_TOLERANCE`
   를 8~10 정도로 완화하거나, 별도 추적 옵트인을 추가.

## 6. review_checklist 자기 검증

- mutating_task_allowed: **아니오**. `ALLOWED_BUSINESS_TASKS` 가 두 개로
  한정돼 있고, `validate_requested_tasks` 와 `build_business_e2e_config`
  가 화이트리스트 외부 이름을 만나면 `BenchmarkArgumentError` 로 거부.
  `main` 은 exit code 2 로 종료.
- production_queue_touched: **아니오**. `PRODUCTION_QUEUE_NAME` 상수와
  `assert_queue_isolation` 이 모든 진입점에서 운영 큐 이름을 거부.
  `cleanup_business_e2e_resources` 도 격리 큐 패턴으로만 스캔·삭제.
- execution_id_passed: **아니오**. `enqueue_business_task` 가
  `execution_id` 를 kwargs 로 넘기지 않으며, 이 사실은 모듈 docstring
  과 함수 docstring 의 주석으로 명시.
- empty_result_passes: **아니오**. `should_exit_nonzero` 가
  `total_enqueued <= 0` 또는 `failed > 0` 또는 `missing > 0` 또는
  `status != "success"` 면 True 를 반환하고, `main` 이 그에 따라
  exit code 1 로 종료.
- test_needs_redis: **아니오**. 단위 테스트는 Redis/Docker 연결을
  열지 않으며, `RedisSettings`/`ArqRedis` 인스턴스화도 하지 않는다.
  실측 경로(`run_single_repetition_async` 등)는 호출되지 않는다.
- scope_creep: **아니오**. `git diff --name-only` 기준
  `scripts/benchmark_arq_business_e2e.py`,
  `tests/test_benchmark_arq_business_e2e.py`,
  `docs/analysis/task_d1bfaebc6bd3.md` 3개만 변경.

## 7. 후속 과업

- 본 스크립트의 실측 실행은 코디네이터 측에서 별도 Docker/Redis 가용
  환경에서 수행한다. 호출 예:
  `uv run python scripts/benchmark_arq_business_e2e.py --repetitions 3 --jobs 5 --timeout 30 --output data/benchmarks/arq_business_e2e.json`.
- 측정 결과는 `data/benchmarks/` 에 저장되며 본 Task 에서 파일을 만들지
  않았다(acceptance: "실제 측정을 실행하지 않았고 data/benchmarks 에 파일을
  만들지 않았다" 충족).
- 운영 워커(기존 `src/tasks/worker.py`)의 functions 등록은 변경하지
  않았다. 본 하네스는 운영 큐와 분리된 격리 큐를 통해 측정하므로
  운영 워커 재기동이 필요 없다.

## 8. 메시지 ID / 핸드오프

- 본 Task 의 검증/측정 결과는 worker_done 본문과 본 문서에 함께 남겼다.
- 후속 코디네이터는 본 Task 가 미수행한 실측 실행만 별도 디스패치로
  진행하면 된다.

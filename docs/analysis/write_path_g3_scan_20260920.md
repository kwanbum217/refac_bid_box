# 쓰기 경로·수집 경로 N+1 질의 및 이벤트 루프 동기 I/O 정적 전수 조사 보고서

> **작성일**: 2026-09-20
> **작성자**: Orca Worker `term_e85bd74d-bd7f-46f7-806d-807fd5bc4f1a` (role: investigator)
> **Task ID**: `task_f895e5e6a4d0`
> **조사 성격**: 정적 코드 전수 조사 (코드 수정, 컨테이너 기동, 벤치마크 실행 미실시)
> **선행 문서**: [`read_path_g3_rescan_20260920.md`](read_path_g3_rescan_20260920.md)

---

## 1. 개요 및 목적

AGENTS.md 는 G3 스택 최적화를 상시 과제로 규정합니다. 2026-09-20 읽기 경로 정적 조사는 쓰기 경로(POST 생성, PUT, DELETE)와 외부 수집 경로를 명시적으로 제외했고, 그 영역은 아직 같은 수준의 조사를 받지 않았습니다.

본 조사는 상태를 바꾸는 API 핸들러(POST, PUT, PATCH, DELETE), 비동기 태스크(Arq), 수집기와 그 경로가 부르는 서비스 계층을 대상으로 다음 두 결함 유형을 정적으로 전수 조사합니다.

- **N+1 질의**: 데이터 규모에 비례해 반복 실행되는 단일 행 단위 SQL 질의
- **이벤트 루프 블로킹 동기 I/O**: `async def` 컨텍스트(ASGI 이벤트 루프 또는 Arq 워커 이벤트 루프)에서 `await` 나 `asyncio.to_thread` 오프로드 없이 실행되는 동기 SQLAlchemy, 동기 Redis, 동기 HTTP, 파일 I/O

코드는 수정하지 않았고, 테스트를 추가하지 않았고, 컨테이너를 기동하지 않았고, 벤치마크를 실행하지 않았습니다. 본 Task 의 산출물은 본 보고서 파일 하나입니다.

---

## 2. 조사 범위 및 분석 방법

### 2.1 정본 경로 불일치 (중요)

정본 사양(Capsule)의 `allowed_read_files` 와 `search_scope.allowed_globs` 는 조사 대상으로 `src/app/tasks/` 와 `src/collectors/` 를 지정합니다. 그러나 실제 저장소에 두 경로는 **존재하지 않습니다.**

| 캡슐이 지정한 경로 | 실제 저장소 상태 | 실제 위치 |
| --- | --- | --- |
| `src/app/tasks/` | 디렉터리 없음 | `src/tasks/` (Arq 워커·크론·태스크 8개 파일) |
| `src/collectors/` | 디렉터리 없음 | `src/app/services/collector_service.py`, `api_collector.py`, `kb_index_sync.py` |

목표 문장이 "비동기 태스크(arq), 수집기(src/collectors)" 를 명시적으로 조사 대상으로 삼으므로, 본 조사는 Arq 태스크 계층을 `src/tasks/**` 로 해석해 **읽기 전용으로** 점검했습니다. 해당 디렉터리는 어떤 파일도 변경하지 않았습니다. 이 해석을 코디네이터에 `orca orchestration ask`(msg_c142ec60db5a)로 질의했으나 540초 대기 후에도 응답이 없어, 캡슐의 목표를 충족하는 방향으로 진행했고 이 사실을 여기에 명시합니다.

수집기 쪽은 실제 위치가 `src/app/services/` 로 캡슐의 허용 범위 안이므로 충돌이 없습니다.

### 2.2 오프로드 정상 경로 규정 (오탐 방지)

Capsule 계약에 따라 다음은 **결함으로 적지 않았습니다.**

- `asyncio.to_thread(...)` 로 명시 오프로드된 동기 호출
- 동기 라우트(`def`)로 선언되어 AnyIO 스레드풀에서 실행되는 핸들러와 그 서비스 체인

### 2.3 조사 대상 계층

1. **API 라우터 (`src/app/api/v1/`)**: 상태 변경 라우트 전량
   - `automation.py` (POST 8종), `evaluations.py` (POST 2, PUT 1, DELETE 2), `accounts.py` (POST 3), `predictions.py` (POST 2), `chatbot.py` (POST 4), `bids.py` (`POST /collect`)
2. **서비스 계층 (`src/app/services/`)**: `collector_service.py`, `api_collector.py`, `automation_orchestrator.py`, `automation_jobs.py`, `automation_callbacks.py`, `automation_responses.py`, `automation_tokens.py`, `kb_builder.py`, `kb_index_sync.py`, `kb_document_builder.py`, `search_index.py`, `ranking_snapshots.py`, `compare_stats_snapshots.py`, `home_context.py`, `dashboard.py`, `mysql_stats_freshness.py`, `plan_executor.py`, `conversation_state.py`, `bid_queries.py`
3. **Arq 태스크 계층 (`src/tasks/`)**: `worker.py`, `automation_tasks.py`, `automation_steps.py`, `scheduled_tasks.py`, `summary_tasks.py`, `retrain_task.py`, `notifier.py`
4. **모델·ML 계층 (`src/app/models/`, `src/ml/`)**: 관계 정의, 특징 단일 공급원 `features.py`, `institution_history.py`, `repeat_history.py`, `monitoring.py`

### 2.4 판정 방법

- 루프 내부 SQL 질의를 정적으로 추적했고, 루프 개수가 데이터 규모에 비례하는지 고정 상수인지 구분했습니다.
- `async def` 함수 본문에서 `to_thread` 없이 실행되는 동기 호출을 추출하고, 그 함수에 도달하는 호출 경로가 이벤트 루프인지 스레드풀인지 판정했습니다.
- 표에 적은 모든 행 번호는 해당 행을 직접 열어 확인했고, 추정으로 적지 않았습니다. 확인하지 못한 것은 5장에 미확인으로 적었습니다.

---

## 3. 식별된 결함 후보 전수 목록

심각도(이벤트 루프 정지 시간 및 질의 증폭 배율) 순으로 정렬한 9건입니다.

| 순번 | 심각도 | 위치 (파일:행) | 형태 | 발생 조건 | 예상 기여 | 측정 방법 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| D1 | 높음 | `src/tasks/summary_tasks.py:22,26` / `:37,40` | 이벤트 루프 블로킹 동기 DB | Arq 워커에서 두 태스크 실행 시 상시 | 수 초 규모 동기 집계·갱신이 워커 루프를 정지 | 태스크 단독 투입 후 loop lag 및 벽시계 비교 |
| D2 | 높음 | `src/tasks/scheduled_tasks.py:226,292,307,361` / `:1205,1219,1293,1309,1397` | 이벤트 루프 블로킹 동기 Redis·DB | 스케줄 태스크 진입·종료 시 상시, catchup 기동 시 | Redis/DB 왕복이 직렬 누적되어 루프 정지 | Redis 지연 주입 후 loop lag·heartbeat 간격 편차 |
| D3 | 중간 | `src/tasks/scheduled_tasks.py:724-737` | 이벤트 루프 동기 CPU 점유 | `ML_DRIFT_MONITOR_ENABLED`(기본 True) 매일 04:00 | 카테고리별 전량 특징 프레임·PSI 계산이 루프 점유 | 구간 타이머 + to_thread 대조군 loop lag |
| D4 | 중간 | `src/app/services/collector_service.py:87-112` | N+1 질의 (카테고리 루프 COUNT) | `start_date` 미지정 수집 시 | 카테고리 4종 기준 최대 8회 COUNT 순차 | 수집 1회의 SQL 카운트·`sql_ms` |
| D5 | 중간 | `src/app/services/ranking_snapshots.py:168-213` | N+1 질의 + 조합별 commit | 야간 스케줄·개발 최신화 성공 후 | 15~30회 집계 질의 + 15회 commit | 조합별 소요·질의 수, commit 병합 대조군 |
| D6 | 낮음 | `src/app/services/collector_service.py:362,385,411,443,469` | 이벤트 루프 동기 세션 연산 | 수집 예외·부분 실패 시에만 | 예외 경로에서 ROLLBACK 왕복 1회, 세션 스레드 공유 위험 | 실패 인위 주입 후 loop lag·세션 상태 계측 |
| D7 | 낮음 | `src/tasks/automation_steps.py:33` | 이벤트 루프 블로킹 동기 DB | G2B serviceKey 미설정 등 수집 error 분기 | 대량 테이블 COUNT 1회가 루프 정지 | serviceKey 미설정 상태로 collect 스텝 실행 |
| D8 | 낮음 | `src/app/services/home_context.py:100-101,115-119` | N+1 질의 (표본·윈도우 루프) | 수집 성공 후 캐시 예열, 캐시 미적중 | 예열 꼬리에서 최대 약 45회 질의 | 예열 구간 질의 수·소요 |
| D9 | 낮음 | `src/tasks/worker.py:293` / `:357` / `scheduled_tasks.py:83,86` | 이벤트 루프 블로킹 동기 Redis | heartbeat 주기마다, 태스크 기동·스케줄 기록마다 | 관측용 Redis 왕복이 주기적으로 루프 정지 | heartbeat 주기 편차, Redis 지연 주입 대조 |

### 3.1 D1 (높음) — 요약 재집계 태스크가 워커 이벤트 루프에서 동기 집계 실행

- **위치**: `src/tasks/summary_tasks.py:22` (`async def rebuild_dataset_summary_task`) 의 `:26` (`summary = rebuild_bid_dataset_summary(db, dataset)`), 그리고 `:37` (`async def refresh_institution_catalog_task`) 의 `:40` (`counts = refresh_institution_name_catalogs(db)`)
- **형태**: Arq 태스크가 `async def` 이고 워커 이벤트 루프에서 실행되는데, 본문의 무거운 동기 SQLAlchemy 집계·갱신을 `asyncio.to_thread` 로 오프로드하지 않고 직접 호출합니다. 같은 저장소의 다른 태스크는 이미 같은 패턴을 `to_thread` 로 처리합니다 (`src/tasks/scheduled_tasks.py:276,279,283,286,289` 및 `:354-358`).
- **발생 조건**: `rebuild_dataset_summary_task` 는 `src/app/services/dashboard.py:385` 의 `enqueue_rebuild_dataset_summary` 를 통해 스냅샷이 낡았을 때마다 등록되므로 수집·조회 직후에, `refresh_institution_catalog_task` 는 매시 크론으로 실행됩니다.
- **예상 기여**: `rebuild_bid_dataset_summary` 는 `bid_announcements`·`bid_results` 전량(현재 운영 규모 300만 행 이상, `docs/context/CURRENT_STATE.md` 의 compare-stats 귀속 측정에서 기관별 상위 10 집계만 2,097ms)을 훑는 집계로 수 초가 걸립니다. 그 시간 동안 워커 루프가 완전히 정지해 같은 워커의 다른 Arq 태스크와 `src/tasks/worker.py:291` 의 heartbeat 루프가 밀리고 `/health/worker` 관측이 공백이 됩니다.
- **측정 방법**: 두 태스크를 Arq 큐에 단독 투입하고 워커 프로세스에서 `asyncio` slow-callback 경고 또는 `loop.time()` 기반 loop lag 를 기록해 태스크 벽시계 시간과 대조합니다. `to_thread` 적용 전후로 동시 실행 태스크의 완료 시각 차이를 비교합니다.

### 3.2 D2 (높음) — 스케줄 진입부의 동기 Redis·DB 호출이 워커 이벤트 루프에서 실행

- **위치**: `src/tasks/scheduled_tasks.py:226` (`acquire_schedule_claim`), `:292`·`:361` (`release_schedule_claim`), `:307` (`acquire_schedule_claim`), 그리고 `run_schedule_catchup_task` 의 `:1282` (`check_schedule_catchup_needed`) → `:1205` (`is_catchup_in_cooldown`), `:1219` (`get_latest_collection_time`), `:1293`·`:1309`·`:1397` (`record_catchup_attempt`)
- **형태**: `async def` 태스크 본문에서 동기 `redis-py` 클라이언트(`client.set(..., nx=True)` = `scheduled_tasks.py:921`, `client.eval(...)` = `:995`, `client.get(...)` = `:1134,1157`)와 동기 SQLAlchemy 조회(`scheduled_tasks.py:1026`)를 `await` 없이 직접 호출합니다. `RedisConnection` 은 동기 클라이언트를 반환합니다 (`src/app/services/automation_tokens.py:57-62` 의 `client.set(key, "1", ex=ttl, nx=True)` 가 같은 계층입니다).
- **발생 조건**: `nightly_schedule_task`·`development_data_refresh_task` 는 진입·성공 종료마다 claim 획득·해제를 수행하고, `run_schedule_catchup_task` 는 워커 기동 시(`src/tasks/worker.py:360`) 실행되며 쿨다운 GET, DB MAX 조회, 원장 SET 2회, 선점 SET 을 직렬로 수행합니다.
- **예상 기여**: Redis 왕복 0.5~3ms(부하 시 수십 ms) 동안 이벤트 루프가 정지합니다. catchup 경로는 최대 5회 왕복이 순차 누적되어 최대 수십 ms 정지하며, 스케줄 태스크는 `worker.py:291` 의 heartbeat 루프와 같은 루프를 공유하므로 관측 공백을 유발합니다.
- **측정 방법**: Redis 에 인위 지연(예: 10ms)을 주입한 뒤 `run_schedule_catchup_task` 와 `nightly_schedule_task` 를 실행해 loop lag 및 heartbeat 간격 편차를 측정하고, `to_thread` 적용 전후를 비교합니다.

### 3.3 D3 (중간) — 드리프트 모니터의 특징 프레임·PSI 계산이 워커 이벤트 루프에서 실행

- **위치**: `src/tasks/scheduled_tasks.py:724-725` (`attach_institution_history`, `attach_repeat_history`), `:726-730` (`to_dict`, `build_feature_frame`, `pd.DataFrame`, `collect_category_levels`, `apply_categorical_dtypes`), `:733` (`check_dataset_drift`)
- **형태**: 바로 위 `:688` 의 `_build_training_dataset_thread` 만 `await asyncio.to_thread(...)` 로 오프로드되고, 그 뒤 전량 프레임 변환과 PSI 계산은 이벤트 루프에서 동기로 실행됩니다. 이것은 소켓 I/O 가 아니라 **동기 CPU 점유**이며, 이벤트 루프를 정지시키는 결과는 같습니다. `src/ml/features.py:441-445` 의 `build_feature_frame` 은 레코드마다 `build_default_feature_map` 을 호출하는 O(N) 순회입니다.
- **발생 조건**: `ML_DRIFT_MONITOR_ENABLED` 가 참(기본값 True)일 때 매일 04:00 실행되며, `CATEGORY_MODEL_NAMES` 카테고리(현재 3종 이상)를 순차 순회합니다.
- **예상 기여**: 모듈 주석 기준 학습 경로에서 773,045행 처리에 3.2초가 걸립니다(`src/ml/institution_history.py` 모듈 docstring). 드리프트 창은 7일이라 행 수는 더 작지만 수 초 규모가 루프를 정지시킵니다. 행당 DB 조회는 없습니다. `:727` 의 `build_feature_frame(records)` 에 세션을 넘기지 않으므로 `lookup_institution_stats`·`lookup_repeat_history` 는 기본값/None 으로 단락됩니다(`src/ml/features.py:104-136`, `src/ml/institution_history.py:399-441`).
- **측정 방법**: `:724-737` 구간을 `perf_counter` 로 계측해 카테고리별 소요를 기록하고, 같은 구간을 단일 `to_thread` 함수로 감싼 대조군과 loop lag 를 비교합니다.

### 3.4 D4 (중간) — 수집 창 결정의 카테고리 루프 COUNT 질의 (N+1)

- **위치**: `src/app/services/collector_service.py:87-112` (`for cat in categories:` 아래 `:90` 과 `:102` 의 `db.scalar(select(func.count(...)))`)
- **형태**: 카테고리마다 공고/결과 존재 여부를 개별 `COUNT` 질의로 확인합니다. 카테고리당 최대 2회, 4종이면 최대 8회의 순차 단일 질의가 발생하며, 단일 `GROUP BY` 집계 1회로 대체할 수 있는 형태입니다.
- **발생 조건**: `start_date` 를 지정하지 않은 수집 호출입니다. `POST /api/v1/bids/collect`(`src/app/api/v1/bids.py:246`)와 Arq 수집 스텝(`src/tasks/automation_steps.py:27`)이 이 경로를 탑니다.
- **예상 기여**: 수집 1회당 고정 8회(행 수 비례 아님)입니다. 다만 `bid_announcements`·`bid_results` 는 300만 행 이상이라 각 `COUNT` 비용이 작지 않고, 이후 체크포인트 집계 2회(`collector_service.py:125,136`)가 뒤따릅니다. 이 함수는 `:306` 의 `asyncio.to_thread(_resolve_collection_window_thread)` 로 오프로드되어 이벤트 루프는 막지 않습니다.
- **측정 방법**: 수집 API 1회 호출 시 발행 SQL 수와 `sql_ms` 를 관측해 카테고리 4종 기준 8회 여부를 확인하고, 단일 `GROUP BY` 대체안과 총 SQL 시간을 비교합니다.

### 3.5 D5 (중간) — 상위 N 스냅샷 재집계의 조합 루프 질의와 조합별 commit

- **위치**: `src/app/services/ranking_snapshots.py:168-213`. 바깥 루프 `:168` (`for dataset, dimension in DIMENSIONS`), 안쪽 루프 `:172` (`for category in SNAPSHOT_CATEGORIES`), 조합별 `:173` (`_compute_rows`)·`:175` (`db.execute(delete(...))`)·`:213` (`db.commit()`). 나이 판정은 `:144` (`_should_rebuild`) → `:127-141` (`_dimension_age_days` 의 `MAX(rebuilt_at)` 질의)
- **형태**: `DIMENSIONS` 3종 × `SNAPSHOT_CATEGORIES` 5종 = 15개 조합마다 집계 질의와 손상값 probe 질의(`:118-122`)가 실행되고, 조합마다 `db.commit()` 이 호출됩니다. 차원마다 `_dimension_age_days` 가 `MAX()` 질의 1회를 더합니다.
- **발생 조건**: 야간 스케줄 또는 개발 데이터 최신화 성공 후 `src/tasks/scheduled_tasks.py:276,354` 가 호출하며, `force_weekly=True` 이면 주간 차원이 전부 재집계됩니다.
- **예상 기여**: 15~30회 집계 질의와 15회 commit 이 발생합니다. 모듈 주석 기준 `bid_ntce_nm` 차원은 6,645,162 행 전표 스캔으로 전체 카테고리 한 조합이 167초이며, 이 차원이 지배 비용입니다. commit 15회는 WAL/fsync 오버헤드를 더합니다. `asyncio.to_thread` 로 오프로드되어 이벤트 루프는 막지 않습니다.
- **측정 방법**: `rebuild_ranking_snapshots` 실행 시 조합별 소요와 발행 질의 수를 로깅하고, commit 을 1회로 묶은 대조군과 총 소요를 비교합니다.

### 3.6 D6 (낮음) — 수집 예외 경로의 동기 세션 연산이 이벤트 루프에서 실행

- **위치**: `src/app/services/collector_service.py:362,385,411,443,469` (각 `db.rollback()`). 진입점은 `:277` (`async def collect_bids`) 이며 `src/app/api/v1/bids.py:259` 와 `src/tasks/automation_steps.py:27` 이 `await` 로 호출합니다.
- **형태**: `async def` 함수의 `except` 블록에서 동기 SQLAlchemy 세션 연산(`db.rollback()`)을 오프로드 없이 실행합니다. 아울러 수집에 쓰는 `db` 는 요청 스코프 세션인데, 실제 적재는 `src/app/services/api_collector.py:445` 의 `await asyncio.to_thread(sink, items)` 를 통해 워커 스레드에서 같은 세션으로 `_bulk_insert`(`collector_service.py:172-194`)를 수행합니다. 적재 자체는 정상 오프로드 경로이나, SQLAlchemy `Session` 은 스레드 안전하지 않아 루프 스레드의 예외 처리와 워커 스레드의 적재가 같은 세션을 공유하는 구조적 위험이 있습니다.
- **발생 조건**: 수집 중 예외 또는 부분 실패(`RangeCollectionError`)가 발생할 때만입니다.
- **예상 기여**: 열린 트랜잭션이 남아 있으면 `ROLLBACK` 왕복 1회가 이벤트 루프에서 발생합니다. 대개 `_bulk_insert` 의 `:191` 이 이미 롤백해 no-op 이므로 기여는 작습니다. 세션 스레드 공유는 지연이 아니라 정합성 위험이며, 발생 시 재현이 어려운 형태로 드러납니다.
- **측정 방법**: 수집 실패를 인위 주입하고 예외 경로의 loop lag 를 측정합니다. 세션 공유는 `_bulk_insert` 를 전용 `sessionmaker` 세션으로 분리한 대조군과 동시성 테스트로 비교합니다.

### 3.7 D7 (낮음) — 수집 스텝 오류 분기의 동기 COUNT 가 이벤트 루프에서 실행

- **위치**: `src/tasks/automation_steps.py:33` (`today_rows = db.scalar(select(func.count(BidAnnouncement.id))...)`), 함수 선언은 `:23` (`async def _step_collect`)
- **형태**: `_step_collect` 만 `async def` 이고 나머지 스텝 러너는 동기 함수라 `src/tasks/automation_tasks.py:233-236` 이 `await asyncio.to_thread(_invoke_sync_runner, ...)` 로 오프로드합니다. 그런데 `_step_collect` 는 async 이므로 `automation_tasks.py:234` 의 `await runner_fn(db, **kwargs)` 경로로 이벤트 루프에서 직접 실행되고, 오류 분기의 `db.scalar` 가 루프에서 돕니다.
- **발생 조건**: `G2B_SERVICE_KEY` 미설정으로 `collect_bids` 가 `status="error"` 를 반환할 때입니다.
- **예상 기여**: `bid_announcements` 300만 행 대상 `COUNT` 1회(수십 ms)가 이벤트 루프를 정지시킵니다.
- **측정 방법**: serviceKey 를 비운 상태로 `collect_only` 파이프라인을 실행하고 오류 분기 구간의 loop lag 를 측정합니다.

### 3.8 D8 (낮음) — 수집 후 홈 캐시 예열 꼬리의 표본·윈도우 루프 질의 (N+1)

- **위치**: `src/app/services/home_context.py:100-101` (`for sample_size in HOME_RECENT_SAMPLE_SIZES:` 아래 `db.execute(stmt.limit(sample_size))`), `:115-119` (`for day_window in HOME_RECENT_DAY_WINDOWS:`), 호출부 `:155-163` (`_build_home_payload` 가 전체 1회 + 카테고리 4종에 대해 반복)
- **형태**: 일 윈도우 3종 × 표본 크기 3종의 중첩 루프가 질의를 최대 9회 발행하고, 이를 전체와 카테고리 4종에 반복해 최대 약 45회 질의가 됩니다. 조기 반환 조건에 따라 실제 횟수는 줄어듭니다.
- **발생 조건**: `collect_bids` 성공 후 `_warm_aggregates_and_caches_sync`(`collector_service.py:218-245`, `:243` 의 `warm_home_page_cache`)가 실행될 때이며, `GET /api/v1/bids/home` 캐시가 미적중일 때입니다.
- **예상 기여**: 수집 종단의 예열 단계에서 고정 다발 질의가 발생해 수집 완료 시각을 늦춥니다. `:464` 의 `asyncio.to_thread` 로 오프로드되어 이벤트 루프는 막지 않습니다. `GET /home` 읽기 경로 자체는 선행 조사 대상이므로 후보에서 제외하고 **수집 경로가 부르는 예열 꼬리만** 후보로 둡니다.
- **측정 방법**: 수집 1회 후 `warm_home_page_cache` 구간의 질의 수와 소요를 측정하고, 윈도우·표본 크기 조합을 단일 질의로 축약한 대조군과 비교합니다.

### 3.9 D9 (낮음) — 워커 heartbeat·스케줄 관측의 동기 Redis 호출이 이벤트 루프에서 실행

- **위치**: `src/tasks/worker.py:357` (`_on_startup` 의 `record_worker_heartbeat()`), `:293` (`_heartbeat_loop` 의 `record_worker_heartbeat(key)`), 그리고 `src/tasks/scheduled_tasks.py:83,86` (`_record_schedule` 데코레이터의 `record_schedule_result`)
- **형태**: `async def` 컨텍스트에서 동기 캐시 갱신을 직접 호출합니다. `record_worker_heartbeat`(`worker.py:231-274`)는 `_worker_cache.set` 1~2회와 `_redis_queue_metrics` 의 `client.zcount`·`client.zcard`(`:210-211`)를 동기로 실행하고, `record_schedule_result`(`:277-288`)는 `_worker_cache.get` 1회와 `set` 1회를 실행합니다.
- **발생 조건**: heartbeat 는 `WORKER_HEARTBEAT_INTERVAL_SECONDS` 주기마다, `record_schedule_result` 는 모든 스케줄 태스크의 성공·실패 종료마다 실행됩니다.
- **예상 기여**: 주기적으로 Redis 왕복 1~4회가 이벤트 루프에서 발생합니다. 이 계층은 관측 전용이라 정확성 영향은 없으나, 스케줄 태스크 종료 시점마다 루프 정지가 누적됩니다.
- **측정 방법**: heartbeat 간격의 실제 편차를 기록하고, Redis 지연 주입 시 편차 확대를 측정해 `to_thread` 적용 전후를 비교합니다.

---

## 4. 전수 조사 입증: 결함 없음(정상) 판정 경로 목록

조사 대상에 포함된 쓰기·수집 경로를 전량 점검했고, 아래는 결함이 없음을 확인한 경로입니다.

| 조사 대상 경로 | 검토 위치 | 판정 | 근거 |
| :--- | :--- | :--- | :--- |
| 챗봇 대화 `POST /chat` | `src/app/api/v1/chatbot.py:431,437,438` | 결함 없음 | `enforce_anonymous_api_quota` 와 `_run_chat` 을 모두 `await asyncio.to_thread(...)` 로 오프로드합니다. |
| 챗봇 SSE `POST /chat/stream` | `src/app/api/v1/chatbot.py:461,472,480,514` | 결함 없음 | 쿼터 검사, `_prepare_chat_sync`, `_finalize_rag_answer_sync` 가 전부 `to_thread` 경유입니다. |
| 챗봇 단발 질의 `POST /query` | `src/app/api/v1/chatbot.py:541,546` | 결함 없음 | `await rag_engine.get_answer(...)` 경유이며 선행 조사에서 파이프라인 전체 오프로드가 확인되었습니다. |
| 챗봇 세션 생성 `POST /session/new` | `src/app/api/v1/chatbot.py:530-532` | 결함 없음 | 동기 라우트(`def`)라 AnyIO 스레드풀에서 실행되고, HMAC 서명 발급만 수행합니다. |
| G2B 수집 `POST /bids/collect` | `src/app/api/v1/bids.py:246,259` | 결함 없음 | 라우트는 async 이나 `collect_bids` 가 창 결정(`collector_service.py:306`), 적재 sink(`api_collector.py:445`), 집계 예열(`collector_service.py:464`)을 모두 오프로드합니다. 예외 경로만 D6 입니다. |
| 수집 적재 sink | `src/app/services/api_collector.py:444-446` | 결함 없음 | `await asyncio.to_thread(sink, items)` 로 세션 적재를 워커 스레드에서 수행하고 `sink_lock`(`:433,444`)으로 동시 사용을 직렬화합니다. |
| 수집 창 결정 | `src/app/services/collector_service.py:306-314` | 결함 없음 | `_resolve_collection_window_thread` 로 오프로드됩니다. 질의 증폭은 D4 로 별도 기재했습니다. |
| 수집 후 집계·캐시 예열 | `src/app/services/collector_service.py:464` | 결함 없음 | `_warm_aggregates_and_caches_sync`(`:218-245`)가 `to_thread` 로 오프로드됩니다. |
| 대량 적재 루프 | `src/app/services/collector_service.py:179-188` | 결함 없음 | 2,000행 배치당 `db.execute` 1회로 묶은 배치 적재이며 행당 질의가 아닙니다. |
| 자동화 8개 POST 라우트 | `src/app/api/v1/automation.py:104-221` | 결함 없음 | 전부 동기 라우트(`def`)이고 서비스 체인(`automation_orchestrator.py`, `automation_responses.py`, `automation_tokens.py`)도 동기이므로 이벤트 루프를 막지 않습니다. |
| 확인 토큰 소비 | `src/app/services/automation_tokens.py:44-70` | 결함 없음 | 동기 Redis `SET NX EX` 이나 호출부 `automation.py:167` 이 동기 라우트입니다. |
| 적격심사 프로필 생성·수정·삭제 | `src/app/api/v1/evaluations.py:780,844,889` | 결함 없음 | 동기 라우트이고 단건 중복 검사 1회 + 단건 쓰기입니다. 루프 질의가 없습니다. |
| 적격심사 스냅샷 생성 | `src/app/api/v1/evaluations.py:959-1016` | 결함 없음 | 동기 라우트이고 `:980-990` 의 증빙 루프는 `db.add` 만 수행합니다(행당 SELECT 없음). |
| 적격심사 스냅샷 삭제 | `src/app/api/v1/evaluations.py:1056-1065` | 결함 없음 | 단건 `db.delete` + commit 이며 `cascade` 삭제는 DB 측입니다. |
| 적격심사 스냅샷 목록 | `src/app/api/v1/evaluations.py:917,937-947` | 결함 없음 | `selectinload(BidEvaluationSnapshot.evidence_items)` 로 일괄 적재되어 지연 로딩 N+1 이 해소된 상태입니다. |
| 적격심사 분석 저장 | `src/app/api/v1/evaluations.py:721-731` → `:569-613` | 결함 없음 | `_save_snapshot_async` 는 이름과 달리 동기 함수이며 호출부가 동기 라우트입니다. 증빙 루프는 `db.add` 만 수행합니다. |
| 회원가입·로그인·로그아웃 | `src/app/api/v1/accounts.py:204,222,251` | 결함 없음 | 전부 동기 라우트입니다. |
| 낙찰가 예측 `POST /predict-price` | `src/app/api/v1/predictions.py:111,118,128,184` | 결함 없음 | 동기 라우트이고 공고 단건 조회 + `build_feature_dict` 1회(기관 이력 1 + 재발주 1 조회)로 루프가 없습니다. |
| 직접 특징 예측 `POST /predict` | `src/app/api/v1/predictions.py:328` | 결함 없음 | 동기 라우트이고 페이로드 기반 인메모리 추론입니다. |
| 자동화 파이프라인 동기 스텝 | `src/tasks/automation_tasks.py:233-236` | 결함 없음 | `inspect.iscoroutinefunction` 판정 후 동기 러너를 `await asyncio.to_thread(_invoke_sync_runner, ...)` 로 오프로드합니다. |
| 자동화 단계 보고 | `src/tasks/automation_tasks.py:255,291,318,360` | 결함 없음 | `_report` 를 `to_thread` 로 오프로드합니다. |
| 자동화 콜백 HTTP | `src/tasks/automation_tasks.py:61` | 결함 없음 | 동기 `httpx.post` 이나 호출부 `_report` 가 `to_thread` 경유입니다. |
| KB 재구축 스텝 | `src/tasks/automation_steps.py:90-116` | 결함 없음 | 동기 함수라 `automation_tasks.py:236` 이 스레드로 오프로드합니다. |
| 검색 인덱스 동기화 스텝 | `src/tasks/automation_steps.py:118-130` | 결함 없음 | 동기 함수라 스레드로 오프로드됩니다. 내부 `search_index.py:133-150` 의 `httpx.request` 도 같은 스레드에서 실행됩니다. |
| 예측 검증 스텝 | `src/tasks/automation_steps.py:132-178` | 결함 없음 | 동기 함수라 스레드로 오프로드됩니다. |
| 데이터 점검 스텝 | `src/tasks/automation_steps.py:221-296` | 결함 없음 | 동기 함수라 스레드로 오프로드됩니다. 고정 개수(11회)의 스칼라 질의이며 루프 질의가 아닙니다. |
| 재학습 태스크 | `src/tasks/retrain_task.py:189,208,218,222` | 결함 없음 | 데이터셋 빌드, champion 지표 로드, 학습, 이력 기록을 전부 `await asyncio.to_thread(...)` 로 오프로드합니다. |
| 야간·개발 최신화 후속 집계 | `src/tasks/scheduled_tasks.py:276,279,283,286,289`, `:354-358` | 결함 없음 | 5종 후속 집계가 전부 `to_thread` 로 오프로드됩니다. |
| 백업 스케줄 | `src/tasks/scheduled_tasks.py:142,143` | 결함 없음 | `execute_backup`·`prune_snapshots` 를 `to_thread` 로 오프로드합니다. |
| 드리프트 태스크 오프로드 구간 | `src/tasks/scheduled_tasks.py:649,688,664,707,740` | 결함 없음 | baseline 로드, 데이터셋 빌드, 판정 이력 기록이 오프로드됩니다. 나머지 구간은 D3 입니다. |
| 주간 재학습 fan-out | `src/tasks/scheduled_tasks.py:516-533` | 결함 없음 | 카테고리 루프가 `await run_retrain_pipeline_task(...)` 를 호출하고 그 내부가 오프로드됩니다. |
| 요약 재집계 오프로드 경로 | `src/tasks/summary_tasks.py:36-42` 이외 | 해당 없음 | D1 이 결함입니다. |
| MySQL 통계 신선도 | `src/app/services/mysql_stats_freshness.py:223-228` | 결함 없음 | 테이블 2개 고정 순회이며 읽기 전용입니다. 호출부 `scheduled_tasks.py:286,357` 이 `to_thread` 입니다. |
| 검색 인덱스 배치 구성 | `src/app/services/search_index.py:254-288` | 결함 없음 | 1,000행 배치마다 `IN` 질의 1회로, 행당 질의가 아닙니다. |
| KB 청크 준비 | `src/app/services/kb_builder.py:155-168` | 결함 없음 | 1,000행 청크마다 `IN` 질의 1회로, 행당 질의가 아닙니다. |
| KB 색인 해시 비교 | `src/app/services/kb_index_sync.py:98-145` | 결함 없음 | 10,000건 페이지 단위 조회이며 순회는 메모리 연산입니다. 재시도 `time.sleep`(`:90`)은 오프로드된 동기 러너 안에서 실행됩니다. |
| KB 삭제·재적재 순서 | `src/app/services/kb_index_sync.py:262-270` | 결함 없음 | 배치 upsert 후 삭제 1회로, 행당 질의가 아닙니다. |
| 비교 통계 스냅샷 | `src/app/services/compare_stats_snapshots.py:200-240` | 결함 없음 | 4개 스냅샷 고정 루프이며 각 항목이 단일 행 upsert 입니다. 호출부 `scheduled_tasks.py:279,355` 가 `to_thread` 입니다. |
| 계획 실행기 | `src/app/services/plan_executor.py:118-127` | 결함 없음 | `execute_plan_steps` 는 `chatbot.py:244` 에서 호출되며 그 상위 `_prepare_chat` 가 `to_thread` 경유입니다. 파이프라인 스텝은 큐 등록만 합니다. |
| 대화 상태 저장 | `src/app/services/conversation_state.py:341-402` | 결함 없음 | 단건 upsert 이며 `_finalize_rag_answer` 경로가 오프로드됩니다. |
| 특징 단일 공급원 | `src/ml/features.py:441-445`, `src/ml/institution_history.py:196-260`, `src/ml/repeat_history.py:159-235` | 결함 없음 | `build_feature_frame` 은 레코드당 파이썬 함수를 호출하지만 세션을 넘기지 않으면 행당 DB 조회가 없고, `attach_*` 는 순수 pandas 연산입니다. 행당 조회 금지는 모듈 docstring 에 명시되어 있습니다. |
| 증빙 관계 정의 | `src/app/models/evaluations.py:104-109,156-159` | 결함 없음 | 목록 경로에 `selectinload` 가 적용되어 있고, 생성 경로는 `db.add` 만 사용합니다. |

선행 조사에서 이미 최적화되었거나 조사 대상에서 제외된 경로(낙찰 목록·상세, 공고 목록·상세, 홈 컨텍스트 조회, 챗봇 RAG 검색, 스냅샷 목록)는 계약에 따라 재조사하지 않았습니다.

---

## 5. 미확인 항목

정적 조사로 확정하지 못했거나 정본 허용 범위 밖이라 열지 않은 항목입니다.

| 항목 | 사유 |
| :--- | :--- |
| `src/rag/structured_data.refresh_institution_name_catalogs` 내부 | 정본 허용 범위 밖입니다. 호출부는 `summary_tasks.py:40` 이며 D1 에 포함했습니다. |
| `src/ml/monitoring.check_dataset_drift`·`src/ml/psi` 내부 | 소스 확인 결과 순수 pandas/numpy 연산으로 파일·DB I/O 가 없음을 확인했으나, 스레드 오프로드 판단은 호출부(D3) 기준입니다. |
| `scripts/backup_recovery`, `scripts/backup_snapshots` 내부 | 스크립트 계층이며 `to_thread` 경유라 이벤트 루프 차단은 없다고 판단했으나 내부 질의 구조는 미확인입니다. |
| `src/app/core/cache.CacheLayer` 클라이언트 종류 | 정본 허용 범위 밖입니다. 다만 `src/tasks/worker.py:210-211` 이 `zcount`·`zcard` 를 동기 호출하는 사실로 동기 클라이언트임을 확인했습니다. |
| 실제 Arq 워커 `max_jobs`·동시성 설정과 실측 loop lag | 벤치마크 실행이 금지된 정적 조사라 수치를 측정하지 않았습니다. 3장의 예상 기여는 근거 있는 추정이며 실측이 아닙니다. |
| D4·D5·D8 의 실측 질의 수·소요 | 컨테이너 기동·DB 조회가 금지되어 정적 추정만 기재했습니다. DB 조회가 필요하면 `uv run python scripts/db_readonly_query.py --sql "..."` 형태만 사용해야 합니다. |

---

## 6. 차기 착수 권고 (상위 3건)

### 6.1 권고 1순위: 요약 재집계 태스크 2종 오프로드 (D1)

- **결함 요약**: `rebuild_dataset_summary_task`(`summary_tasks.py:22,26`)와 `refresh_institution_catalog_task`(`:37,40`)가 async 인데 무거운 동기 DB 작업을 워커 이벤트 루프에서 직접 실행합니다.
- **수정 난이도**: **낮음 (하)**. 두 본문을 각각 동기 함수로 분리하고 `await asyncio.to_thread(...)` 로 감쌉니다.
- **회귀 위험**: **매우 낮음 (최하)**. 같은 저장소의 `scheduled_tasks.py:276-289` 가 동일 패턴을 이미 사용하고 있고, 세션 생성·종료와 반환 구조를 그대로 유지합니다.
- **예상 효과**: 수 초 규모 루프 정지가 제거되어 수집·조회 직후 등록되는 재집계가 다른 태스크와 heartbeat 를 밀지 않습니다.

### 6.2 권고 2순위: 스케줄 진입부의 동기 Redis·DB 오프로드 (D2)

- **결함 요약**: `acquire_schedule_claim`, `release_schedule_claim`, `check_schedule_catchup_needed` 와 그 하위 `is_catchup_in_cooldown`·`get_latest_collection_time`·`record_catchup_attempt` 가 이벤트 루프에서 동기 왕복을 수행합니다.
- **수정 난이도**: **중간 (중)**. 호출부가 async 이므로 각 호출을 `await asyncio.to_thread(...)` 로 감싸면 되지만, catchup 경로는 직렬 호출이 여러 곳이라 한 번에 묶는 편이 안전합니다. claim 획득·해제의 원자성은 Redis 명령 자체가 보장하므로 스레드 이동으로 의미가 바뀌지 않습니다.
- **회귀 위험**: **낮음 (하)**. 로직과 반환 계약을 바꾸지 않고 호출 스레드만 이동합니다. 토큰 검증·쿨다운 판정 조건은 그대로입니다.
- **예상 효과**: 스케줄 태스크 진입·종료와 catchup 기동 시 최대 5회 누적되던 Redis/DB 왕복이 루프에서 사라집니다.

### 6.3 권고 3순위: 드리프트 특징·PSI 구간 단일 오프로드 (D3)

- **결함 요약**: `scheduled_tasks.py:724-737` 의 전량 프레임 변환과 PSI 계산이 이벤트 루프에서 동기 실행됩니다.
- **수정 난이도**: **중간 (중)**. `:724-737` 을 하나의 동기 함수로 추출해 `to_thread` 로 감쌉니다. `features.py` 단일 공급원 규칙은 함수 내부 호출을 그대로 두면 유지됩니다.
- **회귀 위험**: **낮음 (하)**. 계산 정의와 입력을 바꾸지 않고 실행 스레드만 이동합니다. 다만 `to_thread` 로 넘길 인자는 pandas 프레임이라 복사 비용이 발생하므로 프레임을 스레드 안에서 로드하는 형태가 더 낫습니다.
- **예상 효과**: 매일 04:00 카테고리별 수 초 규모 루프 정지가 사라집니다.

D4·D5 는 이미 오프로드되어 있어 이벤트 루프 문제는 아니며, 질의 증폭 해소는 별도 실측 후 착수하는 것이 순서입니다. D6~D9 는 기여가 작고 회귀 위험이 상대적으로 높으므로 D1~D3 이후로 미룹니다.

---

## 7. 결론

쓰기·수집 경로에서 **이벤트 루프를 막는 동기 실행 6건(D1, D2, D3, D6, D7, D9)** 과 **N+1 성격의 루프 질의 3건(D4, D5, D8)** 을 특정했습니다.

가장 뚜렷한 구조적 결함은 Arq 워커 계층입니다. 동기 라우트로 선언된 FastAPI 쓰기 핸들러들은 AnyIO 스레드풀에서 돌아 이벤트 루프를 막지 않았고, 수집기와 자동화 파이프라인도 대부분 `asyncio.to_thread` 로 오프로드되어 있었습니다. 반면 워커 태스크 계층에서는 `scheduled_tasks.py` 의 후속 집계가 오프로드된 것과 달리 `summary_tasks.py`·스케줄 진입부·드리프트 태스크가 같은 규율을 적용받지 못했습니다. 즉 이 결함들은 설계 부재가 아니라 **적용 누락**이며, 저장소 안에 이미 검증된 패턴이 있으므로 낮은 위험으로 회수할 수 있습니다.

N+1 계열은 모두 고정 상수 루프(카테고리 4종, 차원·카테고리 15조합, 표본·윈도우 조합)이며 행 수에 비례하는 증폭은 발견되지 않았습니다. 따라서 이 영역의 우선순위는 이벤트 루프 정지 해소보다 낮습니다.

다음 최적화 작업에서는 6장의 상위 3건을 우선 수정하고, 표준 레이턴시 게이트 규약에 따라 loop lag 및 P95 실측으로 효과를 확인할 것을 제안합니다.

---

## 8. 검증 기록

정본 사양 `verification_commands` 를 그대로 실행한 출력입니다.

```text
$ python3 scripts/validate_agent_rules.py --quiet
============================================================
다중 에이전트 규칙 정합성 검증 (pre-commit / v2)
============================================================
[PASS] CLAUDE.md thin pointer
[PASS] .antigravity/rules.md
[PASS] .cursor core rule AGENTS.md 참조
[PASS] opencode.json instructions v2 단일 주입
[PASS] 스킬 미러 정합성
[PASS] AGENTS.md 단일 진실 원천 (@SKILLS.md 미참조)
[PASS] Task Capsule v2 규약 문서
[PASS] Task Capsule v2 템플릿 정합성
[PASS] orca-section-coordination v2 스킬
[PASS] Orca 정본 스킬 포인터 정합성
[PASS] 신규 Task 분석 문서 추가 차단 (git diff)
[PASS] CURRENT_STATE 정본 존재
[PASS] CURRENT_STATE 필수 필드
[PASS] 컨텍스트 예산
[PASS] 워커 모델 배정표 정합성 (TIER_POLICY vs 문서)
[PASS] AGENTS.md 워커 모델 배정표 부재
[PASS] CURRENT_STATE 기계 상태 원장 정합성
[PASS] CURRENT_STATE 판정 사실 원장 검증
[PASS] CURRENT_STATE 6.1 상태 모순 검사
[PASS] 분석 문서 수치 정합성 (METRICS 마커)
[PASS] pre-commit 훅 설치
------------------------------------------------------------
검증 통과: 21/21 건.
validate_agent_rules exit=0
```

변경 파일 검증도 실제 실행 출력을 그대로 옮겨 적습니다. 이 명령의 출력은 커밋 수와 무관하게 동일합니다.

```text
$ git diff --name-only main...HEAD
docs/analysis/write_path_g3_scan_20260920.md
git diff exit=0
```

작업 브랜치와 최종 커밋 SHA, 커밋 수, 변경 파일 목록은 캡슐 계약의 정본 기록인 `.orca/capsules/task_f895e5e6a4d0/worker_done.json` 의 `branch`·`commit`·`commit_count`·`changed_files` 에 적었습니다.

- 본 보고서는 `METRICS_BEGIN` 마커를 쓰지 않았습니다. 마커가 없으면 분석 문서 수치 정합성 검사 대상이 아니며, 본 조사는 실측 수치가 아니라 정적 판정이므로 마커 대상이 아닙니다.
- 코드·테스트 파일 변경 여부는 커밋 후 `git diff --name-only main...HEAD` 로 확인했고, 변경 파일은 본 보고서 1건뿐입니다. 캡슐 산출물 `.orca/capsules/task_f895e5e6a4d0/worker_done.json` 은 `.gitignore:231` 의 `.orca/` 규칙으로 추적 대상이 아닙니다.
- 표에 적은 행 번호는 작성 시점에 해당 행을 직접 열어 대조했습니다. 대표 확인 위치는 `src/tasks/summary_tasks.py:22,26,37,40`, `src/tasks/scheduled_tasks.py:226,292,724-725,733,1282`, `src/app/services/collector_service.py:88,90,102,362,469`, `src/app/services/ranking_snapshots.py:168,172,173,213`, `src/app/services/home_context.py:100-101,115-119`, `src/tasks/automation_steps.py:23,33` 입니다.

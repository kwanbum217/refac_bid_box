# Task 0bba466af5f3: 스케줄 수집 Redis 원자 claim 가드 및 fail-closed 재작업 분석 보고서

> **작성일**: 2026-09-03
> **작업자**: Orca Worker (Role: builder)
> **태스크 ID**: `task_0bba466af5f3`
> **관련 문서**: `docs/ops/scheduling.md`, `docs/analysis/task_1a6eeab35699.md`, `src/tasks/scheduled_tasks.py`

---

## 1. 재작업 배경 및 Level 3 검토 반려 사유

선행 작업(`task_1a6eeab35699`)에서 기동 시 스케줄 따라잡기(Startup Catch-up)를 구현하고 독립 리뷰(`task_794ea3b9cf87`)는 통과(Pass) 판정을 내렸으나, 코디네이터 Level 3 아키텍처 심층 검토에서 다음과 같은 분산 환경 취약점이 지적되어 본 재작업(`task_0bba466af5f3`)이 발령되었습니다.

### 1.1 발견된 3대 결함 및 위험성

1. **`CacheLayer`의 프로세스 로컬 메모리 Degrade**:
   - `src/app/core/cache.py`의 `CacheLayer`는 일반 조회 캐시 전용으로 설계되어, Redis 연결 불가 시 프로세스 내부 딕셔너리로 폴백(degrade)합니다.
   - 다중 워커 컨테이너 환경에서 Redis 장애가 발생하면 각 프로세스가 독립적인 로컬 메모리를 참조하므로, 모든 워커가 동시에 중복 수집을 발화하여 외부 조달청(G2B) API 쿼터를 소진하거나 DB 교착을 유발할 위험이 있었습니다.
2. **비원자적 GET 후 SET 경합 (Race Condition)**:
   - `check_schedule_catchup_needed`에서 `is_catchup_in_cooldown()`(GET)으로 쿨다운을 조회한 후, `run_schedule_catchup_task`에서 `record_catchup_attempt()`(SET)를 호출하는 2단계 비원자적 흐름이었습니다.
   - 워커 2대 이상이 동시에 기동될 경우 둘 다 GET 판정을 통과한 후 동시에 수집 파이프라인을 실행하는 경합이 발생했습니다.
3. **정규 크론과의 공유 락 부재 및 기동 시점 충돌**:
   - 정규 cron 태스크인 `nightly_schedule_task`(02:00)와 `development_data_refresh_task`(02:00)에는 실행 claim이 적용되어 있지 않았습니다.
   - 정규 스케줄 시각 직전에 워커가 재기동되어 따라잡기가 시작된 경우, 정규 cron과 따라잡기가 동일한 DB/ChromaDB/파이프라인을 동시 실행하는 충돌이 방어되지 않았습니다.

---

## 2. 해결 설계 및 단일 실행 계약 (Single Execution Contract)

### 2.1 Redis `SET NX EX` 기반 원자적 단일 실행 claim
- `CacheLayer`를 일절 배제하고 `RedisConnection(label="schedule_guard")`을 직접 사용하여 `client.set(SCHEDULE_COLLECTION_CLAIM_KEY, payload, ex=ttl, nx=True)` 단일 명령으로 실행 claim을 획득합니다.
- 공통 claim 키: `SCHEDULE_COLLECTION_CLAIM_KEY = "bidbox:schedule:collection_claim"`
- TTL 계약: `AUTOMATION_SCHEDULE_CATCHUP_COOLDOWN_HOURS` * 3600초 (기본 6시간 = 21,600초)

### 2.2 장애 시 무조건 차단 (Fail-Closed Policy)
- Redis 연결 실패(`client is None`) 또는 명령 실행 오류 발생 시, 작업을 허용하지 않고 즉시 fail-closed 처리합니다.
- claim 상태를 `ScheduleClaimStatus` enum(`ACQUIRED`, `ALREADY_CLAIMED`, `REDIS_UNAVAILABLE`, `COMMAND_ERROR`)으로 명확히 구분합니다.
- `REDIS_UNAVAILABLE` 또는 `COMMAND_ERROR` 시 `run_automation_pipeline` 및 후속 집계(`_rebuild_ranking_snapshots`, `_rebuild_institution_stats`)는 절대 호출되지 않습니다.

### 2.3 정규 진입점 단일 가드 및 자기 충돌(Self-Collision) 원천 방지
- `nightly_schedule_task`와 `development_data_refresh_task` 진입부에서 `acquire_schedule_claim`을 호출하여 선점합니다.
- 기동 따라잡기(`run_schedule_catchup_task`)는 바깥에서 별도의 claim을 획득하지 않고 호출 대상 스케줄 태스크 내부의 claim을 그대로 재사용합니다. 이를 통해 바깥 claim과 내부 claim 간의 자기 충돌(self-collision)을 방지하고 코드 중복을 0으로 유지합니다.
- 작업 완료 시 오직 정상 완료(`status == "success"`)인 경우에만 발급받은 소유 토큰(`token`)을 전달하여 Redis Lua 스크립트로 원자적 claim 해제(`release_schedule_claim`)를 수행합니다.
- 파이프라인 실행 예외뿐만 아니라 `status=failed` 또는 `partial` 결과 dict 반환, 후속 집계 실패(`partial_success`) 시에는 claim을 해제하지 않고 6시간 TTL 동안 유지하여 재시작 루프에 의한 반복 수집을 방어합니다.

---

## 3. 변경 파일 내역

| 파일 경로 | 변경 구분 | 주요 내용 |
| --- | :---: | --- |
| `src/tasks/scheduled_tasks.py` | 수정 | `RedisConnection` 기반 `acquire_schedule_claim` 구현, `nightly` 및 `refresh` 진입부 원자 claim 가드 적용, catch-up 자기 충돌 제거 |
| `tests/test_schedule_catchup.py` | 수정 | `FakeRedisConnection` 기반 원자 claim, fail-closed, 상호 배타성, 충돌 방지 등 19개 단위/통합 테스트 전면 보강 |
| `tests/test_scheduled_tasks.py` | 수정 | 스케줄러 검증 테스트 환경을 위한 격리 `mock_schedule_claim` fixture 추가 |
| `tests/test_mlops_notifier.py` | 수정 | 알림 실패 검증 테스트 환경을 위한 격리 `mock_schedule_claim` fixture 추가 |
| `docs/ops/scheduling.md` | 수정 | 원자 claim 아키텍처 다이어그램, 6대 설계 원칙, Redis claim 키 명세 업데이트 |
| `docs/analysis/task_1a6eeab35699.md` | 수정 | 코디네이터 Level 3 검토 반려 사유 및 재작업 인계 섹션 추가 |
| `docs/analysis/task_0bba466af5f3.md` | 신규 | 본 재작업 종합 분석 및 검증 결과 보고서 작성 |

---

## 4. 검증 결과

### 4.1 스케줄러 및 알림 관련 Targeted Tests 검증
- 명령: `uv run pytest tests/test_scheduled_tasks.py tests/test_schedule_catchup.py tests/test_mlops_notifier.py`
- 결과: **44 passed in 0.28s** (종료 코드 0)
  - `tests/test_scheduled_tasks.py`: 14 passed
  - `tests/test_schedule_catchup.py`: 19 passed
  - `tests/test_mlops_notifier.py`: 11 passed

### 4.2 오프로드 연계 검증 (`tests/test_task_offload_scheduled.py`)
- 명령: `uv run pytest tests/test_task_offload_scheduled.py`
- 결과: **2 passed in 0.06s** (종료 코드 0)

### 4.3 에이전트 규칙 검증
- 명령: `python3 scripts/validate_agent_rules.py --quiet`
- 결과: **검증 통과: 20/20 건** (종료 코드 0)

---

## 5. 리뷰 체크리스트 자체 점검

| 항목 ID | 점검 질문 | 판정 | 근거 |
| --- | --- | --- | --- |
| `atomic_claim` | 단일 실행 claim이 Redis SET NX EX 한 번이 아닌 비원자적 읽기-쓰기 또는 프로세스 로컬 fallback을 사용하는가 | **통과 (No)** | `acquire_schedule_claim`에서 `client.set(..., ex=ttl, nx=True)` 단일 명령 사용, `CacheLayer` 미사용 |
| `shared_entrypoint_guard` | nightly, development refresh, catch-up 중 하나라도 공통 claim을 우회하거나 자기 자신과 이중 claim하는가 | **통과 (No)** | 세 경로 모두 동일한 `SCHEDULE_COLLECTION_CLAIM_KEY` 사용, catch-up은 타겟 태스크 claim 재사용 |
| `redis_fail_open` | Redis 연결 없음 또는 SET 예외에서도 수집 파이프라인이 실행되는가 | **통과 (No)** | `REDIS_UNAVAILABLE`, `COMMAND_ERROR` 시 `status=failed` 반환하며 pipeline 호출 0회 보장 |
| `external_test_state` | 회귀 테스트가 실제 Redis, DB, Docker 또는 실행 순서에 의존하는가 | **통과 (No)** | `FakeRedisConnection`, `mock_schedule_claim` 등 테스트 격리 완료, 외부 Redis 없이 결정론적 통과 |
| `scope_exceeded` | 허용된 파일 밖을 수정하거나 새 의존성을 추가했는가 | **통과 (No)** | 허용된 7개 파일만 수정/생성, 신규 외부 라이브러리 추가 0건 |

---

## 6. Level 3 후속 지적 사항 및 후속 재작업(task_4b88e29dc3f9) 인계

본 태스크 이후 코디네이터 Level 3 심층 아키텍처 검토에서 다음 3가지 추가 결함이 발견되어 후속 태스크(`task_4b88e29dc3f9`)로 인계 및 완전 해결되었습니다:

1. **실패 결과 dict 반환 시 claim 조기 소멸 결함**:
   - `run_automation_pipeline`이 예외 없이 `status=failed` dict를 반환했을 때 `nightly_schedule_task`가 claim을 해제하던 결함 -> `status != "success"` 시 즉시 반환 및 claim 유지로 해결.
2. **무조건 DEL로 인한 Stale Owner 경합**:
   - `release_schedule_claim`이 단순 DEL을 수행하여 TTL 만료 후 생성된 후속 실행의 claim을 삭제할 위험 -> UUID 기반 고유 소유 토큰(`token`) 및 Redis Lua 원자 비교-삭제(`RELEASE_SCHEDULE_CLAIM_SCRIPT`)로 해결.
3. **실패 응답 dict 내 중복 `error` 키**:
   - `development_data_refresh_task`의 Redis 실패 응답 dict에서 최상위 중복 `error` 키 제거.
- 상세 해결 내용 및 51개 회귀 테스트 검증 내역은 `docs/analysis/task_4b88e29dc3f9.md`를 참조하십시오.

# D-04 startup catch-up 동시성 제어와 완결성 원장

> **작성일**: 2026-09-05
> **작업 ID**: `task_d9527d72e596`
> **대상 모듈**: `src/tasks/worker.py`, `src/tasks/scheduled_tasks.py`, `tests/test_scheduled_tasks.py`

---

## 1. 문제

워커 기동 시 스케줄 따라잡기는 `asyncio.create_task(_run_catchup_background)` 가 `run_schedule_catchup_task` 를 직접 호출했다. 이 경로는 Arq `max_jobs = 4` 밖에 있어 이미 잡이 가득 찬 워커에서도 수집 파이프라인이 추가로 돌았다. 시도 기록은 쿨다운 키의 `attempted_at` 한 줄뿐이라, 무엇이 대상이었고 무엇이 실행·실패·건너뜀인지 사후에 확인할 수 없었다.

## 2. 동시성 제어 선택

| 방식 | 기동 지연 | `max_jobs` 포함 | 장시간 수집 | 채택 |
| --- | --- | --- | --- | --- |
| Arq 큐에 정규 잡으로 적재 | 적재만 백그라운드, 완료를 기다리지 않음 | 포함 | `arq.func` 로 야간 크론과 같은 10800초 | 채택 |
| asyncio 유지 + 자체 세마포어 | 없음 | 미포함. Arq 세마포어와 별개 상한이 생김 | 기존과 같이 무제한 | 기각 |

자체 세마포어는 이름만 상한을 걸고 실제 `WorkerSettings.max_jobs` 와 슬롯을 공유하지 못한다. 큐 적재는 워커가 이미 쓰는 잡 풀에 들어가므로 D-04 의 동시성 요구를 충족한다.

따라잡기 잡은 `run_schedule_catchup_task` 이름과 고정 `_job_id=schedule-catchup-startup` 으로 넣는다. 같은 잡 결과가 `keep_result` 동안 남아 있으면 Arq 가 중복 적재를 거부한다. 잡 제한 시간은 야간 크론과 맞춰 30분 기본값에 잘리지 않게 했다.

기동 훅은 여전히 `create_task` 만 하고 반환한다. 백그라운드 태스크는 적재만 수행하며, 적재 예외는 삼켜 워커 프로세스를 죽이지 않는다.

## 3. 원장

새 Redis 테이블이나 기록 함수를 만들지 않았다. 기존 `record_catchup_attempt` 가 쿨다운 키와 원장 키를 함께 쓴다.

| 키 | 역할 | TTL |
| --- | --- | --- |
| `bidbox:schedule:catchup_cooldown` | 재시작 루프 방어. 실행 선점(SET NX)과 시도 완료 기록 | 쿨다운(기본 6시간) |
| `bidbox:schedule:catchup_ledger` | 대상·실행·실패·건너뜀 완결성 원장 | 최소 7일 |

페이로드 필드: `status`, `reason`, `targets`, `executed`, `failed`, `skipped`, `details`, `attempted_at`, `ttl`.

판정만 하고 실행하지 않는 경우(비활성, 임계 미달 등)는 쿨다운을 걸지 않고 원장만 남긴다. `in_cooldown` 재평가는 선점 워커의 원장을 덮지 않는다.

## 4. 단일 실행

기존 쿨다운은 GET 이후 실행이 끝난 뒤에야 SET 하므로, 워커 두 대가 동시에 기동하면 둘 다 통과한다. 대상 스케줄의 collection claim 이 무거운 수집은 막지만, 따라잡기 태스크 자체는 두 번 돈다.

실행이 필요하다고 판정되면 `record_catchup_attempt(..., nx=True)` 로 쿨다운 키를 선점한다. 실패한 쪽은 `already_running` 으로 건너뛰고 원장을 덮지 않는다.

## 5. 검증

`tests/test_scheduled_tasks.py` 에 (a) 원장 구분, (b) 동시 기동 1회 실행, (c) 적재 실패가 워커를 죽이지 않음, (d) 기동이 완료를 기다리지 않음, (e) redis 가 있으면 직접 실행하지 않고 enqueue 함을 추가했다.

# CI 환경 스케줄 태스크 실패 복구 및 catch-up 쿨다운 키 분리 분석 보고서

> **작성일**: 2026-09-04
> **작업 식별자**: task_0dfc2f73ee31
> **상태**: 검증 완료 (succeeded)
> **대상 파일**: `src/tasks/scheduled_tasks.py`, `tests/test_task_offload_scheduled.py`, `tests/test_schedule_catchup.py`, `docs/ops/scheduling.md`

---

## 1. 배경 및 작업 목적

GitHub Actions CI 환경에서 `tests/test_task_offload_scheduled.py`의 두 테스트가 `AssertionError: assert 'failed' == 'success'`로 실패하며 main CI pytest job이 실패하는 현상이 발생했습니다.

동시에 코드베이스 조사 결과, `src/tasks/scheduled_tasks.py`에서 기동 시 재시작 루프 방어용 쿨다운 키(`CATCHUP_LAST_ATTEMPT_KEY`)가 단일 실행 방지용 claim 키(`SCHEDULE_COLLECTION_CLAIM_KEY`)와 동일한 값으로 alias 되어 있었습니다. 태스크가 정상 종료될 때 claim 키를 원자적으로 해제하면서 쿨다운 키까지 함께 제거되어, 문서(`docs/ops/scheduling.md`) 및 설정(`AUTOMATION_SCHEDULE_CATCHUP_COOLDOWN_HOURS`, 기본 6시간)이 약속한 쿨다운이 성공 경로에서 유지되지 않는 결함이 존재했습니다.

본 작업의 목적은 다음과 같습니다:
1. CI 환경(Redis 부재)에서 동기 함수 오프로드 검증 테스트가 의도대로 통과하도록 테스트 환경 대역을 구성하고, Redis 미가용 시 fail-closed 안전 동작을 고정하는 테스트를 추가합니다.
2. 실행 claim 키(lease)와 catch-up 쿨다운 키를 분리하여, 태스크 성공 시 claim은 해제되더라도 쿨다운 키는 독립적으로 유지되도록 수정합니다.
3. 기동 catch-up 시도 완료 시 성공/실패와 무관하게 쿨다운 키를 기록하도록 보장합니다.
4. 변경된 키 구조와 쿨다운 수명 명세를 `docs/ops/scheduling.md`에 일치하도록 반영합니다.

---

## 2. 문제 원인 분석

### 2.1 CI 환경 테스트 실패 원인
- `tests/test_task_offload_scheduled.py`의 `test_nightly_schedule_task_offloads_sync_functions` 및 `test_development_data_refresh_task_offloads_sync_functions`는 동기 DB/집계 함수가 이벤트 루프 스레드를 차단하지 않고 `asyncio.to_thread`로 오프로드되는지 검증하는 테스트입니다.
- 태스크 진입 시 `acquire_schedule_claim`을 호출하는데, Redis가 실행되지 않는 CI 환경에서는 `ScheduleClaimResult(status=ScheduleClaimStatus.REDIS_UNAVAILABLE, ...)`가 반환됩니다.
- 태스크는 fail-closed 안전 정책에 따라 `status="failed"`, `reason="redis_unavailable"`을 반환하며 조기 종료되어, 동기 오프로드 대상 함수들이 호출되지 못하고 테스트가 실패했습니다.

### 2.2 catch-up 쿨다운 키 alias 및 조기 소실 결함
- `src/tasks/scheduled_tasks.py` 627행에서 `CATCHUP_LAST_ATTEMPT_KEY = SCHEDULE_COLLECTION_CLAIM_KEY`로 두 키가 동일한 Redis 키(`bidbox:schedule:collection_claim`)를 참조하고 있었습니다.
- `nightly_schedule_task` 및 `development_data_refresh_task`는 성공 시 `release_schedule_claim`을 호출하여 claim 키를 삭제합니다.
- 이로 인해 catch-up 쿨다운 키까지 함께 삭제되어, 정상 수집 완료 후 워커가 재시작되면 6시간 쿨다운이 무력화되는 문제가 있었습니다.

---

## 3. 해결 내용

### 3.1 `src/tasks/scheduled_tasks.py`
1. **키 상수 분리**:
   - `SCHEDULE_COLLECTION_CLAIM_KEY = "bidbox:schedule:collection_claim"` (동시 실행 방지 lease)
   - `SCHEDULE_CATCHUP_COOLDOWN_KEY = "bidbox:schedule:catchup_cooldown"` (기동 재시작 폭주 방어 쿨다운)
   - `CATCHUP_LAST_ATTEMPT_KEY = SCHEDULE_CATCHUP_COOLDOWN_KEY` (하위 호환 alias)
2. **`record_catchup_attempt` 함수 갱신**:
   - 쿨다운 전용 키(`SCHEDULE_CATCHUP_COOLDOWN_KEY`)에 `attempted_at`과 `ttl`을 JSON 페이로드로 `client.set(key, payload, ex=ttl)` 기록하도록 구현.
3. **`is_catchup_in_cooldown` 함수 갱신**:
   - 기본 조회 키를 `SCHEDULE_CATCHUP_COOLDOWN_KEY`로 변경하여 claim lease와 독립적으로 쿨다운 상태를 판정하도록 수정.
4. **`run_schedule_catchup_task` 에 `finally` 블록 추가**:
   - catch-up 태스크 실행 시 성공/실패 여부와 무관하게 `finally: record_catchup_attempt()`를 호출하여 쿨다운 키가 기록되도록 보장.
5. **태스크 성공 시 해제 격리**:
   - `release_schedule_claim`은 claim 키(`SCHEDULE_COLLECTION_CLAIM_KEY`)만 해제하며, 쿨다운 키에는 영향을 주지 않음.

### 3.2 `tests/test_task_offload_scheduled.py`
1. **격리 대역 fixture 추가**:
   - `isolate_schedule_redis` fixture를 도입하여 `FakeRedisConnection`을 주입, 실제 Redis가 없는 환경에서도 claim을 획득하고 동기 오프로드 검사를 온전히 수행하도록 보장.
2. **동기 오프로드 검사 보존**:
   - `_assert_no_running_event_loop` 및 `status == "success"` 단언을 그대로 유지.
3. **fail-closed 안전 동작 고정 테스트 추가**:
   - `test_nightly_schedule_task_fails_closed_when_redis_unavailable`
   - `test_development_data_refresh_task_fails_closed_when_redis_unavailable`
   - Redis 미가용 시 `status="failed"`, `reason="redis_unavailable"` 반환 및 내부 오프로드 함수가 호출되지 않음을 엄격히 검증.

### 3.3 `tests/test_schedule_catchup.py`
1. claim 키와 쿨다운 키 분리에 맞추어 기존 테스트의 단언을 명확화 (claim 키 존재/해제 여부는 `SCHEDULE_COLLECTION_CLAIM_KEY` 직접 확인).
2. 신규 검증 테스트 2건 추가:
   - `test_claim_key_and_cooldown_key_are_distinct`: 상수 분리 검증.
   - `test_catchup_records_cooldown_on_both_success_and_failure`: catch-up 완료 시 성공/실패 무관 쿨다운 키 기록 및 성공 시에도 claim만 해제되고 쿨다운 키는 보존됨을 검증.

### 3.4 `docs/ops/scheduling.md`
- 아키텍처 다이어그램, 6대 설계 원칙, Redis 키 명세에 claim 키와 쿨다운 키의 분리 및 독립적 수명 주기를 문서화.

---

## 4. 검증 결과

| 검증 명령 | 결과 | 상세 내용 |
| --- | :---: | --- |
| `python3 scripts/validate_agent_rules.py --quiet` | PASS | 규칙 검증 20/20 전량 통과 |
| `uv run pytest tests/test_task_offload_scheduled.py -v` | PASS | 4 passed in 0.10s |
| `uv run pytest tests/test_schedule_catchup.py -v` | PASS | 31 passed in 0.32s |
| `uv run pytest tests/test_scheduled_tasks.py -v` | PASS | 14 passed in 0.17s |
| `uv run pytest tests/ -q -m 'not data_assets'` | PASS | 3486 passed, 31 skipped, 3 deselected in 253.66s |

> [!NOTE]
> 격리 워크트리 환경에는 `data/model_files` 및 `chroma_db` 디렉터리가 배치되지 않으므로, `not data_assets` 마커가 제외된 전체 테스트 3,486건이 100% 정상 통과했습니다.

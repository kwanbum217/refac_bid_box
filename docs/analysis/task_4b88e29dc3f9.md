# Task 4b88e29dc3f9: 분산 스케줄 claim 소유 토큰 및 실패 유지 결함 재작업 분석 보고서

> **작성일**: 2026-09-03
> **작업자**: Orca Worker (Role: builder)
> **태스크 ID**: `task_4b88e29dc3f9`
> **관련 문서**: `docs/ops/scheduling.md`, `docs/analysis/task_0bba466af5f3.md`, `src/tasks/scheduled_tasks.py`

---

## 1. 재작업 배경 및 문제 정의

선행 작업(`task_0bba466af5f3`)에서 Redis `SET NX EX` 기반의 단일 실행 claim 및 fail-closed 정책을 구현하였으나, 코디네이터 Level 3 아키텍처 심층 검토에서 다음과 같은 3대 분산 환경 경합 및 상태 관리 결함이 발견되어 본 재작업(`task_4b88e29dc3f9`)이 발령되었습니다.

### 1.1 발견된 3대 결함 및 위험성

1. **무조건 DEL로 인한 Stale Owner Claim 삭제 경합 (Race Condition)**:
   - 기존 `release_schedule_claim`은 소유권 확인 없이 단순 `DEL key`를 수행하였습니다.
   - 이전 실행 A가 장시간 실행되어 TTL(6시간)이 만료된 후 새 실행 B가 동일 키를 획득했을 때, 뒤늦게 종료된 실행 A가 `release_schedule_claim`을 호출하면 실행 B의 활성 claim 키를 무단 삭제하는 경합이 발생했습니다.
2. **실패 결과 Dict 반환 시 Claim 조기 소멸 결함**:
   - `run_automation_pipeline`은 내부 오류 발생 시 예외를 던지지 않고 `status=failed` dict를 반환할 수 있습니다.
   - 기존 `nightly_schedule_task`는 반환 dict의 status를 확인하지 않고 무조건 `release_schedule_claim`을 호출하여, 실패 상태임에도 claim이 즉시 소멸되어 컨테이너 재시작 루프에 의한 수집 재시도를 방어하지 못했습니다.
   - 또한 후속 집계 실패로 `partial_success`가 된 경우에도 claim이 해제되는 누수가 존재했습니다.
3. **실패 응답 Dict 내 중복 `error` 키**:
   - `development_data_refresh_task`의 Redis 실패 응답 dict에서 `claim.to_dict()` 내부에 이미 `error` 키가 포함되어 있음에도 최상위에 `"error": claim.detail`을 중복 작성하는 스키마 불일치가 있었습니다.

---

## 2. 해결 설계 및 단일 실행 계약 (Single Execution Contract)

### 2.1 고유 소유 토큰(UUID) 및 Redis Lua 원자 비교-삭제 (CAS)
- `acquire_schedule_claim` 호출 시마다 고유 UUID 소유 토큰(`token = uuid.uuid4().hex`)을 생성하여 Redis JSON payload(`{"owner": ..., "token": ..., "claimed_at": ..., "ttl": ...}`)에 포함합니다.
- `ScheduleClaimResult` 데이터클래스에 `token: str | None` 필드를 추가하여 획득 성공 시 호출자에게 안전하게 반환합니다.
- 해제(`release_schedule_claim`)는 GET 후 DEL과 같은 다단계 조합이 아니라, Redis 서버 내부에서 단일 명령으로 실행되는 Lua 스크립트(`RELEASE_SCHEDULE_CLAIM_SCRIPT`)를 통해 수행합니다:
  ```lua
  local val = redis.call('GET', KEYS[1])
  if not val then
      return 0
  end
  local ok, data = pcall(cjson.decode, val)
  if ok and type(data) == 'table' and data['token'] == ARGV[1] then
      return redis.call('DEL', KEYS[1])
  else
      return 0
  end
  ```
- 소유 토큰이 누락되었거나 일치하지 않는 경우, 또는 키가 이미 삭제된 경우에는 해제를 거부(False 반환)하고 후속 실행의 claim을 온전히 보존합니다.

### 2.2 정상 성공(Success) 한정 해제 및 실패/부분실패 시 TTL 쿨다운 유지
- `nightly_schedule_task`와 `development_data_refresh_task` 모두 파이프라인 결과 dict의 `status`가 `"success"`가 아니면(`status=failed` 또는 `partial` 등) 후속 단계를 중단하고 즉시 반환하며 `release_schedule_claim`을 호출하지 않습니다.
- 후속 집계(`_rebuild_ranking_snapshots`, `_rebuild_institution_stats`) 실패로 `_mark_followup_failures`에 의해 최종 상태가 `"partial_success"`로 전환된 경우에도 claim을 해제하지 않습니다.
- 오직 파이프라인과 후속 집계가 전량 정상 완료(`status == "success"`)된 경우에만 획득한 자기 토큰(`claim.token`)으로 claim을 해제합니다. 실패 시에는 claim이 6시간 TTL 동안 유지되어 재시작 루프에 의한 외부 API 부하를 원천 차단합니다.

### 2.3 실패 응답 Dict 정규화
- `development_data_refresh_task` 및 `nightly_schedule_task`의 Redis 장애 시 반환 dict에서 최상위 중복 `error` 키를 제거하고, 구조화된 `claim: claim.to_dict()`를 통해 detail 및 error 원인을 단일하게 제공하도록 정규화하였습니다.

---

## 3. 변경 파일 내역

| 파일 경로 | 변경 구분 | 주요 내용 |
| --- | :---: | --- |
| `src/tasks/scheduled_tasks.py` | 수정 | `ScheduleClaimResult` token 필드 추가, acquire 시 UUID 발급, Lua 스크립트 기반 원자적 token 비교-삭제 구현, nightly/refresh 실패/partial 시 claim 유지 및 중복 error 키 제거 |
| `tests/fake_redis.py` | 수정 | `FakeRedisClient`에 Lua eval 메서드 구현 (JSON 디코딩 및 token 일치 시 원자 삭제) |
| `tests/test_schedule_catchup.py` | 수정 | 소유 토큰 원자 해제, Stale owner 경합 차단, pipeline 실패 dict 시 claim 유지, partial 시 claim 유지, 성공 시 정상 해제 등 7개 회귀 테스트 추가 (총 51개 테스트로 확대) |
| `docs/ops/scheduling.md` | 수정 | 원자 claim 명세에 고유 소유 토큰 및 Lua 비교-삭제 계약, 실패/부분실패 claim 유지 쿨다운 계약 반영 |
| `docs/analysis/task_0bba466af5f3.md` | 수정 | 선행 재작업 보고서의 claim 해제 계약 갱신 및 Level 3 후속 재작업 인계 섹션 추가 |
| `docs/analysis/task_4b88e29dc3f9.md` | 신규 | 본 재작업 종합 분석 및 6대 체크리스트 점검 보고서 작성 |

---

## 4. 검증 결과

### 4.1 Targeted Tests 검증
- 명령: `uv run pytest tests/test_scheduled_tasks.py tests/test_schedule_catchup.py tests/test_mlops_notifier.py`
- 결과: **51 passed in 0.35s** (종료 코드 0)
  - `tests/test_scheduled_tasks.py`: 14 passed
  - `tests/test_schedule_catchup.py`: 26 passed (+7 passed)
  - `tests/test_mlops_notifier.py`: 11 passed

### 4.2 오프로드 연계 검증
- 명령: `uv run pytest tests/test_task_offload_scheduled.py`
- 결과: **2 passed in 0.06s** (종료 코드 0)

### 4.3 린터 검증
- 명령: `uv run ruff check src/tasks/scheduled_tasks.py tests/test_schedule_catchup.py tests/fake_redis.py`
- 결과: **All checks passed!** (종료 코드 0)

### 4.4 에이전트 규칙 검증
- 명령: `python3 scripts/validate_agent_rules.py --quiet`
- 결과: **검증 통과: 20/20 건** (종료 코드 0)

---

## 5. 리뷰 체크리스트 자체 점검

| 항목 ID | 점검 질문 | 판정 | 근거 |
| --- | --- | :---: | --- |
| `ownership_safe_release` | 이전 실행이 토큰 비교 없이 후속 실행의 claim을 삭제할 수 있는 경로가 남는가 | **통과 (No)** | `release_schedule_claim`에서 Redis Lua 스크립트를 통해 `data.token == token` 원자 비교 후 일치할 때만 DEL 수행. stale runner 테스트 통과 확인. |
| `failed_outcome_release` | pipeline이 예외 없이 failed 또는 partial 상태를 반환했을 때 claim이 해제되는가 | **통과 (No)** | `nightly` 및 `refresh` 모두 `outcome.get("status") != "success"` 시 즉시 반환하며 release 미호출. 후속 재실행이 `already_claimed`로 차단됨을 테스트로 확인. |
| `success_claim_leak` | 정상 success 완료에서도 자기 claim이 TTL까지 불필요하게 남는가 | **통과 (No)** | 정상 success 완료 시 자기 토큰을 전달하여 `release_schedule_claim` 호출, 키가 즉시 삭제되고 후속 실행 정상 가능함을 확인. |
| `external_test_state` | 추가 테스트가 실제 Redis, DB, Docker 또는 실행 순서에 의존하는가 | **통과 (No)** | `FakeRedisConnection`과 격리 fixture로만 검증하여 외부 인프라 없이 결정론적으로 0.35초 내 통과. |
| `report_contract` | 정확한 ORCA_WORKER_DONE_V2 JSON 보고서가 지정 경로에 없거나 실제 커밋·검증과 불일치하는가 | **통과 (No)** | 지정된 `.orca/capsules/rework_schedule_claim_ownership/worker_done.json` 경로에 정확한 스키마로 작성. |
| `scope_exceeded` | 허용된 파일 밖을 수정하거나 새 의존성을 추가했는가 | **통과 (No)** | 허용된 파일 범위(`scheduled_tasks.py`, `test_schedule_catchup.py`, `fake_redis.py`, `scheduling.md`, `task_0bba466af5f3.md`, `task_4b88e29dc3f9.md`) 내에서만 수정. 새 패키지 추가 0건. |

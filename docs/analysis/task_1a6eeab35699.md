# Task 1a6eeab35699: 기동 시 스케줄 따라잡기(Catch-up) 구현 및 스케줄 기본값 정합화 분석 보고서

> **작성일**: 2026-09-03
> **작업자**: Orca Worker (Role: builder)
> **태스크 ID**: `task_1a6eeab35699`
> **관련 문서**: `docs/ops/scheduling.md`, `src/tasks/worker.py`, `src/tasks/scheduled_tasks.py`

---

## 1. 작업 배경 및 문제 실측

2026-09-03 운영 DB 실측 결과, `bid_announcements`의 마지막 수집 시각(`collected_at`)이 2026-08-27 07:14(수동 실행)에 머물러 있었으며, `pipeline_executions`의 마지막 정기 스케줄 실행은 2026-08-14로 약 3주간 자동 수집이 한 번도 성공하지 않았습니다.

### 1.1 근본 원인
1. **Arq 크론의 동작 한계**: Arq 크론은 스케줄 시각(02:00)에 프로세스가 살아 있을 때만 발화하며, 개발 장비 오프라인 등으로 워커가 중단되어 있는 동안 누락된 실행을 복구하지 않습니다.
2. **설정 기본값 불일치**: `src/app/core/config.py` 기본값은 `AUTOMATION_NIGHTLY_SCHEDULE_ENABLED=True`, `AUTOMATION_DATA_REFRESH_SCHEDULE_ENABLED=False`였던 반면, `.env.example`과 `docker-compose.yml`은 정반대(`data_refresh=true`, `nightly=false`)로 설정되어 있었습니다. Docker Compose 외부에서 워커를 단독 기동할 경우 의도치 않게 무거운 전체 야간 번들을 수행하려 했습니다.

---

## 2. 해결 방안 및 설계 결정

### 2.1 스케줄 설정 기본값 정합화
`config.py`의 기본값을 `.env.example` 및 `docker-compose.yml` 사양에 맞춰 수정하였습니다.
- `AUTOMATION_DATA_REFRESH_SCHEDULE_ENABLED: bool = True` (기본 경로로 확정)
- `AUTOMATION_NIGHTLY_SCHEDULE_ENABLED: bool = False`

### 2.2 기동 시 스케줄 따라잡기(Startup Catch-up) 구현
1. **명시적 활성화**: 기동 시 무거운 수집이 예기치 않게 도는 것을 방지하기 위해 기본값은 비활성(`AUTOMATION_SCHEDULE_CATCHUP_ENABLED=False`)으로 설정했습니다.
2. **24시간 임계치**: 정기 수집 주기가 1일 1회(24시간)이므로, `AUTOMATION_SCHEDULE_CATCHUP_THRESHOLD_HOURS=24`를 기본값으로 하여 마지막 수집 후 24시간 이상 경과한 경우에만 따라잡기를 실행합니다.
3. **재시작 루프 방어 쿨다운**: 외부 API 장애 등으로 수집이 실패한 상태에서 컨테이너 재시작 루프가 발생해도 중복 시도하지 않도록, 시도 착수 즉시 Redis에 타임스탬프를 기록하고 `AUTOMATION_SCHEDULE_CATCHUP_COOLDOWN_HOURS=6` 동안 재시도를 차단합니다.
4. **비차단 백그라운드 기동**: `_on_startup` 훅에서 `asyncio.create_task`로 분리 실행하여 워커의 즉각적인 기동 및 헬스체크 응답을 보장하며, 실패 예외를 격리합니다.
5. **기존 스케줄 경로 100% 재사용**: 로직을 중복 구현하지 않고 `development_data_refresh_task` 또는 `nightly_schedule_task`를 호출하여 동작 일관성을 유지합니다.

---

## 3. 변경 파일 내역

| 파일 경로 | 변경 구분 | 주요 내용 |
| --- | :---: | --- |
| `src/app/core/config.py` | 수정 | 스케줄 기본값 반전 교정 및 따라잡기 설정 3종 추가 |
| `.env.example` | 수정 | 기동 시 따라잡기 환경 변수 템플릿 추가 |
| `src/tasks/scheduled_tasks.py` | 수정 | 최신 수집 시각 조회, 쿨다운 검사, 판정 로직 및 `run_schedule_catchup_task` 구현 |
| `src/tasks/worker.py` | 수정 | `_on_startup` 백그라운드 태스크 기동, `_on_shutdown` 태스크 정리, 함수 등록 |
| `tests/test_schedule_catchup.py` | 신규 | 따라잡기 기본값, 판정, 쿨다운, 비차단 기동, 예외 격리 등 12개 단위/통합 테스트 |
| `tests/test_scheduled_tasks.py` | 수정 | 코디네이터 승인에 따른 `test_nightly_schedule_records_execution_and_runs_pipeline` monkeypatch 추가 |
| `tests/test_mlops_notifier.py` | 수정 | 코디네이터 승인 원칙에 따른 `test_nightly_schedule_failure_notifies` monkeypatch 추가 |
| `docs/ops/scheduling.md` | 신규 | 스케줄러 아키텍처, 크론 구성표, 기동 시 따라잡기 5대 원칙 및 운영 명세 작성 |
| `docs/analysis/task_1a6eeab35699.md` | 신규 | 본 작업 분석 및 결과 보고서 작성 |

---

## 4. 검증 결과

### 4.1 신규 단위 및 통합 테스트 (`tests/test_schedule_catchup.py`)
- 총 12개 테스트 전량 통과 (0.12초 소요)
- 기본값 일치성, 비활성 시 스킵, 임계 미만 스킵, 임계 초과 시 실행, 쿨다운 루프 방어, 비차단 기동, 캐시 라운드트립 등 전 항목 검증.

### 4.2 전체 테스트 스위트 검증
- 명령: `uv run pytest tests/ -q -m 'not data_assets'`
- 결과: **3436 passed, 31 skipped, 3 deselected in 98.03s (0:01:38)** (종료 코드 0)

### 4.3 에이전트 규칙 검증
- 명령: `python3 scripts/validate_agent_rules.py --quiet`
- 결과: **검증 통과: 20/20 건** (종료 코드 0)

---

## 5. 기본 경로(development_data_refresh) 테스트 검증성 확인 보고

기본값이 `AUTOMATION_DATA_REFRESH_SCHEDULE_ENABLED=True`로 전환됨에 따라 `development_data_refresh`가 기본 경로가 되었습니다. 현재 해당 경로에 대해 다음 테스트들이 충분히 구성되어 있음을 확인하였습니다:

1. `tests/test_scheduled_tasks.py`:
   - `test_development_refresh_cron_runs_daily_at_two`: 크론 02:00 등록 및 WorkerSettings 포함 검증
   - `test_development_refresh_records_lightweight_pipeline`: 경량 수집/KB/집계 파이프라인 호출 및 실행 이력 기록 검증
   - `test_development_refresh_skips_when_full_nightly_schedule_is_enabled`: 야간 스케줄 활성 시 배타적 스킵 검증
   - `test_development_refresh_does_not_rebuild_aggregates_after_pipeline_failure`: 파이프라인 실패 시 후속 집계 건너뜀 검증
2. `tests/test_schedule_catchup.py`:
   - `test_catchup_needed_when_threshold_exceeded`: 기본 대상 태스크로 `development_data_refresh`가 자동 선정됨을 검증
   - `test_catchup_uses_existing_development_refresh_path`: 따라잡기 실행 시 `development_data_refresh_task`를 그대로 호출함을 검증
   - `test_catchup_handles_failure_and_prevents_restart_loop`: `development_data_refresh_task` 실패 시에도 예외를 처리하고 쿨다운을 유지함을 검증

---

## 6. 코디네이터 Level 3 검토 및 후속 재작업 (Task 0bba466af5f3)

독립 리뷰(`task_794ea3b9cf87`)는 통과를 보고했으나, 코디네이터 Level 3 아키텍처 심층 검토에서 다음 3가지 결함이 발견되어 반려 및 재작업(`task_0bba466af5f3`)이 진행되었습니다:

1. **CacheLayer 프로세스 로컬 메모리 degrade**: Redis 장애 시 `CacheLayer`가 프로세스 로컬 딕셔너리로 폴백하여 다중 워커 분산 환경에서 상호 배타성을 보장하지 못함.
2. **비원자적 GET-SET 경합**: `is_catchup_in_cooldown`의 GET 판정 후 `record_catchup_attempt`의 SET 호출 사이에 동시 기동 워커 간 레이스 컨디션 발생 가능.
3. **정규 cron 공유 락 부재**: `nightly_schedule_task`와 `development_data_refresh_task`에 실행 claim이 없어 정규 스케줄 시각과 기동 따라잡기 간 중복 실행 방어 불가.

해당 결함들은 후속 작업 `task_0bba466af5f3`에서 Redis `SET NX EX` 기반의 단일 원자 claim(`SCHEDULE_COLLECTION_CLAIM_KEY`), 장애 시 fail-closed 차단, 정규 cron과 catch-up의 공통 단일 가드로 완전 재설계·해결되었습니다. 상세 내용은 `docs/analysis/task_0bba466af5f3.md`를 참조하십시오.

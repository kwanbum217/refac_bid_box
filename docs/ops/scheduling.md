# Arq 스케줄러 및 기동 시 수집 따라잡기 운영 명세서

> **작성일**: 2026-09-03
> **상태**: 운영 정본
> **대상 모듈**: `src/tasks/worker.py`, `src/tasks/scheduled_tasks.py`, `src/app/core/config.py`

---

## 1. 개요

본 문서는 refac_bid_box 프로젝트의 정기 크론 스케줄 구조 및 워커 프로세스 오프라인 중 누락된 수집을 복구하기 위한 **기동 시 스케줄 따라잡기(Startup Catch-up)** 메커니즘을 정의합니다.

기존 모놀리식의 Harness 야간 파이프라인 및 Airflow 주간 재학습 DAG는 Arq 크론 기반 비동기 워커로 단일화되었습니다. 그러나 Arq 크론은 프로세스가 실행 중인 상태에서 정해진 시각(02:00 등)이 도래해야만 발화하며, 개발 장비 오프라인 등으로 워커가 중지되어 있는 동안 누락된 스케줄은 자동으로 소급 실행되지 않는 한계가 있었습니다.

이에 따라 프로세스 기동 시점에 마지막 수집 시각을 확인하고, 임계를 초과한 경우 누락된 수집을 안전하게 백그라운드로 보충 실행하는 따라잡기 메커니즘을 도입하였습니다.

---

## 2. 정기 크론 스케줄 구조

워커 프로세스는 `src.tasks.worker.WorkerSettings`에 정의된 크론 규칙에 따라 주기적인 자동화 작업을 수행합니다.

| 스케줄 태스크 | 발화 시각 | 기본 활성 여부 | 주요 작업 내용 |
| --- | --- | :---: | --- |
| `development_data_refresh_task` | 매일 02:00 | **True** | 개발 DB 최신화 (공고/낙찰 수집, KB 갱신, 상위 N/기관이력 집계) |
| `nightly_schedule_task` | 매일 02:00 | **False** | 운영 전체 야간 번들 (수집, KB, 예측, 전체 검증, 집계 갱신) |
| `weekly_retrain_task` | 매주 월 03:00 | **False** | 카테고리별 모델 자동 재학습 파이프라인 (fan-out) |
| `drift_monitor_task` | 매일 04:00 | **False** | 7일 윈도우 개찰 데이터 기반 다차원 PSI 드리프트 모니터링 |
| `backup_schedule_task` | 매일 03:00 | **False** | MySQL/ChromaDB/가중치 정기 통합 스냅샷 백업 |

- `development_data_refresh_task`와 `nightly_schedule_task`는 상호 배타적입니다. `AUTOMATION_NIGHTLY_SCHEDULE_ENABLED=True`인 경우 `development_data_refresh_task`는 `skipped:nightly_schedule_enabled`로 안전하게 건너뜁니다.
- 개발 환경 및 도커 컴포즈 표준 구성에서는 가벼운 `development_data_refresh_task`가 기본 활성화(True)되며, 전체 검증·재학습을 수반하는 `nightly_schedule_task`는 비활성화(False)됩니다.

---

## 3. 기동 시 수집 따라잡기 (Startup Catch-up) 아키텍처

```mermaid
flowchart TD
    A["워커 기동 (_on_startup)"] --> B{"AUTOMATION_SCHEDULE_CATCHUP_ENABLED"}
    B -- False --> C["따라잡기 비활성 (건너뜀)"]
    B -- True --> D["백그라운드 비동기 태스크 생성<br/>(asyncio.create_task)"]
    D --> E["check_schedule_catchup_needed 판정"]
    E --> F{"활성 스케줄 존재 여부"}
    F -- 없음 --> G["skipped: no_active_schedule"]
    F -- 있음 --> H{"최근 시도 쿨다운 확인<br/>(6시간 이내)"}
    H -- 쿨다운 중 --> I["skipped: in_cooldown (재시작 루프 방어)"]
    H -- 쿨다운 만료 --> J["최신 bid_announcements.collected_at 조회"]
    J --> K{"경과 시간 >= 임계치<br/>(기본 24시간)"}
    K -- 미경과 --> L["skipped: threshold_not_exceeded"]
    K -- 초과 --> M["선제 쿨다운 기록<br/>(record_catchup_attempt)"]
    M --> N["기존 활성 스케줄 태스크 호출<br/>(nightly 또는 data_refresh)"]
    N --> O["실행 결과 및 근거 캐시 기록<br/>(record_schedule_result)"]
```

### 3.1 5대 설계 원칙

1. **명시적 활성화 (Disabled by Default)**:
   - 기동만으로 대량의 공고/낙찰 데이터를 외부 API로부터 수집하는 무거운 작업이 자동 발화되는 것은 의도치 않은 리소스 점유를 유발합니다.
   - 따라서 `AUTOMATION_SCHEDULE_CATCHUP_ENABLED`의 기본값은 `False`이며, 컨테이너 환경변수나 `.env`를 통해 명시적으로 켠 경우에만 동작합니다.

2. **비차단 백그라운드 기동 (Non-blocking Startup)**:
   - 데이터 수집 및 집계 파이프라인은 네트워크 및 DB 상황에 따라 수십 분이 소요될 수 있습니다.
   - 워커의 `_on_startup` 훅에서 동기(`await`)로 대기하지 않고, `asyncio.create_task`를 통해 비동기 백그라운드 태스크로 분리 실행합니다.
   - 따라잡기 작업 중 예외가 발생하더라도 워커 프로세스의 생존과 다른 Arq 큐 작업 처리에 일절 영향을 주지 않도록 예외를 완전 격리합니다.

3. **기존 스케줄 경로 단일 재사용 (Zero Logic Duplication)**:
   - 따라잡기를 위한 별도의 수집/파이프라인 로직을 중복 구현하지 않습니다.
   - 현재 활성화된 스케줄 태스크(`nightly_schedule_task` 또는 `development_data_refresh_task`)를 그대로 호출함으로써, 스케줄 실행과 따라잡기 실행의 파이프라인 동작 정합성을 100% 보장합니다.

4. **하루 주기 기반 임계치 판정 (Threshold Policy)**:
   - 공고 수집의 정상 스케줄 주기는 24시간(매일 02:00)입니다.
   - 따라서 `AUTOMATION_SCHEDULE_CATCHUP_THRESHOLD_HOURS`의 기본값은 **24시간**으로 설정됩니다. 마지막 수집 시각으로부터 24시간 이상 경과했다는 것은 최소 1회 이상의 정기 수집을 누락했음을 의미합니다.

5. **재시작 루프 방어 메커니즘 (Crash-Loop Protection & Cooldown)**:
   - 외부 API 장애, 네트워크 순단 등으로 수집이 실패한 상태에서 워커 컨테이너가 재시작을 반복할 경우, 매 기동마다 수집을 재시도하여 외부 API 쿼터를 소진하거나 부하를 가중시키는 사고가 발생할 수 있습니다.
   - 이를 방지하기 위해 따라잡기 태스크 착수 즉시 Redis 캐시에 시도 시각(`bidbox:worker:catchup_last_attempt`)을 기록하며, `AUTOMATION_SCHEDULE_CATCHUP_COOLDOWN_HOURS`(기본 6시간) 이내에는 재기동되더라도 따라잡기를 발화하지 않고 건너뜁니다.

---

## 4. 환경 변수 및 설정 명세

| 설정 키 | 타입 | 기본값 | 설명 |
| --- | :---: | :---: | --- |
| `AUTOMATION_DATA_REFRESH_SCHEDULE_ENABLED` | bool | `True` | 개발 DB 최신화 크론 활성화 (기본 경로) |
| `AUTOMATION_NIGHTLY_SCHEDULE_ENABLED` | bool | `False` | 운영 전체 야간 번들 크론 활성화 |
| `AUTOMATION_SCHEDULE_CATCHUP_ENABLED` | bool | `False` | 기동 시 누락 수집 따라잡기 활성화 |
| `AUTOMATION_SCHEDULE_CATCHUP_THRESHOLD_HOURS` | int | `24` | 수집 누락 판정 기준 경과 시간 (시간 단위) |
| `AUTOMATION_SCHEDULE_CATCHUP_COOLDOWN_HOURS` | int | `6` | 재시작 루프 방어 재시도 쿨다운 (시간 단위) |

---

## 5. 관측성 및 실행 이력 추적

따라잡기 판정 및 실행 결과는 구조화 로그와 Redis 캐시 상태 원장에 완벽히 기록됩니다.

1. **구조화 로그**:
   - 판정 시점: `스케줄 따라잡기 판정: needed={bool}, reason={str}, details={dict}`
   - 실행 착수: `스케줄 따라잡기 실행 시작 (target_task={task}, details={dict})`
   - 판단 근거(마지막 수집 시각, 경과 시간, 임계값 등)가 항상 로그에 명시되어 사후 감사(Audit)가 가능합니다.

2. **Redis 상태 원장**:
   - 키: `bidbox:worker:schedules`
   - 필드 `schedule_catchup`:
     ```json
     {
       "last_run_at": "2026-09-03T18:45:00+00:00",
       "success": true
     }
     ```

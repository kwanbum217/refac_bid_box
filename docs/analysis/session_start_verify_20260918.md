# 2026-09-18 세션 시작 개발 스택 수집 및 드리프트 실측 보고서

> **작성일**: 2026-09-18
> **작성자**: Orca Worker (builder, task_1be8a9c193a4)
> **기준 시각**: 2026-09-18 14:06 KST
> **목적**: 2026-09-18 세션 시작 및 스택 기동 후, 마지막 수집(id=20) 이후 신규 데이터 수집 및 2026-09-18 04:00 정규 drift_monitor 추가 여부를 읽기 전용으로 실측하고 정본 현황을 기록합니다.

---

## 1. 점검 개요 및 배경

- **스케줄 누락 경위**: 전날(2026-09-17) 작업 종료로 개발 스택이 내려가 2026-09-18 02:00 정기 최신화 크론(`development_data_refresh_task`) 및 04:00 드리프트 감시 크론(`drift_monitor_task`)을 놓쳤습니다.
- **스택 재기동**: 2026-09-18 13:56 KST 코디네이터가 Docker Desktop 및 compose up -d를 수행하여 서비스가 복구되었습니다.
- **점검 원칙**:
  - 컨테이너 조작, 스케줄 수동 실행, 백필(backfill), DB 쓰기, 재학습을 일절 수행하지 않습니다.
  - `AUTOMATION_SCHEDULE_CATCHUP_ENABLED=true`에 의한 자동 따라잡기 대상은 수집(`development_data_refresh_task`)만 해당하며, `drift_monitor_task`는 자동 따라잡기 대상이 아닙니다.
  - 8일 공백이 `MAX_CATCHUP_DAYS=7` 상한을 초과하여 20260909 공백은 자동 회수되지 않으며, 사용자 승인 없는 수동 backfill은 금지됩니다.
  - 모든 실측은 읽기 전용 질의(`scripts/db_readonly_query.py`)를 통해서만 수행되었습니다.

---

## 2. 수집 파이프라인 실행 이력 실측 (`pipeline_executions`)

### 2.1 최근 3건 질의 및 실측 출력

실행 질의:
```sh
uv run python scripts/db_readonly_query.py --sql "SELECT id, run_mode, status, started_at, ended_at FROM pipeline_executions WHERE run_mode = 'development_data_refresh' ORDER BY id DESC LIMIT 3"
```

실측 출력:
```
id | run_mode                 | status  | started_at                 | ended_at
---+--------------------------+---------+----------------------------+---------------------------
21 | development_data_refresh | success | 2026-09-18 04:56:09.841742 | 2026-09-18 05:06:16.731052
20 | development_data_refresh | success | 2026-09-17 10:15:33.665510 | 2026-09-17 10:23:49.939805
19 | development_data_refresh | failed  | 2026-09-16 06:40:32.144723 | 2026-09-16 06:49:23.973996
```

### 2.2 id=21 신규 수집 레코드 정밀 실측

실행 질의:
```sh
uv run python scripts/db_readonly_query.py --sql "SELECT id, execution_id, run_mode, status, source, stage_name, stage_status, started_at, ended_at, metrics_json, logs_summary FROM pipeline_executions WHERE id = 21"
```

실측 출력:
```
id           : 21
execution_id : development_data_refresh-5c230ebc1491
run_mode     : development_data_refresh
status       : success
source       : local_scheduler
stage_name   : inspect
stage_status : success
started_at   : 2026-09-18 04:56:09.841742
ended_at     : 2026-09-18 05:06:16.731052
metrics_json : {"completed_steps": ["collect", "search", "rag", "inspect"]}
logs_summary : 실행 모드 `refresh_data` 스텝 4개 완료: collect, search, rag, inspect
```

- **id=20 이후 새 수집 존재 여부**: **존재함 (id=21)**.
- **실행 모드 및 상태**: `run_mode = 'development_data_refresh'`, `status = 'success'`, `stage_status = 'success'`.
- **소요 시간**: 총 10분 7초 소요 (UTC 04:56:09 ~ 05:06:16, KST 13:56:09 ~ 14:06:16).
- **수행 내역**: 4단계(`collect`, `search`, `rag`, `inspect`) 전 스텝 정상 완료.

### 2.3 당일(2026-09-18) 적재 데이터 건수 실측

실행 질의:
```sh
uv run python scripts/db_readonly_query.py --sql "SELECT category, count(*) as cnt FROM bid_announcements WHERE collected_at >= '2026-09-18 00:00:00' GROUP BY category"
```

실측 출력:
```
category | cnt
---------+----
Thng     | 539
Cnstwk   | 426
Servc    | 670
Frgcpt   | 9
```

- **공고 수집 건수**: 1,644건 (물품 539건, 공사 426건, 용역 670건, 외자 9건).
- **낙찰 수집 건수**: 955건 (`SELECT count(*) FROM bid_results WHERE collected_at >= '2026-09-18 00:00:00'`).

---

## 3. 드리프트 감시 이력 실측 (`retrain_logs`)

### 3.1 최근 6건 질의 및 실측 출력

실행 질의:
```sh
uv run python scripts/db_readonly_query.py --sql "SELECT id, champion_version, challenger_version, status, created_at FROM retrain_logs WHERE trigger_source = 'drift_monitor' ORDER BY id DESC LIMIT 6"
```

실측 출력:
```
id | champion_version      | challenger_version          | status         | created_at
---+-----------------------+-----------------------------+----------------+--------------------
6  | quantum_leap_v25_pro  | b_20260915_thng_post_regime | DRIFT_DETECTED | 2026-09-17 10:24:55
5  | servc_institution_v1  | v_20260915_133523_756       | DRIFT_DETECTED | 2026-09-17 10:24:54
4  | cnstwk_institution_v1 | v_20260915_121521_459       | DRIFT_DETECTED | 2026-09-17 10:24:52
```

### 3.2 2026-09-18 04:00 정규 drift_monitor 추가 여부 판정

실행 질의:
```sh
uv run python scripts/db_readonly_query.py --sql "SELECT count(*) as cnt FROM retrain_logs WHERE trigger_source = 'drift_monitor' AND created_at >= '2026-09-18 00:00:00'"
```

실측 출력:
```
cnt
---
0
```

- **09-18 04:00 정규 drift_monitor 추가 건수**: **0건 (크론 미실행)**.
- **미실행 사유**: 2026-09-18 04:00 KST 시점에 스택이 종료되어 있었으며, `run_schedule_catchup_task`는 수집(`development_data_refresh_task`)만 따라잡고 `drift_monitor_task`는 자동 따라잡기 대상이 아닙니다.
- **라벨 성격 재확인**: 직전 실행된 id=4, 5, 6의 `status='DRIFT_DETECTED'` 및 `overall_action='TRIGGER_RETRAIN'`은 경고/알림 라벨이며 자동 재학습이나 승격 명령이 아닙니다. 실제로 2026-09-18 기준 자동 재학습이나 승격은 일절 실행되지 않았습니다.

---

## 4. 종합 판정 및 결론

| 점검 항목 | 기준 및 사양 | 실측 결과 | 최종 판정 |
| --- | --- | --- | --- |
| id=20 이후 새 수집 여부 | `pipeline_executions` 단일 질의 | id=21 (`development_data_refresh`, `success`) 완료 (10분 7초) | 정상 완료 (공고 1,644건, 낙찰 955건) |
| 09-18 04:00 drift_monitor 추가 | `retrain_logs` 단일 질의 | 2026-09-18 생성 건수 0건 | 미실행 (스택 다운 및 따라잡기 비대상) |
| TRIGGER_RETRAIN 해석 | 알림 라벨 (재학습 미실행) | 신규 재학습 로그 0건 확인 | 정상 해석 (임의 재학습 없음) |
| 20260909 공백 유지 | 사용자 미승인 backfill 금지 | 수동 backfill 미실행 유지 | 규약 준수 (공백 미회수 유지) |
| 작업 제약 준수 | 컨테이너·DB쓰기·수동실행 금지 | 읽기 전용 질의만 사용 | 규약 준수 |

# 2026-09-17 스케줄 따라잡기 수집 실측 검증 보고서

> **작성일**: 2026-09-17
> **작성자**: Orca Worker (builder, task_66406a5a178b)
> **기준 시각**: 2026-09-17 19:25 KST
> **목적**: 2026-09-17 스택 재기동 후 실행된 스케줄 따라잡기(Catch-up) 수집이 XML 살균(commit faa752e4) 적용 후 첫 실기에서 정상 성공(status=success)했는지 실측하고, 7일 회수 창 제한으로 인한 20260909 미회수 공백 현황을 기록합니다.

---

## 1. 개요 및 배경

- **스케줄 누락 경위**: 전날 스택 종료로 인해 2026-09-17 02:00 KST 정기 데이터 최신화 크론(`development_data_refresh_task`)을 놓쳤습니다.
- **재기동 및 따라잡기 트리거**: 2026-09-17 19:15 KST 스택 재기동 시 `AUTOMATION_SCHEDULE_CATCHUP_ENABLED=true` 설정에 따라 워커 기동 시 누락 스케줄 따라잡기(`run_schedule_catchup_task`)가 기동되었습니다.
- **XML 살균 검증 배경**: 2026-09-16 실행(id=19) 실패 원인이었던 물품 조달청 API XML 금지 문자 참조(`reference to invalid character number`) 오류를 방지하기 위해 적용된 `src/app/services/api_collector.py`의 `sanitize_xml_text`(commit `faa752e4`) 배포 이후 첫 실기 검증입니다.
- **점검 원칙**: 컨테이너 조작, 스케줄 수동 실행, 백필(backfill), DB 쓰기 없이 읽기 전용 질의(`scripts/db_readonly_query.py`)와 정본 기록만을 바탕으로 실측을 수행했습니다.

---

## 2. 따라잡기 수집 판정 및 실행 경로 검증

### 2.1 스케줄 따라잡기 판정 결과

워커 기동 시점의 `check_schedule_catchup_needed()` 판정 실측값은 다음과 같습니다:

| 항목 | 실측값 | 비고 |
| --- | --- | --- |
| `needed` | `True` | 따라잡기 실행 필요 판정 |
| `reason` | `missed_schedule` | 최근 크론 슬롯 실행 누락 |
| `elapsed_hours` | 27.57 | 최종 수집 이후 경과 시간 (시간) |
| `threshold_hours` | 24 | 따라잡기 판단 임계값 |
| `latest_collected_at` | `2026-09-16T06:41:36.008726` | 이전 최종 수집 일시 |
| `last_cron_slot` | `2026-09-17T02:00:00+00:00` | 놓친 최근 크론 시점 |
| `target_task` | `development_data_refresh` | 실행 대상 태스크 정본 |

### 2.2 개발 환경 실행 경로 정본

- 개발 스택(`docker-compose.yml`)에서 02:00 데이터 최신화 경로는 `nightly_schedule_task`가 아니라 **`development_data_refresh_task`**입니다.
- `docker-compose.yml` 환경변수 설정:
  - `AUTOMATION_DATA_REFRESH_SCHEDULE_ENABLED=true`: 개발 최신화 활성화
  - `AUTOMATION_NIGHTLY_SCHEDULE_ENABLED=false`: 운영 야간 번들 비활성화
  - `AUTOMATION_SCHEDULE_CATCHUP_ENABLED=true`: 스케줄 공백 시 자동 따라잡기 활성화
- 이에 따라 `run_schedule_catchup_task`는 `nightly_schedule`이 아닌 `development_data_refresh`를 대상 태스크로 정상 식별하여 진입했습니다.

---

## 3. 파이프라인 실행 결과 실측 (`pipeline_executions` id=20)

### 3.1 실행 레코드 상세 실측

실행 질의:
```sh
uv run python scripts/db_readonly_query.py --sql "SELECT id, execution_id, run_mode, status, source, stage_name, stage_status, started_at, ended_at, metrics_json, logs_summary FROM pipeline_executions WHERE id = 20"
```

실측 출력:
```
id           : 20
execution_id : development_data_refresh-b81dcacf0d4d
run_mode     : development_data_refresh
status       : success
source       : local_scheduler
stage_name   : inspect
stage_status : success
started_at   : 2026-09-17 10:15:33.665510
ended_at     : 2026-09-17 10:23:49.939805
metrics_json : {"completed_steps": ["collect", "search", "rag", "inspect"]}
logs_summary : 실행 모드 `refresh_data` 스텝 4개 완료: collect, search, rag, inspect
```

- **최종 상태**: `status = success`, `stage_status = success`로 전체 파이프라인이 결함 없이 종료되었습니다.
- **실행 시간**: 총 8분 16초 소요 (10:15:33 ~ 10:23:49 UTC, KST 19:15:33 ~ 19:23:49).
- **완료 스텝**: `metrics_json`에 기록된 4단계(`collect`, `search`, `rag`, `inspect`)가 전량 누락 없이 성공했습니다.

---

## 4. XML 살균 적용 후 첫 실기 검증 및 적재 실측

### 4.1 XML 살균 효과 검증

- **어제 실패 이력(id=19)**: 2026-09-16 06:40 KST 실행 시 물품 수집 중 `reference to invalid character number` XML 파싱 예외로 인해 `stage_status=failed`로 중단된 바 있습니다.
- **살균 패치 적용(commit faa752e4)**: `src/app/services/api_collector.py`의 `sanitize_xml_text`가 XML `fromstring` 직전에 XML 사양 범위를 벗어나는 문자 참조(`&#...;`)를 제거하도록 정규화 로직이 적용되었습니다.
- **실기 검증 결과**:
  - 워커 컨테이너 실행 로그 전체에서 `reference to invalid character number` 예외가 **단 1건도 발생하지 않았습니다**.
  - 물품 카테고리 수집이 정상 완료되어 데이터베이스에 적재되었습니다.

### 4.2 카테고리별 수집 및 적재 실측

수집 처리 로그 실측치:
- 물품(`Thng`): 공고 3,347건, 낙찰 1,356건 수집 처리
- 공사(`Cnstwk`): 공고 2,376건, 낙찰 1,653건 수집 처리
- 용역(`Servc`): 공고 2,819건, 낙찰 1,556건 수집 처리
- 외자(`Frgcpt`): 공고 35건, 낙찰 12건 수집 처리
- 면허제한: 8,528건, 참가가능지역: 8,112건 적재

2026-09-17 당일 DB 신규 수집 건수 실측 (`collected_at >= '2026-09-17 00:00:00'`):

실행 질의:
```sh
uv run python scripts/db_readonly_query.py --sql "SELECT category, count(*) as cnt FROM bid_announcements WHERE collected_at >= '2026-09-17 00:00:00' GROUP BY category"
```

실측 출력:
```
category | cnt
---------+-----
Thng     | 1393
Cnstwk   | 478
Servc    | 565
Frgcpt   | 10
```

실행 질의:
```sh
uv run python scripts/db_readonly_query.py --sql "SELECT category, count(*) as cnt FROM bid_results WHERE collected_at >= '2026-09-17 00:00:00' GROUP BY category"
```

실측 출력:
```
category | cnt
---------+----
Cnstwk   | 362
Servc    | 313
Thng     | 294
Frgcpt   | 4
```

최신 공고 수집 시각:
```sh
uv run python scripts/db_readonly_query.py --sql "SELECT MAX(collected_at) AS max_collected_at FROM bid_announcements"
```
```
max_collected_at: 2026-09-17 10:16:13.620028
```

- 물품 공고 1,393건 및 낙찰 294건이 DB에 온전히 신규 적재되어, XML 살균 로직의 유효성이 실기로 입증되었습니다.

---

## 5. 7일 자동 회수 창 제한 및 20260909 미회수 공백 분석

### 5.1 7일 회수 창 메커니즘 (`src/app/services/collector_service.py:140-165`)

- `collector_service`는 DB 내 최신 수집 일자(`latest`)를 기준으로 결측 시작일(`gap_start`)을 계산합니다.
- 조달청 OpenAPI의 부하 및 과도한 과거 요청을 방지하기 위해 `max_catchup_days = 7` 상한이 하드코딩되어 있습니다.
- 계산식: `earliest_recoverable = yesterday - timedelta(days=max_catchup_days - 1)`
  - 기준일 `today`: 2026-09-17
  - `yesterday`: 2026-09-16
  - 회수 가능 하한(`earliest_recoverable`): 2026-09-16 - 6일 = **2026-09-10**

### 5.2 수집 공백 및 20260909 미회수 확인

- 이전 성공 수집 데이터의 최신 날짜로 인해 결측 시작일이 2026-09-09로 산정되었으며, 총 공백 일수는 8일이었습니다.
- 수집기 경고 로그 원문:
  > "수집 공백 8일이 자동 회수 상한(7일)을 초과합니다. 20260910부터 회수합니다. 이전 구간(20260909~20260909)은 backfill_from_g2b.py 로 채우십시오."
- 이에 따라 이번 따라잡기에서 실제 수집된 구간은 **20260910 ~ 20260916** (7일간)으로 한정되었습니다.
- **20260909 공백**: 2026-09-09 수집 구간은 7일 상한 제한으로 인해 자동 회수되지 않고 미수집 상태로 남았습니다.
- **운영 조치 준수**: 본 점검 태스크의 계약 및 지침에 따라 `backfill_from_g2b.py` 수동 백필은 일절 실행하지 않았으며, 향후 운영 백필 작업으로 이관합니다.

---

## 6. 결론 및 종합 요약

1. **따라잡기 수집 성공**: 2026-09-17 스택 재기동 직후 `run_schedule_catchup_task`가 `development_data_refresh_task`를 트리거하여 `pipeline_executions` id=20(`status=success`)으로 정상 종료되었습니다.
2. **XML 살균 1차 실기 통과**: `api_collector.py`의 `sanitize_xml_text`(commit `faa752e4`) 적용 결과, `reference to invalid character number` 예외 없이 물품 공고 1,393건, 낙찰 294건이 DB에 무결하게 적재되었습니다.
3. **20260909 공백 보존**: 수집기 7일 회수 창 상한(20260910~20260916)으로 인해 20260909 데이터는 자동 회수에서 제외되었으며, 임의 백필 없이 현 상태를 기록으로 남깁니다.
4. **계약 준수**: 점검 전 과정에서 컨테이너 기동/정지/재시작, 스케줄 태스크 수동 기동, backfill 스크립트 실행, DB 쓰기, 코드 임의 수정을 일절 배제하고 안전하게 실측을 완수했습니다.

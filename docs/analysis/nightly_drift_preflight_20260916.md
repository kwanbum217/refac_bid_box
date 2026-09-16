# 2026-09-17 야간 데이터 최신화 및 PSI 드리프트 감시 사전점검 보고서

> **작성일**: 2026-09-16
> **작성자**: Orca Worker (builder, task_d42fd9ca805f)
> **기준 시각**: 2026-09-16 18:48 KST
> **목적**: 2026-09-17 02:00 데이터 최신화 및 04:00 드리프트 감시 첫 실행을 앞두고, 현재 시점의 서비스 스택, 크론 설정, baseline 아티팩트, 평가 윈도우 표본, 실행 이력을 실측하고 04:00 이후 판정 확인 절차와 Thng 원인 분기를 정의합니다.

---

## 1. 개요 및 점검 배경

- 2026-09-16 세션 인수인계(`docs/handoff/session_20260916_rollout_release_workers.md`) 시점 개발 DB의 `retrain_logs` 내 `trigger_source='drift_monitor'` 건수는 **0건**이었습니다.
- 세 개 카테고리(`Cnstwk`, `Servc`, `Thng`)의 baseline 아티팩트가 모두 준비된 상태에서, 2026-09-17 04:00 KST에 첫 주기적 드리프트 감시(`drift_monitor_task`)가 실행될 예정입니다.
- 본 사전점검에서는 스케줄 실행, 컨테이너 조작, 데이터 쓰기 없이 읽기 전용 질의와 API 엔드포인트 실측만으로 스택 상태를 확인하고, 04:00 이후 Thng 모델이 `INSUFFICIENT_DATA`가 아닌 실제 PSI 판정(`STABLE` 또는 `DRIFT_DETECTED`)으로 남는지 확인하는 절차와 원인 분기를 명시합니다.

---

## 2. 서비스 스택 및 헬스 엔드포인트 실측

- 헬스 체크 엔드포인트(`http://localhost:8000/api/v1/health/ready`) 실측 결과 HTTP 200 정상 응답을 반환했습니다.
- 모든 핵심 의존성(MySQL, Redis, Meilisearch, Model Registry, ChromaDB, LLM)이 정상(`ok: true`) 상태이며 웜업이 완료되었습니다.

### 2.1 실측 명령 및 응답

실행 명령:
```sh
curl -s -w "\nHTTP_STATUS: %{http_code}\n" http://localhost:8000/api/v1/health/ready
```

실측 출력 결과:
```json
{
  "status": "ready",
  "checks": {
    "mysql": { "ok": true, "detail": null, "latency_ms": 7.317 },
    "redis": { "ok": true, "detail": null, "latency_ms": 7.66 },
    "meilisearch": { "ok": true, "detail": null, "latency_ms": 13.248 },
    "model_registry": { "ok": true, "detail": null, "latency_ms": 11.962 },
    "chromadb": { "ok": true, "detail": null, "latency_ms": 42.345 }
  },
  "warmup": {
    "completed": true,
    "started": true,
    "details": {
      "llm": { "ok": true, "error": null },
      "predictor": { "ok": true, "error": null },
      "vector_search": { "ok": true, "error": null }
    }
  },
  "llm": {
    "ok": true,
    "provider": "ollama",
    "detail": null,
    "latency_ms": 12.354
  }
}
HTTP_STATUS: 200
```

---

## 3. 02:00 데이터 최신화 경로 실측 및 검증

### 3.1 개발 환경 실행 경로 정본

- 개발 스택(`docker-compose.yml`)의 매일 02:00 데이터 최신화는 운영 야간 번들인 `nightly_schedule_task`가 아니라 **`development_data_refresh_task`**가 담당합니다.
- `docker-compose.yml` 환경변수 설정:
  - `AUTOMATION_DATA_REFRESH_SCHEDULE_ENABLED=true`: 개발 데이터 최신화 활성화
  - `AUTOMATION_NIGHTLY_SCHEDULE_ENABLED=false`: 운영 야간 번들 비활성화
  - `AUTOMATION_SCHEDULE_CATCHUP_ENABLED=true`: 스케줄 공백 시 1회 따라잡기 활성화
  - `TZ=Asia/Seoul`: KST 기준 스케줄 고정
- 코드 동작 원리 (`src/tasks/scheduled_tasks.py:220-225, 296-306`):
  - `nightly_schedule_task`: `AUTOMATION_NIGHTLY_SCHEDULE_ENABLED`가 false이므로 진입 즉시 `status='skipped', reason='disabled'`를 반환합니다.
  - `development_data_refresh_task`: `AUTOMATION_DATA_REFRESH_SCHEDULE_ENABLED`가 true이고 `AUTOMATION_NIGHTLY_SCHEDULE_ENABLED`가 false이므로 수집, KB 갱신, 후속 집계(순위 스냅샷, 비교 통계 스냅샷, 기관 이력 집계, MySQL 영속 통계 신선도, 복원 드릴 점검)를 정상 실행합니다.

### 3.2 크론 스케줄 등록 상태 (`src/tasks/worker.py:396-405`)

| 태스크명 | 실행 시각 (KST) | 타임아웃 | 활성화 여부 | 동작 상태 |
| --- | --- | --- | --- | --- |
| `development_data_refresh_task` | 매일 02:00 | 10,800초 (3시간) | `AUTOMATION_DATA_REFRESH_SCHEDULE_ENABLED=true` | 정상 실행 |
| `nightly_schedule_task` | 매일 02:00 | 10,800초 (3시간) | `AUTOMATION_NIGHTLY_SCHEDULE_ENABLED=false` | 건너뜀 (skipped) |

### 3.3 과거 파이프라인 실행 이력 실측 (`pipeline_executions`)

실행 질의:
```sh
uv run python scripts/db_readonly_query.py --sql "SELECT run_mode, count(*) AS cnt FROM pipeline_executions GROUP BY run_mode"
```

실측 출력:
```
run_mode                 | cnt
-------------------------+----
kb_only                  | 1
manual_full              | 2
predict_only             | 4
development_data_refresh | 12
```

최근 10건 세부 실행 이력 질의:
```sh
uv run python scripts/db_readonly_query.py --sql "SELECT id, execution_id, run_mode, status, source, started_at, ended_at FROM pipeline_executions ORDER BY id DESC LIMIT 10"
```

실측 출력:
```
id | execution_id                          | run_mode                 | status  | source          | started_at                 | ended_at
---+---------------------------------------+--------------------------+---------+-----------------+----------------------------+---------------------------
19 | development_data_refresh-921e27160ca3 | development_data_refresh | failed  | local_scheduler | 2026-09-16 06:40:32.144723 | 2026-09-16 06:49:23.973996
18 | development_data_refresh-c1f076c580af | development_data_refresh | success | local_scheduler | 2026-09-15 04:26:57.062831 | 2026-09-15 04:39:59.360679
17 | development_data_refresh-d95fbaec4a9e | development_data_refresh | success | local_scheduler | 2026-09-14 04:09:07.675797 | 2026-09-14 04:19:11.208149
16 | development_data_refresh-9c135c0fe890 | development_data_refresh | success | local_scheduler | 2026-09-10 02:03:48.418894 | 2026-09-10 02:12:33.069592
15 | development_data_refresh-613da8a7ca2e | development_data_refresh | success | local_scheduler | 2026-09-09 04:24:44.191026 | 2026-09-09 04:37:11.575483
14 | development_data_refresh-4416770ef5f7 | development_data_refresh | failed  | local_scheduler | 2026-09-08 09:04:40.872293 | 2026-09-08 09:10:28.106313
13 | development_data_refresh-9b85ef491e0e | development_data_refresh | success | local_scheduler | 2026-09-07 12:58:11.739985 | 2026-09-07 13:04:24.650662
12 | development_data_refresh-34c5c1c71f04 | development_data_refresh | failed  | local_scheduler | 2026-09-06 08:44:30.905112 | 2026-09-06 10:09:22.091024
11 | development_data_refresh-d20acbe6cc4e | development_data_refresh | success | local_scheduler | 2026-08-14 03:30:03.504137 | 2026-08-14 03:42:40.150212
10 | development_data_refresh-9081416d3806 | development_data_refresh | success | local_scheduler | 2026-08-09 04:23:59.432719 | 2026-08-09 04:24:22.371525
```

- 실측 결과, 정기 데이터 최신화는 100% `run_mode='development_data_refresh'`로만 기록되었으며, `nightly_schedule` 기록은 0건으로 일치합니다.

---

## 4. 04:00 PSI 드리프트 감시 환경 및 아티팩트 실측

### 4.1 스케줄 설정 및 활성화 상태

- 태스크 정의: `drift_monitor_task` (`src/tasks/scheduled_tasks.py:619-750`)
- 실행 시각: 매일 04:00 KST (`src/tasks/worker.py:415-420`, `timeout=3600`)
- 활성화 플래그: `docker-compose.yml` 워커 환경변수에 `ML_DRIFT_MONITOR_ENABLED`가 명시되지 않았으나, 애플리케이션 기본 설정(`src/app/core/config.py:80`)에서 `ML_DRIFT_MONITOR_ENABLED: bool = True`로 정의되어 있어 워커 기동 시 자동으로 활성화됩니다.
- 평가 윈도우: 기본값 7일 (`[now - 7 days, now)` 개찰일 반열림 구간)

### 4.2 Baseline 아티팩트 보존 상태

워커 컨테이너 내 실측 결과, 3개 대상 모델 모두 baseline 아티팩트(`feature_distributions_v1.json`, `metadata.json`)가 정상 보존되어 있습니다 (`docs/handoff/session_20260916_rollout_release_workers.md` 21행 및 코디네이터 실측 사실).

| 카테고리 | 등록 모델명 (`CATEGORY_MODEL_NAMES`) | Baseline 아티팩트 경로 | 보존 파일 | 학습 표본 수 (컨테이너 실측) |
| --- | --- | --- | --- | --- |
| `Cnstwk` (공사) | `cnstwk_institution_v1` | `ml_registry/cnstwk_institution_v1/baseline/` | `feature_distributions_v1.json`, `metadata.json` | 1,363,701 건 |
| `Servc` (용역) | `servc_institution_v1` | `ml_registry/servc_institution_v1/baseline/` | `feature_distributions_v1.json`, `metadata.json` | 925,054 건 |
| `Thng` (물품) | `quantum_leap_v25_pro` | `ml_registry/quantum_leap_v25_pro/baseline/` | `feature_distributions_v1.json`, `metadata.json` | 18,069 건 |

### 4.3 현재 retrain_logs 내 drift_monitor 이력 실측

실행 질의:
```sh
uv run python scripts/db_readonly_query.py --sql "SELECT count(*) AS drift_monitor_count FROM retrain_logs WHERE trigger_source = 'drift_monitor'"
```

실측 출력:
```
drift_monitor_count
-------------------
0
```

현재 테이블 내 전체 이력 확인 질의:
```sh
uv run python scripts/db_readonly_query.py --sql "SELECT id, trigger_source, champion_version, challenger_version, status, created_at FROM retrain_logs ORDER BY id DESC LIMIT 5"
```

실측 출력:
```
id | trigger_source | champion_version  | challenger_version    | status             | created_at
---+----------------+-------------------+-----------------------+--------------------+--------------------
3  | e2e_final      | v_20260802_064146 | v_20260802_064411_973 | PROMOTE_CHALLENGER | 2026-08-02 06:44:31
2  | e2e_check      | v_20260802_063916 | v_20260802_064012     | PROMOTE_CHALLENGER | 2026-08-02 06:40:31
1  | e2e_check      | v_20260802_063916 | v_20260802_063916     | PROMOTE_CHALLENGER | 2026-08-02 06:39:35
```

- 현재까지 `drift_monitor`에 의해 기록된 행은 **0건**입니다.
- 따라서 2026-09-17 04:00 KST 실행 결과가 `retrain_logs`에 최초로 기록되는 드리프트 감시 이력이 됩니다.

---

## 5. 최근 7일 평가 윈도우 표본 실측

### 5.1 DB 전체 및 최신 개찰일

실행 질의:
```sh
uv run python scripts/db_readonly_query.py --sql "SELECT max(rl_openg_dt) AS max_dt, min(rl_openg_dt) AS min_dt, count(*) AS total_count FROM bid_results"
```

실측 출력:
```
max_dt              | min_dt              | total_count
--------------------+---------------------+------------
2026-09-15 18:00:00 | 2008-12-17 15:20:00 | 3435171
```

- DB 전체 낙찰 데이터: 총 3,435,171건
- 최신 개찰일시: `2026-09-15 18:00:00`

### 5.2 최근 7일 카테고리별 단순 낙찰 건수

실행 질의:
```sh
uv run python scripts/db_readonly_query.py --sql "SELECT category, count(*) AS cnt FROM bid_results WHERE rl_openg_dt >= NOW() - INTERVAL 7 DAY GROUP BY category"
```

실측 출력:
```
category | cnt
---------+----
Cnstwk   | 838
Servc    | 671
Thng     | 832
```

### 5.3 최근 7일 학습 파이프라인 정제 기준 유효 표본 실측

`build_training_dataset` 로직(`src/ml/dataset.py:152-205`)과 동일한 조건(공고 조인 매칭, 낙찰률 70~110%, 추정가격 10만원~1조원 유효 구간)을 적용한 실측 질의입니다.

실행 질의:
```sh
uv run python scripts/db_readonly_query.py --sql "SELECT r.category, count(*) AS valid_samples FROM bid_results r INNER JOIN bid_announcements a ON r.bid_ntce_no = a.bid_ntce_no AND SUBSTR(CONCAT('000', r.bid_ntce_ord), -3, 3) = SUBSTR(CONCAT('000', a.bid_ntce_ord), -3, 3) WHERE r.rl_openg_dt >= NOW() - INTERVAL 7 DAY AND r.sucsf_bid_rate BETWEEN 70.0 AND 110.0 AND a.presmpt_prce BETWEEN 100000 AND 1000000000000 GROUP BY r.category"
```

실측 출력:
```
category | valid_samples
---------+--------------
Thng     | 753
Cnstwk   | 832
Servc    | 643
```

- 판정 기준 요구 표본: `DEFAULT_MIN_SAMPLES = 30`
- 실측 표본 수:
  - **Thng (물품)**: **753건** (기준치 30건 대비 약 25배 충분)
  - **Cnstwk (공사)**: **832건** (기준치 30건 대비 약 27배 충분)
  - **Servc (용역)**: **643건** (기준치 30건 대비 약 21배 충분)
- 결론: 데이터 표본 부족(`recent_samples = 0` 또는 `sample_size < 30`)으로 인한 `INSUFFICIENT_DATA` 판정 가능성은 사전에 완전히 배제되었습니다.

---

## 6. 2026-09-17 04:00 이후 판정 확인 절차 및 질의

### 6.1 확인용 SQL 질의

04:00 드리프트 감시 태스크 종료 후 담당자가 실행해야 하는 단일 SELECT 질의입니다.

```sql
SELECT id, trigger_source, champion_version, challenger_version, status, created_at
FROM retrain_logs
WHERE trigger_source = 'drift_monitor'
ORDER BY id DESC
LIMIT 6;
```

상세 메트릭 요약(`metrics_summary`) 확인 질의:
```sql
SELECT id, champion_version, status, metrics_summary
FROM retrain_logs
WHERE trigger_source = 'drift_monitor'
ORDER BY id DESC
LIMIT 3;
```

### 6.2 기대되는 정상 판정 결과

- 3개 카테고리(`Cnstwk`, `Servc`, `Thng`)에 대해 각각 1건씩 총 3건의 레코드가 생성되어야 합니다.
- 각 레코드의 정본 매핑:
  - `trigger_source`: `'drift_monitor'`
  - `champion_version`: 모델명 (`cnstwk_institution_v1`, `servc_institution_v1`, `quantum_leap_v25_pro`)
  - `challenger_version`: baseline 버전 (`baseline_version` 또는 모델 버전 문자열)
  - `status`: **`STABLE`** 또는 **`DRIFT_DETECTED`** (실제 PSI 계산 판정)

---

## 7. Thng 모델 판정 분기 및 트러블슈팅 매트릭스

04:00 실행 후 만약 Thng 모델(`quantum_leap_v25_pro`)이 `STABLE` 또는 `DRIFT_DETECTED`가 아닌 `INSUFFICIENT_DATA`로 기록될 경우, 아래의 코드 기반 원인 분기 트리를 통해 즉각 원인을 식별합니다.

### 7.1 판정 분기 트리

```
[2026-09-17 04:00 drift_monitor_task 실행]
    │
    ├─► 1. Baseline 아티팩트 로드 시도 (load_baseline_distributions)
    │     │
    │     ├─ [실패/None] ──► status: INSUFFICIENT_DATA (원인 A: Baseline 아티팩트 부재)
    │     │                 ├─ challenger_version = "-"
    │     │                 └─ reason = "Baseline 분포 아티팩트가 없습니다 (...)"
    │     │
    │     └─ [성공/dict] ──► 2. 최근 7일 평가 데이터셋 조회 (build_training_dataset)
    │                         │
    │                         ├─ [df_raw.empty] ──► status: INSUFFICIENT_DATA (원인 B: 최근 평가 데이터 없음)
    │                         │                     ├─ recent_samples = 0
    │                         │                     └─ reason = "카테고리에 대한 최근 평가 데이터가 없습니다 (...)"
    │                         │
    │                         └─ [df_raw 존재] ──► 3. Single Source features.py 특징 변환 및 PSI 계산
    │                                               │
    │                                               ├─ [표본 < 30 또는 컬럼 누락] ──► status: INSUFFICIENT_DATA (원인 C: 특징별 표본 미달)
    │                                               │                                  └─ reason = "표본 부족 (N < 30)" 또는 "특징 컬럼 누락"
    │                                               │
    │                                               └─ [정상 계산 완료] ──► 실제 PSI 종합 판정
    │                                                                        ├─ max(PSI) < 0.2  ──► status: STABLE (정상 안정)
    │                                                                        └─ max(PSI) >= 0.2 ──► status: DRIFT_DETECTED (드리프트 감지, 운영 알림 발신)
```

### 7.2 세부 원인 분기 및 점검 가이드

| 분기 | 판정 상태 | `metrics_summary` 특징적 키/문구 | 근본 원인 | 점검 및 대응 절차 |
| --- | --- | --- | --- | --- |
| **정상 판정 1** | `STABLE` | `"status": "STABLE"`, `"max_psi" < 0.2` | 최근 7일간의 특징 분포가 baseline 대비 안정적으로 유지됨 | 추가 조치 불필요 (정상 감시 완료) |
| **정상 판정 2** | `DRIFT_DETECTED` | `"status": "DRIFT_DETECTED"`, `"max_psi" >= 0.2`, `"drifted_features"` 목록 | 1개 이상의 주요 특징에서 PSI 임계값(0.2) 초과 드리프트 발생 | `notify_drift_detected` 알림 발신 확인. 자동 재학습/승격은 발생하지 않으므로 MLOps 담당자가 재학습 필요 여부 수동 판단 |
| **원인 A** | `INSUFFICIENT_DATA` | `"reason": "Baseline 분포 아티팩트가 없습니다 (ml_registry/quantum_leap_v25_pro/baseline)"`, `challenger_version: "-"` | 컨테이너 내 baseline 디렉터리 경로 마운트 오류 또는 파일 손상/부재 | `docker compose exec worker ls -la ml_registry/quantum_leap_v25_pro/baseline/` 실행하여 `feature_distributions_v1.json` 존재 여부 확인 |
| **원인 B** | `INSUFFICIENT_DATA` | `"reason": "카테고리 Thng에 대한 최근 평가 데이터가 없습니다"`, `"recent_samples": 0` | 윈도우 `[now - 7d, now)` 내 개찰 데이터 누락 또는 공고 조인 매칭 0건 | `bid_results` 최신 수집 여부(`max(rl_openg_dt)`) 및 02:00 `development_data_refresh` 성공 여부 확인 |
| **원인 C** | `INSUFFICIENT_DATA` | 특징 세부 필드에 `"action": "INSUFFICIENT_DATA"`, `"reason": "표본 부족 (N < 30)"` 또는 컬럼 누락 | 유효 표본 필터링 후 30건 미만으로 탈락했거나 단일 특징 공급원(`features.py`) 변환 중 컬럼 누락 발생 | `src/ml/dataset.py` 유효 조건(낙찰률, 추정가격) 분포 및 raw_data JSON 내 누락 컬럼 확인 |

---

## 8. 결론 및 종합 요약

1. **개발 환경 02:00 데이터 최신화 경로**: `development_data_refresh_task`로 정상 바인딩되어 있으며, 운영 번들인 `nightly_schedule_task`는 비활성화(`skipped`)되는 것이 설계 정본입니다.
2. **04:00 드리프트 감시 환경**: 워커 설정에서 `ML_DRIFT_MONITOR_ENABLED=True`로 정상 활성화되어 있으며, Thng을 포함한 3개 모델의 baseline 아티팩트가 모두 보존되어 있습니다.
3. **표본 충족도**: 최근 7일 평가 윈도우 내 Thng 유효 표본은 753건으로, 최소 요구 표본수(30건)를 25배 초과하여 표본 부족 가능성이 배제되었습니다.
4. **04:00 이후 절차**: 본 문서 6.1의 단일 SQL 질의를 통해 `retrain_logs`에 3개 카테고리의 실제 PSI 판정(`STABLE` 또는 `DRIFT_DETECTED`)이 정상 기록되었는지 확인합니다.
5. **무손실 및 계약 준수**: 점검 과정에서 도커 컨테이너 조작, 스케줄 임의 트리거, DB 데이터 쓰기는 일절 수행되지 않았으며 전량 읽기 전용으로 안전하게 검증되었습니다.

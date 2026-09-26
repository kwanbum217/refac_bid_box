# bid_results DBG 합성 행 10건 출처 추적 (2026-09-26)

> **작성일**: 2026-09-26
> **상태**: 분석 완료 (코드·설정·DB 변경 없음, 삭제 미실행)
> **범위**: `docs/analysis/drift_data_check_20260926.md` 3.4절 부수 발견의 출처 추적
> **관련 표**: `bid_results` id 4410791~4410800, `bid_announcements` id 10273569~10273578
> **질의 방법**: `uv run python scripts/db_readonly_query.py` (읽기 전용), `git log -S`, 인라인 Python 분석

---

## 1. 요약 (결론)

1. **출처 판정: 확정된 것은 "추적되지 않은 임시 경로(에이전트 세션의 inline 명령 또는 미추적 스크립트) 삽입"이다.** 저장소 추적 파일 전체에서 `DBG` 문자열이 검색되지 않고(코디네이터 확인 사실, 본 조사에서 재확인), 수집 파이프라인 기록(`pipeline_executions` id 22, 02:53:10~03:02:33 UTC)이 삽입 시각 03:08:12 UTC 보다 5분 39초 먼저 종료됐으므로 수집기 출처는 배제된다. 커밋된 하니스(`scripts/benchmark_read_path_concurrency.py`)는 GET 요청만 보내는 읽기 전용 측정 도구이고(`scripts/benchmark_read_path_concurrency.py:53-73` 측정 경로 정의), `tests/test_mysql_concurrency.py`는 운영 스키마가 아닌 전용 `concurrency_test` 스키마에서만 동작하므로(`tests/test_mysql_concurrency.py:24-27`) 둘 다 배제된다.
2. **가장 유력한 맥락: 2026-09-19 읽기 경로 동시성 측정 하니스 제작 세션(Orca Run `run_1dbced5f03c6`)이다.** DB 시각은 UTC이고 워커 로그 시각은 로컬(KST)이라는 사실이 당일 인수인계에 명시돼 있고(`docs/handoff/session_20260919_measurement_harnesses.md` 4장), 삽입 시각 03:08:12 UTC = 12:08:12 KST는 하니스 첫 커밋 12:17:41 KST(`48c0f648`) 직전, 즉 하니스 개발 중이다. 공고·낙찰이 17ms 간격으로 짝지어 삽입된 것은 선채움 경로 검증에 필요한 "공고-낙찰 매칭 짝" 시딩의 특징이다. 단, 정확한 명령은 Docker 로그 미조회(계약상 접속 금지)로 특정하지 못했다.
3. **영향: 기록된 드리프트 판정에는 미포함, 09-26 수동 재학습 챌린저 1건에 포함(기각됨), 통계 집계 3곳에 오염.** 상세는 4장. 운영 champion 모델 가중치는 무영향이다.
4. **삭제는 실행하지 않았다.** 대상 조건 SQL, 백업 절차, 재집계 목록을 5장에 후보로만 둔다. G1(데이터 무손실) 원칙상 삭제 여부는 사용자 결정 사항이다.

---

## 2. 삽입 사실의 기계적 확인

### 2.1 bid_results 10건 (질의 재현 가능)

`SELECT * FROM bid_results WHERE bid_ntce_no LIKE 'DBG%'` 결과:

| 컬럼 | 값 |
| --- | --- |
| id | 4410791~4410800 (연속 10건) |
| bid_ntce_no | `DBG-0`~`DBG-4`, `DBG2-0`~`DBG2-4` |
| bid_ntce_nm | "동시성 테스트 공고" (10건 동일) |
| bidwinnr_nm | "낙찰업체" |
| dminstt_nm | "테스트 수요기관" |
| category | Servc |
| sucsf_bid_amt | 88,000,000 |
| sucsf_bid_rate | 88.0000 |
| rl_openg_dt | 2026-09-19 03:08:12.568~598 (DBG), 03:08:17.179~207 (DBG2) |
| collected_at | rl_openg_dt 보다 0.5~6ms 뒤 |
| raw_data | 문자열 "null" |

### 2.2 bid_announcements 10건 (짝 삽입)

`bid_ntce_no LIKE 'DBG%'` 조회: id 10273569~10273578, ntce_instt_nm "테스트 공고기관", dminstt_nm "테스트 수요기관", presmpt_prce 90,000,000, base_amount 100,000,000, bid_ntce_dt = 삽입 시각, bid_clse_dt/openg_dt NULL, category Servc. 같은 bid_ntce_no끼리 공고 `collected_at`이 낙찰 `collected_at`보다 15~17ms 먼저다(예: DBG-0 공고 03:08:12.552742, 낙찰 03:08:12.569452). 이는 하나의 시딩 로직이 공고를 넣고 즉시 낙찰을 넣은 흔적이며, `src/ml/dataset.py:206-211`의 공고 조인 조건과 `src/app/api/v1/bids.py` 선채움 매칭(`preload_matching_announcements`)이 요구하는 "공고-낙찰 짝"을 만든다.

### 2.3 시각 정합성 (UTC 기준)

당일 인수인계가 "워커 컨테이너 로그 시각은 로컬, DB 시각은 UTC"임을 확정했다(`docs/handoff/session_20260919_measurement_harnesses.md` 4장 표 마지막 행). 이 기준으로:

| 사건 | DB 시각 (UTC) | 로컬 (KST) | 근거 |
| --- | --- | --- | --- |
| 수집 파이프라인 id 22 종료 | 2026-09-19 03:02:33 | 12:02:33 | `pipeline_executions` id 22 |
| DBG 5건 삽입 | 2026-09-19 03:08:12 | 12:08:12 | `bid_results.collected_at` |
| DBG2 5건 삽입 | 2026-09-19 03:08:17 | 12:08:17 | `bid_results.collected_at` |
| 하니스 첫 커밋 `48c0f648` | - | 12:17:41 | `git log` |
| 측정 전용 플래그 병합 `8d3409b8` | - | 12:32:20 | `git log` |

삽입은 수집 종료와 첫 하니스 커밋 사이, 즉 하니스 제작 세션 도중에 일어났다. 두 웨이브가 5초 간격이고 접두어가 `DBG`에서 `DBG2`로 바뀐 것은 같은 시딩을 접두어만 바꿔 두 번 실행한 양상이다.

### 2.4 출처 배제 근거

| 후보 | 배제 근거 |
| --- | --- |
| 수집기(`collector_service`/api_collector) | `pipeline_executions` id 22가 03:02:33 UTC 종료. 공공조달 API는 `DBG-0` 형식 고시번호를 반환하지 않고 `raw_data`는 원문 JSON이 아니라 문자열 "null" |
| 커밋된 하니스 `benchmark_read_path_concurrency.py` | GET 측정 전용(`--dry-run` 출력도 URL 8종). 파일 전체에 삽입·시딩 코드 없음. DB 세션 임포트도 없음 |
| `tests/test_mysql_concurrency.py` | 전용 `concurrency_test` 스키마 + `concurrency_*` 테이블만 사용(`tests/test_mysql_concurrency.py:83-113`), 종료 시 DROP. MYSQL_TEST_URL 미설정 시 skip |
| 추적된 코드 전체 | 저장소 전체에서 `DBG` 문자열 미검색(코디네이터 확인 사실 + 본 조사 재확인). `git log --all -S DBG` 결과는 이 보고서(`0f1f7908`)가 유일 |
| `.orca/` 세션 기록 | `DBG` 검색 결과는 본 조사 관련 캡슐 4개뿐. 세션 콘솔 로그는 이 워크트리에 존재하지 않음 |
| `prediction_results` | `bid_ntce_no LIKE 'DBG%'` 0건 |

### 2.5 관찰: 인접 auto_increment 공백

`bid_results`에서 id 4410782~4410790의 9개 값이 비어 있다(4410781은 02:53:55 수집 정상 행, 4410791이 DBG-0). AUTO_INCREMENT 값이 소비됐으나 행이 없는 것은 삽입 시도의 rollback 또는 삭제 후 흔적이다. DBG 블록 직전이라 첫 시딩 시도가 rollback되거나 지워졌을 가능성이 있으나, 이 워크트리에서는 확인 불가능한 사항으로 기록만 남긴다.

---

## 3. 저장소·기록 검색 결과

| 검색 | 명령/범위 | 결과 |
| --- | --- | --- |
| DBG 문자열 | `git log --all -S DBG --since=2026-08-01` | `0f1f7908` (2026-09-26 드리프트 확인 보고서) 1건뿐 |
| 88,000,000 | `git log --all -S 88000000` | 히트 20건 모두 레이턴시·RAG 실측 문서. DBG 행과 무관 |
| 2026-09-19 커밋 | `git log --since --until` | 하니스·인증 하니스·게이트 계열. 시딩 코드 커밋 없음 |
| `.orca/` | ripgrep `DBG` | 본 조사 캡슐 4개뿐 (`task_g1_dbg_rows_origin`, `task_685f8ba3bb57`, `task_ba49498d7627`, `task_f1_review`) |
| 당일 세션 인수인계 | `docs/handoff/session_20260919_measurement_harnesses.md` | 시딩 언급 없음. DB 시각 UTC 확정 정보와 세션 타임라인만 확보 |
| A/B 실측 보고서 | `docs/analysis/read_path_ab_confirmation_20260919.md` | 측정은 GET 부하뿐. 시딩 언급 없음 |

---

## 4. 영향 범위 판정

### 4.1 오염된 집계 (확인됨)

| 테이블 | 행 | 내용 | 재집계 시각 (UTC) | 질의 근거 |
| --- | --- | --- | --- | --- |
| `institution_win_rate_stats` | id 695819 | institution_name "테스트 수요기관", category Servc, sample_count 10, avg_rate/ewm_rate 88.0000 | 2026-09-26 03:47:11 | `SELECT ... WHERE institution_name IN (...)` |
| `bid_dataset_summaries` | dataset=result | total_count에 10건 포함, total_amount에 880,000,000 포함, avg_rate 89.2519에 10×88.0 포함 | 2026-09-21 03:10:37 | `SELECT * FROM bid_dataset_summaries` |
| `bid_dataset_summaries` | dataset=announcement | source_latest_collected_at 2026-09-20 기준 전체 집계에 10건의 공고 포함 | 2026-09-21 03:10:25 | 동일 |
| `bid_compare_stats_snapshots` | matched_count | 324,717건 중 +10 | 2026-09-26 03:47:08 | payload 조회 |
| `bid_compare_stats_snapshots` | result_by_month | 2026-09 12,833건 중 +10 (0.08%) | 2026-09-26 03:47:08 | payload 조회 |

`institution_win_rate_stats` 집계는 전체 이력 GROUP BY(dminstt_nm, category)이며 placeholder 기관 필터에 "테스트 수요기관"이 없다(`src/ml/institution_history.py:58-63`, `rebuild_institution_stats` `institution_history.py:265-317`). 운영 영향은 기관명이 정확히 "테스트 수요기관"인 추론 요청이 들어올 때뿐이라 사실상 없으나, 학습 특징 `attach_institution_history`가 이 표를 참조하므로 DBG 행 자체의 특징 계산에는 이 가짜 통계가 쓰였다.

### 4.2 드리프트 판정: 기록된 실행에는 미포함 (확정)

드리프트 평가 윈도우는 `[utcnow() - 7일, utcnow())` 반열림 구간, 개찰일(`rl_openg_dt`) 기준이다(`src/tasks/scheduled_tasks.py:757-759`, 필터 적용 `src/ml/dataset.py:233-236`). DBG 행의 rl_openg_dt는 2026-09-19 03:08:12 UTC다.

| retrain_logs | 생성 시각 (UTC) | 윈도우 시작 = 생성-7일 | DBG 행 (03:08:12) 포함 여부 |
| --- | --- | --- | --- |
| id 4~6 | 2026-09-17 10:24 | 2026-09-10 | 행 미존재(삽입 전) |
| id 7~9 | 2026-09-18 05:33 | 2026-09-11 | 행 미존재(삽입 전) |
| id 10~12 | 2026-09-26 05:57:50 | 2026-09-19 05:57:50 | 미포함 (03:08 < 05:57) |
| id 13~15 | 2026-09-26 06:41:32 | 2026-09-19 06:41:32 | 미포함 |

`drift_data_check_20260926.md` 3.4절의 "최근 7일 윈도우 안에 들어온다" 서술은 그 문서 작성 시점(2026-09-26 03:08 UTC 이전) 기준으로는 참이지만, 실제 드리프트 실행(id 10~15)은 전부 03:08 UTC 이후에 돌아 DBG 행을 이미 윈도우 밖으로 밀어냈다. 2026-09-27 이후 실행(시작 09-20 이후)도 영구히 제외된다. **결론: 기록된 드리프트 판정에 DBG 행이 들어간 사례는 없다.**

### 4.3 재학습: 09-26 수동 챌린저에 포함 (기각되어 운영 무영향)

재학습 파이프라인은 `build_training_dataset`을 시작·종료 시각 없이(전체 이력) 호출한다(`src/tasks/retrain_task.py:152-157`, 기본값 None = 전체 이력 `dataset.py:171`). `require_announcement=True` 기본이라 공고 조인이 필요하고, DBG 행은 짝 공고가 존재해 조인을 통과한다. `retrain_logs` id 16 (manual, 2026-09-26 09:05:22 UTC, champion v_20260915_133523_756 = servc 모델, challenger v_20260926_085519_461)의 학습·홀드아웃 데이터에 DBG 10건이 포함됐다. 판정은 REJECT_CHALLENGER라 champion이 유지됐고, **운영 champion 가중치에는 영향이 없다.** 챌린저 가중치는 기각되었으나 보관된다면 오염 데이터 학습산임을 유의한다. 주간 재학습(09-21 03:00 예정)은 `pipeline_executions`와 `retrain_logs`에 기록이 없어 실행되지 않았다.

### 4.4 무영향 경로

- `bid_ranking_snapshots`: "동시성/DBG/삽입 시각대" 조회 0건.
- `prediction_results`: DBG 식별자 0건.
- `bid_evaluation_snapshots`: 사용자 발화 스냅샷으로 DBG 시딩과 무관한 경로.
- 읽기 경로(홈·목록): 최근 정렬 조회에 DBG 행이 섞일 수 있으나 측정 회차 종료 후 재기록되지 않은 이력값에만 영향.

---

## 5. 정리 후보 (실행하지 않음, 사용자 결정 대기)

### 5.1 백업 절차 (삭제 전 필수)

```bash
uv run python scripts/db_readonly_query.py --sql "SELECT * FROM bid_results WHERE bid_ntce_no LIKE 'DBG%'" --format json > artifacts/dbg_bid_results_backup_20260926.json
uv run python scripts/db_readonly_query.py --sql "SELECT * FROM bid_announcements WHERE bid_ntce_no LIKE 'DBG%'" --format json > artifacts/dbg_bid_announcements_backup_20260926.json
```

### 5.2 삭제 후보 SQL (후보이며 실행 금지 상태)

```sql
-- 기대 영향: bid_results 10행, bid_announcements 10행
DELETE FROM bid_results
WHERE bid_ntce_no LIKE 'DBG%'
  AND bid_ntce_nm = '동시성 테스트 공고'
  AND sucsf_bid_amt = 88000000
  AND collected_at BETWEEN '2026-09-19 03:08:00' AND '2026-09-19 03:09:00';

DELETE FROM bid_announcements
WHERE bid_ntce_no LIKE 'DBG%'
  AND bid_ntce_nm = '동시성 테스트 공고'
  AND presmpt_prce = 90000000
  AND collected_at BETWEEN '2026-09-19 03:08:00' AND '2026-09-19 03:09:00';
```

다중 조건을 붙인 이유: `LIKE 'DBG%'` 단독은 우연히 같은 접두어가 생길 경우를 대비한 안전망이다. 삭제 전 각 DELETE에 대응하는 SELECT로 행 수(10행)를 먼저 확인한다.

### 5.3 삭제 후 필수 재집계

| 대상 | 방법 |
| --- | --- |
| `institution_win_rate_stats` | `rebuild_institution_stats` 재실행 (id 695819 가짜 행 소멸 확인) |
| `bid_dataset_summaries` | 요약 재집계 태스크 재실행 (result/announcement 두 행 모두) |
| `bid_compare_stats_snapshots` | 비교 통계 스냅샷 재집계 (4개 키 모두) |
| `ml_registry` baseline | DBG 행은 baseline 생성 구간(개찰일 2026-05-26~09-15) 밖(09-19)이라 재생성 불요. 단 09-26 이후 baseline을 재생성하는 경우에도 구간 기준일이 09-15 이전이면 불요 |

### 5.4 재발 방지 후보

| 후보 | 내용 |
| --- | --- |
| 격리 스키마 원칙 준수 | 운영 DB 시딩이 필요한 실험은 `tests/test_mysql_concurrency.py` 패턴(전용 스키마 + 종료 시 DROP)을 따른다. 운영 스키마 직접 삽입 금지를 조율 규칙에 명시 |
| placeholder 필터 확장 | `institution_history.py:58`의 `_PLACEHOLDER_INSTITUTIONS`에 테스트 계열 기관명을 추가하는 것은 후보이나, 근본 대책이 아니라 삭제·재집계가 우선 |
| 시딩 흔적 감시 | `bid_results`에서 `bid_ntce_no NOT REGEXP '^[A-Z][0-9]{2}'` 형식 검사 또는 `raw_data IS NULL/문자열 null` 감시 질의를 주간 점검 체크리스트에 추가 |

---

## 6. 재현 방법

본 보고서의 DB 수치는 모두 `uv run python scripts/db_readonly_query.py --sql "<질의>"` 로 재현한다. 주요 질의:

- DBG 행: `SELECT * FROM bid_results WHERE bid_ntce_no LIKE 'DBG%'`, `SELECT id, bid_ntce_no, ... FROM bid_announcements WHERE bid_ntce_no LIKE 'DBG%'`
- 인접 공백: `SELECT id, bid_ntce_no, collected_at FROM bid_results WHERE id BETWEEN 4410780 AND 4410810`
- 통계 오염: `SELECT * FROM institution_win_rate_stats WHERE institution_name = '테스트 수요기관'`, `SELECT * FROM bid_dataset_summaries`
- 드리프트: `SELECT id, trigger_source, champion_version, status, created_at FROM retrain_logs ORDER BY id`
- 파이프라인: `SELECT id, pipeline_name, status, started_at, ended_at FROM pipeline_executions WHERE started_at >= '2026-09-19 00:00:00'`

git 근거: `git log --all -S DBG --since=2026-08-01 --oneline`, `git show --stat 48c0f648`, `git show 8b5aa7ef:docs/handoff/session_20260919_measurement_harnesses.md`.

# MySQL 통계 신선도 야간 상시 점검 독립 검토 (2026-09-11)

> 작성일: 2026-09-11
> 대상: 브랜치 `kwanbum217/orca-bc1`, 커밋 `4992e70`
> 역할: 독립 리뷰어 (task_30345c05d8b3)
> 판정: pass
> 전제: 테스트를 재실행하지 않았고, DB 질의·ANALYZE TABLE·Docker 조작·벤치마크를 하지 않았다. 허용 파일과 `git diff main...HEAD` 만 대조했다.

---

## 1. 결론

야간 경로와 서비스 모듈과 CLI 어디에도 `ANALYZE TABLE` 이나 다른 DB 쓰기가 실행 경로에 들어가지 않는다. 문자열은 독스트링·주석·정책 문서의 사람 절차에만 있다. 판정 로직(임계 기본값, 대상 테이블, 편차·경과일 계산, 종료 코드)은 `src/app/services/mysql_stats_freshness.py` 가 단일 원천이고, 스크립트는 그것을 임포트한다. 야간 점검은 기존 후속 단계와 같은 실패 격리로 붙었고, 임계 초과는 경고와 `outcome["mysql_stats_freshness"]` 에 남는다.

차단 결함은 없다. 잔여 관찰은 8절에 적는다.

---

## 2. ANALYZE 와 DB 쓰기 실행 경로

추적 범위는 `src/app/services/mysql_stats_freshness.py`, `scripts/check_mysql_stats_freshness.py`, `src/tasks/scheduled_tasks.py` 의 이번 커밋 추가분이다.

| 경로 | 실행 여부 | 근거 |
| --- | --- | --- |
| 서비스 모듈 SQL | SELECT 두 문장 + COUNT | `NOW_QUERY` 와 `STATS_QUERY` 는 `SELECT` 뿐이고 (`src/app/services/mysql_stats_freshness.py:34-38`), `fetch_innodb_stats` 가 `text()` 로 그 둘만 `execute` 한다 (`:232`, `:237`). 실제 행 수는 `select(func.count()).select_from(model)` 이다 (`:222`) |
| CLI 조회 | SELECT 두 문장 | `fetch_stats` 가 같은 `NOW_QUERY`/`STATS_QUERY` 를 `assert_read_only` 후 `run_query` 에 넘긴다 (`scripts/check_mysql_stats_freshness.py:76-84`). 쓰기 키워드는 파서와 `READ ONLY` 트랜잭션이 막는다 |
| 야간 래퍼 | 서비스 호출만 | `_check_mysql_stats_freshness` 는 `check_mysql_stats_freshness(db)` 만 부르고 커밋하지 않는다 (`src/tasks/scheduled_tasks.py:421-442`) |
| ANALYZE | 없음 | 실행 구문(`execute`/`scalar`/`run_query`)에 `ANALYZE`/`OPTIMIZE`/`INSERT`/`UPDATE`/`DELETE` 가 없다. 등장은 금지 선언과 사람 절차 주석뿐이다 |
| 조건부 자동 갱신 | 없음 | `stale` 분기에서 하는 일은 `logger.warning` 과 결과 반환뿐이다 (`src/tasks/scheduled_tasks.py:426-437`). 임계 초과여도 SQL 을 추가로 내지 않는다 |

정책 문서 0.3절의 `ANALYZE TABLE bid_announcements;` / `ANALYZE TABLE bid_results;` 는 주석으로만 적힌 사람 승인 절차다 (`docs/ops/mysql_statistics_refresh_policy_20260911.md:36-37`). 코드가 그 문장을 실행하지 않는다.

---

## 3. 판정 로직 단일 원천과 임포트 방향

`git show main:scripts/check_mysql_stats_freshness.py` 와 현재 스크립트를 대조하면, 종전에 스크립트에 있던 `EXIT_*`, `DEFAULT_*`, `STATS_QUERY`, `NOW_QUERY`, `compute_drift_pct`, `compute_age_days`, `evaluate_table`, `evaluate_all`, `parse_expected_rows`, `build_payload`, `render_table` 정의가 사라졌고 서비스 모듈에서 임포트한다 (`scripts/check_mysql_stats_freshness.py:30-48`).

| 항목 | 정의 위치 | 스크립트 |
| --- | --- | --- |
| 임계 기본값 25.0 / 3.0 | `src/app/services/mysql_stats_freshness.py:31-32` | 임포트 후 argparse 기본값으로만 사용 (`:114-122`) |
| 대상 테이블 | `:29` `DEFAULT_TABLES` | 임포트 |
| 편차 계산 | `:69-73` `abs(stats_rows - expected_rows) / expected_rows * 100.0` | 임포트. 자기 사본 없음 |
| 경과일 계산 | `:76-78` `(now - last_update).total_seconds() / 86400.0` | 임포트 |
| 종료 코드 0/1/2 | `:25-27` | 임포트 후 `main` 이 `EXIT_STALE if any(...) else EXIT_OK` 로 매핑 (`:147`) |

스크립트에 남은 자체 함수는 CLI 진입점 `main` 과 읽기 전용 조회 어댑터 `fetch_stats` 뿐이다. `fetch_stats` 는 `scripts/db_readonly_query.py` 경로를 유지하기 위한 I/O 어댑터이며, 판정 식·임계·종료 코드를 다시 정의하지 않는다. 야간 경로는 같은 모듈의 `fetch_innodb_stats` / `fetch_live_row_counts` 를 쓴다.

역방향 임포트는 이번 경로에 없다. `_check_mysql_stats_freshness` 는 `from src.app.services.mysql_stats_freshness import check_mysql_stats_freshness` 만 한다 (`src/tasks/scheduled_tasks.py:421`). 서비스 모듈은 `scripts` 를 임포트하지 않는다. `scheduled_tasks.py` 상단의 `scripts.backup_recovery` 임포트는 이 커밋 이전부터 있던 백업 경로이며 `git diff 4992e70^..4992e70 -- src/tasks/scheduled_tasks.py` 에 포함되지 않는다.

---

## 4. 스크립트 인터페이스 보존

종전 `main` 과 현재 `main` 의 사용자 표면이 같다.

| 계약 | 종전 | 현재 |
| --- | --- | --- |
| 인자 | `--tables`, `--expected-rows`, `--max-drift-pct`, `--max-stale-days`, `--json` | 동일 (`scripts/check_mysql_stats_freshness.py:101-124`) |
| 기본값 | 테이블 두 개, 편차 25.0, 경과일 3.0, `--expected-rows` 빈 문자열 | 동일. 값은 서비스 상수에서 온다 |
| 표 열 | 테이블, 통계행수, 기준행수, 편차%, 마지막갱신, 경과일, 판정 | `render_table` 이 같은 열을 낸다 (`src/app/services/mysql_stats_freshness.py:179`) |
| JSON | `thresholds`, `tables`, `stale`, `exit_code` | `build_payload` 동일 (`:166-174`) |
| 종료 코드 | 0 정상, 1 임계 초과, 2 도구 오류 | `EXIT_OK`/`EXIT_STALE`/`EXIT_ERROR` 동일 |

`--expected-rows` 를 생략하면 편차를 계산하지 않고 경과일로만 판정하는 동작도 그대로다. 야간 경로만 실제 행 수를 세어 기준으로 쓴다. 기존 `tests/test_mysql_stats_freshness.py` 는 `git diff main...HEAD -- tests/test_mysql_stats_freshness.py` 가 비어 있어 수정되지 않았다. 그 테스트가 스크립트에서 재수출된 심볼을 그대로 임포트하므로, 인터페이스가 깨졌다면 기존 테스트가 먼저 깨진다.

---

## 5. 야간 배선, 경고, 실패 격리

`nightly_schedule_task` 는 기관 이력 집계 다음에 점검을 붙이고 결과를 `outcome["mysql_stats_freshness"]` 에 담는다 (`src/tasks/scheduled_tasks.py:272-273`). 같은 후속 단계를 `development_data_refresh_task` 에도 넣었다 (`:341`). 새 크론 등록이나 새 스케줄러 함수는 없다.

로그 수준은 분기되어 있다.

- 임계 초과: `logger.warning("MySQL 영속 통계 신선도 임계 초과 감지: ...")` (`:426-434`). 초과 테이블과 `reason` 을 함께 남긴다.
- 정상: `logger.info("MySQL 영속 통계 신선도 점검 정상 (임계 이내)")` (`:436`). 경고를 남기지 않는다.
- 예외: `logger.exception` 후 `{"status": "failed", "error": str(exc)}` 반환 (`:438-440`)

실패 격리는 `_rebuild_ranking_snapshots` / `_rebuild_compare_stats_snapshots` 와 같다. 세션을 열고, 본문을 try 로 감싸고, 예외를 밖으로 올리지 않고 실패 딕셔너리를 돌려주고, `finally` 에서 세션을 닫는다 (`:372-383`, `:386-397`, `:414-442`). 점검은 `FOLLOWUP_KEYS` 에 들어가지 않는다 (`:348`). 그래서 점검 실패나 임계 초과가 야간 전체 상태를 `partial_success` 로 바꾸지 않는다. 점검은 부가 정보이고, 결과는 outcome 키로 남는다.

---

## 6. 기준 행 수

야간 점검은 상수를 기준으로 쓰지 않는다. `check_mysql_stats_freshness` 가 `fetch_live_row_counts` 로 실제 행 수를 세어 `evaluate_all` 의 `expected` 로 넘긴다 (`src/app/services/mysql_stats_freshness.py:261-267`). `fetch_live_row_counts` 는 `TABLE_MODEL_MAP` 의 `bid_results`, `bid_announcements` 만 `COUNT` 하고, 그 밖 이름은 `ValueError` 로 거절한다 (`:209-224`). 대상 테이블 밖의 행 수 조회로 번지지 않는다.

빌더 Capsule 의 확정 사실로 전체 스캔은 야간 1회 비용으로 허용 범위다. 이 검토는 그 측정을 재실행하지 않았다. CLI 는 종전처럼 `--expected-rows` 가 있을 때만 편차를 계산하므로, 야간 실측이 CLI 기본 동작을 바꾸지 않는다.

---

## 7. 정책 문서, 범위, 테스트, 빌더 보고

정책 문서 0장은 선택지 B 채택, 근거 셋(읽기 전용 기준선 보존, 문서만의 규칙이 열흘 방치를 막지 못함, ANALYZE 는 사람 승인), 사람 절차를 적는다. 4장의 선택지 A/B/C 설명은 남아 있다. 자동 갱신 코드가 없다는 선언은 0.2절과 코드 추적이 맞다.

`git diff --name-only main...HEAD` 는 다음 다섯뿐이다.

- `src/app/services/mysql_stats_freshness.py` (신설)
- `scripts/check_mysql_stats_freshness.py`
- `src/tasks/scheduled_tasks.py`
- `tests/test_mysql_stats_freshness_nightly.py` (신설)
- `docs/ops/mysql_statistics_refresh_policy_20260911.md`

`pyproject.toml` 변경은 없고 새 외부 패키지도 없다. 마이그레이션 파일도 없다.

신규 테스트는 ANALYZE 부재, SELECT 전용 실행, 기준 행 수 조회, 경고/정보 로그, 예외 격리, outcome 배선을 고정한다. `pass` 한 줄짜리 빈 테스트는 없다. 기존 `tests/test_mysql_stats_freshness.py` 는 수정되지 않았다.

`.orca/capsules/task_bd581746143f/worker_done.json` 이 있다. `schema=ORCA_WORKER_DONE_V2`, `version=2.1.0`, `task_id=task_bd581746143f`, `branch=kwanbum217/orca-bc1`, `commit_count=1`, `commit_shas=["4992e70b0b5b84140d860e14d8dabf8ddc107f23"]`, `changed_files` 다섯, `blocking_issues=[]` 를 갖췄다. 이 검토는 그 검증 명령을 재실행하지 않았다.

---

## 8. 잔여 관찰 (차단 아님)

1. CLI `fetch_stats` 는 서비스의 `fetch_innodb_stats` 와 조회 어댑터가 둘이다. 판정식 복제는 아니고, CLI 가 `db_readonly_query` 경로를 유지하려면 필요하다.
2. `STATS_QUERY` 는 SQL 에서 `table_name` 을 거르지 않고 현재 DB 의 `innodb_table_stats` 를 읽은 뒤 파이썬에서 대상 테이블만 남긴다. 사용자 테이블 `COUNT` 는 두 대상으로 제한된다. 종전 CLI 와 같은 질의다.
3. `evaluate_all` 의 `tables` 인자는 쓰이지 않고 `fetched.items()` 를 순회한다. `fetch_*` 가 요청 테이블 전부를 키로 채우므로 현재 호출에서는 빠지지 않는다.
4. `development_data_refresh_task` 에도 같은 점검을 붙였다. 새 스케줄러가 아니라 기존 개발 최신화 후속 단계다.

---

## 9. 체크리스트 요약

| id | 답 | 결함 |
| --- | --- | --- |
| single_source_judgment | yes | 아니오 |
| src_imports_scripts | no | 아니오 |
| script_interface_changed | no | 아니오 |
| analyze_in_code | no | 아니오 |
| nightly_check_wired | yes | 아니오 |
| warning_on_exceed | yes | 아니오 |
| expected_rows_hardcoded | no | 아니오 |
| failure_isolated | yes | 아니오 |
| new_cron_or_migration | no | 아니오 |
| policy_doc_updated | yes | 아니오 |
| new_package_added | no | 아니오 |
| test_quality | no | 아니오 |
| scope_exceeded | no | 아니오 |
| worker_done_report_present | yes | 아니오 |

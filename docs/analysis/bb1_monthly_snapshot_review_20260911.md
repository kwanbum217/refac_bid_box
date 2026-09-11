# BB1 월별 집계 사전 집계 전환 독립 검토

> **작성일**: 2026-09-11
> **검토 대상**: 브랜치 `kwanbum217/orca-bb1`, 커밋 `daf7648e500f6261bf8c2b32fdffc7ece4f92118`
> **대상 Task**: `task_85156cdf0572`
> **판정**: 통과
> **근거**: 코드 대조. 테스트는 재실행하지 않았고, 성능 수치는 새로 주장하지 않는다.

---

## 1. 결론

월별 두 집계의 스냅샷 경로와 실시간 폴백 경로는 같은 `_build_monthly_counts` 를 부른다. 그 헬퍼가 `_month_bucket_expr` 의 방언 분기(SQLite `strftime`, PostgreSQL `to_char`, 그 외 `date_format`)를 타므로, 재집계가 `date_format` 을 다시 구현해 SQLite 테스트와 MySQL 운영이 갈라지는 경로는 없다. 월별 payload 는 리스트인지만 보지 않고 항목이 dict 이며 `month` 와 `count` 를 모두 갖는지(타입까지) 확인한 뒤에만 인덱싱한다.

`get_dashboard_stats` 는 이번 diff 에 없고, 재집계는 기존 `rebuild_compare_stats_snapshots` 안에서 네 키로 확장됐으며 새 테이블·새 마이그레이션·새 크론은 없다. 차단 결함은 없다.

---

## 2. 변경 범위

| 파일 | 역할 |
| --- | --- |
| `src/app/services/compare_stats_snapshots.py` | 월별 두 키 추가, `is_monthly_payload_usable`, 재집계 확장 |
| `src/app/services/dashboard.py` | `get_compare_stats_data` 에 월별 스냅샷 선행·폴백 추출 |
| `tests/test_compare_stats_monthly_snapshot.py` | 월별 스냅샷 고정 테스트 신설 |

`git diff --name-only daf7648^..daf7648` 기준 세 파일뿐이다. `pyproject.toml`, `src/app/models/bids.py`, `migrations/`, `tests/test_compare_stats_snapshots.py`, `src/tasks/scheduled_tasks.py` 는 없다.

---

## 3. 보류 지점 판정

### 3.1 월 버킷 산출 재사용 (최우선)

**판정: 재사용한다. 방언이 갈라지지 않는다.**

`_month_bucket_expr` (`src/app/services/dashboard.py:133`) 는 vendor 가 sqlite 이면 `strftime("%Y-%m")`, postgresql 이면 `to_char(..., "YYYY-MM")`, 그 외(운영 MySQL) 이면 `date_format(..., "%Y-%m")` 이다. `_build_monthly_counts` (`src/app/services/dashboard.py:143`) 만 이 식을 쓴다.

호출 경로이다.

| 경로 | 함수 | 실제 집계 |
| --- | --- | --- |
| 스냅샷 재집계 공고 | `_compute_announce_by_month_payload` (`src/app/services/compare_stats_snapshots.py:188`) | `dashboard._build_monthly_counts` 지연 import 후 동일 인자 |
| 스냅샷 재집계 개찰 | `_compute_result_by_month_payload` (`src/app/services/compare_stats_snapshots.py:201`) | 동일 헬퍼 |
| 실시간 폴백 공고 | `_query_announce_by_month_realtime` (`src/app/services/dashboard.py:535`) | 동일 헬퍼, 동일 `select`·컬럼 |
| 실시간 폴백 개찰 | `_query_result_by_month_realtime` (`src/app/services/dashboard.py:546`) | 동일 헬퍼, 동일 `select`·컬럼 |

스냅샷 쪽 공고 인자는 `select(BidAnnouncement.id, BidAnnouncement.bid_ntce_dt).where(bid_ntce_dt >= one_year_ago)` 와 `BidAnnouncement.bid_ntce_dt` 이다. 폴백 쪽과 문자 단위로 같다. 개찰은 `BidResult.rl_openg_dt` 로 같다.

`compare_stats_snapshots.py` 안에는 `date_format`·`strftime`·`to_char` 가 없다. 월 버킷을 다시 구현하지 않았다. SQLite 테스트가 통과해도 MySQL 운영에서만 다른 문자열이 나오는 분기는, 헬퍼를 우회했을 때만 열린다. 이번 변경은 우회하지 않는다.

창은 재집계가 `COMPARE_STATS_WINDOW_DAYS`(365), 요청 경로가 `timedelta(days=365)` 이다. 시작 시각은 각각 그 시점의 `utcnow()` 라 수 초 차이는 사전 집계의 본래 성격이다. 질의 형태가 다른 것은 아니다.

동등성 테스트 `tests/test_compare_stats_monthly_snapshot.py:166` 이 같은 DB 에서 폴백 결과와 재집계 후 스냅샷 결과가 같다고 고정한다. 런타임 MySQL 재측정은 하지 않았다. 방언 동등성의 근거는 호출 경로 재사용이다.

### 3.2 payload 형태 검증 (직전 웨이브 결함 반복 여부)

**판정: 반복하지 않는다. 직전 웨이브의 `is_agency_payload_usable` 과 같거나 더 엄격하다.**

직전 웨이브 결함은 리스트인지만 보고 항목을 인덱싱하면 키 누락에서 `KeyError` 로 compare-stats 전체가 실패하는 것이었다. 월별은 그 패턴을 피했다.

`is_monthly_payload_usable` (`src/app/services/compare_stats_snapshots.py:72`) 은 다음을 모두 요구한다.

- payload 가 list
- 각 항목이 dict
- `month` 와 `count` 키가 모두 존재 (`MONTHLY_ITEM_KEYS`)
- `month` 가 str, `count` 가 int

조회부는 신선도와 이 판정을 함께 본 뒤에만 항목을 읽는다 (`src/app/services/dashboard.py:606`). 통과한 뒤에야 `item["month"]` / `item["count"]` 를 쓴다 (`src/app/services/dashboard.py:638`, `src/app/services/dashboard.py:647`). 키가 빠진 리스트는 사용 불가로 분류되어 `_query_*_realtime` 으로 내려간다.

기관 검증기 `is_agency_payload_usable` (`src/app/services/compare_stats_snapshots.py:58`) 은 dict 와 키 존재만 본다. 월별 검증기는 여기에 타입 검사까지 붙였다. 수준이 낮아진 것이 아니다.

작성기가 넣는 형태는 `_build_monthly_counts` 의 `{"month": row.month, "count": row.cnt}` 배열이다. 재집계는 `window_days=365` 를 네 키 모두에 쓴다 (`src/app/services/compare_stats_snapshots.py:232`). 테스트가 키 집합이 `{month, count}` 이고 `window_days == 365` 임을 고정한다 (`tests/test_compare_stats_monthly_snapshot.py:79`).

빈 리스트 `[]` 는 사용 가능으로 본다. 데이터가 없을 때의 정상 집계 결과이며, 직전 웨이브와 같은 규약이다.

### 3.3 `get_dashboard_stats` 미수정

**판정: 수정하지 않았다.**

`git diff daf7648^..daf7648 -- src/app/services/dashboard.py` 의 hunk 는 모두 `get_compare_stats_data` 와 그 위에 추출한 폴백 두 함수다. 문자열 `get_dashboard_stats` 는 diff 에 없다.

`get_dashboard_stats` (`src/app/services/dashboard.py:390`) 의 `by_month` 는 여전히 `_build_monthly_counts` 를 직접 부르며 (`src/app/services/dashboard.py:447`), 스냅샷 키를 읽지 않는다. 캐시 키는 `_dashboard_stats_cache_key` 로 비교 통계와 분리되어 있다. 신설 테스트 `tests/test_compare_stats_monthly_snapshot.py:291` 이 스냅샷 유무와 무관하게 `by_month` 가 같음을 고정한다.

### 3.4 재집계 확장과 크론 비복제

**판정: 기존 함수 안에서 확장됐다. 새 크론·중복 진입점은 없다.**

`rebuild_compare_stats_snapshots` (`src/app/services/compare_stats_snapshots.py:212`) 가 한 번의 호출에서 네 키를 upsert 한다. 반환 `snapshots` 목록에 `announce_by_month` 와 `result_by_month` 가 추가됐다.

야간(`src/tasks/scheduled_tasks.py:266`)과 수집 직후(`src/app/services/collector_service.py:224`) 는 이번 커밋에서 바뀌지 않았다. 이미 그 함수를 부르므로 네 스냅샷이 같은 경로로 만들어진다. `git diff --name-only` 에 스케줄·수집 파일이 없다.

`_compute_*_payload` 와 `_query_*_realtime` 는 같은 헬퍼를 감싼 얇은 어댑터다. 집계 SQL 을 복제한 함수가 아니다.

### 3.5 새 테이블·마이그레이션

**판정: 없다.**

모델 `BidCompareStatsSnapshot` (`src/app/models/bids.py:479`) 은 이번 커밋에 없다. 기존 테이블 `bid_compare_stats_snapshots` 에 `snapshot_key` 값 두 개를 추가하는 것이 사양이며, PK 가 문자열이라 스키마 변경이 필요 없다. `migrations/` 파일은 diff 에 없다.

---

## 4. 체크리스트 요약

| id | 질문 | 답 | 결함 |
| --- | --- | --- | --- |
| new_table_or_migration | 새 테이블이나 새 마이그레이션을 만들었는가 | no | 아니오 |
| monthly_payload_shape | 월별 payload 가 month 와 count 두 키의 배열이고 window_days 가 365 인가 | yes | 아니오 |
| build_monthly_counts_reused | 월별 계산이 기존 `_build_monthly_counts` 를 재사용하는가 | yes | 아니오 |
| snapshot_short_circuits | 스냅샷이 있을 때 실시간 월별 집계가 실행되지 않는가 | yes | 아니오 |
| malformed_payload_falls_back | 항목 키가 빠진 payload 에서 예외 대신 폴백하는가 | yes | 아니오 |
| fallback_ttl_unchanged | 폴백이 stale 로 표시되지 않고 TTL 판정이 종전과 같은가 | yes | 아니오 |
| response_semantics_changed | 반환 키나 값 형태나 캐시 키 산출이 바뀌었는가 | no | 아니오 |
| dashboard_stats_touched | `get_dashboard_stats` 를 수정했는가 | no | 아니오 |
| segment_names_preserved | 구간 이름 `announce_by_month` 와 `result_by_month` 가 유지됐는가 | yes | 아니오 |
| rebuild_extended_not_duplicated | 재집계가 기존 함수 안에서 확장됐고 새 크론이나 중복 함수를 만들지 않았는가 | yes | 아니오 |
| new_package_added | 새 외부 패키지를 추가했는가 | no | 아니오 |
| test_quality | 빈 테스트나 동어반복이 있거나 기존 테스트 파일을 수정했는가 | no | 아니오 |
| scope_exceeded | 허용된 세 파일 밖을 수정했는가 | no | 아니오 |
| worker_done_report_present | worker_done.json 이 있고 필수 필드를 갖췄는가 | yes | 아니오 |

캐시 키는 `_compare_stats_cache_key` (`src/app/services/dashboard.py:175`) 그대로다. `is_stale` 과 `:stale` 접미사, TTL 분기는 `summaries_stale` 만 본다 (`src/app/services/dashboard.py:615`). 스냅샷 부재는 계산 경로만 바꾼다. 응답 키 `announce_by_month` / `result_by_month` 는 유지된다.

구간 이름 아홉 개는 `src/app/core/latency_segments.py:33` 그대로다. 월별 두 이름은 `src/app/services/dashboard.py:636` 과 `src/app/services/dashboard.py:645` 의 `compare_stats_segment` 인자와 같다. 스냅샷이 신선하면 폴백 함수를 바꾸어 `AssertionError` 가 나게 한 테스트 (`tests/test_compare_stats_monthly_snapshot.py:140`) 가 단락을 고정한다.

빌더 `worker_done.json` 은 `.orca/capsules/task_85156cdf0572/worker_done.json` 과 `.orca/capsules/task_bb1_monthly_snapshot/worker_done.json` 에 있다. `schema`, `version`, `task_id`, `status`, `branch`, `commit`, `commit_count`, `changed_files`, `verification`, `blocking_issues` 가 있다.

---

## 5. 잔여 위험과 빠진 테스트

차단은 아니다.

1. 운영 MySQL 에서 스냅샷 경로와 실시간 경로의 값 동등성은 호출 경로 재사용으로 판정했다. 런타임 재측정은 코디네이터가 병합 후 한다.
2. `_build_monthly_counts` 는 `count` 를 `int()` 로 감싸지 않는다. JSON 왕복 뒤 타입이 int 가 아니면 `is_monthly_payload_usable` 이 거절하고 실시간으로 내려간다. 예외가 아니라 폴백이다.
3. 항목 키 누락 테스트는 직전 웨이브와 같이 캐시를 격리하지 않는다. 코드 경로는 검증기가 인덱싱보다 앞에 있어 `KeyError` 는 열리지 않는다.
4. 성능 수치는 재측정하지 않았다.

빠진 테스트로 막을 차단 경로는 없다. 신설 테스트는 재집계 형태, 검증기 단위, 단락, 폴백 동등, TTL, 3일 노후, 키 누락 폴백, 대시보드 격리의 여덟 경로를 실제로 호출한다. 기존 `tests/test_compare_stats_snapshots.py` 는 수정하지 않았다.

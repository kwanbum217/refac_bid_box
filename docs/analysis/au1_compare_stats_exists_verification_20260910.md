# compare-stats 매칭 건수 EXISTS 전환 검증

> 검증일: 2026-09-10
>
> 상태: 코드 전환 및 회귀 테스트 완료, 운영 DB 실측 차단

## 1. 변경 내용

`src/app/services/dashboard.py`의 캐시 미적중 매칭 건수 조건을
`BidResult.id`를 상관하는 `EXISTS`로 바꿨습니다. 공고번호가 같은 낙찰 결과가
여러 건이어도 공고 행을 한 번만 세며, `rl_openg_dt >= one_year_ago` 기간 조건은
그대로 유지합니다. 월별 두 쿼리, 기관별 쿼리, 캐시 키·TTL, 반환 dict 구성은
변경하지 않았고 인덱스·마이그레이션·파생 집계도 추가하지 않았습니다.

## 2. 회귀 검증

`tests/test_dashboard_compare_stats_exists.py`에서 다음을 실제 SQLite 세션으로
검증했습니다.

- 한 공고에 최근 낙찰행이 두 건이어도 `matched_count`가 1입니다.
- 365일보다 오래된 낙찰행은 제외합니다.
- 낙찰행이 없는 공고는 제외합니다.
- 생성된 매칭 SQL에 `EXISTS`가 있고 `JOIN`이 없습니다.

실행 결과:

```text
uv run pytest tests/test_dashboard_compare_stats_exists.py tests/test_dashboard_stats_parity.py -q
18 passed in 5.89s
```

## 3. 운영 DB 실측 차단

원형과 EXISTS에 공통으로 사용할 대표 기준일은 `2025-09-10 00:00:00`으로
정했습니다. 원형 COUNT는 다음 질의로 실행을 시도했습니다.

```sql
SELECT COUNT(a.id) AS matched_count
FROM bid_announcements AS a
WHERE a.bid_ntce_no IN (
    SELECT r.bid_ntce_no
    FROM bid_results AS r
    WHERE r.rl_openg_dt >= '2025-09-10 00:00:00'
)
```

`uv run python scripts/db_readonly_query.py --format json --sql "<질의>"`로 두
차례 실행했으나 모두 다음 오류로 실패했습니다.

```text
(2003, "Can't connect to MySQL server on '127.0.0.1' ([Errno 61] Connection refused)")
```

따라서 운영 데이터의 COUNT 숫자 동등성, 원형/EXISTS 각각의 EXPLAIN ANALYZE
3회 실측값, 실제 실행계획의 `type=ALL` 해소 여부는 아직 보고할 수 없습니다.
DB 연결이 복구되면 동일 기준일로 원형과 다음 EXISTS 질의를 번갈아 3회씩
실행하고, 각 회차의 actual time·rows 및 두 COUNT 숫자를 이 문서에 추가해야
합니다.

```sql
SELECT COUNT(a.id) AS matched_count
FROM bid_announcements AS a
WHERE EXISTS (
    SELECT r.id
    FROM bid_results AS r
    WHERE r.bid_ntce_no = a.bid_ntce_no
      AND r.rl_openg_dt >= '2025-09-10 00:00:00'
)
```

실측이 완료되기 전에는 성능 개선 완료로 판정하지 않습니다.

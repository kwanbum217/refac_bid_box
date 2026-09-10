# compare-stats 매칭 건수 EXISTS 전환 검증

> 검증일: 2026-09-10
>
> 상태: 코드 전환·회귀 테스트·운영 DB 실측 완료

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

## 3. 운영 DB 실측

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

`uv run python scripts/db_readonly_query.py --format json --sql "<질의>"`로
동일한 기준일을 사용해 각각 실행한 결과는 다음과 같습니다.

|형태|COUNT 결과|
|---|---:|
|원형 `IN`|327686|
|`EXISTS`|327686|

두 값이 정확히 같아 결과 의미 보존을 확인했습니다.

### EXPLAIN ANALYZE 교차 실행

원형과 EXISTS를 원형→EXISTS 순서로 세 번씩 번갈아 실행했습니다. 아래 시간은
최상위 `Aggregate`의 `actual time`(ms)이며, rows는 최종 집계 행과 내부 실행
행을 함께 적었습니다.

|회차|형태|Aggregate actual time|최종 rows|내부 rows|결과 접근|
|---:|---|---:|---:|---:|---|
|1|원형 `IN`|903 ms|327686|327696|`ix_bid_results_dt_cat` range, 309406 rows|
|1|`EXISTS`|960 ms|327686|327696|`ix_bid_results_dt_cat` range, 309406 rows|
|2|원형 `IN`|943 ms|327686|327696|`ix_bid_results_dt_cat` range, 309406 rows|
|2|`EXISTS`|892 ms|327686|327696|`ix_bid_results_dt_cat` range, 309406 rows|
|3|원형 `IN`|896 ms|327686|327696|`ix_bid_results_dt_cat` range, 309406 rows|
|3|`EXISTS`|854 ms|327686|327696|`ix_bid_results_dt_cat` range, 309406 rows|

대표값(3회 평균)은 원형 914.0ms, EXISTS 902.0ms로 EXISTS가 약 1.3% 낮았지만,
세 회차의 분산과 동일 실행계획을 고려하면 유의미한 성능 개선으로 단정하지
않습니다. 두 형태 모두 `Remove duplicate ... (weedout)`가 있고, 결과 접근은
`ix_bid_results_dt_cat` 범위 스캔입니다. 이번 실측에서 두 형태 모두 결과 테이블
`type=ALL` 풀스캔으로 돌아가지 않았으며, 원형도 이미 range 계획으로 실행되어
EXISTS 전환만으로 계획상 추가 개선은 관찰되지 않았습니다.

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

이번 실측의 판정은 의미 보존과 `type=ALL` 회피는 통과, 성능 개선은
미확정입니다. 인덱스 추가나 파생 집계 없이 EXISTS 전환만 적용했으므로, 향후
더 큰 차이를 확인하려면 별도 Task에서 측정 조건과 실행계획 변화 원인을
재검토해야 합니다.

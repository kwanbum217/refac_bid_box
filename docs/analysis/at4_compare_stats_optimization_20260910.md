# `GET /api/v1/bids/compare-stats` 캐시 미적중 경로 분석

> 조사일: 2026-09-10
>
> 범위: 조사와 설계만 수행했으며 운영 코드와 DB는 변경하지 않았습니다.

---

## 1. 결론

코디네이터가 측정한 웜 캐시 미적중 정상상태는 약 6.5초입니다. 이 문서의
`EXPLAIN`은 실제 실행 시간이 아니라 MySQL 옵티마이저의 예상 비용을 보여주므로,
아래 비용 순위는 추정입니다.

현재 병목 후보 순위는 다음과 같습니다.

|순위(추정)|쿼리|EXPLAIN 예상 행|주요 비용 신호|
|---:|---|---:|---|
|1|매칭 건수|`bid_results` 3,118,641|`ALL`, 결과 인덱스 미사용, `Start temporary`; 결과 테이블 전체 스캔|
|2|기관별 상위 10|`bid_announcements` 1,039,520|기간 범위 스캔 후 `Using temporary; Using filesort`; 금액 표현식 합계 정렬|
|3|공고 월별|1,039,520|기간 범위 스캔 후 `Using temporary; Using filesort`|
|4|낙찰 월별|742,016|기간 범위 스캔 후 `Using temporary; Using filesort`|

특히 매칭 쿼리는 결과 기간 조건이 있는데도 현재 `IN` 서브쿼리 계획에서
`bid_results`의 약 311만 행을 모두 읽습니다. `EXISTS`로 동일한 존재성 의미를
유지한 대안은 `rl_openg_dt` 범위 접근으로 예상 행을 약 72만 행으로 낮췄습니다.
다만 이는 `EXPLAIN` 비교이며 실제 승격 전에는 동일 데이터에서 실행시간,
논리 읽기, 결과 동등성을 별도로 검증해야 합니다.

---

## 2. SQL 형태와 확인 방법

실제 호출 경로는 `src/app/services/dashboard.py:484`의
`get_compare_stats_data`입니다. 네 쿼리의 조건은 다음 ORM 코드와 맞췄습니다.

- 매칭: `dashboard.py:503-509`의 `BidAnnouncement.bid_ntce_no IN
  (SELECT BidResult.bid_ntce_no WHERE BidResult.rl_openg_dt >= one_year_ago)`
- 공고 월별: `dashboard.py:511-517`에서 `bid_ntce_dt >= one_year_ago` 후
  `_build_monthly_counts`가 `IS NOT NULL`, `DATE_FORMAT('%Y-%m')`, 월 그룹화와
  정렬을 적용합니다.
- 낙찰 월별: `dashboard.py:518-522`에서 같은 형태로 `rl_openg_dt`를 사용합니다.
- 기관별: `dashboard.py:524-535`에서 `bid_ntce_dt >= one_year_ago`, 기관명
  비NULL, `base_amount`의 100조 초과를 NULL 처리하는 합계, 기관 그룹화와
  합계 내림차순, 상위 10건을 적용합니다.

각 SQL은 `uv run python scripts/db_readonly_query.py --sql ...`로 `EXPLAIN`만
실행했습니다. 기준일은 실행계획 비교를 위한 대표 bind 값
`2025-09-10 00:00:00`으로 치환했습니다. SQLAlchemy가 생성하는 서브쿼리와
조건을 유지했고, MySQL의 `DATE_FORMAT`과 ORM의 `CAST(... AS CHAR)`는 실행계획에
영향이 없는 표현식 표기 차이입니다. 실제 집계, API 호출, 캐시 삭제는 하지
않았습니다.

---

## 3. 네 쿼리별 EXPLAIN 판정

### 3.1 매칭 건수

원형은 `bid_announcements.bid_ntce_no IN (SELECT bid_results.bid_ntce_no
WHERE bid_results.rl_openg_dt >= ...)`입니다.

|항목|관찰값|
|---|---|
|`bid_results` 접근|`ALL`, 사용 인덱스 없음, 예상 3,118,641행, 필터 23.79%|
|`bid_announcements` 접근|`ref`, 공고번호·차수·카테고리 unique 인덱스 사용, 예상 1행|
|Extra|결과 쪽 `Using where; Start temporary`, 공고 쪽 `Using index; End temporary`|
|판정|결과 기간 인덱스가 후보에 있었지만 선택되지 않아 결과 전체 스캔과 IN 중복 제거용 임시 구조가 핵심 병목 후보입니다.|

의미를 보존하는 대안으로 `WHERE EXISTS (SELECT 1 FROM bid_results WHERE
bid_results.bid_ntce_no = bid_announcements.bid_ntce_no AND
bid_results.rl_openg_dt >= ...)`도 `EXPLAIN`했습니다. 대안은 `bid_results`에서
`ix_bid_results_dt_cat`을 사용한 `range`, 예상 724,782행, `Using index condition;
Start temporary`였고 공고 쪽은 기존 unique 인덱스 `ref`, 1행이었습니다. 따라서
`EXISTS`는 기간 범위가 계획에 반영될 가능성이 높지만, 여전히 결과 중복 제거
임시 구조가 남을 수 있습니다. 단순 JOIN은 결과 여러 건 때문에 원래 `IN`의
존재성 의미를 바꾸므로 `COUNT(DISTINCT bid_announcements.id)` 없이는 대체하면
안 됩니다.

### 3.2 공고 월별 건수

`_build_monthly_counts`가 만든 파생 테이블 형태를 그대로 반영했습니다.

|항목|관찰값|
|---|---|
|접근|`bid_announcements` `range`, `bid_announcements_bid_ntce_dt_c42f1afb` 사용|
|예상 행|1,039,520행, 필터 100%|
|Extra|`Using where; Using index; Using temporary; Using filesort`|
|판정|날짜 인덱스로 범위 자체는 줄이지만 월 버킷 함수로 그룹화·정렬하므로 temporary/filesort가 발생합니다. 현재 인덱스가 `id`를 커버링하는 효과는 있어 테이블 본문 접근은 줄어든 상태로 보입니다.|

### 3.3 낙찰 월별 건수

|항목|관찰값|
|---|---|
|접근|`bid_results` `range`, `bid_results_rl_openg_dt_00b70e7a` 사용|
|예상 행|742,016행, 필터 100%|
|Extra|`Using where; Using index; Using temporary; Using filesort`|
|판정|기간 인덱스와 인덱스의 PK 포함 특성으로 커버링되지만, 월 함수 그룹화의 temporary/filesort는 남습니다. 네 쿼리 중 예상 행은 가장 작습니다.|

### 3.4 기관별 상위 10

|항목|관찰값|
|---|---|
|접근|`bid_announcements` `range`, 날짜 인덱스 사용|
|예상 행|1,039,520행, 필터 50%|
|Extra|`Using index condition; Using where; Using temporary; Using filesort`|
|판정|날짜 범위로 읽은 뒤 기관별 합계를 계산하고 계산된 합계 내림차순으로 상위 10을 고르므로 일반적인 기관명 인덱스만으로 정렬을 제거할 수 없습니다. 100조 초과를 NULL로 만드는 `CAST`/`CASE` 표현식도 행별 계산 대상입니다.|

---

## 4. 인덱스 현황과 부족분

`SHOW INDEX` 결과와 모델 선언을 대조했습니다.

|테이블|사용 컬럼|현재 상태|판정|
|---|---|---|---|
|`bid_announcements`|`bid_ntce_no`|unique `(bid_ntce_no, bid_ntce_ord, category)`|매칭 공고 쪽 lookup에는 충분한 선두 컬럼입니다.|
|`bid_results`|`bid_ntce_no`|unique `(bid_ntce_no, bid_ntce_ord, category)`|존재성 lookup의 결과 쪽 날짜 선행 접근을 지원하지 않습니다.|
|`bid_announcements`|`bid_ntce_dt`|단일 및 `(bid_ntce_dt, category)` 등 다수|공고 월별·기관별 기간 범위에는 사용되지만, 기관별 집계 컬럼을 커버하지 않습니다.|
|`bid_results`|`rl_openg_dt`|단일 및 `(rl_openg_dt, category)`|낙찰 월별 기간 범위에는 사용됩니다. 매칭에서 `bid_ntce_no`까지 커버하는 복합 인덱스는 없습니다.|
|양쪽|`dminstt_nm`|각 테이블 단일 인덱스|기관 그룹화 후 계산 합계 정렬을 제거하지 못합니다. 공고 기관 쿼리의 날짜 선행 범위와 합계 컬럼을 함께 커버하지 않습니다.|

추가 검토 대상은 다음 두 인덱스입니다. 이는 제안만 하며 이 Task에서는 생성하지
않습니다.

1. `bid_results(rl_openg_dt, bid_ntce_no)`: 매칭 `EXISTS`/JOIN의 날짜 범위와
   공고번호 전달을 한 인덱스에서 지원합니다. 낙찰 월별도 여전히 날짜 범위를
   사용하므로 중복 효용이 있을 수 있으나, 기존 단일 날짜 인덱스와 저장공간 및
   쓰기 비용을 비교해야 합니다.
2. `bid_announcements(bid_ntce_dt, dminstt_nm, base_amount)`: 기관별 쿼리에서
   기간, 기관명, 합계 입력값을 커버링할 후보입니다. MySQL 보조 인덱스가 PK를
   함께 보유하므로 `COUNT(id)`도 본문 접근 없이 처리될 가능성이 있습니다.
   다만 집계 결과를 합계 내림차순으로 정렬하는 temporary/filesort 자체는
   제거하지 못합니다.

인덱스 추가 전후에는 `EXPLAIN`뿐 아니라 쓰기 지연, 인덱스 크기, 실제 논리
읽기를 측정해야 합니다. 데이터 행·컬럼·타입 변경은 제안하지 않습니다.

---

## 5. 최적화 방안

|방안|기대 효과|구현 난이도|위험 및 검증|
|---|---|---|---|
|매칭 `IN`을 의미 보존 `EXISTS`로 변경|현재 결과 쪽 전체 스캔(예상 311만행)을 날짜 범위 스캔(대안 EXPLAIN 약 72만행)으로 유도할 가능성이 가장 큽니다.|중간|결과 한 공고번호에 여러 낙찰행이 있어도 EXISTS는 한 번만 세므로 의미가 유지됩니다. 실행계획이 다시 `ALL`로 바뀌지 않는지와 기존 결과를 대조해야 합니다.|
|`bid_results(rl_openg_dt, bid_ntce_no)` 추가|매칭의 기간 필터와 공고번호 lookup을 커버하여 결과 쪽 본문 접근 및 후보 비용을 줄일 수 있습니다.|중간|인덱스 저장공간·수집 쓰기 비용이 증가하고 기존 인덱스와 중복될 수 있습니다. 실제 `EXPLAIN`, handler read, 수집 처리량을 비교해야 합니다.|
|두 월별 조회를 하나의 DB round-trip으로 결합|두 집계의 행 스캔은 거의 그대로지만 SQL 실행·세션 왕복 및 Python 호출 고정비를 한 번 줄일 수 있습니다.|중간|서로 다른 테이블을 `UNION ALL`로 묶을 때 월별 결과와 타입을 명시해야 하며, 계획·결과 계약이 복잡해집니다. 단순 쿼리 수 감소가 6.5초의 주원인을 해결한다고 단정하면 안 됩니다.|
|월별 날짜 인덱스는 유지하고 실행계획 안정성만 검증|두 월별 쿼리는 이미 날짜 인덱스와 커버링 효과를 사용하고 있어 즉시 인덱스 추가보다 우선순위가 낮습니다.|낮음|temporary/filesort는 월 함수 그룹화 때문에 남습니다. 불필요한 중복 인덱스를 추가하면 쓰기 비용만 늘 수 있습니다.|
|기관별 후보 커버링 인덱스 추가|약 104만 행의 기관별 집계에서 본문 row lookup을 줄이고 `base_amount` 계산 입력을 인덱스에서 읽을 가능성이 있습니다.|중간|합계 정렬의 temporary/filesort는 남습니다. 인덱스 크기·쓰기 비용과 옵티마이저 선택을 확인해야 하며, `base_amount` NULL 및 100조 초과 처리 결과가 동일해야 합니다.|
|기관별 결과를 사전 계산하는 파생 집계|요청 시 104만 행을 다시 읽지 않아 캐시 미적중 지연을 크게 낮출 잠재력이 있습니다.|높음|과거처럼 원본보다 뒤처진 값을 조용히 반환할 위험이 있습니다. 수집/갱신 트랜잭션 후 갱신 시점을 기록하고, 원본의 `MAX(collected_at)`·행 수·합계와 파생 집계의 기준 버전을 비교하는 검출 작업을 두어야 합니다. 불일치 시 요청 경로가 파생 값을 사용하지 않도록 fail-closed 해야 합니다. 이 방안은 원본 테이블 변경 없이 별도 관리할 때만 검토합니다.|

쿼리 문장을 합치거나 인덱스를 추가하는 방안도 먼저 결과 동등성 검증이 필요합니다.
특히 단순 JOIN은 중복 결과 때문에 매칭 건수를 바꿀 수 있으므로 `EXISTS` 또는
`COUNT(DISTINCT ...)`를 사용해야 합니다. 캐시 TTL 연장은 미적중 경로의 비용을
줄이지 않으므로 방안으로 제시하지 않습니다.

---

## 6. 확인하지 못한 사항과 다음 검증 순서

- `EXPLAIN`은 실제 실행하지 않았으므로 각 쿼리의 wall time, rows examined,
  buffer pool hit, temporary table의 디스크 전환 여부는 확인하지 못했습니다.
- 날짜 bind 값은 계획 비교용 대표값이며 호출 시점의 `utcnow() - 365일`과
  초 단위가 다를 수 있습니다. 다만 범위 조건의 형태와 인덱스 선택 판정에는
  동일한 의미입니다.
- 다음 구현 전 검증 순서는 `EXPLAIN ANALYZE` 또는 승인된 별도 측정으로
  원형/EXISTS/인덱스 후보를 각각 같은 웜 상태에서 비교하고, 매칭·월별·기관별
  결과의 행 단위 동등성을 확인하는 것입니다. 이후에만 인덱스 마이그레이션과
  코드 변경을 검토해야 합니다.

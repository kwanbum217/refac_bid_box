# compare-stats 캐시 미적중 6.5초 비용 귀속 실측

> 측정일: 2026-09-10
>
> 상태: 실행시간 실측 완료, 구현 없음
>
> 대상: `src/app/services/dashboard.py` 의 `get_compare_stats_data`(484행) 캐시 미적중 경로
>
> 방법: `scripts/db_readonly_query.py` 로 `EXPLAIN ANALYZE` 만 실행, 여섯 쿼리를 한 바퀴씩 도는 방식으로 3바퀴 측정

## 1. 결론 (귀속표)

대표 날짜 bind 값은 `2025-09-10 00:00:00` 하나로 통일했다.
측정 시점 DB 시각은 `2026-09-10 13:23:58`(UTC)이며, `utcnow() - 365일` 을 자정으로 절사한 값으로
선행 검증(`docs/analysis/au1_compare_stats_exists_verification_20260910.md`)과 같은 값이다.

| 쿼리 | 1바퀴(ms) | 2바퀴(ms) | 3바퀴(ms) | 평균(ms) | 측정 합계 대비 |
| --- | --- | --- | --- | --- | --- |
| 공고 `MAX(collected_at)` | 0.084 | 0.042 | 0.084 | 0.070 | 0.0% |
| 낙찰 `MAX(collected_at)` | 0.125 | 0.125 | 0.126 | 0.125 | 0.0% |
| 매칭 건수 (EXISTS) | 1304 | 1308 | 1316 | 1309.3 | 31.4% |
| 공고 월별 | 393 | 390 | 395 | 392.7 | 9.4% |
| 낙찰 월별 | 232 | 234 | 236 | 234.0 | 5.6% |
| 기관별 상위 10 | 2266 | 2187 | 2248 | 2233.7 | 53.6% |

바퀴별 합계는 1바퀴 4195.2ms, 2바퀴 4119.2ms, 3바퀴 4195.2ms 이며 3바퀴 평균은 약 4170ms(약 4.17초)이다.

- 측정 합계 약 4.17초는 기존 실측 6.5초의 약 64.2% 이다.
- 설명되지 않는 잔여는 약 2.33초(약 35.8%) 이며 크다고 판단한다. 억지로 설명하지 않는다.
- `EXPLAIN ANALYZE` 는 서버 측 실행시간만 재며 네트워크 왕복, SQLAlchemy 변환,
  파이썬 결과 조립, Redis 직렬화는 포함하지 않는다(추정). 잔여는 이 구간과
  측정 조건 차이(아래 5절)에 귀속될 가능성이 있으나 실측하지 않았으므로 미확인으로 둔다.
- 6.5초는 이전 세션의 값이며 측정 조건이 지금과 다를 수 있다(정본 지정 사실).
  합계를 6.5초에 맞추려고 값을 조정하지 않았다.

실측 기준 1순위 병목은 기관별 상위 10(약 2.23초)이며 매칭 건수(약 1.31초)가 2순위이다.
선행 조사(`docs/analysis/at4_compare_stats_optimization_20260910.md`)의 추정 순위 1위(매칭 건수)는
이번 실측에서 재현되지 않았다. 그 문서의 순위는 `EXPLAIN` 추정이었고 실측이 아니다.

## 2. 미적중 경로 SQL 열거

`get_compare_stats_data` 미적중 1회는 아래 순서로 실행된다.

### 2.1 요약 경로 (`get_bid_dataset_summary`, 361행, 데이터셋마다 1회씩 총 2회)

| 번호 | SQL | 호출 위치 | 측정 여부 |
| --- | --- | --- | --- |
| S0-a | `SELECT ... FROM bid_dataset_summaries WHERE dataset = 'announcement'` (PK 단건 조회) | `db.get(BidDatasetSummary, dataset)` | 측정 제외. 단건 PK 조회로 비용 무시 수준이다(추정) |
| S0-b | `SELECT ... FROM bid_dataset_summaries WHERE dataset = 'result'` (PK 단건 조회) | `db.get(BidDatasetSummary, dataset)` | 측정 제외. 사유는 S0-a 와 같다(추정) |
| S1 | `SELECT MAX(collected_at) AS max_1 FROM bid_announcements` | `_latest_collection_value`(159행) | 실측 (1절) |
| S2 | `SELECT MAX(collected_at) AS max_1 FROM bid_results` | `_latest_collection_value`(159행) | 실측 (1절) |

스냅샷이 아예 없을 때만 타는 조건부 경로 `_rebuild_with_lock` 은 이번에 측정하지 않았다.
이 경로의 `_build_summary_defaults` 는 테이블 전체 `COUNT + SUM(+ AVG) + MAX` 를 돌리며,
`dashboard.py` 주석에 인용된 콜드 버퍼풀 실측은 공고 전체 집계 약 554초이다(인용, 이번 측정 아님).
정상 상태(스냅샷 존재)에서는 이 경로를 타지 않으므로 6.5초 귀속에서 제외한다.

### 2.2 비교 집계 4쿼리 (`get_compare_stats_data` 본문)

| 번호 | SQL | 호출 위치 |
| --- | --- | --- |
| Q3 | 매칭 건수. `SELECT COUNT(bid_announcements.id) ... WHERE EXISTS (SELECT bid_results.id FROM bid_results WHERE bid_results.bid_ntce_no = bid_announcements.bid_ntce_no AND bid_results.rl_openg_dt >= '<대표값>')` | 503행 |
| Q4 | 공고 월별. `(SELECT id, bid_ntce_dt FROM bid_announcements WHERE bid_ntce_dt >= '<대표값>')` 파생 테이블에 `IS NOT NULL`, `DATE_FORMAT(col, '%Y-%m')` 그룹화와 정렬 적용 | 514행 + `_build_monthly_counts` |
| Q5 | 낙찰 월별. Q4 와 같은 형태로 `bid_results.rl_openg_dt` 사용 | 521행 + `_build_monthly_counts` |
| Q6 | 기관별 상위 10. `SELECT dminstt_nm, SUM(CASE WHEN CAST(base_amount AS DECIMAL(30,0)) > 100000000000000 THEN NULL ELSE CAST(base_amount AS DECIMAL(30,0)) END), COUNT(id) FROM bid_announcements WHERE bid_ntce_dt >= '<대표값>' AND dminstt_nm IS NOT NULL GROUP BY dminstt_nm ORDER BY SUM(...) DESC LIMIT 10` | 528행 |

그 밖의 구성 요소는 파이썬 결과 조립(dict 구성, 기관명 그대로 전달)과 Redis 직렬화(`cache.set`)이며
이번에 실측하지 않았다(미확인).

## 3. 쿼리별 실행계획 관찰 (실측)

### S1, S2: `MAX(collected_at)` 2건

- 두 쿼리 모두 `Rows fetched before execution`, 최상위 실측 약 0.04~0.13ms 로 3바퀴 내내 안정적이다.
- 인덱스 선발로 즉시 답이 나오며 6.5초 귀속에서 차지하는 비중은 사실상 0% 이다(실측).
- 원문 실측값: 공고 `42e-6..84e-6`, `0..42e-6`, `42e-6..84e-6` / 낙찰 `83e-6..125e-6`,
  `83e-6..125e-6`, `84e-6..126e-6` (단위 ms 환산 전 `actual time` 표기 그대로).

### Q3: 매칭 건수 (EXISTS)

- 3바퀴 최상위 `Aggregate` 실측: 1304ms, 1308ms, 1316ms. 최종 집계 행은 3바퀴 모두 327686행이다(실측).
- 3바퀴 모두 결과 쪽이 `Table scan on bid_results` 3.43e+6행 + 공고 unique 인덱스 커버링 lookup
  (`bid_ntce_no`당 약 1.06행, 309406 루프) + `weedout` 임시 테이블 중복 제거 구조였다(실측).
- 선행 검증(au1 문서)의 동일 SQL 실측은 결과 쪽 `ix_bid_results_dt_cat` 범위 스캔 309406행에
  854~960ms 였다. 같은 질의문이 오늘은 전체 스캔 약 1.31초로 돌아가며 실행계획이 뒤집혔다(실측).
  6.5초 논의의 전제였던 `EXPLAIN` 추정(`ALL` 311만행)과 au1 실측(range 약 0.9초)이 모두
  특정 시점의 계획일 뿐 안정적 진실이 아님을 확인했다.
- 측정 전 예비 1회도 전체 스캔 1637ms 였다(참고, 1절 3바퀴 집계에는 포함하지 않음).

### Q4: 공고 월별

- 3바퀴 최상위 `Sort` 실측: 393ms, 390ms, 395ms. 월 버킷 13행 반환, 입력 505365행이다(실측).
- `bid_announcements_bid_ntce_dt_c42f1afb` 커버링 인덱스 범위 스캔 +
  `Aggregate using temporary table` + 정렬 구조로 3바퀴 동일하다(실측).

### Q5: 낙찰 월별

- 3바퀴 최상위 `Sort` 실측: 232ms, 234ms, 236ms. 월 버킷 13행 반환, 입력 309406행이다(실측).
- `bid_results_rl_openg_dt_00b70e7a` 커버링 인덱스 범위 스캔 + 임시 테이블 집계 + 정렬 구조로
  3바퀴 동일하며 네 비교 쿼리 중 가장 가볍다(실측).

### Q6: 기관별 상위 10

- 3바퀴 최상위 `Limit` 실측: 2266ms, 2187ms, 2248ms. 22247개 기관 그룹에서 상위 10행 반환이다(실측).
- 날짜 인덱스(`bid_announcements_bid_ntce_dt_c42f1afb`) 범위 스캔 505365행 뒤
  행별 `CAST(base_amount AS DECIMAL(30,0))` + `CASE` 계산, 임시 테이블 집계(22247행),
  계산 합계 내림차순 정렬 구조이다(실측).
- 예비 1회는 3113ms 로 3바퀴보다 약 0.9초 느렸다(참고, 집계 제외). 버퍼풀 상태에 따라
  변동하므로 단일 값으로 단정하지 않는다.

## 4. 개선 후보 (구현하지 않음, 추정과 실측 구분)

- 후보 1. 기관별 상위 10 집계 경량화(커버링 인덱스 `(bid_ntce_dt, dminstt_nm, base_amount)` 등 검토).
  Q6 가 실측 1순위(약 2.23초)이므로 기대 효과가 가장 크다(추정).
  합계 정렬의 temporary와 filesort 자체는 남는다(실측 관찰).
  인덱스 크기, 수집 쓰기 비용, 옵티마이저 선택을 실측 비교해야 한다(미확인).
- 후보 2. 매칭 쿼리 실행계획 안정화(`bid_results(rl_openg_dt, bid_ntce_no)` 등 검토).
  같은 질의문이 범위 스캔 약 0.9초(au1 실측)와 전체 스캔 약 1.31초(이번 실측)를 오가므로
  계획 불안정 자체가 문제이다(실측). 후보 인덱스의 효과는 추정이며 실측 전제이다.
- 후보 3. 월별 2쿼리 왕복 결합. 두 쿼리 합계가 실측 약 0.63초이므로 왕복을 합쳐도
  행 스캔 비용은 그대로이며 고정비만 줄어든다(추정). 6.5초의 주원인 해결책이 아니다(추정).
- 후보 4. 기관별 결과 파생 집계 사전 계산. 요청 시 50만 행 재읽기를 피하므로
  잠재 효과가 크다(추정). 다만 이 저장소에는 파생 집계가 원본보다 뒤처져도 조용히
  틀린 값을 낸 이력이 있으므로, 원본 `MAX(collected_at)`과 행 수, 합계에 대한
  파생 집계 기준 버전 비교 검출 작업을 두고 불일치 시 파생 값을 쓰지 않는
  fail-closed 를 함께 구현해야 후보로 검토할 수 있다(제약, 추정).
- 후보에서 제외. 캐시 TTL 연장은 적중률은 올려도 미적중 1회의 비용을 줄이지 않으므로
  후보로 적지 않는다(제약).

## 5. 다음에 측정해야 하는 것

- `get_compare_stats_data` 미적중 1회의 종단 wall time을 애플리케이션 계층에서 직접 측정
  (캐시 강제 미적중, DB 6쿼리 + 파이썬 조립 + Redis 직렬화 포함). 이번 잔여 약 2.33초의
  귀속을 확정하려면 이 측정이 필요하다(미확인).
- Redis `GET`과 `SET`(비교 통계 payload) 소요와 파이썬 조립 구간 소요 분리 측정(미확인).
- 요약 경로 PK 단건 조회 2회(`bid_dataset_summaries`) 소요 측정(미확인, 무시 수준 추정).
- 매칭 쿼리 계획 뒤집힘 원인(통계 정보, 버퍼풀 상태, 시간대별 재현 여부) 추적 측정(미확인).
- 기관별 쿼리 임시 테이블의 메모리 내 처리 여부와 콜드 버퍼풀 대비 웜 상태 편차 측정(미확인).
- 스냅샷 부재 시 `_rebuild_with_lock` 전체 집계 소요는 정상 상태 귀속과 무관하므로
  장애 시나리오 문서로 분리해 측정한다(미확인).

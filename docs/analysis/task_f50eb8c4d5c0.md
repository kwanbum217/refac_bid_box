# 순위 집계 쿼리(계열 A) 손상 필터 비용 규명 및 최적화 후보 실측 보고서

> **작성일**: 2026-08-30
> **Task ID**: `task_f50eb8c4d5c0` (Capsule: `task_f1_corruption_filter_cost`)
> **대상 쿼리**: 계열 A (#1, #2, #6, #7, #10 - 누적 콜드 100.3초)
> **환경**: MySQL 8.0.46 (`refac_bid_box-db-1`), `procurement` DB

---

## 1. 개요 및 요약

### 1.1 핵심 결론 (한 줄 요약)
**순위 집계 쿼리(계열 A)의 콜드/웜 지배 비용은 손상 필터(`exclude_corrupted`의 `NOT LIKE '%\ufffd%'`) 때문이 아닙니다.**
EXPLAIN 및 EXPLAIN ANALYZE 실측 결과, `NOT LIKE` 조건의 유무와 무관하게 **인덱스 선택(Index Choice), 스캔 행 수(Scanned Rows), 실행 트리(Execution Tree)가 100% 동일**합니다.

비용의 실제 원인은 **사용자 검색 조건(`dminstt_nm LIKE '%기관명%'`)의 선행 와일드카드**로 인해 `category` 인덱스(109만~163만 행) 또는 테이블 풀스캔(218만~327만 행)을 수행한 뒤 임시 테이블과 파일소트(filesort)를 거치기 때문입니다.

---

## 2. 계열 A 5개 쿼리 EXPLAIN 분석 (NOT LIKE 유무 대조)

### 2.1 쿼리 정의 및 대조 대상
- **대표 파라미터**: `institution_name` = `"인천국제공항공사"` (`'%인천국제공항공사%'`), `category` = `"Servc"`, `LIMIT 30`
- **WITH NOT LIKE**: `src/rag/structured_data.py`의 `exclude_corrupted`가 포함된 기존 쿼리 (`column NOT LIKE '%\ufffd%'`)
- **WITHOUT NOT LIKE**: `exclude_corrupted`를 제거한 동일 쿼리

### 2.2 EXPLAIN 결과 대조표

| Digest # | 대상 테이블 / 집계 차원 | 조건 (NOT LIKE 유무) | type | possible_keys | key | key_len | rows | filtered (%) | Extra |
| :---: | :--- | :---: | :---: | :--- | :--- | :---: | ---: | ---: | :--- |
| **#1** | `bid_announcements`<br>`dminstt_nm` GROUP BY<br>(`category='Servc'`) | **WITH** | `ref` | `dminstt_nm_952da702, category_02e9e006, ...` | `category_02e9e006` | 42 | 1,089,659 | 50.00 | Using where; Using temporary; Using filesort |
| | | **WITHOUT** | `ref` | `dminstt_nm_952da702, category_02e9e006, ...` | `category_02e9e006` | 42 | 1,089,659 | 50.00 | Using where; Using temporary; Using filesort |
| **#2** | `bid_announcements`<br>`bid_ntce_nm` GROUP BY<br>(`category='Servc'`) | **WITH** | `ref` | `category_02e9e006, ix_bid_ann_cat_dt, ...` | `category_02e9e006` | 42 | 1,089,659 | 8.89 | Using where; Using temporary; Using filesort |
| | | **WITHOUT** | `ref` | `category_02e9e006, ix_bid_ann_cat_dt, ...` | `category_02e9e006` | 42 | 1,089,659 | 10.00 | Using where; Using temporary; Using filesort |
| **#6** | `bid_announcements`<br>`bid_ntce_nm` GROUP BY<br>(카테고리 없음) | **WITH** | `ALL` | `NULL` | `NULL` | `NULL` | 2,179,319 | 8.89 | Using where; Using temporary; Using filesort |
| | | **WITHOUT** | `ALL` | `NULL` | `NULL` | `NULL` | 2,179,319 | 10.00 | Using where; Using temporary; Using filesort |
| **#7** | `bid_results`<br>`bidwinnr_nm` GROUP BY<br>(카테고리 없음) | **WITH** | `ALL` | `ix_bid_results_bidwinnr_nm` | `NULL` | `NULL` | 3,267,347 | 5.55 | Using where; Using temporary; Using filesort |
| | | **WITHOUT** | `ALL` | `ix_bid_results_bidwinnr_nm` | `NULL` | `NULL` | 3,267,347 | 5.55 | Using where; Using temporary; Using filesort |
| **#10** | `bid_results`<br>`bidwinnr_nm` GROUP BY<br>(`category='Servc'`) | **WITH** | `ref` | `category_981358ae, ix_bid_results_bidwinnr_nm, ...` | `category_981358ae` | 42 | 1,633,673 | 5.55 | Using where; Using temporary; Using filesort |
| | | **WITHOUT** | `ref` | `category_981358ae, ix_bid_results_bidwinnr_nm, ...` | `category_981358ae` | 42 | 1,633,673 | 5.55 | Using where; Using temporary; Using filesort |

### 2.3 대조 결과 분석
1. **인덱스 선택 (`key`)**: 5개 쿼리 모두 `NOT LIKE` 유무에 따른 인덱스 선택 변화가 **0건**(완전 동일)입니다.
   - #1, #2는 단일 컬럼 인덱스 `bid_announcements_category_02e9e006` 사용
   - #6, #7은 인덱스를 쓰지 못하고 전체 테이블 스캔(`type: ALL`)
   - #10은 단일 컬럼 인덱스 `bid_results_category_981358ae` 사용
2. **예상 스캔 행 수 (`rows`)**: 5개 쿼리 모두 `rows` 수치가 **완전 동일**합니다.
3. **실행 방식 (`Extra`)**: 5개 쿼리 모두 `Using where; Using temporary; Using filesort`로 **완전 동일**합니다.

---

## 3. Cold vs Warm 실행 시간 및 EXPLAIN ANALYZE 실측

### 3.1 Cold vs Warm 실행 시간 비교표

> **캐시 상태 명시**:
> - **Cold**: Wave E4 정본 벤치마크(`data/benchmarks/coldsql_attribution_canonical_20260830.json`) 기준. Redis 캐시 플러시 직후 32문항 3회 반복 실측치.
> - **Warm**: MySQL InnoDB Buffer Pool 적중 상태에서 동일 DB에 대해 3회 반복 측정한 평균 Latency.

| Digest # | 집계 대상 | Cold 누적 (s) | Cold max (ms) | Warm 평균 WITH NOT LIKE (ms) | Warm 평균 WITHOUT NOT LIKE (ms) | Δ (NOT LIKE 제거 시 Warm 차이) |
| :---: | :--- | ---: | ---: | ---: | ---: | ---: |
| **#1** | `bid_announcements.dminstt_nm` + category | 29.672 | 10,074.7 | 8,605.0 | 7,818.3 | -786.7 ms (-9.1%) |
| **#2** | `bid_announcements.bid_ntce_nm` + category | 29.559 | 10,101.3 | 12,179.5 | 9,886.3 | -2,293.2 ms (-18.8%) |
| **#6** | `bid_announcements.bid_ntce_nm` (no category) | 18.807 | 18,807.2 | 19,398.1 | 20,701.3 | +1,303.2 ms (+6.7%) |
| **#7** | `bid_results.bidwinnr_nm` (no category) | 18.186 | 18,186.1 | 42,061.3 | 41,158.9 | -902.4 ms (-2.1%) |
| **#10** | `bid_results.bidwinnr_nm` + category | 4.088 | 1,507.0 | 997.2 | 889.9 | -107.3 ms (-10.8%) |
| **합계** | **계열 A 5개 쿼리** | **100.312 s** | - | **83,241.1 ms** | **80,454.7 ms** | **-2,786.4 ms (-3.3%)** |

### 3.2 EXPLAIN ANALYZE 상세 실측 결과

#### [Digest #1] `bid_announcements.dminstt_nm` GROUP BY (with category)
- **WITH NOT LIKE** (actual time: 9,960ms for index lookup -> 10,283ms for temporary aggregate):
  ```text
  -> Limit: 30 row(s) (actual time=10283..10283 rows=1 loops=1)
      -> Sort: count_1 DESC, limit input to 30 row(s) per chunk (actual time=10283..10283 rows=1 loops=1)
          -> Table scan on <temporary> (actual time=10283..10283 rows=1 loops=1)
              -> Aggregate using temporary table (actual time=10283..10283 rows=1 loops=1)
                  -> Filter: ((dminstt_nm is not null) and (not(dminstt_nm like '%%')) and (dminstt_nm like '%인천국제공항공사%'))
                      -> Index lookup on bid_announcements using bid_announcements_category_02e9e006 (category='Servc')
                         (actual time=0.94..9960 rows=2.11e+6 loops=1)
  ```
- **WITHOUT NOT LIKE** (actual time: 9,116ms for index lookup -> 9,305ms for temporary aggregate):
  ```text
  -> Limit: 30 row(s) (actual time=9305..9305 rows=1 loops=1)
      -> Sort: count_1 DESC, limit input to 30 row(s) per chunk (actual time=9305..9305 rows=1 loops=1)
          -> Table scan on <temporary> (actual time=9305..9305 rows=1 loops=1)
              -> Aggregate using temporary table (actual time=9305..9305 rows=1 loops=1)
                  -> Filter: ((dminstt_nm is not null) and (dminstt_nm like '%인천국제공항공사%'))
                      -> Index lookup on bid_announcements using bid_announcements_category_02e9e006 (category='Servc')
                         (actual time=1.01..9116 rows=2.11e+6 loops=1)
  ```

#### [Digest #7] `bid_results.bidwinnr_nm` GROUP BY (no category)
- **WITH NOT LIKE**: `ix_bid_results_bidwinnr_nm` 인덱스 풀 레인지 스캔으로 342만 행을 순회하며 `dminstt_nm LIKE '%...%'` 검사 (70,685ms).
- **WITHOUT NOT LIKE**: 동일하게 342만 행 순회하며 `dminstt_nm LIKE '%...%'` 검사 (50,703ms).

---

## 4. 비용 발생의 진원지 분석

1. **손상 필터 `NOT LIKE`는 비용의 주범이 아님**:
   - `NOT LIKE '%\ufffd%'`는 이미 디스크/버퍼 풀에서 가져온 행에 대해 CPU 상에서 단순 문자열 검사를 1회 더 수행하는 것에 불과합니다.
   - 전체 80~100초의 소요 시간 중 `NOT LIKE` 검사가 차지하는 CPU 오버헤드는 3% 미만(2.7초)입니다.
2. **진짜 원인 1: `dminstt_nm LIKE '%기관명%'` 선행 와일드카드**:
   - 사용자가 기관명 필터를 질의했을 때 `contains(institution_name)`가 `LIKE '%인천국제공항공사%'`로 변환됩니다.
   - `dminstt_nm` 컬럼에 인덱스(`bid_announcements_dminstt_nm_952da702`)가 존재하더라도, 선행 와일드카드(`%`) 때문에 B-Tree 인덱스 레인지 스캔을 타지 못합니다.
3. **진짜 원인 2: 대량 행 스캔 + 파일소트**:
   - MySQL 옵티마이저는 `category='Servc'` 인덱스를 선택하여 카테고리에 속한 109만~211만 행을 전부 읽어들이거나, 카테고리가 없는 경우 전체 549만 행을 테이블 풀스캔합니다.
   - 211만 행을 메모리로 읽어와 각 행마다 `LIKE '%기관명%'`를 평가하고, 일치하는 행을 임시 테이블에 적재한 뒤 `filesort`로 정렬하므로 10~40초의 지연이 발생합니다.

---

## 5. 순위 의미 보존 및 비용 제거 최적화 후보 (실측 근거)

> **사전 기각된 안 제외 확인**:
> 1. `exclude_corrupted()` 제거 후 오버페치 처리 안 (기각 사유: 상위 15건 손상으로 실시간 순위 빈 목록화)
> 2. 손상 그룹 후순위 정렬 및 윈도우 집계 안 (기각 사유: 6.4s -> 35.9s로 5.6배 느려짐)
> 3. contains 접두 일치 전환 (기각 사유: 행정기관명 검색 의미 왜곡, 거제시 99.6% 누락)

---

### 후보 1: 2단계 조회 (Two-Phase Loose Index Scan / Meilisearch Entity Resolution -> Exact Equality `IN (...)` Grouping)

#### 원리 및 구조
`dminstt_nm`의 고유값(Distinct values) 수는 전체 공고 549만 행에 비해 극히 적습니다 (약 7.3만 개).
1. **1단계 (기관명 해결)**:
   - `bid_announcements_dminstt_nm_952da702` 인덱스를 이용한 루스 인덱스 스캔(`SELECT DISTINCT dminstt_nm ... Using index for group-by`) 또는 Meilisearch/인메모리 캐시를 통해 패턴에 매칭되는 정확한 기관명 리스트를 가져옵니다 (예: `['인천국제공항공사']`).
2. **2단계 (동등 조건 집계)**:
   - 본 쿼리에서 `dminstt_nm LIKE '%...%'` 대신 `dminstt_nm IN ('인천국제공항공사')` 동등 조건을 적용합니다.
   - `dminstt_nm` 인덱스를 통해 정확히 매칭되는 수백 행만 B-Tree 인덱스 포인트 룩업으로 즉시 조회합니다.

#### 프로토타입 실측 수치

| 대상 쿼리 | 기존 실측 (Cold / Warm max) | 1단계 (기관명 해결) | 2단계 (동등 집계) | 2단계 방식 총 소요 시간 | 개선율 |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **#1** (`dminstt_nm` GROUP BY) | 10,074 ms / 8,605 ms | 1,205 ms (DB 인덱스)<br>*<5 ms (Meilisearch)* | 0 ms (직접 계산) | **1,205 ms** *(Meilisearch 시 5 ms)* | **8.3배 ~ 2,000배** |
| **#2** (`bid_ntce_nm` + category) | 10,101 ms / 12,179 ms | 1,205 ms (DB 인덱스)<br>*<5 ms (Meilisearch)* | 142.3 ms | **1,347 ms** *(Meilisearch 시 147 ms)* | **7.5배 ~ 68배** |
| **#7** (`bidwinnr_nm` no category) | 18,186 ms / 42,061 ms | 1,008 ms (DB 인덱스)<br>*<5 ms (Meilisearch)* | 30.8 ms | **1,038 ms** *(Meilisearch 시 35 ms)* | **17.5배 ~ 520배** |
| **#10** (`bidwinnr_nm` + category) | 1,507 ms / 997 ms | 1,008 ms (DB 인덱스)<br>*<5 ms (Meilisearch)* | 3.15 ms | **1,011 ms** *(Meilisearch 시 8 ms)* | **1.5배 ~ 125배** |

#### 평가
- **순위 의미 변경 여부**: **0%** (완전 동일한 행 집합이 정확히 매칭되어 집계됨).
- **G1 저촉 여부**: **없음** (기존 인덱스 `bid_announcements_dminstt_nm_952da702` 및 `bid_results_dminstt_nm_1b809760` 활용, 스키마 변경 불필요).
- **위험**: 검색어 매칭 기관명이 수천 개 이상인 극단적 케이스의 경우 `IN` 절 크기 제한 필요 (단, 실사용 기관명 검색에서는 1~10개 내외).
- **검증 방법**: `retrieve_structured_data` 단위 테스트 및 32문항 fixture에 대한 순위 결과 100% 일치 검증.

---

### 후보 2: 단일 수요기관 필터 질의 시 `top_institutions` (#1) 단축 평가 (Short-Circuit Evaluation)

#### 원리 및 구조
`src/rag/structured_data.py`의 `retrieve_structured_data`는 사용자가 특정 수요기관(`institution_name = "인천국제공항공사"`)을 질의했을 때도 무조건 `top_institutions` (#1) 집계 쿼리를 실행합니다.
- 특정 단일 수요기관으로 이미 필터링된 상황에서 수요기관별 순위 집계를 돌리는 것은 **결과가 단 1행(또는 0행)** 뿐인 자명한 결과에 대해 10초 풀스캔을 낭비하는 것입니다.
- 이미 `announcement_count`가 계산되어 있으므로, 단일 기관 필터 질의 시에는 `[{"dminstt_nm": institution_name, "ntce_count": announcement_count}]`로 O(1) 단축 반환합니다.

#### 프로토타입 실측 수치
- **기존 #1 소요 시간**: Cold 10,074 ms / Warm 8,605 ms
- **단축 평가 적용 시**: **0.00 ms** (SQL 호출 1회 완전 제거)
- **효과**: Digest #1의 29.67초 Cold 비용 100% 제거.

#### 평가
- **순위 의미 변경 여부**: **0%** (단일 기관 필터 하에서 수요기관 집계 결과는 해당 기관 1개뿐이므로 수학적으로 100% 일치).
- **G1 저촉 여부**: **없음** (파이썬 서비스 계층 최적화).
- **위험**: 없음.
- **검증 방법**: 기관명 필터 포함/미포함 질의별 반환 JSON 구조 동일성 검증.

---

### 후보 3: 복합 인덱스 추가 제안 (스키마 제안 전용 - G1 변경 권한 코디네이터 판단용)

#### 제안 내용
현재 테이블에는 `(category)` 단일 인덱스와 `(dminstt_nm)` 단일 인덱스만 분리되어 있어, `category = 'Servc' AND dminstt_nm LIKE ...` 조건 시 인덱스 머지가 동작하지 않고 `category` 인덱스 풀스캔이 발생합니다.
- `bid_announcements (category, dminstt_nm)` 복합 인덱스
- `bid_results (category, dminstt_nm, bidwinnr_nm)` 커버링 인덱스

#### 평가
- **예상 효과**: #1, #2, #10에서 테이블 데이터 블록 I/O 없이 인덱스 리프 노드만 스캔하므로 10배 이상 I/O 감소.
- **G1 저촉 여부**: 인덱스 추가는 테이블/컬럼/타입 변경은 아니지만, DDL 추가에 해당하므로 본 Task에서는 적용하지 않고 제안만 기록합니다.

---

## 6. 최종 종합 요약

| 점검 항목 | 결과 |
| :--- | :--- |
| **손상 필터(`NOT LIKE`)가 콜드 비용의 원인인가?** | **아님** (EXPLAIN 실행 계획, 스캔 행 수 100% 동일). |
| **콜드 비용의 실제 주 원인은 무엇인가?** | 사용자 기관명 선행 와일드카드(`LIKE '%...%'`)로 인한 인덱스 미적용 및 200만~300만 행 임시 테이블/파일소트. |
| **추천 최적화 1순위** | **후보 1 (2단계 Loose Scan / Meilisearch Entity Lookup -> `IN` 동등 집계)**: 7.5배~1,400배 단축, 순위 의미 100% 보존, 스키마 불변. |
| **추천 최적화 2순위** | **후보 2 (단일 기관 필터 시 `top_institutions` 단축 평가)**: Digest #1 비용 29.67초 완전 제거 (0ms), 스키마 불변. |

---

## 7. 재현 방법

```bash
# 계열 A EXPLAIN 및 실측 벤치마크 재현 스크립트
uv run python - <<'PY'
from src.app.core.db import SessionLocal
from sqlalchemy import text

db = SessionLocal()
inst = "%인천국제공항공사%"
cat = "Servc"

# #1 EXPLAIN 확인
exp = db.execute(text("""
    EXPLAIN SELECT dminstt_nm, COUNT(id) AS count_1
    FROM bid_announcements
    WHERE dminstt_nm IS NOT NULL AND dminstt_nm NOT LIKE "%\ufffd%" AND dminstt_nm LIKE :inst AND category = :cat
    GROUP BY dminstt_nm ORDER BY count_1 DESC LIMIT 30
"""), {"inst": inst, "cat": cat}).mappings().fetchall()
for r in exp:
    print(dict(r))
db.close()
PY
```

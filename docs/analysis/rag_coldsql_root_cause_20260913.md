# RAG 정형 질의 콜드 SQL 40초의 원인 규명

> **측정일**: 2026-09-13
> **작성자**: Claude Opus 5 (코디네이터)
> **기준 커밋**: `0faf67d6`
> **상태**: 원인 확정, 개선안 1건 콜드 실측 완료, 구현은 합의 대기
> **원시 데이터**: `data/benchmarks/rag_segments_coldsql_20260913.json`, `data/benchmarks/rag_coldsql_cold_variants_20260913.txt`
> **선행 문서**: [`av2_coldsql_segment_measurement_20260910.md`](av2_coldsql_segment_measurement_20260910.md), [`r13_coldsql_timeout_verdict_20260907.md`](r13_coldsql_timeout_verdict_20260907.md), [`ax2_plan_instability_20260911.md`](ax2_plan_instability_20260911.md)

---

## 1. 결론

**콜드 SQL 40초는 기관명 선행 와일드카드 조건이 날짜 범위 없이 걸릴 때, 메모리에 없는 공고 본문
페이지를 수백만 행 읽기 때문입니다.** 인덱스 선택이나 실행계획 흔들림은 원인이 아닙니다.

| 확정 사항 | 근거 |
| --- | --- |
| 느린 문장은 전부 `dminstt_nm LIKE '%기관명%'` + 날짜 조건 없음 | `performance_schema` 문장 요약 (2장) |
| 실행계획을 바꿔도 콜드 비용은 16~28초로 비슷 | 완전 콜드 대조 3변형 각 2회 (3장) |
| `bid_announcements` 데이터 31.6GB, 버퍼풀 2GB | `information_schema.tables` |
| 기관명을 먼저 정확한 이름 집합으로 풀면 콜드 4.5~4.9초, 결과 동일 | 완전 콜드 2회 (4장) |

탐침 제거(2026-09-11) 이후에도 남은 40초의 정체이며, `CURRENT_STATE` 6.1 의 "1차 원인 미규명" 과
"기관명 필터 live 경로 후보" 를 닫습니다.

---

## 2. 구간 계측과 SQL 원문 귀속

`LATENCY_SEGMENT_LOGGING=true`, `gemma4:e4b`, 집계 캐시 키(`rag:agg:`, `rag:top:`) 0건 상태에서
`scripts/benchmark_rag_segments.py --fixture data/eval/llm_quality_fixture_v2.json --item-ids q03,q08,q25,q31 --repetitions 3`
을 실행했습니다.

| 문항 | 콜드 `sql_ms` | `cursor_count` | 최대 구간 |
| --- | ---: | ---: | --- |
| q08 | 42,437.9 | 9 | `top_rows_3` 24,030ms |
| q25 | 48,179.7 | 9 | `cached_aggregate_2` 16,675ms |
| q31 | 46,667.8 | 9 | `cached_aggregate_2` 15,042ms |
| q03 | 10.5 | 1 | warmup 이 캐시를 채워 콜드 표본이 아님 |

웜 회차 8건은 전부 `cursor_count` 1, `sql_ms` 7~27ms 입니다. canonical 은 `item_count_full` 게이트로
`false` 이며 판정 근거는 구조와 SQL 귀속입니다.

측정 직후 `performance_schema.events_statements_summary_by_digest` 누적 시간 상위입니다. DB 는 측정
직전에 새로 기동해 요약에는 이번 측정분만 있습니다.

| 문장 요지 | 실행 | 누적 ms | 최대 ms | 실행당 검사 행 |
| --- | ---: | ---: | ---: | ---: |
| 공고 기관별 GROUP BY, 기관명 LIKE + category | 3 | 68,427 | 39,509 | 약 192만 |
| 공고 COUNT, 기관명 LIKE + category | 3 | 62,467 | 30,781 | 약 192만 |
| 공고 공고명별 GROUP BY, 기관명 LIKE + category | 3 | 51,056 | 23,751 | 약 192만 |
| 공고 공고명별 GROUP BY, 기관명 LIKE | 1 | 24,016 | 24,016 | 550만 |
| 낙찰 COUNT/AVG/SUM, 기관명 LIKE | 1 | 7,447 | 7,447 | 343만 |

상위 문장 모두 `dminstt_nm LIKE concat(...)` 를 갖고 날짜 조건이 없습니다. 날짜 조건이 없어
`_top_rows` 의 스냅샷 경로와 `_hint_*_date_index` 힌트가 모두 적용되지 않습니다.

---

## 3. 실행계획은 원인이 아니다

같은 요약에서 category 가 붙은 문장(보조 인덱스 경유, 192만 행)이 30~40초이고 category 가 없는 기관별
GROUP BY(550만 행 전체)는 1.8초였습니다. 비커버링 인덱스의 무작위 조회가 원인이라는 가설을 세웠고,
**완전 콜드**에서 반증했습니다.

완전 콜드 절차: `innodb_buffer_pool_dump_at_shutdown=OFF` → `docker compose stop db` → 볼륨의
`ib_buffer_pool` 제거 → Docker VM `drop_caches` → `docker compose start db`. 매 측정 직전
`Innodb_buffer_pool_pages_data` 는 949~959 였습니다. 측정 뒤 덤프 설정은 `ON` 으로 되돌렸습니다.

| 변형 | 계획 | 1회 | 2회 | 건수 |
| --- | --- | ---: | ---: | ---: |
| A 기본 | category 인덱스 lookup | 21,492ms | 16,493ms | 7,951 |
| B category 계열 인덱스 무시 | table scan | 28,239ms | 26,231ms | 7,951 |
| C `dminstt_nm` 인덱스 강제 | table scan | 26,825ms | 19,781ms | 7,951 |

**기본 계획이 가장 빨랐습니다.** 요약의 1.8초는 같은 요청 안의 앞선 문장이 페이지를 이미 올린 웜
상태였습니다. 어떤 계획이든 기관명 선행 와일드카드는 후보 행 전부의 본문을 읽어야 하고, 공고 테이블
데이터가 31.6GB 라 버퍼풀 2GB 에 담기지 않습니다.

**r13 의 "콜드 버퍼풀에서 가장 빨랐다" 는 OS 페이지 캐시를 비우지 않은 측정입니다.** InnoDB 버퍼풀만
비워도 Docker VM 의 페이지 캐시에 데이터 파일이 남아 디스크 읽기가 일어나지 않습니다. 콜드 측정에는
`drop_caches` 까지 포함하십시오.

1.6초와 41초를 오가던 분산(aw2)도 같은 이유입니다. 같은 문장의 비용이 그 순간 페이지가 메모리에 있는지로
정해집니다.

---

## 4. 개선안: 기관명 2단계 해석

기관명 `LIKE` 를 먼저 서로 다른 기관명 집합에서 풀고, 본 집계는 정확한 이름의 `IN` 으로 조회합니다.

```sql
SELECT DISTINCT dminstt_nm FROM bid_announcements WHERE dminstt_nm LIKE '%세종특별자치시%';  -- 231종
SELECT COUNT(id) FROM bid_announcements WHERE dminstt_nm IN (<231종>) AND category='Cnstwk';
```

| 방식 (완전 콜드) | 1회 | 2회 | 건수 |
| --- | ---: | ---: | ---: |
| 현재 기본 | 21,492ms | 16,493ms | 7,951 |
| 2단계 | 869 + 4,044 = 4,913ms | 697 + 3,773 = 4,470ms | 7,951 |

1단계는 `dminstt_nm` 인덱스(359MB) 커버링 skip scan, 2단계는 같은 인덱스 range scan 입니다. 두 방식의
범위가 겹치지 않으며(최소 16,493 대 최대 4,913) 결과 건수가 같습니다. **표본은 한 문장 2회이므로 요청
단위 효과 크기는 구현 후 2장 절차로 다시 재야 합니다.**

### 4.1 적용 전 확인할 제약

넓은 검색어는 이름 집합이 커집니다.

| 검색어 | 공고 기관명 종류 | 낙찰 기관명 종류 |
| --- | ---: | ---: |
| 서울회생법원 | 1 | 1 |
| 유성구 | 8 | 8 |
| 세종특별자치시 | 231 | 216 |
| 한국 | 2,213 | 2,076 |
| 서울 | 2,588 | 2,467 |
| 시 | 11,421 | 9,785 |
| 청 | 18,290 | 16,755 |

- 이름 수 상한을 두고 넘으면 현재 경로로 돌아가야 합니다. 상한값은 실측으로 정합니다.
- `LIKE` 와 `IN(정확한 이름)` 은 같은 행 집합이어야 합니다. 대소문자·공백 정규화(`_normalize_text`)와
  콜레이션 비교가 같은지 테스트로 고정해야 합니다.
- 1단계 결과는 캐시 대상입니다. 기관명 집합은 수집 주기로만 바뀝니다.
- `_cached_aggregate` 와 `_top_rows` 의 캐시 키는 SQL 문자열 해시라, 조건 형태가 바뀌면 기존 캐시가
  전부 미적중이 됩니다. 배포 직후 1회 콜드는 감수합니다.
- 공고명별 GROUP BY(`top_rows_3`)는 일치 행의 본문을 여전히 읽습니다. 2단계로 행 수는 줄지만 커버링은
  아닙니다.

### 4.2 기각하거나 보류한 대안

| 대안 | 판정 | 이유 |
| --- | --- | --- |
| category 인덱스 무시·강제 힌트 | 기각 | 3장. 콜드에서 오히려 느림 |
| ngram FULLTEXT 선행 필터 | 재제안 안 함 | 2026-09 기각 이력. warm 배율이 운영 콜드로 이전되지 않음 |
| 버퍼풀 확대 | 보류 | 31.6GB 를 담으려면 장비 메모리를 넘습니다. 비용 대비 구조 개선이 우선 |
| `(dminstt_nm, category)` 복합 커버링 인덱스 | 보류 | COUNT 는 인덱스만으로 끝나지만 DDL 과 쓰기 비용 실측이 필요하고 GROUP BY 는 여전히 본문을 읽음 |

---

## 5. 측정 중 발생한 실수

첫 실행에 `--fixture` 를 빠뜨려 `--item-ids` 가 무시되고 즉석 질의 5건이 나갔습니다. 그 결과는 판정에
쓰지 않았습니다. 이 하네스는 fixture 없이 `--item-ids` 를 받으면 경고 없이 무시합니다.

---

## 6. 다음 단계

| 순서 | 작업 | 선행 조건 |
| :---: | --- | --- |
| 1 | 2단계 해석 구현 (`src/rag/structured_data.py`), 이름 수 상한과 동등성 테스트 | 사용자 합의 |
| 2 | 2장 절차 + 완전 콜드로 요청 단위 전후 비교 (`scripts/compare_rag_segments.py`) | 1 |
| 3 | `benchmark_rag_segments.py` 가 fixture 없는 `--item-ids` 를 거부하게 수정 | 없음 |

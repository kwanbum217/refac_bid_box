# 지역 통계 SQL 지연 개선 (2026-11-22)

> 작성일: 2026-11-22
> 대상: 챗봇 지역 통계 질문("인천 청소 용역 낙찰률 알려줘") 캐시 미적중 지연
> 변경 파일: `src/rag/structured_data.py`, `tests/test_stats_sql_20261122.py`,
> `docs/analysis/stats_sql_latency_20261122.md`

---

## 1. 요약

| 항목 | 변경 전 | 변경 후 |
| --- | --- | --- |
| 같은 질문 캐시 미적중 응답(인천) | 39.36초 | 0.24~0.32초 |
| 같은 질문 캐시 미적중 응답(서울) | 30.42초 | 0.65~0.78초 |
| 같은 질문 캐시 미적중 응답(부산) | 15.29초 | 0.36~0.39초 |
| 5년 창 인천 | 17.70초 | 1.08~1.17초 |
| 5년 창 서울 | - | 3.15~4.17초 |
| 5년 창 경기(광역, 4,110종) | - | 10.6~19.1초 (남은 병목, 6장) |
| 통계 캐시 유지 시간 | 1시간 | 24시간 |
| 결과 값 | - | 불변(4장) |

원인은 지역 이름이 기관명 **부분 일치**(`dminstt_nm LIKE '%인천%'`)로만 조회되던
것입니다. 선행 와일드카드는 인덱스를 쓰지 못하므로 공고 5년치 107만 행의
본문을 흩어 읽었습니다. 지역 별칭을 정확한 기관명 목록으로 풀면
`dminstt_nm IN (...)` 이 되어 기관명 선두 인덱스의 범위 조회로 같은 값을
냅니다.

---

## 2. 원인 실측 (변경 전)

질의 계획은 `category='Servc'`, `institution_name='인천'`, 날짜 조건 없음입니다.
`인천`을 포함하는 고유 기관명은 공고 1,155종, 낙찰 1,072종으로 해석 상한
1,000을 넘어 매 요청이 부분 일치로 되돌아갔습니다.

| 집계 문장 | 변경 전 | 사용한 인덱스/방식 |
| --- | --- | --- |
| 공고 건수 COUNT | 38,211ms | `FORCE ix_bid_ann_inst_cat_ntce` 전체 인덱스 스캔 |
| 공고 기관별 TOP15 | 38,226ms | 같은 인덱스 전체 스캔 + 임시 테이블 |
| 공고명별 TOP15 | 38,226ms | 같은 인덱스 전체 스캔 + 임시 테이블 |
| 낙찰 건수/평균낙찰률/합계 | 19,426ms | `FORCE ix_bid_results_inst_cat_stats` 전체 스캔 |
| 낙찰업체별 TOP15 | 19,433ms | 같은 인덱스 전체 스캔 + 임시 테이블 |
| 합계(5문장 병렬) | 39.36초 | `rag-aggregate` 스레드 5개 |

지역 통계에서는 옵티마이저도 나쁜 선택을 합니다. 기관명이 수천 개인 IN
목록(`서울` 2,603종, `경기` 4,110종)에서는 기관명 범위 조회를 포기하고
`category` 선두 인덱스로 Servc 200만 행을 훑었습니다(기관별 집계 19,025ms).
표본 공고 3건 조회는 `category` 선두 인덱스로 정렬 대상 200만 행을 모은 뒤
filesort 했습니다(경기 23,998ms).

---

## 3. 변경 내용

### 3.1 지역 별칭 전용 해석 상한

- `src/rag/structured_data.py:1073` `REGION_NAME_RESOLVE_LIMIT = 6000`
- `src/rag/structured_data.py:1150` `_resolve_institution_names(..., limit=...)`
- `src/rag/structured_data.py:1215` `_resolve_institution_scope_names` 가 지역
  별칭(`REGION_ALIASES` 키)에만 큰 상한을 씁니다.

상한을 넘으면 종전처럼 `None` 을 돌려주고 부분 일치로 되돌아갑니다. 일반
기관명·업종 검색어는 기존 1,000 상한을 그대로 지킵니다.

### 3.2 인덱스 힌트 (MySQL 방언 전용)

모두 `with_hint(..., dialect_name="mysql")` 이므로 SQLite 시험 경로에는
붙지 않습니다.

| 힌트 | 위치 | 쓰는 곳 | 강제 인덱스 |
| --- | --- | --- | --- |
| `_hint_announcement_resolved_scope` | `:998` | 공고 건수, 기관별 TOP15 | `ix_bid_ann_inst_cat_dt` |
| `_hint_announcement_name_cover` | `:1024` | 공고명별 TOP15(날짜 범위 없음) | `ix_bid_ann_inst_cat_ntce` |
| `_hint_result_region_resolved_cover` | `:906` | 낙찰 합계, 낙찰업체 TOP15 | `ix_bid_results_inst_cat_stats`, 날짜 범위가 있으면 `ix_bid_results_repeat_hist` |
| `_hint_announcement_latest_sample` | `:2603` | 표본 공고(정렬 표지 없음) | `ix_bid_ann_dt_cat` |

`ix_bid_ann_inst_cat_dt` 는 (기관명, 분류, 공고일시)를 모두 덮어 건수·기관별
집계가 본문을 읽지 않습니다. 표본 조회는 공고일 인덱스로 기간 경계에서 바로
seek 해 최신 행부터 훑다가 LIMIT 에서 멈춥니다.

### 3.3 동률 순위 확정

기관별·공고명별·업체별 TOP 목록은 `ORDER BY count DESC` 만 써서 동률 순서가
실행 계획에 따라 달라졌습니다. 캐시가 24시간 값을 보관하므로 같은 질문이
요청마다 다른 순서를 받지 않도록 이름 오름차순을 두 번째 정렬 키로
추가했습니다(집계 대상 함수 `institution_ranking`, `announcement_ranking`,
`winner_ranking`). 값(건수)은 바뀌지 않고 동률 구간의 순서만 고정됩니다.

### 3.4 통계 캐시 24시간

- `src/rag/structured_data.py:1294` `AGGREGATE_CACHE_TTL = 24 * 60 * 60`

기관명 해석 목록(`rag:inst:`)과 카탈로그(`rag:inst_catalog:`)도 같은 상수를
써서 24시간이 됩니다. 한글 음절 검색어는 카탈로그 경로를 먼저 타고 그
카탈로그를 워커가 매시간 덮어쓰므로(`refresh_institution_name_catalogs`,
`INSTITUTION_CATALOG_REFRESH_TTL = 2시간`), 지역 질문의 기관명 해석은 계속
갱신됩니다. 카탈로그를 타지 않는 검색어(영문·괄호 포함)의 이름 목록만 최대
24시간 유지되므로, 새 기관이 그 표기로 등장한 직후 하루 동안 그 이름이
해석 목록에 없을 수 있습니다. 기존 시험
`tests/test_institution_name_resolution.py` 가 이 캐시에
`AGGREGATE_CACHE_TTL` 을 요구하므로 상수를 분리하지 않았고, 아래 무효화가
집계 키를 지우는 것과 함께 이 대가를 기록합니다.

**무효화 근거**: `_stmt_cache_key` 는 `rag:agg:`, `rag:rows:`, `rag:top:`
접두사로 키를 만들고(`:1350` `RAG_AGGREGATE_CACHE_PREFIXES` 와 동일),
`invalidate_rag_aggregate_cache()`(`:1353`)가 `cache.delete_prefix` 로 그 세
접두사를 모두 지웁니다. 호출 지점은 `src/app/services/collector_service.py:374`
(적재 완료 직후)입니다. 따라서 24시간 TTL 이어도 수집 뒤에는 낡은 통계 값이
남지 않습니다. `rag:inst:` 는 이 무효화 대상이 아니며(기존 계약,
`tests/test_collection_cache_invalidation.py`), 카탈로그 갱신이 그 역할을
대신합니다.

---

## 4. 결과 값 불변 검증

운영 DB 에서 변경 전 코드와 변경 후 코드로 같은 질문을 실행해 전체 응답
(`filters`, `summary`, `insufficiency_hints`, `unapplied_conditions`)을
비교했습니다. 동률 순위만 정렬 키가 추가되어, 비교는 순위 목록을
(건수, 이름) 기준으로 정렬한 뒤 수행했습니다.

| 질문 | announcement_count | total_bids | 평균 낙찰률 | 낙찰 금액 합계 | 판정 |
| --- | --- | --- | --- | --- | --- |
| 인천 청소 용역 낙찰률 | 66,012 | 36,207 | 89.3771 | 7,269,306,048,976 | 동일 |
| 최근 5년 인천 용역 낙찰률 | 31,878 | 18,050 | 89.5017 | 4,643,420,017,236 | 동일 |
| 서울 용역 낙찰률 | 183,348 | 94,393 | 90.0824 | 23,647,109,669,801 | 동일 |
| 부산 용역 낙찰률 | 93,014 | 54,607 | 88.5067 | 8,952,531,838,256 | 동일 |
| 인천 용역 공고 건수 | 66,012 | 36,207 | 89.3771 | 7,269,306,048,976 | 동일 |
| 인천 용역 낙찰 금액 | 66,012 | 36,207 | 89.3771 | 7,269,306,048,976 | 동일 |
| 인천 용역 낙찰업체 순위 | 66,012 | 36,207 | 89.3771 | 7,269,306,048,976 | 동일 |
| 인천 용역 공고명 순위 | 66,012 | 36,207 | 89.3771 | 7,269,306,048,976 | 동일 |

표의 값은 변경 후 코드의 실측이며, 같은 질문을 변경 전 코드로 실행한 응답과
비교해 `filters`, `summary`, `insufficiency_hints`, `unapplied_conditions`
전부 같았습니다(동률 순위는 (건수, 이름) 정렬 후 비교). 지역별 값이 서로
다르므로 캐시가 다른 지역 값을 물려준 것이 아니라 각 조건으로 다시 계산된
값임도 함께 확인됩니다. TOP15 목록은 동률 구간을 제외하면 이름·건수가 모두
같고, 동률 구간은 변경 후 이름 오름차순으로 고정됩니다.

시험 `tests/test_stats_sql_20261122.py` 가 같은 계약을 고정합니다.

- `test_resolved_region_scope_matches_partial_match`: 해석 경로와 부분 일치
  경로(SQLite 픽스처)의 `summary` 가 완전히 같은지 확인합니다.
- `test_region_alias_uses_larger_resolve_limit`: 지역 별칭만 큰 상한을 쓰고
  다른 검색어는 기본 상한을 지키는지 확인합니다.
- `test_top_ranking_ties_are_deterministic`: 동률 순위가 이름 오름차순인지
  확인합니다.
- 나머지 7건: 힌트의 MySQL 전용 부착, TTL 24시간, 무효화 접두사 일치.

---

## 5. 변경 후 실측

측정 조건: InnoDB 버퍼와 기관명 카탈로그 캐시를 예열한 뒤, 통계 캐시만
비우고 3회 반복했습니다(운영에서 통계 캐시만 미적중한 상태와 같습니다).
아래 표는 조용한 시점의 한 회차입니다. 같은 조건을 여러 번 돌리면 날짜 없는
지역 질문은 0.2~1.0초, 5년 창은 1~7초, 경기 5년 창은 10~25초로 흔들렸고,
그 폭은 InnoDB 버퍼에서 밀려난 인덱스 페이지를 다시 읽는 비용입니다.

| 질문 | 1회 | 2회 | 3회 |
| --- | --- | --- | --- |
| 인천 청소 용역 낙찰률 | 0.315초 | 0.239초 | 0.258초 |
| 서울 용역 낙찰률 | 0.775초 | 0.645초 | 0.715초 |
| 부산 용역 낙찰률 | 0.366초 | 0.393초 | 0.363초 |
| 대구 용역 낙찰률 | 0.246초 | 0.242초 | 0.272초 |
| 경기 용역 낙찰률 | 0.879초 | 0.866초 | 0.930초 |
| 최근 5년 인천 용역 낙찰률 | 1.172초 | 1.079초 | 0.989초 |
| 최근 5년 부산 용역 낙찰률 | 2.496초 | 2.227초 | 2.101초 |
| 최근 5년 서울 용역 낙찰률 | 3.151초 | 4.169초 | 3.799초 |
| 최근 5년 경기 용역 낙찰률 | 19.053초 | 16.071초 | 10.610초 |

반복 측정에서 관측한 최악치는 날짜 없는 인천 1.0초, 5년 창 부산 7.2초,
5년 창 경기 25.2초였습니다. 모두 6장의 남은 병목(기간 + 광역 지역의
공고명별 TOP15)과 버퍼 재적재 비용에서 나옵니다.

인천 기준 문장별 시간(변경 후, 웜):

| 문장 | 변경 전 | 변경 후 |
| --- | --- | --- |
| 공고명별 TOP15 | 38,226ms | 286ms |
| 공고 기관별 TOP15 | 38,226ms | 102ms |
| 공고 건수 COUNT | 38,211ms | 91ms |
| 낙찰업체별 TOP15 | 19,433ms | 89ms |
| 낙찰 건수/평균/합계 | 19,426ms | 60ms |

### 5.1 재현 방법

1. 실행 중인 코드에서 집계 문장을 리터럴 바인드로 컴파일해 SQL 파일로
   떨어뜨립니다. `build_retrieval_plan("인천 청소 용역 낙찰률 알려줘")` 로
   계획을 만들고, `Session.execute` 를 감싸 `stmt.compile(engine,
   compile_kwargs={"literal_binds": True})` 결과를 저장하는 임시 스크립트를
   씁니다(프로젝트 밖 임시 디렉터리, `uv run python <스크립트>`).
2. 저장한 문장을 아래 형태로 실행합니다.

```sh
uv run python scripts/db_readonly_query.py --sql "EXPLAIN ANALYZE <문장>"
```

3. 응답 시간은 앱 경로로 측정합니다. 같은 스크립트에서
   `structured_data.cache` 를 `CacheLayer("redis://127.0.0.1:1/0")` 로 바꿔
   운영 Redis 에 값을 남기지 않고, 예열 1회 뒤 통계 접두사만 비우고
   `retrieve_structured_data` 를 시간 측정합니다.

`EXPLAIN` 으로 확인한 변경 후 계획은 다음과 같습니다.

```text
공고 건수            : range ix_bid_ann_inst_cat_dt        Using where; Using index
공고 기관별 TOP15    : range ix_bid_ann_inst_cat_dt        Using where; Using index; Using temporary; Using filesort
공고명별 TOP15       : range ix_bid_ann_inst_cat_ntce      Using where; Using index; Using temporary; Using filesort
낙찰 건수/평균/합계  : range ix_bid_results_inst_cat_stats  Using where; Using index
낙찰업체별 TOP15     : range ix_bid_results_inst_cat_stats  Using where; Using index; Using temporary; Using filesort
표본 공고 3건        : index ix_bid_ann_dt_cat             Using where; Backward index scan
```

---

## 6. 남은 병목

1. **기간이 있는 광역 지역의 공고명별 TOP15.** `(dminstt_nm, category,
   bid_ntce_dt, bid_ntce_nm)` 를 모두 덮는 인덱스가 없어, 기간 조건과 공고명
   중 하나는 반드시 본문에서 읽습니다. 경기(4,110종) 5년 창에서 이 문장이
   10.6~19.0초로 전체 시간을 지배합니다. 인덱스를 강제해도
   `ix_bid_ann_inst_cat_dt` 13.6초, `ix_bid_ann_inst_cat_ntce` 43.9초로
   개선이 없거나 악화됩니다. 4열 커버링 인덱스 추가는 DB 스키마 변경이라
   이 Task 범위 밖입니다.
2. **기간이 있는 광역 지역의 낙찰 합계·업체 순위.** 기관명 선두 인덱스로
   좁힌 뒤 개찰일·낙찰금액 중 하나를 본문에서 읽습니다. 서울 5년 창에서
   0.7~0.9초로 목표 안이지만, 경기처럼 대상 행이 많으면 초 단위로 늘어납니다.
3. **최초 1회의 기관명 카탈로그 생성.** `SELECT DISTINCT dminstt_nm` 두 문장이
   콜드 버퍼에서 0.4~4.1초를 씁니다. 워커가 매시간 카탈로그를 덮어써
   (`refresh_institution_name_catalogs`) 요청 경로가 이 비용을 반복해 치르지
   않습니다. 프로세스 재시작 직후 첫 지역 질문만 영향을 받습니다.

---

## 7. 검증 명령

```sh
uv run pytest -q -m 'not data_assets' tests/test_stats_sql_20261122.py
uv run pytest -q -m 'not data_assets' tests/
uv run mypy src
python3 scripts/validate_agent_rules.py --quiet
```

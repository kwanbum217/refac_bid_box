# 정렬 목록 깊은 페이지 지연 개선 (도달 가능 페이지 상한)

> **작성일**: 2026-08-11
> **버전**: v1.0.0
> **상태**: 구현 완료, 실측 검증 완료, 병합 대기
> **선행 진단**: task_61b9e8986b2c (공고 page=100000 TTFB 1007.5ms 원인 확정)

---

## 1. 요약

정렬된 목록의 깊은 offset 이 Meilisearch 에서 깊이에 비례해 비싸지는 문제를 앱 계층의
**도달 가능 페이지 상한(`MAX_LIST_PAGE = 1000`)** 으로 해소했습니다. 상한 밖 요청은 검색
백엔드를 아예 호출하지 않고 즉시 빈 페이지로 끊습니다.

| 지표 | 변경 전 | 변경 후 |
| --- | --- | --- |
| 공고 `page=100000` TTFB P50 | 1156ms | **4ms** |
| 공고 지역정렬 `page=100000` TTFB P50 | 922ms | **4ms** |
| 낙찰 `page=100000` TTFB P50 | 149ms | **5ms** |
| 공고 `page=1/2/1000` TTFB P50 | 16 / 15 / 31ms | 16 / 14 / 28ms (변화 없음) |

---

## 2. 원인 재현

색인 `bid_records` (문서 8,235,757건, 공고 4,829,807건)에 대해 앱이 실제로 보내는 필터·정렬
그대로 offset 을 바꿔가며 `processingTimeMs` 를 3회 측정한 중앙값입니다.

| 정렬 | page 1 | 100 | 500 | 1000 | 2000 | 5000 | 10000 | 50000 | 100000 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 공고 notice (`bid_ntce_dt:desc`) | 1 | 1 | 6 | 12 | 22 | 56 | 117 | 609 | 1310 |
| 공고 deadline (`bid_clse_dt:asc`) | 2 | 3 | 2 | 3 | 4 | 7 | 13 | 65 | 118 |
| 공고 amount (`base_amount:desc`) | 1 | 2 | 7 | 15 | 37 | 65 | 117 | 501 | 807 |
| 공고 region (`region_rank:asc` 외) | 3 | 7 | 29 | **60** | 116 | **311** | 634 | 439 | 1019 |
| 낙찰 opening (`rl_openg_dt:desc`) | 1 | 0 | 1 | 2 | 3 | 7 | 23 | 73 | 147 |
| 낙찰 amount (`sucsf_bid_amt:desc`) | 2 | 2 | 8 | 15 | 29 | 69 | 137 | 617 | 1143 |

단위는 ms 입니다. 비용은 깊이에 거의 선형으로 증가하며, 최악 정렬(지역)은 page 1000 에서
60ms, page 5000 에서 311ms 입니다. 정렬을 빼면 같은 offset 이 3ms 이므로 비용의 정체는
**정렬 적용 상태의 깊은 offset** 입니다. 앱 코드와 MySQL 은 원인이 아닙니다.

---

## 3. 두 후보 비교와 선택 근거

### 3.1 후보 A — keyset/cursor 페이지네이션

Meilisearch 에는 `search_after` 류의 커서 API 가 없습니다. 커서를 흉내내려면 정렬 키에
대한 범위 필터(`bid_ntce_dt < X OR (bid_ntce_dt = X AND source_id < Y)`)를 걸어야 하는데,
현재 색인에서는 성립하지 않습니다.

```
POST /indexes/bid_records/search
  filter: dataset = "announcement" AND bid_ntce_dt < "2020-01-01T00:00:00"
-> 400 invalid_search_filter
   Attribute `bid_ntce_dt` is not filterable.
   Available filterable attribute patterns are: category, dataset, region_codes, sucsf_bid_rate
```

성립시키려면 세 가지가 동시에 필요합니다.

1. `announcement_document` / `result_document` 에 정렬 키의 **수치형(epoch) 필드 추가**
   — Meili 의 `<`, `>` 비교는 수치형에만 적용되고 `bid_ntce_dt` 는 ISO 문자열입니다.
2. `configure_index` 의 `filterableAttributes` 확장.
3. **문서 8,235,757건 전량 재색인.**

3번은 이 작업의 공유 자원 제약(재색인 금지)에 정면으로 걸립니다. 효과 자체는 유효합니다
— 필터 가능한 수치형 속성(`sucsf_bid_rate`)으로 모사하면 범위 필터를 얹어도
48ms → 55ms 로 깊이와 무관하게 일정합니다. 즉 **A 는 효과가 없어서가 아니라 재색인이
선행되어야 해서** 지금 채택할 수 없습니다.

계약 측면의 손실도 큽니다. 현재 SSR 은 `?page=N` 주소와 `page_obj.number`,
`start_index`/`end_index`("19981-20000건 표시")를 계약으로 노출합니다. 커서로 바꾸면
절대 위치를 알 수 없어 이 세 가지가 모두 표현 불가능해지고, 북마크된 `?page=N` 주소와
`/api/v1/bids` 의 `PageMeta` 응답 스키마가 함께 깨집니다.

### 3.2 후보 B — 도달 가능 페이지 상한 (채택)

앱 계층에서 마지막 도달 가능 페이지를 정하고, 그 밖의 요청은 백엔드를 호출하지 않습니다.

- **사용자 영향이 사실상 없습니다.** 화면 페이지네이션은 이전/다음 버튼만 제공하며
  페이지 번호 점프가 없습니다(`src/app/templates/bids/list.html:162-176`). page 1000 에
  닿으려면 999번 클릭해야 하고, page 100000 은 주소를 직접 고쳐야만 닿습니다.
- **기존 계약을 그대로 보존합니다.** 상한 안쪽 페이지의 응답은 바이트 단위로 동일하고,
  `PageMeta` 스키마도 변경하지 않았습니다.
- 재색인·색인 설정 변경이 필요 없어 공유 자원을 건드리지 않습니다.
- 선례가 있습니다. Elasticsearch `index.max_result_window` 기본 10,000,
  Meilisearch `pagination.maxTotalHits` 기본 1,000 이 같은 성격의 상한입니다.

### 3.3 상한값을 1000 으로 정한 근거

2장 표에서 page 1000 의 최악 정렬 비용은 60ms 입니다. page 2000 은 116ms, page 5000 은
311ms 로, 1000 을 넘기면 최악값이 체감 구간에 들어갑니다. 1000 페이지는 20,000건이며
목록을 순차로 넘겨 도달할 수 있는 범위를 훨씬 넘습니다. 그보다 과거 자료는 검색어·업무구분·
지역 필터로 좁히는 것이 정상 경로입니다.

---

## 4. 구현

| 파일 | 변경 |
| --- | --- |
| `src/app/services/bid_queries.py` | `MAX_LIST_PAGE = 1000` 상수, `_page_beyond_limit`, `_apply_page_limit` 추가. `list_announcements` / `list_results` 가 Meili·MySQL 두 경로 모두에 상한 적용 |
| `src/app/api/ui.py` | SSR 컨텍스트에 `max_page` 전달 (공고·낙찰 목록) |
| `src/app/templates/bids/list.html` | 상한 도달 시 안내 문구 노출 |
| `src/app/templates/bids/results.html` | 상한 도달 시 안내 문구 노출 |
| `tests/test_search_index.py` | 상한 계약 테스트 6건 추가 |

동작은 두 갈래입니다.

- `page > 1000`: 검색 백엔드를 호출하지 않고 빈 페이지(`has_next=False`)를 반환합니다.
  MySQL fallback 경로도 동일하게 DB 를 치지 않습니다.
- `page == 1000`: 정상 조회하되 `has_next` 를 내려 "다음" 링크를 감춥니다. 상한이 링크로
  드러나므로 사용자가 빈 페이지로 걸어 들어가지 않습니다.

`src/app/services/search_index.py` 는 원인 판정 과정에서 검토했으나 변경이 필요하지
않아 그대로 두었습니다(`INDEX_MAX_TOTAL_HITS` 를 낮추는 방법은 공유 색인에 설정 쓰기가
필요하고, 앱 계층 상한이 이미 같은 효과를 내며 테스트 가능합니다).

---

## 5. 변경 전후 브라우저 실측

시스템 Chrome(`/Applications/Google Chrome.app`)을 `executablePath` 로 지정한 puppeteer-core 로
케이스당 20회 반복, `PerformanceNavigationTiming` 기준입니다. 앱은 이 작업 브랜치를 로컬
uvicorn(127.0.0.1:8010)으로 띄워 공유 스택의 MySQL·Redis·Meilisearch 를 읽기 전용으로
사용했습니다. 오류 수는 200 이 아닌 응답과 내비게이션 예외의 합입니다.

| 케이스 | TTFB P50 전 → 후 | TTFB P95 전 → 후 | load P50 전 → 후 | 오류 전/후 |
| --- | --- | --- | --- | --- |
| 공고 `page=1` | 16 → 16ms | 19 → 28ms | 372 → 376ms | 0 / 0 |
| 공고 `page=2` | 15 → 14ms | 18 → 16ms | 338 → 364ms | 0 / 0 |
| 공고 `page=1000` | 31 → 28ms | 35 → 31ms | 328 → 376ms | 0 / 0 |
| 공고 `page=100000` | **1156 → 4ms** | **1218 → 5ms** | 1476 → 326ms | 0 / 0 |
| 공고 지역정렬 `page=100000` | **922 → 4ms** | **1002 → 7ms** | 1228 → 334ms | 0 / 0 |
| 낙찰 `page=100000` | **149 → 5ms** | **162 → 8ms** | 451 → 353ms | 0 / 0 |

page 1/2/1000 의 차이는 반복 측정 잡음 범위입니다(P95 의 28ms, 665ms 값은 단발 스파이크).
목표였던 깊은 페이지는 TTFB P95 기준 1218ms → 5ms 입니다.

---

## 6. 기존 검색 계약 확인

### 6.1 테스트

`uv run pytest tests/ -q -m "not data_assets"` → **799 passed, 4 skipped**.

마커 없이 전량 실행하면 `test_data_preservation.py` 의 2건이 실패하는데, 이는
`data/model_files/*/model.bin` 과 `chroma_db/` 가 `.gitignore` 대상이라 이 작업 트리에
존재하지 않기 때문입니다(정본 작업 트리에는 둘 다 존재). 해당 테스트는 파일 상단에
`pytest -m "not data_assets"` 로 제외하도록 명시된 데이터 자산 전용 검사이며 본 변경과
무관한 선행 조건입니다.

계약별 담당 테스트입니다.

| 계약 | 테스트 |
| --- | --- |
| 빈 q 목록 조회 | `test_empty_query_announcement_search_sends_filters_sort_and_page`, `test_empty_query_result_search_preserves_index_order` |
| 필터 조합(업무구분·지역·검색어) | 위 두 건 + `test_meili_search_sends_dataset_filters_and_sort` |
| 503 계약 | `test_announcement_search_backend_failure_returns_503`, `test_result_search_backend_failure_returns_503`, `test_mysql_timeout_keeps_api_503_contract` |
| NULL 정렬(낙찰률) | `test_rate_sort_excludes_null_rates_and_escapes_filter_values` |
| 상한 신규 계약 | `test_page_beyond_limit_skips_the_search_backend`, `test_last_reachable_page_hides_the_next_link`, `test_page_beyond_limit_also_applies_to_mysql_fallback` (각 목록 2건씩) |

`uv run python scripts/validate_agent_rules.py` → **6/6 통과**.

### 6.2 실환경 스모크

변경 후 앱에 실제 Meilisearch 를 물려 확인했습니다.

| 요청 | 결과 |
| --- | --- |
| `/bids/?q=&page=1` (빈 q) | 200, 30ms |
| `/bids/?q=청소&cat=Servc&region=seoul&sort=deadline` | 200, 107ms |
| `/bids/?cat=Cnstwk&region=gyeonggi&sort=amount&page=3` | 200, 69ms |
| `/bids/results/?sort=rate` (NULL 제외 정렬) | 200, 24ms |
| `/bids/results/?q=주식&cat=Servc&sort=rate&page=2` | 200, 117ms |
| `/api/v1/bids?page=1` | 20건, `has_next=true` |
| `/api/v1/bids?page=1000` | 20건, `has_next=false`, `start_index=19981` |
| `/api/v1/bids?page=1001` | 0건, `has_next=false`, `PageMeta` 스키마 동일 |

---

## 7. 별건 판정 — `opengdt` not sortable

Meilisearch 로그의 400 오류는 **운영 경로 영향이 없습니다.**

```
WARN HTTP request{... user_agent=curl/8.7.1 status_code=400
  error=Attribute `opengdt` is not sortable.}
```

근거는 셋입니다.

1. `user_agent` 가 `curl/8.7.1` 입니다. 앱은 httpx 로 호출하므로 발신자는 앱이 아니라
   선행 진단(task_61b9e8986b2c)에서 손으로 친 curl 입니다.
2. 저장소 전체에 `opengdt` 문자열이 없습니다. 앱이 보내는 낙찰 정렬 키는
   `rl_openg_dt` (`src/app/services/bid_queries.py:300`)이며, 색인
   `sortableAttributes` 에 등재되어 있습니다.
3. 앱 컨테이너 로그에 같은 오류가 한 건도 없습니다.

즉 진단 도구의 속성명 오타이며 조치 대상이 아닙니다.

---

## 8. 남은 일과 후속 제안

- **병합은 별도 승인 후 별도 Task 로 수행합니다.** 이 브랜치
  (`kwanbum217/claude-deep-page-pagination`)는 커밋만 되어 있습니다.
- keyset 페이지네이션은 재색인이 선행되어야 성립합니다. 색인 확장(수치형 정렬 키 +
  `filterableAttributes`)과 8.2M 문서 재색인을 감수할 가치가 있는지는 별도 판단이
  필요합니다. 현재 상한으로 지연 문제 자체는 해소되었으므로 시급하지 않습니다.
- 방어를 이중으로 두려면 색인 설정의 `pagination.maxTotalHits` 를 상한에 맞춰 낮추는
  방법이 있습니다. 공유 색인에 설정 쓰기가 필요하므로 이 작업 범위에서는 제외했습니다.

---

## 9. 측정 환경 원상복구

| 항목 | 처리 |
| --- | --- |
| 임시 사용자 계정 | **만들지 않았습니다.** 기존 계정 `probe`(id=2)의 세션 토큰만 Redis 에 발급해 사용했습니다 |
| 세션 토큰 | 측정 종료 후 삭제 |
| 사용자 기준선 | 측정 전후 모두 4명(`kwanbum`, `probe`, `ui-check-user`, `logintest99`) |
| 공유 스택 | 컨테이너 기동·중지·재색인 없음. Meilisearch 와 MySQL 은 조회만 수행 |
| 계측용 앱 | 로컬 uvicorn 127.0.0.1:8010, 측정 종료 후 종료 |

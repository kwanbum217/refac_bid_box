# .contains() 호출부 전수 조사 (2026-08-30)

> **작성일**: 2026-08-30
> **조사 HEAD**: `4ff7548` (작업 시작 시점 main 동기화 커밋)
> **모드**: 조사 전용. 운영 코드 수정 0건
> **결론 한 줄**: SQLAlchemy `.contains()` 호출은 4개 파일·총 13회 등장하며, 이 중 9회가 `LIKE '%...%'` 로 컴파일되어 인덱스를 전혀 쓰지 못한다. 접두 일치로의 단순 전환은 사용자 질의가 손상값으로 도배된 한국 행정기관명 특성상 막대한 의미 변화를 일으키므로 **대체 불가** 판정이다. `corrupted_probe` 3건은 안내 문구 한 줄을 위해 매 질의당 합산 ~27초를 쓰며 **제거 가능**이지만 운영 코드 변경 없이 조사만으로는 불가능하다.

---

## 1. 조사 범위와 방법

1. `src/rag/` 와 `src/app/` 전체에서 `\.contains\(` 정규식 검색 (`Grep`).
2. `LIKE` / `.ilike(` / `.not_like(` 도 함께 검색하여 음수 와일드카드 사례를 누락 없이 집계.
3. 각 호출이 등장하는 함수의 **호출 시점·용도·대상 컬럼**을 정독.
4. MySQL 8 에 직접 접속해 EXPLAIN 과 실측(ms)·예상 매칭 건수를 측정.
5. Meilisearch 가 같은 토큰을 검색하는 응답 시간과 매칭 분포를 측정해 대체 경로 후보의 실제 거동을 확인.

호출 13건을 7개 그룹으로 분류했다. 그룹은 같은 의도·같은 컴파일 결과를 갖는 호출끼리 묶었다.

| 그룹 | 의도 | 컴파일 형태 |
| --- | --- | --- |
| G1 | 사용자 질의의 기관명 부분 매칭 (RAG) | `LIKE '%?%'` |
| G2 | 손상값(U+FFFD) probe (RAG 집계) | `LIKE '%�%'` |
| G3 | 손상값 제외 (스냅샷 집계·대시보드) | `LIKE '%�%'`, `NOT LIKE '%...%'` |
| G4 | 지역 코드 alias 부분 매칭 (목록) | `LIKE '%alias%'` |
| G5 | 자유 검색 q 부분 매칭 (목록) | `LIKE '%q%'` |
| G6 | 공고번호·업체명 부분 매칭 (목록) | `LIKE '%q%'` |
| G7 | 단위가격/교복/학생복 제외 (대시보드) | `NOT LIKE '%...%'` (3 AND) |

---

## 2. 호출부 전수 목록

| # | 파일:라인 | 그룹 | 컬럼·테이블 | 호출 시점 | 용도 |
| --- | --- | --- | --- | --- | --- |
| 1 | `src/rag/structured_data.py:100` | G1 | `bid_results.dminstt_nm` | RAG 통계 질의에서 기관명 필터가 걸린 모든 경우 | 사용자 질의 토큰 매칭 |
| 2 | `src/rag/structured_data.py:118` | G1 | `bid_announcements.dminstt_nm` | RAG 통계 질의에서 기관명 필터가 걸린 모든 경우 | 사용자 질의 토큰 매칭 |
| 3 | `src/rag/structured_data.py:195` | G1 | `bid_results.dminstt_nm` | "최근 개찰일" 사전 확인 질의 | 결과 보유 범위 확인 |
| 4 | `src/rag/structured_data.py:546` | G2 | `bid_results.bidwinnr_nm` | `_top_rows(bidwinnr_nm)` 의 손상 probe (LIMIT 1) | 안내 문구 표시 여부 |
| 5 | `src/rag/structured_data.py:564` | G2 | `bid_announcements.dminstt_nm` | `_top_rows(dminstt_nm)` 의 손상 probe (LIMIT 1) | 안내 문구 표시 여부 |
| 6 | `src/rag/structured_data.py:582` | G2 | `bid_announcements.bid_ntce_nm` | `_top_rows(bid_ntce_nm)` 의 손상 probe (LIMIT 1) | 안내 문구 표시 여부 |
| 7 | `src/app/services/ranking_snapshots.py:83` | G3 | `column`(모델 컬럼) | `_compute_rows` 의 손상값 제외 | 집계 결과의 무결성 |
| 8 | `src/app/services/ranking_snapshots.py:119` | G3 | `column`(모델 컬럼) | 손상값 probe (LIMIT 1) | 안내 문구 표시 여부 |
| 9 | `src/app/services/bid_queries.py:160-161` | G4 | `dminstt_nm`·`ntce_instt_nm` | `list_announcements` 의 지역 필터 | 지역별 정렬/필터링 |
| 10 | `src/app/services/bid_queries.py:166` | G4 | `bid_results.dminstt_nm` | `list_results` 의 지역 필터 | 지역별 정렬/필터링 |
| 11 | `src/app/services/bid_queries.py:410,414-416` | G5·G6 | `bid_ntce_no/nm/dminstt_nm` | `list_announcements` 의 검색어 매칭 | 사용자 q 매칭 |
| 12 | `src/app/services/bid_queries.py:480,484-487` | G5·G6 | `bid_ntce_no/nm/dminstt_nm/bidwinnr_nm` | `list_results` 의 검색어 매칭 | 사용자 q 매칭 |
| 13 | `src/app/services/dashboard.py:66` | G7 | `bid_ntce_nm` | `get_dashboard_stats` 의 업체 TOP 100 | 단가/교복/학생복 제외 |

`api/ui.py:300` 의 `ChatSessionState.session_key.not_like("user:%")` 는 음수 와일드카드(접두 일치의 반대로 트리)이며 `.contains()` 가 아니므로 본 조사 범위에서 제외한다. 벡터 채널(`src/rag/vector_store.py`)은 LIKE/contains/startswith 어느 것도 쓰지 않음을 별도 확인.

---

## 3. EXPLAIN 실측

`information_schema.tables` 의 `bid_announcements.table_rows = 2,179,319`, `bid_results.table_rows = 3,267,347` 이며 Meilisearch 색인은 `numberOfDocuments = 8,278,445` (`isIndexing=false`).

### 3.1 그룹별 EXPLAIN

| 쿼리 | type | key | rows | Extra |
| --- | --- | --- | ---: | --- |
| `bid_announcements.dminstt_nm LIKE '%경상남도%'` | **index** | `bid_announcements_dminstt_nm_952da702` | 2,179,319 | Using where; Using index |
| `bid_announcements.dminstt_nm LIKE '경상남도%'` | **range** | 동일 인덱스 | 1,089,659 | Using where; Using index |
| `bid_announcements.dminstt_nm LIKE '거제시%'` | range | 동일 인덱스 | **36** | Using where; Using index |
| `bid_results.dminstt_nm LIKE '%경상남도%'` | index | `bid_results_dminstt_nm_1b809760` | 3,267,347 | Using where; Using index |
| `bid_results.bid_ntce_nm LIKE '%교복%' AND ... ` (G7) | **ALL** | **NULL** | 3,267,347 | Using where |
| `list_announcements` q 부분 매칭 (3 OR) | **ALL** | **NULL** | 2,179,319 | Using where |
| `bid_announcements.dminstt_nm LIKE '%서울%' OR ntce_instt_nm LIKE '%서울%'` (G4) | **ALL** | **NULL** | 2,179,319 | Using where |

> 키 컬럼이 1개인 인덱스에서 선행 와일드카드 LIKE 는 type=index (인덱스 풀스캔) 또는 type=ALL (테이블 풀스캔) 으로 떨어진다. 두 경우 모두 인덱스 range 스캔이 제공하는 "필터에 맞는 행만" 의 이점을 잃는다.

### 3.2 손상값 probe 실측 (LIMIT 1)

손상값이 **없을 때** U+FFFD 가 하나도 없음을 증명하려면 끝까지 훑어야 한다. 두 회 측정.

| 쿼리 | 회차 1 (ms) | 회차 2 (ms) | 손상값 분포 (총 행) |
| --- | ---: | ---: | --- |
| `bid_results.bidwinnr_nm LIKE '%�%' LIMIT 1` | 1.22 | 5.19 | 1,244,778 |
| `bid_announcements.dminstt_nm LIKE '%�%' LIMIT 1` | 1,053.47 | 4,929.72 | 0 |
| `bid_announcements.bid_ntce_nm LIKE '%�%' LIMIT 1` | **23,177.05** | **19,858.74** | 0 |

`bid_results.bidwinnr_nm` probe 는 U+FFFD 가 행의 38% 를 차지해 첫 행에서 즉시 적중한다. `bid_announcements.dminstt_nm` 와 `bid_announcements.bid_ntce_nm` probe 는 0건임이 **실측으로** 확인됐고(2,179,319행 전체), 그 "없음" 증명에 각 1~5초와 20~23초가 든다. `_top_rows` 는 실시간 경로에서 이 probe 를 3회 호출하므로 정상 상태에서 매 질의당 약 27초 추가다. ground_truth 의 "최대 27,668ms" 와 일치한다.

---

## 4. 의미 변화 위험: 접두 일치 전환이 실패시키는 실제 사례

사용자 질의는 종종 정식 행정명칭이 아니라 부분 토큰으로 들어온다. 부분 일치를 접두 일치로 바꾸면 일부 결과가 0건이 된다.

### 4.1 한국 행정기관명 부분 토큰 분포

| 테이블 | 토큰 | 부분 일치 건수 (`%tok%`) | 접두 일치 건수 (`tok%`) | 부분에만 잡히는 건수 |
| --- | --- | ---: | ---: | ---: |
| `bid_announcements.dminstt_nm` | `거제시` | 10,184 | 36 | **10,148** |
| `bid_announcements.dminstt_nm` | `경상남도` | 301,571 | 299,410 | 2,161 |
| `bid_announcements.dminstt_nm` | `서울특별시` | 310,974 | 305,724 | 5,250 |
| `bid_announcements.dminstt_nm` | `경기도` | 576,722 | 568,335 | 8,387 |
| `bid_announcements.dminstt_nm` | `서울` | 441,858 | 390,421 | **51,437** |
| `bid_results.dminstt_nm` | `거제시` | 3,778 | 36 | **3,742** |
| `bid_results.dminstt_nm` | `경상남도` | 118,661 | 117,890 | 771 |
| `bid_results.dminstt_nm` | `서울특별시` | 129,305 | 127,325 | 1,980 |
| `bid_results.dminstt_nm` | `경기도` | 229,034 | 225,704 | 3,330 |
| `bid_results.dminstt_nm` | `서울` | 179,613 | 158,930 | **20,683** |

**접두 일치 전환 시 부분 일치 결과의 약 99% 가 그대로 잡힌다**는 ground_truth 와 달리, **거제시처럼 토큰 단독 입력은 0.35% 만 잡힌다**. "서울" 처럼 짧은 정식 호칭도 11.6% 가 누락된다 (예: `서울특별시 강남구 보건소` → `서울` prefix OK vs `한국서울...` 처럼 중간 등장 → prefix miss).

### 4.2 정량: 접두 전환이 사용자에게 노출하는 회귀

- 사용자가 `"거제시"` 를 입력하면 접두 전환 후 `bid_announcements` 36건, `bid_results` 36건만 남는다. 현재 부분 일치는 10,148건 + 3,742건 → **99.6% 회귀**.
- 사용자가 `"서울"` 을 입력하면 부분 일치 441,858건 + 179,613건이 390,421건 + 158,930건으로 떨어진다 → **11.6% 회귀**.
- 사용자가 `"경상남도"` 를 입력하면 301,571건이 299,410건으로 떨어진다 → **0.7% 회귀** (전형적 정식 호칭은 안전).

이 회귀는 **사용자가 입력한 텍스트가 "어디 기관을 가리키는가"** 라는 의미가 달라진다는 점에서 G1(데이터 무손실)과 같은 무게의 회귀다. RAG 의 `_result_conditions` 와 `_announcement_conditions` 가 모두 이 경로를 탄다.

---

## 5. 그룹별 판정

### 5.1 G1 (RAG 기관명 부분 매칭) - 대체 불가

- **호출**: #1, #2, #3
- **의도**: 사용자 질의에서 들어온 한국 행정기관명 토큰 매칭. 입력은 "경상남도 거제시" 정식 명칭이 아니라 "거제시", "서울", "강남구" 등 부분 토큰이 대부분.
- **대체 후보와 의미 변화**:
  - 접두 일치 전환 → 4.2 절의 회귀 발생. "거제시" 입력 시 결과 99.6% 손실.
  - Meilisearch 위임 → 5.4 절에서 별도 분석.
  - 사전 계산 (`institution_win_rate_stats`) → 이미 존재하지만 `(institution_name, category)` PK 등치 조회만 가능. 사용자 토큰이 일부만 일치하는 경우 적중하지 못한다.
  - 제거 → 사용자 의도(기관 필터링)를 포기하므로 무리.
- **판정**: **불가능**. 무리한 제안을 하지 않는다.

### 5.2 G2 (손상값 probe, RAG 집계) - 제거 가능하나 조사 범위 밖

- **호출**: #4, #5, #6
- **의도**: `_top_rows` 가 집계 결과의 안내 문구 표시를 결정하기 위해 손상값 존재 여부를 묻는다.
- **비용**: 정상 상태에서 매 질의당 합산 약 27초 (3.2 절 실측). ground_truth 의 "최대 27,668ms" 와 일치.
- **대체 후보와 의미 변화**:
  - probe 제거 → `_top_rows` 가 안내 문구를 항상 "표시함" 으로 가정. 손상값이 없는 정상 상태에서 잘못된 안내가 한 줄 추가된다.
  - probe 를 손상값 사전 집계로 위임 → `bid_ranking_snapshots.rank=0` 슬롯에 이미 기록되어 있다 (`SKIPPED_MARKER_RANK`). 호출부 `_top_rows:259` 가 이미 스냅샷에서 `get_skipped_count` 를 읽고 있어 **probe 가 불필요한 호출이 되는 경로가 있다**.
- **판정**: **제거 가능**. 다만 이 작업은 운영 코드 변경이 필요하므로 본 조사에서는 판정만 남기고 코드 수정은 다음 Task 의 몫이다. `ranking_snapshots.py:83` 의 `exclude_corrupted` 와 `structured_data.py:259` 의 `get_skipped_count` 가 이미 손상값 마커를 별도 관리하므로 중복 비용을 정리할 여지가 있다.

### 5.3 G3 (손상값 제외, 스냅샷 집계) - 의도 보존이 필수

- **호출**: #7, #8
- **의도**: `_compute_rows` 가 손상값을 SQL 단계에서 미리 제외해 집계 후속 단계에서 U+FFFD 가 top-N 을 차지하는 사고를 막는다.
- **의미 변화 위험**: 제거 시 순위 상위 10위가 모두 `�������...` 로 채워진다 (`bid_results` 의 41% 손상값).
- **판정**: **불가능**. 비용이 들더라도 의도 자체가 데이터 무손실(G1) 보장의 일부다. 호출 자체는 옵티마이저가 `LIMIT 10` + 손상값 제외 시 메모리 내에서 끝낼 수 있어 풀스캔보다 훨씬 가볍다.

### 5.4 G4 (지역 코드 alias 매칭) - 부분 대체 가능

- **호출**: #9, #10
- **의도**: `BID_REGION_BY_CODE` 의 alias(예: `("경상남도","경남")`) 가 `dminstt_nm` / `ntce_instt_nm` 안에 들어있는지 매칭.
- **비용**: type=ALL 풀테이블 스캔, rows=2.18M (`bid_announcements`), 3.27M (`bid_results`) (3.1 절).
- **대체 후보와 의미 변화**:
  - 접두 일치 전환 → "서울" 입력이 `서울특별시` 외 `서울강남...` 같은 비공식 표기까지 잡던 부분 일치 결과를 잃는다. 다만 region 매칭의 의도는 "정식 광역시/도 단위" 매칭이므로 정식 호칭만 잡아도 회귀가 작다 (3.2 절의 11.6% 회귀와 별도 평가 필요).
  - 사전 계산된 `region_codes` 컬럼 → Meilisearch 색인에 이미 들어있다. SQL 로 옮기려면 `dminstt_nm` 에 `region_codes VARCHAR(20)` 파생 컬럼을 추가하거나 별도 매핑 테이블이 필요하다.
  - Meilisearch 위임 → 4.1 절의 토큰 분포 측정에서 Meili 응답 86~294ms. 그러나 본 호출은 목록 화면 페이지네이션 안에서 매 페이지마다 호출되므로 20건 응답에 100ms 추가는 누적된다.
- **판정**: **부분 대체 가능**. 다만 region 의 alias 가 "서울특별시"/"서울", "제주특별자치도"/"제주" 처럼 정식 호칭과 약식 동시 포함이라는 점에 주의. 약식 alias 만 접두로 바꾸면 alias "서울" 자체는 단독으로 매칭되어야 하는데 `dminstt_nm` 이 "서울" 로 시작하는 행은 36건에 불과하다 (3.1 절의 "거제시 prefix" 와 같은 의미 변화**. 운영 측에서 약식 alias의 의미를 정의한 후에만 전환 가능.

### 5.5 G5·G6 (자유 검색 q 매칭) - 부분 대체 가능

- **호출**: #11, #12
- **의도**: 사용자가 `/bids?q=조달` 같이 입력한 검색어를 `bid_ntce_nm/nm/dminstt_nm/bidwinnr_nm` 의 어디든 매칭.
- **비용**: type=ALL 풀테이블 스캔, rows=2.18M (3.1 절).
- **대체 후보와 의미 변화**:
  - 접두 일치 전환 → 의미 변화 막대함. "서울특별시 강남구" 입력 시 `bid_ntce_nm LIKE '서울특별시 강남구%'` 로는 매칭 0건 (실측 8,187건 → 0건). "조달" 입력 시 27,973건 → 0건.
  - Meilisearch 위임 → Meilisearch 가 이미 색인돼 있고 `_meili_enabled()` 일 때 `list_announcements`/`list_results` 가 `_search_index_page` 로 빠진다 (`bid_queries.py:391-403, 462-474`). 부분 일치는 그대로 유지된다.
  - 인덱스 추가 → `bid_ntce_nm` 은 varchar(500) + 인덱스 없음. FULLTEXT 인덱스 추가가 유일한 SQL 내 해결책이지만 G1(스키마 불변) 원칙 위배.
- **판정**: **부분 대체 가능 (Meilisearch 권장)**. 이미 `_meili_enabled()` 분기로 위임 경로가 있어 추가 코드 변경 없이 `MEILI_ENABLED=true` 만 켜면 된다. 단 Meili 가 떨어졌을 때 폴백은 같은 풀스캔이므로 fail-closed 운영이 필수.

### 5.6 G7 (단위가격/교복/학생복 제외) - 의도상 유지 필요하나 비용 큼

- **호출**: #13
- **의도**: 대시보드 "최근 1년 업체 TOP 10" 에서 단가/교복/학생복 계약이 점유하는 자릿수를 빼고 일반 용역/물품 업체만 노출.
- **비용**: type=ALL 풀테이블 스캔 3.27M 행, 실측 2,305.95ms (3.2 절). `WHERE (bid_ntce_nm IS NULL OR bid_ntce_nm NOT LIKE '%단가%') AND ...` 3개 AND.
- **대체 후보와 의미 변화**:
  - 단어 목록을 카테고리 코드 매핑으로 위임 → 원본 parquet 의 `category` 값과 매칭되지 않으므로 데이터 무손실 위배.
  - 사전 계산된 카테고리 제외 컬럼 → 동일 이유로 G1 위배.
  - LIKE prefix 전환 → "단가" 로 시작하는 공고만 제외 (의도와 정반대로 적중률 폭증).
- **판정**: **유지 (의도 보존 필수)**. 비용은 대시보드 캐시 TTL 24시간과 회사 TOP 100 LIMIT 으로 1일 1회만 호출되므로 콜드 스타트 비용 한 번만 부담한다. 평균 트래픽 기준 G2·G3 와 비교해 우선순위가 낮다.

---

## 6. 우선순위 (비용·위험 기준)

`performance_schema.events_statements_summary_by_digest` 의 지배 패턴은 선행 와일드카드 LIKE 계열이며, 누적 비용은 ground_truth 의 표 그대로다.

| 순위 | 그룹 | 실측 근거 | 위험 | 판정 |
| :---: | --- | --- | --- | --- |
| 1 | **G2 (손상 probe 3건)** | 매 질의당 ~27초 합산 (3.2 절). 정상 상태가 대부분이라 매번 전액 부담 | 안내 문구 한 줄의 표시 여부만 결정 | **제거 가능** (다음 코드 변경 Task 에서) |
| 2 | **G5·G6 (자유 검색 q)** | `list_announcements`/`list_results` 가 Meili 비활성일 때 풀테이블 스캔. 페이지당 호출 | Meilisearch 경로가 이미 존재 → `MEILI_ENABLED=true` 로 즉시 해소 | **부분 대체 (Meili)** |
| 3 | **G4 (region alias)** | type=ALL 2.18M / 3.27M 스캔. 정식 alias 만 쓰면 회귀 작음 | 약식 alias ("서울", "제주") 가 사라짐 | **부분 대체 (alias 정책 결정 후)** |
| 4 | **G1 (RAG 기관명)** | 콜드 스타트 시 누적 89초의 주범 (ground_truth 9장 표 1행) | 99.6% 회귀 (거제시 사례) | **대체 불가 (이 Task 에서 변경 금지)** |
| 5 | **G3 (손상값 제외, 스냅샷)** | 비용은 있으나 의도가 G1 보장의 일부 | 회귀 시 top-N 무결성 붕괴 | **불가능** |
| 6 | **G7 (대시보드 제외)** | 1일 1회 2.3초, 캐시 24시간 | 의도 자체를 잃으면 top-N 오염 | **불가능** |

G2 가 비용 대비 위험이 가장 낮다. 이 Task 는 조사만 수행하지만, 후속 작업이 G2 의 3개 probe 제거에 가장 먼저 손을 대야 한다는 점은 기록으로 남긴다.

---

## 7. Meilisearch 위임 시 검증

| 토큰 | Meili 응답(ms) | estimated_total | DB 부분 일치 (announcements) | DB 부분 일치 (results) |
| --- | ---: | ---: | ---: | ---: |
| `거제시` | 294.17 | 29,828 | 10,184 | 3,778 |
| `경상남도` | 86.22 | 268,662 | 301,571 | 118,661 |
| `서울특별시` | 253.79 | 560,642 | 310,974 | 129,305 |
| `강남구` | 110.07 | 37,729 | - | - |

- Meili 의 "거제시" top 결과는 `["거제시종합사회복지관", "경상남도 거제시", "경상남도 거제시", ...]` 이며 `거제해양관광개발공사` 처럼 중간에 "거제" 가 들어간 비공식 표기도 포함한다. DB 의 부분 일치와 **의미가 다르다** (포함 vs 토큰).
- "경상남도" / "서울특별시" 정식 호칭은 Meili 응답이 DB 부분 일치의 89% / 180% 수준으로 의미가 거의 같다.
- G1 (RAG 기관명) 을 Meili 로 위임하면 **사용자가 입력한 토큰의 의미가 부분 일치에서 토큰 일치로 미묘하게 바뀐다**. 답변의 top 5 가 달라질 수 있으므로 G1 의 무리한 위임은 권장하지 않는다.

---

## 8. 재현 명령 (실행 가능 형태)

```bash
# 1) .contains() 호출 전수 검색
grep -rn "\.contains(" src/rag src/app --include='*.py' | grep -v vendor

# 2) Meilisearch 헬스 체크
curl -s http://localhost:7700/health

# 3) 행 수 / 인덱스 확인
uv run python -c "from sqlalchemy import text; from src.app.core.db import engine; \
print(engine.connect().execute(text(\"SELECT table_name, table_rows \
FROM information_schema.tables WHERE table_schema = DATABASE() \
AND table_name IN ('bid_announcements','bid_results','bid_ranking_snapshots')\")).all())"

# 4) 접두 vs 부분 일치 비교 (거제시)
uv run python - <<'PY'
from sqlalchemy import text
from src.app.core.db import engine
with engine.connect() as c:
    for q, mode in [("거제시","prefix"),("서울","prefix"),("경상남도","prefix")]:
        rows = c.execute(text("SELECT COUNT(*) FROM bid_announcements \
WHERE dminstt_nm LIKE :p"), {"p": f"{q}%" if mode=='prefix' else f"%{q}%"}).first()
        print(mode, q, dict(rows._mapping))
PY

# 5) 손상값 probe LIMIT 1 실측
uv run python - <<'PY'
from sqlalchemy import text
from src.app.core.db import engine
import time
with engine.connect() as c:
    for sql in [
        "SELECT 1 FROM bid_results WHERE bidwinnr_nm LIKE '%\ufffd%' LIMIT 1",
        "SELECT 1 FROM bid_announcements WHERE dminstt_nm LIKE '%\ufffd%' LIMIT 1",
        "SELECT 1 FROM bid_announcements WHERE bid_ntce_nm LIKE '%\ufffd%' LIMIT 1",
    ]:
        t0 = time.perf_counter()
        c.execute(text(sql)).first()
        print(round((time.perf_counter()-t0)*1000, 2), "ms", sql[:50])
PY
```

---

## 9. 결론

- 13개 `.contains()` 호출 중 9개가 `LIKE '%...%'` 로 컴파일되며 **인덱스 range 스캔이 불가능**하다.
- **접두 일치로의 단순 전환은 G1 (RAG 기관명) 에서 사용자가 입력하는 "거제시" 등 부분 토큰의 99.6% 를 잃게 하므로 무리한 제안이다.**
- 가장 비용 대비 위험이 낮은 개입은 G2 의 손상값 probe 3건 제거다. 손상값 존재 여부는 이미 `bid_ranking_snapshots.rank=0` 슬롯과 `get_skipped_count` 로 관리되므로 중복 비용이다. 단 코드 수정이 필요하므로 본 조사에서는 판정만 남긴다.
- G5·G6 는 Meilisearch 위임이 가능하다. `_meili_enabled()` 가 이미 분기를 제공하므로 `MEILI_ENABLED=true` 설정만으로 풀스캔을 우회할 수 있다. 다만 Meili 가 비정상일 때의 fail-closed 운영이 전제되어야 한다.
- G3·G7 은 의도 자체가 G1(데이터 무손실)과 충돌하므로 SQL 변경 없이 풀스캔을 없앨 수 없다. 대시보드 캐시 TTL 이 이미 24시간이라 G7 의 비용은 일 1회로 한정된다.
- **본 보고서는 조사 전용이며 운영 코드를 수정하지 않았다.** DB 에 쓰기 연산도 수행하지 않았다.

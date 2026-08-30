# Series B(사용자 기관명 검색) Meilisearch 위임 판정 결과

> **작성일**: 2026-08-30
> **조사 HEAD**: `420b836` (kwanbum217/orca-f2-search-delegation)
> **모드**: 조사 전용. 운영 코드 수정 0건
> **결론**: **불가**. Meilisearch의 토큰 매칭 의미와 SQL `LIKE '%...%'` 부분 일치 의미가 달라 결과 카운트가 질의에 따라 0.86x~9.83x 수준으로 변동한다. RAG 통계 경로가 요구하는 정확 COUNT, AVG, SUM, GROUP BY 집계를 Meilisearch가 제공할 수 없다.

---

## 1. Meilisearch 색인 보유 필드와 문서 수

`GET /indexes/bid_records/stats` 실측 결과 (2026-08-30):

| 항목 | 값 |
| --- | --- |
| numberOfDocuments | **8,278,445** |
| isIndexing | false |
| rawDocumentDbSize | 4,532,047,872 bytes (~4.2GB) |
| avgDocumentSize | 539 bytes |

### 1.1 필드 분포 (fieldDistribution)

| 필드 | 문서 수 | 포함 비율 | 비고 |
| --- | ---: | ---: | --- |
| `bid_ntce_nm` | 8,278,445 | 100% | 공고명 |
| `dminstt_nm` | 8,278,445 | 100% | 수요기관명 |
| `bid_ntce_no` | 8,278,445 | 100% | 공고번호 |
| `category` | 8,278,445 | 100% | 업무분류 |
| `dataset` | 8,278,445 | 100% | "announcement" 또는 "result" |
| `ntce_instt_nm` | 4,855,437 | 58.6% | 공고기관명 (공고만) |
| `bid_ntce_dt` | 4,855,437 | 58.6% | 공고일시 (공고만) |
| `bidwinnr_nm` | 3,423,008 | 41.3% | 낙찰업체명 (낙찰만) |
| `rl_openg_dt` | 3,423,008 | 41.3% | 개찰일시 (낙찰만) |
| `sucsf_bid_amt` | 3,423,008 | 41.3% | 낙찰금액 (낙찰만) |
| `sucsf_bid_rate` | 3,423,008 | 41.3% | 낙찰률 (낙찰만) |

### 1.2 검색/필터/정렬 가능 속성 (settings)

| 구분 | 속성 |
| --- | --- |
| searchableAttributes | `bid_ntce_nm`, `bid_ntce_no`, `dminstt_nm`, `ntce_instt_nm`, `bidwinnr_nm` |
| filterableAttributes | `dataset`, `category`, `region_codes`, `sucsf_bid_rate` |
| sortableAttributes | `bid_ntce_dt`, `bid_clse_dt`, `base_amount`, `rl_openg_dt`, `sucsf_bid_amt`, `sucsf_bid_rate`, `region_rank`, `source_id` |

### 1.3 계열 B 질의가 요구하는 필드 보유 판정

| 요구 필드 | 용도 | 보유 여부 |
| --- | --- | --- |
| `dminstt_nm` | 기관명 부분 매칭 | **보유** (100%) |
| `bid_ntce_nm` | 공고명 부분 매칭 | **보유** (100%) |
| `category` | 카테고리 필터 | **보유** (100%, filterable) |
| `dataset` | 공고/낙찰 구분 | **보유** (100%, filterable) |

**필드 자체는 모두 보유한다.** 그러나 필드 보유와 결과 동일성은 별 문제다 (3장).

---

## 2. 계열 B 다섯 쿼리별 위임 가능 여부

계열 B는 `performance_schema` digest 기준 콜드 SQL 누적 105.5초의 상위 5개다. 모두 `src/rag/structured_data.py`의 `_announcement_conditions` / `_result_conditions` 가 발생시킨다.

### 2.1 각 쿼리의 의도와 Meilisearch 대체 가능성

| # | digest 패턴 | cold 누적 (s) | SQL 의도 | Meili 대체 | 이유 |
| :---: | --- | ---: | --- | :---: | --- |
| #3 | `bid_ntce_nm LIKE` + `dminstt_nm LIKE` + category | 28.964 | 공고 존재 확인 (SELECT 1) | **불가** | Meili 토큰 매칭이 SQL 부분 일치와 의미 불일치 (3장). 존재 확인조차 결과 집합이 달라 false positive/negative 발생 |
| #4 | `dminstt_nm LIKE` x2 + category | 28.315 | announcement_count (COUNT) | **불가** | COUNT 값이 MySQL과 다르다.实测 강남구 +882%, 거제시 +138% |
| #5 | COUNT + `dminstt_nm LIKE` + category | 27.076 | result_count + avg_rate + total_amt | **불가** | Meili는 AVG/SUM 집계를 지원하지 않는다. `estimatedTotalHits`도 정확 보장이 안 됨 |
| #8 | `bid_ntce_nm LIKE` (no category) | 16.680 | announcement 존재 확인 | **불가** | #3과 같은 이유. 카테고리 없을 때 차이 더 큼 |
| #9 | COUNT + `bid_ntce_nm LIKE` (no category) | 4.432 | announcement_count | **불가** | #4와 같은 이유 |

### 2.2 집계(COUNT, GROUP BY)를 Meili가 대신할 수 있는지

| 집계 유형 | Meili 지원 | 비고 |
| --- | :---: | --- |
| COUNT (existence) | 부분 | `estimatedTotalHits`는 근사치. 토큰 매칭 의미 차이로 정확한 COUNT 불가 |
| COUNT (exact) | **불가** | `estimatedTotalHits`는 정확 보장이 안 됨. 실측 -14% ~ +883% 편차 |
| AVG(sucsf_bid_rate) | **불가** | Meili는 집계 함수를 제공하지 않음 |
| SUM(sucsf_bid_amt) | **불가** |同上 |
| GROUP BY + ORDER BY count | **불가** | Meili에 GROUP BY 개념이 없음. top_winners/top_institutions/top_announcements 계산 불가 |

**결론: Meilisearch는 검색 엔진이지 집계 엔진이 아니다.** 계열 B의 5개 쿼리 중 COUNT 1개(#5의 announcement_count)만 이론적으로 근사 가능하고, 나머지는 SQL 기능 자체가 부족하다.

---

## 3. 표본 질의 MySQL 대 Meili 결과 대조

### 3.1 실험 조건

- **MySQL**: `SELECT COUNT(*) FROM bid_announcements WHERE dminstt_nm LIKE '%token%' [AND category = ?]`
- **Meilisearch**: `POST /indexes/bid_records/search` with `q=token`, `attributesToSearchOn=["dminstt_nm"]`, `matchingStrategy="all"`, `filter=dataset="announcement" [AND category="?"]`
- **캐시 상태**: MySQL cold (버퍼 풀 warm), Meilisearch cold (응답 캐시 없음)
- **Meili 검색 전략**: `matchingStrategy=all` (모든 토큰 필수 매칭), `attributesToSearchOn=["dminstt_nm"]` (dminstt_nm 필드만 검색)

### 3.2 공고(announcement) COUNT 대조표

| 질의 | MySQL COUNT | Meili estimatedTotalHits | 편차 | MySQL (ms) | Meili (ms) | 속도개선 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 거제시 + Servc | 3,404 | 8,088 | **+137.6%** | 14,178 | 211 | 67x |
| 경상남도 + Cnstwk | 137,794 | 125,586 | -8.9% | 15,361 | 33 | 463x |
| 서울 (no cat) | 441,858 | 378,311 | -14.4% | 11,684 | 120 | 97x |
| 강남구 + Thng | 1,703 | 16,735 | **+882.7%** | 1,720 | 31 | 55x |
| 한국토지주택공사 (no cat) | 12,818 | 11,936 | -6.9% | 2,804 | 254 | 11x |

### 3.3 낙찰(result) COUNT 대조표

| 질의 | MySQL COUNT | Meili estimatedTotalHits | 편차 | MySQL (ms) | Meili (ms) | 속도개선 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 거제시 + Servc | 1,915 | 5,555 | **+190.1%** | 1,797 | 8 | 214x |
| 경상남도 + Cnstwk | 17,223 | 17,223 | +0.0% | 2,365 | 7 | 338x |
| 서울 (no cat) | 179,613 | 180,122 | +0.3% | 4,140 | 9 | 471x |
| 강남구 + Thng | 1,075 | 14,692 | **+1266.7%** | 760 | 7 | 112x |
| 한국토지주택공사 (no cat) | 10,326 | 10,326 | +0.0% | 1,811 | 13 | 137x |

### 3.4 불일치 원인 분석

Meilisearch는 한국어 텍스트를 토큰화하여 색인한다. SQL `LIKE '%강남구%'` 는 "강남구"라는 **연속 부분 문자열**을 매칭하지만, Meilisearch는 "강남" + "구" 등으로 토큰 분해 후 각 토큰의 존재 여부를 판단한다.

**실측 사례:**

- **"강남구" + Thng**: MySQL 1,703건 vs Meili 16,735건 (+882.7%)
  - Meili가 "강남" 토큰과 "구" 토큰을 개별 매칭. "구"는 한국어 기관명에 극히 흔한 글자라서 ("교육청", "구청", "복지관" 등) 거의 모든 문서가 "구" 토큰을 포함. 결과적으로 "강남" 토큰이 포함된 문서를 광범위하게 매칭.
- **"거제시" + Servc**: MySQL 3,404건 vs Meili 8,088건 (+137.6%)
  - "거제시종합사회복지관"처럼 "거제시"가 부분 포함된 기관명을 Meili가 과도하게 매칭.
- **"경상남도"**, **"한국토지주택공사"**: 비교적 정확 (-8.9%, -6.9%)
  - 토큰이 충분히 길고 고유해서 토큰 매칭과 부분 일치가 유사한 결과 집합을 만듦.

**핵심**: 불일치는 토큰의 길이와 고유성에 따라 체계적으로 발생한다. 짧은 토큰이나 흔한 글자를 포함하는 토큰일수록 편차가 크다. 이 편차는 운영 환경에서 예측 불가능하며, RAG 답변의 통계 수치가 사용자에게 직접 노출된다는 점에서 허용할 수 없다.

---

## 4. 레이턴시 실측

### 4.1 측정 조건

- MySQL: Docker 컨테이너 내부, 버퍼 풀 warm 상태 (cold SQL 측정의 "cold"는 Redis 캐시 cold를 의미)
- Meilisearch: Docker 컨테이너 내부 (`refac_bid_box-meilisearch-1`), 응답 캐시 없음
- 계측: `time.perf_counter()` 기반 wall-clock, 각 1회 측정

### 4.2 비교 요약

| 질의 | MySQL cold (ms) | Meili cold (ms) | 속도개선 |
| --- | ---: | ---: | ---: |
| 거제시 + Servc (ann) | 14,178 | 211 | **67x** |
| 경상남도 + Cnstwk (ann) | 15,361 | 33 | **463x** |
| 서울 (no cat, ann) | 11,684 | 120 | **97x** |
| 강남구 + Thng (ann) | 1,720 | 31 | **55x** |
| 한국토지주택공사 (no cat, ann) | 2,804 | 254 | **11x** |

Meilisearch의 레이턴시는 모든 질의에서 33~254ms로, MySQL cold (1,720~15,361ms) 대비 11~463배 빠르다. **레이턴시 관점에서는 위임이 매력적**이지만, 3장의 결과 불일치가 치명적이다.

---

## 5. Fail-closed 동작 현황

### 5.1 현재 코드 상태

`src/rag/structured_data.py`의 `retrieve_structured_data`는 Meilisearch를 **전혀 호출하지 않는다**. 모든 쿼리가 MySQL 직접 경로다. 따라서 Series B 쿼리에 대한 fail-closed 메커니즘이 존재할 필요가 없다.

### 5.2 기존 Meilisearch 경로의 fail-closed

`src/rag/engine.py`의 `retrieve_lexical_context` (607~704행):
- `MEILI_ENABLED=False` → 빈 리스트 반환 (벡터 경로로 폴백)
- 서버 미기동/타임아웃/예외 → `logger.warning` 후 빈 리스트 반환 (벡터 경로로 폴백)
- **fail-closed 구현됨**: Meili 장애가 전체 질의 실패로 전파되지 않음

`src/app/services/bid_queries.py`의 `list_announcements` / `list_results`:
- `_meili_enabled()` 분기에서 `MeiliSearchClient().search()` 호출
- `SearchBackendUnavailable` 예외 발생 시 httpx.HTTPError → API 503으로 전파
- **fail-closed가 아닌 fail-open (503 응답)**: Meili 장애 시 목록 API가 503을 반환

### 5.3 Series B 위임 시 필요한 fail-closed

만약 Series B 쿼리를 Meili로 위임한다면:
- Meili 장애 시 RAG 통계 질의가 전체 실패하면 안 됨
- `retrieve_structured_data` 에서 Meili 호출을 감싸는 try/except가 필요
- Meili 결과와 MySQL 결과의 불일치를 허용할 수 없으므로, Meili 장애 시 MySQL 폴백이 필수
- **현 코드에 이 메커니즘은 없다.** 위임 구현 시 전제 조건으로 추가해야 한다.

---

## 6. 종합 판정

### 6.1 결론: **불가**

계열 B 다섯 쿼리를 Meilisearch로 위임할 수 없다. 이유는 세 가지다:

1. **결과 동일성 위반**: Meilisearch의 토큰 매칭은 SQL `LIKE '%...%'` 부분 일치와 의미가 다르다. 5개 표본 중 2개는 +137% 이상 초과, 1개는 -14% 미만 매칭. 이 편차는 RAG 답변의 `announcement_count`, `total_bids` 수치가 사용자에게 그대로 노출된다는 점에서 허용 불가.

2. **집계 기능 부재**: 계열 B의 #5는 `COUNT(bid_results.id)`, `AVG(sucsf_bid_rate)`, `SUM(sucsf_bid_amt)` 을 한 쿼리로 계산한다. Meilisearch는 집계 함수를 제공하지 않는다. COUNT 근사(`estimatedTotalHits`)만 이론적으로 가능하지만, 그것마저 토큰 매칭 의미 차이로 정확하지 않다.

3. **GROUP BY 부재**: `_top_rows`(top_winners, top_institutions, top_announcements)는 `GROUP BY + COUNT + ORDER BY` 집계를 필요로 한다. Meilisearch에 GROUP BY 개념이 없어 이 집계는 전량 MySQL에만 가능하다.

### 6.2 레이턴시는 매력적이지만 정확도가 따라주지 않음

Meilisearch는 11~463배 빠르다. 그러나 빠른 답이 틀린 답이면 의미가 없다. G1(데이터 무손실) 원칙이 결과 동일성을 요구하는 한, Meilisearch를 Series B에 위임할 수 없다.

### 6.3 기존 Meilisearch 활용 경로와의 관계

- **목록 검색 (G5/G6)**: `_meili_enabled()` 기반 위임이 이미 작동 중. 이 경로는 텍스트 검색 + 페이지네이션이 목적이라 토큰 매칭 의미 차이가 치명적이지 않다. 본 Task의 Series B와 무관.
- **Lexical 채널**: `retrieve_lexical_context`가 `bid_ntce_nm` 정확 일치를 위해 Meilisearch를 사용. 이 또한 Series B의 통계 집계와 무관.

### 6.4 Series B 비용 해소의 남은 경로

Meilisearch 위임이 불가하므로, 계열 B의 105.5초 비용은 다른 방법으로 해소해야 한다:

1. **캐시 워밍업**: warm 상태에서는 0.15초. 캐시 만료 시점의 cold만 문제. stale-while-revalidate 전략으로 사용자 체감 cold를 제거 가능.
2. **MySQL 버퍼 풀 관리**: cold SQL의 주원인은 MySQL 버퍼 풀 미스. InnoDB 버퍼 풀 사이즈 조정 또는 쿼리 결과의 Redis 캐시 TTL 연장으로 대응 가능.
3. **손상값 probe 제거 (G2)**: 매 질의당 ~27초의 중복 비용을 제거하면 Series B의 체감 비용이 크게 감소. `get_skipped_count`가 이미 스냅샷에 기록하므로 probe는 중복.

---

## 7. 재현 명령

```bash
# 1) Meilisearch 색인 상태 확인
uv run python -c "
from src.app.services.search_index import MeiliSearchClient, INDEX_UID
import json
client = MeiliSearchClient()
stats = client._request('GET', f'/indexes/{INDEX_UID}/stats')
print(json.dumps(stats, indent=2, ensure_ascii=False))
"

# 2) MySQL vs Meilisearch 비교 (거제시 + Servc)
uv run python -c "
import time
from sqlalchemy import text
from src.app.core.db import engine
from src.app.services.search_index import MeiliSearchClient, INDEX_UID
client = MeiliSearchClient()
with engine.connect() as conn:
    t0 = time.perf_counter()
    mysql = conn.execute(text(\"SELECT COUNT(*) FROM bid_announcements WHERE dminstt_nm LIKE '%거제시%' AND category = 'Servc'\")).scalar()
    print(f'MySQL: {mysql} ({(time.perf_counter()-t0)*1000:.0f}ms)')
t0 = time.perf_counter()
p = client._request('POST', f'/indexes/{INDEX_UID}/search', json={
    'q': '거제시', 'filter': 'dataset = \"announcement\" AND category = \"Servc\"',
    'limit': 0, 'attributesToRetrieve': [], 'attributesToSearchOn': ['dminstt_nm'],
    'matchingStrategy': 'all',
})
print(f'Meili: {p[\"estimatedTotalHits\"]} ({(time.perf_counter()-t0)*1000:.0f}ms)')
"
```

---

## 8. 본 보고서는 조사 전용이며 운영 코드를 수정하지 않았다. DB 쓰기 연산도 수행하지 않았다.

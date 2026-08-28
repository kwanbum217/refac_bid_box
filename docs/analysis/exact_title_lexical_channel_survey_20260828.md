# 정확 공고명 조회의 독립 Lexical 채널 처리를 위한 현황 조사 보고서

> **작성일**: 2026-08-28
> **조사 대상**: `src/rag/vector_store.py`, `src/rag/query_planning.py`, `src/rag/engine.py`, `src/app/services/search_index.py`, `src/app/services/bid_queries.py`
> **목적**: 정확 공고명 조회를 ChromaDB 벡터 후보 풀 30 확대에 의존하지 않고 독립 어휘(Lexical) 채널로 처리하기 위한 현황 조사 및 기술 분석

---

## 1. `_rerank_by_exact_title` 제목 정규화 단계 분석

[`src/rag/vector_store.py:140-176`](../../src/rag/vector_store.py#L140-L176)에 정의된 `_rerank_by_exact_title` 함수는 질의(`semantic_query`)와 각 문서의 공고명(`doc_title`)을 정규화 키로 변환한 후 상호 일치 여부를 비교합니다.

### 1.1 정규화 함수 및 정규식 정의

제목 정규화는 [`src/rag/vector_store.py:79-81`](../../src/rag/vector_store.py#L79-L81)의 정규식 패턴과 [`src/rag/vector_store.py:132-138`](../../src/rag/vector_store.py#L132-L138)의 `_normalize_match_key` 함수를 통해 수행됩니다.

| 단계 | 적용 코드 / 정규식 | 수행 내용 및 변환 규칙 |
| :--- | :--- | :--- |
| **단계 1** | [`src/rag/vector_store.py:136`](../../src/rag/vector_store.py#L136)<br>`unicodedata.normalize("NFC", str(value))` | 입력값을 문자열로 변환하고 유니코드 NFC(정규 결합) 형식으로 정규화합니다. |
| **단계 2** | [`src/rag/vector_store.py:136`](../../src/rag/vector_store.py#L136)<br>`.strip()` | 문자열 양 끝의 공백 문자를 제거합니다. |
| **단계 3** | [`src/rag/vector_store.py:136`](../../src/rag/vector_store.py#L136)<br>`.lower()` | 모든 영문 대문자를 소문자로 변환합니다. |
| **단계 4** | [`src/rag/vector_store.py:79-81`](../../src/rag/vector_store.py#L79-L81)<br>`MATCH_KEY_CLEAN_PATTERN.sub("", normalized)` | 정규식 `[\s\(\)\[\]\{\}\uff08\uff09\uff3b\uff3d\uff5b\uff5d\u3010\u3011\u3014\u3015\u3008\u3009\u300a\u300b\u300c\u300d\u300e\u300f]`을 매칭하여 모든 공백(`\s`)과 반각/전각 괄호 기호류(`()[]{}` 및 `（）［］｛｝【】〔〕〈〉《》「」『』`)를 빈 문자열(`""`)로 치환하여 완전히 제거합니다. |

### 1.2 재순위 처리 흐름

1. **질의 키 생성**: [`src/rag/vector_store.py:149`](../../src/rag/vector_store.py#L149)에서 `query_key = _normalize_match_key(semantic_query)`를 생성합니다. 키가 빈 문자열이면 원본 문서를 그대로 반환합니다.
2. **문서 제목 추출**: [`src/rag/vector_store.py:157-160`](../../src/rag/vector_store.py#L157-L160)에서 문서 본문의 `[공고명]` 정규식 매칭([`src/rag/vector_store.py:75`](../../src/rag/vector_store.py#L75), [`src/rag/vector_store.py:116-129`](../../src/rag/vector_store.py#L116-L129)) 또는 메타데이터의 `bid_ntce_nm`/`title`로부터 제목을 획득합니다.
3. **일치 판정 및 분리**: [`src/rag/vector_store.py:162-165`](../../src/rag/vector_store.py#L162-L165)에서 `_normalize_match_key(doc_title) == query_key`를 평가하여 일치하는 문서는 `exact_matches` 리스트에, 불일치 문서는 `others` 리스트에 분류합니다.
4. **결합 반환**: [`src/rag/vector_store.py:175`](../../src/rag/vector_store.py#L175)에서 `exact_matches + others` 형태로 정확 일치 문서를 상단으로 재배치합니다.

---

## 2. 제목 정규화 충돌 가능성 판정

현재 정규화 방식은 공백과 다양한 괄호 기호류를 무조건 제거하므로, 조달 공고에서 구분자로 사용되는 괄호 및 띄어쓰기 차이가 소실되어 **서로 다른 실제 공고가 동일한 정규화 키로 뭉개지는 충돌**이 발생합니다.

### 2.1 구체적 충돌 입력 쌍 유도

| 입력 쌍 구분 | 원문 제목 및 조달 공고상 의미 | 정규화 단계별 손 유도 과정 | 최종 정규화 키 및 충돌 여부 |
| :--- | :--- | :--- | :--- |
| **쌍 1**<br>(괄호 유무에 따른 차수/구분 소실) | **원문 A**: `2026년 도로포장공사(1차)`<br>*(1차분 발주 공고)*<br>**원문 B**: `2026년 도로포장공사 1차`<br>*(별도 일반 공고 또는 띄어쓰기 변형 공고)* | **원문 A 유도**:<br>1) NFC/소문자: `2026년 도로포장공사(1차)`<br>2) 공백/괄호 제거: `2026년도로포장공사1차`<br>**원문 B 유도**:<br>1) NFC/소문자: `2026년 도로포장공사 1차`<br>2) 공백/괄호 제거: `2026년도로포장공사1차` | **키**: `2026년도로포장공사1차`<br>**판정**: 완벽 일치 충돌 |
| **쌍 2**<br>(괄호 기호 형태 차이 및 긴급/재공고 식별) | **원문 A**: `[긴급] AI 서버 구매`<br>*(대괄호 긴급 공고)*<br>**원문 B**: `【긴급】 AI 서버 구매`<br>*(전각 렌티큘러 괄호 긴급 공고)* | **원문 A 유도**:<br>1) NFC/소문자: `[긴급] ai 서버 구매`<br>2) 공백/대괄호 제거: `긴급ai서버구매`<br>**원문 B 유도**:<br>1) NFC/소문자: `【긴급】 ai 서버 구매`<br>2) 공백/렌티큘러 제거: `긴급ai서버구매` | **키**: `긴급ai서버구매`<br>**판정**: 완벽 일치 충돌 |
| **쌍 3**<br>(단어 경계 및 띄어쓰기 차이) | **원문 A**: `초등 학교 급식 위탁`<br>*(단어별 띄어쓰기된 공고)*<br>**원문 B**: `초등학교 급식위탁`<br>*(복합명사 붙여쓰기된 공고)* | **원문 A 유도**:<br>1) NFC/소문자: `초등 학교 급식 위탁`<br>2) 공백 제거: `초등학교급식위탁`<br>**원문 B 유도**:<br>1) NFC/소문자: `초등학교 급식위탁`<br>2) 공백 제거: `초등학교급식위탁` | **키**: `초등학교급식위탁`<br>**판정**: 완벽 일치 충돌 |
| **쌍 4**<br>(기관명/사업구분 괄호 표기 변형) | **원문 A**: `소프트웨어 유지보수 사업(행정망)`<br>*(행정망 대상 특정 공고)*<br>**원문 B**: `소프트웨어 유지보수 사업 행정망`<br>*(동일 기관의 분리 공고)* | **원문 A 유도**:<br>1) NFC/소문자: `소프트웨어 유지보수 사업(행정망)`<br>2) 공백/괄호 제거: `소프트웨어유지보수사업행정망`<br>**원문 B 유도**:<br>1) NFC/소문자: `소프트웨어 유지보수 사업 행정망`<br>2) 공백/괄호 제거: `소프트웨어유지보수사업행정망` | **키**: `소프트웨어유지보수사업행정망`<br>**판정**: 완벽 일치 충돌 |

### 2.2 조달 공고 도메인 특성상 실재성 평가

- 나라장터 공고는 `(긴급)`, `(재공고)`, `(정정)`, `[소액수의]`, `(1차/2차)` 등 괄호 표기가 공고의 차수, 긴급 여부, 발주 형태를 나타내는 핵심 메타데이터로 빈번히 사용됩니다.
- 발주 기관마다 `()`, `[]`, `【】`, `〔〕` 등 사용하는 괄호 표기 양식이 다르고 띄어쓰기가 일관되지 않습니다.
- 따라서 단순 공백/괄호 제거 정규화는 **서로 다른 차수나 발주 구분을 가진 공고들을 동일한 정규화 키로 판정하여 잘못된 공고를 최상위 일치 문서로 승격시킬 위험**이 명백합니다.

---

## 3. 정확 제목 일치 복수 발생 시 순서 및 동점 해소(Tie-breaking) 판정

### 3.1 현재 코드의 처리 순서

[`src/rag/vector_store.py:153-175`](../../src/rag/vector_store.py#L153-L175)의 구현은 다음과 같이 순회합니다:

```python
    exact_matches: list[dict[str, Any]] = []
    others: list[dict[str, Any]] = []

    for doc in documents:
        # ...
        if doc_title and _normalize_match_key(doc_title) == query_key:
            exact_matches.append(doc)
        else:
            others.append(doc)
    # ...
    return exact_matches + others
```

1. 입력된 `documents` 리스트는 ChromaDB의 벡터 임베딩 유사도 질의 결과([`src/rag/vector_store.py:377-390`](../../src/rag/vector_store.py#L377-L390))로서, 거리(`distance`) 오름차순으로 정렬되어 있습니다.
2. `exact_matches`에는 `documents` 리스트에 처음 등장한 순서(즉, ChromaDB의 임베딩 거리 순서)대로 차례로 누적(`append`)됩니다.

### 3.2 동점 해소(Tie-breaking) 근거 유무 판정

- **판정: 동점 해소 로직 부재 (ChromaDB 임베딩 거리 순서에 완전 종속)**
- **근거**:
  - 동일한 정규화 키를 갖는 복수의 공고가 검색 풀 내에 존재할 때, 공고일시(`bid_ntce_dt`), 개찰일시(`rl_openg_dt`), 공고 차수(`bid_ntce_ord`), 계약금액, 또는 최신 수집일자 등 **비즈니스적 기준에 기반한 재정렬 로직이 전혀 구현되어 있지 않습니다**.
  - 만약 동일 명칭의 과거 연도 공고와 최신 공고가 함께 후보에 포함되어 있고 우연히 과거 공고의 임베딩 유사도가 더 높다면, 과거 공고가 최신 공고보다 우선하여 1위로 반환됩니다.

---

## 4. 후보 풀 30 확대(Candidate Pool Size) 적용 대상 분석

### 4.1 코드 근거 및 계산 로직

[`src/rag/vector_store.py:364-366`](../../src/rag/vector_store.py#L364-L366)에 정의된 쿼리 대상 후보 수(`query_top_k`) 계산 로직은 다음과 같습니다:

```python
    target_top_k = max(int(plan.top_k or DEFAULT_VECTOR_TOP_K), 1)
    base_fetch_k = target_top_k * POST_FILTER_FETCH_MULTIPLIER if has_post_filter else target_top_k
    query_top_k = max(base_fetch_k, DEFAULT_CANDIDATE_POOL_SIZE)
```

상수 정의:
- [`src/rag/schemas.py:22`](../../src/rag/schemas.py#L22): `DEFAULT_VECTOR_TOP_K = 5`
- [`src/rag/vector_store.py:35`](../../src/rag/vector_store.py#L35): `POST_FILTER_FETCH_MULTIPLIER = 3`
- [`src/rag/vector_store.py:38`](../../src/rag/vector_store.py#L38): `DEFAULT_CANDIDATE_POOL_SIZE = 30`

### 4.2 적용 대상 및 조건별 판정

| 질의 조건 및 상황 | 계산 과정 | 최종 `query_top_k` | 판정 결과 |
| :--- | :--- | :--- | :--- |
| **일반 기본 벡터 질의**<br>(post-filter 없음, `top_k=5`) | `target_top_k = 5`<br>`base_fetch_k = 5`<br>`query_top_k = max(5, 30)` | **30** | **post-filter가 없어도 강제로 30건을 ChromaDB에서 조회함** |
| **단일 문서 요청 질의**<br>(post-filter 없음, `top_k=1`) | `target_top_k = 1`<br>`base_fetch_k = 1`<br>`query_top_k = max(1, 30)` | **30** | **요청 `top_k`가 1이어도 강제로 30건을 조회함** |
| **Post-filter 적용 질의**<br>(기관명/기간 필터 있음, `top_k=5`) | `target_top_k = 5`<br>`base_fetch_k = 5 * 3 = 15`<br>`query_top_k = max(15, 30)` | **30** | **30건 조회** |
| **대용량 요청 질의**<br>(post-filter 있음, `top_k=15`) | `target_top_k = 15`<br>`base_fetch_k = 15 * 3 = 45`<br>`query_top_k = max(45, 30)` | **45** | `base_fetch_k`가 30을 초과할 때만 30건 이상 조회 |

### 4.3 판정 결론

- `query_top_k`는 `max(base_fetch_k, 30)`으로 하한선이 고정되어 있어, **post-filter(수요기관, 기간) 적용 여부 및 `top_k` 크기와 무관하게 모든 ChromaDB 벡터 검색 질의에서 최소 30건의 문서를 무조건 fetch**합니다.
- 이는 특정 임베딩 순위 10위권의 문서를 건져내기 위해 도입되었으나, 임베딩 검색의 I/O 및 역직렬화 부하를 불필요하게 가중시키고 있습니다.

---

## 5. 저장소 내 재사용 가능한 Meilisearch 및 Lexical 조회 경로 목록

저장소 내의 어휘(Lexical) 및 전문 검색 관련 구현을 조사한 결과입니다.

| 번호 | 파일 경로 및 위치 | 함수 / 클래스명 | 입력 매개변수 | 반환 형태 | 정확 공고명 일치 조회 활용 가능 여부 및 사유 |
| :---: | :--- | :--- | :--- | :--- | :--- |
| **1** | [`src/app/services/search_index.py:106-219`](../../src/app/services/search_index.py#L106-L219) | `MeiliSearchClient.search` | `query: str`,<br>`dataset: str` (`"announcement"` \| `"result"`),<br>`category: str \| None`,<br>`region: str \| None`,<br>`sort: list[str]`,<br>`offset: int`,<br>`limit: int` | `SearchPage`<br>(`ids: list[int]`, `has_next: bool`) | **활용 가능 (핵심 후보)**<br>- Meilisearch 인덱스 `bid_records`의 `searchableAttributes`에 `bid_ntce_nm`이 등록되어 있음([`src/app/services/search_index.py:146`](../../src/app/services/search_index.py#L146)).<br>- 따옴표 구문 검색(`"..."`)을 질의로 넘기면 정확 어휘 일치 검색 가능.<br>- 단, 현재 반환값은 `source_id` 리스트이므로 RAG 문서 포맷 매핑 또는 DB 재조회가 필요함. |
| **2** | [`src/app/services/search_index.py:115-133`](../../src/app/services/search_index.py#L115-L133) | `MeiliSearchClient._request` | `method: str`,<br>`path: str`,<br>`**kwargs: Any` | `dict[str, Any]`<br>(HTTP JSON 응답) | **활용 가능 (저수준 확장용)**<br>- 임의의 Meilisearch 엔드포인트(`POST /indexes/bid_records/search`)로 필터 및 검색 옵션을 직접 구성하여 호출 가능. |
| **3** | [`src/app/services/bid_queries.py:323-392`](../../src/app/services/bid_queries.py#L323-L392) | `list_announcements` | `db: Session`,<br>`q: str \| None`,<br>`cat: str \| None`,<br>`region: str \| None`,<br>`sort: str \| None`,<br>`page: int` | `OffsetPage`<br>(`items: list[BidAnnouncement]`, `total`, `page`, 등) | **제한적 활용 가능**<br>- Meilisearch 활성화 시 `_search_index_page`를 거쳐 ORM 객체를 반환하고, 비활성화 시 MySQL `contains` 쿼리를 수행함([`src/app/services/bid_queries.py:340-368`](../../src/app/services/bid_queries.py#L340-L368)).<br>- 페이지네이션 UI 전용 모델이므로 RAG 검색 파이프라인에 직접 끼우기에는 오버헤드가 있음. |
| **4** | [`src/app/services/bid_queries.py:394-455`](../../src/app/services/bid_queries.py#L394-L455) | `list_results` | `db: Session`,<br>`q: str \| None`,<br>`cat: str \| None`,<br>`region: str \| None`,<br>`sort: str \| None`,<br>`page: int` | `OffsetPage`<br>(`items: list[BidResult]`, 등) | **제한적 활용 가능**<br>- 낙찰 결과에 대한 어휘 검색 지원. 위 3번과 동일한 제약. |
| **5** | [`src/rag/structured_data.py:1-400`](../../src/rag/structured_data.py#L1-L400) | `retrieve_structured_data` | `db: Session`,<br>`plan: RetrievalPlan` | `dict[str, Any]` | **활용 불가 (기능 불일치)**<br>- SQL 기반 통계, 집계 및 최근 목록 질의 전용 함수. 공고명 텍스트에 대한 어휘 검색 기능은 없음. |
| **6** | [`src/rag/vector_store.py:320-460`](../../src/rag/vector_store.py#L320-L460) | `retrieve_semantic_context` | `plan: RetrievalPlan` | `SemanticSearchResult` | **독립 어휘 채널 아님**<br>- ChromaDB 벡터 검색 후 `_rerank_by_exact_title`로 후처리하는 구조임. |

---

## 6. 독립 Lexical 채널 도입 시 통합 지점 후보 및 위험 분석

### 6.1 통합 지점 후보 비교

```
[사용자 질의]
      │
      ▼
[후보 A: build_retrieval_plan] ── (use_lexical 플래그 판정)
      │
      ▼
[후보 C: RAG Engine _prepare_context] ── (Vector / Lexical / SQL 병렬·우선 분기)
      │
      ▼
[후보 B: vector_store 하이브리드 계층] ── (ChromaDB + Meilisearch 내부 합성)
```

| 구분 | 통합 지점 후보 | 분기 위치 (행 번호) | 설계 개요 | 잠재적 위험 및 주의사항 |
| :--- | :--- | :--- | :--- | :--- |
| **후보 A** | **쿼리 플래너 수준 분기**<br>(Planner-level Routing) | [`src/rag/query_planning.py:366-475`](../../src/rag/query_planning.py#L366-L475)<br>및 [`src/rag/schemas.py:50-62`](../../src/rag/schemas.py#L50-L62) | - `RetrievalPlan`에 `use_lexical: bool`, `lexical_query: str` 필드 추가.<br>- 질의에 따옴표(`"..."`)나 특정 공고명 개체 신호가 있을 경우 플래너가 `use_lexical=True` 설정.<br>- [`src/rag/engine.py:590-630`](../../src/rag/engine.py#L590-L630)에서 플랜에 따라 Meilisearch 채널을 직접 호출. | - 플래너의 정규식/키워드 판정이 실패할 경우 lexical 조회가 트리거되지 않고 누락될 위험.<br>- 플래너 규칙 복잡도 증가. |
| **후보 B** | **리트리버 저장소 수준 통합**<br>(Retriever-level Hybrid) | [`src/rag/vector_store.py:364-440`](../../src/rag/vector_store.py#L364-L440) | - `retrieve_semantic_context` 내부에서 ChromaDB 조회 전/병렬로 Meilisearch 정확 검색을 수행.<br>- 정확 일치 문서가 발견되면 Chroma 후보 30개 확대 없이 즉시 상위에 배치하거나 Chroma 검색을 생략. | - `src/rag/vector_store.py`가 ChromaDB뿐만 아니라 Meilisearch 클라이언트와 DB Session에 직접 의존하게 되어 모듈 결합도 증가.<br>- `DEFAULT_CANDIDATE_POOL_SIZE = 30` 제거를 위한 내부 흐름 분기 복잡화. |
| **후보 C** | **엔진 컨텍스트 준비 수준 다중 채널 합성**<br>(Engine-level Orchestration) | [`src/rag/engine.py:607-630`](../../src/rag/engine.py#L607-L630) | - `_prepare_context`에서 `use_sql`, `use_vector`와 대등하게 `lexical_search`를 수행.<br>- 어휘 검색 결과(`lexical_docs`)가 충분하면 `vector_docs`의 후보 풀을 기본 `top_k`(5)로 유지하거나 가중치 결합(RRF 등) 수행. | - `PreparedContext`, `_build_evidence_items`([`src/rag/answer_format.py:25`](../../src/rag/answer_format.py#L25)) 등 다운스트림 파이프라인의 증거 수집 포맷 수정 필요. |

### 6.2 권고 방향

- 가장 깔끔한 아키텍처는 **후보 C(엔진 컨텍스트 수준 다중 채널 합성)**와 **후보 A(플래너 스키마 확장)**의 결합입니다.
- 즉, 플래너는 질의 특성에 맞게 채널 플래그를 결정하고, `engine._prepare_context`에서 Meilisearch 독립 채널을 호출하여 정확 일치 문서를 확보한 뒤, ChromaDB에는 불필요한 30건 풀 조회를 요청하지 않고 원래의 `top_k`(예: 5)만 요청하도록 역할을 분리하는 것이 바람직합니다.

---

## 7. 조사 한계 및 미확인 사항

본 조사는 코드 및 아키텍처 정적 분석을 중심으로 수행되었으며, 다음 사항은 Task 범위 및 제약 조건(서비스 미기동, 성능 측정 금지)으로 인해 확인하지 않았습니다.

| 미확인 항목 | 미확인 사유 및 배경 |
| :--- | :--- |
| **1. 실제 DB 및 Meilisearch 색인 데이터의 공고명 중복 빈도 실측** | 실제 서비스 DB에 적재된 수십만 건의 공고 중 동일 정규화 키를 갖는 공고명 쌍의 실제 비율 및 분포는 DB 쿼리 실행 및 데이터 통계 조사가 제한되어 실측하지 못했습니다. |
| **2. Meilisearch 한국어 토크나이저의 형태소/특수문자 검색 거동 실측** | Meilisearch 서버가 기동되어 있지 않은 상태에서의 정적 코드 검토였으므로, 공고명 내 괄호/특수문자가 포함된 질의를 Meilisearch에 전달했을 때의 형태소 토큰화 및 정확 일치 점수 산정 거동을 실서버에서 테스트하지 않았습니다. |
| **3. ChromaDB 30건 조회와 Meilisearch 조회 간의 레이턴시 비교 실측** | 벤치마크 및 성능 측정 금지 규칙에 따라, 후보 풀 30건 ChromaDB 조회 대비 Meilisearch 단건 조회의 P95 레이턴시 차이를 직접 계측하지 않았습니다. |

---
*보고서 작성 완료.*

# Task 5df3f4d1da4f: ChromaDB 벡터 검색 필터 변환 및 결과 우선순위 개선 분석 보고서

> **작성일**: 2026-08-25
> **Task ID**: `task_5df3f4d1da4f`
> **상태**: 완료 (Completed)

---

## 1. 개요 및 배경

기존 `src/rag/vector_store.py`의 `retrieve_semantic_context`는 `collection.query(query_texts=[semantic_query], n_results=plan.top_k)`만 호출하여 질의 계획(`build_retrieval_plan`)이 계산한 카테고리 등의 필터가 전달되지 않고 버려졌습니다.
이로 인해 동일/유사 사업명의 공고가 다수 존재할 때 낙찰 결과가 없는 공고가 상위를 차지하여, 낙찰 결과를 묻는 질의에서 필요한 문서를 수신하지 못하는 문제가 발생했습니다.

또한, 복합 질의(예: "○○건축공사 감리 용역")에서 기존 카테고리 키워드 매칭이 첫 번째 일치("공사")에서 종료되어 실제 메타데이터인 "용역"(Servc) 대신 "공사"(Cnstwk)로 오분류되는 잠복 결함이 확인되었습니다.

본 작업에서는 다음을 구현하여 해결했습니다:
1. ChromaDB 메타데이터(`bidding_kb`)에서 표현 가능한 필터(`category`, `has_result`)를 추출하여 `where` 절로 변환
2. 낙찰 결과 질의 시 `has_result=True` 조건을 부여
3. 카테고리 키워드 추출 시 한국어 명사구 구조상 핵어(마지막 위치 키워드)를 채택하도록 개선
4. 필터 검색 결과가 0건일 경우 자동으로 필터를 해제하여 완화(fallback) 재검색을 수행

---

## 2. 변경 내용 및 설계 결정

### 2.1 ChromaDB where 절 변환 함수 (`build_vector_where`)
- `src/rag/vector_store.py`에 `build_vector_where` 함수를 구현했습니다.
- 지원 메타데이터 필드(`category`, `has_result`, `type`, `id`, `doc_hash`, `fmt`)만 `where` 절에 포함합니다.
- `date_from`, `date_to`, `institution_name`, `result_limit`, `analysis_mode` 등 메타데이터에 없는 필터는 조용히 버려지지 않도록 디버그 로그(`logger.debug`)를 남기고 `where` 절에서 안전하게 제외했습니다.
- 단일 조건일 때는 `{"category": "Servc"}` 또는 `{"has_result": True}` 형태로 반환하고, 2개 이상의 조건일 때는 `{"$and": [...]}` 표준 문법으로 결합합니다.

### 2.2 낙찰 결과 질의 판별 (`is_result_query`)
- `src/rag/query_planning.py`에 `is_result_query` 함수를 구현했습니다.
- 기존 정의된 `RESULT_QUERY_MARKERS` ("낙찰된", "낙찰 결과", "낙찰정보", "낙찰 정보", "낙찰 사업", "낙찰 업체"), 통계 키워드("낙찰률"), 개체 속성 지목 패턴("최종 낙찰", "낙찰업체", "낙찰자", "낙찰금액", "1순위 낙찰" 등)을 재사용하여 별도의 임의 키워드 목록 없이 정확하게 변별합니다.
- 낙찰 결과를 묻지 않는 일반 공고 질의나 기준 질의("...입찰 참가 조건", "...공고 목록", "적격심사 기준")에는 `has_result` 조건을 부여하지 않아 진행 중 공고 검색을 보존합니다.

### 2.3 카테고리 핵어(마지막 위치) 우선 매칭
- `src/rag/query_planning.py`의 `build_retrieval_plan`에서 `CATEGORY_KEYWORDS` 순회 시 `rfind`를 사용하여 질의 문자열에서 가장 마지막에 등장하는 카테고리 키워드를 선택하도록 변경했습니다.
- 예: "봉화 공설운동장 리모델링 사업 건축공사 감리 용역" -> "공사"(pos=24)보다 뒤에 위치한 "용역"(pos=32)이 최종 채택되어 `category="Servc"`로 정확히 분류됩니다.
- 카테고리 키워드가 전혀 없는 질의는 종전과 같이 `category` 필터를 생성하지 않습니다.

### 2.4 필터 0건 시 완화(Fallback) 재검색 및 상태 기록
- 필터(`where`)가 적용된 검색 결과가 0건인 경우, `retrieve_semantic_context`가 필터 없이 1회 재검색을 수행하여 결과를 반환합니다.
- `SemanticSearchResult`에 `relaxed: bool = False` 필드 및 `filter_relaxed` 프로퍼티를 추가하여 완화 재검색 여부를 명확히 기록합니다.

---

## 3. 검증 결과

### 3.1 단위 및 회귀 테스트
- `tests/test_vector_store_filters.py`:
  - (a) category 단일 조건의 where 절 반영 검증
  - (b) 결과 질의 시 has_result=True 추가 검증
  - (c) 비결과 질의 시 has_result 제외 검증
  - (d) date_from/date_to/institution_name 미누출 검증
  - (e) 다중 조건의 $and 결합 검증
  - (f) 필터 0건 시 완화 재검색 및 relaxed 플래그 설정 검증
  - (g) AsyncVectorStore 의 filters 인자 전달 검증
- `tests/test_query_planning.py`:
  - `is_result_query` 판별 회귀 테스트
  - fixture 파일 기반 복합 카테고리(q01, q02, q03 -> Servc, q08, q09 -> Cnstwk, q14 -> Thng) 핵어 우선 매칭 회귀 테스트
- 실행 결과: `uv run pytest tests/test_vector_store_filters.py tests/test_query_planning.py -q` (38 passed)
- 전체 테스트 결과: `uv run pytest tests/ -q -m "not data_assets"` (2098 passed)
- 정적 분석 및 규칙 검증:
  - `uv run ruff check src/ tests/` (All checks passed)
  - `python3 scripts/validate_agent_rules.py --quiet` (12/12 passed)

### 3.2 ChromaDB 실측 쿼리 검증 (fixture 16문항 전량)
- fixture v2 의 16개 `context_sufficient` 문항 전체에 대해 ChromaDB `bidding_kb` 실측 검색을 수행한 결과:
  - **적중률: 16/16 (100% HIT)**
  - q01 (`bid_10015927` HIT), q02 (`bid_10015878` HIT), q03 (`bid_10015925` HIT), q04~q16 전량 1순위 근거 적중 확인

---

## 4. 변경 파일 목록

| 파일 경로 | 변경 요약 |
| --- | --- |
| `src/rag/vector_store.py` | `build_vector_where` 구현, `retrieve_semantic_context` where 절 및 완화 재검색 적용, `SemanticSearchResult.relaxed` 추가 |
| `src/rag/query_planning.py` | `is_result_query` 함수 추가, `CATEGORY_KEYWORDS` 마지막 위치(핵어) 매칭 로직 개선 |
| `tests/test_vector_store_filters.py` | ChromaDB 메타데이터 where 절 변환 및 완화 재검색 단위 테스트 추가 |
| `tests/test_query_planning.py` | `is_result_query` 판별 및 fixture 기반 카테고리 판별 회귀 테스트 추가 |
| `docs/analysis/task_5df3f4d1da4f.md` | 작업 분석 및 검증 보고서 작성 |

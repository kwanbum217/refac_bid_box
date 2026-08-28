# Task task_a2764ba98c7c 분석 및 구현 보고서

> **작성일**: 2026-08-28
> **작업자**: Orca Worker (Builder)
> **Task ID**: task_a2764ba98c7c
> **Run ID**: run_43d9937ac156

---

## 1. 개요 및 배경

### 1.1 배경 및 문제점
- 기존 정확 공고명 검색은 ChromaDB 임베딩 검색 시 후보 풀을 30개로 강제 확대(`DEFAULT_CANDIDATE_POOL_SIZE = 30`)한 뒤, 본문 공고명을 파싱하여 `_rerank_by_exact_title()`로 재순위하는 임시 방식에 의존했습니다.
- 외부 감사 및 현황 조사(`docs/analysis/exact_title_lexical_channel_survey_20260828.md`) 결과 다음과 같은 구조적 결함이 확인되었습니다:
  1. **제목 정규화 충돌**: `_normalize_match_key()`가 공백과 괄호 기호 전체를 무조건 삭제하여 `'2026년 도로포장공사(1차)'`와 `'2026년 도로포장공사 1차'`가 동일한 정규화 키로 뭉개져 오탐 발생.
  2. **동점 해소(Tie-breaker) 부재**: 동일 정규화 키를 갖는 복수 문서가 존재할 때, 업무적 기준 없이 ChromaDB 벡터 임베딩 거리 순서에 무조건 의존하여 과거 공고가 최신 공고보다 우선 반환되는 비결정성 문제.
  3. **독립 어휘 채널 부재**: `bid_records` 인덱스에 공고명(`bid_ntce_nm`)이 색인된 Meilisearch 전문 검색 읽기 모델이 이미 존재함에도 불구하고 RAG 엔진에서 이를 독립 채널로 활용하지 못함.

### 1.2 구현 목표
1. **플래너 스키마 확장 (후보 A)**: `RetrievalPlan`에 `use_lexical: bool`과 `lexical_query: str | None` 필드를 기본값과 함께 추가하고, 개체 질의 및 따옴표 질의 시 안전하게 활성화.
2. **엔진 컨텍스트 합성 (후보 C)**: `HybridRAGEngine._prepare_context`에서 Meilisearch 독립 어휘 채널을 호출하여 정확 일치 문서를 확보하고 벡터 결과 상위에 배치.
3. **결정적 동점 해소 (Tie-breaking)**: 복수 정확 일치 시 공고일시(`bid_ntce_dt` 최신순) -> 개찰일시(`rl_openg_dt`) -> 공고번호(`bid_ntce_no`) -> 차수(`bid_ntce_ord`) 순의 결정적 기준 적용.
4. **괄호 보존 정규화**: 괄호 내용을 삭제하지 않고 표준 괄호(`()`)로 일원화하여 차수/구분 괄호 유무에 따른 충돌 방지.
5. **안전한 폴백 및 후보 풀 30 유지**: Meilisearch 비활성(`MEILI_ENABLED=False`), 서버 미기동, 예외, 0건 매칭 시 기존 ChromaDB 벡터 검색 결과로 무장애 폴백.

---

## 2. 주요 아키텍처 및 변경 상세

### 2.1 검색 스키마 확장 (`src/rag/schemas.py`)
- `RetrievalPlan`에 `use_lexical: bool = False`, `lexical_query: str | None = None` 추가.
- 기존 필드 기본값을 보존하여 기존 호출부 및 직렬화 경로와 100% 하위 호환성 유지.

### 2.2 쿼리 플래너 라우팅 (`src/rag/query_planning.py`)
- `is_entity_specific_query` 및 `QUOTED_TITLE_PATTERN` 정규식을 활용하여 개체 질의 또는 따옴표로 감싼 공고명이 감지되면 `use_lexical=True`와 `lexical_query`를 설정.
- 따옴표 인용구가 있을 경우 인용구 내부 텍스트를 `lexical_query`로 우선 추출하여 Meilisearch 어휘 검색 정확도 향상.

### 2.3 Meilisearch 어휘 채널 및 컨텍스트 합성 (`src/rag/engine.py`)
- `retrieve_lexical_context(plan, db=None)` 함수 구현:
  - `settings.MEILI_ENABLED` 검사 및 `MeiliSearchClient`를 통한 `POST /indexes/bid_records/search` 질의.
  - 카테고리(`category`), 수요기관/지역(`region_codes`) 필터 반영.
  - 서버 미기동, 연결 실패, 예외 발생 시 경고 로그를 남기고 빈 리스트를 반환하여 안전하게 무장애 폴백.
- `_prepare_context` 합성 로직:
  - `plan.use_lexical` 활성화 시 Meilisearch 어휘 채널 호출.
  - 정규화 키 일치 문서를 추출하고 `_extract_doc_sort_key` 기반으로 정렬.
  - 정확 일치 문서를 `vector_docs` 최상단에 우선 배치하고 기존 벡터 문서와 중복 제거.
  - `PreparedContext`에 세부 계측 지표 `lexical_ms` 추가.

### 2.4 괄호 보존 정규화 및 결정적 Tie-breaker (`src/rag/vector_store.py`)
- `_normalize_match_key`:
  - `OPEN_BRACKETS_PATTERN` 및 `CLOSE_BRACKETS_PATTERN`을 통해 전각/반각/대괄호/렌티큘러 괄호(`[], {}, （）, 【】` 등)를 표준 `(` 및 `)`로 정규화.
  - 괄호 자체를 제거하지 않음으로써 `'도로포장공사(1차)'` (`"도로포장공사(1차)"`)와 `'도로포장공사 1차'` (`"도로포장공사1차"`)가 서로 다른 키를 갖도록 충돌 해소.
- `_extract_doc_sort_key`:
  - 1순위: 공고일시 (`bid_ntce_dt` 최신순)
  - 2순위: 개찰일시 (`rl_openg_dt` 최신순)
  - 3순위: 공고번호 (`bid_ntce_no`)
  - 4순위: 공고차수 (`bid_ntce_ord`)
  - 벡터 검색 재순위(`_rerank_by_exact_title`)와 엔진 어휘 합성 양쪽에서 동일한 정렬 함수를 공유.

### 2.5 후보 풀 30 (`DEFAULT_CANDIDATE_POOL_SIZE = 30`)을 유지하는 이유
- Meilisearch는 독립 데몬으로 실행되며 환경 설정(`MEILI_ENABLED`)이나 네트워크/컨테이너 상태에 따라 비활성이거나 장애가 발생할 수 있습니다.
- Meilisearch 어휘 채널 실패 시 ChromaDB 벡터 검색이 안정적인 폴백 안전망으로 작동해야 하므로, 임베딩 거리 10위권에 밀집된 동명/유사 사업 공고를 놓치지 않기 위해 기존 `DEFAULT_CANDIDATE_POOL_SIZE = 30` 경로를 삭제하지 않고 폴백 용도로 유지합니다.

---

## 3. 검증 결과

### 3.1 회귀 및 단위 테스트 (`tests/test_rag_lexical_channel.py`, `tests/test_vector_store_filters.py`, `tests/test_query_planning.py`, `tests/test_rag_engine.py`)
- `tests/test_rag_lexical_channel.py` 신규 추가 (전체 항목 통과):
  - `test_planner_sets_use_lexical_for_entity_queries`: 개체 질의 시 `use_lexical=True` 검증.
  - `test_planner_extracts_quoted_title_for_lexical_query`: 따옴표 제목 추출 검증.
  - `test_planner_keeps_use_lexical_false_for_pure_aggregation`: 순수 집계 질의 비활성화 검증.
  - `test_engine_promotes_lexical_exact_match_above_vector_results`: 정확 일치 문서 최상위 배치 검증.
  - `test_engine_fallback_when_meili_disabled`: 비활성화 시 무장애 폴백 검증.
  - `test_engine_fallback_when_meili_raises_exception`: 서버 예외 시 무장애 폴백 검증.
  - `test_engine_fallback_when_meili_returns_zero_hits`: 0건 검색 시 무장애 폴백 검증.
  - `test_normalize_key_distinguishes_parentheses_vs_space`: 괄호 유무 충돌 방지 검증.
  - `test_normalize_key_handles_various_bracket_styles`: 다양한 괄호 표준화 일치 검증.
  - `test_deterministic_tie_breaking_prefers_latest_notice_date`: 최신 공고일시 우선 동점 해소 검증.
  - `test_extract_doc_sort_key_deterministic`: 정렬 키 튜플 결정론 검증.

### 3.2 다중 에이전트 규칙 검증
- `python3 scripts/validate_agent_rules.py --quiet`: 통과 (12/12 건).
- `uv run pytest tests/ -q -m 'not data_assets'`: 전체 2,393 건 테스트 통과.

---

## 4. 향후 계획 (Next Steps)
1. **실제 Meilisearch 기동 환경에서의 레이턴시 실측**:
   - Meilisearch Docker 컨테이너가 기동된 통합 환경에서 벡터 검색 단독 대비 어휘 채널 병렬/합성 시의 P95 레이턴시 계측.
2. **후보 풀 크기 조건부 축소 검토**:
   - Meilisearch 어휘 채널이 성공하여 정확 일치 문서가 확보된 경우, ChromaDB 조회를 건너뛰거나 `query_top_k`를 기본 `top_k`(5)로 축소하여 임베딩 검색 부하를 경감하는 최적화 도입.

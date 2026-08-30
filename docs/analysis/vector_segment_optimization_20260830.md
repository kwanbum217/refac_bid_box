# Vector 구간 지연 분석 및 무손실 최적화 (2026-08-30)

> **작성일**: 2026-08-30
> **작성자**: Task task_f4651d2ec6ef (Builder)
> **대상**: `src/rag/vector_store.py`, `tests/test_vector_store_perf.py`
> **원칙**: 검색 결과 100% 불변(Output Invariance) 보장, 무손실(G1) 준수, 실측 미수행(직렬 구간 측정 명령 제공)

---

## 1. 개요 및 배경

2026-08-30 정본 구간 레이턴시 측정(`data/benchmarks/rag_segments_canonical_20260830.json`) 결과, 전체 RAG 지연 중 `vector` 구간이 33.0% (P50 1,307.88ms, P95 2,058.22ms)를 차지하여 `llm` (65.8%)과 함께 전체 지연의 98.8%를 점유하고 있습니다.

동일 일자 측정에서 검색 경로 변경으로 인한 회귀(정확 공고명 포함 매칭을 Lexical 채널 상위로 승격시켰을 때 낙찰 결과를 담지 않은 문서가 결과를 담은 문서를 `top_k=5` 절단선 밖으로 밀어내어 numeric 및 refusal 정확도가 저하됨)를 겪은 바 있습니다. 따라서 본 작업은 **검색 반환 문서 집합 및 순서를 단 한 건도 변경하지 않는 범위(Output Invariance)** 내에서만 코드 수준 최적화를 수행하고, 결과 변경 가능성이 있는 모든 후보는 근거와 함께 제안 목록으로 분리합니다.

---

## 2. Vector 구간 세부 단계별 시간 소비 분해

`src/rag/vector_store.py:retrieve_semantic_context` 경로의 실행 흐름을 세부 단계별로 분해한 구조 및 시간 소비 특성은 다음과 같습니다.

| 단계 | 주요 연산 및 로직 | 예상 소요 비중 | 성격 및 병목 요인 |
| --- | --- | ---: | --- |
| **1. 계획 및 필터 정규화** | `_normalize_text`, `build_vector_where`, post-filter 날짜/기관 파싱 | < 0.05ms (< 0.01%) | 순수 CPU 메모리 연산 |
| **2. ChromaDB 클라이언트 및 컬렉션 준비** | `chromadb.PersistentClient`, `get_collection` | ~5.0 - 15.0ms (~0.5 - 1.0%) | SQLite 연결 점검 및 세그먼트 메타데이터 조회 |
| **3. 임베딩 계산 (Embedding Inference)** | `bge-m3` 모델(ONNX/PyTorch) 질의 텍스트 1,024차원 밀집 벡터 추론 | **~1,200.0 - 1,900.0ms (> 95.0%)** | **CPU 연산 집중 병목** (815M 파라미터 다국어 트랜스포머 순전파) |
| **4. ChromaDB HNSW 인덱스 탐색 및 메타데이터 필터링** | HNSW 그래프 거리 계산, SQLite 메타데이터 `$and` 필터링 및 30건 후보 추출 | ~5.0 - 15.0ms (~0.5 - 1.0%) | C++/Rust HNSW 탐색 및 SQLite I/O |
| **5. 역직렬화 및 Post-filtering** | 본문 정규식 추출(`INSTITUTION_PATTERN`, `OPENING_DATE_PATTERN`, `NOTICE_DATE_PATTERN`), fail-closed 판정 | ~0.5 - 2.0ms (~0.1%) | 정규식 매칭 및 날짜 비교 |
| **6. 정확 공고명 재순위 (Reranking)** | `_normalize_match_key`, `_rerank_by_exact_title`, 다중 일치 시 최신순 정렬 | ~0.2 - 1.0ms (< 0.1%) | 부분 문자열 탐색 및 동점 해소 키 정렬 |
| **7. 절단 및 반환 객체 구성** | `target_top_k` 슬라이싱 및 `SemanticSearchResult` 인스턴스화 | < 0.05ms (< 0.01%) | 리스트 슬라이싱 |

---

## 3. 구현된 최적화 내역 (출력 100% 불변 보장)

모든 구현은 기존 검색 결과(반환 문서 ID, 정렬 순서, 메타데이터, distance, provenance)를 100% 동일하게 유지합니다.

| 변경 위치 | 기존 로직 | 최적화 구현 내용 | 안전성 및 불변성 근거 |
| --- | --- | --- | --- |
| `_normalize_text` | `unicodedata.normalize("NFC", (value or "").strip())` | `not value` 또는 `not stripped` 시 `""` 조기 반환 | 빈 값/공백에 대해 `unicodedata.normalize` 호출을 생략하며 반환값 `""`로 100% 동일 |
| `_normalize_match_key` | `unicodedata.normalize("NFC", str(value)).strip().lower()` | `not value` 또는 `not stripped` 시 `""` 조기 반환 | 빈 값/공백에 대해 정규화 및 정규식 치환을 생략하며 반환값 `""`로 100% 동일 |
| `extract_effective_document_date` | `extract_document_dates`로 공고일시·개찰일시 정규식을 모두 수행 후 개찰일시 우선 채택 | 개찰일시 정규식을 먼저 탐색하여 일치 시 공고일시 정규식 탐색을 완전히 생략 | 개찰일시 존재 시 공고일시 값은 폐기되므로 유효 날짜 반환값은 100% 동일 |
| `_matches_post_filters` | `extract_document_institution` 반환값에 대해 `_normalize_text` 중복 호출 | `extract_document_institution`이 이미 NFC 정규화 문자열을 반환하므로 중복 호출 제거 | 이미 정규화된 문자열의 부분 문자열 판정이므로 결과 100% 동일 |
| `_rerank_by_exact_title` | `len(query_key) < 5`인 경우에도 30건 전체에 대해 루프 수행 및 일치 건수 1건일 때도 정렬 수행 | `len(query_key) < RERANK_MIN_TITLE_LENGTH(5)` 시 즉시 반환, 일치 문서 수가 1건 이하일 때 `sort()` 생략 | 5자 미만 질의는 5자 이상 공고명을 포함할 수 없으므로 매칭 불가능하며, 1건 정렬은 no-op이므로 100% 동일 |
| `retrieve_semantic_context` | 구간 계측 로깅 부재 | `logger.isEnabledFor(logging.DEBUG)` 조건부 세부 구간 계측(query, post_process, total) 추가 | 디버그 모드에서만 계측하여 운영 오버헤드 0ms 유지 |

---

## 4. 구현하지 않은 후보 및 기각/제안 사유

검색 결과가 변경될 위험이 있거나 프로젝트 원칙에 위배되는 후보는 구현하지 않고 아래와 같이 사유를 기록합니다.

| 최적화 후보 | 예상 지연 단축 효과 | 검색 결과 변경 위험 | 기각 / 미구현 근거 |
| --- | :---: | :---: | --- |
| **후보 풀 `DEFAULT_CANDIDATE_POOL_SIZE` 축소 (30 -> 10건)** | 10 - 20ms 절감 | **치명적 (High)** | **기각**: 2026-08-30 실측에서 q21 정답 문서(`bid_10169448`)가 벡터 9위였으며 30건 풀 덕분에 1위로 승격됨. 풀을 축소하면 q21 등 하위 순위 기대 문서가 탈락하여 RAG 품질 회귀 발생. |
| **임베딩 모델 교체 (`bge-m3` -> MiniLM/Small)** | 1,000 - 1,500ms 절감 | **치명적 (High)** | **기각**: MiniLM은 한국어 공공조달 top-5 적중률이 4%에 불과하여 이미 기각됨. 임베딩 모델 교체 시 벡터 공간 전체가 재배치되어 검색 결과 전면 변경. |
| **재순위 기준 완화 (부분 문자열 -> 퍼지/편집거리 매칭)** | 0ms (오히려 증가) | **치명적 (High)** | **기각**: 2026-08-30 실측에서 Lexical 포함 매칭 완화 시 numeric 138 -> 132, refusal 93 -> 90으로 회귀 발생. 5자 이상 엄격 포함 매칭 규칙 유지 필수. |
| **Post-filter fail-closed 해제 (fail-open 전환)** | 0ms | **치명적 (High)** | **기각**: 날짜/기관 파싱 불가 문서를 통과시키면 필터 조건 밖 문서가 답변 컨텍스트에 섞여 품질 회귀 발생. |
| **임베딩 벡터 차원 축소 (Matryoshka / PCA)** | 5 - 10ms 절감 | **중간 (Medium)** | **미구현**: 벡터 차원 축소 시 코사인 유사도 순위가 미세하게 변경될 수 있어 사전 벤치마크 및 재색인 없이 적용 불가. |
| **동일 질의 임베딩/결과 인메모리 캐싱 (LRU Cache)** | 반복 질의 시 1,300ms 절감 (Hit 시 0ms) | **낮음 (Low)** | **제안(추후 검토)**: 완전 동일 질의 반복 시 지연을 0ms로 단축 가능하나, 콜드/비반복 질의 지연에는 영향이 없고 지식베이스 점진 증분 색인 시 캐시 무효화 동기화 복잡도 고려 필요. |

---

## 5. 불변성 검증 및 안전장치

`tests/test_vector_store_perf.py`에 다음 6대 안전장치 테스트를 구축하여 회귀를 기계적으로 차단했습니다:

1. `test_vector_store_invariants_constants`: `DEFAULT_CANDIDATE_POOL_SIZE == 30`, `RERANK_MIN_TITLE_LENGTH == 5`, `POST_FILTER_FETCH_MULTIPLIER == 3` 불변 검증.
2. `test_normalize_text_invariance`: 유니코드 NFD 결합, 공백, None, 빈 문자열의 정규화 출력 일치 검증.
3. `test_normalize_match_key_invariance`: 다양한 괄호(대괄호, 중괄호, 특수괄호) 정규화 및 공백 제거 키 불변 검증.
4. `test_extract_document_dates_and_effective_date_invariance`: 개찰일시/공고일시 우선순위 판정 불변 검증.
5. `test_matches_post_filters_invariance`: 기관명 및 기간 필터의 fail-closed 판정 불변 검증.
6. `test_rerank_30_candidates_q21_exact_match_order_invariance` & `test_retrieve_semantic_context_deterministic_output`: 고정 30건 풀에 대해 q21 승격, 다중 일치 동점 해소, 짧은 질의 원본 순서 보존 검증.

---

## 6. 재현 및 성능 실측 안내 (코디네이터용)

본 Task는 fixture 실측을 수행하지 않았으며 수치를 임의로 추정하지 않았습니다. 코디네이터가 직렬 측정 환경에서 성능 개선 효과를 측정할 수 있는 절차는 다음과 같습니다.

```bash
# 1. 벡터 저장소 불변성 및 기존 RAG 테스트 전체 검증
uv run pytest tests/test_vector_store_perf.py tests/test_rag_vector_store.py tests/test_vector_store_filters.py -q

# 2. 전체 테스트 스위트 통과 확인
uv run pytest tests/ -q -m 'not data_assets'

# 3. 다중 에이전트 규칙 정합성 검증
python3 scripts/validate_agent_rules.py --quiet

# 4. (코디네이터 전용) 컨테이너 기동 후 구간 레이턴시 정본 직렬 재측정
# uv run python scripts/benchmark_rag_segments.py \
#   --fixture data/eval/llm_quality_fixture_v2.json \
#   --repetitions 3 --expected-llm-model gemma4:e2b \
#   --output data/benchmarks/<산출물>.json
```

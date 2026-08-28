# Conditional Vector Bypass 구현 완료 보고서

> **작성일**: 2026-08-28
> **작성자**: Orca Worker (Role: builder / Task: task_7ba76bc4cb71)
> **상태**: 구현 완료
> **목적**: 어휘(Lexical) 검색에서 정확 공고명 일치가 확보된 경우 ChromaDB 후보 풀 30 조회를 조건부로 생략(Bypass)하고, 실패/비적중 시 기존 벡터 경로로 100% 폴백하도록 실행 순서 재배치 및 무손실 검증

---

## 1. 개요 및 배경

기존 하이브리드 RAG 엔진(`src/rag/engine.py`)은 검색 채널 실행 순서가 `SQL -> Vector (ChromaDB 30개 후보 조회) -> Lexical (Meilisearch)` 순서로 고정되어 있었습니다.
이로 인해 Meilisearch 에 질의 공고명이 100% 정확히 존재하여 최우선 채택될 수 있는 단일 공고 질의(q01~q24)에서도 불필요하게 ChromaDB 임베딩 검색 및 30개 문서 역직렬화/재순위 연산이 선행되는 비효율이 존재했습니다.

이에 따라 조사 보고서 [conditional_vector_bypass_survey_20260828.md](conditional_vector_bypass_survey_20260828.md)의 **설계안 1(Sequential Lexical-First Complete Bypass)**을 정본 사양으로 채택하여 구현을 완료했습니다.

---

## 2. 변경된 검색 실행 순서 및 코드 구현

### 2.1 검색 채널 실행 순서 비교

| 실행 단계 | 변경 전 순서 | 변경 후 순서 | 진입 조건 (`src/rag/engine.py`) | 동작 및 바이패스 로직 |
| :--- | :--- | :--- | :--- | :--- |
| **1단계** | Plan 수립 | Plan 수립 | 무조건 실행 | `build_retrieval_plan(user_query)` 호출 |
| **2단계** | SQL 정형 검색 | SQL 정형 검색 | `if plan.use_sql and structured_data is None and db is not None:` | MySQL 집계/조회 수행 (`src/rag/engine.py:744-747`) |
| **3단계** | Vector (ChromaDB) | **Lexical (Meilisearch)** | `if plan.use_lexical and not vector_docs:` | Meilisearch 조회 후 정확 공고명 일치(`_normalize_match_key`) 문서 추출 (`src/rag/engine.py:755-783`) |
| **4단계** | Lexical (Meilisearch) | **Vector (ChromaDB)** | `if plan.use_vector and not vector_docs:` | **Lexical 정확 일치가 1건 이상이면 `vector_docs`가 이미 채워져 있으므로 ChromaDB 조회가 자동 생략(Bypass)**됨 (`src/rag/engine.py:786-807`) |
| **5단계** | KB Status 메타 조회 | KB Status 메타 조회 | `if plan.use_kb_status and kb_status is None and db is not None:` | 지식베이스 버전 조회 (`src/rag/engine.py:810-815`) |
| **6단계** | 컨텍스트 합성 (Assembly) | 컨텍스트 합성 (Assembly) | 무조건 실행 | EvidenceItem 생성 및 프롬프트 조립 (`src/rag/engine.py:817-860`) |

### 2.2 핵심 코드 변경 상세

#### `src/rag/engine.py:754-808` (`_prepare_context` 내부)

```python
        # 1. Lexical (Meilisearch) 어휘 채널 선행 호출 및 정확 일치 검사
        if plan.use_lexical and not vector_docs:
            t_lex_start = _safe_perf_counter()
            lexical_candidates = retrieve_lexical_context(plan, db=db)
            lexical_elapsed_ms = (_safe_perf_counter() - t_lex_start) * 1000.0

            if lexical_candidates:
                query_key = _normalize_match_key(plan.lexical_query or plan.semantic_query)
                exact_lexical_matches: list[dict[str, Any]] = []

                for doc in lexical_candidates:
                    raw_doc_meta = doc.get("metadata")
                    doc_meta: dict[str, Any] = (
                        raw_doc_meta if isinstance(raw_doc_meta, dict) else {}
                    )
                    doc_title = doc_meta.get("bid_ntce_nm") or extract_document_title(
                        doc.get("document")
                    )
                    if doc_title and _normalize_match_key(doc_title) == query_key:
                        exact_lexical_matches.append(doc)

                if exact_lexical_matches:
                    exact_lexical_matches.sort(key=_extract_doc_sort_key, reverse=True)
                    target_k = plan.top_k or DEFAULT_VECTOR_TOP_K
                    vector_docs = exact_lexical_matches[:target_k]
                    logger.info(
                        "Meilisearch 어휘 채널 정확 일치 문서 %d건 우선 채택 완료 (ChromaDB 벡터 검색 생략, 총 %d건)",
                        len(exact_lexical_matches),
                        len(vector_docs),
                    )

        # 2. Vector (ChromaDB) 의미 검색 (Lexical 정확 일치가 없을 때만 실행)
        if plan.use_vector and not vector_docs:
            t_vector_start = _safe_perf_counter()
            result = retrieve_semantic_context(plan)
            vector_elapsed_ms = (_safe_perf_counter() - t_vector_start) * 1000.0
            vector_docs = result.documents
            if not result.ok:
                vector_failed = True
            else:
                vector_filter_provenance = result.as_filter_provenance()
                if result.filter_relaxed:
                    vector_hints.append(
                        "지식베이스 검색 필터가 완화되어 필터 조건 밖 문서가 반환되었을 수 있습니다."
                    )
                if result.unsupported_filters:
                    unsupported_keys = ", ".join(sorted(result.unsupported_filters))
                    vector_hints.append(
                        f"지식베이스 검색에서 지원되지 않아 적용되지 않은 필터: {unsupported_keys}"
                    )
                if result.effective_filters and not result.documents:
                    vector_hints.append(
                        "지식베이스 필터 조건에 맞는 문서가 0건이라 문맥 없이 답변합니다."
                    )
```

---

## 3. 폴백(Fallback) 및 안전성 보장

| 시나리오 | 동작 과정 | 결과 및 보장 사항 |
| :--- | :--- | :--- |
| **Meilisearch 비활성 (`MEILI_ENABLED=False`)** | `retrieve_lexical_context`가 `[]` 반환 (`src/rag/engine.py:612-613`) | `vector_docs`가 `None`으로 유지되어 Vector 블록 진입. ChromaDB 30개 후보 풀 및 `_rerank_by_exact_title` 정상 실행 |
| **Meilisearch 서버 장애/타임아웃/예외** | 내부 `except Exception`에서 경고 로그 후 `[]` 반환 (`src/rag/engine.py:703-705`) | 예외가 밖으로 전파되지 않고 Vector 경로로 100% 무손실 폴백 |
| **Lexical 검색 결과 0건 또는 부분 일치만 존재** | `exact_lexical_matches`가 비어있어 `vector_docs` 미할당 | Vector 블록 진입. ChromaDB 임베딩 검색 수행하여 유사/거절 질의 처리 |
| **동명 공고 복수 적중 (차수/일시 상이)** | `exact_lexical_matches.sort(key=_extract_doc_sort_key, reverse=True)` | 공고일시, 개찰일시, 공고번호, 차수 순으로 결정적 최신 우선 정렬 보장 |
| **구간 계측 무결성** | Vector 생략 시 `vector_elapsed_ms = 0.0` 유지 | `timings["vector_ms"] == 0.0`, `lexical_ms >= 0.0`, 구간 계측 키 집합 불변 |

---

## 4. 단위 및 회귀 테스트 검증 결과

테스트는 실제 ChromaDB, Meilisearch, DB, 외부 LLM을 호출하지 않고 모킹(Mocking) 객체의 호출 여부 및 호출 횟수로 단언했습니다.

### 4.1 추가 및 보강된 테스트 목록

| 테스트 파일 | 테스트 함수 | 검증 항목 | 결과 |
| :--- | :--- | :--- | :--- |
| `tests/test_rag_lexical_channel.py` | `test_engine_bypasses_vector_when_lexical_exact_hit_found` | Lexical 정확 일치 시 `retrieve_semantic_context` 호출 0회 및 `vector_ms == 0.0` 단언 | 통과 |
| `tests/test_rag_lexical_channel.py` | `test_engine_promotes_lexical_exact_match_above_vector_results` | Lexical 정확 일치 문서의 `vector_docs` 채택 및 소스 메타데이터 확인 | 통과 |
| `tests/test_rag_lexical_channel.py` | `test_engine_fallback_when_meili_disabled` | `MEILI_ENABLED=False` 시 Vector 검색 정상 호출 (1회) 확인 | 통과 |
| `tests/test_rag_lexical_channel.py` | `test_engine_fallback_when_meili_raises_exception` | Meilisearch 예외 발생 시 크래시 없이 Vector 로 폴백 (1회) 확인 | 통과 |
| `tests/test_rag_lexical_channel.py` | `test_engine_fallback_when_meili_returns_zero_hits` | Meilisearch 0건 시 Vector 로 폴백 (1회) 확인 | 통과 |
| `tests/test_rag_lexical_channel.py` | `test_engine_fallback_when_meili_returns_only_partial_match` | 부분 일치만 있을 때 정확 일치 0건이므로 Vector 로 폴백 (1회) 확인 | 통과 |
| `tests/test_rag_lexical_channel.py` | `test_engine_calls_vector_when_plan_use_lexical_is_false` | `plan.use_lexical=False`인 일반 질의에서 Vector 정상 호출 확인 | 통과 |
| `tests/test_rag_lexical_channel.py` | `test_engine_multiple_exact_matches_sorted_by_sort_key_and_bypasses_vector` | 복수 정확 일치 시 `_extract_doc_sort_key` 내림차순 정렬 및 Vector 바이패스 확인 | 통과 |
| `tests/test_rag_segment_metrics.py` | `test_segment_metrics_vector_bypass_when_lexical_exact_hit` | 플래그 ON 상태에서 Vector 바이패스 시 `vector_ms == 0.0`, `lexical_ms >= 0.0`, 키 집합 10개 완비 확인 | 통과 |

### 4.2 전체 검증 명령어 실행 요약

```bash
# 1. RAG 단위 및 세그먼트 메트릭 테스트
uv run pytest tests/test_rag_lexical_channel.py tests/test_rag_segment_metrics.py -q
# 결과: 26 passed

# 2. 전체 회귀 테스트 스위트 (data_assets 제외)
uv run pytest tests/ -q -m 'not data_assets'
# 결과: 2523 passed, 6 skipped, 3 deselected

# 3. 린터 및 타입 정적 분석
uv run ruff check src/ scripts/ tests/
uv run mypy src/
# 결과: All checks passed / Success: no issues found in 89 source files

# 4. 에이전트 규칙 및 문서 링크 검증
python3 scripts/validate_agent_rules.py --quiet
uv run python scripts/validate_doc_links.py
# 결과: 검증 통과 (12/12 건, 379개 문서 링크 유효)
```

---

## 5. 미확인 사항 및 향후 과제

본 Task는 정본 사양(Capsule)에 따라 순수 로직 변경과 모킹 기반 단위/회귀 테스트만을 수행하였습니다.

1. **서비스 환경 실측 레이턴시 벤치마크 (별도 Task 필요)**:
   - 실제 Docker 컨테이너(Meilisearch, MySQL, Redis, ChromaDB)를 기동하고 네트워크 부하가 없는 조용한 기계에서 32문항 평가 픽스처 전수 P50/P95 레이턴시 측정 필요.
2. **신규 패키지 추가 없음**:
   - `pyproject.toml` 의존성 변경 없이 표준 라이브러리 및 기존 모듈만 사용함.
3. **데이터 무손실 원칙 준수**:
   - DB 테이블/컬럼/데이터 및 벡터 저장소 포맷 일체 변경 없음.

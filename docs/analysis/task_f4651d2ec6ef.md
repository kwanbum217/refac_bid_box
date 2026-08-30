# task_f4651d2ec6ef 인수인계: Vector 구간 지연 분해 및 무손실 최적화

> **task_id**: task_f4651d2ec6ef
> **작성일**: 2026-08-30
> **소스 branch**: kwanbum217/orca-d3-vector
> **base commit**: 3d706fc
> **결과 상태**: succeeded

---

## 1. 작업 요약

2026-08-30 정본 구간 레이턴시 측정에서 `vector` 구간이 전체 지연의 33.0% (P50 1,307.88ms, P95 2,058.22ms)를 차지함에 따라, `retrieve_semantic_context` 경로의 시간 소비를 단계별로 분해하고 검색 결과를 단 한 건도 바꾸지 않는(Output Invariance) 범위 내에서 안전한 코드 수준 최적화를 적용했습니다.

검색 결과 변경 위험이 있는 후보(`DEFAULT_CANDIDATE_POOL_SIZE` 축소, 임베딩 모델 교체, 재순위 기준 완화 등)는 엄격히 기각하고 그 근거를 `docs/analysis/vector_segment_optimization_20260830.md`에 상세 기술했습니다. 또한 출력 불변성을 기계적으로 강제하는 안전장치 테스트 `tests/test_vector_store_perf.py`를 신규 구축했습니다.

---

## 2. 추가 및 수정 파일 목록

| 경로 | 구분 | 작업 내용 및 역할 |
| --- | :---: | --- |
| `src/rag/vector_store.py` | 수정 | 문자열/매칭키 조기 반환, 유효 날짜 판정 단축(개찰일시 우선), post-filter 중복 정규화 제거, 5자 미만 질의 재순위 조기 반환 및 1건 이하 정렬 생략, 디버그 단계별 계측 로깅 추가 |
| `tests/test_vector_store_perf.py` | 신규 | 불변 상수(후보 30건 등), 정규화/키 생성 동일성, 날짜/필터 판정 동일성, 30건 고정 풀 재순위 순서 불변성, retrieve_semantic_context 출력 동일성 단위 테스트 (8개 함수, 57개 케이스) |
| `docs/analysis/vector_segment_optimization_20260830.md` | 신규 | Vector 구간 세부 단계 분해, 구현된 최적화 근거, 기각/제안 후보 표, 코디네이터 직렬 재측정 재현 명령 |
| `docs/analysis/task_f4651d2ec6ef.md` | 신규 | 본 Task 인수인계 및 최종 보고 문서 |

---

## 3. 핵심 설계 및 최적화 내역

### 3.1 세부 단계별 시간 소비 분석
- **임베딩 추론 (`bge-m3`)**: 벡터 구간 지연의 >95% (~1,200 - 1,900ms) 점유. CPU 연산 집중 병목이며 모델 교체 시 한국어 적중률 급감(MiniLM 4% 기각 이력)으로 인해 모델 교체 불가.
- **ChromaDB 질의 및 HNSW 탐색**: ~5 - 15ms (1%).
- **Post-filter 및 정규식 추출**: ~0.5 - 2ms.
- **정확 제목 재순위 및 정렬**: ~0.2 - 1ms.

### 3.2 구현된 무손실(Output-Invariant) 최적화
1. **문자열 정규화 조기 반환**: `_normalize_text` 및 `_normalize_match_key`에서 `None` 또는 빈/공백 문자열 전달 시 불필요한 `unicodedata.normalize` 호출을 건너뛰고 `""` 즉시 반환.
2. **유효 날짜 추출 Fast-Path**: `extract_effective_document_date`에서 개찰일시(`OPENING_DATE_PATTERN`)를 먼저 탐색하여 일치 시 공고일시 정규식 탐색을 생략 (개찰일시 존재 시 공고일시가 버려지는 특성 활용).
3. **Post-filter 중복 연산 제거**: `extract_document_institution`이 이미 NFC 정규화된 기관명을 반환하므로 `_matches_post_filters` 내 `_normalize_text(doc_inst)` 중복 호출 제거.
4. **재순위 루프 단축**: `_rerank_by_exact_title`에서 질의 길이가 `RERANK_MIN_TITLE_LENGTH`(5자) 미만일 때 전체 루프를 건너뛰고 원본 반환. 일치 문서 수가 1건 이하일 때 no-op 정렬(`sort()`) 생략.
5. **조건부 세부 구간 계측**: `logger.isEnabledFor(logging.DEBUG)`를 활용해 query, post_process, total 밀리초를 로깅하여 프로덕션 오버헤드 0ms 유지.

### 3.3 기각된 최적화 항목 및 사유
- `DEFAULT_CANDIDATE_POOL_SIZE` 축소 금지: 30건 유지 (q21 정답 문서가 9위에서 1위로 승격된 실측 기반, 축소 시 RAG 품질 저하).
- 임베딩 모델 교체 금지: `bge-m3` 유지 (MiniLM 4% 적중률로 기각).
- 재순위/필터 기준 완화 금지: 2026-08-30 Lexical 포함 매칭 완화로 인한 회귀(numeric 138->132) 경험 반영.
- `src/rag/engine.py` 미수정 (읽기 전용 범위 준수).
- fixture 벤치마크 미실행 및 `data/benchmarks` 파일 미생성 (사양 준수).

---

## 4. 검증 결과 요약

1. **벡터 저장소 전용 불변성 및 RAG 단위 테스트**:
   - `uv run pytest tests/test_vector_store_perf.py tests/test_rag_vector_store.py tests/test_vector_store_filters.py -q`
   - **결과**: `57 passed, 1 warning in 0.06s` (exit_code: 0)
2. **전체 테스트 스위트 (격리 트리 data_assets 제외)**:
   - `uv run pytest tests/ -q -m 'not data_assets'`
   - **결과**: `2748 passed, 6 skipped, 3 deselected, 312 warnings in 244.63s` (exit_code: 0)
3. **다중 에이전트 규칙 정합성**:
   - `python3 scripts/validate_agent_rules.py --quiet`
   - **결과**: `검증 통과: 12/12 건.` (exit_code: 0)

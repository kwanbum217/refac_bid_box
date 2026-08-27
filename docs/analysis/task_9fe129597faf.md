# Task task_9fe129597faf 분석 및 구현 보고서

> **작성일**: 2026-08-27
> **작업자**: Orca Worker (Builder)
> **Task ID**: task_9fe129597faf
> **Run ID**: run_85b91a35137a

---

## 1. 작업 개요

### 1.1 배경 및 문제 정의
- blind fixture v2 측정에서 q21(2026년 조림지 풀베기사업 2차(동부지구))은 벡터 검색 결과 10위에 위치하여 기존 top_k=5 설정 하에서 최종 탈락하는 문제가 있었습니다.
- 이는 조달 공고의 특성상 동일 사업이 지역별로 다수 분할 발주되어 동부지구, 영암지구, 산동용방2지구 등 고유명사만 다른 근사 중복 문서가 밀집 임베딩 공간에서 유사한 거리를 갖기 때문입니다.

### 1.2 목표
1. ChromaDB 후보 검색 수를 max(top_k * multiplier, 30) 수준으로 확보하여 10위권에 위치한 정확 일치 문서를 후보군에 포함.
2. 질의(semantic_query)와 문서 본문의 [공고명] 간 공백 및 다양한 괄호류 차이를 정규화하여 **정확 일치(Exact Match)** 하는 문서를 최상위로 안정적 재순위.
3. 부분 문자열 오탐으로 인한 일반 질의나 유사 지구 공고의 부당한 승격 방지 (음성 케이스 보장).
4. 기존 메타데이터 where 절 및 post-filter(institution_name, date_from, date_to)의 fail-closed 정책과 프로비넌스(provenance) 완전 보존.

---

## 2. 주요 변경 사항

### 2.1 src/rag/vector_store.py
1. **후보 풀 상수 추가 및 검색 크기 산출 로직 개선**:
   - DEFAULT_CANDIDATE_POOL_SIZE = 30 정의.
   - query_top_k = max(base_fetch_k, DEFAULT_CANDIDATE_POOL_SIZE) 산출을 통해 필터 유무와 관계없이 최소 30건 이상의 후보를 확보.
2. **공고명 추출 함수 구현 (extract_document_title)**:
   - TITLE_PATTERN = re.compile(r"\[공고명\]\s*([^\r\n]+)")를 통해 본문에서 공고명을 추출하고 NFC 정규화.
3. **정확 일치 비교 키 정규화 함수 (_normalize_match_key)**:
   - NFC 정규화, 소문자 변환, 공백(\s) 및 각종 괄호류((), [], {}, （）, ［］, ｛｝, 【】, 〔〕, 〈〉, 《》, 「」, 『』)를 제거하여 문자열 차이를 해소.
4. **정확 일치 재순위 함수 (_rerank_by_exact_title)**:
   - 정규화된 비교 키가 완전히 일치하는 문서를 리스트 앞쪽으로 배치하고, 그 외 문서는 기존 상대적 거리 순서를 그대로 유지(stable sort).
5. **검색 파이프라인 통합 (retrieve_semantic_context)**:
   - post-filter를 먼저 적용하여 fail-closed 원칙을 만족한 문서들에 대해 정확 일치 재순위를 수행한 후 최종 plan.top_k로 슬라이싱하여 반환.

### 2.2 tests/test_vector_store_filters.py
- 기존 테스트의 후보 풀 크기(DEFAULT_CANDIDATE_POOL_SIZE = 30) 검증 갱신.
- test_extract_document_title: 공고명 추출 기능 단위 테스트.
- test_normalize_match_key: 공백 및 전각/반각 괄호류 정규화 단위 테스트.
- test_rerank_by_exact_title_q21_promotion: q21 10위 문서가 1위로 승격되는지 검증.
- test_rerank_by_exact_title_negative_cases_no_false_promotion: 일반 질의(부분 문자열), 축약 질의 시 불필요한 승격이 발생하지 않는지 음성 검증.
- test_retrieve_semantic_context_q21_end_to_end_in_top5: q21 질의 시 top-5에 정답 문서가 정상 포함되는 통합 검증.
- test_retrieve_semantic_context_post_filter_fail_closed_with_exact_title: 정확 일치 공고명이더라도 post-filter 불만족 시 fail-closed 정책에 따라 제외됨을 검증.

---

## 3. 검증 체크리스트

| ID | 검토 항목 | 결과 |
|---|---|---|
| R1 | 정확 제목 문서가 비슷한 지역명 문서보다 우선되는가? | 통과 (q21 단위/통합 테스트 완료) |
| R2 | 부분 문자열 또는 일반 질의가 부당하게 재순위되는가? | 통과 (음성 테스트 완료) |
| R3 | 기존 post-filter와 fail-closed 의미가 바뀌었는가? | 통과 (기존 및 추가 fail-closed 테스트 완료) |
| R4 | 새 의존성이나 DB 스키마 변경이 있는가? | 없음 (표준 라이브러리 re, unicodedata만 사용) |

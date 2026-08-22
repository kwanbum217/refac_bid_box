# 단발 질의 API RAG 준비 및 LLM 생성 시간 분리 계측 보고서

> **작성일**: 2026-08-22
> **대상 모듈**: `src/rag/engine.py`, `tests/test_rag_engine.py`
> **목적**: 단발 질의 API(`POST /api/v1/chatbot/query`) 및 하이브리드 RAG 엔진(`HybridRAGEngine`)의 응답 계약을 보존하면서, 내부 RAG 컨텍스트 준비와 LLM 생성 및 후처리 구간을 `time.perf_counter` 기반 구조화 로그로 정밀 분리 계측하고 검증합니다.

---

## 1. 개요 및 계측 배경

기존 단발 질의 API는 전체 P95 레이턴시(6.29초 ~ 10.26초)와 SSE 스트리밍의 완료 시간만 측정되었을 뿐, 내부의 RAG 컨텍스트 준비(SQL, 벡터 검색, KB 상태, 프롬프트 조립)와 LLM 백엔드 생성(`backend.generate`), Answer Guard 및 후처리 구간의 개별 소요 시간과 내부 비율은 분리 계측되지 않았습니다.

본 작업에서는 외부 API 계약(`AnswerBundle`, `ChatbotQueryResponse`) 및 기존 비동기/스트리밍 동작을 100% 보존하면서, 각 처리 단계의 소요 시간을 밀리초(`ms`) 단위로 정밀 계측하여 구조화 로그(`rag_engine_latency`)를 남기도록 개선하였습니다.

---

## 2. 세부 구현 내용

### 2.1 `PreparedContext(tuple)` 도입을 통한 하위 호환성 보존

`_prepare_context`의 반환값을 기존 7개 튜플 `(plan, structured_data, vector_docs, kb_status, provenance, context_text, messages)`과 완전히 호환되도록 `tuple`을 상속하는 `PreparedContext` 클래스로 래핑하였습니다.

- **기존 호출부 및 테스트 호환성**: 7개 변수 언패킹(`a, b, c, d, e, f, g = prepared`) 및 인덱스 접근이 동일하게 동작합니다.
- **계측 메타데이터 전달**: `prepared.timings` 속성을 통해 `_prepare_context` 내부에서 실측된 세부 구간 레이턴시 딕셔너리를 호출자에게 전달합니다.

### 2.2 `_prepare_context` 세부 구간 분리 계측

`_prepare_context` 내 각 단계의 시작과 종료를 `time.perf_counter()`로 측정하여 다음 구간을 분리하였습니다:

| 계측 항목 | 키 이름 | 설명 및 비고 |
| :--- | :--- | :--- |
| 질의 계획 수립 | `plan_ms` | `build_retrieval_plan(user_query)` 키워드 파싱 및 규칙 매칭 소요 시간 |
| 정형 데이터 조회 | `sql_ms` | `retrieve_structured_data(db, plan)` MySQL 통계/목록 집계 시간 (미실행 시 `0.0`) |
| 지식베이스 벡터 검색 | `vector_ms` | `retrieve_semantic_context(plan)` ChromaDB 임베딩 검색 시간 (미실행 시 `0.0`) |
| KB 상태 메타데이터 | `kb_status_ms` | `get_latest_kb_status_payload(db)` 최신 색인 상태 조회 시간 (미실행 시 `0.0`) |
| 컨텍스트/프롬프트 조립 | `assembly_ms` | 근거 항목, 힌트, Provenance, 컨텍스트 텍스트 및 메시지 구성 시간 |
| 전체 컨텍스트 준비 | `prepare_total_ms` | `_prepare_context` 진입부터 반환까지의 총 소요 시간 |

### 2.3 `get_answer_sync` 파이프라인 분리 계측 및 구조화 로깅

`get_answer_sync` 진입부터 답변 반환까지의 전체 수명 주기를 4가지 분기 경로별로 분리 계측하고 단일 구조화 로그(`rag_engine_latency`)를 발행합니다:

1. **정상 LLM 생성 경로 (`status="success"`)**:
   - `prepare_ms`: 컨텍스트 준비 총 시간
   - `llm_ms`: `backend.generate(SYSTEM_PROMPT, messages)` LLM 네트워크 I/O 및 토큰 생성 시간
   - `guard_ms`: `_apply_answer_guard` 및 `_build_source_citation_from_context` 후처리 시간
   - `total_ms`: `get_answer_sync` 전체 실행 시간 (`bundle.latency_ms`와 일치)
2. **직접 결과 목록 직답 경로 (`status="direct_result_list"`)**:
   - `llm_ms=0.0`: LLM을 호출하지 않고 SQL 결과로 즉시 포맷팅
   - `guard_ms`: 출처 인용 접미사 조립 시간
3. **LLM 백엔드 미가용 폴백 경로 (`status="fallback_no_backend"`)**:
   - `llm_ms=0.0`: 백엔드 부재 시 룰 기반 폴백 답변 생성
   - `backend="fallback"`
4. **LLM 백엔드 호출 예외 폴백 경로 (`status="fallback_error"`)**:
   - `llm_ms`: 예외 발생 전까지 대기한 시간
   - `logger.warning`으로 오류 원인과 `trace_id`를 기록하고 폴백 답변 반환

### 2.4 보안 및 프라이버시 보호

- 질의 원문(`user_query`), 검색된 문서 본문(`documents`), 사용자 개인정보는 로그 메시지 및 `extra` 딕셔너리에 일절 포함되지 않습니다.
- 오직 고유 식별자(`trace_id`), 라우팅 사유(`route_reason`), 플래그(`use_sql`, `use_vector`, `use_kb_status`), 백엔드명(`backend`), 밀리초 단위 수치(`ms`)만 기록됩니다.

---

## 3. 구조화 로그 포맷 사양

`src.rag.engine` 로거를 통해 다음과 같은 표준 형식으로 기록됩니다:

```text
rag_engine_latency: trace_id={trace_id} status={status} route={route} use_sql={bool} use_vector={bool} use_kb={bool} plan_ms={float} sql_ms={float} vector_ms={float} kb_ms={float} assembly_ms={float} prepare_ms={float} llm_ms={float} guard_ms={float} total_ms={float} backend={backend}
```

- 파이썬 표준 `logging`의 `extra` 딕셔너리에도 동일한 키-값 쌍이 주입되어 JSON 로거 및 APM 수집기와 연동 가능합니다.

---

## 4. 검증 및 테스트 결과

### 4.1 단위 테스트 추가 내역 (`tests/test_rag_engine.py`)

| 테스트 함수명 | 검증 내용 | 결과 |
| :--- | :--- | :---: |
| `test_prepare_context_returns_prepared_context_with_timings` | `PreparedContext` 인스턴스, 7요소 언패킹, 6개 계측 키 유효성 검증 | 통과 |
| `test_prepare_context_timings_respects_skipped_stages` | `tool_context` 제공 시 미실행 구간(`sql_ms`, `vector_ms`, `kb_status_ms`) `0.0` 검증 | 통과 |
| `test_get_answer_sync_logs_latency_success_path` | 정상 생성 시 `status=success`, `llm_ms`, `guard_ms` 포함 및 구조화 로그 포맷 검증 | 통과 |
| `test_get_answer_sync_logs_latency_direct_result_list` | 직답 목록 생성 시 `status=direct_result_list`, `llm_ms=0.00`, `backend=none` 검증 | 통과 |
| `test_get_answer_sync_logs_latency_fallback_no_backend` | 백엔드 부재 시 `status=fallback_no_backend`, `llm_ms=0.00`, `backend=fallback` 검증 | 통과 |
| `test_get_answer_sync_logs_latency_fallback_on_exception` | LLM 예외 발생 시 `status=fallback_error`, 경고 로그 및 폴백 번들 반환 검증 | 통과 |
| `test_latency_logs_do_not_leak_user_query_or_documents` | 질의 문자열 및 비공개 데이터가 로그에 누출되지 않음을 전수 검증 | 통과 |

### 4.2 전체 테스트 및 규칙 검증 결과

1. **`tests/test_rag_engine.py`**: 19건 전체 통과 (0.35초)
2. **비데이터 자산 전체 테스트 (`pytest tests/ -q -m 'not data_assets'`)**: **1,688 passed**, 6 skipped, 3 deselected, 0 failed
3. **에이전트 규칙 검증 (`python scripts/validate_agent_rules.py --quiet`)**: **12/12 건 전량 통과**

---

## 5. 결론 및 기대 효과

1. **응답 계약 100% 보존**: `AnswerBundle` 및 `POST /api/v1/chatbot/query` API 응답 스키마 변경 없이 무손실로 계측 체계를 확립하였습니다.
2. **병목 구간 식별 가능**: 향후 단발 질의 API 호출 시 로그 분석을 통해 P95 지연의 주원인이 RAG 데이터 조회(SQL/ChromaDB)인지, LLM 토큰 생성(`backend.generate`)인지 즉시 분리 판단할 수 있습니다.

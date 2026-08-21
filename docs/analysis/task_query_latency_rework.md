# Task 완료 요약: 단발 질의 API 레이턴시 구간 분해 및 재작업 보고서

> **작성일**: 2026-08-22
> **Task ID**: `task_query_latency_rework`
> **역할**: Investigator (단발 질의 지연 분석 재작업)
> **대상 커밋**: `1308223`
> **정본 분석 문서**: `docs/analysis/query_latency_breakdown.md`

---

## 1. 재작업 배경 및 목적

1차 산출물(`query_latency_breakdown.md`)에 대해 제기된 결함을 보완하고 근거 수준을 명확히 분리하기 위해 재작업을 수행했습니다.

### 주요 보완 사항
1. **절대경로 및 파일 스킴 링크 제거**: 모든 로컬 절대경로 및 파일 스킴 URI 표기를 프로젝트 루트 기준 상대경로 표기(예: `src/app/api/v1/chatbot.py:544-553`)로 일원화했습니다.
2. **미계측 단계별 시간 단정 제거**: RAG 컨텍스트 준비(1~2초) 및 LLM 생성(3~8초) 등 분리 계측되지 않은 구간의 소요 시간 단정을 삭제하고, 실측 사실과 미계측 추정 영역을 명확히 구분했습니다.
3. **관측 사실과 원인 해석 분리**: SSE 완료 대역(P95 6.37~7.65초)과 단발 질의 완료 대역(P95 6.29~10.26초)의 중첩 관측과 "동일 작업량/추가 병목 부재"라는 해석을 엄격히 분리하여 기술했습니다.
4. **호출부 목적에 대한 근거 수준 표기**: 프론트엔드의 SSE 100% 호출 사실과 단발 엔드포인트의 summary("단발 질의 (간이 계약)") 계약 사실을 명시하고, 외부 클라이언트(cURL/Webhook 등) 목적은 코드에 없는 일반적 용례 추정임을 명시했습니다.
5. **대상 커밋 기준 정정**: 분석 대상 기준 커밋을 `1308223`으로 바로잡았습니다.
6. **산출물 정리**: 기존 `task_query_latency_investigation.md`를 제거하고 본 재작업 요약 문서(`task_query_latency_rework.md`)로 대체했습니다.

---

## 2. 핵심 분석 결과 요약

1. **코드 경로 매핑**:
   - `POST /api/v1/chatbot/query` 요청은 FastAPI 라우팅 -> `rag_engine.get_answer` (`asyncio.to_thread`) -> `_prepare_context` (SQL + ChromaDB 검색) -> `backend.generate` (LLM 동기 생성) -> `_apply_answer_guard` 및 응답 직렬화 순서로 실행됩니다.
2. **실측 데이터 (확인된 사실)**:
   - 단발 질의 종합 P95: **6.29초 ~ 10.26초** (P50: 4.13초 ~ 6.79초, `data/benchmarks/blocking_io_p95/`)
   - SSE 스트리밍 P95: `first_stage_ms` **3.4~11.0ms**, `first_token_ms` **1,263.4~2,290.9ms**, `final_ms` **6,365.9~7,654.5ms**
3. **미계측 추정 영역**:
   - 단발 질의 내부의 RAG 준비(MySQL SQL 조회, ChromaDB 벡터 검색)와 LLM 생성(`backend.generate`)의 개별 소요 시간은 현재 분리 계측된 데이터가 없으며, 정밀한 원인 규명을 위해서는 개별 타이머 계측이 필요합니다.
4. **호출부 전수 조사**:
   - **프론트엔드 (`frontend/src/App.tsx:215`)**: 웹 UI 챗봇은 100% SSE 스트리밍(`POST /api/v1/chatbot/chat/stream`)만 사용합니다.
   - **백엔드 내부 (`src/`)**: 단발 질의를 내부 호출하는 코드는 0건입니다.
   - **테스트/벤치마크 (`tests/`, `scripts/`)**: 엔드포인트 계약 보존 검증 및 비교 벤치마크 용도로만 참조됩니다.

---

## 3. 의사결정 선택지 요약 (근거 제공용)

- **선택지 A (현행 유지 및 목표 수립)**: 비스트리밍 간이 클라이언트 계약 보존을 위해 P95 목표를 현실적 수치(12.0~15.0초)로 별도 정의.
- **선택지 B (SSE 전면 유도)**: API 문서에 `/chat/stream`을 정본으로 표준화하고 `/query`를 Deprecated 예고 처리.
- **선택지 C (RAG 캐싱 도입)**: 단발 질의 경로에 Redis 캐시를 적용하여 반복 질의의 P95 단축.

상세 내용은 `docs/analysis/query_latency_breakdown.md`를 참조하십시오.

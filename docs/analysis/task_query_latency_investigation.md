# Task 완료 요약: 단발 질의 API 레이턴시 구간 분해 및 분석

> **작성일**: 2026-08-22
> **Task ID**: `task_query_latency_investigation`
> **역할**: Investigator (읽기 전용 조사)
> **정본 분석 문서**: [`docs/analysis/query_latency_breakdown.md`](file:///Users/kwanbum/orca/workspaces/refac_bid_box/handoff-query-latency/docs/analysis/query_latency_breakdown.md)

---

## 1. 과업 개요 및 목적

단발 질의 API(`POST /api/v1/chatbot/query`)의 6.29~10.26초 P95 레이턴시가 발생하는 원인을 코드 실행 경로 단위로 분해하고, SSE 스트리밍 경로와의 구조적 차이 및 호출부 현황을 분석하여 설계 목표 수립 또는 SSE 유도 판단을 위한 객관적 근거를 정리했습니다. 본 작업은 읽기 전용 조사로서 제품 코드 변경 및 자체 결정 없이 근거와 선택지만을 도출했습니다.

---

## 2. 핵심 분석 결과 요약

1. **코드 경로 분해 및 소요 시간**:
   - **1단계**: FastAPI 요청 라우팅 및 `asyncio.to_thread` 오프로드 (수 ms 미만)
   - **2단계**: RAG 컨텍스트 준비(`_prepare_context`: MySQL DB 조회 + ChromaDB 벡터 검색) -> **약 1.0~2.2초** 소요
   - **3단계**: LLM 백엔드 블로킹 생성(`backend.generate` -> 토큰 전체 생성 완료 대기) -> **약 3.0~8.0초** 소요
   - **4단계**: Answer Guard 및 출처 인용 후처리, JSON 응답 직렬화 (수 ms 미만)
2. **SSE 스트리밍 경로와의 비교**:
   - SSE 완료 시간(P95 6.37~7.65초)과 단발 질의 완료 시간(P95 6.29~10.26초)은 물리적 총 작업량이 거의 동일합니다.
   - 단발 질의의 체감 지연은 백엔드 추가 병목이 아니라 **비스트리밍 블로킹 방식으로 인해 전체 완료 시점까지 무응답 상태로 대기**하기 때문입니다.
3. **호출부 전수 조사 결과**:
   - **프론트엔드(`frontend/src/App.tsx`)**: 이미 100% SSE 스트리밍(`POST /api/v1/chatbot/chat/stream`)만 사용하고 있으며, 단발 질의를 호출하는 UI 코드는 0건입니다.
   - **단발 질의(`POST /api/v1/chatbot/query`)**: 브라우저 UI가 아닌 cURL/배치 스크립트 등 비스트리밍 간이 클라이언트를 위한 경량 계약입니다.

---

## 3. 의사결정 선택지 요약

- **선택지 A (현행 유지 및 목표 수립)**: 비스트리밍 간이 클라이언트 호환성을 위해 P95 목표를 현실적 수치(12~15초)로 별도 정의.
- **선택지 B (SSE 전면 유도)**: API 문서에 `/chat/stream`을 정본으로 표준화하고 `/query`를 Deprecated 예고 처리.
- **선택지 C (RAG 캐싱 도입)**: 단발 질의에 Redis RAG 결과 캐시를 적용하여 반복 질의에 대한 P95 대폭 단축.

상세 분석 내용은 [`docs/analysis/query_latency_breakdown.md`](file:///Users/kwanbum/orca/workspaces/refac_bid_box/handoff-query-latency/docs/analysis/query_latency_breakdown.md)를 참조하십시오.

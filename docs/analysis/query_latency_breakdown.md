# 단발 질의 API 레이턴시 구간 분해 및 분석 보고서

> **작성일**: 2026-08-22
> **대상 엔드포인트**: `POST /api/v1/chatbot/query` (단발 질의 간이 계약)
> **비교 엔드포인트**: `POST /api/v1/chatbot/chat/stream` (정본 SSE 스트리밍)
> **대상 커밋**: `e219d9cc537e9d88b6720a62d345e97c65ded9e5`
> **목적**: 단발 질의 API의 P95(6.29~10.26초) 발생 구간을 코드 경로로 분해하고, SSE 경로와의 구조적 차이 및 호출부 현황을 분석하여 설계 목표 수립 또는 경로 유도 판단을 위한 근거를 제공합니다. (결정 제외, 근거 제출 전용)

---

## 1. 단발 질의 엔드포인트 요청 처리 경로 코드 분해

`POST /api/v1/chatbot/query` 호출 시 실행되는 전체 처리 경로는 아래 4단계로 구성됩니다.

### 1.1 단계별 코드 매핑

| 단계 | 실행 함수 및 위치 | 주요 작업 내용 | I/O 및 연산 유형 |
| :---: | :--- | :--- | :--- |
| **1단계** | `query_chatbot`<br>([`src/app/api/v1/chatbot.py:544-553`](file:///Users/kwanbum/orca/workspaces/refac_bid_box/handoff-query-latency/src/app/api/v1/chatbot.py#L544-L553)) | 요청 수신, `rag_engine.get_answer` 비동기 호출, Pydantic 응답 직렬화 | FastAPI ASGI 라우팅, CPU 직렬화 |
| **2단계** | `HybridRAGEngine._prepare_context`<br>([`src/rag/engine.py:196-248`](file:///Users/kwanbum/orca/workspaces/refac_bid_box/handoff-query-latency/src/rag/engine.py#L196-L248)) | 1) 질의 계획 수립 (`build_retrieval_plan`)<br>2) 정형 DB 통계/공고 조회 (`retrieve_structured_data`)<br>3) ChromaDB 지식베이스 벡터 검색 (`retrieve_semantic_context`)<br>4) 검색 컨텍스트 텍스트 및 프롬프트 메시지 조립 | CPU 키워드 파싱,<br>MySQL 동기 SQL I/O,<br>ChromaDB 임베딩 연산 및 디스크 I/O |
| **3단계** | `HybridRAGEngine.get_answer_sync`<br>([`src/rag/engine.py:276-334`](file:///Users/kwanbum/orca/workspaces/refac_bid_box/handoff-query-latency/src/rag/engine.py#L276-L334)) | 1) 직답 목록 생성 여부 판정 (`_build_result_list_answer`)<br>2) LLM 백엔드 전체 생성 블로킹 호출 (`backend.generate`)<br>3) Answer Guard 교정 (`_apply_answer_guard`)<br>4) 출처 인용 문구 조립 (`_build_source_citation_from_context`) | 외부 LLM API/Ollama 네트워크 I/O 및 토큰 생성 대기 (블로킹),<br>CPU 문자열 정규화 |
| **4단계** | `HybridRAGEngine.get_answer`<br>([`src/rag/engine.py:336-344`](file:///Users/kwanbum/orca/workspaces/refac_bid_box/handoff-query-latency/src/rag/engine.py#L336-L344)) | 2~3단계 전체 동기 실행을 `asyncio.to_thread`로 워커 스레드 풀에 위임 | 스레드 풀 스케줄링 오버헤드 |

---

## 2. 단계별 소요 시간 분석 (확인된 사실 vs 추정)

### 2.1 확인된 사실 (Ground Truth 및 실측 데이터)

1. **단발 질의 API 전체 레이턴시 실측치** (`data/benchmarks/blocking_io_p95/run1.json` ~ `run3.json`):
   - 1회차: P50 = 6,792.5ms (6.79s) / P95 = 10,257.0ms (10.26s) / 오류 0건
   - 2회차: P50 = 4,132.2ms (4.13s) / P95 = 6,285.3ms (6.29s) / 오류 0건
   - 3회차: P50 = 4,885.2ms (4.89s) / P95 = 8,090.8ms (8.09s) / 오류 0건
   - 종합 P95 대역: **6.29초 ~ 10.26초** (P50 대역: 4.13초 ~ 6.79초)
2. **SSE 스트리밍 경로의 단계별 분해 실측치**:
   - `first_stage_ms` (FastAPI 진입 및 첫 stage 이벤트 전송): P95 = **3.4ms ~ 11.0ms**
   - `first_token_ms` (FastAPI 진입 -> RAG 컨텍스트 준비 -> LLM 첫 토큰 도착): P95 = **1,263.4ms ~ 2,290.9ms** (P50 = 772.2ms ~ 1,228.2ms)
   - `final_ms` (전체 스트리밍 완료): P95 = **6,365.9ms ~ 7,654.5ms** (P50 = 3,641.2ms ~ 4,419.7ms)
3. **코드상 지연 요인 확인**:
   - 단발 질의 API 내부에는 별도의 인위적인 슬립, 큐 대기, 재시도 루프, 불필요한 직렬화 지연이 없습니다.
   - 단발 질의의 전체 소요 시간(P95 6.29~10.26초)은 SSE 완료 시간(P95 6.37~7.65초)과 본질적으로 같은 작업량(RAG 검색 + LLM 전체 토큰 생성)을 수행하는 시간입니다.

### 2.2 추정인 것 (현재 세부 계측 부재 구간)

1. **RAG 컨텍스트 준비 구간(약 1.0~2.0초) 내부의 세부 비율**:
   - MySQL 정형 DB 조회(`retrieve_structured_data`)와 ChromaDB 벡터 검색(`retrieve_semantic_context`)이 각각 몇 ms를 소비하는지는 현재 코드상 분리 계측되지 않아 정확한 비율은 추정입니다.
2. **LLM 생성 구간(약 3.0~8.0초) 내부의 세부 비율**:
   - `backend.generate()` 블로킹 호출 시 백엔드 네트워크 연결 왕복 시간(RTT)과 LLM 추론 엔진의 토큰 생성 순수 처리 시간 간의 비율은 추정입니다.

### 2.3 필요 계측 제안

단발 질의 내부 구간의 정밀 분할이 필요한 경우 다음 계측을 코드에 삽입할 수 있습니다:
- `_prepare_context` 내 `sql_elapsed_ms` (MySQL 조회 시간) 및 `vector_elapsed_ms` (ChromaDB 임베딩/조회 시간) 측정
- `backend.generate` 전후 `llm_elapsed_ms` (LLM 생성 소요 시간) 측정
- 측정값을 `AnswerBundle` 및 서버 로그/메트릭에 기록

---

## 3. SSE 스트리밍 경로와의 구조적 차이 비교

| 비교 항목 | 단발 질의 API (`POST /api/v1/chatbot/query`) | 정본 SSE 스트리밍 (`POST /api/v1/chatbot/chat/stream`) |
| :--- | :--- | :--- |
| **통신 프로토콜** | HTTP POST 단일 JSON 응답 | HTTP POST `text/event-stream` (SSE) |
| **사전 분석 단계** | 플래너 및 세션 로드 생략, `_prepare_context` 직행 | 세션 로드, 보안 키워드 검사, 플래너 분석, 액션 도구 실행 |
| **RAG 검색 방식** | SQL 조회 + ChromaDB 벡터 검색 (동일) | SQL 조회 + ChromaDB 벡터 검색 (동일) |
| **LLM 호출 방식** | `backend.generate` (완료 시까지 동기 블로킹 대기) | `backend.stream_generate` (토큰 단위 비동기 `yield`) |
| **체감 응답 시점** | **6.29 ~ 10.26초 동안 무응답 대기** 후 일괄 수신 | **3~11ms(stage)** 즉각 반응, **1.26~2.29초(첫 토큰)** 출력 시작 |
| **대화 이력 저장** | 저장 안 함 (단발성 질의 계약) | `remember_chat_interaction` (DB 대화 세션 기록) |
| **전체 완료 P95** | **6.29초 ~ 10.26초** | **6.37초 ~ 7.65초** |

### 3.1 구조적 차이 결론

- 두 경로의 **총 작업량과 물리적 처리 시간(약 6~10초)은 거의 동일**합니다.
- 단발 질의가 느리게 느껴지는 원인은 백엔드에 병목이 추가되어서가 아니라, **LLM의 긴 생성 시간(수 초) 동안 클라이언트가 첫 바이트/토큰을 받지 못하고 블로킹되기 때문**입니다.

---

## 4. 호출부 전수 조사 및 SSE 유도 가능성 판단 근거

### 4.1 호출부 전수 조사 결과

1. **프론트엔드 (`frontend/src/`)**:
   - `frontend/src/App.tsx:215`: 챗봇 탭의 모든 사용자 대화는 **전적으로 `POST /api/v1/chatbot/chat/stream` (SSE 정본)을 호출**하고 있습니다.
   - 프론트엔드 React 코드 어디에서도 `POST /api/v1/chatbot/query` 또는 `POST /api/v1/chatbot/chat`을 호출하지 않습니다.
2. **백엔드 내부 서비스 (`src/`)**:
   - 백엔드 내부 태스크나 다른 서비스에서 `/chatbot/query`를 자체 호출하는 곳은 없습니다.
3. **테스트 및 벤치마크 도구 (`scripts/`, `tests/`)**:
   - `scripts/benchmark_latency.py:214`: 스트리밍 대비 비교 참고값 측정을 위해 호출.
   - `tests/test_api_v1.py`, `tests/test_chatbot_api_split.py`, `tests/test_e2e_cutover.py`: API 엔드포인트 계약 보존 검증용.

### 4.2 SSE 유도 및 경로 판단 근거

- **프론트엔드 사용자 경험 관점**:
  - 실제 웹 UI 사용자는 이미 100% SSE 경로를 사용하고 있으므로, 단발 질의의 6~10초 대기 지연을 겪지 않습니다.
- **단발 질의 엔드포인트의 존재 목적**:
  - `POST /api/v1/chatbot/query`는 브라우저 UI가 아닌 **간이 HTTP 클라이언트(cURL, 외부 배치 스크립트, Webhook, 스트리밍 미지원 타 시스템)** 연동을 위한 간이 비스트리밍 계약입니다.
- **기술적 제약 사항**:
  - RAG + LLM 생성 파이프라인의 특성상, 외부 LLM 모델의 생성 속도 자체를 획기적으로 줄이지 않는 한 비스트리밍 방식의 P95를 1~2초대로 낮추는 것은 구조적으로 불가능합니다 (LLM 생성 시간 자체가 4~6초 소요됨).

---

## 5. 향후 방향에 대한 선택지 나열 (의사결정용 근거)

코디네이터의 정책 결정을 위해 가능한 3가지 대안과 각각의 장단점 및 근거를 정리합니다. (결정은 하지 않음)

### 선택지 A: 단발 질의 API 목표를 별도로 수립하고 현행 유지
- **내용**: 단발 질의 API의 P95 목표를 LLM 전체 생성 시간을 감안한 현실적 수치(예: 12.0초 또는 15.0초 이내)로 정의하고 유지.
- **장점**: 외부 비스트리밍 클라이언트 및 cURL/스크립트 연동 호환성 100% 유지, 코드 수정 불필요.
- **단점**: 비스트리밍 특성상 사용자가 6~10초 대기를 감수해야 함.

### 선택지 B: 단발 질의 API를 비권장(Deprecated) 처리하고 SSE로 전면 유도
- **내용**: API 문서(Swagger/OpenAPI)에 `/chat/stream`을 정본으로 명시하고 `/query`에 Deprecation 예고 안내.
- **장점**: 챗봇 인터페이스 표준을 SSE 스트리밍으로 일원화, 사용자 체감 품질(첫 토큰 1.2초) 보장.
- **단점**: 스트리밍 처리가 어려운 단순 스크립트/외부 시스템 연동 시 클라이언트 구현 부담 증가.

### 선택지 C: 단발 질의 경로에 RAG 결과 캐싱(Redis Cache) 도입
- **내용**: 동일/유사 질의에 대해 RAG 및 LLM 생성 결과를 Redis 캐시에 저장하여 반복 질의 시 밀리초(ms) 단위로 응답.
- **장점**: 캐시 적중 질의에 대해 비스트리밍이라도 P95 대폭 단축 가능.
- **단점**: 캐시 무효화 정책(데이터 갱신 시), 캐시 미적중 질의는 여전히 6~10초 소요, 구현 복잡도 증가.

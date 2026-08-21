# 단발 질의 API 레이턴시 구간 분해 및 분석 보고서

> **작성일**: 2026-08-22
> **대상 엔드포인트**: `POST /api/v1/chatbot/query` (단발 질의 간이 계약)
> **비교 엔드포인트**: `POST /api/v1/chatbot/chat/stream` (정본 SSE 스트리밍)
> **대상 커밋**: `1308223`
> **목적**: 단발 질의 API의 P95(6.29~10.26초) 발생 구간을 코드 경로로 분해하고, SSE 경로와의 구조적 차이 및 호출부 현황을 분석하여 설계 목표 수립 또는 경로 유도 판단을 위한 근거를 제공합니다. (결정 제외, 근거 제출 전용)

---

## 1. 단발 질의 엔드포인트 요청 처리 경로 코드 분해

`POST /api/v1/chatbot/query` 호출 시 실행되는 전체 처리 경로는 아래 4단계로 구성됩니다.

### 1.1 단계별 코드 매핑

| 단계 | 실행 함수 및 위치 | 주요 작업 내용 | I/O 및 연산 유형 |
| :---: | :--- | :--- | :--- |
| **1단계** | `query_chatbot`<br>([`src/app/api/v1/chatbot.py:544-553`](src/app/api/v1/chatbot.py#L544-L553)) | 요청 수신, `rag_engine.get_answer` 비동기 호출, Pydantic 응답 직렬화 | FastAPI ASGI 라우팅, CPU 직렬화 |
| **2단계** | `HybridRAGEngine._prepare_context`<br>([`src/rag/engine.py:196-248`](src/rag/engine.py#L196-L248)) | 1) 질의 계획 수립 (`build_retrieval_plan`)<br>2) 정형 DB 통계/공고 조회 (`retrieve_structured_data`)<br>3) ChromaDB 지식베이스 벡터 검색 (`retrieve_semantic_context`)<br>4) 검색 컨텍스트 텍스트 및 프롬프트 메시지 조립 | CPU 키워드 파싱,<br>MySQL 동기 SQL I/O,<br>ChromaDB 임베딩 연산 및 디스크 I/O |
| **3단계** | `HybridRAGEngine.get_answer_sync`<br>([`src/rag/engine.py:276-334`](src/rag/engine.py#L276-L334)) | 1) 직답 목록 생성 여부 판정 (`_build_result_list_answer`)<br>2) LLM 백엔드 전체 생성 블로킹 호출 (`backend.generate`)<br>3) Answer Guard 교정 (`_apply_answer_guard`)<br>4) 출처 인용 문구 조립 (`_build_source_citation_from_context`) | 외부 LLM API/Ollama 네트워크 I/O 및 토큰 생성 대기 (블로킹),<br>CPU 문자열 정규화 |
| **4단계** | `HybridRAGEngine.get_answer`<br>([`src/rag/engine.py:336-344`](src/rag/engine.py#L336-L344)) | 2~3단계 전체 동기 실행을 `asyncio.to_thread`로 워커 스레드 풀에 위임 | 스레드 풀 스케줄링 오버헤드 |

---

## 2. 단계별 소요 시간 분석 (확인된 사실 vs 미계측 추정)

### 2.1 확인된 사실 (Ground Truth 및 실측 데이터)

1. **단발 질의 API 전체 레이턴시 실측치** (`data/benchmarks/blocking_io_p95/run1.json` ~ `run3.json`):
   - 1회차: P50 = 6,792.5ms (6.79s) / P95 = 10,257.0ms (10.26s) / 오류 0건
   - 2회차: P50 = 4,132.2ms (4.13s) / P95 = 6,285.3ms (6.29s) / 오류 0건
   - 3회차: P50 = 4,885.2ms (4.89s) / P95 = 8,090.8ms (8.09s) / 오류 0건
   - 종합 P95 대역: **6.29초 ~ 10.26초** (P50 대역: 4.13초 ~ 6.79초)
2. **SSE 스트리밍 경로의 단계별 분해 실측치** (`data/benchmarks/blocking_io_p95/run1.json` ~ `run3.json`):
   - `first_stage_ms` (FastAPI 진입 및 첫 stage 이벤트 전송): P95 = **3.4ms ~ 11.0ms**
   - `first_token_ms` (FastAPI 진입 -> RAG 컨텍스트 준비 -> LLM 첫 토큰 도착): P95 = **1,263.4ms ~ 2,290.9ms** (P50 = 772.2ms ~ 1,228.2ms)
   - `final_ms` (전체 스트리밍 완료): P95 = **6,365.9ms ~ 7,654.5ms** (P50 = 3,641.2ms ~ 4,419.7ms)
3. **코드 정적 분석 결과**:
   - 단발 질의 API 내부 코드 경로에는 인위적인 sleep, 큐 대기 루프, 재시도 로직, 불필요한 직렬화 지연이 존재하지 않음.

### 2.2 미계측 추정 영역 및 관측과 해석의 분리

1. **단계별 개별 소요 시간 미계측**:
   - 현재 벤치마크 및 프로파일링 데이터는 단발 질의 전체 소요 시간(P95 6.29~10.26초)과 SSE의 stage/first_token/final 수치만 실측되었음.
   - 단발 질의 경로 내부의 2단계(RAG 컨텍스트 준비: MySQL SQL 조회 및 ChromaDB 벡터 검색)와 3단계(LLM 백엔드 생성: `backend.generate`)의 개별 소요 시간 및 내부 비율은 분리 계측된 바 없으므로, 이를 특정 수치(예: RAG 1~2초, LLM 3~8초 등)로 단정할 수 없으며 전적으로 미계측 추정 영역임.
2. **완료 대역 관측과 원인 해석의 분리**:
   - **관측 사실**: 단발 질의 API의 P95 대역(6.29~10.26초)과 SSE 완료 P95 대역(6.37~7.65초)의 수치 범위가 일부 중첩됨.
   - **해석 및 한계**: 완료 대역이 유사하다는 관측 결과만으로 두 경로가 완전히 동일한 작업량을 수행한다거나 백엔드에 추가 병목이 전혀 없다고 단정할 수는 없음. 단계별 정밀 계측이 부재하므로 이는 구조적 유사성에 기반한 추정에 불과하며, 실제 차이를 규명하려면 단계별 계측이 선행되어야 함.

### 2.3 필요 계측 제안 (향후 과제)

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
| **체감 응답 시점** | **6.29 ~ 10.26초 동안 무응답 대기** 후 일괄 수신 | **3~11ms(stage)** 즉각 반응, **1.26~2.29초(첫 토큰)** 출력 시작 (실측 P95 기준) |
| **대화 이력 저장** | 저장 안 함 (단발성 질의 계약) | `remember_chat_interaction` (DB 대화 세션 기록) |
| **전체 완료 P95** | **6.29초 ~ 10.26초** | **6.37초 ~ 7.65초** |

### 3.1 구조적 차이 분석

- **확인된 구조적 차이**: SSE 경로는 `stream_generate`를 통해 토큰 단위로 실시간 `yield`하여 첫 토큰을 빠르게 클라이언트에 전달하는 반면, 단발 질의는 `generate` 블로킹 호출로 전체 답변 생성이 완료될 때까지 단일 JSON 응답을 대기함.
- **해석상의 한계**: 단발 질의의 체감 대기 지연은 비스트리밍 응답 모델의 특성에서 기인하지만, 단계별 시간 분리 계측이 없으므로 두 경로의 백엔드 연산 효율이 완전히 동일하다고 단정할 수는 없음.

---

## 4. 호출부 전수 조사 및 SSE 유도 가능성 판단 근거

### 4.1 호출부 전수 조사 결과 (Search Scope 내 확인 사실)

1. **프론트엔드 (`frontend/src/`)**:
   - `frontend/src/App.tsx:215`: 챗봇 탭의 사용자 대화는 전적으로 `POST /api/v1/chatbot/chat/stream` (SSE 정본)을 호출함.
   - 프론트엔드 코드 내에 `POST /api/v1/chatbot/query` 호출은 존재하지 않음 (0건).
2. **백엔드 내부 서비스 (`src/`)**:
   - 백엔드 내부 태스크나 다른 서비스에서 `/chatbot/query`를 자체 호출하는 코드는 존재하지 않음 (0건).
3. **테스트 및 벤치마크 도구 (`scripts/`, `tests/`)**:
   - `scripts/benchmark_latency.py:214`: 비스트리밍 단발 질의 레이턴시 벤치마크 측정용.
   - `tests/test_api_v1.py:29`, `tests/test_chatbot_api_split.py:125`, `tests/test_e2e_cutover.py:23`: API 엔드포인트 계약 및 라우팅 보존 검증용.

### 4.2 SSE 유도 및 경로 판단 근거 (확인 사실 vs 추정)

- **프론트엔드 사용자 경험 관점 (확인 사실)**:
  - 실제 웹 UI 사용자는 100% SSE 경로를 사용하므로, 단발 질의의 6~10초 일괄 대기 지연을 겪지 않음.
- **단발 질의 엔드포인트의 성격 및 목적 (확인 사실 vs 추정)**:
  - **코드상 확인 사실**: `src/app/api/v1/chatbot.py:543`에 summary="단발 질의 (간이 계약)"으로 명시된 단일 JSON 질의-응답 인터페이스임.
  - **외부 사용 목적 (추정)**: 브라우저 UI가 아닌 간이 HTTP 클라이언트(cURL, 배치 스크립트, Webhook, 스트리밍 미지원 타 시스템) 연동을 위한 계약이라는 해석은 일반적인 API 용례에 기반한 추정이며 코드 계약상에 특정 클라이언트용으로 명시되어 있지는 않음.
- **기술적 특성**:
  - 비스트리밍 방식은 LLM 전체 생성이 완료될 때까지 응답을 반환할 수 없으므로, 외부 LLM 모델의 전체 토큰 생성 시간이 소요되는 한 단발 질의의 완료 지연을 스트리밍 첫 토큰 수준(1~2초대)으로 단축하는 것은 구조적으로 제한됨.

---

## 5. 향후 방향에 대한 선택지 나열 (의사결정용 근거)

코디네이터의 정책 결정을 위해 가능한 3가지 대안과 각각의 장단점 및 근거를 정리합니다. (결정은 하지 않음)

### 선택지 A: 단발 질의 API 목표를 별도로 수립하고 현행 유지
- **내용**: 단발 질의 API의 P95 목표를 LLM 전체 생성 시간을 감안한 현실적 수치(예: 12.0초 또는 15.0초 이내)로 정의하고 유지.
- **장점**: 외부 비스트리밍 클라이언트 및 cURL/스크립트 연동 호환성 100% 유지, 코드 수정 불필요.
- **단점**: 비스트리밍 특성상 사용자가 6~10초 대기를 감수해야 함.

### 선택지 B: 단발 질의 API를 비권장(Deprecated) 처리하고 SSE로 전면 유도
- **내용**: API 문서(Swagger/OpenAPI)에 `/chat/stream`을 정본으로 명시하고 `/query`에 Deprecation 예고 안내.
- **장점**: 챗봇 인터페이스 표준을 SSE 스트리밍으로 일원화, 사용자 체감 품질(첫 토큰 1.2~2.3초) 보장.
- **단점**: 스트리밍 처리가 어려운 단순 스크립트/외부 시스템 연동 시 클라이언트 구현 부담 증가.

### 선택지 C: 단발 질의 경로에 RAG 결과 캐싱(Redis Cache) 도입
- **내용**: 동일/유사 질의에 대해 RAG 및 LLM 생성 결과를 Redis 캐시에 저장하여 반복 질의 시 밀리초(ms) 단위로 응답.
- **장점**: 캐시 적중 질의에 대해 비스트리밍이라도 P95 대폭 단축 가능.
- **단점**: 캐시 무효화 정책(데이터 갱신 시), 캐시 미적중 질의는 여전히 6~10초 소요, 구현 복잡도 증가.

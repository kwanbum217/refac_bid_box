# 미측정 읽기 경로 N+1 질의 및 이벤트 루프 동기 I/O 정적 전수 조사 보고서

> **작성일**: 2026-09-20
> **작성자**: Antigravity (Orca Worker `term_7298f414-46fb-43f7-9b60-8902d877836e`)
> **Task ID**: `task_c420f88e33b2`
> **조사 성격**: 정적 코드 전수 조사 (코드 수정 및 런타임 측정 미실시)
> **선행 문서**: [`read_path_concurrency_20260918.md`](read_path_concurrency_20260918.md), [`read_path_ab_confirmation_20260919.md`](read_path_ab_confirmation_20260919.md)

---

## 1. 개요 및 목적

AGENTS.md는 G3 스택 최적화를 상시 과제로 규정합니다. 2026-09-18 회차는 낙찰 목록(`GET /api/v1/bids/results`) 직렬화 시 공고 단건 조회 N+1 결함을 발견하여 일괄 선채움(`preload_matching_announcements`, 커밋 `419274cd`)으로 개선했고, 2026-09-19 통제 A/B 실측으로 순개선 -62.7%를 확정했습니다.

그러나 해당 회차는 낙찰 목록과 홈 컨텍스트(`GET /api/v1/bids/home`)만을 조사 대상으로 삼았으며, 공고 목록, 상세 조회, 일반용역 적격심사, 챗봇 RAG 및 플래너 도구 체인은 동일한 수준의 조사가 이루어지지 않았습니다. 본 조사는 아직 실측·최적화 대상이 되지 않은 읽기 경로 전반을 대상으로 N+1 질의와 이벤트 루프를 차단하는 비동기 미오프로드 동기 I/O를 정적으로 전수 조사하여, 차기 최적화 우선순위와 실측 방안을 도출하는 것을 목적으로 합니다.

본 조사는 정본 사양(Capsule)의 계약에 따라 코드를 수정하지 않고 컨테이너 기동이나 벤치마크 측정을 일절 수행하지 않은 순수 정적 분석입니다.

---

## 2. 조사 범위 및 분석 방법

### 2.1 조사 범위

코디네이터 확정 계약에 따라 쓰기 경로(POST 생성, PUT, DELETE 등)와 외부 수집 경로(`collect_bids` 관리 명령 등)를 제외한 잔여 읽기 경로를 전수 조사했습니다.

1. **API 라우터 계층**:
   - `src/app/api/v1/bids.py`: 입찰공고 목록, 공고 상세, 낙찰결과 상세, 통계 엔드포인트
   - `src/app/api/v1/evaluations.py`: 적격심사 통합 분석, 평가 프로필 목록/상세, 분석 스냅샷 목록/상세
   - `src/app/api/v1/predictions.py`: 모델 목록, 공고 기반 낙찰가 예측, 특징 직접 예측
   - `src/app/api/v1/chatbot.py`: 챗봇 동기 질의, SSE 스트리밍, 단발 질의
2. **서비스 계층**:
   - `src/app/services/bid_queries.py`: 공고/낙찰 목록 및 상세 조회 쿼리
   - `src/app/services/dashboard.py`: 대시보드 및 비교 분석 집계 쿼리
   - `src/app/services/evaluation_rules.py`, `evaluation_scoring.py`, `negotiation_stats.py`: 적격심사 도메인 로직
   - `src/app/services/conversation_state.py`: 대화 세션 상태 저장 및 복원
   - `src/app/services/planner.py`, `plan_executor.py`: 챗봇 의도 분류 및 플랜 실행
   - `src/app/services/tools/`: `bid_prediction_tool.py`, `trend_analyzer.py`, `chart_builder.py`, `kb_status_tool.py`, `automation_status_tool.py`
3. **RAG 및 벡터 검색 계층**:
   - `src/rag/engine.py`: 하이브리드 RAG 질의 처리 및 토큰 스트리밍
   - `src/rag/structured_data.py`: 정형 통계 및 시계열 조회
   - `src/rag/vector_store.py`: ChromaDB 벡터 검색
   - `src/rag/llm.py`: 로컬 Ollama 및 외부 Gemini 생성 인터페이스
   - `src/rag/embeddings.py`: Ollama 임베딩 함수

### 2.2 분석 방법

- **N+1 질의 탐지**: 루프(`for`, `while`, 리스트 컴프리헨션) 내부에서 SQLAlchemy 세션의 `execute()`, `query()`, `get()` 등 DB 질의를 반복 호출하거나, ORM 관계(`relationship`)의 기본 지연 로딩(`lazy='select'`) 속성을 컬렉션 순회 과정에서 건드려 1 + N 질의를 유발하는 지점을 AST 및 정적 호출 그래프로 추적했습니다.
- **동기 I/O 블로킹 탐지**: FastAPI의 `async def`로 선언된 비동기 엔드포인트 또는 이벤트 루프 컨텍스트 내부에서 `await` 또는 `asyncio.to_thread` 오프로드 없이 실행되는 동기 SQLAlchemy 호출, 파일 입출력, 동기 네트워크 통신(`httpx` sync client, `redis` sync client), `time.sleep` 호출을 전수 추출했습니다.
- **예외 규정 준수**: `asyncio.to_thread`로 명시적 오프로드된 동기 호출(`src/rag/engine.py`의 `get_answer_sync` 호출, `src/app/main.py`의 예열 태스크 등)은 이벤트 루프를 막지 않으므로 정상 경로로 판정했습니다. 또한 이미 최적화가 완료된 낙찰 목록 N+1과 홈 컨텍스트 선채움은 새 후보에서 완전히 배제했습니다.

---

## 3. 식별된 결함 후보 전수 목록

심각도(동시성 저해 수준 및 질의 증폭 배율) 순으로 정렬된 5대 후보 목록입니다. 모든 후보는 필수 5개 항목(위치, 형태, 발생 조건, 예상 기여, 측정 방법)을 완비하고 있습니다.

| 순번 | 심각도 | 위치 (파일:행) | 형태 | 발생 조건 | 예상 질의 수나 지연 기여 | 측정 방법 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | 높음 | `src/app/services/bid_queries.py:745-748` | N+1 질의 | `GET /api/v1/bids/results/{pk}` 또는 SSR `GET /bids/results/{pk}` 호출 시 (낙찰 상세 화면 및 관련 낙찰 5건 조회) | 본건 외 관련 낙찰 5건에 대해 `row.display_winning_rate(db)`를 루프 순회하며 호출. 건당 1~2회의 공고 단건 조회 쿼리가 발생하여 총 5~10회의 추가 SQL 질의 실행. `bids.py`의 `_serialize_results` 선채움 이전에 서비스 함수 내부에서 이미 루프를 돌기 때문에 선채움 캐시가 무력화되어 항상 발생. c10 동시성 환경에서 커넥션 풀 경합 유발 (약 30~80ms 지연 기여). | `GET /api/v1/bids/results/1`을 대상으로 단일 요청 및 c10 동시성 100회 요청 시 SQLAlchemy 쿼리 카운트 및 P95 레이턴시 측정. |
| 2 | 높음 | `src/app/api/v1/evaluations.py:920-946` | N+1 질의 (ORM 지연 로딩) | 인증된 사용자가 `GET /api/v1/evaluations/snapshots` 호출 시 (내 적격심사 분석 스냅샷 목록 조회) | `BidEvaluationSnapshot`의 `evidence_items` 관계가 기본 `lazy='select'`로 선언되어 있음. 스냅샷 목록 N건 조회 후 DTO 변환 시 `for e in s.evidence_items`를 평가하면서 스냅샷 1건마다 증빙 조회 SELECT 쿼리가 1회씩 발생 (1 + N 쿼리). 페이징 제한이 없어 스냅샷 누적에 비례해 질의 수 선형 증가 (스냅샷 20건 기준 21회 질의 발생, 약 20~60ms 지연). | 스냅샷 N건(예: 10건, 30건)을 생성한 테스트 계정으로 `GET /api/v1/evaluations/snapshots`를 호출하여 발송되는 총 SQL 질의 수(1 + N 여부) 검증. |
| 3 | 높음 | `src/app/api/v1/chatbot.py:437, 472`, `src/app/core/security.py:421-428` | 이벤트 루프 블로킹 동기 I/O | 미인증(익명) 사용자가 `POST /api/v1/chatbot/chat` 또는 `POST /api/v1/chatbot/chat/stream` 호출 시 | 비동기 핸들러(`async def`) 진입 직후 스레드 오프로드 전에 `enforce_anonymous_api_quota`를 직접 호출. 내부에서 동기 Redis 클라이언트(`client.get()`, `pipe.execute()`)를 메인 이벤트 루프 스레드에서 직접 실행하여 동기 소켓 I/O 발생. Redis 왕복 시간(0.5~3ms, 부하 시 수십 ms) 동안 이벤트 루프가 완전히 멈춰 다른 동시 비동기 연결 처리가 지연됨. | Redis에 네트워크 지연(예: 10ms)을 인위적으로 부여하거나 미인증 동시 요청(c10)을 주입하며 이벤트 루프 지연(loop lag) 및 `/api/v1/health/live` 응답 시간 관측. |
| 4 | 중간 | `src/rag/structured_data.py:1264-1293` | N+1 질의 (다중 기관 루프 집계) | 챗봇 질의 중 2개 이상의 수요기관 비교가 요청될 때 (`filters.institution_names`가 2~5개 유입, 예: "도로공사와 서울시 낙찰률 비교") | 대상 기관 K개(최대 5개)에 대해 루프를 돌며, 기관마다 `BidResult` 집계 쿼리(`COUNT`, `AVG`) 1회 + 최신 결과 3건 조회 쿼리(`_fetch_recent_results`, LIMIT 9) 1회를 순차 실행. K개 기관에 대해 2*K회(최대 10회)의 단건 SQL 질의가 반복 발생. 수백만 건의 `bid_results` 테이블을 기관별로 반복 집계하여 총 50~150ms DB 시간 소모. | `POST /api/v1/chatbot/query`에 `{"query": "한국도로공사와 서울특별시의 최근 낙찰률 비교해줘"}`를 전송하여 응답 메트릭의 `sql_ms` 및 실행 쿼리 수 관측. |
| 5 | 중간 | `src/rag/structured_data.py:1106-1140` | N+1 질의 (분기 시계열 루프 집계) | 챗봇 질의에서 트렌드 분석 또는 분기별 집계 요청 시 (`time_bucket == 'quarter'` 또는 `analysis_mode == 'trend'`) | 조회 대상 분기 목록(`quarters`)을 순회하며 분기 1건마다 `BidResult` 집계 쿼리 1회 + `BidAnnouncement` 집계 쿼리 1회를 실행. 2년(8분기) 범위 질의 시 캐시 미적중 상태에서 2*8 = 16회의 개별 SQL 집계 쿼리가 순차 실행됨. 단일 `GROUP BY YEAR, QUARTER` 질의 대신 루프 질의를 수행하여 약 80~200ms DB 시간 소모. | 캐시 초기화 후 `POST /api/v1/chatbot/query`에 `{"query": "최근 2년간 분기별 낙찰률 추세 알려줘"}`를 호출하여 `segment_metrics.sql_ms` 및 쿼리 수 관측. |
| 6 | 보통 | `src/app/services/tools/bid_prediction_tool.py:177, 307` | N+1 질의 (복수 공고 예측 피처 순회) | 챗봇 플래너가 복수 공고 투찰가 예측을 실행할 때 (limit > 1, 예: "최근 공고 3개 투찰가 예측해줘") | 최근 예측 가능 공고 K건을 가져온 뒤 `[_predict_bid(...) for bid in bids]` 루프를 순회하며 공고마다 `build_feature_dict` 호출. 공고 1건마다 기관 이력 조회(`lookup_institution_stats`) 1회 + 재발주 이력 조회(`lookup_repeat_history`) 1회가 실행되어 K건당 2*K회 추가 DB 질의 발생 (3건 기준 6회, 5건 기준 10회 질의 발생, 약 20~50ms 지연). | `POST /api/v1/chatbot/chat`에 `{"message": "최근 공고 3개 예측해줘"}`를 전송하고 플래너 도구 실행 중 발송되는 DB 질의 수 관측. |

---

## 4. 전수 조사 입증: 결함 없음(정상) 판정 경로 목록

조사 대상에 포함된 모든 읽기 경로에 대해 정적 코드 점검을 완료하였으며, 아래 경로들은 N+1 질의가 없고 동기 I/O 블로킹이 발생하지 않음을 확인했습니다.

| 조사 대상 경로 | 검토 함수 및 파일 | 판정 | 근거 및 분석 결과 |
| :--- | :--- | :--- | :--- |
| 공고 목록 (`GET /api/v1/bids`) | `list_bids` (`src/app/api/v1/bids.py`), `list_announcements` (`src/app/services/bid_queries.py`) | 결함 없음 | Meilisearch 인덱스에서 PK 목록을 획득한 후 `BidAnnouncement.id.in_(ids)` 1회 쿼리로 일괄 조회함. 직렬화 함수 `_serialize_announcement`는 공고 자체 컬럼 및 `raw_data` JSON 인메모리 필드만 접근하며 추가 쿼리를 유발하지 않음. |
| 공고 상세 (`GET /api/v1/bids/{pk}`) | `get_bid_detail` (`src/app/api/v1/bids.py`), `get_announcement_detail` (`src/app/services/bid_queries.py`) | 결함 없음 | 본건 조회(1회), 유사 공고 조회(1회), 과거 결과 조회(1회), 제한정보 조회(2회)가 고정 횟수로 실행됨. `past_results` 5건 직렬화는 `_serialize_results`의 `preload_matching_announcements`가 정상 적용되어 일괄 IN 조회로 처리됨. |
| 대시보드 통계 (`GET /api/v1/bids/stats`) | `api_stats` (`src/app/api/v1/bids.py`), `get_dashboard_stats` (`src/app/services/dashboard.py`) | 결함 없음 | 동기 라우트(`def`)로 AnyIO 스레드풀에서 실행되어 이벤트 루프를 막지 않음. 집계 결과는 `BidDatasetSummary` 단일 행 조회 및 Redis 캐시(`DASHBOARD_STATS_CACHE_TTL`)를 활용하여 O(1)로 조회됨. |
| 비교 통계 (`GET /api/v1/bids/compare-stats`) | `api_compare_stats` (`src/app/api/v1/bids.py`), `get_compare_stats_data` (`src/app/services/dashboard.py`) | 결함 없음 | 동기 라우트(`def`)로 실행되며, 사전 구축된 스냅샷(`BidCompareStatsSnapshot`) 4건을 PK로 일괄 조회하여 재사용하므로 실시간 대규모 집계가 발생하지 않음. |
| 예측 모델 목록 (`GET /api/v1/predictions/list-models`) | `list_models_api` (`src/app/api/v1/predictions.py`) | 결함 없음 | `ModelRegistry.list_models_info()` 인메모리 딕셔너리만 반환하며 DB 질의가 전혀 없음. |
| 낙찰가 예측 (`POST /api/v1/predictions/predict-price`) | `predict_price_api` (`src/app/api/v1/predictions.py`) | 결함 없음 | 동기 라우트(`def`)로 실행. 공고 단건 조회(`db.get`) 후 `build_feature_dict`가 1회 실행되며 루프 순회가 없음. G3 정본 레이턴시 게이트 통과 경로. |
| 직접 특징 예측 (`POST /api/v1/predictions/predict`) | `predict_winning_price` (`src/app/api/v1/predictions.py`) | 결함 없음 | 동기 라우트(`def`)로 실행. 공고 조회 없이 페이로드 기반 인메모리 추론 수행. |
| 적격심사 분석 (`POST /api/v1/evaluations/analyze`) | `analyze_evaluation` (`src/app/api/v1/evaluations.py`) | 결함 없음 | 동기 라우트(`def`)로 실행. 단건 공고 조회 후 규칙 매칭 및 `predict_price_api` 단건 호출. 루프 쿼리 없음. |
| 평가 프로필 목록/상세 (`GET /api/v1/evaluations/profiles*`) | `list_evaluation_profiles`, `get_evaluation_profile` (`evaluations.py`) | 결함 없음 | `BidEvaluationProfile` 단일 테이블 단순 조회(연관 관계 없음). 루프 쿼리 없음. |
| 스냅샷 상세 (`GET /api/v1/evaluations/snapshots/{id}`) | `get_evaluation_snapshot` (`src/app/api/v1/evaluations.py`) | 결함 없음 | 단건 스냅샷 조회로, 증빙 컬렉션 조회가 발생하더라도 대상 스냅샷 1건에 한정되므로 N+1 증폭이 발생하지 않음. |
| 챗봇 세션 생성 (`POST /api/v1/chatbot/session/new`) | `new_chat_session_api` (`src/app/api/v1/chatbot.py`) | 결함 없음 | 동기 라우트(`def`)로 실행. 인메모리 HMAC 서명 기반 세션 키 발급만 수행. |
| 챗봇 단발 질의 (`POST /api/v1/chatbot/query`) | `query_chatbot` (`src/app/api/v1/chatbot.py`) | 결함 없음 | `async def` 라우트이나 `await rag_engine.get_answer` 내부에서 `await asyncio.to_thread(self.get_answer_sync)`를 통해 전체 파이프라인을 스레드로 오프로드함. 이벤트 루프 블로킹 없음. |
| ChromaDB 벡터 검색 | `retrieve_semantic_context`, `search_similar_docs` (`src/rag/vector_store.py`) | 결함 없음 | `search_similar_docs`는 `await asyncio.to_thread(...)`로 오프로드되어 있으며, 단일 컬렉션 쿼리 후 파이썬 인메모리 필터링을 수행함. 루프 질의 없음. |
| RAG 토큰 스트리밍 | `stream_tokens` (`src/rag/engine.py`) | 결함 없음 | 컨텍스트 준비(`_prepare_context`)는 `await asyncio.to_thread(...)`로 스레드에 오프로드되고, LLM 토큰 생성기 호출(`next(token_gen)`) 역시 `await asyncio.to_thread(...)`로 래핑되어 이벤트 루프를 막지 않음. |
| 플래너 도구 체인 | `trend_analyzer.py`, `chart_builder.py` (`src/app/services/tools/`) | 결함 없음 | 선행 단계의 `tool_results` 인메모리 딕셔너리만 수치 변환 및 집계함. DB 및 네트워크 I/O 없음. |
| 상태 도구 | `kb_status_tool.py`, `automation_status_tool.py` (`src/app/services/tools/`) | 결함 없음 | 최신 상태 레코드 1건만 `limit(1)`로 조회하여 단건 반환. 루프 질의 없음. |

*(참고: 이미 최적화된 낙찰 목록 `GET /api/v1/bids/results` 및 홈 컨텍스트 `GET /api/v1/bids/home`는 선행 확정 사실에 따라 재조사에서 제외되었습니다.)*

---

## 5. 차기 착수 권고 (상위 3건)

식별된 6개 결함 후보 중 즉각적인 레이턴시 개선 효과가 높고 회귀 위험이 낮은 상위 3건을 차기 최적화 대상으로 권고합니다.

### 5.1 권고 1순위: 낙찰 상세 관련 결과 N+1 해소 (`src/app/services/bid_queries.py:747`)

- **결함 요약**: `get_result_detail`이 관련 낙찰 5건에 대해 `preload_matching_announcements` 선채움 없이 `row.display_winning_rate(db)`를 순차 호출하여 건당 5~10회 단건 쿼리 발생.
- **수정 난이도**: **낮음 (하)**
  - `src/app/services/bid_queries.py`의 `get_result_detail` 내부에서 `related_results` 조회 직후 `preload_matching_announcements(db, related_results)` 1줄을 호출하면 해결됩니다.
- **회귀 위험**: **매우 낮음 (최하)**
  - 이미 커밋 `419274cd`에서 단위 테스트(`tests/test_bid_result_serialization_batch.py` 8건)로 정합성이 증명된 일괄 선채움 함수를 그대로 재활용하는 것입니다.
  - 객체의 인스턴스 캐시(`_matching_announcement_cache`)를 채우는 방식이므로 하위 로직이나 반환 스키마에 일절 부작용이 없습니다.
- **예상 효과**: 낙찰 상세 API (`GET /api/v1/bids/results/{pk}`) 및 SSR 화면 조회 시 추가 SQL 질의 수 5~10회 -> 1회로 감소, 응답 지연 약 30~50ms 단축.

### 5.2 권고 2순위: 적격심사 스냅샷 목록 ORM 지연 로딩 N+1 해소 (`src/app/api/v1/evaluations.py:942`)

- **결함 요약**: `list_evaluation_snapshots`가 스냅샷 목록을 조회한 후 응답 조립 시 지연 로딩 관계인 `evidence_items`에 접근하여 스냅샷 1건마다 추가 SELECT 쿼리 발생 (1 + N 쿼리).
- **수정 난이도**: **낮음 (하)**
  - 쿼리 작성부에 `options(selectinload(BidEvaluationSnapshot.evidence_items))` 옵션을 추가하여 1회의 IN 쿼리로 증빙 목록을 사전 적재하도록 변경합니다.
- **회귀 위험**: **매우 낮음 (최하)**
  - 응답 스키마(`EvaluationSnapshotResponse`) 및 데이터 변환 로직에 아무런 영향이 없으며, SQLAlchemy의 표준 일괄 로딩 전략을 적용하는 작업입니다.
- **예상 효과**: 스냅샷 목록 API (`GET /api/v1/evaluations/snapshots`) 호출 시 SQL 질의 수가 1 + N회에서 고정 2회로 축소, 스냅샷 다건 보유 사용자의 응답 레이턴시 50% 이상 개선.

### 5.3 권고 3순위: 챗봇 익명 쿼터 제한기의 이벤트 루프 블로킹 해소 (`src/app/api/v1/chatbot.py:437, 472`)

- **결함 요약**: `async def chat_api` 및 `async def chat_stream_api` 핸들러가 진입 즉시 이벤트 루프 메인 스레드에서 동기 Redis I/O(`enforce_anonymous_api_quota`)를 직접 실행하여 이벤트 루프를 정지시킴.
- **수정 난이도**: **중간 (중)**
  - `enforce_anonymous_api_quota` 호출을 `await asyncio.to_thread(enforce_anonymous_api_quota, request, user)`로 오프로드하거나, Redis 연결 계층을 비동기로 전환합니다. 핸들러 진입 단계에서의 단순 `to_thread` 오프로드가 가장 안전하고 단순한 해결책입니다.
- **회귀 위험**: **낮음 (하)**
  - 쿼터 제한 로직(IP 파싱, 윈도우 카운팅, 429 예외 발생) 자체는 완전히 동일하게 유지되며, 호출 스레드 컨텍스트만 메인 이벤트 루프에서 작업자 스레드로 이동합니다.
- **예상 효과**: 미인증 사용자의 다중 동시 챗봇 요청 또는 SSE 연결 시 이벤트 루프 블로킹(0.5~3ms)이 완전히 제거되어, 서버 전체 비동기 처리량 증대 및 꼬리 지연 스파이크 방지.

---

## 6. 결론

본 조사를 통해 아직 최적화되지 않은 읽기 경로에서 실질적인 성능 저하를 유발하는 N+1 질의 5건과 이벤트 루프 블로킹 동기 I/O 1건을 특정했습니다.

특히 **낙찰 상세 관련 결과 N+1**은 이전 회차에서 목록 경로만 선채움되고 상세 서비스 함수(`get_result_detail`) 내부에서는 누락되어 선채움이 무력화되던 숨은 결함이며, **적격심사 스냅샷 목록 지연 로딩**은 사용자 데이터 누적 시 심각한 선형 지연을 유발할 수 있는 구조적 결함입니다. 또한 **챗봇 익명 쿼터 제한기의 동기 Redis 호출**은 이벤트 루프의 본질적인 동시성을 훼손하는 요소입니다.

다음 최적화 작업에서는 위 상위 3건을 우선적으로 수정하고, 표준 레이턴시 게이트 규약에 따라 A/B 실측을 진행할 것을 제안합니다.

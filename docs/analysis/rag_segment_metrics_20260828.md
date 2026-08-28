# RAG 질의 처리 구간별 계측 지표 정의 및 진단 가이드

> **작성일**: 2026-08-28
> **문서 버전**: v1.0.0
> **대상 모듈**: `src/rag/engine.py`, `src/app/core/config.py`

---

## 1. 개요

RAG(Retrieval-Augmented Generation) 파이프라인에서 특정 질의가 수십 초를 소모하거나 타임아웃되는 현상이 발생할 때, 병목이 검색 단계(SQL / Vector / Lexical)인지, 컨텍스트 조립인지, LLM 토큰 생성인지 신속하고 명확하게 지목할 수 있도록 구간별 지연 시간(`time.perf_counter` 기준, ms 단위)을 분해 계측합니다.

계측된 지표는 `LATENCY_SEGMENT_LOGGING` 활성화 시 구조화 로그(`rag_engine_latency`)로 출력되며, `RAG_EXPOSE_SEGMENT_METRICS` 설정 시 `AnswerBundle.segment_metrics` 및 스트리밍 `done` 이벤트를 통해 선택적으로 노출됩니다.

---

## 2. 구간 지표 정의

| 지표명 (`key`) | 계측 대상 구간 | 설명 |
| :--- | :--- | :--- |
| `plan_ms` | 검색 계획 수립 | `build_retrieval_plan`을 통한 질의 분석, 키워드/정규식 매칭 및 라우팅 계획 수립 소요 시간 |
| `sql_ms` | 정형 데이터 조회 | `retrieve_structured_data`를 통한 MySQL 데이터베이스 집계 및 통계 조회 소요 시간 |
| `vector_ms` | 벡터 지식베이스 검색 | `retrieve_semantic_context`를 통한 ChromaDB 임베딩 검색 및 유사 문서 조회 소요 시간 |
| `lexical_ms` | 어휘(키워드) 인덱스 검색 | `retrieve_lexical_context`를 통한 Meilisearch 공고명/기관명 일치 검색 소요 시간 |
| `kb_status_ms` | KB 상태 메타데이터 조회 | `get_latest_kb_status_payload`를 통한 최신 KB 버전 및 동기화 상태 조회 소요 시간 |
| `assembly_ms` | 컨텍스트 합성 및 메시지 조립 | `_compose_context_text`, 근거(`Provenance`) 생성, 프롬프트 메시지 구성 소요 시간 |
| `prepare_total_ms` | 전체 준비(검색+조립) 소요 시간 | `_prepare_context` 전체 실행 소요 시간 (`plan_ms` + 각 검색 채널 + `assembly_ms`) |
| `llm_ms` | LLM 추론 및 토큰 생성 | Ollama/Gemini 등 백엔드 LLM 모델의 첫 토큰 생성 및 전체 텍스트 추론 소요 시간 |
| `guard_ms` | 답변 검증 및 가드 처리 | `_apply_answer_guard`, 카테고리 정규화, 수치 누락 검출(`check_numeric_omissions`) 소요 시간 |
| `total_ms` | 전체 질의 응답 처리 시간 | `get_answer_sync` 또는 `stream_tokens`의 질의 수신부터 최종 번들 반환까지의 총 소요 시간 |

---

## 3. 병목 구간별 진단 및 해석 가이드

특정 지표의 수치가 비정상적으로 높을 경우 아래 표를 참조하여 원인을 진단합니다.

| 지표 이상 현상 | 의심 원인 (Root Cause) | 권장 조치 사항 |
| :--- | :--- | :--- |
| `vector_ms` > 500ms | 1. ChromaDB 프로세스 부하 또는 I/O 지연<br>2. 임베딩 모델(Ollama bge-m3) 동시성 경합 또는 콜드스타트<br>3. 과도하게 큰 `top_k` 값 또는 복잡한 메타데이터 필터 | 1. 임베딩 백엔드 연결 및 프로세스 리소스 확인<br>2. 임베딩 사전 웜업 및 배치 질의 최적화<br>3. `top_k` 기본값(5) 준수 여부 점검 |
| `lexical_ms` > 200ms | 1. Meilisearch 컨테이너 리소스 부족 또는 네트워크 지연<br>2. 과도하게 긴 검색어 파싱 및 필터 조합 오버헤드<br>3. Meilisearch 인덱스 재색인 작업과의 동시성 경합 | 1. `MEILI_ENABLED` 및 네트워크 연결 상태 점검<br>2. `MEILI_TIMEOUT_SECONDS` 타임아웃 및 폴백 동작 점검<br>3. 어휘 인덱스 복합 필터 간소화 |
| `sql_ms` > 300ms | 1. MySQL 인덱스 미적용 풀스캔 (날짜/기관명 복합 조건)<br>2. 대량 데이터 집계 쿼리 실행<br>3. DB 커넥션 풀 고갈 또는 락 경합 | 1. `EXPLAIN`으로 쿼리 실행 계획 점검 및 복합 인덱스 확인<br>2. 집계 기간 제한(`time_window`) 및 캐싱 적용<br>3. DB 커넥션 풀 설정 확인 |
| `llm_ms` > 10,000ms (10초+) | 1. Ollama 모델 메모리 언로드 후 첫 호출(콜드스타트 로드 비용)<br>2. `LLM_THINKING` 활성화로 인한 사고 토큰 생성 지연<br>3. 긴 검색 컨텍스트 입력으로 인한 TTFT(Time To First Token) 급증<br>4. CPU/GPU 컴퓨팅 자원 부족 | 1. `OLLAMA_KEEP_ALIVE=-1` 설정 및 기동 시 웜업(`LLM_WARMUP_ON_STARTUP=True`) 점검<br>2. `LLM_THINKING=False` 적용 여부 확인<br>3. 컨텍스트 크기 축소 및 불필요한 프롬프트 토큰 절감 |
| `assembly_ms` > 50ms | 1. 과도하게 많은 문서 스니펫 병합 및 중복 제거 루프<br>2. 대용량 문자열 정규화 및 정규식 처리 지연 | 1. `vector_docs` 및 `evidence_items` 슬라이싱 상한선 확인<br>2. 정규식 컴파일 캐싱 점검 |
| `guard_ms` > 50ms | 1. 긴 답변 본문 대상 정규식 매칭 반복<br>2. `check_numeric_omissions`의 다중 후보 수치 비교 오버헤드 | 1. 수치 누락 검출 대상 범위 최소화<br>2. 컴파일된 정규식 패턴 재사용 확인 |

---

## 4. 운영 설정 및 안전성 원칙

1. **기본값 비노출 원칙**:
   - `RAG_EXPOSE_SEGMENT_METRICS`: 기본값 `False`.
   - 운영 환경에서 불필요한 메타데이터 전송과 직렬화 오버헤드를 방지합니다.
2. **진단 로깅 선택 활성화**:
   - `LATENCY_SEGMENT_LOGGING`: 기본값 `False`.
   - 정밀 지연 분석 또는 회귀 테스트 시에만 환경변수나 설정을 통해 활성화합니다.
3. **무장애 계측 원칙 (Fault Tolerance)**:
   - 계측 로직(`time.perf_counter`, 딕셔너리 연산, 로깅 등)에서 예외가 발생하더라도 RAG 질의 응답의 주 경로는 영향을 받지 않고 정상 완료됩니다.

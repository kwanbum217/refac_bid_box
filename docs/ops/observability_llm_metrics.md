# RAG LLM 관측성 지표 사양서

> **작성일**: 2026-09-14
> **상태**: 확정 (Active)
> **표준**: OpenTelemetry Metrics API / SDK
> **대상 모듈**: `src/app/core/observability.py`, `src/rag/llm.py`

---

## 1. 개요

본 문서는 하이브리드 RAG 엔진의 LLM 호출 단계를 계측하기 위해 수집하는 OpenTelemetry 메트릭 표준 사양을 정의합니다.
SQL 조회 병목 최적화 이후 발생하는 꼬리 지연의 주원인인 LLM 생성 시간(전체 생성 시간 및 첫 토큰 시간 TTFT)과 입·출력 토큰 소비량, 요청 성공/실패율을 체계적으로 관측할 수 있도록 지원합니다.

---

## 2. 핵심 지표 목록

RAG LLM 단계에서 수집 및 내보내기되는 4대 핵심 계측기 사양은 다음과 같습니다.

| 지표명 | 종류 (Type) | 단위 (Unit) | 속성 (Attributes) | 의미 및 설명 |
| --- | --- | --- | --- | --- |
| `rag_llm_ttft_ms` | Histogram | `ms` | `backend`, `model` | 스트리밍 응답에서 첫 번째 유효 토큰 청크가 도달할 때까지 소요된 시간(Time To First Token). |
| `rag_llm_generation_ms` | Histogram | `ms` | `backend`, `model` | LLM 호출 시작부터 생성 종료(또는 예외 발생)까지 소요된 총 생성 시간. |
| `rag_llm_tokens` | Counter | `{token}` | `backend`, `model`, `direction` (`input` \| `output`) | LLM 모델이 처리한 입력(프롬프트) 및 출력(생성) 토큰 수. |
| `rag_llm_requests` | Counter | `{request}` | `backend`, `model`, `outcome` (`success` \| `error`) | RAG LLM 호출 요청 총 횟수 및 성공/오류 결과 상태. |

---

## 3. 계측 속성 및 개인정보 보호 (PII 차단)

### 3.1 허용 속성 라벨

모든 지표는 카디널리티 폭발과 개인정보 유출을 방지하기 위해 정형화된 저카디널리티 라벨만 부여합니다.

* `backend`: LLM 백엔드 제공자 식별자 (`ollama`, `gemini`)
* `model`: 구동 중인 모델 식별자 (예: `gemma4:e2b`, `gemini-1.5-flash`)
* `direction`: 토큰 이동 방향 (`input`, `output`)
* `outcome`: 요청 처리 결과 (`success`, `error`)

### 3.2 민감 정보 및 프롬프트 배제 원칙

* 사용자 질의 내용(User Query), 시스템 프롬프트(System Prompt), 모델 응답 본문(Response Text)은 메트릭 속성에 일절 포함되지 않습니다.
* 고차원 식별자나 인증 키(`token`, `secret`, `key` 등)는 계측 라벨로 유입되지 않도록 엄격히 차단됩니다.

---

## 4. 토큰 계측 및 수집 정책

1. **실측 토큰 제공 시에만 기록**: 백엔드 응답이 토큰 사용량을 명시적으로 반환할 때만 `rag_llm_tokens` 지표를 기록합니다.
   * Ollama: 최종 응답 또는 스트리밍 종료 청크의 `prompt_eval_count` (입력) 및 `eval_count` (출력)
   * Gemini: `usage_metadata.prompt_token_count` (입력) 및 `usage_metadata.candidates_token_count` (출력)
2. **추정치 기록 절대 금지**: 백엔드가 토큰 필드를 제공하지 않거나 누락한 경우, 글자 수 기반 토큰 추정치를 계산하지 않고 해당 토큰 지표 기록을 건너뜁니다.

---

## 5. 수명 주기 및 예외 처리 원칙

1. **오류 시 즉각 기록 및 예외 재전파**:
   * 네트워크 타임아웃, HTTP 오류, 백엔드 클라이언트 장애 발생 시 `outcome=error` 속성으로 `rag_llm_requests` 및 생성 소요 시간 `rag_llm_generation_ms`를 1회 기록한 후 예외를 원형 그대로 재전파합니다.
2. **스트리밍 중단 시 중복 기록 방지**:
   * 소비자가 스트림을 끝까지 소비하지 않고 조기 중단(예: GeneratorExit 발생)하더라도 지표가 2회 이상 중복 기록되지 않습니다.
3. **계측 실패 격리**:
   * 메트릭 기록 함수 내부의 예외는 로깅 후 흡수되어 실제 LLM 호출 및 비즈니스 로직의 실패를 유발하지 않습니다.
4. **비활성화 시 무동작 (Zero Overhead)**:
   * `OTEL_ENABLED=False` 또는 `OTEL_METRICS_ENABLED=False` 상태에서는 메트릭 객체가 생성되지 않으며, 기록 함수 호출 시 즉시 반환되어 런타임 오버헤드가 발생하지 않습니다.

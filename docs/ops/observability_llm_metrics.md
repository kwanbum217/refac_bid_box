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

---

## 6. Prometheus 내보내기 지표 명칭 변환 규약

OpenTelemetry Collector의 Prometheus 익스포터(`pkg/translator/prometheus`)를 통해 스크랩 엔드포인트로 노출될 때, 기존 HTTP·DB 지표(`http.server.request.duration` -> `http_server_request_duration_seconds_bucket`, `http.server.request.count` -> `http_server_request_count_total`)와 동일한 명명 규칙을 엄격히 적용합니다.

| OTel 계측기 명칭 | OTel 단위 | 지표 유형 | Prometheus 변환 명칭 | 비고 |
| --- | --- | --- | --- | --- |
| `rag_llm_ttft_ms` | `ms` | Histogram | `rag_llm_ttft_ms_milliseconds_bucket`<br>`rag_llm_ttft_ms_milliseconds_sum`<br>`rag_llm_ttft_ms_milliseconds_count` | OTel Collector의 단위 정규화 규약에 따라 단위 `ms`가 `_milliseconds` 접미사로 결합되고 히스토그램 버킷 접미사가 부여됩니다. |
| `rag_llm_generation_ms` | `ms` | Histogram | `rag_llm_generation_ms_milliseconds_bucket`<br>`rag_llm_generation_ms_milliseconds_sum`<br>`rag_llm_generation_ms_milliseconds_count` | 히스토그램 전체 생성 지연(ms) 관측용. |
| `rag_llm_tokens` | `{token}` | Counter | `rag_llm_tokens_total` | 누적 카운터 지표로 `_total` 접미사가 부여되며 중괄호 단위 주석은 제거됩니다. |
| `rag_llm_requests` | `{request}` | Counter | `rag_llm_requests_total` | 누적 카운터 지표로 `_total` 접미사가 부여됩니다. |

---

## 7. Grafana 대시보드 사양 (`docker/grafana/dashboards/llm_generation.json`)

대시보드 식별자는 `bidbox-llm-generation`이며 기존 대시보드와 동일한 프로비저닝 데이터소스(`uid: prometheus`)와 스키마 버전 39를 사용합니다.

| 패널 ID | 패널 제목 | 단위 | 주요 PromQL 표현식 | 설명 |
| :---: | --- | :---: | --- | --- |
| 1 | TTFT P50 / P95 by backend and model | `ms` | `histogram_quantile(0.95, sum by (le, backend, model) (rate(rag_llm_ttft_ms_milliseconds_bucket[5m])))`<br>`histogram_quantile(0.50, sum by (le, backend, model) (rate(rag_llm_ttft_ms_milliseconds_bucket[5m])))` | 백엔드·모델별 첫 유효 토큰 도착 시간의 5분 P95 및 P50 추이. |
| 2 | Generation duration P95 by backend and model | `ms` | `histogram_quantile(0.95, sum by (le, backend, model) (rate(rag_llm_generation_ms_milliseconds_bucket[5m])))` | 백엔드·모델별 전체 생성 시간의 5분 P95 추이. |
| 3 | LLM request rate by backend and model | `reqps` | `sum by (backend, model) (rate(rag_llm_requests_total[5m]))` | 백엔드·모델별 초당 요청 수. |
| 4 | LLM error rate by backend and model | `percentunit` | `sum by (backend, model) (rate(rag_llm_requests_total{outcome="error"}[5m])) / clamp_min(sum by (backend, model) (rate(rag_llm_requests_total[5m])), 1e-9)` | 백엔드·모델별 LLM 호출 5분 오류율. |
| 5 | Token rate by direction | `short` | `sum by (backend, model, direction) (rate(rag_llm_tokens_total[5m]))` | 입력(input) 및 출력(output) 토큰의 초당 소비 증가율. |

---

## 8. Prometheus 알람 규칙 (`docker/prometheus_rules.yml`)

운영 그룹 `bidbox_slo`에 추가된 3대 RAG LLM 전용 알람 규칙 명세입니다.

| 알람 이름 (Alert) | 심각도 (Severity) | 평가 기간 (for) | 발화 조건 (expr) | 설명 및 임계값 근거 |
| --- | :---: | :---: | --- | --- |
| `RagLlmErrorRateHigh` | `critical` | `5m` | `(sum(rate(rag_llm_requests_total{outcome="error"}[5m])) / clamp_min(sum(rate(rag_llm_requests_total[5m])), 1e-9)) > 0.1` | LLM 호출 5분 오류율이 10%(0.1)를 5분 연속 초과할 때 발화. |
| `RagLlmTtftP95High` | `warning` | `10m` | `histogram_quantile(0.95, sum by (le) (rate(rag_llm_ttft_ms_milliseconds_bucket[5m]))) > 3000` | SSE 첫 토큰 게이트 기준(3초 = 3000ms)과 동일하게 TTFT 5분 P95가 3000ms를 10분 연속 초과할 때 발화. |
| `RagLlmRequestsZeroWithHttpTraffic` | `critical` | `15m` | `sum(rate(rag_llm_requests_total[5m])) == 0 and sum(rate(http_server_request_count_total{http_route="/chatbot/chat/stream"}[5m])) > 0` | 인바운드 챗봇 스트리밍 HTTP 요청은 지속되나 15분 동안 LLM 요청이 0건으로 단절되었을 때 발화. |

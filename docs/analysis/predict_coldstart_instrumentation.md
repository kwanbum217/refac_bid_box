# 예측 API 콜드스타트 세부 구간 계측 및 예열 로깅 보고서

> **작성일**: 2026-08-22
> **과업**: task_7a50318888eb (predict_coldstart_instrumentation)
> **대상 파일**: `src/app/main.py`, `src/app/api/v1/predictions.py`, `tests/test_predict_instrumentation.py`, `tests/test_startup_warmup.py`
> **목적**: 응답 계약 및 스키마 변경 없이 예측 API 콜드스타트 상위 구간별 지연 계측 및 기동 예열 구조화 로그 구축

---

## 1. 개요 및 계측 배경

2026-08-22 실측에서 낙찰가 예측 API는 웜 상태(3~6회차)에서 P95 61.9ms ~ 83.6ms로 목표(100ms)를 충족했으나, 1회차 콜드스타트에서 P95 383.1ms, 2회차 전이 상태에서 P95 122.1ms의 꼬리 지연이 발생했습니다.
기존 계측 로그는 전체 소요 시간(`wall_ms`), 전체 스레드 CPU 시간(`thread_cpu_ms`), 모델 구간 시간(`model_wall_ms`), 모델 스레드 CPU 시간(`model_thread_cpu_ms`), 실행기 대기 시간(`executor_queue_wait_ms`)만 기록하여 세부 단계별 기여도를 파악하기 어려웠습니다.

본 과업에서는 응답 계약(HTTP 상태 코드 및 스키마)과 데이터베이스 스키마를 전혀 변경하지 않고, 콜드스타트 지연의 주요 후보 구간을 `time.perf_counter` 기반의 구조화 로그로 정밀 분리 계측하도록 개선했습니다.

구간 로그는 `LATENCY_SEGMENT_LOGGING=true`일 때만 발행합니다. 기본값은 `false`이며,
정식 레이턴시 게이트에서는 로그 포매팅과 출력 오버헤드를 배제하기 위해 반드시
비활성으로 둡니다.

---

## 2. 세부 구간 분리 계측 설계

### 2.1 공고 기반 예측 경로 (`POST /api/v1/predictions/predict-price`)

공고 기반 예측 경로(`predict_price_api`)의 처리 흐름을 4개 상위 구간으로 분리하여 밀리초(ms) 단위로 계측합니다.

| 구간 명칭 | 계측 필드명 | 계측 시작/종료 지점 | 측정 대상 및 의미 |
| --- | --- | --- | --- |
| **실행기 대기** | `executor_queue_wait_ms` | ASGI 수신 직전 ~ 라우트 함수 진입 | Starlette/AnyIO 워커 스레드 풀 디스패치 대기 시간 |
| **DB 공고 조회** | `db_lookup_ms` | `db.get(BidAnnouncement, ...)` 전후 | SQLAlchemy 커넥션 획득 및 MySQL 공고 단건 조회 시간 |
| **특징 생성** | `feature_build_ms` | 공고 페이로드 조립 ~ `build_feature_dict` 완료 | 원시 JSON 파싱, 기본 특징 구성 및 기관/재발주 이력 DB 조회 시간 |
| **점 추론** | `point_infer_ms` | `predict_optimal_price_with_provenance` 전후 | Champion/Fallback 모델 로드 확인 및 C-Extension 점 추론 시간 |
| **구간 추론** | `interval_infer_ms` | `predict_interval` 전후 | 불확실성 분위수 구간 산출 시간 (구 모델 시 None) |
| **모델 전체** | `model_wall_ms` | `point_infer_ms + interval_infer_ms` | 점 추론과 구간 추론을 합산한 순수 모델 연산 시간 |
| **요청 전체** | `wall_ms` | 라우트 진입 ~ 응답 객체 생성 완료 | 엔드포인트 전체 Wall Clock 시간 |

#### 구조화 로그 포맷:
```text
endpoint=predict_price_api, wall_ms=%.2f, thread_cpu_ms=%.2f, model_wall_ms=%.2f, model_thread_cpu_ms=%.2f, db_lookup_ms=%.2f, feature_build_ms=%.2f, point_infer_ms=%.2f, interval_infer_ms=%.2f
endpoint=predict_price_api, executor_queue_wait_ms=%.2f
```

### 2.2 특징 직접 입력 예측 경로 (`POST /api/v1/predictions/predict`)

특징 직접 입력 경로(`predict_winning_price`)는 Pydantic 페이로드 역직렬화(`payload_dump_ms`)와 모델/배처 실행 시간(`model_wall_ms`)을 분리하여 계측합니다.

| 구간 명칭 | 계측 필드명 | 측정 대상 및 의미 |
| --- | --- | --- |
| **실행기 대기** | `executor_queue_wait_ms` | ASGI 워커 스레드 풀 디스패치 대기 시간 |
| **페이로드 덤프** | `payload_dump_ms` | Pydantic Request 모델 딕셔너리 변환 시간 |
| **모델/배처 실행** | `model_wall_ms` | `predictor.predict` (단건 또는 마이크로배처) 처리 시간 |
| **요청 전체** | `wall_ms` | 엔드포인트 전체 Wall Clock 시간 |

#### 구조화 로그 포맷:
```text
endpoint=predict_winning_price, wall_ms=%.2f, thread_cpu_ms=%.2f, model_wall_ms=%.2f, model_thread_cpu_ms=%.2f, payload_dump_ms=%.2f
endpoint=predict_winning_price, executor_queue_wait_ms=%.2f
```

---

## 3. 기동 예열(`_warm_predictor`) 구조화 로깅

FastAPI Lifespan 백그라운드 태스크로 구동되는 `_warm_predictor`의 실행 상태(성공, 실패, 건너뜀)와 경과 시간(`elapsed_ms`)을 구조화 로그로 명확히 남겨 기동 예열 완료 시점과 실제 서빙 시점의 인과관계를 추적할 수 있도록 개선했습니다.

| 상태 (`status`) | 발동 조건 | 로그 레벨 | 구조화 로그 형식 |
| --- | --- | :---: | --- |
| `skipped` | `SKIP_MODEL_LOAD=true` 환경변수 설정 시 | INFO | `event=predictor_warmup, status=skipped, elapsed_ms=0.00` |
| `success` | `ModelRegistry.load_all_models()` 정상 완료 시 | INFO | `event=predictor_warmup, status=success, elapsed_ms=%.2f, models_loaded=%d` |
| `failed` | 모델 로드 중 예외 발생 시 | WARNING | `event=predictor_warmup, status=failed, elapsed_ms=%.2f, error=%s` |

- **안정성 보장**: 예열 실패(`failed`) 시에도 예외를 흡수(swallow)하여 경고 로그만 남기므로 FastAPI 애플리케이션의 기동을 절대 차단하지 않습니다 (Fail-Open 원칙).

---

## 4. 무손실 및 계약 불변성 보장

1. **응답 스키마 불변 (G1)**: `PredictPriceResponse` 및 `PredictionResponse` Pydantic 모델의 모든 필드 타입과 응답 구조가 기존과 100% 동일하게 유지됩니다.
2. **호출 동등성 및 Fallback 보존**: 모델 부재 시의 Fallback 동작 및 예외 처리(404 공고 없음, 422 금액 없음/비예가, 503 모델 불가)가 변경 없이 보존됩니다.
3. **시간값 일관성**: 모든 구간 시간은 `max(0.0, ...)` 처리를 통해 음수 발생을 방지하며, `model_wall_ms == point_infer_ms + interval_infer_ms` 및 `wall_ms >= model_wall_ms` 관계가 수학적으로 성립합니다.

---

## 5. 검증 결과

### 5.1 단위 및 통합 테스트 (`pytest`)
- `tests/test_predict_instrumentation.py` (5개 테스트 케이스):
  - `test_predict_price_api_instrumentation_and_equivalence`: 구간별 계측 필드 정합성, 응답 동등성, 수치 관계 검증 통과
  - `test_predict_winning_price_instrumentation_and_equivalence`: 직접 입력 경로 계측 필드 및 응답 동등성 검증 통과
  - `test_predict_price_api_fallback_and_interval`: Fallback 발생 시 계측 및 응답 정합성 검증 통과
  - `test_predict_price_api_missing_reference_amount_422`: 금액 부재 시 422 응답 검증 통과
  - `test_predict_price_api_model_failure_503`: 모델 실패 시 503 응답 검증 통과
- `tests/test_startup_warmup.py` (4개 테스트 케이스):
  - `test_predictor_warmup_skipped_when_model_load_disabled`: 건너뜀 로그 및 `elapsed_ms=0.00` 검증 통과
  - `test_predictor_warmup_loads_models`: 성공 로그 및 `models_loaded` 카운트 검증 통과
  - `test_predictor_warmup_swallows_failure`: 실패 시 경고 로그 기록 및 기동 차단 방지 검증 통과
  - `test_llm_warmup_skipped_when_disabled`: LLM 예열 스킵 검증 통과

전체 비데이터 자산 테스트(`uv run pytest tests/ -q -m 'not data_assets'`) 1681건 전량 통과 및 다중 에이전트 규칙 검증(`validate_agent_rules.py`) 12/12건 통과를 확인했습니다.

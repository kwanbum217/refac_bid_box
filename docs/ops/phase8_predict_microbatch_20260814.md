# `/predict` c10 마이크로배칭 병목 분해 및 후보 판정

> **작성일**: 2026-08-14
> **범위**: 실행기 대기·모델 후보 호출 계측, 요청 마이크로배칭 후보 구현
> **기준**: Docker Compose 단일 Uvicorn 워커, 동일 Thng payload, 각 조건 100회
> **상태**: 후보 구현 완료. c1/c2/c4는 통과했으며 c10은 실행별 변동으로 안정 통과를 확정하지 않음

---

## 1. 후보 선택 근거

기존 후보 A 적용 기준 c10 P95는 199.18ms였습니다. 계측 추가 후 같은 조건에서
실행기·요청 준비 구간(`executor_queue_wait_ms`) P95는 12.33ms, 기존 단건
`quantum_leap_v25_pro` 호출 P95는 190.77ms였습니다. 따라서 용량 제한보다 동일
모델 호출을 묶는 요청 마이크로배칭을 단일 후보로 선택했습니다.

오프라인 동일 모델 호출 비교에서도 10건을 개별 호출하면 P95 58.89ms였지만,
10행을 한 번에 LightGBM에 전달하면 P95 1.62ms였습니다. 배치 경로는 물품
기본 모델이며 배치 API를 지원하는 Joblib 래퍼에만 적용하고, Servc·명시 모델·
모델 오류·fallback은 기존 단건 provenance 경로로 되돌립니다.

## 2. 구현

| 파일 | 변경 |
| --- | --- |
| `src/app/main.py` | `/predict`, `/predict-price` ASGI 기준 시각을 request scope에 기록 |
| `src/app/api/v1/predictions.py` | 기존 wall/thread CPU/model 계측을 유지하면서 실행기 대기 계측을 별도 로그로 기록 |
| `src/ml/model_registry.py` | 후보 모델별 단건 호출 및 오류 호출, 동일 Joblib 모델의 배치 호출을 계측; `predict_batch` 추가 |
| `src/ml/predictor.py` | 최대 10건, 5ms 창의 단일 프로세스 마이크로배처; 비대상·오류는 단건 경로로 복귀 |
| `tests/test_predict_instrumentation.py` | 기존 계측 계약과 새 실행기 대기 로그 검증 |

로그 형식은 다음과 같습니다.

```text
endpoint=predict_winning_price, executor_queue_wait_ms=...
model_call=model_id=quantum_leap_v25_pro, status=success, wall_ms=..., thread_cpu_ms=...
model_call=model_id=quantum_leap_v25_pro, status=success, batch_size=..., wall_ms=..., thread_cpu_ms=...
```

`executor_queue_wait_ms`는 ASGI 수신 기준 시각부터 sync 라우트 진입까지의
대기·요청 준비 구간입니다. Starlette/AnyIO 내부 토큰 획득 시각을 직접 노출하는
API가 없으므로, 모델 구간과 비교하는 실행기 대기 상한 계측으로 사용합니다.

## 3. 원시 측정 결과

| 조건 | P50 | P95 | P99 | 오류 | 판정 |
| ---: | ---: | ---: | ---: | ---: | --- |
| c1, 최종 코드 | 12.5ms | 17.0ms | 23.6ms | 0 | 통과 |
| c2, 최종 코드 | 16.7ms | 20.7ms | 22.4ms | 0 | 통과 |
| c4, 최종 코드 | 28.5ms | 42.9ms | 44.8ms | 0 | 통과 |
| c10, 배치 실행 1 | 38.7ms | **67.0ms** | 76.0ms | 0 | 목표 통과 |
| c10, 배치 실행 2 | 42.7ms | 163.3ms | 178.3ms | 0 | 목표 미달 |
| c10, 배치 실행 3 | 41.6ms | 107.6ms | 108.1ms | 0 | 목표 미달 |

원시 JSON은 다음에 보존합니다.

- `data/benchmarks/phase8_predict_batch_final_c1_20260814.json`
- `data/benchmarks/phase8_predict_batch_final_c2_20260814.json`
- `data/benchmarks/phase8_predict_batch_final_c4_20260814.json`
- `data/benchmarks/phase8_predict_batch5_c10_r1_20260814.json`
- `data/benchmarks/phase8_predict_batch5_c10_r2_20260814.json`
- `data/benchmarks/phase8_predict_batch5_c10_20260814.json`

## 4. 동등성·회귀 검증

- `tests/test_feature_map_single_build.py`: Thng 배치 경로와 기존 특징 맵 계약,
  Servc 단건 경로, fallback 단건 경로의 예측값·프레임 동등성 검증
- `tests/test_predict_instrumentation.py`: `/predict`·`/predict-price` 응답
  동등성과 기존 로그 형식, 실행기 대기 로그 검증
- 대상 테스트: 9 passed
- `uv run ruff check src/ml/predictor.py src/ml/model_registry.py`: 통과

## 5. 판정

요청 마이크로배칭은 기준 c10 P95 199.18ms보다 한 실행에서 67.0ms까지 낮췄고,
c1/c2/c4와 HTTP 오류 0건을 보존했습니다. 다만 같은 코드와 표본 수의 반복에서
163.3ms와 107.6ms가 관찰되어 c10 P95 100ms 이하를 안정적으로 달성했다고
표현하지 않습니다. 다음 검증에서는 배치 큐 대기 자체를 별도 계측해 67ms 성공과
반복 꼬리의 차이를 확인해야 합니다.

---

## 6. 코디네이터 검수 (2026-08-14)

### 6.1 예측 동등성 — 통과

`JoblibModelWrapper.predict_batch` 는 `_prepare_full_frame` 이 만든 프레임을
`concat` 하지 않고 `frame.iloc[0].to_dict()` 로 행을 다시 조립합니다. 값이
갈릴 수 있는 지점이므로 실측했습니다.

| 표본 | 결과 |
| --- | --- |
| 정상 5건, 영 금액, 하한율 결측 | 단건과 배치 최대 절대차 **0.0** (비트 단위 일치) |
| 배치 크기 1~7 | 크기를 바꿔도 값 동일 |

구조적 근거도 함께 확인했습니다. `predict_optimal_price_batch` 는 단건 경로와
같은 `_prepare_full_frame` 을 쓰고 `_normalize_prediction_rate` 도 동일하게
적용합니다. `model_id` 를 명시한 요청은 배칭을 우회하고, 모델이 섞이면
`ValueError` 로 단건 provenance 경로로 되돌아갑니다.

이 사실은 `tests/test_predict_microbatch_equivalence.py` 로 고정했습니다.
허용오차는 0 입니다. 기본값 규칙이나 결측 판정이 바뀌면 이 테스트가 먼저
깨집니다.

### 6.2 무응답 위험 제거

검수에서 발견한 문제입니다. `_BatchItem.event.wait()` 에 상한이 없고
`BATCH_WORKERS = 1` 이어서, 배치 스레드가 어떤 이유로든 종료되면 이후 모든
`/predict` 요청이 **오류 없이 영구 대기**합니다. 레이턴시 미달보다 비싼
가용성 손실입니다.

| 조치 | 내용 |
| --- | --- |
| `SUBMIT_TIMEOUT_SECONDS = 5.0` | 대기 상한. 만료 시 호출 스레드가 단건 경로로 직접 처리 |
| `_run` 이 `BaseException` 까지 포착 | 어떤 실패도 배치 스레드를 끝내지 못합니다 |
| `_release` | 실패 시 대기 항목 전부에 오류를 넣고 깨웁니다 |
| 결과 수 검증 | 배치 결과 수가 요청 수와 다르면 명시적으로 실패시킵니다 |

회귀 테스트 2건을 함께 넣었습니다. 배치가 영구히 응답하지 않을 때 단건으로
떨어지는지, 결과 수가 어긋나도 스레드가 살아남아 다음 요청에 응답하는지
확인합니다.

### 6.3 검증 결과

| 항목 | 결과 |
| --- | --- |
| 전량 회귀 | 998 passed / 2 skipped (기준선 994 + 신규 4) |
| ruff | 통과 |
| `validate_agent_rules.py` | 6/6 |

### 6.4 판정

동등성이 보존되고 저동시성 역행이 없으므로 개선분을 병합합니다. **G3 예측
c10 P95 게이트는 미달 상태로 유지합니다.** p50 은 151.24ms 에서 38.7~42.7ms
로 안정적으로 내려갔으나 p95 중앙값이 107.6ms 입니다.

다음 조사 대상은 tail 변동입니다. p50 이 안정적인데 p95 만 흔들리므로 배치 창
대기, 단일 배치 스레드 직렬화, GC 중 무엇이 꼬리를 만드는지 분리해야 합니다.
`BATCH_WORKERS` 를 늘리는 것은 프로세스 증설과 다른 축이므로 기각 목록에
해당하지 않지만, 늘리기 전에 원인을 먼저 특정합니다.

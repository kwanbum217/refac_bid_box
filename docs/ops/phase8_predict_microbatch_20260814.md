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

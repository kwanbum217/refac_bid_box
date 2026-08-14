# `/predict` c10 P95 tail 원인 판정

> **측정일**: 2026-08-14
> **범위**: warm c10, 120회씩 9회, 단일 Uvicorn 프로세스
> **판정**: H2 단일 배치 스레드 직렬화
> **원칙**: 원인 판정 전 `BATCH_WORKERS`와 배치 창 설정은 변경하지 않음

---

## 1. 계측 범위

요청마다 다음 구간을 기록했습니다.

| 구간 | 정의 |
| --- | --- |
| `enqueue_to_pick_ms` | 큐에 넣은 시각부터 배치 스레드가 해당 항목을 `get`한 시각까지 |
| `batch_window_ms` | 해당 항목을 집은 시각부터 `_collect`가 창을 닫은 시각까지 |
| `lightgbm_call_ms` | `self.model.predict(batch)` wall time |
| `residual_after_model_ms` | enqueue 이후 응답 완료까지에서 앞의 세 구간을 뺀 잔여 |

보조 계측으로 배치 전체 처리 시간(`batch_dispatch_ms`), 동일 스레드 CPU 시간,
GC 누적 collection 수, 배치 크기를 함께 기록했습니다. `X-Prediction-Trace-Id`로
HTTP 표본과 서버 trace를 연결했으며, 계측은 `PREDICTION_TAIL_TRACE=true`에서만
로그를 남깁니다.

---

## 2. c10 반복 결과

각 회차의 상위 5% 요청만 tail로 분리했습니다. p95 계산은 기존 벤치마크와 같은
선형 보간 방식입니다.

| 회차 | 표본 P50 | 표본 P95 | tail 큐 대기 평균/최대 | tail 창 평균/최대 | tail LightGBM 평균/최대 | tail 잔여 평균/최대 | tail 배치 크기 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| r4 | 32.0ms | 37.8ms | 3.3/6.1ms | 5.5/6.3ms | 1.5/1.6ms | 13.2/15.8ms | 9:5, 10:1 |
| r5 | 31.0ms | 35.7ms | 7.1/7.4ms | 3.8/3.8ms | 1.5/1.5ms | 9.9/10.7ms | 10:6 |
| r6 | 32.1ms | 69.0ms | 5.6/5.7ms | 4.0/4.0ms | 1.7/1.7ms | 46.5/47.4ms | 10:6 |
| r7 | 31.1ms | 36.1ms | 4.0/5.6ms | 4.0/4.0ms | 1.6/1.6ms | 12.9/15.1ms | 9:5, 10:1 |
| r8 | 31.9ms | 64.8ms | 0.1/0.2ms | 4.2/4.3ms | 36.8/36.8ms | 9.9/10.8ms | 10:6 |
| r9 | 30.7ms | 34.6ms | 5.3/6.2ms | 3.9/4.0ms | 1.5/1.5ms | 10.0/10.7ms | 10:6 |
| r10 | 31.4ms | 75.7ms | 17.5/45.5ms | 6.4/6.4ms | 1.6/1.6ms | 12.7/14.4ms | 9:6 |
| r11 | 30.5ms | 33.9ms | 5.8/8.7ms | 3.9/4.0ms | 1.6/1.9ms | 9.7/10.2ms | 10:6 |
| r12 | 31.1ms | 67.9ms | 3.3/6.5ms | 3.9/3.9ms | 38.6/38.6ms | 10.5/11.2ms | 10:6 |

원시 결과:

- `data/benchmarks/phase8_predict_tail_c10_20260814.json`
- `data/benchmarks/phase8_predict_tail_c10_r2_20260814.json`
- `data/benchmarks/phase8_predict_tail_c10_r3_20260814.json`
- `data/benchmarks/phase8_predict_tail_c10_r4_20260814.json`
- `data/benchmarks/phase8_predict_tail_c10_r5_20260814.json`
- `data/benchmarks/phase8_predict_tail_c10_r6_20260814.json`
- `data/benchmarks/phase8_predict_tail_c10_r7_20260814.json`
- `data/benchmarks/phase8_predict_tail_c10_r8_20260814.json`
- `data/benchmarks/phase8_predict_tail_c10_r9_20260814.json`
- `data/benchmarks/phase8_predict_tail_c10_r10_20260814.json`
- `data/benchmarks/phase8_predict_tail_c10_r11_20260814.json`
- `data/benchmarks/phase8_predict_tail_c10_r12_20260814.json`

---

## 3. H1/H2/H3 판정

### H1 배치 창 대기: 기각

tail의 `batch_window_ms`는 대부분 3.8~4.3ms였고, 가장 큰 회차도 6.4ms였습니다.
p95가 64.8~75.7ms인 r6/r8/r10/r12에서 창 대기만으로는 관측된 꼬리를
설명할 수 없습니다. r10에서 큐 대기 45.5ms가 발생한 요청도 창 대기는 6.4ms에
불과했습니다.

### H2 단일 배치 스레드 직렬화: 특정

tail 요청은 54개 중 38개가 10건 배치, 16개가 9건 배치였으며 단독 1건 배치는
없었습니다. 특히 r10에서 다음 현상이 직접 관측되었습니다.

| 배치 | 배치 크기 | 배치 전체 처리 | LightGBM wall/CPU | 다음 배치 요청 큐 대기 |
| ---: | ---: | ---: | ---: | ---: |
| 33 | 1 | 45.9ms | 1.45ms / 1.45ms | 배치 34에서 최대 45.5ms |
| 34 | 9 | 11.1ms | 1.55ms / 1.55ms | 해당 없음 |

즉 단일 배치 스레드가 앞 배치의 처리를 끝낼 때까지 뒤 요청이 큐에서
기다리는 구간이 p95 tail에 그대로 전달됩니다. 별도 회차 r12에서는 배치 크기
10의 LightGBM 호출이 38.6ms로 늘었고 같은 배치의 6개 tail 요청이 함께
느려졌습니다. wall 38.6ms와 스레드 CPU 38.6ms가 일치하므로, 이 변동도
단일 배치 스레드에서 직렬로 수행되는 모델 호출 시간이 요청 묶음 전체에
전파된 사례입니다.

### H3 GC 또는 프로세스 일시 정지: 기각

최근 계측 회차의 tail 24개에서 LightGBM wall-스레드 CPU 차이는 중앙값 0.01ms,
최대 0.03ms였습니다. r12의 38.6ms tail도 CPU 시간이 38.57ms로 거의 전부
실행 시간이었고, stop-the-world 대기 형태가 아닙니다. tail의 GC 누적 수는
0보다 큰 값이 모두 관측됐지만, GC가 없는 정상 요청과 비교할 수 있는
`0건`이 없고 회차별 4~9회로 일정한 누적 증가 패턴이므로 tail과의 인과 증거가
아닙니다.

---

## 4. 수정 후보

원인에 직접 대응하는 단일 후보는 `BATCH_WORKERS = 2`로 늘리는 것입니다.
첫 번째 배치 스레드가 긴 모델 호출 또는 전처리를 수행하는 동안 두 번째
스레드가 다음 배치를 집을 수 있어 H2의 큐 대기를 완화할 수 있습니다.
이번 작업에서는 설정을 변경하거나 성능 개선을 통과로 선언하지 않았습니다.
후속 구현 시 `tests/test_predict_microbatch_equivalence.py`의 허용오차 0과
c1/c2/c4 회귀를 먼저 확인하고, 동일 계측으로 c10 p95를 재측정해야 합니다.

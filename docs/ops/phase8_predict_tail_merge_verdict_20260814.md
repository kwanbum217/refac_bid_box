# `perf/predict-tail` 병합 판정

> **작성일**: 2026-08-14
> **판정 주체**: 코디네이터 (Claude Opus 5). `git diff main...perf/predict-tail` 직접 검수
> **대상**: `perf/predict-tail` `0fd489a` (커밋 4개)
> **판정**: **계측 하네스 병합 불가.** 진단 도구는 브랜치에 보존하고 벤치마크 스크립트만 선별 병합합니다

---

## 1. 왜 이 판정이 필요했는가

[`2026-08-14_session_handoff.md`](../handoff/2026-08-14_session_handoff.md) 2장이 이
브랜치의 병합 관문으로 다음을 지정했습니다.

> 계측 비활성 시 추가 호출과 객체 생성이 0 인지. `e023bd2` 시점에는
> `gc.get_stats()` 와 trace dict 가 요청마다 실행됐습니다. `a6b34df` 에서
> 고쳤다고 보고했으나 코디네이터가 diff 로 확인하지 않았습니다

diff 를 읽은 결과 **`a6b34df` 의 수정은 불완전합니다.** 아래 세 항목이 계측
비활성 상태에서도 요청마다 비용을 냅니다. 그리고 검수 과정에서 보고에 없던
관측성 회귀 1건을 추가로 발견했습니다.

---

## 2. 코드 변경 규모

전체 diff 는 457,688줄이지만 검수 대상인 코드는 4개 파일입니다.

| 파일 | 변경 | 성격 |
| --- | ---: | --- |
| `src/ml/predictor.py` | +257/-11 | 추론 hot path |
| `src/ml/model_registry.py` | +112/-14 | 추론 hot path |
| `src/app/api/v1/predictions.py` | +14/-2 | 요청 엔드포인트 |
| `scripts/benchmark_predict_tail.py` | +216 (신규) | 독립 스크립트 |

나머지 457,089줄은 `data/benchmarks/` 원시 측정치 JSON 55개(14.2MB)입니다.

---

## 3. 계측 비활성 시 잔존 비용

### 3.1 `_BatchItem` 속성 14개가 무조건 추가됩니다

`src/ml/predictor.py` 의 `_BatchItem.__init__` 은 `PREDICTION_TAIL_TRACE` 와
무관하게 다음을 매 요청 생성합니다.

```
trace_id, enqueued_ns, batch_timing, picked_ns, batch_id,
batch_window_start_ns, batch_window_end_ns, batch_size,
lightgbm_call_ms, lightgbm_thread_cpu_ms, batch_dispatch_ms,
batch_dispatch_thread_cpu_ms, model_end_ns, result_assembled_ns
```

**이것이 가장 심각한 항목입니다.** 이 브랜치가 규명한 원인이
generation-2 GC 이고, 인스턴스 속성 증가는 객체당 `__dict__` 크기와 추적
대상 객체 수를 늘려 **바로 그 GC 압력을 키우는 방향**입니다. 원인을 찾은
계측기가 원인을 악화시키는 구조로는 병합할 수 없습니다.

### 3.2 엔드포인트가 무조건 두 가지를 더 합니다

`src/app/api/v1/predictions.py`

| 항목 | 내용 |
| --- | --- |
| `t_model_start_ns = time.perf_counter_ns()` | 게이트 밖. 무조건 실행 |
| `finalize_prediction_tail_trace(result, time.perf_counter_ns(), ...)` | 인자 평가가 먼저 일어나므로 함수 내부 게이트가 막지 못함 |
| `http_response: Response` 파라미터 추가 | FastAPI 가 요청마다 `Response` 객체를 주입. 계측 비활성에도 할당됨 |

호출 2회는 나노초 수준이라 지연 자체는 문제가 아닙니다. `Response` 객체
주입은 3.1 과 같은 성격의 요청당 할당입니다.

### 3.3 `_predict_batch` 가 배처 사설 속성을 읽습니다

`SingletonPredictor._predict_batch` 가 `self._batcher._trace_enabled` 로 다른
객체의 사설 속성을 참조합니다. 동작은 하지만 계측 제거 시 함께 지워야 하는
결합이 하나 더 생깁니다.

---

## 4. 보고에 없던 회귀 1건

`src/ml/model_registry.py` 의 `predict_optimal_price_batch` 에서 **기존 운영
관측성 로그가 삭제됐습니다.**

```
-    latency_logger.info(
-        "model_call=model_id=%s, status=success, batch_size=%d, wall_ms=%.2f, thread_cpu_ms=%.2f",
```

이 줄은 `main` 에서 배치 모델 호출의 wall/CPU 시간을 남기는 유일한 지점입니다.
`timing` dict 로 대체됐다고 볼 수 있으나, `timing` 은 계측 활성 시에만 채워지고
로그로 나가지 않습니다. 즉 **병합하면 운영 상태에서 배치 모델 호출 지연을
관측할 수단이 사라집니다.** 워커의 `worker_done` 에 이 삭제는 언급되지
않았습니다.

---

## 5. 판정과 처리

| 커밋 | 내용 | 판정 |
| --- | --- | --- |
| `b8a080d` | tail 구간 계측 결과 문서 | 이미 `main` 반영됨 (`5989e78`) |
| `e023bd2` | 요청 구간 계측 코드 | **병합 불가.** 3장, 4장 |
| `a6b34df` | 근본 원인 계측과 GC 대조 | **병합 불가.** 같음 |
| `0fd489a` | 벤치마크 하네스와 산출물 | **선별 병합.** `scripts/benchmark_predict_tail.py` 만 |

### 5.1 계측 하네스를 브랜치에 남기는 이유

폐기하지 않습니다. 이 하네스가 generation-2 GC 원인을 특정했고, 후속 GC 튜닝
후보를 검증할 때 같은 계측이 다시 필요합니다. `perf/predict-tail` 을 **진단
전용 브랜치**로 유지하고, 재측정이 필요할 때 그 브랜치에서 서버를 띄웁니다.

프로덕션 hot path 에 계측을 상주시키려면 다음을 만족하는 재작성이 필요합니다.
현재 브랜치는 셋 다 만족하지 않습니다.

1. 계측 비활성 시 `_BatchItem` 속성 수가 `main` 과 동일할 것 (별도 trace 객체를
   활성 시에만 붙이는 구조)
2. 엔드포인트에서 게이트 밖 호출이 0 일 것
3. `model_call=` 운영 로그를 유지할 것

### 5.2 벤치마크 스크립트를 병합하는 이유

`scripts/benchmark_predict_tail.py` 는 hot path 와 무관한 독립 스크립트입니다.
trace 헤더가 없으면 `trace_id` 를 `None` 으로 두고 계속 동작하므로, 계측 없는
`main` 에서도 end-to-end 지연 벤치마크로 쓸 수 있습니다. Phase 7 재측정에
필요한 도구라 `main` 에 둡니다.

### 5.3 원시 측정치 JSON

`data/benchmarks/` 는 `main` 에서 이미 45개 파일을 추적하고 있어 관례상
문제가 없습니다. 다만 이 브랜치의 55개 14.2MB 중 단일 파일 173,203줄
(`..._instrumented_c10_long_...`) 같은 것은 과합니다. 분석에 실제로 쓰인
파일만 병합하고 나머지는 브랜치에 둡니다.

---

## 6. 이 판정이 남긴 후속 작업

| 순서 | 작업 | 상태 |
| ---: | --- | --- |
| 1 | 표본 수 효과 분리와 100ms 초과율 산출 | 진행 중 (`task_ea703513dd98`) |
| 2 | GC 튜닝 후보 3종 안전성 조사 (RSS 추이 필수) | 미착수 |
| 3 | 계측 하네스 무비용 재작성 (5.1 의 세 조건) | 미착수. 2번 결과에 따라 필요 여부 결정 |

2번을 하려면 `perf/predict-tail` 의 계측을 다시 켜야 합니다. **그 브랜치에서
띄우십시오.** `main` 에 계측을 넣지 말고 진행합니다.

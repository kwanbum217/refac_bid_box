# Arq 정식 기준선 캘리브레이션 결과 (2026-08-24)

> **작성일**: 2026-08-24 (Asia/Seoul)
> **observed_commit**: `0ab8c3e`
> **status**: current
> **설계 근거**: [`arq_calibration_design_20260824.md`](arq_calibration_design_20260824.md) 3장 고정 조건, 4장 회차 수, 6장 도출식
> **판정**: 두 경로 모두 **신뢰 가능**. `scripts/arq_gate.py` 의 잠정 임계값을 실측 기준선으로 교체함

---

## 1. 배경

`scripts/arq_gate.py` 의 `RepetitionThresholds` 는 900 jobs/sec, 600ms P95 였다. 이 값은
어떤 통계적 도출식으로도 재현되지 않는 사후 보정된 잠정 봉투임이
[`arq_threshold_derivation_20260823.md`](arq_threshold_derivation_20260823.md) 에서 확인됐다.
본 문서는 그 값을 대체할 정식 기준선의 측정 결과와 도출 과정을 기록한다.

---

## 2. 측정 조건

설계서 3.1 고정 조건을 그대로 적용했다. 사전 점검을 통과하지 못하면 측정을 시작하지
않는 실행기를 사용했다.

| 항목 | In-Process | Container |
| --- | ---: | ---: |
| 총 작업 수 | 600 | 600 |
| 동시성 | 10 | 4 |
| 작업 지연 | 0.0ms | 0.0ms |
| 폴링 주기 | 0.01s | 0.01s |
| 인위 실패율 | 0.0 | 0.0 |
| 회차 수 | 10 | 10 |
| 회차 간격 | 30s | 30s |

측정 시작 시 주변 부하는 중앙값 26.14% / 최대 26.33% 로 규약(중앙값 30%, 최대 50%)을
통과했다. Redis 컨테이너는 `refac_bid_box-redis-1` 단일 후보로 결박했다.

---

## 3. 측정 결과

| 경로 | n | 처리량 median | CV | MAD/median | P95 median | CV | MAD/median | 규약 위반 회차 | 판정 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :---: |
| In-Process | 10 | 1,195.59 jps | 0.0172 | 0.0092 | 480.42ms | 0.0162 | 0.0070 | 0 | **stable** |
| Container | 10 | 1,756.94 jps | 0.0145 | 0.0045 | 327.06ms | 0.0154 | 0.0042 | 0 | **stable** |

반복 안정성 임계(`CV <= 0.05`, `MAD/median <= 0.03`)를 두 경로 모두 크게 밑돈다.
`non_canonical_runs` 가 0 이므로 부하 규약을 위반한 회차가 기준선에 섞이지 않았다.

회차별 raw 와 기준선 요약은 `data/benchmarks/frozen/arq/<mode>/0ab8c3e/` 에 있다.

---

## 4. 기준선 도출

설계서 6장 산식을 그대로 적용했다.

```
throughput_baseline = median(T)
p95_baseline        = median(P)

rt = max(3 * CV(T), 0.06)
rp = max(3 * CV(P), 0.06)

min_throughput = median(T) * (1 - rt)
max_p95        = median(P) * (1 + rp)
```

두 경로 모두 `3 * CV` 가 0.043~0.052 로 하한 0.06 보다 작아 `rt = rp = 0.06` 이 적용됐다.
하한 0.06 은 반복 안정성 임계 `cv_max = 0.05` 보다 엄격히 크게 두어, 정상 변동 범위 안의
측정이 회귀로 오탐되지 않게 한다.

| 지표 | 기존 (임의값) | In-Process | Container |
| --- | ---: | ---: | ---: |
| `min_throughput_tasks_per_sec` | 900.0 | **1,123.85** | **1,651.52** |
| `max_p95_latency_ms` | 600.0 | **509.25** | **346.68** |
| `min_runs` | 3 | 3 | 3 |
| `max_failure_rate` | 0.0 | 0.0 | 0.0 |

---

## 5. 경로 분리가 필요한 이유

두 경로의 처리량은 **1.47배** 차이나고 P95 는 **1.47배** 차이난다. 단일 임계값으로는
어느 쪽도 판정할 수 없다.

- 기존 900 jps 하한은 In-Process 실측(1,195 jps)의 **75% 수준**이라 25% 열화까지 통과시킨다.
- Container 실측(1,757 jps) 기준으로는 절반 아래로 떨어져도 PASS 가 된다.
- 600ms P95 상한은 실측 327~480ms 대비 과도하게 느슨해 사실상 게이트로 동작하지 않았다.

따라서 `WORKER_MODE_THRESHOLDS` 로 경로별 프리셋을 두고, evidence 의
`benchmark_worker_mode` 로 자동 판별한다.

---

## 6. Fail-closed 동작

| 상황 | 동작 |
| --- | --- |
| 반복 evidence 의 경로가 섞임 | 판정하지 않고 `ValueError` 로 중단 |
| 기준선이 없는 경로 | 기본값으로 넘어가지 않고 `ValueError` 로 중단 |
| `benchmark_worker_mode` 필드 누락 | 조용히 통과시키지 않고 `ValueError` 로 중단 |
| `--mode` 로 명시 지정 | 자동 판별보다 우선 적용 |

---

## 7. 잔여 사항

- 본 기준선은 이 호스트의 실측값이다. 다른 장비에서는 재캘리브레이션이 필요하다.
- 측정 대상은 합성 noop 작업이며 production business-task E2E 성능이 아니다.
- Windows Docker Desktop 실기 환경의 기준선은 장비 부재로 미측정이다.

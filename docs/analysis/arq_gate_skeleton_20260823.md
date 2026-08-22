# Arq 처리량 일관성 게이트 (2026-08-23)

> **작성일**: 2026-08-23
> **Task ID**: `arq_throughput_gate_20260823` (B2)
> **Companion**: 측정 Task `arq_throughput_measure_20260823` (B1, Antigravity 풀 워커)

---

## 1. 동기

핸드오프 6.2 unknowns였던 Arq 처리량은 600건 3회 반복 측정과 원시값 보존까지 수행했습니다. 이 문서는 상대 회귀 비교와 절대 반복 게이트를 모두 기계 판정하는 구현을 기록하며, 실제 운영 worker 컨테이너 업무 큐와 G3 전체 컷오버는 별도 검증 대상입니다.

## 2. 골격 결정

| 지표 | 임계치 | 의미 |
| --- | --- | --- |
| 처리량 | `-10%` 이내 | current_tasks_per_sec >= baseline * 0.9 |
| P95 latency | `+10%` 이내 | current_p95_ms <= baseline * 1.1 |
| 실패율 | `+1pp` 이내 | current_failure_rate - baseline_failure_rate <= 0.01 |

## 3. 게이트 판정 동작

`scripts/arq_gate.py`는 두 경로를 제공합니다.

- `evaluate_throughput_gate(baseline, current, thresholds=None)`: baseline/current strict evidence를 처리량 -10%, P95 +10%, 실패율 +1pp 기준으로 비교.
- `evaluate_repetition_gate(samples, thresholds=None)`: 최소 3회, 최악 회차 기준으로 처리량 >=900 jobs/sec, P95 <=600ms, 실패율 0%를 판정. CLI는 `--repetition`을 여러 번 지정합니다.

## 4. 검증 결과

`tests/test_arq_gate.py` 14 passed:

| ID | 검증 |
| --- | --- |
| `test_all_metrics_pass_when_within_margins` | 모든 지표 baseline과 동등 → PASS |
| `test_throughput_drop_beyond_margin_fails` | 처리량 -20% (>10%) → throughput FAIL |
| `test_p95_latency_inflate_beyond_margin_fails` | P95 +20% (>10%) → p95 FAIL |
| `test_failure_rate_inflate_beyond_margin_fails` | 실패율 +1.5pp (>1pp) → failure FAIL |
| `test_thresholds_overrides_change_pass_status` | 같은 표본에 strict vs permissive 임계치 적용 시 결과 갈림 |
| 반복 게이트 테스트 4건 | 3회 요구, 절대 기준 PASS/FAIL, 사용자 임계치, strict JSON 다중 파일 읽기 |

## 5. 실측 판정

- 검증 원시값: `data/benchmarks/arq_throughput_20260823_verification_r1.json`, `r2.json`, `r3.json`.
- 기계 판정: 최악 처리량 1,138.77 jobs/sec, 최악 P95 504.941ms, 실패율 0%로 반복 게이트 PASS.
- 이 PASS는 Redis 연계 in-process 합성 하네스 범위이며, 실제 worker 컨테이너의 업무 큐 처리량이나 G3 전체 컷오버 판정으로 확장하지 않는다.

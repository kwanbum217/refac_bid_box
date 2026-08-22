# Arq 처리량 일관성 게이트 골격 (2026-08-23)

> **작성일**: 2026-08-23
> **Task ID**: `arq_throughput_gate_20260823` (B2)
> **Companion**: 측정 Task `arq_throughput_measure_20260823` (B1, Antigravity 풀 워커)

---

## 1. 동기

핸드오프 6.2 unknowns: Arq 태스크 처리량과 단발 RAG/LLM 내부 구간은 계측 배선만 완료되었고, 반복 게이트 판정은 미수행. 본 문서는 그 골격을 마련한다. B1 측정 결과 도착 후 임계치 정밀화는 보조 task로 분리 진행한다.

## 2. 골격 결정

| 지표 | 임계치 | 의미 |
| --- | --- | --- |
| 처리량 | `-10%` 이내 | current_tasks_per_sec >= baseline * 0.9 |
| P95 latency | `+10%` 이내 | current_p95_ms <= baseline * 1.1 |
| 실패율 | `+1pp` 이내 | current_failure_rate - baseline_failure_rate <= 0.01 |

## 3. 게이트 판정 동작

`scripts/arq_gate.py`의 `evaluate_throughput_gate(baseline, current, baseline_throughput, current_throughput, thresholds=None)`:
- 단일 입력 baseline/current 표본 + 측정된 throughput으로 3개 지표 마진 검사.
- 미주입 시 보수 기본 임계치 사용.
- 결과는 `ThroughputGateResult(verdicts: list[GateVerdict])` 형태로 PASS 또는 한 지표 이상 FAIL.

## 4. 회귀 검증

`tests/test_arq_gate.py` 5 passed:

| ID | 검증 |
| --- | --- |
| `test_all_metrics_pass_when_within_margins` | 모든 지표 baseline과 동등 → PASS |
| `test_throughput_drop_beyond_margin_fails` | 처리량 -20% (>10%) → throughput FAIL |
| `test_p95_latency_inflate_beyond_margin_fails` | P95 +20% (>10%) → p95 FAIL |
| `test_failure_rate_inflate_beyond_margin_fails` | 실패율 +1.5pp (>1pp) → failure FAIL |
| `test_thresholds_overrides_change_pass_status` | 같은 표본에 strict vs permissive 임계치 적용 시 결과 갈림 |

## 5. 잔여 작업 (B1 측정 도착 후 결정)

- B1 측정 데이터가 도착하면 골격의 임계치를 실측치 기준으로 보수 조정. 기본값은 보수적 기본선을 유지한다.
- 본 모듈은 P2-3R을 거친 strict JSON 헬퍼와 결합하지 않아 의존성 최소화. 추후 evidence 데이터 ingest 모듈은 `scripts/_strict_json.py`의 `load_strict_json`을 사용해 일관성 유지.
- B1 산출물 `data/benchmarks/arq_throughput_20260823.json`이 도착하면 별도 task에서 본 골격과 직접 wire-up + 잠정 G3 Cutover의 일관성 게이트 결과 보고서를 작성.

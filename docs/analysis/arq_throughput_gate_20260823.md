# Arq 처리량 일관성 게이트 판정

> **작성일**: 2026-08-23
> **판정 도구**: [`scripts/arq_gate.py`](../../scripts/arq_gate.py)
> **검증 원시값**: [`r1`](../../data/benchmarks/arq_throughput_20260823_verification_r1.json), [`r2`](../../data/benchmarks/arq_throughput_20260823_verification_r2.json), [`r3`](../../data/benchmarks/arq_throughput_20260823_verification_r3.json)
> **범위**: Redis 연계 in-process Arq Worker 합성 하네스

---

## 1. 기준

| 항목 | 기준 |
| --- | ---: |
| 최소 반복 | 3회 |
| 처리량 | 900 jobs/sec 이상 |
| Enqueue-to-Complete P95 | 600ms 이하 |
| 실패율 | 0% |

회차 하나라도 기준을 벗어나거나 반복 수가 부족하면 FAIL입니다. 이 절대 반복 게이트와 별개로 `--baseline/--current` 경로는 처리량 -10%, P95 +10%, 실패율 +1pp 상대 회귀를 판정합니다.

## 2. 검증 측정

| 회차 | 처리량 (jobs/sec) | P95 (ms) | 실패율 | 판정 |
| ---: | ---: | ---: | ---: | :---: |
| 1 | 1,165.18 | 492.452 | 0.00% | PASS |
| 2 | 1,138.77 | 504.941 | 0.00% | PASS |
| 3 | 1,158.08 | 495.597 | 0.00% | PASS |
| **최악 대표** | **1,138.77** | **504.941** | **0.00%** | **PASS** |

실행 결과:

```text
uv run python scripts/arq_gate.py --repetition ...r1.json --repetition ...r2.json --repetition ...r3.json
PASS
```

## 3. 상대 재현성 확인

초기 대표 원시값([`arq_throughput_20260823.json`](../../data/benchmarks/arq_throughput_20260823.json))과 검증 Run 2를 상대 비교했습니다.

| 지표 | 초기 대표 | 검증 Run 2 | 변화 | 기준 | 판정 |
| --- | ---: | ---: | ---: | ---: | :---: |
| 처리량 | 1,150.48 | 1,138.77 | -1.02% | -10% 이내 | PASS |
| P95 | 499.457ms | 504.941ms | +1.10% | +10% 이내 | PASS |
| 실패율 | 0.00% | 0.00% | +0pp | +1pp 이내 | PASS |

## 4. 제한 사항

- 초기 측정 파일은 대표 Run 1개였으므로 검증 3회의 raw JSON을 별도 보존했습니다.
- 하네스는 전용 Redis 큐에 in-process Worker를 띄우며, Docker `worker` 컨테이너의 실제 업무 큐 소비량을 측정하지 않습니다.
- 따라서 본 판정은 Arq 합성 하네스의 반복 일관성 PASS이며 G3 전체 컷오버 PASS가 아닙니다.

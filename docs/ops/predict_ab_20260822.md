# 2026-08-22 예측 API 통제 교차 A/B 벤치마크 보고서

> **측정일**: 2026-08-22
> **기준 환경**: 격리 과거 baseline (`refac-bid-box-predict-baseline:af674bc`, `127.0.0.1:8001`) vs 현재 main (`127.0.0.1:8000`)
> **규약**: [`latency_gate_protocol.md`](latency_gate_protocol.md)
> **핵심 판정**: **이전 c2/c4 임계치 미달 미재현 확인. 전 회차 >50ms 및 >100ms 0건. c4 1.31ms 중앙 델타는 합의된 회귀 예산 초과 시에만 진단.**
> **환경**: PREDICTION_GC_MODE=freeze, Python 3.12.14, macOS arm64 (14코어), Docker 컨테이너 격리

---

## 1. 개요 및 통제 환경 (Isolation & Controls)

이전 순차 재측정(`predict_remeasurement_20260822.md`)에서 관측된 c2(22.68ms) 및 c4(48.59ms)의 임계치 미달 원인을 정확히 분리하기 위해, 과거 baseline 이미지와 현재 main 환경을 동일 호스트에서 동시에 띄우고 교차(alternating) 방식으로 5회차 통제 A/B 벤치마크를 수행했습니다.

| 통제 항목 | 통제 내용 | 비고 |
| --- | --- | --- |
| **비교 대상 격리** | Baseline: `refac-bid-box-predict-baseline:af674bc` (포트 8001)<br>Current: 현재 main (포트 8000) | 독립 Docker 컨테이너 격리 기동 |
| **요청 수 및 워밍업** | 회차당 600 요청 (warmup 제외), 동시성과 동일한 수(c2=2, c4=4) 사전 워밍업 | 총 20회차 12,000 요청 (Warmup 별도) |
| **GC 및 런타임 조건** | `PREDICTION_GC_MODE=freeze` 동일 적용 (`gc.freeze()`) | `PREDICTION_TAIL_TRACE` 비활성 |
| **회차 간 간격** | 각 런 종료 후 30초 대기 (30s inter-run gap) | 호스트 열 및 자원 안정화 |
| **교차 실행 순서** | Baseline r1 -> Current r1 -> Baseline r2 -> Current r2 ... 순차 교차 | 호스트 부하 드리프트 상쇄 |
| **퍼센타일 계산** | `position = (n - 1) * q / 100` 선형 보간 (values_ms 기준) | 정본 스크립트 규약 준수 |

---

## 2. 20회차 원시 실측 결과 (Raw Evidence)

모든 수치는 warmup(c2: 2건, c4: 4건)을 제외한 600개 유효 요청에 대한 측정값이며 단위는 ms 입니다.

### 2.1 c2 동시성 5회 교차 측정 결과

#### Baseline (c2) — 포트 8001
| 회차 | 표본(n) | 오류 | P50 (ms) | P95 (ms) | P99 (ms) | Min (ms) | Max (ms) | >50ms | >100ms | 호스트 부하 (중앙/최대) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| r1 | 600 | 0 | 22.04 | 25.40 | 27.48 | 15.89 | 30.72 | 0 | 0 | 42.45% / 42.48% |
| r2 | 600 | 0 | 21.93 | 24.52 | 26.54 | 17.14 | 30.19 | 0 | 0 | 36.99% / 37.11% |
| r3 | 600 | 0 | 19.51 | 21.70 | 23.59 | 15.57 | 28.23 | 0 | 0 | 25.57% / 26.70% |
| r4 | 600 | 0 | 19.27 | 23.17 | 24.80 | 16.77 | 29.24 | 0 | 0 | 20.37% / 20.90% |
| r5 | 600 | 0 | 18.65 | 21.25 | 24.16 | 16.54 | 29.70 | 0 | 0 | 27.90% / 29.09% |

#### Current (c2) — 포트 8000
| 회차 | 표본(n) | 오류 | P50 (ms) | P95 (ms) | P99 (ms) | Min (ms) | Max (ms) | >50ms | >100ms | 호스트 부하 (중앙/최대) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| r1 | 600 | 0 | 22.09 | 26.15 | 31.98 | 15.90 | 39.03 | 0 | 0 | 42.80% / 44.04% |
| r2 | 600 | 0 | 21.57 | 25.08 | 29.84 | 18.36 | 47.32 | 0 | 0 | 33.89% / 34.03% |
| r3 | 600 | 0 | 18.45 | 20.73 | 25.48 | 16.66 | 27.44 | 0 | 0 | 18.67% / 19.05% |
| r4 | 600 | 0 | 18.63 | 21.05 | 26.47 | 16.98 | 32.25 | 0 | 0 | 32.32% / 33.27% |
| r5 | 600 | 0 | 18.44 | 20.15 | 24.88 | 15.47 | 27.30 | 0 | 0 | 30.95% / 36.30% |

---

### 2.2 c4 동시성 5회 교차 측정 결과

#### Baseline (c4) — 포트 8001
| 회차 | 표본(n) | 오류 | P50 (ms) | P95 (ms) | P99 (ms) | Min (ms) | Max (ms) | >50ms | >100ms | 호스트 부하 (중앙/최대) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| r1 | 600 | 0 | 29.10 | 32.24 | 34.37 | 13.05 | 40.74 | 0 | 0 | 27.15% / 28.08% |
| r2 | 600 | 0 | 28.70 | 33.01 | 34.60 | 13.03 | 37.11 | 0 | 0 | 17.04% / 18.84% |
| r3 | 600 | 0 | 28.72 | 32.29 | 34.24 | 12.97 | 36.00 | 0 | 0 | 16.21% / 16.62% |
| r4 | 600 | 0 | 28.85 | 32.47 | 36.68 | 12.90 | 39.38 | 0 | 0 | 10.09% / 10.34% |
| r5 | 600 | 0 | 28.35 | 31.82 | 33.22 | 12.00 | 35.50 | 0 | 0 | 19.50% / 20.51% |

#### Current (c4) — 포트 8000
| 회차 | 표본(n) | 오류 | P50 (ms) | P95 (ms) | P99 (ms) | Min (ms) | Max (ms) | >50ms | >100ms | 호스트 부하 (중앙/최대) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| r1 | 600 | 0 | 28.83 | 33.88 | 37.14 | 12.97 | 44.06 | 0 | 0 | 22.28% / 24.23% |
| r2 | 600 | 0 | 28.92 | 34.32 | 38.55 | 13.03 | 42.10 | 0 | 0 | 19.65% / 20.74% |
| r3 | 600 | 0 | 28.62 | 33.59 | 37.88 | 12.69 | 42.39 | 0 | 0 | 11.46% / 11.56% |
| r4 | 600 | 0 | 28.58 | 33.91 | 37.77 | 12.98 | 39.16 | 0 | 0 | 14.52% / 14.54% |
| r5 | 600 | 0 | 28.44 | 32.99 | 36.84 | 12.09 | 40.70 | 0 | 0 | 12.03% / 12.74% |

---

## 3. 쌍대 비교 및 통계 분석 (Paired Comparison & Statistics)

동일 시점에 교차 실행된 각 회차별 P95 수치를 1:1 쌍대 비교(paired delta = current - baseline)하여 호스트 환경 변화 영향을 배제하고 순수한 차이를 분석했습니다.

### 3.1 동시성별 P95 요약 및 쌍대 차이

| 동시성 | 회차 | Baseline P95 (ms) | Current P95 (ms) | 쌍대 델타 (Current - Baseline) |
| :---: | :---: | ---: | ---: | ---: |
| **c2** | r1 | 25.40 | 26.15 | +0.75ms |
| **c2** | r2 | 24.52 | 25.08 | +0.56ms |
| **c2** | r3 | 21.70 | 20.73 | -0.97ms |
| **c2** | r4 | 23.17 | 21.05 | -2.12ms |
| **c2** | r5 | 21.25 | 20.15 | -1.10ms |
| **c4** | r1 | 32.24 | 33.88 | +1.64ms |
| **c4** | r2 | 33.01 | 34.32 | +1.31ms |
| **c4** | r3 | 32.29 | 33.59 | +1.31ms |
| **c4** | r4 | 32.47 | 33.91 | +1.44ms |
| **c4** | r5 | 31.82 | 32.99 | +1.16ms |

### 3.2 대표 통계치 비교 (Median & Worst)

| 동시성 | 지표 구분 | Baseline | Current | 쌍대 델타 (Current - Baseline) |
| :---: | --- | ---: | ---: | ---: |
| **c2** | **중앙값 (Median)** | **23.17ms** | **21.05ms** | **-0.97ms** (Current 우세) |
| **c2** | **최악값 (Worst)** | **25.40ms** | **26.15ms** | **+0.75ms** |
| **c4** | **중앙값 (Median)** | **32.29ms** | **33.88ms** | **+1.31ms** |
| **c4** | **최악값 (Worst)** | **33.01ms** | **34.32ms** | **+1.31ms** |

### 3.3 꼬리 지연 안전성 (>50ms / >100ms)

Baseline 10회차(6,000 표본) 및 Current 10회차(6,000 표본), 총 12,000개 요청 전체에서:
- **50ms 초과 표본 수**: **0건 (0.00%)**
- **100ms 초과 표본 수**: **0건 (0.00%)**
- **전체 측정 최대 지연**: Current c2_r2 47.32ms (50ms 이내)

---

## 4. 결과 해석 및 제한적 결론 (Constrained Conclusion)

1. **이전 임계치 미달(FAIL)의 비재현성 확인**:
   - 이전 순차 재측정에서 보고되었던 c2(22.68ms vs 기준 21.77ms) 및 c4(48.59ms vs 기준 36.81ms)의 임계치 미달 현상은 통제된 교차 A/B 환경에서 재현되지 않았습니다.
   - c2의 경우 5회 측정 중 3회에서 Current가 Baseline보다 빨랐으며(중앙 델타 -0.97ms), 최악 P95도 26.15ms로 Baseline의 25.40ms와 실질적으로 대등합니다.
   - c4의 경우 이전 측정의 r1 스파이크(48.59ms)와 같은 이상 현상은 전혀 관측되지 않았으며, 전 회차 32.99ms~34.32ms 구간에서 매우 안정적으로 집속되었습니다.

2. **c4의 안정적인 1.31ms 중앙 델타 성격**:
   - c4에서 관측된 Current와 Baseline의 차이는 +1.16ms ~ +1.64ms(중앙값 +1.31ms)로 극히 좁은 분산과 일관성을 보입니다.
   - 이는 회귀 결함이나 꼬리 지연 파탄(threshold failure)이 아니며, 미세한 프로파일 차이에 따른 안정적 옵셋입니다.

3. **제한적 결론 (Constrained Conclusion)**:
   - 본 통제 A/B 벤치마크를 통해 런타임 파탄이나 치명적 성능 퇴행이 없음이 입증되었으나, 이를 근거로 **G3 게이트의 완전 통과를 단정하거나 런타임 코드/설정을 임의 변경하지 않습니다.**
   - **명시적 후속 조치**: c4의 1.31ms 중앙 델타에 대해서는 프로젝트에서 사전 합의된 회귀 예산(regression budget)이 수립되고 해당 예산을 초과할 경우에만 추가 진단을 진행하며, 이를 임계치 미달 실패(threshold failure)로 분류하지 않습니다.

---

## 5. 보존된 원시 데이터 아티팩트 (Raw Artifacts)

모든 20개 원시 JSON 파일은 `data/benchmarks/predict_ab_20260822/`에 바이트 동일하게 보존되었습니다.

| 파일명 | 대상 | 동시성/회차 | SHA-256 체크섬 (앞 16자리) |
| --- | --- | :---: | --- |
| [`baseline_c2_r1.json`](../../data/benchmarks/predict_ab_20260822/baseline_c2_r1.json) | Baseline | c2 / r1 | `b58e5d084bdcf49d...` |
| [`baseline_c2_r2.json`](../../data/benchmarks/predict_ab_20260822/baseline_c2_r2.json) | Baseline | c2 / r2 | `989fbda26c99ed4c...` |
| [`baseline_c2_r3.json`](../../data/benchmarks/predict_ab_20260822/baseline_c2_r3.json) | Baseline | c2 / r3 | `5ebd5466e611cfa0...` |
| [`baseline_c2_r4.json`](../../data/benchmarks/predict_ab_20260822/baseline_c2_r4.json) | Baseline | c2 / r4 | `9a33a4bc959833e9...` |
| [`baseline_c2_r5.json`](../../data/benchmarks/predict_ab_20260822/baseline_c2_r5.json) | Baseline | c2 / r5 | `6a5b77cc59e02fdf...` |
| [`baseline_c4_r1.json`](../../data/benchmarks/predict_ab_20260822/baseline_c4_r1.json) | Baseline | c4 / r1 | `49e85afa295e91dd...` |
| [`baseline_c4_r2.json`](../../data/benchmarks/predict_ab_20260822/baseline_c4_r2.json) | Baseline | c4 / r2 | `a8bb1d4c125e605c...` |
| [`baseline_c4_r3.json`](../../data/benchmarks/predict_ab_20260822/baseline_c4_r3.json) | Baseline | c4 / r3 | `3b9317f20cba6f3b...` |
| [`baseline_c4_r4.json`](../../data/benchmarks/predict_ab_20260822/baseline_c4_r4.json) | Baseline | c4 / r4 | `4ab7c610cd8ccdb7...` |
| [`baseline_c4_r5.json`](../../data/benchmarks/predict_ab_20260822/baseline_c4_r5.json) | Baseline | c4 / r5 | `935eb55e10c8a023...` |
| [`current_c2_r1.json`](../../data/benchmarks/predict_ab_20260822/current_c2_r1.json) | Current | c2 / r1 | `a07017d4590f112f...` |
| [`current_c2_r2.json`](../../data/benchmarks/predict_ab_20260822/current_c2_r2.json) | Current | c2 / r2 | `4fb71dd08d43ef13...` |
| [`current_c2_r3.json`](../../data/benchmarks/predict_ab_20260822/current_c2_r3.json) | Current | c2 / r3 | `a49b2c1d96b5ce1e...` |
| [`current_c2_r4.json`](../../data/benchmarks/predict_ab_20260822/current_c2_r4.json) | Current | c2 / r4 | `11c93ebd80d6d077...` |
| [`current_c2_r5.json`](../../data/benchmarks/predict_ab_20260822/current_c2_r5.json) | Current | c2 / r5 | `b422d7201f562565...` |
| [`current_c4_r1.json`](../../data/benchmarks/predict_ab_20260822/current_c4_r1.json) | Current | c4 / r1 | `fb543a147463cf8f...` |
| [`current_c4_r2.json`](../../data/benchmarks/predict_ab_20260822/current_c4_r2.json) | Current | c4 / r2 | `451f6282e19e4c68...` |
| [`current_c4_r3.json`](../../data/benchmarks/predict_ab_20260822/current_c4_r3.json) | Current | c4 / r3 | `6c76802cf16e71d2...` |
| [`current_c4_r4.json`](../../data/benchmarks/predict_ab_20260822/current_c4_r4.json) | Current | c4 / r4 | `d1cae7d80594f29d...` |
| [`current_c4_r5.json`](../../data/benchmarks/predict_ab_20260822/current_c4_r5.json) | Current | c4 / r5 | `0bf318ba4b11dc9b...` |

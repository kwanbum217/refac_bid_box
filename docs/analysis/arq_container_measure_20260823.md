# Arq Docker 컨테이너 워커 큐 처리량 및 지연 실측 보고서

> **작성일**: 2026-08-23
> **작성 목적**: 실제 Docker 컨테이너로 기동한 Arq 워커(`refac_bid_box-worker:latest`, `max_jobs=4`)를 대상으로 업무 큐 처리량, P95 지연, 실패율 실측 및 게이트 기준선 대조 판정
> **측정 도구**: [`scripts/benchmark_arq_container.py`](../../scripts/benchmark_arq_container.py)
> **워커 설정 모듈**: [`scripts/_bench_worker_settings.py`](../../scripts/_bench_worker_settings.py)
> **게이트 판정 모듈**: [`scripts/arq_gate.py`](../../scripts/arq_gate.py)
> **대표 원시 데이터**: [`data/benchmarks/arq_container_measure_20260823.json`](../../data/benchmarks/arq_container_measure_20260823.json) (Run 3, 최악 P95 대표)
> **대조군 원시 데이터 (In-Process)**: [`data/benchmarks/arq_worker_measure_20260823.json`](../../data/benchmarks/arq_worker_measure_20260823.json)
> **규약 문서**: [`docs/ops/latency_gate_protocol.md`](../ops/latency_gate_protocol.md)

---

## 1. 측정 개요 및 목적

본 문서는 운영 워커([`src/tasks/worker.py`](../../src/tasks/worker.py:1)) 및 운영 큐(`arq:queue`)를 일체 변경하지 않고, 운영과 동일한 Docker 이미지(`refac_bid_box-worker:latest`)와 운영 동시성 사양(`max_jobs=4`)을 적용한 일회성 컨테이너 워커([`scripts/_bench_worker_settings.py`](../../scripts/_bench_worker_settings.py:1))를 기동하여 실제 컨테이너 경계를 넘나드는 Arq 큐의 처리량(jobs/sec), 종단 지연(Enqueue-to-Complete latency), 그리고 실패율을 실측한 결과를 기록합니다.

[`docs/ops/latency_gate_protocol.md`](../ops/latency_gate_protocol.md:92) 규약에 따라 최소 3회 반복 측정(회차당 표본 600건, 회차 간 간격 30초 대기)을 수행하였으며, 3회차 중 최악 대표값(worst-case representative)을 기준으로 절대 기준선 및 회귀 기준선 적합성을 검증합니다.

```mermaid
flowchart LR
    A[Benchmark Client<br>Host uv Python 3.12<br>600 합성 작업 적재] -->|UUID 전용 큐<br>arq:container-bench:*| B[(Docker Redis 7.4.9<br>Container a289b4f265c2)]
    B -->|Docker Bridge 네트워크<br>max_jobs=4, poll=0.01s| C[Docker Worker Container<br>refac_bid_box-worker:latest<br>Container 5cfdbbb79b2a]
    C -->|완료 이벤트 비동기 반환<br>f'{queue}:done'| B
    B -->|blpop/lpop 수신 및 지연 집계| A
    A -->|Strict RFC-8259 JSON 저장| D[arq_container_measure_20260823.json]
    A -.->|finally 컨테이너 강제 정리| C
```

---

## 2. In-Process 하네스 측정과의 핵심 차이

기존 `arq_docker_worker_measure_20260823` 측정([`docs/analysis/arq_docker_worker_measure_20260823.md`](arq_docker_worker_measure_20260823.md))과 본 컨테이너 워커 측정 간의 구조적/환경적 차이는 아래와 같습니다.

| 비교 항목 | 기존 In-Process 하네스 측정 | 본 Docker 컨테이너 워커 실측 | 비고 |
| --- | --- | --- | --- |
| **워커 실행 위치** | Host OS 프로세스 내부 (`asyncio.create_task`) | 독립 Docker 컨테이너 내부 (`docker run`) | 컨테이너 격리 경계 적용 |
| **워커 동시성 (`max_jobs`)** | `concurrency = 10` (합성 기본값) | **`max_jobs = 4` (운영 사양 일치)** | `src/tasks/worker.py:61` 준수 |
| **Redis 통신 경로** | Host localhost:6379 포트 매핑 통신 | Docker 내부 Bridge 네트워크 (`arq-docker-measure_default`) | 네트워크 격리 경로 |
| **Python 환경** | Host Python 3.12.14 (`.venv`) | Container Python 3.11.11 (Linux Debian slim) | 운영 Dockerfile 일치 |
| **운영 설정 보존** | `WorkerSettings.functions` 미사용 (직접 Worker 인스턴스화) | `scripts/_bench_worker_settings.py` 전용 분리 | 운영 코드 100% 무변경 |

---

## 3. 측정 환경 및 Provenance

측정 환경의 host, Docker, Redis, Worker Container, Arq, Python 정보 및 provenance는 아래와 같습니다.

| 항목 | 상세 규격 및 Provenance | 비고 |
| --- | --- | --- |
| **호스트 OS / 하드웨어** | macOS Darwin 26.6.2 arm64 (Apple Silicon 14 cores) | `platform.platform()` |
| **호스트 Python 런타임** | CPython 3.12.14 (`.venv`, uv 패키지 환경) | `platform.python_version()` |
| **컨테이너 Python 런타임** | CPython 3.11.11 (Linux aarch64) | Dockerfile 표준 베이스 |
| **Arq / Redis 라이브러리** | `arq 0.28.0`, `redis-py 5.3.1` | 패키지 버전 |
| **Docker 엔진 버전** | Docker version 29.7.2, build a7dcaa6 | `docker --version` |
| **Redis Container ID** | `a289b4f265c2` (`arq-docker-measure-redis-1`) | Docker Container ID |
| **Redis Image** | `redis:7-alpine` (v7.4.9) | Redis 공식 이미지 |
| **워커 Container Image** | `refac_bid_box-worker:latest` (`sha256:d88574a908269e84ffe3b7255b77868245a5c9247d5f89cd7c7a09478e59b0ba`) | 프로젝트 표준 이미지 |
| **워커 Container IDs** | Run 1: `e1dc94df506a`, Run 2: `b566f0b8cbd4`, Run 3: `5cfdbbb79b2a` | 회차별 독립 기동/정리 |
| **워커 동시성 설정** | **`max_jobs = 4`** (`poll_delay = 0.01초`) | 운영 WorkerSettings 기준 |
| **인위 지연 및 실패율** | `job_delay_ms = 0.0ms`, `simulate_error_rate = 0.0` | 순수 큐 I/O 및 실행 성능 측정 |
| **표본 수 및 반복** | 회차당 600 작업, 3회 반복 (총 1,800 작업) | 규약 1장 준수 |
| **측정 시각** | 2026-08-23 18:38 ~ 18:39 KST (UTC: 2026-08-23T09:38:49Z ~ 09:39:52Z) | 실측 시각 |

### 3.1 주변 부하 (Ambient Load)

[`docs/ops/latency_gate_protocol.md`](../ops/latency_gate_protocol.md:255) 5.3절에 따라 각 회차 시작 직전 코어당 부하율을 기록하였습니다.

| 측정 시점 | 1분 Load Average | 코어 수 (`hw.ncpu`) | 코어당 부하율 | 적합 여부 판정 |
| --- | :---: | :---: | :---: | :---: |
| **Run 1 시작 전** | 5.09 | 14 | **36.36%** | 적합 (<50% max) |
| **Run 2 시작 전 (30s 대기 후)** | 5.25 | 14 | **37.50%** | 적합 (<50% max) |
| **Run 3 시작 전 (30s 대기 후)** | 5.41 | 14 | **38.64%** | 적합 (<50% max) |

---

## 4. 3회 반복 실측 결과 요약

3회 반복 측정의 회차별 결과는 다음과 같으며, 3회 모두 실패나 누락 없이 100% 정상 처리되었습니다. 대표 원시 JSON에는 최악 P95를 기록한 Run 3가 보존되었습니다.

| 회차 | 워커 Container ID | 대상 큐 ID | 총 작업 수 | 소요시간 (초) | 처리량 (jobs/sec) | P50 (ms) | P95 (ms) | P99 (ms) | Min (ms) | Max (ms) | 평균 (ms) | 실패/오류 |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Run 1** | `e1dc94df506a` | `arq:container-bench:72a5cd2a7ebf` | 600 | 0.3440 | **1,744.07** | 208.23 | 329.49 | 340.42 | 19.98 | 343.16 | 207.90 | 0 / 0 |
| **Run 2** | `b566f0b8cbd4` | `arq:container-bench:eed6b95e503c` | 600 | 0.3551 | **1,689.70** | 215.20 | 339.78 | 350.75 | 26.88 | 354.22 | 216.96 | 0 / 0 |
| **Run 3** | `5cfdbbb79b2a` | `arq:container-bench:ac8f737f30bc` | 600 | 0.3667 | **1,636.00** | 221.01 | **352.61** | **363.22** | 14.20 | **365.95** | 221.96 | 0 / 0 |
| **최악 대표** | `5cfdbbb79b2a` | `ac8f737f30bc` (P95 기준) | 600 | **0.3667** | **1,636.00** | **221.01** | **352.61** | **363.22** | 14.20 | 365.95 | **221.96** | **0 / 0 (0.0%)** |

---

## 5. 지연 및 처리량 상세 분석

### 5.1 컨테이너 워커의 Enqueue-to-Complete 지연 특성

클라이언트가 600개의 작업을 `asyncio.gather`를 통해 일괄 적재한 후 컨테이너 워커(`max_jobs=4`)가 큐를 소진(drain)하는 패턴입니다.

1. **컨테이너-Redis 간 빠른 IPC/Bridge I/O**: Docker bridge 네트워크 내에서 워커가 Redis 큐를 폴링하여 작업을 소비하는 오버헤드가 극히 낮아 첫 배치 수신 지연은 ~14~20ms 수준입니다.
2. **동시성 소진 속도**: 4개 워커 슬롯이 병렬로 작업을 연속 인출(drain)하며, 600개 전체 작업이 약 0.34~0.37초 내에 완전 소진되었습니다.
3. **지연 분포 수렴**: P50 지연은 ~221ms, P95 지연은 ~352ms, 최댓값은 ~366ms로 매우 안정적으로 수렴하였습니다.

### 5.2 지연 구간 분포 (Run 3 기준, n=600)

| 지연 구간 | 작업 수 (건) | 백분율 (%) | 누적 백분율 (%) | 비고 |
| --- | :---: | :---: | :---: | --- |
| **< 100ms** | 12 | 2.00% | 2.00% | 초기 Redis enqueue 및 첫 배치 처리 |
| **100ms ~ 150ms** | 134 | 22.33% | 24.33% | 2~35번째 배치 순차 처리 |
| **150ms ~ 200ms** | 132 | 22.00% | 46.33% | 36~68번째 배치 처리 |
| **200ms ~ 250ms** | 142 | 23.67% | 70.00% | 69~103번째 배치 처리 (P50 경계 221ms) |
| **250ms ~ 300ms** | 114 | 19.00% | 89.00% | 104~131번째 배치 처리 |
| **300ms ~ 360ms** | 64 | 10.67% | 99.67% | 132~149번째 배치 처리 (P95 경계 352ms) |
| **> 360ms** | 2 | 0.33% | 100.00% | 150번째 최종 배치 완료 (최대 365.95ms) |

---

## 6. 게이트 판정 및 기준선 대조

### 6.1 scripts/arq_gate.py 절대 기준선 판정 (Repetition Gate)

`scripts/arq_gate.py`의 `RepetitionThresholds` 절대 기준선(처리량 >= 900 jps, P95 <= 600ms, 실패율 <= 0.0%)과 3회 실측치를 대조한 기계 판정 결과입니다.

| 평가 항목 | 판정 기준선 | 3회 실측치 (최악값) | 판정 결과 | 상세 비고 |
| --- | :---: | :---: | :---: | --- |
| **최소 반복 회차** | `>= 3회` | **3회 완료** | **PASS** | 3회 반복 측정 완료 |
| **최소 처리량** | `>= 900.0 jobs/sec` | **1,636.00 jobs/sec** (Run 3) | **PASS** | 기준선 대비 +81.8% 여유 확보 |
| **Enqueue-to-Complete P95** | `<= 600.0 ms` | **352.61 ms** (Run 3) | **PASS** | 기준선 대비 247.4ms 여유 확보 |
| **최대 작업 실패율** | `<= 0.0%` | **0.00% (0 / 1,800)** | **PASS** | 3회 전량 실패 0건 |

**기계 판정 CLI 실행 결과**:
```text
$ uv run python scripts/arq_gate.py --repetition data/benchmarks/arq_container_measure_20260823_r1.json --repetition data/benchmarks/arq_container_measure_20260823_r2.json --repetition data/benchmarks/arq_container_measure_20260823_r3.json
PASS
run=1: throughput=1744.07 p95=329.485 failure_rate=0.0000 PASS throughput=PASS p95=PASS failure=PASS
run=2: throughput=1689.70 p95=339.778 failure_rate=0.0000 PASS throughput=PASS p95=PASS failure=PASS
run=3: throughput=1636.00 p95=352.614 failure_rate=0.0000 PASS throughput=PASS p95=PASS failure=PASS
```

### 6.2 In-Process Baseline 대비 회귀 판정 (GateThresholds)

기존 In-Process 하네스 측정치([`arq_worker_measure_20260823.json`](../../data/benchmarks/arq_worker_measure_20260823.json))를 baseline 으로 하여 `GateThresholds` 마진(처리량 -10% 이내, P95 +10% 이내, 실패율 +1pp 이내)을 대조한 결과입니다.

| 지표 | Baseline (In-Process, c10) | Current (Container, max_jobs=4) | 임계 허용선 | 판정 | 상세 델타 |
| --- | :---: | :---: | :---: | :---: | :---: |
| **처리량 (jobs/sec)** | 1,107.79 | **1,636.00** | `>= 997.01` (drop <= 10%) | **PASS** | **+47.68% 향상** (`drop_ratio = -0.4768`) |
| **P95 지연 (ms)** | 519.20 | **352.61** | `<= 571.12` (inflate <= 10%) | **PASS** | **-32.08% 단축** (`inflate_ratio = -0.3208`) |
| **실패율** | 0.00% | **0.00%** | `<= 1.00%` (inflate <= 1pp) | **PASS** | **0.00% (동일)** (`inflate_pp = 0.0000`) |

**기계 판정 CLI 실행 결과**:
```text
$ uv run python scripts/arq_gate.py --baseline data/benchmarks/arq_worker_measure_20260823.json --current data/benchmarks/arq_container_measure_20260823.json
PASS
throughput: baseline=1107.790000 current=1636.000000 threshold=0.100000 PASS drop_ratio=-0.4768
p95_latency: baseline=519.198000 current=352.614000 threshold=0.100000 PASS inflate_ratio=-0.3208
failure_rate: baseline=0.000000 current=0.000000 threshold=0.010000 PASS inflate_pp=0.0000
```

---

## 7. 결론 및 불변성 준수 확인

1. **실제 Docker 컨테이너 워커 실측 증거 확보**:
   - `refac_bid_box-worker:latest` 이미지 기반의 실제 컨테이너 워커 환경에서 Arq 큐의 처리량(1,636.00 ~ 1,744.07 jobs/sec), P95 지연(329.49 ~ 352.61ms), 실패율(0.0%)에 대한 원시 증거 JSON과 상세 분석을 확보하였습니다.
2. **게이트 기준선 전체 통과**:
   - 절대 기준선(`RepetitionThresholds`: >=900 jps, <=600ms, 0% failure) 및 baseline 대조 회귀 판정(`GateThresholds`)을 3회 반복 전체에서 안정적으로 PASS 하였습니다.
3. **운영 무결성 100% 보존**:
   - `docker-compose.yml`, `src/tasks/worker.py` 및 기존 `data/benchmarks` 원시 증거는 100% 변경 없이 보존되었습니다.
   - 측정 중 기동된 일회성 컨테이너(`e1dc94df506a`, `b566f0b8cbd4`, `5cfdbbb79b2a`)는 측정 완료 즉시 완전히 정리되었으며, DB(`mysql:8.0`) 및 Redis(`redis:7-alpine`) 컨테이너는 재시작 없이 정상 운영 상태를 유지하였습니다.

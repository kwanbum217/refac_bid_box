# Arq 정식 기준선 캘리브레이션 절차 설계서

> **작성일**: 2026-08-24
> **Task ID**: task_5e354d395d04
> **상태**: 설계 (측정 미실시)
> **목적**: `scripts/arq_gate.py`의 잠정 일관성 봉투(`RepetitionThresholds`)를 대체할 정식 기준선(Formal Baseline)을 도출하기 위한 실행 가능한 캘리브레이션 절차를 명시한다.
> **코드 변경 없음**: 본 문서는 설계서만 작성하며, 측정을 실행하거나 기존 코드를 수정하지 않는다.

---

## 1. 개요 및 목적

현재 `scripts/arq_gate.py:80-100`에 정의된 `RepetitionThresholds`(900 jobs/sec, 600ms P95)는 실측 근거 없이 사후 보정된 잠정 일관성 봉투이다([`docs/analysis/arq_threshold_derivation_20260823.md`](docs/analysis/arq_threshold_derivation_20260823.md) 6장 참조). 본 설계서는 이 봉투를 대체할 정식 기준선을 데이터로부터 도출하는 절차, 고정 조건, 회차 수, frozen baseline 파일 규약, 기준선 도출식, 기각 조건을 실행 가능한 사양으로 정의한다.

정식 기준선은 두 가지 워커 경로에 대해 각각 도출한다.

| 경로 | 하네스 | 워커 구현 | 용도 |
| --- | --- | --- | --- |
| **In-Process** | `scripts/benchmark_arq_throughput.py` | `arq.worker.Worker` + `benchmark_noop_task` | 개발/CI 빠른 회귀 검증 |
| **Container** | `scripts/benchmark_arq_container.py` | `scripts/_bench_worker_settings.WorkerSettings` | 운영 Docker 환경 적합성 검증 |

---

## 2. 용어 정의

| 용어 | 정의 |
| --- | --- |
| **캘리브레이션 런(Calibration Run)** | 정식 기준선을 도출하기 위해 동일 조건으로 수행되는 반복 측정 집합 |
| **회차(Run)** | 단일 벤치마크 실행 및 그 결과 JSON 1개 |
| **Frozen Baseline** | 캘리브레이션 런 종료 후 선정된 대표 결과 및 원시 회차 결과를 보존한 불변 아티팩트 |
| **잠정 일관성 봉투** | 기존 `RepetitionThresholds`(900 jobs/sec, 600ms P95). 실측 근거 없는 보수적 상수 |
| **CV(Coefficient of Variation)** | 표준편차 / 산술평균. 회차 간 상대 변동성 지표 |

---

## 3. 고정 조건

아래 조건은 캘리브레이션 런 전체 회차에 걸쳐 동일해야 한다. Provenance 기록은 시작과 종료 시점 모두에서 검증하며, 변경 시 해당 회차는 무효로 처리한다.

### 3.1 측정 대상 및 작업 부하

| 항목 | In-Process 경로 | Container 경로 | 근거 |
| --- | --- | --- | --- |
| 총 작업 수 (`total_jobs`) | 600 | 600 | 기존 측정과 동일한 큐 깊이 ([`docs/analysis/arq_threshold_derivation_20260823.md`](docs/analysis/arq_threshold_derivation_20260823.md) 2장) |
| 동시성 (`max_jobs`) | 10 | 4 | In-Process는 기존 10, Container는 운영 워커(`src/tasks/worker.py:61`)와 동일 |
| 작업 지연 (`job_delay_ms`) | 0.0 | 0.0 | 합성 noop 작업 기준 |
| 폴링 주기 (`poll_delay_sec`) | 0.01 | 0.01 | 기존 측정과 동일 |
| 타임아웃 (`timeout_sec`) | 60.0 | 60.0 | 하네스 기본값 |
| 인위 실패율 (`simulate_error_rate`) | 0.0 | 0.0 | 정상 경로 기준선 |

### 3.2 Redis 및 Docker 환경

| 항목 | 고정 값/판정식 | 비고 |
| --- | --- | --- |
| Redis URL | `redis://localhost:6379/0` | `src/app/core/config.py` 기본값 또는 `.env` 설정 |
| Redis 컨테이너 | `docker-compose.yml`의 `redis` 서비스로 기동한 컨테이너 | `container_id`, `image_id`를 Provenance에 기록 |
| Container 워커 이미지 | `refac_bid_box-worker:latest` | 빌드 시점 이미지 SHA 기록 |
| Container 네트워크 | `arq-docker-measure_default` | `benchmark_arq_container.py` 기본값 |
| 소스 마운트 | 프로젝트 루트를 `/app`에 bind mount | `source_mount`, `source_git_sha`, `source_git_dirty` 기록 |

### 3.3 Host 부하 규약

| 항목 | 제안 판정식 | 비고 |
| --- | --- | --- |
| 1분 평균 부하 상한 | `host_load_avg_1m / cpu_count <= 0.30` | SSE 측정 규약의 최대 주변 부하 27.8%를 참고한 제안 상한. 정식 채택은 측정 후 합의 |
| 메모리 여유 | `memory_available_bytes >= memory_total_bytes * 0.20` | OOM 및 스왑 방지를 위한 최소 여유 제안 |
| 동시 측정 금지 | 캘리브레이션 런 실행 중 예측/SSE 벤치마크, 모델 학습, 대용량 색인 동시 실행 금지 | 외생 변수 차단 |

---

## 4. 회차 수 및 산술 근거

### 4.1 권장 회차 수

정식 기준선 도출을 위해 각 경로(In-Process, Container)별로 **최소 10회** 독립 반복 측정을 수행한다.

### 4.2 산술 근거

기존 In-Process 3회 검증 데이터([`docs/analysis/arq_threshold_derivation_20260823.md`](docs/analysis/arq_threshold_derivation_20260823.md) 2장)를 바탕으로 표준오차를 추정하면 다음과 같다.

| 지표 | 평균 | 표준편차 | CV | n=3 SEM | n=10 SEM | n=30 SEM |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 처리량 (jobs/sec) | 1,154.01 | 13.34 | 1.16% | 7.70 | 4.22 | 2.44 |
| P95 지연 (ms) | 497.66 | 6.38 | 1.28% | 3.68 | 2.02 | 1.17 |

- CV가 1.3% 이하로 작은 지표라도, 중앙값 기반 기준선의 안정성을 확보하려면 n=10 이상이 필요하다.
- n=10에서 처리량 기준선의 95% 신뢰구간 반폭은 약 `2 * 4.22 = 8.44 jobs/sec`(평균의 0.73%)로 충분히 안정적이다.
- n=3은 중앙값 추정의 변동성이 크고 outlier에 취약하므로 정식 기준선으로 부적절하다.

### 4.3 회차 간 간격

- 각 회차 종료 후 Redis 키 완전 정리 및 **30초 이상 대기**(`--run-interval-sec 30.0`) 후 다음 회차 시작.
- CPU 캐시, Redis 커넥션 풀, 컨테이너 재기동의 잔여 영향을 최소화한다.

---

## 5. Frozen Baseline 파일 규약

### 5.1 파일 경로

```
data/benchmarks/frozen/arq/<mode>/<git_sha_short>/<YYYYMMDD_HHMMSS>_arq_<mode>_baseline.json
```

- `<mode>`: `inprocess` 또는 `container`
- `<git_sha_short>`: 측정 시점 Git SHA의 앞 7자. dirty 상태에서는 frozen baseline으로 선정 불가.
- 파일명 예시: `data/benchmarks/frozen/arq/container/7892951/20260824_143052_arq_container_baseline.json`

### 5.2 개별 회차 원시 파일

`--repetitions 10` 실행 시 하네스가 자동 생성하는 개별 회차 파일을 함께 보존한다.

```
data/benchmarks/frozen/arq/<mode>/<git_sha_short>/<YYYYMMDD_HHMMSS>_arq_<mode>_baseline_r1.json
...
data/benchmarks/frozen/arq/<mode>/<git_sha_short>/<YYYYMMDD_HHMMSS>_arq_<mode>_baseline_r10.json
```

### 5.3 보존 필드 목록

Frozen baseline JSON은 하네스 출력 전체를 그대로 보존하되, 다음 필드가 반드시 존재해야 한다.

| 필드 경로 | 설명 |
| --- | --- |
| `status` | `"success"`여야 함 |
| `git_sha` | 측정 시점 Git SHA |
| `timestamp` | ISO 8601 측정 시각 |
| `benchmark_worker_mode` | `"in_process"` 또는 `"docker_container"` |
| `provenance.host` | Python 버전, 플랫폼, CPU 수, 부하, 메모리 |
| `provenance.redis` | Redis 컨테이너 ID, 이미지 ID, 서버 버전/모드 |
| `provenance.arq` | Arq 버전, max_jobs, poll_delay, worker_settings_module |
| `provenance.docker` | Docker 버전, 워커 컨테이너/이미지 ID, source mount, git SHA/dirty |
| `config` | queue_name, total_jobs, concurrency, job_delay_ms, poll_delay_sec 등 |
| `summary.jobs_per_second` | 처리량 |
| `summary.total_enqueued` | 600 |
| `summary.failed_jobs` | 0 |
| `summary.error_count` | 0 |
| `latency_ms.p50_ms` | P50 지연 |
| `latency_ms.p95_ms` | P95 지연 |
| `latency_ms.p99_ms` | P99 지연 |
| `latency_ms.min_ms` | 최소 지연 |
| `latency_ms.max_ms` | 최대 지연 |
| `latency_ms.mean_ms` | 평균 지연 |
| `latency_ms.values_ms` | 원시 지연 값 배열(전체) |
| `errors` | 빈 배열 |

---

## 6. 기준선 도출식

본 설계서는 구체 계수를 지어내지 않는다. 아래 식은 캘리브레이션 런 완료 후 채워질 **도출 방법 사양**이다.

### 6.1 표본 집계

캘리브레이션 런에서 수집된 n개 회차의 핵심 지표를 다음과 같이 정의한다.

- `T = [t_1, t_2, ..., t_n]`: 처리량(samples) 목록
- `P = [p_1, p_2, ..., p_n]`: P95 지연(samples) 목록
- `F = [f_1, f_2, ..., f_n]`: 실패율(samples) 목록

### 6.2 처리량 기준선

처리량은 높을수록 양호하므로, 하위 측정값 중 보수적 분위수를 사용한다.

```
throughput_baseline = max(
    Q_p(T, 0.05),
    min(T) * 0.95
)
```

- `Q_p(T, q)`: 선형 보간 백분위수 함수(`benchmark_arq_throughput.py:335-306`의 `calculate_percentile`과 동일 알고리즘)
- `Q_p(T, 0.05)`: 처리량 분포의 5% 분위수
- `min(T) * 0.95`: 최악 회차 대비 5% 여유

### 6.3 P95 지연 기준선

P95 지연은 낮을수록 양호하므로, 상위 측정값 중 보수적 분위수를 사용한다.

```
p95_baseline = max(
    Q_p(P, 0.95),
    max(P) * 1.05
)
```

- `Q_p(P, 0.95)`: P95 지연 분포의 95% 분위수
- `max(P) * 1.05`: 최악 회차 대비 5% 여유

### 6.4 실패율 기준선

```
failure_baseline = max(F)
```

- 정상 경로 캘리브레이션이므로 `failure_baseline = 0.0`이어야 한다.
- 만약 `max(F) > 0`이면 캘리브레이션 런 전체를 기각한다.

### 6.5 최종 정식 기준선

위 도출식 결과를 `scripts/arq_gate.py`의 `RepetitionThresholds` 대신 사용한다.

```python
class FormalRepetitionThresholds:
    min_runs: int = 10
    min_throughput_tasks_per_sec: float = <throughput_baseline>
    max_p95_latency_ms: float = <p95_baseline>
    max_failure_rate: float = 0.0
```

> **주의**: `<throughput_baseline>`과 `<p95_baseline>`은 본 설계서가 아닌 실제 캘리브레이션 런 결과로 채워진다.

---

## 7. 기각 조건

캘리브레이션 런 수행 중 또는 수행 후 아래 조건을 만족하면 해당 회차 또는 전체 런을 기각하고 재측정한다.

### 7.1 회차 기각(개별)

| 조건 | 판정식 | 조치 |
| --- | --- | --- |
| 부하 규약 위반 | `host_load_avg_1m / cpu_count > 0.30` | 해당 회차 무효, Redis/컨테이너 정리 후 재측정 |
| Provenance 불일치 | `start_identity != end_identity` | 해당 회차 무효, `--allow-unknown-provenance` 미사용 시 fail-closed |
| Git dirty | `source_git_dirty == true` | 전체 런 중단, clean 상태에서 재시작 |
| Redis 컨테이너 교체 | `redis_container_id` 또는 `redis_image_id` 변경 | 해당 회차 무효 |
| 워커 컨테이너 교체(Container 경로) | `worker_container_id` 또는 `worker_image_id` 변경 | 해당 회차 무효 |

### 7.2 런 전체 기각

| 조건 | 판정식 | 조치 |
| --- | --- | --- |
| 회차 수 부족 | 유효 회차 수 `n < 10` | 런 무효, 10회 이상 재측정 |
| 처리량 변동계수 초과 | `CV(T) > 0.05` | 외생 변수 의심, 환경 정리 후 재측정 |
| P95 변동계수 초과 | `CV(P) > 0.05` | 외생 변수 의심, 환경 정리 후 재측정 |
| 실패율 존재 | `max(F) > 0.0` | 런 무효, 원인 조사 후 재측정 |
| Outlier 존재 | IQR 기준(`Q3 + 1.5 * IQR` 또는 `Q1 - 1.5 * IQR` 이탈) 회차가 2회 이상 | 런 무효, 환경 정리 후 재측정 |
| Provenance 미기록 | `provenance` 4계층 중 필수 필드 누락 | 런 무효, 하네스 점검 |

### 7.3 CV 계산식

```
CV(X) = stdev(X) / mean(X)
```

- `stdev`: 표준편차(모집단 추정치가 아닌 표본 표준편차 사용)
- `mean`: 산술평균
- `CV(X) <= 0`이거나 `mean(X)`가 0에 가까우면 유효하지 않은 표본으로 처리

---

## 8. In-Process 경로와 Container 경로 통합 권고

### 8.1 현황

- In-Process 측정: 966 ~ 1,165 jobs/sec, P95 492 ~ 519 ms
- Container 측정: 1,636 jobs/sec, P95 352 ms

두 경로의 처리량 차이는 **약 1.7배**에 달하며, P95 지연도 30% 이상 차이난다([`docs/analysis/arq_threshold_derivation_20260823.md`](docs/analysis/arq_threshold_derivation_20260823.md) 2장, capsule ground_truth).

### 8.2 권고

**별도 기준선을 유지한다.**

| 경로 | 기준선 파일 | 용도 |
| --- | --- | --- |
| In-Process | `data/benchmarks/frozen/arq/inprocess/...` | 개발 환경/CI 빠른 회귀 검증 |
| Container | `data/benchmarks/frozen/arq/container/...` | 운영 Docker 환경 적합성 검증 |

통합 기준선을 사용할 경우, Container 경로의 여유로운 수치가 In-Process 경로의 회귀를 놓치거나, In-Process 경로의 엄격한 수치가 Container 경로에서 불필요한 FAIL을 유발할 수 있다. 두 환경의 런타임 특성이 다륯률로 별도 관리하는 것이 합리적이다.

---

## 9. 캘리브레이션 런 실행 절차

다음 절차는 설계서만 읽고 바로 실행할 수 있도록 작성했다.

### 9.1 사전 준비

1. Docker Desktop 또는 Docker Engine 기동
2. `docker-compose up -d redis`로 Redis 컨테이너 기동
3. Container 경로 측정 시 워커 이미지 빌드: `docker compose build worker` 또는 `docker build -t refac_bid_box-worker:latest .`
4. Git working tree가 clean 상태인지 확인: `git status --porcelain`의 출력이 비어 있어야 함

### 9.2 In-Process 경로 캘리브레이션

```bash
mkdir -p data/benchmarks/frozen/arq/inprocess/$(git rev-parse --short HEAD)
uv run python scripts/benchmark_arq_throughput.py \
  --jobs 600 \
  --concurrency 10 \
  --poll-delay 0.01 \
  --timeout 60.0 \
  --repetitions 10 \
  --run-interval-sec 30.0 \
  --output data/benchmarks/frozen/arq/inprocess/$(git rev-parse --short HEAD)/$(date +%Y%m%d_%H%M%S)_arq_inprocess_baseline.json
```

### 9.3 Container 경로 캘리브레이션

```bash
mkdir -p data/benchmarks/frozen/arq/container/$(git rev-parse --short HEAD)
uv run python scripts/benchmark_arq_container.py \
  --jobs 600 \
  --concurrency 4 \
  --poll-delay 0.01 \
  --timeout 60.0 \
  --repetitions 10 \
  --run-interval-sec 30.0 \
  --output data/benchmarks/frozen/arq/container/$(git rev-parse --short HEAD)/$(date +%Y%m%d_%H%M%S)_arq_container_baseline.json
```

### 9.4 기준선 도출

1. 10개의 `_r1.json` ~ `_r10.json`에서 `summary.jobs_per_second`와 `latency_ms.p95_ms`를 추출한다.
2. 7장 기각 조건을 적용하여 유효 회차를 선별한다.
3. 6장 도출식으로 `throughput_baseline`과 `p95_baseline`을 계산한다.
4. 계산 결과를 `FormalRepetitionThresholds`에 기록하고, `scripts/arq_gate.py`의 `RepetitionThresholds`를 대체하는 별도 코드 변경 Task를 생성한다.

---

## 10. 참고 및 출처

| 항목 | 경로 |
| --- | --- |
| 잠정 일관성 봉투 개명 근거 | [`docs/analysis/arq_threshold_derivation_20260823.md`](docs/analysis/arq_threshold_derivation_20260823.md) |
| Provenance 규약 | [`docs/ops/arq_threshold_provenance_20260823.md`](docs/ops/arq_threshold_provenance_20260823.md) |
| 게이트 판정 모듈 | [`scripts/arq_gate.py`](scripts/arq_gate.py) |
| In-Process 벤치마크 하네스 | [`scripts/benchmark_arq_throughput.py`](scripts/benchmark_arq_throughput.py) |
| Container 벤치마크 하네스 | [`scripts/benchmark_arq_container.py`](scripts/benchmark_arq_container.py) |
| 벤치마크 워커 설정 | [`scripts/_bench_worker_settings.py`](scripts/_bench_worker_settings.py) |
| 운영 워커 설정 | [`src/tasks/worker.py`](src/tasks/worker.py) |

---

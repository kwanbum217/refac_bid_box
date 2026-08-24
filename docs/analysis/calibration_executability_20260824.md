# Arq 캘리브레이션 설계서 실행 가능성 대조 보고서

> **작성일**: 2026-08-24
> **Task ID**: task_4e39c6f2075c
> **대상 설계서**: `docs/analysis/arq_calibration_design_20260824.md`
> **대상 코드**: `scripts/benchmark_arq_throughput.py`, `scripts/benchmark_arq_container.py`, `scripts/arq_gate.py`, `scripts/_bench_worker_settings.py`, `src/tasks/worker.py`
> **상태**: 코드 수정 없음, 측정 미실행

---

## 1. 개요

본 보고서는 `docs/analysis/arq_calibration_design_20260824.md`가 지시하는 절차를 현재 하네스와 게이트 코드로 실제 실행할 수 있는지 대조한 결과입니다. 코드는 수정하지 않았고 측정도 실행하지 않았습니다. 설계서의 고정 조건, CLI 인자, 파일 인용, frozen baseline 스키마, 기준선 도출식의 실행 가능성을 중심으로 검토합니다.

---

## 2. 고정 조건과 실제 CLI 인자 대조

### 2.1 측정 대상 및 작업 부하

| 설계서 항목 | In-Process | Container | 실제 CLI 인자 | 지정 가능 여부 |
| --- | ---: | ---: | --- | :---: |
| 총 작업 수 (`total_jobs`) | 600 | 600 | `--jobs`, `-n` | 가능 |
| 동시성 (`max_jobs`) | 10 | 4 | `--concurrency`, `-c` | 가능 |
| 작업 지연 (`job_delay_ms`) | 0.0 | 0.0 | `--job-delay-ms`, `-d` | 가능 |
| 폴팅 주기 (`poll_delay_sec`) | 0.01 | 0.01 | `--poll-delay` | 가능 |
| 타임아웃 (`timeout_sec`) | 60.0 | 60.0 | `--timeout` | 가능 |
| 인위 실패율 (`simulate_error_rate`) | 0.0 | 0.0 | `--simulate-error-rate` | 가능 |

### 2.2 Redis 및 Docker 환경

| 설계서 항목 | 설계서 값 | 실제 코드 동작 | 지정 가능 여부 | 비고 |
| --- | --- | --- | :---: | --- |
| Redis URL | `redis://localhost:6379/0` | `--redis-url`로 지정, 기본값은 `settings.REDIS_URL` 또는 `redis://localhost:6379/0` | 가능 | |
| Redis 컨테이너 | `docker-compose.yml`의 `redis` 서비스 | 이름에 `redis`가 포함된 실행 중인 컨테이너 중 첫 번째를 자동 감지 | 가능 (자동) | 정확히 docker-compose.yml의 `redis` 서비스가 아니어도 이름 일치 시 인식 |
| Container 워커 이미지 | `refac_bid_box-worker:latest` | `--image`로 지정, 기본값 동일 | 가능 | |
| Container 네트워크 | `arq-docker-measure_default` | `--network`로 지정, 미지정 시 Redis 컨테이너 네트워크 자동 감지 | 가능 | docker-compose 네트워크 이름이 다를 경우 `--network`로 재정의 필요 |
| 소스 마운트 | 프로젝트 루트를 `/app`에 bind mount | `--source-mount`로 지정, 기본값 `PROJECT_ROOT` | 가능 | |

### 2.3 회차 수 및 회차 간 간격

| 설계서 항목 | 설계서 값 | 실제 CLI 인자 | 지정 가능 여부 |
| --- | --- | --- | :---: |
| 반복 회차 수 | 10회 | `--repetitions`, `-r` | 가능 |
| 회차 간 대기 시간 | 30.0초 이상 | `--run-interval-sec` | 가능 |

### 2.4 Host 부하 규약

| 설계서 항목 | 설계서 제안 | 실제 코드 지원 | 지정 가능 여부 |
| --- | --- | --- | :---: |
| `host_load_avg_1m / cpu_count <= 0.30` | 제안 상한 | `provenance.host.load_avg_1m`, `cpu_count`에 기록만 하고 자동 검증/거부하지 않음 | 불가능 (하네스 외부 수동 준수) |
| `memory_available_bytes >= memory_total_bytes * 0.20` | 제안 상한 | `provenance.host.memory_*_bytes`에 기록만 함 | 불가능 (하네스 외부 수동 준수) |
| 동시 측정 금지 | 수동 규약 | 하네스에 기능 없음 | 불가능 (운영자 수동 준수) |

---

## 3. 실행 불가능하거나 외부 수동 절차가 필요한 지점

| 번호 | 지점 | 설계서 요구사항 | 현재 코드 상태 | 실행 가능 여부 | 대안 |
| --- | --- | --- | --- | :---: | --- |
| 1 | Host 부하 규약 enforcing | 측정 전/후 `host_load_avg_1m / cpu_count <= 0.30` 등 검증 | 기록만 하고 자동 거부하지 않음 | 부분 불가 | 하네스 외부에서 `scripts/benchmark_provenance.single_host_load_sample()` 또는 시스템 명령으로 사전 검증 후 실행 |
| 2 | Frozen baseline 디렉터리 구조 | `data/benchmarks/frozen/arq/<mode>/<git_sha_short>/...` 경로로 저장 | `--output`이 지정한 경로 그대로 저장, 중간 디렉터리는 자동 생성하지만 `<mode>/<git_sha_short>`는 사용자가 미리 생성해야 함 | 부분 불가 | 실행 전 `mkdir -p data/benchmarks/frozen/arq/<mode>/$(git rev-parse --short HEAD)` 수동 실행 |
| 3 | Container 네트워크 기본값 | `arq-docker-measure_default`로 고정 가정 | Redis 컨테이너 네트워크 자동 감지, `--network`로 재정의 가능 | 가능 (주의) | docker-compose 네트워크 이름이 `arq-docker-measure_default`가 아니면 `--network` 명시 |
| 4 | Redis 컨테이너 식별 | `docker-compose.yml`의 `redis` 서비스 | 이름에 `redis`가 포함된 컨테이너 중 첫 번째 자동 선택 | 가능 (주의) | 여러 redis 컨테이너가 있을 경우 의도하지 않은 컨테이너가 선택될 수 있음 |
| 5 | Frozen baseline 대표값 선정 | 6장 도출식(`Q_p(T, 0.05)`, `Q_p(P, 0.95)` 등)으로 계산 | 하네스는 P95 기준 최악값(`max(results, key=p95_ms)`)을 `--output`에 자동 저장 | 불가능 (자동) | `--output` 대표 파일을 무시하고 `_r1.json`~`_r10.json`을 별도로 읽어 6장 식을 직접 계산해야 함 |
| 6 | Git dirty 전체 런 중단 | dirty 상태에서 전체 런 중단 | strict 모드에서 개별 회차마다 `BuildProvenanceError`로 즉시 종료 | 가능 (동작 다름) | 실제로는 첫 회차부터 종료되므로 "전체 런 중단"과 결과적으로 동일 |
| 7 | Provenance 4계층 필수 필드 누락 시 기각 | 누락 시 런 무효 | 하네스가 `unknown`으로 채워 출력함 | 부분 불가 | `unknown` 값이 있으면 수동으로 기각 판정해야 함 |

---

## 4. 설계서 파일:행 인용 대조

설계서에 파일:행 형식으로 명시된 인용은 총 3건이며, 5건 요구가 있었으나 추가 인용은 없었습니다.

| 번호 | 설계서 인용 | 대상 파일 내용 | 일치 여부 | 비고 |
| --- | --- | --- | :---: | --- |
| 1 | `scripts/arq_gate.py:80-100` | `RepetitionThresholds` 클래스 정의 (`min_runs=3`, `min_throughput_tasks_per_sec=900.0`, `max_p95_latency_ms=600.0`, `max_failure_rate=0.0`) | 일치 | |
| 2 | `src/tasks/worker.py:61` | `max_jobs = 4` | 일치 | |
| 3 | `benchmark_arq_throughput.py:335-306` | `calculate_percentile` 함수 정의는 `335-344`에 있음, `306`은 함수 정의 이전 행 | 불일치 | 설계서 행 범위가 역순이며 실제 함수 범위는 `335-344`; 동일 알고리즘은 `benchmark_arq_container.py:297-306`에도 존재 |

추가로 설계서 10장에 파일 참조(행 미표기)는 `scripts/arq_gate.py`, `scripts/benchmark_arq_throughput.py`, `scripts/benchmark_arq_container.py`, `scripts/_bench_worker_settings.py`, `src/tasks/worker.py`가 있으며 모두 실제 존재하는 파일입니다.

---

## 5. 설계서 6장 계수 확정 여부 확인

설계서 6장은 "구체 계수를 지어내지 않는다"고 선언했으며 실제로도 `<throughput_baseline>`, `<p95_baseline>`과 같은 자리 표시자만 사용합니다.

| 위치 | 내용 | 확정값 여부 |
| --- | --- | :---: |
| 6.2 | `throughput_baseline = max(Q_p(T, 0.05), min(T) * 0.95)` | 미확정 (도출 방법) |
| 6.3 | `p95_baseline = max(Q_p(P, 0.95), max(P) * 1.05)` | 미확정 (도출 방법) |
| 6.4 | `failure_baseline = max(F)` | 미확정 (정상 경로 시 0.0) |
| 6.5 | `min_throughput_tasks_per_sec: float = <throughput_baseline>` | 미확정 |
| 6.5 | `max_p95_latency_ms: float = <p95_baseline>` | 미확정 |

다만 4.2 산술 근거 표와 8.1 현황에는 과거 측정값이 구체 수치로 기록되어 있습니다. 이들은 6장의 기준선 도출식이 아닌 과거 진단 데이터이므로 6장 자체가 확정값을 지어낸 것은 아닙니다.

---

## 6. Frozen Baseline 출력 스키마 대조

설계서 5.3의 보존 필드와 실제 `BenchmarkResult.as_dict()` 출력을 대조한 결과입니다.

| 설계서 필드 경로 | 실제 출력 존재 여부 | 비고 |
| --- | :---: | --- |
| `status` | 있음 | |
| `git_sha` | 있음 | |
| `timestamp` | 있음 | |
| `benchmark_worker_mode` | 있음 | `"in_process"` 또는 `"docker_container"` |
| `provenance.host` | 있음 | python_version, platform, cpu_count, load_avg_1m, memory_total_bytes, memory_available_bytes |
| `provenance.redis` | 있음 | redis_url, container_id, container_name, image, image_id, server_version, server_mode |
| `provenance.arq` | 있음 | arq_version, redis_py_version, benchmark_worker_mode, worker_settings_module, worker_functions, is_synthetic, worker_max_jobs, worker_poll_delay, worker_job_timeout |
| `provenance.docker` | 있음 | docker_version, worker_container_id, worker_container_name, worker_image, worker_image_id, source_mount, source_git_sha, source_git_dirty |
| `config` | 있음 | queue_name, total_jobs, concurrency, job_delay_ms, poll_delay_sec, timeout_sec, simulate_error_rate, redis_url 등; Container 경로에는 container_image, container_network, source_mount 추가 |
| `summary.jobs_per_second` | 있음 | |
| `summary.total_enqueued` | 있음 | |
| `summary.failed_jobs` | 있음 | |
| `summary.error_count` | 있음 | |
| `latency_ms.p50_ms` | 있음 | |
| `latency_ms.p95_ms` | 있음 | |
| `latency_ms.p99_ms` | 있음 | |
| `latency_ms.min_ms` | 있음 | |
| `latency_ms.max_ms` | 있음 | |
| `latency_ms.mean_ms` | 있음 | |
| `latency_ms.values_ms` | 있음 | |
| `errors` | 있음 | |

스키마는 전반적으로 일치합니다. 다만 `provenance.docker`의 컨테이너 관련 필드는 In-Process 경로에서 `null`로 기록되며, 이는 "해당 없음"을 의미합니다.

---

## 7. 결론

설계서의 개별 측정 CLI 인자는 `scripts/benchmark_arq_throughput.py`와 `scripts/benchmark_arq_container.py`에서 모두 지정 가능하나, frozen baseline 대표값 선정과 Host 부하 규약 enforcing은 하네스 외부의 수동 절차가 필요하므로 설계서를 그대로 완전 자동 실행할 수는 없습니다.

---

## 8. 후속 권고

1. Host 부하 규약을 하네스 낮은 수준에서 검증하는 CLI 인자(예: `--max-load-ratio`, `--min-memory-ratio`)를 추가하거나, 실행 전 별도 셸 스크립트로 사전 검증합니다.
2. Frozen baseline 파일 경로의 `<mode>/<git_sha_short>` 디렉터리를 자동 생성하도록 하거나, 실행 전 `mkdir -p`를 문서화합니다.
3. 대표값 선정 로직을 하네스에 추가하거나, `_r1.json`~`_r10.json`을 읽어 6장 도출식을 적용하는 별도 스크립트를 작성합니다.
4. `benchmark_arq_throughput.py:335-306` 인용을 `335-344`로 정정합니다.

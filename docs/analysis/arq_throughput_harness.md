# Arq 백그라운드 태스크 처리량 벤치마크 하네스 설계 및 사용 문서

> **작성일**: 2026-08-22
> **도구 위치**: [`scripts/benchmark_arq_throughput.py`](scripts/benchmark_arq_throughput.py)
> **단위 테스트**: [`tests/test_benchmark_arq_throughput.py`](tests/test_benchmark_arq_throughput.py)
> **대상**: Arq 비동기 워커 처리량(jobs/sec) 및 Enqueue-to-Complete 지연 측정 도구

---

## 1. 개요 및 배경

`src/tasks/` 디렉터리의 8개 Arq 백그라운드 태스크(`scheduled_tasks.py`, `automation_tasks.py`, `retrain_task.py`)에 동기 I/O 오프로드(`asyncio.to_thread`)가 적용되었습니다.

HTTP API 요청-응답 경로는 [`docs/analysis/blocking_io_p95_20260822.md`](docs/analysis/blocking_io_p95_20260822.md)를 통해 P95 레이턴시 실측이 완료되었으나, Redis 큐를 매개로 비동기 실행되는 Arq 워커의 처리량(Throughput, jobs/sec)과 작업 적재부터 완료까지의 종단 지연(Enqueue-to-Complete latency)은 전용 하네스의 부재로 미측정 상태였습니다.

실제 Redis 환경에서 운영 워커를 벤치마크할 때 운영 데이터(DB, ChromaDB, ML 가중치)를 오염시키지 않고, 재현 가능한 수치와 계약을 확보하기 위해 본 격리형 벤치마크 하네스를 구현하였습니다.

---

## 2. 핵심 설계 원칙 및 무손실 격리 (G1)

| 원칙 | 구현 방식 | 검증 및 안전 장치 |
| --- | --- | --- |
| **G1 데이터 무손실** | 운영 DB, ML 모델 가중치, ChromaDB에 일체 접근하지 않는 무해한 합성 태스크(`benchmark_noop_task`) 사용 | 외부 I/O 배제, 인위 지연(`simulate_delay_sec`) 시뮬레이션 지원 |
| **큐 격리** | 운영 큐(`arq:queue`) 대신 실행 회차마다 UUID 기반 고유 큐(`arq:benchmark:<uuid>`) 생성 및 바인딩 | 운영 태스크 소비 방해 및 큐 오염 원천 차단 |
| **자동 리소스 정리** | 벤치마크 종료 시 생성된 큐, 헬스체크 키, 작업 키(`arq:job:*`, `arq:result:*`, `arq:retry:*`, `arq:abort:*`) 전량 삭제 | `cleanup_benchmark_resources`를 `finally` 블록에서 강제 실행 |
| **Fail-Fast & No Fail-Open** | Redis 연결 불가, 타임아웃, 작업 실패 시 성공으로 위장하지 않고 즉시 비정상 종료 코드(1 또는 2) 반환 | 무결성 보장, 오류 누락 방지 |
| **결정론적 집계** | 선형 보간 기반 백분위수(`P50`, `P95`, `P99`) 및 총 작업 수 대조를 통한 오류/누락 건수 명시 | 부분 실패 및 누락 작업의 정확한 원인 기록 |

---

## 3. CLI 사용법 및 인자 정의

### 3.1 실행 명령어

```bash
# 기본 실행 (100개 작업, 동시성 10)
uv run python scripts/benchmark_arq_throughput.py

# 고부하 및 인위 지연 시뮬레이션 (500개 작업, 동시성 20, 작업당 5ms 지연, JSON 저장)
uv run python scripts/benchmark_arq_throughput.py --jobs 500 --concurrency 20 --job-delay-ms 5.0 --output data/benchmarks/arq_throughput.json

# Redis 미실행 환경에서의 도움말 조회 (Redis 연결 없이 즉시 실행 가능)
uv run python scripts/benchmark_arq_throughput.py --help
```

### 3.2 CLI 옵션 목록

| 옵션 | 단축키 | 기본값 | 설명 |
| --- | :---: | :---: | --- |
| `--jobs` | `-n` | `100` | 적재할 총 작업 수 (1 이상의 정수) |
| `--concurrency` | `-c` | `10` | 워커 프로세스의 최대 동시 처리 수 (`max_jobs`) |
| `--job-delay-ms` | `-d` | `0.0` | 작업별 인위 지연 시간 (밀리초) |
| `--poll-delay` | - | `0.01` | 워커의 Redis 큐 폴링 주기 (초) |
| `--simulate-error-rate` | - | `0.0` | 인위 작업 실패율 (0.0 ~ 1.0) |
| `--timeout` | - | `60.0` | 전체 벤치마크 최대 허용 시간 (초) |
| `--redis-url` | - | `settings.REDIS_URL` | 대상 Redis 연결 URL |
| `--output` | `-o` | `None` | 결과 JSON 파일 저장 경로 |
| `--quiet` | `-q` | `False` | 콘솔 요약 리포트 출력을 생략 |

### 3.3 종료 코드 규약

- `0`: 벤치마크 성공 (모든 작업 정상 완료, 오류 0건)
- `1`: 벤치마크 실패 (작업 오류 발생, 타임아웃으로 인한 누락, 또는 부분 실패)
- `2`: 초기화 및 인프라 오류 (Redis 연결 불가, 잘못된 CLI 인자 입력)

---

## 4. 출력 JSON 스키마 및 계약

결과 JSON 파일은 환경 메타데이터, 실행 설정, 요약 통계, 지연 분포 및 오류 내역을 포함합니다.

```json
{
  "status": "success",
  "git_sha": "bd5d48102381...",
  "timestamp": "2026-08-22T04:20:00.000000+00:00",
  "environment": {
    "python": "3.12.14",
    "platform": "macOS-26.6.2-arm64-arm-64bit",
    "redis_url": "redis://localhost:6379/0"
  },
  "config": {
    "queue_name": "arq:benchmark:3ad4978b4025",
    "total_jobs": 100,
    "concurrency": 10,
    "job_delay_ms": 0.0,
    "poll_delay_sec": 0.01,
    "timeout_sec": 60.0,
    "simulate_error_rate": 0.0,
    "redis_url": "redis://localhost:6379/0"
  },
  "summary": {
    "total_duration_sec": 0.2415,
    "jobs_per_second": 414.08,
    "total_enqueued": 100,
    "successful_jobs": 100,
    "failed_jobs": 0,
    "error_count": 0
  },
  "latency_ms": {
    "p50_ms": 14.21,
    "p95_ms": 28.65,
    "p99_ms": 35.12,
    "min_ms": 4.52,
    "max_ms": 36.80,
    "mean_ms": 15.34,
    "values_ms": [4.52, 5.10, 14.21, "..."]
  },
  "errors": []
}
```

---

## 5. 지표 산출 정의

1. **Enqueue-to-Complete Latency ($L_i$)**:
   - $t_{enq, i}$: 클라이언트가 Redis 큐에 작업을 적재(`enqueue_job`)하기 직전 측정한 고해상도 타임스탬프(`time.perf_counter()`)
   - $t_{comp, i}$: 워커가 작업을 수신하여 처리를 완료한 시점의 타임스탬프
   - $L_i = (t_{comp, i} - t_{enq, i}) \times 1000$ (ms)
2. **처리량 (Throughput, $JPS$)**:
   - $JPS = \frac{\text{successful\_jobs}}{\text{total\_duration\_sec}}$ (jobs/sec)
3. **백분위수 ($P_{50}, P_{95}, P_{99}$)**:
   - 정렬된 $L$ 배열에 대한 선형 보간 백분위수

---

## 6. 테스트 및 검증 결과

[`tests/test_benchmark_arq_throughput.py`](tests/test_benchmark_arq_throughput.py)를 통해 Redis 의존성 없이 아래 항목이 완전하게 검증되었습니다.

- **고유 큐 생성 검증**: 100회 연속 생성 시 중복 0건 및 접두사(`arq:benchmark:`) 준수 확인.
- **결정론적 집계 및 백분위수**: 단일값, 홀수/짝수 표본, 성공/실패 혼합 시 정확한 P50/P95/P99 산출 확인.
- **리소스 정리 로직 검증**: 모의 Redis 환경에서 큐, 헬스체크, 작업 결과 키 전량 삭제 호출 검증.
- **Fail-Fast 동작 검증**: Redis 연결 실패 시 성공으로 승격되지 않고 에러 발생 및 종료 코드 2 반환 확인.
- **누락 작업 처리**: 타임아웃 등으로 미완료된 작업을 `failed_jobs` 및 `error_count`로 엄격 집계함을 확인.

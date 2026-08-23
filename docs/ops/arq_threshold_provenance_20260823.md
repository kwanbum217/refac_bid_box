# Arq 임계값 게이트 도출 근거 및 Provenance 규약

> **작성일**: 2026-08-23
> **수정일**: 2026-08-23 (절대 기준선 → 잠정 일관성 봉투 개명 반영)
> **모듈**: `scripts/arq_gate.py`, `scripts/benchmark_arq_throughput.py`
> **상태**: 확정 (단, 절대 기준선은 잠정 일관성 봉투로 개명)
> **적용 범위**: Arq 비동기 큐 처리량 및 enqueue-to-complete 지연 일관성 게이트

---

## 1. 개요 및 목적

본 문서는 Arq 태스크 큐의 처리량(Throughput), P95 대기 지연(Enqueue-to-Complete Latency), 작업 실패율(Failure Rate)에 대한 **게이트 판정 임계치 도출식**과, 벤치마크 신뢰성 확보를 위한 **측정 환경(Provenance: host, Redis, Arq, Docker) 기록 규약**을 정의합니다.

정본 판정 모듈은 [`scripts/arq_gate.py`](../../scripts/arq_gate.py)이며, 벤치마크 하네스는 [`scripts/benchmark_arq_throughput.py`](../../scripts/benchmark_arq_throughput.py)를 사용합니다.

> **중요**: `scripts/arq_gate.py`의 `RepetitionThresholds`에 정의된 절대 기준선(900 jobs/sec, 600ms P95)은 **실측 데이터에서 도출되지 않았음**을 확인했습니다. 상세 분석은 [`docs/analysis/arq_threshold_derivation_20260823.md`](../../docs/analysis/arq_threshold_derivation_20260823.md)를 참조하십시오. 이에 따라 본 문서와 코드 내 명칭을 **절대 기준선 → 잠정 일관성 봉투(Provisional Consistency Envelope)**로 개명합니다.

---

## 2. 게이트 임계값 도출식 및 기준 (Threshold Formulation)

### 2.1 3대 핵심 게이트 지표 (상대 회귀 임계값: GateThresholds)

| 지표 | 기준 식 | 기본 허용 오차 (`DEFAULT_*_TOLERANCE`) | 도출 근거 및 성격 |
| --- | --- | :---: | --- |
| **처리량 (Throughput)** | `current_tp >= baseline_tp * (1 - DEFAULT_TP_TOLERANCE)` | **-10% 이내** (`0.10`) | 이벤트 루프 및 네트워크 지연에 따른 일시적 변동 흡수, 영구적 런타임 퇴행 방지 |
| **P95 지연 (Latency)** | `current_p95 <= baseline_p95 * (1 + DEFAULT_P95_TOLERANCE)` | **+10% 이내** (`0.10`) | `latency_gate_protocol.md`의 회귀 금지(+10%) 원칙과 정합성 유지 |
| **실패율 (Failure Rate)** | `current_failure_rate - baseline_failure_rate <= DEFAULT_FAILURE_TOLERANCE` | **+1%p 이내** (`0.01`) | 네트워크 일시 순단에 의한 미세 실패 허용, 구조적 결함 차단 |

> **역할**: baseline 표본 대비 current 표본의 **상대적 회귀**를 판정합니다. 배포 전 CI/CD 게이트에서 사용.

### 2.2 잠정 일관성 봉투 (Provisional Consistency Envelope / 구 RepetitionThresholds)

반복 3회 측정 시 단독 판정 기준으로 사용되는 **보수적 여유 구간**입니다. **실측 데이터에서 통계적으로 도출된 값이 아니며**, 현재까지 관측된 모든 실측 분포를 확실하게 포괄하는 한시적 판정 구간입니다.

| 지표 | 잠정 봉투 값 | 실측 분포 대비 여유도 | 비고 |
| --- | :---: | ---: | --- |
| **최소 반복 회차** | 3회 (`min_runs = 3`) | — | `latency_gate_protocol.md` 반복 기준 준수 |
| **최소 초당 처리량** | `>= 900.0 tasks/sec` | 실측 최솟값 1,107.79 대비 **+23.1% 여유** | 합성 작업 기준 인메모리 큐 **보수적 하한** (도출식 없음) |
| **최대 P95 지연** | `<= 600.0 ms` | 실측 최댓값 519.198 대비 **-13.4% 여유** | 인메모리 큐 enqueue-to-complete **보수적 상한** (도출식 없음) |
| **최대 실패율** | `<= 0.0 %` (0건) | 실측 0.00%와 일치 | 단독 정밀 측정 시 완전 무결성 요구 |

> **도출 근거**: **없음 (사후 보정 인정)**. 상세 역산 결과는 [`docs/analysis/arq_threshold_derivation_20260823.md#4`](../../docs/analysis/arq_threshold_derivation_20260823.md#4) 참조.
> **정식 기준선 전환 조건**: 전용 캘리브레이션 런(독립 10회 이상, 환경 고정, 워커/컨테이너 분리, 부하 변이 포함, 통계적 도출식 합의) 완료 시. 조건은 [`docs/analysis/arq_threshold_derivation_20260823.md#7`](../../docs/analysis/arq_threshold_derivation_20260823.md#7) 참조.

> **역할**: 신규 환경 구성·리팩토링 후 **최소 운용 품질 적합성**을 1차 확인하는 스모크 게이트입니다. 상대 회귀 게이트와 혼동하지 마십시오.

---

## 3. 측정 환경 Provenance 기록 규약

모든 벤치마크 결과 JSON(`BenchmarkResult`) 및 게이트 판정 기록에는 측정 재현성과 외생 변수 차단을 위해 다음 4가지 계층의 Provenance가 엄격한 strict JSON 형태로 기록되어야 합니다.

### 3.1 4대 Provenance 구성 요소

| 계층 | 수집 항목 | 기록 방식 및 근거 |
| --- | --- | --- |
| **1. Host** | OS, Kernel 버전, Python 버전, CPU 코어 수, 메모리 | `platform.platform()`, `platform.python_version()` |
| **2. Redis** | Redis 서버 버전, 실행 모드 (독립/클러스터), 접속 URL | `INFO server` 명령 및 `config.redis_url` (비밀번호 마스킹) |
| **3. Arq** | Arq 라이브러리 버전, Worker concurrency, poll_delay, 큐 이름 | `WorkerSettings`, `BenchmarkConfig` |
| **4. Docker** | Compose 서비스 컨테이너 ID, 이미지 SHA/태그, 네트워크 격리 상태 | Docker inspection 및 Git commit SHA (`git rev-parse HEAD`) |

### 3.2 벤치마크 결과 JSON 스키마 예시

```json
{
  "status": "success",
  "git_sha": "d95efd5c...",
  "timestamp": "2026-08-23T17:20:00+00:00",
  "environment": {
    "python": "3.12.x",
    "platform": "macOS-...",
    "redis_url": "redis://localhost:6379/0",
    "docker_container_id": "refac_bid_box-worker-1",
    "host_load_pct": 28.5
  },
  "config": {
    "queue_name": "arq:benchmark:a1b2c3d4e5f6",
    "total_jobs": 600,
    "concurrency": 20,
    "job_delay_ms": 0.0,
    "poll_delay_sec": 0.01,
    "timeout_sec": 60.0,
    "simulate_error_rate": 0.0,
    "redis_url": "redis://localhost:6379/0"
  },
  "summary": {
    "total_duration_sec": 0.5241,
    "jobs_per_second": 1144.82,
    "total_enqueued": 600,
    "successful_jobs": 600,
    "failed_jobs": 0,
    "error_count": 0
  },
  "latency_ms": {
    "p50_ms": 14.2,
    "p95_ms": 22.8,
    "p99_ms": 29.1,
    "min_ms": 5.1,
    "max_ms": 34.0,
    "mean_ms": 15.6,
    "values_ms": [...]
  },
  "errors": []
}
```

---

## 4. 운영 및 검증 절차

1. **운영 큐 격리**: 벤치마크는 운영 큐(`arq:queue`)를 건드리지 않고, 매회 고유 큐(`arq:benchmark:<uuid>`)를 생성하여 실행 후 잔여 키를 전량 삭제합니다.
2. **strict JSON 파서 사용**: 결과 입력 및 비교 시 `scripts/_strict_json.py`의 `load_strict_json`을 통해 비정상 JSON 주입을 방지합니다.
3. **게이트 실행**:
   ```bash
   uv run python scripts/arq_gate.py --baseline data/benchmarks/baseline.json --current data/benchmarks/current.json
   ```

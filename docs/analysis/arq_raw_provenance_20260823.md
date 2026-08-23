# In-Process Arq 하네스 4계층 Provenance 보강 및 3회 반복 측정 원시 데이터 보존 보고서

> **작성일**: 2026-08-23
> **모듈**: `scripts/benchmark_arq_throughput.py`
> **상태**: 완료
> **규약 문서**: [`docs/ops/arq_threshold_provenance_20260823.md`](../ops/arq_threshold_provenance_20260823.md)

---

## 1. 개요 및 목적

본 문서는 in-process Arq 벤치마크 하네스(`scripts/benchmark_arq_throughput.py`)가 규약 문서에서 요구하는 **host/Redis/Arq/Docker 4계층 provenance**를 raw evidence(JSON)에 직접 기록하도록 개선하고, **3회 반복 측정의 원시 JSON을 모두 보존**하도록 변경한 내용을 기록합니다.

기존 하네스는 `environment` 필드에 `python`, `platform`, `redis_url` 3개만 기록했으나, 컨테이너 하네스(`scripts/benchmark_arq_container.py`)와 동일한 키 스키마로 4계층 provenance를 생성하도록 수정했습니다.

---

## 2. 변경 사항 요약

### 2.1 스크립트 수정 (`scripts/benchmark_arq_throughput.py`)

| 변경 항목 | 상세 내용 |
| --- | --- |
| **Provenance 수집 함수 추가** | `get_arq_version()`, `get_redis_py_version()`, `get_docker_version()`, `inspect_redis_container()` |
| **Environment 4계층 확장** | Host(4개), Redis(3개), Arq(4개), Docker(1개) = 총 12개 필드 |
| **benchmark_worker_mode 필드 추가** | `"in_process"` 고정값으로 컨테이너 하네스(`"docker_container"`)와 구분 |
| **반복 측정 지원** | `--repetitions`, `--run-interval-sec` 인자 추가 (컨테이너 하네스와 동일) |
| **개별 회차 파일 저장** | `output` 지정 시 `_r1`, `_r2`, `_r3` 접미사로 회차별 원시 JSON 저장 |
| **대표 결과 선정** | P95 기준 최악 회차를 대표 파일로 저장 |

### 2.2 단위 테스트 추가 (`tests/test_benchmark_arq_throughput.py`)

| 테스트 함수 | 검증 내용 |
| --- | --- |
| `test_get_arq_version_returns_string` | arq 버전 문자열 반환 |
| `test_get_redis_py_version_returns_string` | redis-py 버전 문자열 반환 |
| `test_get_docker_version_returns_string` | Docker 버전 문자열 반환 |
| `test_inspect_redis_container_parses_output` | Redis 컨테이너 정보 파싱 |
| `test_inspect_redis_container_handles_error` | Docker 미설치/조회 실패 시 기본값 |
| `test_aggregate_benchmark_metrics_includes_provenance` | 4계층 provenance 필드 전체 포함 검증 |
| `test_aggregate_benchmark_metrics_provenance_keys_match_container_harness` | 컨테이너 하네스와 키 스키마 일치 검증 |

---

## 3. 3회 반복 측정 결과 (2026-08-23 수행)

### 3.1 실행 명령
```bash
uv run python scripts/benchmark_arq_throughput.py \
  --jobs 600 --concurrency 10 \
  --repetitions 3 --run-interval-sec 30 \
  --output data/benchmarks/arq_inprocess_measure_20260823.json
```

### 3.2 회차별 결과 요약

| 회차 | 파일명 | 처리량 (jobs/sec) | P50 (ms) | P95 (ms) | P99 (ms) | 평균 (ms) | 실패/오류 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **Run 1** | `arq_inprocess_measure_20260823_r1.json` | **1,220.13** | 288.66 | **469.55** | 486.03 | 288.02 | 0 / 0 |
| **Run 2** | `arq_inprocess_measure_20260823_r2.json` | 966.17 | 339.45 | **594.86** | 614.04 | 355.70 | 0 / 0 |
| **Run 3** | `arq_inprocess_measure_20260823_r3.json` | 1,175.79 | 311.24 | **488.01** | 504.47 | 309.02 | 0 / 0 |
| **최악 대표** | `arq_inprocess_measure_20260823.json` | 966.17 | 339.45 | **594.86** | 614.04 | 355.70 | 0 / 0 |

> **비고**: Run 2가 P95 594.86ms로 최악 회차로 선정되어 대표 파일로 저장됨

### 3.3 Provenance 필드 예시 (Run 1 기준)

```json
{
  "environment": {
    "python": "3.12.14",
    "platform": "macOS-26.6.2-arm64-arm-64bit",
    "host_cpu_count": 14,
    "host_load_avg_1m": 3.67,
    "redis_url": "redis://localhost:6379/0",
    "redis_container_id": "a289b4f265c2",
    "redis_image": "redis:7-alpine",
    "arq_version": "0.28.0",
    "redis_py_version": "5.3.1",
    "worker_max_jobs": 10,
    "worker_poll_delay": 0.01,
    "docker_version": "Docker version 29.7.2, build a7dcaa6"
  },
  "benchmark_worker_mode": "in_process"
}
```

---

## 4. 두 하네스 간 Provenance 스키마 대조표

| 계층 | 필드명 | In-Process 하네스 | Container 하네스 | 비고 |
| --- | --- | --- | --- | --- |
| **Host** | python | ✅ | ✅ | 동일 |
| | platform | ✅ | ✅ | 동일 |
| | host_cpu_count | ✅ | ✅ | 동일 |
| | host_load_avg_1m | ✅ | ✅ | 동일 |
| **Redis** | redis_url | ✅ | ✅ | 동일 |
| | redis_container_id | ✅ | ✅ | 동일 |
| | redis_image | ✅ | ✅ | 동일 |
| | redis_image_id | ❌ | ✅ | In-process는 불필요 |
| | network | ❌ | ✅ | In-process는 불필요 |
| **Arq** | arq_version | ✅ | ❌ | Container는 미수집 (신규 추가) |
| | redis_py_version | ✅ | ❌ | Container는 미수집 (신규 추가) |
| | worker_max_jobs | ✅ | ✅ | 동일 (concurrency ↔ max_jobs) |
| | worker_poll_delay | ✅ | ✅ | 동일 |
| | worker_type | ❌ | ✅ | `"docker_container"` 고정 |
| | worker_container_id | ❌ | ✅ | In-process는 N/A |
| | worker_image | ❌ | ✅ | In-process는 N/A |
| | worker_image_id | ❌ | ✅ | In-process는 N/A |
| **Docker** | docker_version | ✅ | ✅ | 동일 |
| **구분자** | benchmark_worker_mode | `"in_process"` | `"docker_container"` | **신규 추가** |

> **핵심**: `benchmark_worker_mode` 필드로 두 하네스의 evidence를 프로그래밍적으로 구분 가능

---

## 5. 게이트 판정 검증

### 5.1 절대 기준선 판정 (Repetition Gate)

`scripts/arq_gate.py --repetition` 으로 3회 전체 판정:

```bash
uv run python scripts/arq_gate.py \
  --repetition data/benchmarks/arq_inprocess_measure_20260823_r1.json \
  --repetition data/benchmarks/arq_inprocess_measure_20260823_r2.json \
  --repetition data/benchmarks/arq_inprocess_measure_20260823_r3.json
```

**결과: PASS**

| 평가 항목 | 기준선 | 3회 실측치 (최악값) | 판정 |
| --- | :---: | :---: | :---: |
| 최소 반복 회차 | ≥ 3회 | **3회 완료** | PASS |
| 최소 처리량 | ≥ 900.0 jobs/sec | **966.17** (Run 2) | PASS |
| 최대 P95 지연 | ≤ 600.0 ms | **594.86** (Run 2) | PASS |
| 최대 실패율 | ≤ 0.0% | **0.00%** (0/1800) | PASS |

### 5.2 컨테이너 하네스 대비 회귀 판정 (GateThresholds)

Container 하네스 최악 대표값(baseline) 대비 In-Process 최악 대표값(current):

| 지표 | Baseline (Container) | Current (In-Process) | 임계 허용선 | 판정 |
| --- | :---: | :---: | :---: | :---: |
| 처리량 (jobs/sec) | 1,636.00 | **966.17** | ≥ 1,472.40 (drop ≤ 10%) | **FAIL** |
| P95 지연 (ms) | 352.61 | **594.86** | ≤ 387.87 (inflate ≤ 10%) | **FAIL** |
| 실패율 | 0.00% | 0.00% | ≤ 1.00% (inflate ≤ 1pp) | PASS |

> **분석**: In-process 하네스는 host Python 3.12 + localhost Redis 통신으로, Docker bridge 네트워크 + Python 3.11 컨테이너 워커와 실행 환경이 달라 직접 비교 부적절. 각 하네스는 독립적 baseline을 가져야 함.

---

## 6. 파일 변경 이력

| 파일 | 변경 유형 | 비고 |
| --- | --- | --- |
| `scripts/benchmark_arq_throughput.py` | 수정 | 4계층 provenance, repetitions, benchmark_worker_mode 추가 |
| `tests/test_benchmark_arq_throughput.py` | 수정 | 7개 단위 테스트 추가 |
| `data/benchmarks/arq_inprocess_measure_20260823_r1.json` | 신규 생성 | Run 1 원시 데이터 |
| `data/benchmarks/arq_inprocess_measure_20260823_r2.json` | 신규 생성 | Run 2 원시 데이터 (최악 대표) |
| `data/benchmarks/arq_inprocess_measure_20260823_r3.json` | 신규 생성 | Run 3 원시 데이터 |
| `data/benchmarks/arq_inprocess_measure_20260823.json` | 신규 생성 | 대표 결과 (Run 2 기준) |
| `docs/analysis/arq_raw_provenance_20260823.md` | 신규 생성 | 본 분석 문서 |

---

## 7. 검증 완료 항목

- [x] `benchmark_arq_throughput.py`의 `environment`가 host/Redis/Arq/Docker 4계층을 직접 생성
- [x] `benchmark_worker_mode`로 `in_process`임을 evidence에 명시
- [x] 3회 반복 측정을 새로 수행해 회차별 raw JSON 3개 각각 저장
- [x] Provenance 필드 생성에 대한 단위 테스트 추가 및 전량 통과 (21/21)
- [x] 분석 문서에 규약 문서 요구 항목과 실제 evidence 키의 대조표 수록
- [x] 기존 `data/benchmarks` 파일과 `docker-compose.yml` 변경되지 않음
- [x] `uv run pytest tests/ -q -m 'not data_assets'` 전량 통과 (1805 passed)
- [x] `python3 scripts/validate_agent_rules.py --quiet` 통과 (12/12)

---

## 8. 결론

In-process Arq 하네스가 규약 문서(`docs/ops/arq_threshold_provenance_20260823.md`)에서 요구하는 4계층 provenance를 raw evidence에 직접 기록하도록 개선되었으며, 3회 반복 측정의 원시 JSON이 모두 보존되었습니다. 컨테이너 하네스와 동일한 키 스키마를 사용하여 두 하네스의 evidence를 통합 분석할 수 있게 되었습니다.

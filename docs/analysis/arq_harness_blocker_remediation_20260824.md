# Arq 하네스 자동화 결손(BLOCKER 3건) 해소 보고서

> **작성일**: 2026-08-24
> **Task ID**: task_22512afde3d9
> **대상**: [`calibration_executability_20260824.md`](calibration_executability_20260824.md) 3.1 절에서 BLOCKER 로 분류된 3건
> **대상 코드**: `scripts/benchmark_provenance.py`, `scripts/benchmark_arq_container.py`, `scripts/benchmark_arq_throughput.py`
> **상태**: 구현 및 검증 완료

---

## 1. 개요

Arq 정식 캘리브레이션 설계서([`arq_calibration_design_20260824.md`](arq_calibration_design_20260824.md))를 완전 자동 실행하기 전에, 실행 가능성 대조 보고서([`calibration_executability_20260824.md`](calibration_executability_20260824.md))가 분류한 **BLOCKER 3건**을 하네스가 스스로 수행하도록 구현했습니다.

| 번호 | BLOCKER | 해소 방법 |
| ---: | --- | --- |
| 1 | Host 부하 규약 enforcing 부재 | 측정 시작·종료 양쪽에서 주변 부하를 평가하고, strict 모드에서 임계(중앙값 30%, 최대 50%) 초과 시 fail-closed |
| 5 | Frozen baseline 대표값 산식 자동 적용 부재 | 설계서 6장 중앙값 기준선 산식(`median`, `CV`, `MAD/median`, `rt`, `rp`)을 별도 요약 파일로 자동 산출 |
| 7 | Provenance 4계층 필수 필드 unknown 자동 기각 부재 | 필수 필드 명시 목록 정의, strict 모드에서 unknown 기각 |

---

## 2. 변경 사항

### 2.1 주변 부하 규약 자동 강제 (`check_ambient_load_protocol`)

`scripts/benchmark_provenance.py` 에 `check_ambient_load_protocol()` 을 추가했습니다. `compute_host_load_stats()` 의 `normalized_load_1m_percent`(정규화 1분 load average %, 하위 호환 `per_core_percent` 유지)의 중앙값·최대값을 [`docs/ops/latency_gate_protocol.md`](../../docs/ops/latency_gate_protocol.md) 5.3 절 임계(중앙값 30% 이하, 최대 50% 이하)와 비교합니다.

- 상수: `LOAD_PROTOCOL_MEDIAN_LIMIT_PERCENT = 30.0`, `LOAD_PROTOCOL_MAX_LIMIT_PERCENT = 50.0`
- 두 하네스(`benchmark_arq_container.py`, `benchmark_arq_throughput.py`) 모두:
  - **측정 시작**: `host_load_metadata()` 로 시작 부하를 표집해 평가. strict + 미우회 시 위반이면 `BuildProvenanceError` 로 즉시 중단(회차 시작 전).
  - **측정 종료**: 종료 부하를 평가. strict + 미우회 시 위반이면 `extra_errors` 에 기록해 해당 회차를 실패 처리. 이미 수집된 회차 raw(`_rN.json`)는 버리지 않고 보존합니다.
- **우회 플래그**: `--allow-load-protocol-violation`. `--allow-unknown-provenance` 와 같은 규약을 따르며, 우회 측정은 결과 JSON 의 `load_protocol` 에 미준수 표시(`bypassed=true`, `canonical_evidence=false`)를 남겨 정본 evidence 가 아님을 기록합니다.
- `build_load_protocol_record()` 가 결과 JSON 의 `load_protocol` 구조체를 만듭니다:
  - `enforced`, `bypassed`, `compliant`, `canonical_evidence`, `start`/`end` 상세.
- **지표 정의 및 후속 과제**: 해당 지표는 1분 load average를 논리 코어 수로 나눈 정규화 1분 load average(%)이며, 실제 CPU utilization(사용률)이 아닙니다. psutil 또는 OS 커널 카운터 기반의 실제 CPU utilization 계측은 신규 외부 라이브러리 추가 금지 원칙에 따라 현재 미도입 상태이며, 향후 정밀 프로파일링을 위한 후속 과제로 분리합니다.

### 2.2 설계서 6장 중앙값 기준선 산식 자동 적용 (`compute_baseline_summary`)

`compute_baseline_summary(results)` 를 공통 모듈에 추가하고, 두 하네스의 `main()` 이 `--output` 지정 + 반복 측정(`len(results) > 1`)일 때 `{stem}_baseline_summary{suffix}` 파일로 저장합니다.

계산 항목(설계서 6.2~6.4):

| 항목 | 산식 |
| --- | --- |
| `throughput_baseline` | `median(T)` |
| `p95_baseline` | `median(P)` |
| `CV(T)`, `CV(P)` | `stdev(X) / mean(X)` (표본 표준편차) |
| `MAD/median` | `median(abs(x - median(X))) / median(X)` |
| `rt`, `rp` | `max(3 * CV, 0.06)` |
| 반복 안정성 | `CV <= 0.05` **그리고** `MAD/median <= 0.03` |

- 안정성 위반 시 `stability.verdict = "unstable_baseline_not_trustworthy"` 와 `baseline_trustworthy=false` 를 기록해 기준선을 신뢰할 수 없다고 명시합니다.
- **non-canonical 회차 배제(추가 결함 수정)**: `compute_baseline_summary` 는 입력 회차의 `load_protocol.canonical_evidence` 를 검사합니다. 종료 시점 부하 위반 등으로 `canonical_evidence=false` 가 기록된 회차는 raw(`_rN.json`)는 보존하되, 요약에 `non_canonical_runs`(회차 식별 정보: `run_index`, `git_sha`, `timestamp`)를 기록하고 하나라도 존재하면 `baseline_trustworthy=false` 로 내립니다. 이때 `verdict` 는 `"unstable_non_canonical_runs_present"` 로 기록되어 CV/MAD 변동성 판정(`"unstable_baseline_not_trustworthy"`)과 구분됩니다. 규약 위반 측정이 조용히 기준선이 되는 것을 차단합니다.
- **기존 동작 미변경**: `--output` 의 P95 최악 회차 대표 파일 선정(`max(results, key=p95_ms)`)과 `scripts/arq_gate.py` 의 `RepetitionThresholds` 는 그대로 유지됩니다.

### 2.3 Provenance 필수 필드 unknown 자동 기각 (`PROVENANCE_REQUIRED_FIELDS`)

필수 필드 목록(`PROVENANCE_REQUIRED_FIELDS`)을 명시적으로 정의했습니다. strict 모드에서 이 목록에 속한 필드 값이 `"unknown"` 이거나 누락이면 `BuildProvenanceError` 로 기각합니다.

**필수 필드 근거**:
- `host`: `python_version`, `platform`, `cpu_count` — 하네스가 항상 결정하는 값.
- `redis`: `redis_url`, `container_id`, `container_name`, `image`, `image_id`, `server_version`, `server_mode` — Redis 대상이 결박되어야 정본 evidence 가 되며, `inspect_redis_container`/`fetch_redis_server_info` 가 strict 모드에서 fail-closed 로 보장.
- `arq`: `arq_version`, `redis_py_version`, `benchmark_worker_mode`, `worker_settings_module`, `worker_functions`, `is_synthetic`, `worker_max_jobs`, `worker_poll_delay`, `worker_job_timeout` — 측정 조건을 규정하는 값.
- `docker`: `docker_version` — 측정 환경의 컨테이너 런타임 버전.

**선택 필드(unknown 허용)**: `docker.worker_container_id`, `worker_container_name`, `worker_image`, `worker_image_id` — in-process 경로에서는 해당 없음(None)을 기록하므로 필수에서 제외했습니다. `host.load_avg_1m`, `memory_*` 도 Windows 등에서 None 일 수 있어 필수에서 제외했습니다.

함수: `provenance_unknown_required_fields()`(unknown/누락 dot-path 목록), `enforce_provenance_required_fields()`(strict 기각).

---

## 3. 검증

```bash
uv run pytest tests/test_benchmark_provenance.py tests/test_benchmark_arq_container.py tests/test_benchmark_arq_throughput.py -q
# 102 passed

uv run pytest tests/ -q -m 'not data_assets'
# 1949 passed, 6 skipped, 3 deselected

uv run ruff check scripts/ tests/
# All checks passed

python3 scripts/validate_agent_rules.py --quiet
# 12/12 PASS
```

### 3.1 신규 테스트

| 테스트 | 검증 |
| --- | --- |
| `test_run_container_worker_benchmark_strict_aborts_on_high_load` | 시작 부하 중앙값 30% 초과 시 strict 에서 중단 |
| `test_run_container_worker_benchmark_bypass_marks_load_violation` | 우회 시 결과에 미준수 표시(`canonical_evidence=false`) |
| `TestAmbientLoadProtocol` | 부하 임계 판정 및 `build_load_protocol_record` |
| `test_median_and_cv_and_mad_deterministic` | 고정 표본으로 median/CV/MAD/rt/rp 결정론적 계산 |
| `test_stability_verdict_*` | 반복 안정성 임계 위반/통과 판정 기록 |
| `TestProvenanceRequiredFields` | 필수 unknown 기각 / 선택 unknown 허용 |

---

## 4. 준수 확인

- `scripts/arq_gate.py` 수정 없음, P95 최악 대표값 선정 로직 유지.
- 새 Python 라이브러리 추가 없음 (표준 라이브러리 `math`, `collections.abc` 만 사용).
- DB 스키마·모델 가중치·데이터 무손실 영향 없음.
- 이모지 사용 없음.

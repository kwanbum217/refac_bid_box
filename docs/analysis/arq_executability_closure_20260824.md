# Arq 캘리브레이션 실행가능성 잔여 항목 해소 보고서

> **작성일**: 2026-08-24
> **Task ID**: task_ef39109bd5a5
> **대상**: [`calibration_executability_20260824.md`](calibration_executability_20260824.md) 3.1 절의 잔여 MANUAL 1건, WARNING 1건
> **상태**: 해소 완료

---

## 1. 개요

BLOCKER 3건([`arq_harness_blocker_remediation_20260824.md`](arq_harness_blocker_remediation_20260824.md))은 이미 해소되었습니다. 남은 실행가능성 항목 2건을 닫아 설계서의 10회 캘리브레이션을 운영자 수동 절차 없이 실행할 수 있게 합니다.

| 기존 등급 | 항목 | 해소 방법 |
| --- | --- | --- |
| **MANUAL** | Frozen baseline 디렉터리 수동 생성 | `--frozen-baseline` 옵션으로 경로 규약 자동 구성 + 중간 디렉터리 자동 생성 |
| **WARNING** | 컨테이너 네트워크 기본값 하드코딩 | Redis 감지 네트워크 우선, strict 감지 실패 시 fail-closed, `--network` 명시 지정, provenance 일치 검증 |

---

## 2. 변경 사항

### 2.1 Frozen baseline 경로 자동 구성 (`--frozen-baseline`)

`scripts/benchmark_provenance.py` 에 `frozen_baseline_path()` 를 추가했습니다.

- 경로 규약(설계서 5.1): `<root>/arq/<mode>/<git_sha_short>/<YYYYMMDD_HHMMSS>_arq_<mode>_baseline.json`
- root 기본값: `data/benchmarks/frozen` (`mode`: `inprocess` / `container`)
- 두 하네스(`benchmark_arq_throughput.py`, `benchmark_arq_container.py`)에 `--frozen-baseline` 플래그를 추가했습니다. 지정 시 대표 결과·회차 raw(`_r1`~`_rN`)·기준선 요약(`_baseline_summary.json`)을 자동 구성된 경로에 저장하고 `mkdir(parents=True)` 로 중간 디렉터리를 자동 생성하므로 사전 `mkdir -p` 가 필요 없습니다.
- **하위 호환**: `--frozen-baseline` 미지정 시 기존 `--output` 동작이 그대로 유지됩니다.

### 2.2 컨테이너 네트워크 결정 명시화

`scripts/benchmark_provenance.py` 의 `resolve_redis_container` 에 네트워크 감지 fail-closed 를 적용했습니다.

- Redis 컨테이너에서 감지한 네트워크를 우선 사용합니다.
- strict 모드에서 감지 실패(출력 부재, 파싱 불가, 빈 네트워크)는 하드코딩 기본값(`arq-docker-measure_default`)으로 조용히 넘어가지 않고 `BuildProvenanceError` 로 중단합니다.
- 비-strict(우회)에서만 기본값으로 폴백합니다.
- `run_container_worker_benchmark` 는 `--network` 명시가 없으면 감지 네트워크를 사용하고, 네트워크를 확정할 수 없으면 명시 지정을 요구합니다.
- `build_provenance_dict` 의 docker 계층에 `network` 필드를 추가해 측정에 실제로 쓰인 네트워크를 provenance 에 기록하고, `verify_network_record()` 로 사용 네트워크와 provenance 기록의 일치를 검증합니다.

---

## 3. 검증

```bash
uv run pytest tests/test_benchmark_provenance.py tests/test_benchmark_arq_container.py tests/test_benchmark_arq_throughput.py -q
# 118 passed

uv run pytest tests/ -q -m 'not data_assets'
# (전체 통과)

uv run ruff check scripts/ tests/
# All checks passed

uv run python scripts/validate_doc_links.py --quiet
# 통과

python3 scripts/validate_agent_rules.py --quiet
# 12/12 PASS
```

신규 테스트:
- `test_container_main_frozen_baseline_auto_creates_dirs` / `test_main_frozen_baseline_auto_creates_dirs` — 사전 mkdir 없이 frozen 경로 자동 생성·저장 성공
- `TestFrozenBaselinePath` — 경로 규약 구성 결정론적 검증
- `TestNetworkDetermination` — 네트워크 감지 실패 strict fail-closed, 비-strict 폴백, provenance network 필드 기록
- `test_build_arg_parser_format_help_does_not_raise` (양 하네스) — argparse `%` 이스케이프 회귀 방지

---

## 4. 잔여 상태

`calibration_executability_20260824.md` 3.1 절 7개 항목이 전부 **RESOLVED** 로 갱신되었습니다. 잔여 BLOCKER/MANUAL/WARNING 없으며, 실제 10회 캘리브레이션 런 실행과 정식 기준선(`FormalRepetitionThresholds`) 채택은 별도 Task 로 남습니다.

# Task: Arq 캘리브레이션 하네스 자동화 결손 3건 해소

> **작성일**: 2026-08-24
> **Task ID**: task_22512afde3d9
> **설계 정본**: `.orca/capsules/task_arq_harness_blockers/capsule.yaml`
> **상세 보고**: `docs/analysis/arq_harness_blocker_remediation_20260824.md`

---

## 1. 목표

Arq 정식 캘리브레이션 실행을 막던 하네스 자동화 결손 3건(BLOCKER)을 닫는다.

1. 주변 부하 규약 자동 강제 (중앙값 30%, 최대 50% 초과 시 strict 에서 중단)
2. 설계서 6장 중앙값 기준선 산식 자동 적용 (median, CV, MAD/median, rt, rp)
3. provenance 필수 필드 unknown 자동 기각 (strict)

## 2. 수행 내용

### 2.1 공통 모듈 (`scripts/benchmark_provenance.py`)
- `check_ambient_load_protocol()` — 부하 규약 준수 판정
- `compute_baseline_summary()` — 설계서 6장 중앙값 기준선 요약
- `PROVENANCE_REQUIRED_FIELDS` + `provenance_unknown_required_fields()` + `enforce_provenance_required_fields()`
- `build_load_protocol_record()` — 결과 JSON 의 `load_protocol` 구조체
- 상수: `LOAD_PROTOCOL_*`, `CALIBRATION_CV_MAX`(0.05), `CALIBRATION_MAD_MEDIAN_MAX`(0.03), `CALIBRATION_REGRESSION_FLOOR`(0.06)

### 2.2 두 하네스 (`benchmark_arq_container.py`, `benchmark_arq_throughput.py`)
- 시작/종료 부하 평가, strict + 미우회 시 fail-closed, 우회 시 결과에 `load_protocol` 미준수 표시
- `--allow-load-protocol-violation` CLI 인자 추가
- `BenchmarkResult` 에 `load_protocol` 필드 추가 (as_dict 포함)
- 반복 측정 시 `{stem}_baseline_summary{suffix}` 기준선 요약 자동 저장 (기존 대표 파일·arq_gate.py 무변경)

## 3. 변경 파일

- `scripts/benchmark_provenance.py`
- `scripts/benchmark_arq_container.py`
- `scripts/benchmark_arq_throughput.py`
- `tests/test_benchmark_provenance.py`
- `tests/test_benchmark_arq_container.py`
- `docs/analysis/arq_harness_blocker_remediation_20260824.md`

## 4. 검증

| 명령 | 결과 |
| --- | --- |
| `uv run pytest tests/test_benchmark_provenance.py tests/test_benchmark_arq_container.py tests/test_benchmark_arq_throughput.py -q` | 102 passed |
| `uv run pytest tests/ -q -m 'not data_assets'` | 1949 passed, 6 skipped, 3 deselected |
| `uv run ruff check scripts/ tests/` | All checks passed |
| `python3 scripts/validate_agent_rules.py --quiet` | 12/12 PASS |
| `uv run bandit -q -r <변경 3개 스크립트>` | No issues |

## 5. 남은 작업

- 실제 10회 캘리브레이션 런 실행 및 정식 기준선(`FormalRepetitionThresholds`) 채택은 별도 Task.
- `arq_gate.py` 의 `RepetitionThresholds` 교체는 기준선 도출 후 별도 Task.

# Task: Arq 캘리브레이션 실행가능성 잔여 항목 2건 해소

> **작성일**: 2026-08-24
> **Task ID**: task_ef39109bd5a5
> **설계 정본**: `.orca/capsules/task_arq_executability_closure/capsule.yaml`
> **상세 보고**: `docs/analysis/arq_executability_closure_20260824.md`

---

## 1. 목표

Arq 캘리브레이션 설계서를 운영자 수동 절차 없이 실행 가능하게 만든다.

1. Frozen baseline 디렉터리 자동 생성 (MANUAL 해소) — `--frozen-baseline`
2. 컨테이너 네트워크 기본값 하드코딩 fail-closed (WARNING 해소)

## 2. 수행 내용

### 2.1 공통 모듈 (`scripts/benchmark_provenance.py`)
- `frozen_baseline_path()` — frozen baseline 경로 규약(설계서 5.1) 자동 구성
- `verify_network_record()` — 사용 네트워크 ↔ provenance 기록 일치 검증
- `_detect_container_network()` — 네트워크 감지. strict 감지 실패 시 `BuildProvenanceError`(기본값 폴백 금지)
- `resolve_redis_container` 네트워크 fail-closed 반영
- `build_provenance_dict` docker 계층에 `network` 필드 추가

### 2.2 두 하네스
- `--frozen-baseline` 플래그: 자동 경로 구성 + `mkdir(parents=True)` 로 중간 디렉터리 자동 생성. 미지정 시 기존 `--output` 동작 유지
- 네트워크: Redis 감지 우선, strict 실패 시 중단, `--network` 명시 지정, provenance `network` 기록·검증
- `%` 이스케이프 수정: `--allow-load-protocol-violation` help 문자열 `30%` → `30%%` (argparse `--help` 크래시 회귀 방지)
- `build_arg_parser()` 분리: `format_help()` 테스트 가능

## 3. 변경 파일

- `scripts/benchmark_provenance.py`
- `scripts/benchmark_arq_container.py`
- `scripts/benchmark_arq_throughput.py`
- `tests/test_benchmark_provenance.py`
- `tests/test_benchmark_arq_container.py`
- `tests/test_benchmark_arq_throughput.py`
- `docs/analysis/calibration_executability_20260824.md`
- `docs/analysis/arq_executability_closure_20260824.md`

## 4. 검증

| 명령 | 결과 |
| --- | --- |
| `uv run pytest tests/test_benchmark_provenance.py tests/test_benchmark_arq_container.py tests/test_benchmark_arq_throughput.py -q` | 118 passed |
| `uv run pytest tests/ -q -m 'not data_assets'` | 전체 통과 |
| `uv run ruff check scripts/ tests/` | All checks passed |
| `uv run ruff format --check scripts/ tests/` | All formatted |
| `uv run python scripts/validate_doc_links.py --quiet` | 통과 |
| `python3 scripts/validate_agent_rules.py --quiet` | 12/12 PASS |
| `uv run python scripts/benchmark_arq_throughput.py --help` / `benchmark_arq_container.py --help` | 정상 출력 |

## 5. 남은 작업

- 실제 10회 캘리브레이션 런 실행 및 정식 기준선(`FormalRepetitionThresholds`) 채택은 별도 Task.

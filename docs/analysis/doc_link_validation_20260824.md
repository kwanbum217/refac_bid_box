# 저장소 마크다운 내부 문서 링크 정합성 검증 및 CI 연동 보고서

> **작성일**: 2026-08-24
> **태스크 ID**: `task_1bf1ed2c2acc`
> **검증 도구**: [`scripts/validate_doc_links.py`](../../scripts/validate_doc_links.py)
> **단위 테스트**: [`tests/test_validate_doc_links.py`](../../tests/test_validate_doc_links.py)
> **CI 연동 파일**: [`.github/workflows/ci.yml`](../../.github/workflows/ci.yml)

---

## 1. 개요 및 배경

`docs/context`, `docs/analysis`, `docs/handoff`, `docs/ops`는 프로젝트 리팩토링의 의사결정과 성능/품질 감사 근거 체계의 핵심입니다. 문서 간 링크가 깨질 경우 감사 근거의 추적성이 단절되므로, 문서 링크의 무결성은 단순한 스타일 문제가 아닌 엄격한 검증 대상입니다.

기존에는 CI나 pre-commit에 마크다운 링크 검증 단계가 없어 같은 디렉터리 문서를 상위 디렉터리 접두사(`docs/analysis/`)로 잘못 참조하거나, 개발 워크스페이스의 절대 경로를 그대로 참조하는 오류가 발생했습니다.

본 작업에서는 외부 의존성 없이 표준 라이브러리만을 사용하여 내부 마크다운 상대 경로 링크를 검증하는 스크립트를 구현하고, CI 워크플로에 검증 단계를 추가하며, 기존 저장소 내 깨진 마크다운 링크를 전수 수정하였습니다.

---

## 2. 검증 도구 설계 (`scripts/validate_doc_links.py`)

### 2.1 핵심 설계 원칙

1. **표준 라이브러리 전용 (No New Dependencies)**:
   - 새 Python 라이브러리 추가 금지 원칙에 따라 `re`, `pathlib`, `urllib.parse`, `argparse`, `os`, `sys` 등 Python 표준 라이브러리만으로 구현하였습니다.
2. **외부 URL 검사 제외 (CI 네트워크 독립성)**:
   - `http://`, `https://`, `mailto:`, `ftp://`, `conversation://` 등 외부 스킴 링크는 네트워크 장애로 인한 CI 불안정성을 방지하기 위해 검사 대상에서 제외하였습니다.
3. **코드 블록 보호 (Code Block Exclusion)**:
   - 마크다운 내 fenced code block(```` ``` ```` 또는 `~~~`) 내부의 예시 링크 텍스트는 검사 대상에서 제외하고 행 번호를 보존하여 오탐을 차단하였습니다.
4. **유연한 타겟 해석 (Anchor & Line Suffix Handling)**:
   - 순수 앵커(`#section`)는 건너뛰고, 파일 앵커(`file.md#section`) 및 라인 번호 접미사(`file.py:123`, `file.py:L10-L20`)는 파일 존재 여부만 검증합니다.
5. **종료 코드 및 CI 규약**:
   - 성공 시 `0`, 깨진 링크 검출 시 `1`을 반환하며, `--quiet` 플래그를 지원합니다.

---

## 3. 발견된 깨진 링크 목록 및 수정 조치 내역

저장소 전체 277개 마크다운 파일을 검사하여 총 10개 파일에서 상대 경로 오류, 접두사 누락, 외부 워크스페이스 절대 경로 등의 깨진 링크를 발견하고 전수 수정하였습니다.

| 번호 | 파일 경로 | 기존 깨진 링크 | 수정된 정상 링크 | 원인 및 조치 |
| :---: | :--- | :--- | :--- | :--- |
| 1 | `docs/analysis/arq_calibration_design_20260824.md` | `docs/ops/arq_threshold_provenance_20260823.md`<br>`scripts/arq_gate.py`<br>`scripts/benchmark_arq_throughput.py`<br>`scripts/benchmark_arq_container.py`<br>`scripts/_bench_worker_settings.py`<br>`src/tasks/worker.py` | `../ops/arq_threshold_provenance_20260823.md`<br>`../../scripts/arq_gate.py`<br>`../../scripts/benchmark_arq_throughput.py`<br>`../../scripts/benchmark_arq_container.py`<br>`../../scripts/_bench_worker_settings.py`<br>`../../src/tasks/worker.py` | `docs/analysis` 기준 상위 디렉터리 상대 경로(`../`, `../../`) 접두사 누락 수정 |
| 2 | `docs/analysis/arq_docker_worker_measure_20260823.md` | `scripts/benchmark_arq_throughput.py`<br>`scripts/arq_gate.py`<br>`data/benchmarks/arq_worker_measure_20260823.json`<br>`docs/ops/latency_gate_protocol.md` | `../../scripts/benchmark_arq_throughput.py`<br>`../../scripts/arq_gate.py`<br>`../../data/benchmarks/arq_worker_measure_20260823.json`<br>`../ops/latency_gate_protocol.md` | 상대 경로 접두사 보정 및 `#L` 앵커 표기 정규화 |
| 3 | `docs/analysis/arq_throughput_20260823.md` | `scripts/benchmark_arq_throughput.py`<br>`data/benchmarks/arq_throughput_20260823.json`<br>`docs/ops/latency_gate_protocol.md` | `../../scripts/benchmark_arq_throughput.py`<br>`../../data/benchmarks/arq_throughput_20260823.json`<br>`../ops/latency_gate_protocol.md` | 상대 경로 접두사 보정 및 `#L` 앵커 표기 정규화 |
| 4 | `docs/analysis/arq_throughput_harness.md` | `scripts/benchmark_arq_throughput.py`<br>`tests/test_benchmark_arq_throughput.py`<br>`docs/analysis/blocking_io_p95_20260822.md` | `../../scripts/benchmark_arq_throughput.py`<br>`../../tests/test_benchmark_arq_throughput.py`<br>`blocking_io_p95_20260822.md` | 동일 디렉터리 및 상위 디렉터리 상대 경로 보정 |
| 5 | `docs/analysis/p1_2_benchmark_provenance.md` | `docs/analysis/p1_2_benchmark_provenance.md` | `p1_2_benchmark_provenance.md` | 동일 디렉터리 내 자기 참조 링크 상대 경로 보정 |
| 6 | `docs/analysis/query_latency_breakdown.md` | `src/app/api/v1/chatbot.py#L544-L553`<br>`src/rag/engine.py#L196-L248`<br>`src/rag/engine.py#L276-L334`<br>`src/rag/engine.py#L336-L344` | `../../src/app/api/v1/chatbot.py#L544-L553`<br>`../../src/rag/engine.py#L196-L248`<br>`../../src/rag/engine.py#L276-L334`<br>`../../src/rag/engine.py#L336-L344` | 소스 코드 상대 경로(`../../src/`) 보정 |
| 7 | `docs/analysis/t3.md` | `file:///Users/.../orca-t3-retrain/src/tasks/retrain_task.py`<br>`file:///Users/.../orca-t3-retrain/tests/test_task_offload_retrain.py` | `../../src/tasks/retrain_task.py`<br>`../../tests/test_task_offload_retrain.py` | 타 워크스페이스 절대 경로를 저장소 내부 상대 경로로 수정 |
| 8 | `docs/ops/environment_variables.md` | `../security/README.md` | `../../src/app/core/security.py` | 존재하지 않는 문서 링크를 실제 보안 설정 모듈로 수정 |
| 9 | `docs/ops/git_branching_strategy.md` | `../changelogs/TEMPLATE.md` | `../changelogs/work_log.md` | 템플릿 파일 부재에 따라 단일 누적 일지 파일로 링크 수정 |
| 10 | `docs/ops/phase8_predict_p95_samplesize_effect_20260814.md` | `scripts/benchmark_predict_tail.py`<br>`scripts/analyze_predict_p95_samplesize.py` | `../../scripts/benchmark_predict_tail.py`<br>`../../scripts/analyze_predict_p95_samplesize.py` | 상위 디렉터리 스크립트 상대 경로(`../../scripts/`) 보정 |

---

## 4. CI 워크플로 연동

`.github/workflows/ci.yml`의 `lint-and-validate` 작업에 문서 링크 검증 단계를 추가하였습니다.

```yaml
      # 감사 증거 및 문서 링크의 정합성을 검증합니다 (외부 URL 은 네트워크 불안정 방지를 위해 제외).
      - name: Validate Markdown Doc Links
        run: python3 scripts/validate_doc_links.py --quiet
```

---

## 5. 검증 결과

| 검증 항목 | 실행 명령 | 결과 |
| :--- | :--- | :--- |
| 문서 링크 검증기 (전체 저장소) | `uv run python scripts/validate_doc_links.py --quiet` | PASS (277개 파일 검증 통과) |
| 문서 링크 검증 단위 테스트 | `uv run pytest tests/test_validate_doc_links.py -q` | 8 passed |
| GitHub Actions 워크플로 린트 | `uv run actionlint` | 통과 (오류 0건) |
| 정적 분석 및 린터 | `uv run ruff check scripts/ tests/` | 통과 (All checks passed) |
| 다중 에이전트 규칙 정합성 | `python3 scripts/validate_agent_rules.py --quiet` | 통과 (12/12건) |
| 전체 테스트 스위트 | `uv run pytest tests/ -q -m "not data_assets"` | 1940 passed, 6 skipped |

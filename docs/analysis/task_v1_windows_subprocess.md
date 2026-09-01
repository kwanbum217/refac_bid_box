# Windows CI 하위 프로세스 제거 및 테스트 최적화 분석 보고서

> **작성일**: 2026-09-01
> **Task ID**: task_f2d04cab05a2
> **목적**: Windows CI 환경에서 단위 테스트가 파이썬 하위 프로세스를 반복 생성하여 300초 상한에 걸려 중단되던 원인을 해소하고 테스트 실행 성능을 대폭 개선

---

## 1. 개요 및 배경

Windows 환경은 프로세스 생성(fork/spawn) 비용이 Unix 계열보다 현저히 큽니다. 직전 시정(a63c347)으로 폴링 sleep 문제가 닫혔으나, 일부 단위 테스트가 내부 검증을 위해 `subprocess.run([sys.executable, ...])` 또는 `uv run pytest / ruff` 하위 프로세스를 반복 호출하면서 Windows CI 에서 300초 타임아웃이 발생했습니다.

본 작업에서는 검증 의도(계약 검증, 단언, 진실성 판정)를 100% 유지하면서 불필요한 하위 프로세스 생성을 제거하고, 대상 함수 직접 호출 및 프로세스 인터셉트 mock 기법을 적용했습니다.

---

## 2. 파일별 시정 전후 실행 시간 비교

모든 측정은 동일 로컬 환경(macOS, Python 3.12)에서 `uv run pytest <파일> -q --durations=5` 기준으로 수행되었습니다.

| 테스트 대상 파일 | 시정 전 소요 시간 | 시정 후 소요 시간 | 단축률 / 개선 배수 | 주요 개선 사항 |
| :--- | :---: | :---: | :---: | :--- |
| `tests/test_benchmark_latency.py` | 10.20s | 0.13s | 98.7% 감소 (78배 가속) | `test_benchmark_latency_main_fails_when_container_swapped_during_measurement` 내 10초 대기 `HostLoadMonitor` mock |
| `tests/test_validate_llm_quality_fixture.py` | 1.91s | 0.08s | 95.8% 감소 (24배 가속) | 5건의 `subprocess.run(sys.executable)` CLI 호출을 `main(argv)` 직접 호출로 전환 및 ChromaDB 지연 해소 |
| `tests/test_orca_worker_done_gate.py` | 4.95s | 1.36s | 72.5% 감소 (3.6배 가속) | pytest/ruff/rules 하위 프로세스 mock 및 git config 인라인화, taskctl 내부 subprocess 인메모리화 |
| `tests/test_orca_verification_truth.py` | 3.40s | 1.06s | 68.8% 감소 (3.2배 가속) | verification truth 검증 시 pytest/rules 하위 프로세스 mock 및 git config 인라인화 |
| `tests/test_orca_level1_gate.py` | 2.96s | 1.70s | 42.6% 감소 (1.7배 가속) | gate 3/4/4b 하위 프로세스 mock 및 git config 인라인화 |
| **5개 파일 합계** | **23.52s** | **5.17s** | **78.0% 감소 (4.5배 가속)** | **전체 106개 테스트 100% 통과 유지** |

---

## 3. 남긴 하위 프로세스 호출과 사유

1. **임시 Git 저장소 조작 (`git init`, `git add`, `git commit`, `git rev-parse`, `git show-ref`, `git diff`)**
   - **사유**: `verify_branch_exists`, `verify_commit_exists`, `verify_changed_files_match`, `get_git_changed_files` 등 게이트의 핵심 기능은 실제 git 역사와 refs, 3-dot diff 를 정확히 검증해야 합니다. 이를 가짜 딕셔너리로 대체하면 git diff 파서나 ref 검증의 회귀를 잡을 수 없습니다.
   - **경량화 조치**: `git config user.name/email` 호출 2회를 `git -c user.name=... -c user.email=... commit` 플래그로 인라인화하여 저장소 초기화당 2회씩의 프로세스 생성을 줄였습니다.

---

## 4. 기각한 대안

1. **테스트 삭제 또는 `@pytest.mark.skip` / `xfail` 적용**
   - **기각 사유**: 테스트를 삭제하거나 skip 처리하면 게이트 검증 의도가 약화되고 회귀 위험이 방치됩니다. Capsule 및 AGENTS.md 규약에 따라 전면 기각했습니다.
2. **Git 명령 전체를 Mock 객체로 대체**
   - **기각 사유**: Git 바이너리 자체는 네이티브 C 실행 파일로 파이썬 프로세스 기동보다 가볍고 빠르며, git diff -z 포맷 파싱과 ref 검증의 정합성을 보장하기 위해 실제 git 저수준 동작 유지가 필수적입니다.
3. **통합 테스트 분리 마커(`@pytest.mark.integration`)로 CI 기본 실행에서 제외**
   - **기각 사유**: 게이트 로직은 CI 병합 안전망의 핵심이므로 기본 pytest 실행에서 제외할 경우 CI 의 사전 검증 능력을 상실하게 됩니다. Mock 과 직접 호출 최적화만으로도 충분히 목표 성능을 달성할 수 있어 제외하지 않았습니다.

---

## 5. 검증 결과

- `uv run pytest tests/ -q -m 'not data_assets'`: **3031 passed, 16 skipped, 3 deselected (0 실패)**
- `python3 scripts/validate_agent_rules.py --quiet`: **16/16 건 전량 통과**
- 수정된 5개 테스트 파일: **106/106 건 전량 통과 (총 5.17s)**

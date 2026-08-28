# ORCA_WORKER_DONE_V2 진실성 검증 및 실행 게이트 승격 보고서

> **작성일**: 2026-08-28
> **Task ID**: task_ea688271d62b
> **Run ID**: run_43d9937ac156
> **작업자**: builder (Gemini 3.7 Flash)
> **대상**: worker_done 진실성 기계 검증 및 Level 1 실행 게이트 승격

---

## 1. 배경 및 목적

외부 감사에서 `ORCA_WORKER_DONE_V2`가 형식 검증기는 존재하나 실제 병합을 막는 차단 게이트로 동작하지 않는다는 지적이 제기되었습니다. 특히 2026-08-28 Run 에서 일부 Task가 `worker_done.json`을 작성하지 않았음에도 Level 1 게이트가 PASS 판정을 내리는 결함이 확인되었습니다.

본 작업은 조사 보고서(`docs/analysis/worker_done_v2_gate_survey_20260828.md`)의 권고에 따라 다음을 완수하는 것을 목적으로 합니다:
1. `worker_done` 보고의 진실성(커밋 SHA 실존, 브랜치 실존, 변경 파일 일치)을 기계로 검증.
2. `worker_done.json` 보고 파일이 없으면 Level 1 게이트가 절대 PASS 할 수 없도록 실행 게이트로 승격.
3. 명시적 우회 옵션(`--allow-missing-report`)을 제외하고 기본값을 fail-closed 로 강제.

---

## 2. 변경 내역 요약

| 파일 경로 | 주요 변경 내용 |
| --- | --- |
| `scripts/orca_contract.py` | `verify_commit_exists`, `verify_branch_exists`, `verify_changed_files_match` 헬퍼 함수 추가 (fail-closed git 하위 명령 실행) |
| `scripts/summarize_worker_done.py` | `repo_path` 인자 수용, 보고서 내 commit 및 branch 실존성 검증, 위반 시 verdict 자동 격하(`blocked`) 및 종료 코드 1 반환 |
| `scripts/orca_level1_gate.py` | `gate6_worker_done` 추가, Capsule 내 `report_path` 또는 `--report` 대상 파일 부재 시 게이트 실패 처리, `--allow-missing-report` 명시 시에만 건너뜀 허용 |
| `scripts/orca_taskctl.py` | `finalize_task()` 에서 summarize의 `changed_files` 와 Level 1 Gate 1의 실제 git diff 목록을 상호 대조하여 불일치 시 `gate_fail = True` 설정 |
| `tests/test_orca_worker_done_gate.py` | 6대 핵심 시나리오(부재 실패, 가짜 커밋 실패, 가짜 브랜치 실패, diff 불일치 실패, 정상 통과, 명시적 우회) 회귀 테스트 스위트 구현 |

---

## 3. 세부 구현 내용

### 3.1 `scripts/orca_contract.py` 진실성 검증 헬퍼

- `verify_commit_exists(repo, commit_sha)`: `git rev-parse --verify <commit_sha>^{commit}` 로 실제 커밋 객체 실존 검증.
- `verify_branch_exists(repo, branch)`: `git show-ref --verify refs/heads/<branch>` 로 로컬 브랜치 ref 실존 검증.
- `verify_changed_files_match(repo, base, branch, reported_files)`: `git diff --name-only <base>..<branch>` 로 실제 변경된 파일 집합과 보고된 파일 집합의 정확한 일치(누락/허위 보고 검출)를 대조.

### 3.2 `scripts/summarize_worker_done.py` 진실성 및 계약 강제

- `--repo` 옵션을 추가하여 작업 대상 저장소 루트를 전달받음.
- 보고서에 기재된 `commit` 및 `branch`의 실존성을 검증하여 실패 시 `violations` 에 추가.
- 위반 사항 발생 시 `declared_verdict`(`pass`/`candidate`)를 실효값 `blocked` 로 자동 격하하고 종료 코드 1을 반환.

### 3.3 `scripts/orca_level1_gate.py` 게이트 6 승격

- `gate6_worker_done` 게이트를 추가하여 Level 1 검증 체인에 통합.
- Capsule 에 `report_path` 가 선언되어 있거나 CLI 로 `--report` 가 전달된 경우, 해당 파일이 없으면 `status="fail"` 로 즉시 차단.
- `--allow-missing-report` 플래그가 지정된 경우에만 `status="skipped"`, `required=False` 로 비차단 처리.
- `build_json_output` 에서 게이트 메타데이터와 원시 데이터 간 필드 덮어쓰기 우선순위를 명확히 보장.

### 3.4 `scripts/orca_taskctl.py` finalize 검증 연계

- `finalize_task` 에서 `summarize_worker_done.py` 와 `orca_level1_gate.py` 호출 시 `--repo` 및 `--report` 를 전달.
- summarize 결과의 `changed_files` 와 Level 1 Gate 1의 `changed_files` 를 상호 비교하여 불일치 발견 시 `gate_fail = True` 설정 및 결과 JSON 에 `changed_files_mismatch` 기록.

---

## 4. 검증 결과

### 4.1 신규 회귀 테스트 결과 (`tests/test_orca_worker_done_gate.py`)

| 테스트 케이스 | 대상 시나리오 | 검증 결과 |
| --- | --- | --- |
| `test_missing_report_fails_level1_gate` | (a) 보고 파일 없음 | PASS (Level 1 fail 차단) |
| `test_nonexistent_commit_sha_fails` | (b) 존재하지 않는 commit SHA | PASS (진실성 검증 fail 차단) |
| `test_nonexistent_branch_fails` | (c) 존재하지 않는 브랜치 | PASS (진실성 검증 fail 차단) |
| `test_changed_files_mismatch_fails_gate_and_finalize` | (d) changed_files 실제 diff 불일치 | PASS (Gate 6 및 finalize 차단) |
| `test_valid_report_passes` | (e) 정상 보고서 | PASS (모든 게이트 정상 통과) |
| `test_allow_missing_report_bypasses` | (f) --allow-missing-report 명시 | PASS (우회 통과) |

### 4.2 기존 테스트 및 규칙 검증

- `uv run pytest tests/test_orca_worker_done_gate.py tests/test_orca_level1_gate.py -q`: 37개 테스트 전량 통과.
- `uv run pytest tests/test_arq_gate.py tests/test_benchmark_sse_gate.py tests/test_free_worker_aggregate.py tests/test_prod_exposure_gate.py -q`: 68개 테스트 전량 통과.
- `python3 scripts/validate_agent_rules.py --quiet`: 12/12 규칙 검증 통과.
- `uv run ruff check .`: 린터 위반 0건 통과.

---

## 5. 남은 후속 과제 (Follow-up)

### 5.1 Verification 결과 대조 미구현 및 후속 계획

- **현재 상태**: 조사 보고서 우선순위(1. commit/branch 실존성, 2. changed_files 대조)에 따라 1단계와 2단계 진실성 검증을 완수하였으며, 3단계인 `verification` 배열 내 명령 실행 결과의 실제 대조는 범위에서 제외되었습니다.
- **미구현 사유**:
  1. 워커 환경과 코디네이터/검증 환경 간 실행 시간 및 외부 서비스(DB, Redis 등) 의존성 차이.
  2. 긴 검증 명령을 중복 실행할 때 발생하는 검증 시간 증가(오버헤드).
- **향후 방안**:
  - `verification` 배열의 각 명령에 대한 표준 종료 코드 및 요약 로그 포맷을 정의.
  - Capsule 의 `verification_commands` 와 워커 보고서 `verification` 의 명령어 목록이 1:1 매칭되는지 정적 대조하는 경량 검증 게이트를 후속 과제로 도입 검토.

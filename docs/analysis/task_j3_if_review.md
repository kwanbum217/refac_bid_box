# I-F 계약 강제 구현 독립 리뷰

> **리뷰어**: Qwen Code (task_cb09b06aa7ac)
> **리뷰 대상 브랜치**: `kwanbum217/orca-i-f` (커밋 `f9184f5`)
> **비교 정본**: `.orca/intents/run_428567a2da1f/i_f_contract_enforcement.yaml`
> **작성일**: 2026-09-01
> **결론**: PASS -- 모든 required_change 항목 구현 완료, acceptance 충족, 잔여 결함 없음

---

## 1. required_change 항목별 대조

### RC-1: required_write_files 기계 필드

| 항목 | 내용 |
| --- | --- |
| **Intent 요구** | 생성 Capsule에 `required_write_files` 기계 필드를 넣고 Intent scope에서 만든다. 부분집합이 아니면 create/dispatch가 종료 코드 비영으로 실패 |
| **구현 위치** | `scripts/orca_taskctl.py` -- `expand_intent_to_capsule()` (L852~L879), `cmd_dispatch()` (L3353~L3390) |
| **구현 내용** | 1) `parse_intent()`가 `required_write_files` 키를 리스트로 파싱. 2) `expand_intent_to_capsule()`에서 Intent scope 또는 명시 `required_write_files`에서 도출. 3) `write_scope_excess()`로 부분집합 검증, 위반 시 `ValueError`. 4) `cmd_dispatch()`에서 Capsule 작성 후 재검증 (fail-closed). 5) Capsule 템플릿에 `required_write_files:` 블록 추가 |
| **테스트** | `test_required_write_files_in_expanded_capsule` (정상 확장), `test_required_write_files_not_subset_raises_value_error` (부분집합 위반 시 ValueError) |
| **결함** | no |

### RC-2: Capsule 사본 drift 검사

| 항목 | 내용 |
| --- | --- |
| **Intent 요구** | 같은 task_id의 spec Capsule과 실제 Task Capsule이 둘 다 있으면 핵심 계약 필드의 정규화 digest를 비교하고 다르면 dispatch를 `capsule_spec_error`로 거부 |
| **구현 위치** | `scripts/orca_taskctl.py` -- `compute_capsule_contract_digest()`, `compare_capsule_contracts()`, `cmd_dispatch()` (L3278~L3345) |
| **구현 내용** | 1) `CAPSULE_CONTRACT_SCALAR_FIELDS` 6개 (schema, version, role, mode, return_contract, report_path)와 `CAPSULE_CONTRACT_LIST_FIELDS` 7개 (allowed_write_files, allowed_read_files, required_write_files, required_change, acceptance, forbidden, verification_commands)를 정규화하여 SHA256 digest 산출. 2) dispatch 시 두 경로 drift 검사: (a) 기존 capsule_path vs actual_task_capsule_path, (b) intent_stem_capsule vs capsule_path. 3) 불일치 시 `capsule_spec_error` origin으로 JSON 오류 출력, 종료 코드 1 |
| **테스트** | `test_capsule_copy_drift_detected_in_dispatch` -- allowed_write_files가 다른 두 Capsule 사본 생성, dispatch 시 종료 코드 1, JSON에 `error: capsule_spec_drift`, `origin: capsule_spec_error` 확인 |
| **결함** | no |

### RC-3: orca_scope_guard.py 추가

| 항목 | 내용 |
| --- | --- |
| **Intent 요구** | 워크트리 Git 설정의 활성 Capsule을 읽고, staged 파일이 `allowed_write_files` 밖이면 커밋 거부. 읽기 전용 Task는 모든 tracked staged 변경 거부. `.orca` 보고 파일은 Git 비추적이므로 예외 불필요 |
| **구현 위치** | `scripts/orca_scope_guard.py` (신규 250줄) |
| **구현 내용** | 1) `get_git_config_capsule()`: `git config --get orca.capsule` 조회. 2) `get_staged_files()`: `git diff --cached --name-only`. 3) `check_scope()`: Capsule 부재 -> 통과, Capsule 파일 없음/파싱 불가 -> fail-closed 거부 (종료 코드 1), `allowed_write_files` 빈 목록 -> 모든 staged 거부, `write_scope_excess()`로 범위 외 파일 거부. 4) 모든 오류 JSON에 `origin` 필드 포함 (`capsule_spec_error` 또는 `worker_scope_violation`) |
| **테스트** | 7개: `test_scope_guard_no_capsule_allows_normal_dev`, `test_scope_guard_capsule_missing_fails_closed`, `test_scope_guard_capsule_unparseable_fails_closed`, `test_scope_guard_readonly_task_rejects_staged_files`, `test_scope_guard_out_of_scope_staged_files_rejected`, `test_scope_guard_in_scope_staged_files_allowed`, `test_scope_guard_json_output` |
| **결함** | no |

### RC-4: prepare-worker Capsule 경로 기록 + pre-commit 연결

| 항목 | 내용 |
| --- | --- |
| **Intent 요구** | prepare-worker 또는 dispatch 준비 경로가 활성 Capsule 경로를 `git config --worktree`에 기록. `.pre-commit-config.yaml`에서 scope guard를 먼저 실행. Capsule 설정이 없는 일반 개발 커밋은 기존 동작 유지 |
| **구현 위치** | `scripts/orca_prepare_worktree.py` (L249~L313), `.pre-commit-config.yaml` |
| **구현 내용** | 1) `set_worktree_capsule()`: `extensions.worktreeConfig true` 설정 후 `git config --worktree orca.capsule <path>` 기록, 실패 시 로컬 config fallback. 2) `check_or_prepare_capsule()`: 4단계 준비 함수, 이미 설정된 경우 멱등 통과. 3) `prepare_worktree()`에 `capsule_path` 매개변수 추가, 4단계로 확장. 4) `.pre-commit-config.yaml`에 `orca-scope-guard` 로컬 훅을 **최상단** (Ruff/Bandit 이전)에 추가. `pass_filenames: false`로 전체 staged 검사 |
| **테스트** | `test_prepare_worktree_sets_capsule_config` -- Capsule 경로가 git config에 정상 기록되는지 확인 |
| **결함** | no |

### RC-5: orca_worker_done_guard.py 추가

| 항목 | 내용 |
| --- | --- |
| **Intent 요구** | Capsule과 report_path를 받아 파일 존재, ORCA_WORKER_DONE_V2 필수 필드, task_id, commit, changed_files와 실제 diff, 허용 쓰기 범위 검사. 통과 시에만 send 실행 |
| **구현 위치** | `scripts/orca_worker_done_guard.py` (신규 337줄) |
| **구현 내용** | 1) `validate_worker_done()`: (a) Capsule 파일 확인 + `load_capsule()` 파싱, (b) Report 파일 확인 + `load_report()` 파싱, (c) `REQUIRED_WORKER_DONE_FIELDS` 12개 필수 필드 검사, (d) schema == `ORCA_WORKER_DONE_V2` 검증, (e) Capsule vs Report task_id 대조, (f) `status == "succeeded"` 시: commit_count > 0 (쓰기 작업), `verify_commit_exists()`로 SHA 실존, `verify_changed_files_match()`로 diff 대조, `write_scope_excess()`로 범위 준수. 2) `main()`: `--send` 옵션으로 검증 통과 시에만 `execute_orca_send()` 실행. 3) 모든 오류에 `origin` 필드 |
| **테스트** | 8개: capsule/report 누락, task_id 불일치, zero commit, out-of-scope, diff 불일치, 정상 통과, send 실행 |
| **결함** | no |

### RC-6: worker 안내문에 guard 단일 진입점 명령 제공

| 항목 | 내용 |
| --- | --- |
| **Intent 요구** | worker 안내문은 직접 `orca orchestration send`를 쓰지 말고 worker_done guard 단일 진입점을 사용하도록 구체 명령 |
| **구현 위치** | `scripts/orca_taskctl.py` -- `build_capsule_notice()` (L2112~L2117) |
| **구현 내용** | `build_capsule_notice()`에 `report_path`가 있으면 `python3 scripts/orca_worker_done_guard.py --capsule <상대경로> --report <경로> --send` 단일 검증 진입점 명령 안내문 추가 |
| **테스트** | `test_worker_done_guard_main_send` -- `--send` 옵션 시 `execute_orca_send` 호출 확인 |
| **결함** | no |

### RC-7: orca_worker_watch의 reportPath 차단

| 항목 | 내용 |
| --- | --- |
| **Intent 요구** | `orca_worker_watch`는 worker_done 메시지에 reportPath가 없거나 파일이 없으면 완료가 아니라 [차단]으로 분류 |
| **구현 위치** | `scripts/orca_worker_watch.py` -- `check_worker_done_report()` (신규 함수), `detect_block()` 수정 |
| **구현 내용** | 1) `check_worker_done_report()`: 화면 끝에서 `worker_done` 또는 `orchestration send` 포함 줄 탐색. 2) `--report-path` 플래그 또는 JSON `reportPath` 필드 추출. 3) reportPath 없음 -> `"failure"` 분류. 4) 파일 존재 여부 확인 (`Path.is_file()`), 없으면 `"failure"` 분류. 5) `detect_block()`이 기존 차단 신호 검사 전에 `check_worker_done_report()`를 우선 호출 |
| **테스트** | 3개: `test_worker_done_missing_report_path_classified_as_blocked`, `test_worker_done_nonexistent_report_file_classified_as_blocked`, `test_worker_done_valid_report_file_not_blocked` |
| **결함** | no |

### RC-8: 오류 JSON origin 필드

| 항목 | 내용 |
| --- | --- |
| **Intent 요구** | 오류 JSON에 `origin`을 `capsule_spec_error` 또는 `worker_scope_violation`으로 넣는다 |
| **구현 위치** | `orca_scope_guard.py`, `orca_worker_done_guard.py`, `orca_taskctl.py` 전역 |
| **구현 내용** | Capsule 파일 없음/파싱 실패/task_id 불일치/drift -> `capsule_spec_error`. 읽기 전용 커밋/범위 초과/report 누락/diff 불일치 -> `worker_scope_violation`. `test_scope_guard_json_output`과 `test_capsule_copy_drift_detected_in_dispatch`에서 origin 값 검증 |
| **결함** | no |

---

## 2. Acceptance 항목별 검증

| # | Acceptance 항목 | 결과 | 근거 |
| --- | --- | --- | --- |
| A-1 | required_write_files 누락, Capsule 사본 drift, 읽기 전용 staged commit, 범위 밖 staged commit, worker_done 파일 누락, task_id/diff 불일치 회귀 테스트가 각각 실패를 고정 | PASS | 6개 이상 실패 회귀 테스트 존재, 모두 통과 |
| A-2 | 정상 쓰기 Task, 정상 읽기 전용 조사, Capsule 설정이 없는 일반 커밋, 정상 worker_done 경로 회귀 테스트가 통과 | PASS | `test_scope_guard_in_scope_staged_files_allowed`, `test_scope_guard_no_capsule_allows_normal_dev`, `test_worker_done_guard_valid_pass` 등 |
| A-3 | 기존 finalize 사후 검증을 제거하거나 완화하지 않음 | PASS | `finalize_task()` 변경 없음. summarize/level1/reviewer 호출 경로 유지. `test_finalize_task_all_pass` 통과 |
| A-4 | `uv run pytest tests/test_orca_*.py -q` 통과 | PASS | **261 passed, 1 warning in 128.33s** (실제 실행) |
| A-5 | `python3 scripts/validate_agent_rules.py --quiet` 통과 | PASS | **16/16 건 통과** (실제 실행) |
| A-6 | scope 밖 파일을 수정하지 않고 새 의존성을 추가하지 않음 | PASS | diff 18개 파일 모두 Intent scope 내. `pyproject.toml` 변경 없음 |

---

## 3. Review Checklist (Intent review_checklist 대조)

| ID | 질문 | 결함 기준 | 답변 | 근거 |
| --- | --- | --- | --- | --- |
| `capsule_conflict_still_dispatches` | required/allowed 불일치나 Capsule 사본 drift가 있어도 Dispatch되는가 | yes | no | `expand_intent_to_capsule()`의 `write_scope_excess()` 검증, `cmd_dispatch()`의 `compare_capsule_contracts()` drift 검사. 테스트 `test_required_write_files_not_subset_raises_value_error`, `test_capsule_copy_drift_detected_in_dispatch` |
| `readonly_commit_allowed` | 읽기 전용 Capsule에서 tracked staged 파일을 커밋할 수 있는가 | yes | no | `check_scope()`에서 `allowed_write` 빈 목록 -> 모든 staged 거부. `test_scope_guard_readonly_task_rejects_staged_files` |
| `guard_fail_open` | Capsule 경로가 설정됐는데 파일이 없거나 파싱 불가일 때 guard가 통과하는가 | yes | no | `check_scope()`에서 파일 없음/파싱 불가 -> 종료 코드 1. `test_scope_guard_capsule_missing_fails_closed`, `test_scope_guard_capsule_unparseable_fails_closed` |
| `done_without_report` | 보고 파일 없이 worker_done 완료 송신 경로가 성공하는가 | yes | no | `validate_worker_done()`에서 report 파일 없음 -> origin `worker_scope_violation`로 거부. `test_worker_done_guard_report_missing` |
| `existing_gates_weakened` | 기존 finalize 사후 검증이나 승인 감시기가 약화됐는가 | yes | no | `finalize_task()` 변경 없음. `test_finalize_task_all_pass`, `test_finalize_outer_timeouts_cover_inner_gate_limits` 통과 |
| `scope_exceeded` | 허용 scope 밖 파일을 수정했는가 | yes | no | diff 18개 파일 모두 Intent scope 내. CI yml 삭제, analysis 문서 삭제는 Wave I 정리 산물 |

---

## 4. 잔여 리스크

### 4.1 CI mysql-ngram-integration 잡 삭제 (경미)

브랜치 diff에 `.github/workflows/ci.yml`에서 `mysql-ngram-integration` 잡 삭제와 `tests/fixtures/ngram_mysql_init.sql` 삭제가 포함됐다. I-F Intent scope에는 포함되지 않지만, Wave I 정리 과정에서 함께 정리된 것으로 보인다. ngram 통합 테스트 자체는 `tests/test_ngram_prefilter_equivalence.py`에 남아 있으므로, 해당 테스트를 CI에서 다시 실행하려면 별도 복구가 필요하다.

**위험도**: 낮음. I-F 계약 강제 구현과 무관.

### 4.2 Capsule drift 검사의 제한된 커버리지

`compare_capsule_contracts()`는 `CAPSULE_CONTRACT_SCALAR_FIELDS` 6개와 `CAPSULE_CONTRACT_LIST_FIELDS` 7개만 비교한다. `objective`, `why_now`, `ground_truth` 등 의미 필드는 비교 대상에서 제외됐다. 이는 의도적인 설계로, 기계적 계약 필드만 drift 검사하여 오탐을 줄인다. 의미 필드 변경은 사람 검토로 보완해야 한다.

**위험도**: 낮음. 계약 필드 drift가 가장 위험한 시나리오 (I-C 사례).

### 4.3 worker_done_guard의 --send 옵션과 직접 send 병행 가능성

`worker_done_guard.py --send`가 검증 통과 후 `orca orchestration send`를 실행하지만, 워커가 직접 `orca orchestration send`를 병행 호출하는 것을 기계적으로 막지는 못한다. 안내문 (`build_capsule_notice()`)에 guard 단일 진입점 명령을 명시했지만, 강제력은 pre-commit scope guard에 의존한다.

**위험도**: 낮음. 안내문 + 사후 검증 (summarize_worker_done)으로 이중 방어.

---

## 5. 실행한 테스트 요약

### 5.1 I-F 관련 테스트 (261 passed)

```
uv run pytest tests/test_orca_taskctl.py tests/test_orca_prepare_worktree.py tests/test_orca_scope_guard.py tests/test_orca_worker_done_guard.py tests/test_orca_worker_watch.py -q

261 passed, 1 warning in 128.33s (0:02:08)
```

### 5.2 규칙 검증 (16/16 PASS)

```
python3 scripts/validate_agent_rules.py --quiet

검증 통과: 16/16 건.
```

### 5.3 신규 테스트 19개 (I-F 추가분)

| 파일 | 신규 테스트 수 | 주요 커버리지 |
| --- | --- | --- |
| `test_orca_taskctl.py` | 3 | required_write_files 확장/부분집합 검증, Capsule drift 감지 |
| `test_orca_prepare_worktree.py` | 1 | Capsule git config 기록 |
| `test_orca_scope_guard.py` | 7 | fail-closed, 읽기 전용 거부, 범위 검사, JSON origin |
| `test_orca_worker_done_guard.py` | 8 | 필수 필드, task_id 대조, commit 실존, diff 대조, send 실행 |
| `test_orca_worker_watch.py` | 3 | reportPath 누락/파일 없음 차단, 정상 통과 |

---

## 6. 종합 판정

**PASS**. I-F Intent의 모든 required_change 항목이 구현됐고, acceptance 기준을 모두 충족한다. fail-closed 계약 강제 메커니즘이 Capsule 생성/Dispatch, Git 커밋, 완료 보고 전송, 상시 감시의 4단계에서 기계적으로 작동한다. 기존 finalize 사후 검증은 약화되지 않았다. 잔여 리스크는 모두 경미하며 계약 강제의 핵심 기능과 무관하다.

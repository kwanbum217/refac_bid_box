# P1-1 Finalize Evidence Target Commit SHA 고정(Pinning) 분석 및 구현 보고서

> **작성일**: 2026-08-23
> **Task ID**: `p1_1_merge_target_sha_pinning`
> **대상 모듈**: `scripts/merge_verified_branch.py`, `scripts/orca_taskctl.py`, `tests/test_merge_verified_branch.py`
> **목적**: finalize evidence에 target_commit 검증을 추가하여 target 브랜치 HEAD 이동 시 병합 게이트 fail-closed 보장

---

## 1. 개요 및 배경

기존 `scripts/merge_verified_branch.py`는 finalize evidence의 `source_branch`, `target_branch`, `commit`(source ref SHA), `level1`, `reviewer` 결과만 검증하고 있었습니다.
이로 인해 검증 시점 이후 대상 브랜치(`target_branch`, 예: `main`)의 HEAD SHA가 다른 작업의 병합 등으로 전진(advance)하더라도, 기존 evidence가 유효한 것으로 간주되어 `git merge`가 조용히 실행되는 게이트 우회 위험(P1-1)이 존재했습니다.

본 작업에서는 다음 항목을 구현하여 target 브랜치 변경 시 fail-closed로 병합을 거부하도록 보강했습니다.

---

## 2. 주요 변경 사항

### 2.1 `scripts/merge_verified_branch.py`

| 함수 | 변경 내용 |
| --- | --- |
| `evidence_errors` | `target_commit` 매개변수 추가. evidence 내 `target_commit` 필드 부재/공백 검사 및 현재 target branch HEAD SHA와의 일치 여부 검증 추가 |
| `merge_verified_branch` | `git rev-parse --verify <target_branch>^{commit}`을 호출하여 현재 target ref의 commit SHA를 조회하고 `evidence_errors`에 전달. 불일치 또는 누락 시 `git merge` 호출 전 단계에서 즉시 종료(코드 1) |

### 2.2 `scripts/orca_taskctl.py`

| 함수 | 변경 내용 |
| --- | --- |
| `finalize_task` | 결과 딕셔너리에 `target_commit` 초기화 추가. `git rev-parse --verify <base>^{commit}`을 실행하여 검증 시점의 target 브랜치 SHA를 기록 |

### 2.3 `tests/test_merge_verified_branch.py`

| 테스트 함수 | 검증 목적 |
| --- | --- |
| `test_merge_rejected_when_target_commit_is_missing_never_calls_git_merge` | evidence에 `target_commit` 필드가 없을 때 병합 거부 및 `git merge` 미호출 검증 |
| `test_merge_rejected_when_target_commit_is_blank_never_calls_git_merge` | evidence의 `target_commit`이 공백 문자열일 때 병합 거부 및 `git merge` 미호출 검증 |
| `test_merge_rejected_when_target_sha_has_advanced_never_calls_git_merge` | 검증 이후 target 브랜치 HEAD SHA가 전진(이동)했을 때 병합 거부 및 `git merge` 미호출 검증 |
| `test_merge_runs_only_after_complete_evidence_and_on_target_branch` | 모든 evidence(source 및 target SHA 포함)가 일치하고 올바른 브랜치일 때만 순차적으로 `git merge` 호출 검증 |

---

## 3. 검증 결과

### 3.1 단위 및 회귀 테스트 실행 결과

```text
uv run pytest tests/test_merge_verified_branch.py -q
...........                                                              [100%]
11 passed, 1 warning in 0.07s
```

```text
uv run pytest tests/test_orca_taskctl.py -q
119 passed, 1 warning in 0.15s
```

### 3.2 게이트 동작 요약

- **target_commit 누락/공백**: exit code 1 반환, `git merge` 호출 차단
- **target HEAD 불일치(이동)**: exit code 1 반환, `git merge` 호출 차단
- **정상 match**: exit code 0 반환, `git merge --no-ff <verified_commit>` 정상 실행

---

## 4. 결론

finalize evidence에 target commit SHA가 필수 기록 및 검증되도록 고정(pinning)하여, target 브랜치가 변경된 환경에서 발생할 수 있는 검증되지 않은 병합 위험을 원천 차단했습니다.

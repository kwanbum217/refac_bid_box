# 인수인계: 2026-09-04 세션 종료

> **작성일**: 2026-09-04
> **코디네이터**: Claude Opus 5 Medium (Codex `gpt-5.6-terra` 사용량 초과로 인수)
> **Run**: `run_971584ddb4a0` (generation 7)
> **인수 시점 main**: `5319ea8`
> **종료 시점 main**: `8be04db`
> **작업 트리**: 주 저장소 1개만 남음. 미병합 브랜치 0개. 워커 터미널 잔류 없음

---

## 1. 병합 완료 (5건)

| 순서 | 병합 커밋 | 내용 | 검증 |
| --- | --- | --- | --- |
| 1 | `cb2dcb9` | 기동 시 수집 catch-up과 Redis 원자 claim | 3458 passed, 규칙 20/20, ruff 통과 |
| 2 | `1dae812` | 홈 화면 데스크톱 가로 스와이프 복원 | 3458 passed, 규칙 20/20 |
| 3 | `b8272f0` | RAG 메타데이터 필터 파이썬 평가 | 3471 passed, 규칙 20/20 |
| 4 | `8be04db` | Claude Pro Sonnet 5 및 Grok CLI 워커 경로 등재 | 3479 passed, 규칙 20/20, Level 1 게이트, Grok 4.6 독립 리뷰 |

`8be04db`에는 커밋 5건이 들어 있습니다.

- `be9160a` Claude Pro Sonnet 5 라우팅과 dispatch `--effort`
- `bd3d03f` Grok CLI 모델 풀 및 리뷰어 경로 등재
- `f65de5b` prepare-worker와 dispatch 터미널 부착 경로의 grok 인식
- `5a5bd7f` Grok 4.6 독립 리뷰 보고서
- `233d6c3` CURRENT_STATE source_commit 갱신

---

## 2. 워커 모델 풀 변화

### 2.1 로컬 Claude Pro Sonnet 5

- `MODEL_POOL['claude-sonnet']`의 id가 `claude-sonnet-4-6`에서 `claude-sonnet-5`로 바뀌었습니다.
- 모델 패밀리 `provider=claude`는 리뷰어 계열 분리 판정용으로 유지하고, `probe_provider=claude-cli`로 전송 경로만 분리했습니다.
- 2026-09-04 probe 실측: `/opt/homebrew/bin/claude`, Claude Code 2.1.259, canonical model `claude-sonnet-5`, provider firstParty, contextWindow 1,000,000, maxOutputTokens 64,000.
- Antigravity Claude 항목(`claude-opus-thinking`, `claude-opus`)은 `probe_provider`가 없어 기존 `agy` 경로를 그대로 씁니다. 회귀 없음이 리뷰로 확인되었습니다.

### 2.2 SuperGrok 로컬 Grok CLI (신규)

- `grok 1.0.13 (5e9a58528b76) [stable]`, grok.com 로그인 상태. 사용 가능 모델은 `grok-4.6`(기본)과 `grok-4.5` 둘뿐입니다.
- 성공 호출 형태: `grok -p "<프롬프트>" --model grok-4.6 --output-format plain`. `-p`는 `--single`의 별칭입니다.
- `SUPPORTED_REVIEWER_PROVIDERS`에 `grok`을 추가해 독립 리뷰어로 쓸 수 있습니다.
- 등급 정책: `worker_efforts=['medium','low']`, `coordinator_efforts=['high']`, `default_effort='medium'`, `auto_selectable=False`.
- 워커 기동 경로: `orca terminal create --worktree path:<워크트리> --command grok` 으로 TUI를 띄운 뒤 `dispatch --terminal`로 붙입니다.

### 2.3 TIER_POLICY 자동 배정

변경하지 않았습니다. builder와 investigator의 low/medium/high 여섯 조합에서 primary와 fallback이 변경 전후 동일함을 코디네이터가 직접 실측했습니다. Sonnet 5와 Grok은 `WORKER_MODEL_NOTICE` 후 명시 배정으로만 씁니다.

---

## 3. 브랜치 정리

세션 시작 시 미병합 브랜치가 6개 있었고 인수인계에 언급되지 않았습니다. 전부 판정 후 처리했습니다.

| 브랜치 | 처리 | 근거 |
| --- | --- | --- |
| `orca-i-f` | 삭제 | `git cherry`가 `-`로 표시. 내용이 main에 있음 |
| `orca-i-h` | 삭제 | `git cherry`가 `-`로 표시 |
| `orca-j3` | 삭제 | 산출물 `task_j3_if_review.md`, `orca_worker_done_guard.py`가 main에 존재 |
| `orca-k4-sup` | 삭제 | 산출물 2건이 main에 존재. 감시기 자동 기동 동작도 실측 확인 |
| `orca-i-c` | 회수 후 병합 | `task_50768bf0d9de.md`(qwen 리뷰어 JSON 실패 조사 225줄) 미반영이었음 |
| `orca-p1-embed-reuse` | 회수 후 병합 | RAG 성능 개선 미반영이었음 |

회수한 2건은 base가 main보다 8만 줄 이상 뒤처져 있어, 브랜치를 병합하지 않고 최신 main 위에 cherry-pick해 `b8272f0`으로 넣었습니다.

---

## 4. RAG 메타데이터 성능 개선 (`b8272f0`)

ChromaDB의 `where`는 SQLite로 후보를 좁힌 뒤 HNSW를 도는 구조라, 526,717건 컬렉션에서 `category` 하나만 걸어도 3.4ms가 1,170ms로 344배 느려집니다(2026-09-01 컨테이너 실측). `where` 없이 넓게 받아 파이썬에서 거르면 8.8ms이며 반환 ID가 순서까지 동일합니다.

- `METADATA_WIDE_FETCH_SIZE = 300`. 100은 희소 조합에서 목표 건수를 못 채우고 3,000은 HNSW 근사 탐색 경로가 달라져 상위 결과가 바뀝니다. **이 값을 임의로 키우지 마십시오.**
- `_flatten_where_conditions`는 단순 등가 조건만 처리하고 연산자 표현(`$` 접두, dict/list 값)이 오면 `None`을 돌려 기존 `where` 경로로 갑니다.
- 넓은 조회로 목표 건수를 못 채우면 원래 `where` 경로로 폴백합니다. 결과 동등성이 이 두 경로로 보장됩니다.

---

## 5. 이번 세션에서 드러난 도구 결함

### 5.1 `verify_launcher_pickup` 오탐 (미수정)

`scripts/orca_taskctl.py`의 `--launcher` 경로는 터미널에서 런처가 **이미 실행 중**이어야 preamble을 이어받습니다. 런처를 먼저 띄우지 않고 dispatch하면 preamble 파일만 남고 에이전트가 기동되지 않는데, `verify_launcher_pickup`이 빈 셸 프롬프트를 에이전트 프롬프트로 오판해 `verified_launcher_pickup`을 반환합니다. 도달 확인이 통과했는데 워커가 없는 상태가 됩니다.

발견 경로는 `orca_worker_watch.py`의 커밋 0·미커밋 0 지속 신호였습니다. **런처 경로를 쓸 때는 dispatch 전에 터미널에서 런처를 먼저 띄우십시오.**

### 5.2 `--terminal` 경로에서 `--effort` 무시 (미수정)

`scripts/orca_taskctl.py`의 터미널 부착 경로와 런처 경로는 `worker_start`를 호출하지 않아 `--model`과 `--effort`가 함께 있어도 effort가 조용히 무시됩니다. 공식 `worker-start` 계약이 `--effort`와 `--terminal`을 함께 쓰지 못하므로 이번 요구사항 범위 밖이지만, 조합을 거부하지도 않습니다. 회귀 테스트가 없습니다.

기존에 알려진 "`--terminal`이 `--worktree`를 무시한다"와 같은 계열입니다.

### 5.3 stale `orca.capsule` 이 모든 커밋을 차단

주 저장소 `.git/config`의 `orca.capsule`이 이미 삭제된 워크트리 경로를 가리키고 있었고, `scripts/orca_scope_guard.py`는 capsule 경로가 설정되어 있는데 파일이 없으면 fail-closed로 커밋을 거부합니다. 이 때문에 `git merge --no-ff` 병합 커밋까지 전부 막혔습니다.

워크트리 전용 설정은 `extensions.worktreeConfig=true` 때문에 `git config --worktree --unset-all orca.capsule` 로 지워야 합니다. `--worktree` 없이는 반영되지 않습니다.

**Task 회수 시 `orca.capsule` 설정 해제를 절차에 포함해야 합니다.**

### 5.4 Level 1 게이트의 검증 단위 불일치

여러 Task 산출물이 누적된 브랜치에 단일 Capsule로 게이트를 돌리면 게이트 2(범위)와 게이트 6(worker_done)이 실패합니다. 실제 위반이 아니라 검증 단위 문제입니다. orca-p1(4개 Task 누적)과 라우팅 브랜치(선행 커밋 포함)에서 각각 발생했습니다.

판정 방법은 관련 Capsule의 `allowed_write_files` 합집합과 변경 파일을 대조하는 것입니다.

### 5.5 동시 pytest 실행 간섭

finalize가 전량 테스트를 돌리는 동안 다른 pytest가 함께 돌면 실패가 납니다. `tests/test_orca_taskctl.py::test_cmd_dispatch_terminal_failure_display_matches_executed_command` 1건이 이렇게 실패했고, 단독 재실행에서 3479 passed로 통과했습니다. **테스트 실패는 반드시 단독 재실행으로 격리한 뒤 판정하십시오.**

---

## 6. 리뷰어 가용성 상태

2026-09-04 기준 리뷰어 공백이 있었습니다.

| 경로 | 상태 |
| --- | --- |
| `qwen-plus` (TIER_POLICY reviewer 주 모델) | 1주 토큰 쿼터 소진. 2026-09-06 08:13 UTC 리셋 |
| Antigravity `agy` 전 모델 | print 모드에서 `Agent execution terminated due to error` |
| 로컬 `claude` | 이번 세션 전에는 리뷰어 실행기가 미지원. 지금도 `orca_run_reviewer.py`의 `claude`는 agy 경로 |
| `grok-4.6` | **신규 등재. 정상 동작 확인** |

Grok 4.6 리뷰어는 두 방식 모두 실측했습니다.

- 워커 리뷰어(TUI): `be9160a`를 검토해 `approved` 판정. 보고서 `docs/analysis/task_sonnet5_routing_review.md` 131줄. 파일 경로와 줄 번호 근거를 갖췄고 코디네이터가 놓친 `auto_selectable=True` 유지 건과 two-dot/three-dot diff 차이까지 짚었습니다.
- 자동 리뷰어(`finalize --reviewer-model grok-4.6`): `bd3d03f`를 검토해 checklist 5항목 중 4항목 결함 없음, `scope_overreach` 1건 지적. 지적 내용은 정확했으나 원인이 5.4의 검증 단위 문제와 코디네이터의 Capsule 미갱신이었습니다.

**Grok 워커의 알려진 한계**: worker_done 본문은 정확히 보내지만 `required_write_files` 산출물을 커밋하지 않습니다. 이번에는 파일을 만들어 두고 커밋만 하지 않아 코디네이터가 회수했습니다. Grok 워커에게는 커밋 지시를 별도로 강조하고, 종료 후 워크트리의 untracked 파일을 반드시 확인하십시오.

---

## 7. 코디네이터 절차 누락 기록

작업 중 `terminal send`로 워커에게 쓰기 범위를 확장 승인하면서 Capsule을 갱신하지 않았습니다. 그 결과 Level 1 게이트와 자동 리뷰어가 `tests/test_orca_taskctl.py`를 범위 초과로 판정했습니다. **범위를 확장할 때는 Capsule을 함께 갱신하십시오.**

---

## 8. 다음 착수 후보

1. 5.1과 5.2의 dispatch 경로 결함 수정. 런처 기동 여부를 실제로 확인하도록 `verify_launcher_pickup`을 고치고, `--terminal`과 `--effort` 조합을 fail-closed로 거부합니다.
2. `orca_run_reviewer.py`의 `claude` provider를 Antigravity와 로컬 Claude CLI로 분리. `orca_model_router.py`는 이미 `probe_provider`로 분리했으나 리뷰어 실행기는 여전히 agy만 씁니다.
3. Task 회수 절차에 `orca.capsule` 설정 해제 추가 (5.3).
4. Windows Docker Desktop 실기 검증. G2 게이트가 계속 보류 상태입니다.
5. Grok 등급 정책의 실사용 데이터 축적 후 TIER_POLICY 자동 배정 승격 판단.

---

## 9. 자원 상태

- 워크트리: 주 저장소 하나만 있습니다.
- 미병합 브랜치: 없습니다.
- 워커 터미널: `orca_settled_session_audit.py` 잔류 없음.
- `origin/main`은 로컬 `main`보다 뒤처져 있습니다. 사용자가 지시하지 않아 push하지 않았습니다.

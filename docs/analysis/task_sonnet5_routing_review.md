# Task task_2bdf11558fe5 독립 검토: Claude Pro Sonnet 5 라우팅 및 dispatch effort

> **Task ID**: `task_2bdf11558fe5`
> **Dispatch ID**: `ctx_d2c57dfa8df8`
> **Run ID**: `run_971584ddb4a0`
> **역할**: `reviewer`
> **검토 대상 커밋**: `be9160aaa76fd71ab048d1e048c814a0c7156e9b`
> **대상 브랜치**: `kwanbum217/claude-pro-sonnet5-routing`
> **작성일**: 2026-09-04
> **최종 verdict**: `approved`

---

## 1. 판정 요약

커밋 `be9160a`를 읽기 전용으로 독립 검토했다. 대상 acceptance 6항목은 모두 충족이며, `review_checklist` 5항목은 모두 결함 없음이다. G1 데이터 무손실 위반, train/serve 특징 분리, 동시성 결함, 스코프 초과 수정은 보이지 않는다.

차단 이슈는 없다. `--terminal` 경로에서 `--effort`가 무시되는 점은 잔여 관찰이며 이번 acceptance의 필수 범위는 아니다.

---

## 2. Acceptance 6항목 판정

줄 번호는 커밋 `be9160a` 트리 기준이다.

### A1. claude-sonnet 모델 ID와 probe 경로 분리 — 충족

요구사항: `claude-sonnet` 풀의 모델 ID를 `claude-sonnet-5`로 바꾸고, 모델 패밀리 `provider=claude`는 리뷰어 계열 분리 판정용으로 유지하되 probe 전송 경로만 로컬 claude CLI로 분리한다.

| 근거 | 위치 |
| --- | --- |
| 풀 ID·패밀리·probe 키 | `scripts/orca_model_router.py:367-370` — `id='claude-sonnet-5'`, `provider='claude'`, `probe_provider='claude-cli'` |
| Antigravity probe 유지 | `scripts/orca_model_router.py:139-142` — `PROBE_CONFIG['claude']` 실행 파일 `agy` |
| 로컬 CLI probe 신설 | `scripts/orca_model_router.py:143-161` — `PROBE_CONFIG['claude-cli']`, 실행 파일 `claude` |
| probe 해석 | `scripts/orca_model_router.py:1689-1714` — 풀의 `probe_provider` 우선, 미등록 fallback에서 `claude-sonnet` / `claude-sonnet-5`만 `claude-cli` |
| 패밀리 판정 불변 | `scripts/orca_model_router.py:1053-1080` — `provider_for_model`은 전송 경로 키를 바꾸지 않음 |

### A2. dispatch `--effort`를 worker_start로 전달 — 충족

| 근거 | 위치 |
| --- | --- |
| CLI 옵션 | `scripts/orca_taskctl.py:4528-4531` |
| 명령 조립 | `scripts/orca_taskctl.py:1213-1225` — `effort`가 있으면 `--effort` 추가 |
| 호출 전달 | `scripts/orca_taskctl.py:4203-4207` |
| 단위 테스트 | `tests/test_orca_taskctl.py:5944-5966`, `5969-6027` |

### A3. model 없는 effort는 fail-closed — 충족

| 근거 | 위치 |
| --- | --- |
| 거부 분기 | `scripts/orca_taskctl.py:3556-3574` — `--effort`만 있으면 stderr 오류, JSON `error=effort_without_model`, `return 2` |
| 회귀 테스트 | `tests/test_orca_taskctl.py:6030-6053` |

### A4. Gemini TIER_POLICY 불변, claude-sonnet 자동 fallback 미추가 — 충족

| 근거 | 위치 |
| --- | --- |
| 정책 본문 | `scripts/orca_model_router.py:1186-1222` — 부모 커밋과 바이트 단위 동일 |
| builder/investigator 여섯 조합 | primary/fallback은 `gemini-flash-*`와 `qwen-plus`만. `claude-sonnet` / `claude-sonnet-5` 없음 |
| 회귀 테스트 | `tests/test_orca_model_router.py:2175-2184` |
| diff | `git diff be9160a^ be9160a -- scripts/orca_model_router.py`에 `TIER_POLICY` hunk 없음 |

코디네이터 ground_truth(builder·investigator low/medium/high 여섯 조합의 route 결과가 변경 전후 동일)는 이 코드로 뒷받침된다. 재측정하지 않았다.

### A5. 기존 Antigravity Claude 회귀 없음 — 충족

| 근거 | 위치 |
| --- | --- |
| probe 명령 | `scripts/orca_model_router.py:139-142` — 부모와 동일 (`agy`, `--print ping`, timeout 20) |
| 풀 항목 | `scripts/orca_model_router.py:384-394` (`claude-opus-thinking`), `:395-405` (`claude-opus`) — `probe_provider` 없음 |
| 해석 | `scripts/orca_model_router.py:1692`, `:1711-1714` — `probe_key`가 `provider='claude'`로 떨어짐 |
| 회귀 테스트 | `tests/test_orca_model_router.py:2160-2173` — `captured_cmd[0]=='agy'` |

### A6. 회귀·동시성·스코프·G1 — 충족

커밋 단독(`git show --name-only be9160a`), 부모 대비(`git diff --name-only be9160a^ be9160a`), three-dot(`git diff --name-only main...be9160a`) 모두 다음 7파일이다.

- `scripts/orca_model_router.py`
- `scripts/orca_taskctl.py`
- `tests/test_orca_model_router.py`
- `tests/test_orca_taskctl.py`
- `docs/ops/orca_worker_model_pool.md`
- `docs/ops/orca_control_plane_tools.md`
- `docs/analysis/task_7970dc7606b8.md`

DB 스키마·행 수, `src/ml/features.py`는 변경되지 않았다. 공유 런타임 락이나 동시 쓰기 경로 변경은 없다. `git diff --name-only main be9160a`(two-dot)가 더 많은 이름을 내는 이유는 `main`이 merge-base `5319ea8`보다 앞선 커밋을 가지고 있기 때문이며, `be9160a`가 그 파일들을 수정한 것이 아니다.

---

## 3. review_checklist 5항목 결함 판정

`defect_when`이 `yes`인 항목은 답이 `yes`일 때 결함이다. 아래 답은 모두 `no`이므로 결함 없음이다.

| id | 질문 | 답 | 결함 |
| --- | --- | --- | --- |
| `antigravity_claude_regression` | 기존 Antigravity Claude 항목의 probe 경로나 provider 판정이 바뀌어 회귀가 생겼는가 | no | 없음 |
| `provider_family_semantics` | `provider_for_model`이 `claude-sonnet`과 `claude-sonnet-5`를 모두 `claude` 패밀리로 판정하지 못하게 되었는가 | no | 없음 |
| `effort_fail_closed` | model 없이 effort만 지정한 dispatch 호출이 거부되지 않고 통과하는가 | no | 없음 |
| `gemini_tier_policy_unchanged` | `TIER_POLICY`의 Gemini 자동 배정 값이 변경되었거나 `claude-sonnet`이 자동 fallback 목록에 추가되었는가 | no | 없음 |
| `scope_overreach` | 허용 범위 밖 파일을 수정했는가 | no | 없음 |

근거는 2장의 해당 항목과 같다. 추가 코드 위치는 다음과 같다.

- 패밀리 접두사: `scripts/orca_model_router.py:1042` (`("claude", "claude")`), 테스트 `tests/test_orca_model_router.py:1947-1948`
- 풀 키와 id: `scripts/orca_model_router.py:367-370`

---

## 4. 최종 verdict

**approved**

차단 이슈 없음. 병합 판정은 코디네이터 몫이다.

---

## 5. 잔여 관찰: `--terminal` 경로에서 effort 무시

`scripts/orca_taskctl.py:4068-4154`의 터미널 부착 경로와 `:3997-4003`의 런처 경로는 `worker_start`를 호출하지 않는다. `--model`과 `--effort`가 함께 있어도 이 경로에서는 effort가 전달되지 않고 조용히 무시된다.

공식 `worker-start` 계약은 `--effort`를 `--terminal`과 같이 쓰지 못하므로, worker_start 경로에 `--effort`를 붙이고 model 없는 effort를 fail-closed로 막는 이번 요구사항은 충족한다. fail-closed는 model 없는 effort에만 있고, `--effort`와 `--terminal` 조합은 거부하지 않는다.

이 조합을 다루는 회귀 테스트는 없다. 필수 범위는 아니다.

---

## 6. 기타 관찰 (비차단)

`MODEL_POOL['claude-sonnet']`의 `auto_selectable`은 부모에서도 `True`였고 이번에도 `True`다 (`scripts/orca_model_router.py:372`). 실제 자동 배정은 `TIER_POLICY`만 쓰므로 동작 회귀는 없다. 문서와 notes는 수동 보조 워커라고 적는다.

빌더가 보고한 pytest 353 passed와 live probe 성공은 이 검토 워크트리에서 재실행하지 않았다. 대상 브랜치 체크아웃이 금지되어 있었다. 단위 테스트 충족은 커밋에 포함된 테스트 코드와 코디네이터 ground_truth(Level 1 통과)로만 인정한다.

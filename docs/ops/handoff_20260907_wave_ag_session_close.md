# 인수인계: 20260907 Wave AG 세션 종료

> **작성일**: 2026-09-07
> **Run**: `run_71d230fcb319` 종료 후 신규 `run_0ba65879eff5`
> **기준 커밋**: `49cea48` -> `a9b66d6` (커밋 8개)
> **미병합 브랜치**: 없음
> **인수 대상**: 다음 코디네이터
> **선행 문서**: [`handoff_20260906_wave_ae_af_session_close.md`](handoff_20260906_wave_ae_af_session_close.md)

---

## 1. 한 줄 요약

**선행 인수인계 7.1절이 남긴 도구 결함 세 건을 전부 닫았습니다.** 이번에도 제품
기능이 아니라 조율 도구 자체만 다뤘습니다. 코디네이터는 Claude Opus 5 단독이며
빌더 2대를 병렬로 운용했습니다.

---

## 2. 닫은 항목

| Wave | 내용 | 작업 커밋 | 병합 |
| --- | --- | --- | --- |
| AG1 | 런처 경로 Dispatch 가 preamble 을 쓰기 전에 터미널의 런처 대기 표지를 검사 | `cc0625b` | `8b0011a` |
| AG2 | Capsule `forbidden` 표준 항목에 패키지 관리자 교체 금지 추가 | `db8e27b` | `a9b66d6` |
| AG3 | 리뷰어 읽기 범위(`search_scope`) 사후 감사 도구 신설 | `fcd5973` | `c9277be` |
| 부수 | Antigravity `claude-sonnet-4-6` 을 워커 풀에 등록 | `a46d8f8` | `a7dd411` |

AG1 과 AG3 은 **빌더 1대 + 리뷰어 1대** 구성이며 리뷰 판정은 둘 다 `pass`,
blocking_issues 0건입니다. Level 1 게이트는 두 건 모두 `--strict` 에서 8/8
PASS 입니다. AG2 는 템플릿 한 줄 추가라 위임하지 않고 코디네이터가 직접
처리했습니다(스킬 3.1절의 위임 손익 기준).

`main` 최종 검증은 pytest **3,778 passed / 32 skipped / 실패 0**,
`validate_agent_rules` 20/20 입니다.

---

## 3. 선행 인수인계의 후속 과제가 어떻게 닫혔는지

| 선행 7.1 항목 | 이번 결과 |
| --- | --- |
| 런처 경로 Dispatch 가 터미널의 실행 명령을 먼저 검사 | AG1 로 닫힘 (`cc0625b`) |
| Capsule `forbidden` 표준 항목에 패키지 관리자 교체 금지 | AG2 로 닫힘 (`db8e27b`) |
| 리뷰어 `search_scope` 위반을 사후 감사로 검출 | AG3 로 닫힘 (`fcd5973`) |
| baseline 생성 (필요해질 때) | 미착수, 필요 시점 아님 |
| R-10 2단계 Prometheus | 미착수, 계측 선행 필요 |

**두 세션 연속으로 후속 과제 표가 그대로 소비되었습니다.** 이 형식을 유지하십시오.

---

## 4. AG1 은 "실행 명령 검사" 가 아니라 "대기 표지 검사" 로 구현했습니다

선행 문서는 "터미널의 실행 명령을 먼저 검사" 로 적었지만 **그 경로는 존재하지
않습니다.** `orca terminal list --json` 과 `terminal show --json` 은 실행 명령이나
argv 를 돌려주지 않습니다. 반환 필드는 `handle`, `ptyId`, `worktreePath`,
`branch`, `tabId`, `title`, `preview`, `agentIdentity` 계열뿐입니다.

그래서 판정 근거를 **화면 버퍼의 표지**로 바꿨습니다. preamble 대기형 런처 세
개가 모두 같은 문자열을 찍습니다.

    preamble 대기 중: .orca/preamble.txt (최대 300초)

`scripts/orca_agy_launch.py:215`, `scripts/orca_qwen_launch.py:166`,
`scripts/orca_kimi_launch.py:172` 입니다. `scripts/orca_codex_launch.py` 는
preamble 대기 구조가 아니라 이 표지를 찍지 않으며, `--launcher` 로 지정하면
거부되는 것이 의도된 동작입니다.

검사는 20초 폴링이고, 표지를 못 보거나 화면을 아예 읽지 못하면 **preamble 을
쓰지 않고** 종료 코드 2 로 거부합니다(`launcher_terminal_not_waiting`). 우회는
`--allow-unready-launcher` 뿐이며 기본값은 거부입니다.

**사양을 증상에서 역추론해 못박으면 워커가 없는 API 를 찾습니다.** 이번에는
Dispatch 전에 코디네이터가 직접 `terminal list --json` 을 호출해 필드를 확인하고
ground_truth 를 고쳤습니다.

---

## 5. AG3 도구의 한계를 알고 쓰십시오

`scripts/orca_read_scope_audit.py` 는 **워커 터미널의 화면 버퍼**에서 경로
토큰을 뽑아 Capsule 의 `allowed_read_files` 및 `search_scope.allowed_globs` 와
대조합니다.

```bash
python3 scripts/orca_read_scope_audit.py --terminal <handle> --capsule <경로> --repo <워크트리>
```

종료 코드는 0 위반 없음, 1 위반 발견, 2 도구 오류입니다. 버퍼나 Capsule 을 읽지
못하면 2 이며 **위반 없음으로 처리하지 않습니다.**

**위반 없음은 위반이 없었다는 증명이 아닙니다.** 화면 버퍼는 잘리고 밀려나므로
증거가 남은 범위에서만 유효합니다. 그래서 이번 범위에서는 Level 1 게이트나
pre-commit 훅에 **연결하지 않았습니다.** 게이트로 승격하려면 버퍼 유실을
보정할 근거가 먼저 필요합니다.

---

## 6. 이번 세션에서 걸린 도구 결함

### 6.1 `taskctl dispatch --intent` 만으로는 Task 가 만들어지지 않습니다

`dispatch --intent <파일>` 을 바로 부르면 Intent 파일명에서 task_id 를 유추하다
`Task not found` 로 끝납니다. **`create` 로 Task 를 먼저 만들고 그 출력의
`task_id` 와 `capsule` 을 `--task-id`, `--capsule` 로 넘겨야** 합니다. 이 사실은
[`agent_worker_launch_reference.md`](agent_worker_launch_reference.md) 2절에
적혀 있으나 명령 예시에는 빠져 있어 첫 시도가 실패했습니다.

### 6.2 명시 모델은 MODEL_POOL 에 없으면 거부됩니다

Grok 풀 주간 한도 소진으로 리뷰어를 Antigravity Claude 계열로 돌렸는데
`claude-sonnet-4-6` 이 `scripts/orca_model_router.py` 의 `MODEL_POOL` 에 없어
Dispatch 가 `ModelRoutingError` 로 거부됐습니다. **터미널은 그 모델로 이미
정상 기동한 뒤였습니다.** 라우터 등록과 실제 CLI 가용성은 별개입니다.
`claude-sonnet-thinking` 풀로 등록했습니다(`a46d8f8`).

### 6.3 상시 감시기가 부팅 텍스트를 승인 대기로 오판했습니다

`orca_worker_watch.py` 가 AG3 빌더를 `[차단:승인 대기] Antigravity 부팅이 인증
단계에서 정체` 로 표시했으나, 터미널 실측 결과 워커는 정상적으로 Capsule 을
읽는 중이었습니다. **차단 신호가 뜨면 터미널을 직접 확인하십시오.** 도구도
그렇게 안내합니다.

### 6.4 전량 테스트 증거는 병합 대상 커밋에서 만들어야 합니다

선행 6.2절과 같은 지점에 다시 걸렸습니다. `premerge-full-suite-gate` 는 증거의
`commit` 이 `MERGE_HEAD` 와 일치할 것을 요구하므로 **워커 워크트리를 제거하기
전에 거기서** `python3 scripts/premerge_full_suite_gate.py --record` 를 돌려야
합니다. 이번에는 순서를 지켜 세 번 모두 한 번에 통과했습니다.

---

## 7. 남은 항목

| ID | 내용 | 선행 조건 |
| --- | --- | --- |
| **R-12** | G2 Windows Docker Desktop 실기 | Windows 장비. `worker-start --on <saved-environment>` 원격 워커 경로가 열려 있다 |
| **R-13 정본 측정** | canonical 게이트 충족 측정 | HTTP 실패 0, trace 대조 전량, 문항·회차 정본 기준 충족. 저장소 동결 필요 |

### 7.1 후속 과제 (이 세션이 만든 것)

| 출처 | 내용 |
| --- | --- |
| 4장 | `--launcher` 에 codex 런처를 지정하면 표지 부재로 거부된다. codex 를 런처 경로로 쓸 일이 생기면 런처에 대기 표지를 추가하는 편이 검사를 느슨하게 만드는 것보다 낫다 |
| 5장 | `orca_read_scope_audit.py` 를 `worker_done` ack 절차에 편입할지 판단. 편입하려면 버퍼 유실 보정 근거가 먼저 필요하다 |
| 6.1 | `agent_worker_launch_reference.md` 2절 명령 예시에 `create` -> `dispatch --task-id --capsule` 순서를 명시 |
| 6.3 | `orca_worker_watch.py` 의 승인 대기 판정이 부팅 텍스트를 오판하는 조건 축소 |
| 선행 4.2 | baseline 생성 (필요해질 때) |
| 선행 R-10 | 메트릭 계측 후 Prometheus 추가 (2단계) |

---

## 8. 정리 상태

**모든 자원을 회수했습니다.** 빌더 2대는 `worker_done` 확인 직후, 리뷰어 2대는
판정 확인 직후 회수했습니다. `worker-release` 는 비감독 경로(`--terminal`)라 네
건 모두 `no_owned_resource` 또는 `retained` 로 돌아왔고 `orca terminal close
--terminal` 로 창 단위 종료했습니다(`--tab` 미사용). 닫기 전에 `tabId` 가
코디네이터와 다른지 매번 확인했습니다.

워크트리 `wave-ag1`, `wave-ag3` 은 `main` 병합 확인 후 제거했고 브랜치는
`git branch -d` 로 삭제했습니다. `-D` 강제는 쓰지 않았습니다.
`orca_settled_session_audit.py` 는 잔류 없음, `git worktree list` 는 주 저장소
한 줄, Run `run_0ba65879eff5` 의 Task 4건은 전부 `completed` 입니다.

**원격 푸시는 하지 않았습니다.** `main` 이 `origin/main` 보다 8커밋 앞서 있습니다.

**Docker 는 선행 세션이 띄운 dev compose 스택이 그대로 떠 있습니다.** 이번
세션도 컨테이너를 건드리지 않았습니다.

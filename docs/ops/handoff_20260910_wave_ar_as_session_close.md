# 인수인계: 20260910 Wave AR·AS 세션 종료

> **작성일**: 2026-09-10
> **Run**: `run_1ec113af3fc0` (Wave AR, 인수), `run_c14f5b87912c` (Wave AS)
> **기준 커밋**: `2d6b21d` -> `ba15eaa` (4 커밋)
> **인수 대상**: 다음 코디네이터
> **선행 문서**: [`handoff_20260910_wave_aq_ng_session_close.md`](handoff_20260910_wave_aq_ng_session_close.md)

---

## 0. 다음 세션 첫 작업

**워크트리를 만들 때 반드시 `--setup skip` 을 붙이십시오.** 이것을 빠뜨리면
그 Task 의 Level 1 게이트가 막힙니다. 이유는 4장에 있습니다.

기능 작업으로는 기술용역 적격심사가 판별·표본·화면까지 닫혔습니다. 남은 것은
협상에의한계약의 가격점수인데, 계수 `k` 와 통과점수 `T` 의 원천이 공고 데이터에
없어 **새 정보 수집 없이는 진행 불가**입니다. 추측해 넣지 마십시오.

G2 Windows 실기 검증은 장비 부재로 보류 유지입니다.

---

## 1. 이 세션이 한 일

Grok 코디네이터에게서 Wave AR 병합 직후 상태를 인수해, 정리와 화면 후속을
마치고 그 과정에서 드러난 도구 결함까지 닫았습니다.

| 커밋 | 내용 |
| --- | --- |
| `a092adf` | 기술용역 적격심사 화면 표시 (Wave AS1) |
| `ba15eaa` | 금지 패키지 산출물 게이트 (Wave AS2·AS3·AS4) |

병합 후 main 전량 테스트 **4,303 passed**, 규칙 검증 21/21 입니다.

---

## 2. AS1 기술용역 화면 (완료)

### 2.1 발견한 기존 결함

배지 작업을 준비하다 **차단 사유 문구 사전이 통째로 죽어 있는 것**을 소스로
확인했습니다.

- `src/app/api/v1/evaluations.py:374`, `:474` 가 `blocked_reason` 을
  `"코드: 한국어메시지"` 형태로 만듭니다. 순수 코드로 넣는 경로는 없습니다.
- `src/app/templates/bids/detail.html` 이 그 합쳐진 문자열을 통째로
  `getBlockedReasonText` 에 넘깁니다.
- 사전은 키가 순수 코드라 **어떤 값에도 매칭되지 않았습니다.**

즉 `TECH_SERVICE_MISSING_LWLT` 를 사전에 추가하기만 해서는 아무 효과가 없었습니다.

### 2.2 반영한 것

- 코드 접두 분리(`/^([A-Z][A-Z_]*)\s*:/`). 사전에 있으면 사전 문구를, 없으면
  서버가 보낸 한국어 메시지를 씁니다. `BLOCK_CODE` 상수 8종이 전부 걸리는 것을
  코디네이터가 열거해 확인했습니다.
- 사전에 `TECH_SERVICE_MISSING_LWLT` 추가.
- `setEvaluationScopeBadge(data)` 신설. 일반용역·기술용역·협상 세 상태를 응답마다
  다시 설정합니다. 종전에는 협상 경로만 덮어써서 공고를 옮기면 협상 문구가
  남았습니다.

### 2.3 남은 비차단 사항

- ajax 오류 경로에서는 배지가 갱신되지 않습니다. 카드 내용도 갱신되지 않으므로
  일관적이고 무해합니다.
- 새 테스트가 정규식 리터럴을 문자열로 고정합니다. 동등한 리팩터링에 깨질 수
  있으나 이 저장소 UI 테스트의 기존 방식입니다.

---

## 3. AS2·AS3·AS4 금지 패키지 산출물 게이트 (완료)

한 브랜치에 세 커밋이 쌓였습니다. 리뷰 반려가 한 번, 코디네이터 검증에서
발견한 병합 차단 결함이 한 번 있었습니다.

| 커밋 | 내용 |
| --- | --- |
| `0efa12a` | 게이트 9 추가, 감시기 경고 |
| `5d13545` | 감시기 전체 순회를 `git status` 재사용으로, 정의 단일화 |
| `89727aa` | 직접 실행 `import` 복구 |

### 3.1 게이트 9 판정 기준 (코디네이터가 정함)

| 항목 | 기준 |
| --- | --- |
| 금지 | `pnpm-lock.yaml`, `pnpm-workspace.yaml`, `yarn.lock`, `bun.lockb` |
| 허용 | 루트와 `frontend/` 의 `package-lock.json` (`.gitignore:222` 가 정본으로 명시) |
| 제외 | `node_modules/` 아래 |
| 검출 | **커밋 여부와 무관하게 작업 트리 존재만으로** |

종전 게이트 7 은 커밋된 변경만 보므로 untracked 부산물을 놓쳤습니다. 실제로 두
사건 모두 untracked 였습니다. 11GB 주 저장소에서 1.45초입니다.

`.gitignore` 추가는 기각했습니다. 무시하면 위반이 조용히 숨고 워크트리에 계속
남아 `worktree rm` 을 막습니다.

### 3.2 리뷰가 잡은 것

첫 리뷰가 `fail` 판정했고 코디네이터가 재현했습니다.

- 감시기가 워크트리마다 전체 순회를 돌고 감시 주기는 10초입니다. **워크트리 1개당
  0.439초, 3개면 10초 주기의 13% 상시 점유**였습니다. `collect()` 가 이미 실행한
  `git status` 의 untracked 목록을 재사용하도록 고쳤습니다.
- 상수와 함수가 두 파일에 두 벌이었습니다. `scripts/orca_forbidden_artifacts.py`
  단일 원천으로 합쳤습니다.

감시기는 `git status` 를 쓰므로 **gitignore 대상을 놓칩니다.** 의도된 절충이며
docstring 에 적혀 있습니다. 병합을 막는 정본 판정은 게이트 9 이고 그쪽은 파일
시스템을 직접 봅니다.

### 3.3 코디네이터가 잡은 병합 차단 결함

`5d13545` 가 공유 모듈 `import` 를 fallback 없이 최상단에 넣어 이렇게 되었습니다.

```
$ python3 scripts/orca_worker_watch.py
ModuleNotFoundError: No module named 'scripts'
```

이 형태는 `AGENTS.md:99` 와 `SKILL.md:323-325` 가 지정한 정본 호출이고,
`scripts/orca_taskctl.py:2003` 이 상시 감시기를 `sys.executable` + 절대 경로로
띄우는 형태이기도 합니다. **병합했다면 워커 감시 체계가 무력화되었을 것입니다.**
`taskctl` 은 배경 기동 후 PID 를 기록하므로 즉시 죽어도 "기동 성공"으로
보고합니다.

**전량 테스트 4,293건이 통과했습니다.** pytest 가 저장소 루트를 `sys.path` 에
넣기 때문입니다. `89727aa` 가 `orca_level1_gate.py:25-52` 의
`try/except ModuleNotFoundError` 패턴으로 고쳤고, **실제 프로세스를 비저장소 cwd 에서
띄우는 회귀 테스트**를 추가했습니다.

> **교훈**: 스크립트로 직접 실행되는 도구는 pytest 통과만으로 검증되지 않습니다.
> 그런 도구를 고치는 Task 의 acceptance 에는 반드시 직접 실행을 넣으십시오.

### 3.4 후속으로 남긴 비차단 사항

- 감시기의 `git status --short` 파싱이 `core.quotePath` 로 따옴표가 감싸지는
  비ASCII 경로에서 어긋날 수 있습니다. 금지 산출물 4종은 전부 ASCII 이름이고
  저장소 경로도 ASCII 라 실질 위험은 낮습니다.

---

## 4. 워크트리 setup 의 pnpm 오염 (원인 확정, 절차로 회피)

**이것이 다음 세션에 가장 중요한 항목입니다.**

### 4.1 원인

`pnpm-lock.yaml` 을 만드는 것은 워커가 아니라 **Orca 프로젝트 setup 스크립트**입니다.

```
orca project setups -> hookSettings.scripts.setup = "pnpm install"
```

워크트리를 만들 때마다 실행되어 `pnpm-lock.yaml` 과 `node_modules` 를 만듭니다.
이 세션에서 워크트리를 만든 직후(워커 기동 전) 파일이 존재하는 것을 확인해
확정했습니다.

> **2026-09-06 인수인계 6.3 절의 "AF2 빌더가 만들었다" 는 오인일 가능성이 높습니다.**
> 이 세션에서도 시각 일치를 근거로 같은 오인을 한 번 했습니다.

### 4.2 CLI 로 고칠 수 없습니다

`orca project setup-update` 의 `--setup` 은 **대상 setup-id 이지 정책이 아닙니다**
(`--setup skip` 을 주면 `Project host setup not found: skip`). 도움말의
`--setup run|skip|inherit` 설명은 잘못 붙어 있습니다. `setup-create`,
`setup-existing-folder` 에도 스크립트를 바꾸는 옵션이 없습니다.
`commandSourcePolicy` 가 `local-only` 라 저장소 `orca.yaml` 정의도 무시될
가능성이 높습니다.

영속 변경은 **Orca 앱 UI 에서만** 가능합니다. 루트 `package-lock.json` 이 Git
추적 중이라 `npm ci` 로 바꾸면 바로 동작합니다.

### 4.3 회피 절차 (실측 확인)

```bash
orca worktree create --name <이름> --setup skip --json
```

검증용 워크트리로 확인했습니다. `pnpm-lock.yaml` 도 `node_modules` 도 생기지
않고, `git status` 가 완전히 깨끗하며, `worktree rm` 이 곧바로 성공합니다.

**빠뜨리면 게이트 9 가 그 Task 의 Level 1 을 막습니다.** 파일을 지우면 회복되므로
치명적이지는 않지만, 워커의 `worker_done` 에 blocking issue 로 올라와 verdict 가
`blocked` 로 격하됩니다. 이 세션에서 실제로 그렇게 됐습니다.

---

## 5. 도구 계약에서 새로 걸린 것

기동에 세 번 실패한 뒤 성공했습니다. 전부 코디네이터의 도구 사용 결함입니다.

| 함정 | 대응 |
| --- | --- |
| `taskctl dispatch --intent` 는 Orca Task 를 만들지 않는다 (`task_not_found`) | `create` 를 먼저 돌려 실제 `task_...` id 를 받는다 |
| `create` 를 반복하면 미사용 Task 가 `ready` 로 쌓인다 | `task-update --status failed` 에 사유를 적어 닫는다 (`cancelled` 상태는 없다) |
| 기존 워크트리 재사용 시 `--repo` 가 붙으면 거부 (`Creation and setup options apply only to new-child...`) | `--repo ""` 로 플래그를 생략시킨다. `worker-start` 직접 호출은 감시기 부착이 빠지므로 쓰지 않는다 |
| 새 워크트리에 Capsule 이 자동 복사되지 않는다 | 기동 전에 복사한다. 안 하면 워커가 1분 안에 `failed` 로 종결한다 |
| 새 워크트리 기준 커밋이 세션 시작 커밋 (이번엔 36커밋 뒤처짐) | 만든 직후 `rev-list --count HEAD..main` 확인, `reset --hard main` |
| OpenCode 리뷰어는 빈 터미널에 `--launcher` 불가 (`launcher_terminal_not_waiting`) | `terminal create --command 'uv run python scripts/orca_opencode_launch.py --model ...'` 로 런처와 함께 만든다 |
| 비감독 경로라 `worker-release` 가 `no_owned_resource` 로 `retained` | `orca terminal close --terminal <handle>` 로 직접 닫는다 (`--tab` 금지) |
| 새 게이트를 자기 자신으로 검증하려면 워크트리 스크립트를 써야 한다 | 주 저장소 스크립트로 돌리면 새 게이트가 빠진다. 이 세션에서 한 번 놓쳤다 |

### 5.1 한 브랜치에 여러 Task 커밋이 쌓이면 게이트 2·6 이 오탐한다

`ba15eaa` 병합 직전 Level 1 이 `exit 1` 이었고, 게이트 2(범위)와 6(worker_done
changed_files)이 실패했습니다. **둘 다 오탐입니다.** 브랜치 전체 diff(4파일)를
**마지막 Capsule 하나**(AS4, 2파일 허용)로 재기 때문입니다.

커밋별로 각 Capsule 과 대조해 판정했고 셋 다 초과 0건이었습니다.

```
0efa12a (AS2) 3파일 / 허용 3파일 -> 초과 없음
5d13545 (AS3) 4파일 / 허용 4파일 -> 초과 없음
89727aa (AS4) 2파일 / 허용 2파일 -> 초과 없음
```

**같은 상황에서는 커밋별 대조로 판정하십시오.** 게이트 출력만 보고 반려하면
정상 산출물을 되돌리게 됩니다.

---

## 6. 자원 정리 상태

**전부 회수했습니다.**

- 워크트리: 주 저장소 하나. `orca-ar1`, `orca-ar2`, `orca-as1`, `orca-as2` 및
  검증용 probe 전부 제거
- 브랜치: `main` 하나. 전부 `git log --oneline main..<branch>` 공집합 확인 후
  `orca worktree rm` 의 병합 증명 기반 삭제 (`-D` 미사용)
- 터미널: 코디네이터 창만 남음. 빌더는 `worker-release`, OpenCode 리뷰어는
  `terminal close` 로 회수
- `orca_settled_session_audit.py` 잔류 없음, reclaimable 0
- 워커·리뷰 보고서는 주 저장소 `.orca/capsules/<task_id>/` 에 복사 보존

Docker 스택은 주 저장소에서 `make up` 한 상태이며, `docker inspect` 로 app·worker
컨테이너가 주 저장소 경로(`src`, `data`, `chroma_db`, `ml_registry`)만 bind mount
하는 것을 제거 전마다 확인했습니다.

### 6.1 Task 종결 상태 (`run_c14f5b87912c`)

| Task | 상태 | 비고 |
| --- | --- | --- |
| `task_5a1fedfa1031` | failed | Capsule 미배치로 기동 실패. 이력 보존 |
| `task_d601a49d3675` | failed | 재시도 중 생긴 중복. 사유 기록 후 종결 |
| `task_cd14c9e2a8fe` | completed | AS1 빌더 |
| `task_863144ab8dc8` | completed | AS1 리뷰 (pass) |
| `task_4869fb81dd28` | completed | AS2 빌더 |
| `task_260795e62e04` | completed | AS2 리뷰 (**fail** — 반려) |
| `task_23dfc8492060` | completed | AS3 반려 대응 |
| `task_b953cabf430f` | completed | AS4 import 수정 |
| `task_b399b0f1292f` | completed | 브랜치 최종 리뷰 (pass) |

반려 대상 Task 를 `failed` 로 되돌리지 않았습니다. 워커는 지시대로 했고 결함은
코디네이터의 기준 제정 누락에서 왔으므로, 새 Task 로 이어 쌓는 편이 이력이
정확합니다.

---

## 7. 남은 항목

| ID | 내용 | 선행 조건 |
| --- | --- | --- |
| **R-12** | G2 Windows Docker Desktop 실기 | Windows 장비. `worker-start --on <saved-environment>` 원격 워커 경로가 열려 있습니다 |
| **R-14** | 원격 푸시 | 사용자 확인. 현재 `origin/main` 대비 **ahead 40** |
| **R-15** | Orca setup 스크립트를 `npm ci` 로 영속 변경 | Orca 앱 UI. CLI 불가 (4.2 절) |
| **R-16** | 감시기 `git status` 따옴표 경로 파싱 | 비차단. 실질 위험 낮음 (3.4 절) |
| **R-17** | 협상 가격점수 | **차단**. `k` 와 `T` 의 원천이 공고 데이터에 없습니다. 새 정보 수집 필요 |

### 7.1 하지 말아야 할 것

- 기술용역의 `B`, `k`, `T` 를 하드코딩하거나 일반용역 공통 배점표로 환원하지
  마십시오. 2026-09-09 에 반려된 이력이 있습니다.
- 협상 가격점수 산식을 추측해 넣지 마십시오. `sucsfbidMthdAppStd` 가 전부 빈
  문자열이고 `bid_results` 에 낙찰자 한 명만 있어 사후 재현도 불가능합니다.
- `.gitignore` 에 금지 lockfile 을 추가하지 마십시오. 위반이 조용히 숨습니다.

---

## 8. 모델 배정

사용자 지정으로 빌더 `gpt-5.6-luna`(codex, effort medium), 리뷰어
`opencode/muse-spark-1.3-contributor-free` 를 이 웨이브 전체에 썼습니다.
리뷰어 Capsule 에는 `builder_provider: codex` 와 `builder_model: gpt-5.6-luna` 를
넣어야 독립성 검사를 통과합니다.

리뷰어 판정 품질은 좋았습니다. AS2 리뷰가 잡은 감시기 비용 문제는 코디네이터가
실측으로 재현했고 수치까지 맞았습니다. 다만 **직접 실행 결함은 리뷰어도 놓쳤습니다.**
코드 읽기만으로는 잡히지 않는 종류였고, 코디네이터가 실행해 발견했습니다.

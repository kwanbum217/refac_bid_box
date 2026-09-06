# 인수인계: 20260906 Wave AE~AF 세션 종료

> **작성일**: 2026-09-06
> **Run**: `run_71d230fcb319` (Wave AE, AF 를 같은 Run 에서 진행)
> **기준 커밋**: `5381d83` -> `7ac9e64` (커밋 10개)
> **미병합 브랜치**: 없음
> **인수 대상**: 다음 코디네이터
> **선행 문서**: [`handoff_20260906_wave_aa_ad_session_close.md`](handoff_20260906_wave_aa_ad_session_close.md)

---

## 1. 한 줄 요약

**선행 인수인계 7.1절이 남긴 후속 과제 네 건을 전부 닫고, 그 과정에서 새로
드러난 OpenCode 도달 확인 결함 한 건을 추가로 닫았습니다.** 이번 세션은 제품
기능이 아니라 **조율 도구 자체의 결함**만 다뤘습니다. 코디네이터는 Grok 이
시작해 토큰 소진으로 중단했고 Claude Opus 5 가 AF2 리뷰 Dispatch 지점부터
이어받아 종료했습니다.

---

## 2. 닫은 항목

| Wave | 내용 | 작업 커밋 | 병합 |
| --- | --- | --- | --- |
| AE | worker_done 의 dispatch capability 자동 해소 | `63c75bf` | `dfa5e34` |
| AE | 게이트 3 docker 검증에 `-f <파일>` 형태 허용 | `d87c444` | `5493c92` |
| AE | SSR 인증 E2E 고정 대기를 조건 대기로 전환 | `94d5d60` | `2c53592` |
| AF1 | 게이트 3 pytest 실패 노드 단독 재시도 | `e486892` | `7e4cb70` |
| AF2 | OpenCode 워커 지시 도달 확인을 우회 없이 성공 | `2a6400f` | `7ac9e64` |

다섯 건 모두 **빌더 1대 + 리뷰어 1대** 구성이며 리뷰 판정은 전부 `pass`,
blocking_issues 0건입니다. Level 1 게이트는 다섯 건 모두 `--strict` 에서 8/8
PASS 입니다.

`main` 최종 검증은 pytest **3,774 passed / 23 skipped / 실패 0**,
`validate_agent_rules` 20/20, ruff 통과입니다.

---

## 3. 선행 인수인계의 후속 과제가 어떻게 닫혔는지

선행 문서 7.1절 표와의 대응입니다. **후속 과제로 적어 둔 것이 실제로 다음
세션에서 소비되었습니다.** 이 형식은 유지할 가치가 있습니다.

| 선행 7.1 항목 | 이번 결과 |
| --- | --- |
| `orca_worker_done_guard.py` 가 preamble 에서 capability 자동 해소 | AE 로 닫힘 (`63c75bf`) |
| 게이트 실패 시 단독 자동 재시도 | AF1 로 닫힘 (`e486892`) |
| `tests/e2e/test_ssr_auth.py` 계열 결정화 | AE 로 닫힘 (`94d5d60`) |
| 게이트 3 docker 허용 목록에 `-f` 형태 추가 | AE 로 닫힘 (`d87c444`) |
| baseline 생성 (필요해질 때) | 미착수, 필요 시점 아님 |
| R-10 2단계 Prometheus | 미착수, 계측 선행 필요 |

---

## 4. AF2 는 이번 세션이 스스로 만든 과제입니다

AE 를 진행하면서 **Muse Spark(OpenCode) 워커를 Dispatch 할 때마다 사후 도달
확인이 `not_observed` 로 끝나** 코디네이터가 `--allow-unverified-delivery` 로
우회하는 관행이 생겼습니다. Wave U/V/AE 에 걸쳐 반복된 우회였습니다.

원인은 세 가지가 겹친 것이었습니다.

| # | 원인 |
| --- | --- |
| 1 | 사후 확인이 뷰포트(`terminal_tail`)만 보고 전체 버퍼(`terminal_read`)를 보지 않음 |
| 2 | OpenCode TUI 의 색상·커서 ANSI 코드가 표지 문자열 사이에 끼어 포함 검사가 빗나감 |
| 3 | 긴 고지문이 뷰포트 너비에서 잘리거나 개행되어 probe 중간이 끊김 |

시정은 ANSI 제거 후 비교, 실패 시 공백 제거 재비교, `terminal_read` 전체 버퍼
fallback, 고지문 뒤 짧은 `전달 확인 표지: <probe>` 확인문 추가 전송입니다.
**fail-closed 는 그대로입니다.** 표지가 정말 안 보이면 우회 플래그 없이 종료
코드 3 이며 `--allow-unverified-delivery` 기본값도 그대로입니다.

**이제 도달이 화면에 보이는데 플래그가 필요하면 그것은 이 시정의 결함입니다.**
그 경우 우회하지 말고 결함으로 보고하십시오.

---

## 5. 코디네이터 인수 경위와 그때 확인한 것

Grok 코디네이터가 AF2 리뷰 Capsule 작성과 리뷰 터미널 생성까지 마치고 토큰
소진으로 멈췄습니다. 인수 시점 상태는 AF2 빌더 산출물 `2a6400f` 가 미병합,
리뷰 Task `task_dd56b545815e` 가 `ready` 였습니다.

**인수할 때 먼저 확인한 것**은 다음 다섯 가지입니다. 다음 인수자도 같은
순서를 쓰십시오.

1. `git worktree list` 와 `git branch` 로 미병합 브랜치와 살아 있는 트리
2. `orca orchestration task-list` 로 Run 의 Task 상태 (어디서 끊겼는지)
3. `orca_settled_session_audit.py` 로 완료 세션 잔류
4. 리뷰 Capsule 의 `task_id` 가 디렉터리 이름과 일치하는지 (게이트 5 실패 원인)
5. `docs/context/CURRENT_STATE.md` 의 `source_commit` 뒤처짐

5번이 실제로 걸렸습니다. `54b3f4c` 로 **22커밋 뒤처져** 있었고 허용치는 5입니다.
규약대로 병합 커밋 안에서 `7e4cb70` 으로 함께 갱신했습니다.

---

## 6. 도구 결함과 코디네이터 과실

### 6.1 런처는 터미널을 만들 때 명령으로 지정해야 한다

**AF2 리뷰 Dispatch 첫 시도가 `launcher_pickup_timeout` 으로 실패했습니다.**
원인은 리뷰 터미널이 **런처를 명령으로 지정하지 않은 빈 셸**이었기 때문입니다.

`orca_agy_launch.py` 는 preamble 파일이 나타날 때까지 기다렸다가 `agy` 를
exec 하는 구조입니다. 터미널이 그냥 셸이면 preamble 을 써도 이어받을 주체가
없습니다. `--launcher` 는 preamble 을 쓰고 기동을 확인만 합니다.

```bash
orca terminal create --worktree path:<워크트리> --title "<섹션명>" \
  --command "uv run python scripts/orca_agy_launch.py --model <모델>"
```

이번에는 이미 만들어진 셸 터미널에 런처 명령을 손으로 보내 남아 있던 고유
preamble 을 소비시켰습니다. **이 마무리는 비감독 경로였습니다.** 그래서
`worker-release` 가 `no_owned_resource` 로 돌아왔고 `terminal close` 로 창
단위 종료했습니다.

### 6.2 전량 테스트 증거는 병합 대상 커밋에서 만들어야 한다

`premerge-full-suite-gate` 는 `.cache/premerge_full_suite_evidence.json` 의
`commit` 이 `MERGE_HEAD` 와 일치할 것을 요구합니다. 주 저장소에서 병합 트리를
전량 통과시킨 것으로는 통과하지 않습니다. **워커 워크트리에서 그 브랜치 HEAD
기준으로 `--record` 를 돌려야 합니다.**

```bash
cd <워커 워크트리> && python3 scripts/premerge_full_suite_gate.py --record
```

이때 격리 트리 예외(`test_model_bin_files_exist`, `test_chroma_db_exists`)를
걱정할 필요가 없습니다. **정본 명령이 `-m "not data_assets"` 로 그 두 건을
애초에 제외합니다.** 이번 세션은 이것을 모르고 gitignore 산출물을 심볼릭
링크로 붙였다가 불필요함을 확인하고 되돌렸습니다.

### 6.3 워커가 범위 밖 부산물을 남겼다

AF2 빌더가 워크트리 루트에 `pnpm-lock.yaml`(18KB)을 만들었습니다. 이 저장소는
npm 을 쓰고 게이트도 `npm ci` 를 봅니다. 커밋에는 포함되지 않아 산출물 영향은
없었고 워크트리 제거 시 함께 삭제했습니다. **Capsule 의 `forbidden` 에 패키지
관리자 교체 금지를 적어 두는 것이 좋습니다.**

### 6.4 리뷰어가 범위 밖 파일을 읽었다

AF2 리뷰어(Gemini)가 `find /Users/kwanbum -maxdepth 3` 으로 워크트리 밖을
훑고 다른 Task 의 `review_done.json` 을 읽었습니다. 읽기 전용 워커라
산출물 오염은 없었지만 `search_scope` 의 `deny_by_default` 가 기계로
강제되지 않는다는 뜻입니다. 판정 근거는 정상적으로 지정 파일과 줄 번호를
가리켰으므로 이번 판정 자체는 유효합니다.

---

## 7. 남은 항목

| ID | 내용 | 선행 조건 |
| --- | --- | --- |
| **R-12** | G2 Windows Docker Desktop 실기 | Windows 장비. `worker-start --on <saved-environment>` 원격 워커 경로가 열려 있다 |
| **R-13 정본 측정** | canonical 게이트 충족 측정 | HTTP 실패 0, trace 대조 전량, 문항·회차 정본 기준 충족. 저장소 동결 필요 |

### 7.1 후속 과제 (이 세션이 만든 것)

| 출처 | 내용 |
| --- | --- |
| 6.1 | 런처 경로 Dispatch 가 터미널의 실행 명령을 먼저 검사하고, 빈 셸이면 preamble 을 쓰기 전에 거부 |
| 6.3 | Capsule `forbidden` 표준 항목에 패키지 관리자 교체 금지 추가 |
| 6.4 | 리뷰어 `search_scope` 위반을 사후 감사로 검출 (읽은 경로 기록) |
| 선행 4.2 | baseline 생성 (필요해질 때) |
| 선행 R-10 | 메트릭 계측 후 Prometheus 추가 (2단계) |

---

## 8. 정리 상태

**모든 자원을 회수했습니다.** 리뷰어 1대는 `worker_done` 확인 직후 회수했고
빌더 워크트리에 남아 있던 터미널 2개도 함께 닫았습니다. `worker-release` 는
비감독 경로라 `no_owned_resource` 로 돌아왔고 `orca terminal close --terminal`
로 창 단위 종료했습니다(`--tab` 미사용).

AF2 워크트리는 `main` 병합(`7ac9e64`) 확인 후 제거했고 브랜치는
`git branch -d` 로 삭제했습니다. `-D` 강제는 쓰지 않았습니다.
`orca_settled_session_audit.py` 는 잔류 없음, `git worktree list` 는 주 저장소
한 줄, Run `run_71d230fcb319` 의 Task 10건은 전부 `completed` 입니다.

**Docker 는 선행 세션이 띄운 dev compose 스택(app, db, redis, meilisearch,
worker)이 그대로 떠 있습니다.** 이번 세션은 컨테이너를 건드리지 않았습니다.
다음 사람이 필요 없으면 내리십시오.

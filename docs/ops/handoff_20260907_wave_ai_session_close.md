# 인수인계: 20260907 Wave AI 세션 종료

> **작성일**: 2026-09-07
> **Run**: `run_4385c1063efc`
> **기준 커밋**: `c352de4` -> `d1dd144` (커밋 10개)
> **미병합 브랜치**: 없음
> **인수 대상**: 다음 코디네이터
> **선행 문서**: [`handoff_20260907_wave_ah_session_close.md`](handoff_20260907_wave_ah_session_close.md)

---

## 1. 한 줄 요약

**선행 인수인계 8.1 후속 과제 중 지금 착수 가능한 두 건을 닫고, 조율 중 직접
관측한 감시기 결함 한 건을 더해 세 건을 병합했습니다.** 빌더 3대와 리뷰어 3대를
운용했고 동시 쓰기는 상한 안에서 최대 2대였습니다.

---

## 2. 닫은 항목

| Wave | 내용 | 작업 커밋 | 병합 |
| --- | --- | --- | --- |
| AI1 | 커밋 메시지 한국어 규약 정본화와 기계 검사 (검사기 신규, commit-msg 훅, Level 1 게이트 8) | `50a2a6b` | `803724a` |
| AI2 | 감시기 `screen_tail` 계열 명명 정리 | `acc4132` | `a054bd4` |
| AI3 | 감시기가 Dispatch preamble 을 완료 보고로 오인하던 오탐 제거 | `068ce10` | `9fb38e0` |
| 정합 | AGENTS.md 허용 type 목록과 `source_commit` 갱신 | `3ab5be6`, `b4b2b8a` | `d1dd144` |

빌더는 전부 Antigravity `gemini-3.8-flash-medium`, 리뷰어는 전부 Antigravity
`claude-sonnet-4-6` 입니다. 리뷰 판정은 세 건 모두 `pass`, blocking_issues 0건
입니다. `main` 최종 검증은 pytest **3,843 passed / 32 skipped / 실패 0** 입니다.

원격 푸시까지 완료했습니다 (`c352de4..d1dd144`).

### 2.1 WORKER_MODEL_NOTICE

리뷰어 기본값은 `grok-4.6` 이나 토큰 리셋 전이라 사용할 수 없어 사용자 지시로
Antigravity `claude-sonnet-4-6` 을 썼습니다. 빌더가 Gemini 계열이므로 리뷰어
계열 분리 불변조건은 충족합니다.

---

## 3. 선행 인수인계의 후속 과제가 어떻게 처리됐는지

| 선행 8.1 항목 | 이번 결과 |
| --- | --- |
| 커밋 메시지 언어 규약을 기계로 검사 | AI1 로 닫힘 |
| `screen_tail` 계열 명명 정리 | AI2 로 닫힘 |
| `evidence.complete` 관측 후 감사 도구 ack 편입 판단 | 미착수. 관측치 축적이 선행 조건 |
| codex 런처 대기 표지 | 미착수. 조건부 과제 |
| baseline 생성 | 미착수 |
| R-10 2단계 Prometheus | 미착수 |

---

## 4. AI1: 규약이 정본이 아니었습니다

착수 전에 규약 충돌을 발견했습니다. `docs/ops/git_branching_strategy.md` 3장이
**"subject는 간결하게, 영어 또는 한국어 가능"** 이라고 적고 있었습니다. 즉
선행 세션 7.2 가 "워커의 커밋 메시지 이탈" 로 기록한 사건은 **정본 규약 위반이
아니라 Capsule `ground_truth` 이탈**이었습니다.

사용자가 2026-09-07 에 한국어 필수로 확정했고, 확정 내용은 다음과 같습니다.

| 항목 | 규약 |
| --- | --- |
| 형식 | `<type>: <subject>` |
| type | `feat` `fix` `docs` `refactor` `chore` `test` `ci` `merge` (영어 소문자) |
| subject | 한국어 필수. 한글 음절(U+AC00-U+D7A3) 최소 한 자 |
| 면제 | `Merge branch`, `Merge remote-tracking`, `Revert "`, `fixup!`, `squash!` |
| 검사 범위 | 제목 줄만. 본문과 트레일러는 대상 아님 |

`merge` 는 실제 이력에서 계속 쓰이는데 문서 표에 없었습니다. 이번에
`git_branching_strategy.md` 와 `AGENTS.md` 양쪽에 추가했습니다.

구현은 `scripts/validate_commit_message.py` 하나를 두 자리에 연결했습니다.

    pre-commit  commit-msg 훅       작성 시점에 거부
    Level 1     게이트 8            코디네이터 검증 시점에 거부

**훅은 별도 설치가 필요합니다.** 이 세션에서 주 저장소에는 설치했습니다.

```bash
uv run pre-commit install --hook-type pre-commit --hook-type prepare-commit-msg --hook-type commit-msg
```

### 4.1 필요성이 과제 진행 중에 스스로 입증됐습니다

규약 이탈은 이번 세션 워커 3대 중 2대에서 나왔습니다.

| 워커 | 커밋 제목 | 처리 |
| --- | --- | --- |
| AH1 (선행 세션) | `fix: verify block signals from rendered screen...` | amend 거부되어 그대로 병합 |
| AI2 | `refactor: rename screen_tail to terminal_text...` | amend 성공, `acc4132` 로 정정 |
| AI3 | 한국어 | 이탈 없음 |
| AI1 | 한국어 | 이탈 없음 |

**Capsule 의 `ground_truth` 에 규약을 명시해도 기계 검사가 없으면 통과했습니다.**
AI1 리뷰어가 최근 커밋 20개를 검사기에 넣어 확인한 결과 19개 통과, 1개 거부였고
거부된 것이 AH1 의 그 영어 제목입니다. 게이트 8 은 `main..branch` 의 새 작업만
검사하므로 과거 이력이 병합을 막지는 않습니다.

---

## 5. AI3: 조율 중 관측한 결함이었습니다

세션 내내 감시기가 정상 작업 중인 워커를 다음과 같이 표시했습니다.

    [차단:실패 정체] worker_done 완료 메시지에 reportPath 가 누락됨

화면을 직접 읽어 오탐임을 확인하고, 사양을 쓰기 전에 **재현으로 원인을
확정**했습니다. 증상에서 역추론하지 않았습니다.

```
preamble 전문        -> ('worker_done 완료 메시지에 reportPath 가 누락됨', ..., 'failure')
에코된 한 줄만        -> None
```

원인은 둘이 겹친 것입니다. `check_worker_done_report` 가 줄 단위로만 보아
백슬래시로 이어진 명령을 합치지 않으므로 `--type worker_done` 이 있는 줄에서
`--report-path` 를 찾지 못하고, 값이 `<optional: path to the full artifact>`
같은 꺾쇠 자리표시자인데도 실행된 명령과 구분하지 않았습니다.

**AH1 이 고친 것은 지나간 스트림 출력이 남는 문제였고, 이번 것은 현재 화면에
실제로 떠 있는 지시문 자체가 원인이라 그 수정으로 걸러지지 않았습니다.**

병합 직후 감시기를 돌려 오탐이 사라지고 진짜 승인 대기를 정확히 잡는 것을
확인했습니다. 임시 필터 없이 나온 결과입니다.

---

## 6. 이번 세션의 코디네이터 과실

### 6.1 격리 트리 예외를 Capsule 에 적지 않아 워커가 자산을 링크했습니다

AI3 Capsule 의 검증 명령에 `uv run pytest tests/ -q` 를 그대로 적었습니다.
격리 워크트리에서는 `tests/test_data_preservation.py` 의
`test_model_bin_files_exist` 와 `test_chroma_db_exists` 두 건이 gitignore 대상
자산 부재로 실패하는 것이 정상인데(스킬 2.3), **그 사실을 Capsule 에 옮기지
않았습니다.**

워커는 실패를 고쳐야 할 것으로 보고 **주 저장소의 `chroma_db/` 와 `model.bin`
5개로 심볼릭 링크를 걸었습니다.** 그 뒤 정리하려고 `rm -f` 승인을 요청했습니다.

승인 전에 대상이 링크인지 실체인지 확인했고 전부 링크였습니다. `rm -f` 는
링크를 따라가지 않으므로 원본은 지워지지 않습니다. 승인 후 원본 5개의 크기와
`chroma_db/` 내용을 재확인했고 **G1 위반은 없습니다.**

**워커의 cwd 가 주 저장소였다면 같은 명령이 모델 가중치를 복구 불가능하게
지웠을 것입니다.** 화면만 보고 승인했다면 그 차이를 알 수 없었습니다.

정본 형태는 `uv run pytest tests/ -q -m 'not data_assets'` 입니다. AI1 에는
이 형태가 갔고 AI3 에는 가지 않은 것이 차이의 전부입니다.

### 6.2 승인한 범위 확장을 Capsule 에 반영하지 않았습니다

AI1 이 게이트 8 추가 후 기존 픽스처 두 곳의 영어 mock 커밋 메시지가 거부된다며
범위 확장을 물었습니다. 승인은 Run 메시지(`msg_984e118077d5`)로만 했고 Capsule
은 그대로 두었습니다. 결과적으로 `summarize_worker_done.py` 가
`allowed_write_files 범위 초과` 를 위반으로 잡았습니다.

사후에 Capsule 을 갱신해 해소했으나, **승인하는 그 자리에서 Capsule 을 함께
갱신해야** 기계 검증까지 일관됩니다.

### 6.3 리뷰어에게 빌더용 커밋 강제 지시가 그대로 갔습니다

Dispatch 지시문의 "변경 파일을 스테이징하고 커밋하라" 는 추가 지시가 리뷰어
Dispatch 에도 붙습니다. AI1 리뷰어가 커밋할 것이 없는 상태에서 이 지시와
리뷰어 계약(커밋 금지)이 충돌해 **질문으로 멈췄습니다.**

리뷰어 산출물인 `review_done.json` 은 `.orca/` 아래라 gitignore 대상이므로
커밋 수 0 이 정상입니다.

### 6.4 Task 를 중복 생성했습니다

AI2 Task 생성 시 출력 JSON 파싱만 실패했는데 재시도해 중복(`task_e6f5857b53cc`)
이 생겼습니다. 정본은 `task_7db7ea0df02a` 이며 중복은 Dispatch 되지 않은 상태로
`failed` 처리하고 사유를 기록했습니다. **명령 실패와 출력 파싱 실패는 다릅니다.**

Run 도 같은 이유로 둘(`run_bc3e64fda5f8`, `run_73f0bb5ab2e4`)이 남았습니다.
`run-create` 에 `--title` 이 없고 `--objective` 만 받는데 이를 모르고 재시도한
결과이며, 두 Run 모두 Task 가 없습니다.

---

## 7. 병합 과정에서 걸린 게이트 두 건

둘 다 게이트가 옳았고 강제로 넘기지 않았습니다.

### 7.1 premerge 증거와 `MERGE_HEAD` 불일치

AI2 커밋 제목을 amend 해 해시가 `b0fae02` -> `acc4132` 로 바뀌자 게이트가
병합을 거부했습니다. **워커 워크트리를 지우기 전에** 거기서 `--record` 를 다시
돌려 해소했습니다. 순서가 반대였으면 증거를 만들 곳이 사라집니다.

같은 문제가 `source_commit` 수정에서도 났습니다. 주 저장소 작업 트리에서 고쳐
병합 커밋에 넣으려 했으나 증거 커밋이 `MERGE_HEAD` 와 달라 거부됐습니다.
병합을 중단하고 수정을 작업 브랜치에 올린 뒤 거기서 증거를 기록해 다시
병합했습니다.

### 7.2 `source_commit` 뒤처짐

병합 세 건이 쌓이자 `CURRENT_STATE.md` 의 `source_commit` 이 `52b5cb2` 에서
**HEAD 보다 10 커밋 뒤처져 허용치 5** 를 넘겼고,
`tests/test_validate_agent_rules.py` 두 건이 실패했습니다.

**각 작업 브랜치에서는 뒤처짐이 5 이내라 보이지 않고, 병합이 누적된 `main`
에서만 드러납니다.** 브랜치 전량 통과와 `main` 실패는 모순이 아닙니다.

---

## 8. 남은 항목

| ID | 내용 | 선행 조건 |
| --- | --- | --- |
| **R-12** | G2 Windows Docker Desktop 실기 | Windows 장비. `worker-start --on <saved-environment>` 원격 워커 경로가 열려 있다 |
| **R-13 정본 측정** | canonical 게이트 충족 측정 | HTTP 실패 0, trace 대조 전량, 문항·회차 정본 기준 충족. 저장소 동결 필요 |

### 8.1 후속 과제 (이 세션이 만든 것)

| 출처 | 내용 |
| --- | --- |
| 6.1 | `orca_taskctl.py expand` 가 격리 워크트리용 전량 테스트 명령에 `-m 'not data_assets'` 를 붙이도록 한다. 지금은 Capsule 작성자가 기억해야 하고, 잊으면 워커가 자산을 링크한다 |
| 6.1 | 스킬 2.3 의 격리 트리 예외를 Capsule `ground_truth` 표준 항목으로 승격한다 |
| 6.3 | Dispatch 지시문의 커밋 강제 문구를 역할별로 분기한다. 리뷰어에는 붙이지 않는다 |
| 세션 전반 | `$(...)` 명령 치환과 `while read` 가 섞인 읽기 전용 명령이 자동 승인 화이트리스트를 벗어난다. 이번 세션에서 다섯 번 이상 사람이 풀었다. 스킬 2.5 가 DB 조회에서 지적한 것과 같은 함정이 훅 조사와 이력 검사 경로에도 있다 |
| 4장 | 게이트 8 은 `main..branch` 만 검사한다. 과거 이력의 영어 제목은 남아 있으며 정리 여부는 판단하지 않았다 |
| 선행 AH 8.1 | `evidence.complete` 관측치 축적 후 감사 도구 ack 편입 판단, codex 런처 대기 표지, baseline 생성, R-10 2단계 Prometheus |

---

## 9. 정리 상태

**모든 자원을 회수했습니다.** 빌더 3대와 리뷰어 3대 전부 `worker_done` ack
직후 회수했습니다. `worker-release` 는 런처 경로가 비감독이라 여섯 건 모두
`retained` / `no_owned_resource` 로 돌아왔고, `orca terminal close --terminal`
로 창 단위 종료했습니다 (`--tab` 미사용). 닫기 전에 `tabId` 를 매번 코디네이터
것과 대조했습니다.

워크트리 `wave-ai1`, `wave-ai2`, `wave-ai3` 는 `main` 병합 확인 후 제거했고
브랜치는 `git branch -d` 로 삭제했습니다. `orca_settled_session_audit.py` 는
잔류 없음, `git worktree list` 는 주 저장소 한 줄입니다.

Run `run_4385c1063efc` 의 Task 는 6건 `completed`, 1건 `failed`(6.4 의 중복)
입니다.

**Docker 는 선행 세션이 띄운 dev compose 스택이 그대로 떠 있습니다.**

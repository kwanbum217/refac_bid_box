# 인수인계: Wave U 진단 보고서 P1 시정

> **작성일**: 2026-09-05
> **Run**: `run_88eed8b64095` (Wave T 에서 이어받아 Wave U 로 계속)
> **기준 커밋**: `9d7fdce` -> `5dc13cb` (원격 `main` 반영 완료)
> **미병합 후보**: 없음
> **인수 대상**: 다음 코디네이터
> **이전 코디네이터**: Codex -> Claude Opus 5
> **선행 문서**: [`handoff_20260905_wave_t_p0_remediation.md`](handoff_20260905_wave_t_p0_remediation.md)

---

## 1. 한 줄 요약

선행 인수인계 3장의 T10 재개 절차를 완료해 `main` CI 를 초록으로 되돌리고,
5.2 절 잔여 항목 중 O-04, O-05, O-06, T-01, C-01 잔여 4건, C-02 를 병렬로 닫아
전부 병합했습니다. 워커 3대와 독립 리뷰어 6대를 운용했고 리뷰가 반려한 결함 2건은
재작업으로 해소했습니다. 남은 항목은 5 장에 정리했습니다.

---

## 2. 병합 완료 (전부 원격 반영)

| 순서 | 작업 | 병합 커밋 |
| --- | --- | --- |
| 1 | T10 CI actionlint SC2034 수정 + Wave T 인수인계 문서 커밋 | `fa1202f` |
| 2 | T-01 Arq span, C-01 잔여 4건, C-02, 코디네이터 문서 작업 | `ac3def7` |
| 3 | O-04/O-05/O-06 통제면 + `source_commit` 기준 정정 | `5dc13cb` |

`main` 상태는 `5dc13cb` 입니다. 전량 3,643 passed / 32 skipped / 3 deselected,
`validate_agent_rules` 20/20, ruff 통과, mypy 93개 파일 0건, 문서 링크 594개 통과.

`fa1202f` 의 GitHub Actions Run `33947859707` 은 **전 job success** 입니다.
Windows job 성공은 `ci_windows` 판정의 실행 증거로 문서에 인용했습니다.
`ac3def7` 의 Run `33949674818` 은 `lint-and-validate` 만 실패했고 원인과 조치는
7.2 절에 있습니다. `5dc13cb` 의 Run 결과는 세션 종료 시점 기준 9 장을 보십시오.

---

## 3. 항목별 처리 결과

| ID | 처리 | 커밋 |
| --- | --- | --- |
| O-04 | 리뷰 Task 와 rework 재작업 Task 가 대상 Task 를 `deps` 로 자동 연결 | `d5d675b` |
| O-05 | 완료 보고 필수 필드 정본을 `scripts/orca_contract.py` 하나로 통일. 검증기·고지문·디스크 템플릿이 전부 파생되고 테스트가 완전 일치를 강제 | `d5d675b`, `522c2ff` |
| O-06 | 비감독 Dispatch 를 `.orca/dispatch_receipts` 에 기록하고 잔류 세션 감사가 그것을 읽음 | `d5d675b` |
| T-01 | `arq_on_job_end` 가 ERROR span 을 덮지 않고, 등록 태스크 15개 전수를 `traced_worker_task` 로 배선. 레지스트리 순회 테스트로 누락 차단 | `3e11c80` |
| C-01 잔여 | `confirmation_token_redis`, `row_reconciliation`, `promotion_status_check`, `ci_windows` 를 실제 코드와 실행 결과 기준으로 갱신 | `c735dfb`, `5dd95f5` |
| C-02 | 공급망 문서의 플랫폼 팀 소유와 PR 리뷰 전제를 1인 작업 규약으로 교체. 게이트 강도 불변 | `c735dfb` |

---

## 4. 리뷰어가 잡은 것

**기계 게이트를 전부 통과한 산출물 두 건이 독립 리뷰에서 반려됐습니다.**

| 대상 | 반려 사유 | 해소 |
| --- | --- | --- |
| C-01 | `ci_windows` 를 `closed` 로 바꾸면서 근거가 워크플로 정의뿐인데 통과 상태를 단정. 열린 확인 항목이 문서상 사라짐 | 코디네이터가 GHA Run `33947859707` 실행 증거를 확보해 재작업으로 인용 |
| O-05 | 디스크 템플릿이 정본에서 파생되지 않은 복사본이고, 드리프트 테스트가 같은 상수를 자기 자신과 비교하며, `dispatch_id` 가 문서와 코드에서 어긋남 | 렌더러 출력과 디스크 템플릿의 완전 일치를 테스트로 강제. `dispatch_id` 는 선택 필드로 통일 |

두 지적 모두 "테스트가 통과한다" 와 "실제로 그렇게 동작한다" 가 다른 사례입니다.
선행 세션의 같은 결론이 이번에도 재현됐습니다.

---

## 5. 남은 항목

| ID | 내용 | 비고 |
| --- | --- | --- |
| S-02 | Actions, 도구 이미지, pip-audit 버전 불변 pin | 미착수. `.github/workflows/` 단독 작업이라 병렬화 가능 |
| D-04 | startup catch-up 이 ARQ `max_jobs` 밖에서 실행, completeness ledger 없음 | 미착수 |
| D-05 | KB reconciliation 103건 모집단 불일치 | 미착수 |
| G-01 | Windows Docker 실기, RPO/RTO, 관측성 backend, cold SQL 재측정 | 장비 부재로 보류. `worker-start --on <saved-environment>` 로 원격 Windows 워커를 띄우는 경로가 아직 열려 있음 |
| 신규 A | Arq abort 경로의 `CancelledError` 가 `except Exception` 에 걸리지 않아 최상위 span 이 OK 로 남음 | T-01 리뷰가 지적한 잔여 리스크. `allow_abort_jobs = True` 이므로 실경로다 |
| 신규 B | Level 1 게이트에 mypy 검증 능력이 없음 | T-01 병합 후에야 mypy 2건이 드러났다. 7.3 절 |
| 신규 C | Level 1 게이트 6 이 브랜치당 worker_done 보고 1건을 가정 | 재작업 브랜치에서 구조적으로 실패한다. 7.4 절 |
| 신규 D | `taskctl rework` 의 Capsule 경로 불일치 | 7.1 절. 워커 두 대가 이 때문에 엉뚱한 Capsule 을 읽었다 |
| 신규 E | `cmd_dispatch --deps` 도움말과 `orca_control_plane_tools.md` 6.1 절이 dispatch 시점 자동 연결을 주장하나 구현은 `create` 에만 있음 | O-05 리뷰가 지적한 문서 과장 |
| 신규 F | 비감독 receipt 기록 실패가 fail-open | O-06 리뷰가 지적. 기존 fail-closed 게이트는 느슨해지지 않았다 |

---

## 6. 이번 세션의 워커 운용

| 역할 | 모델 | 대수 | 결과 |
| --- | --- | --- | --- |
| 빌더 | `gemini-3.8-flash-medium` (Antigravity) | 3 | 전부 완주. 계약 위반 0건 |
| 빌더 재작업 | `gemini-3.8-flash-medium` 1대, `gemini-3.8-flash-high` 1대 | 2 | 전부 완주 |
| 리뷰어 | `grok-4.6` | 6 | 전부 완주. 반려 2건, pass 4건 |

`qwen3.7-plus` 는 이 세션 내내 할당량 소진 상태였습니다. 리뷰어는 전부
`grok-4.6` 으로 띄웠고 그 경로를
[`agent_worker_launch_reference.md`](agent_worker_launch_reference.md) 1.7 절로
정본화했습니다.

`WORKER_MODEL_NOTICE`: O-05 재작업 1건만 라우터 권장값보다 상위인
`gemini-3.8-flash-high` 를 명시 지정했습니다. 반려 사유가 "자기 자신과 비교하는
무의미한 테스트" 를 정직한 테스트로 바꾸라는 구조적 판단이었고 medium 등급이
1차에서 그 함정에 빠졌기 때문입니다. 이후 기본값으로 복귀했습니다.

리뷰어는 `dispatch --return-preamble` + `terminal send` 경로라 **비감독**입니다.
`worker-release` 가 전부 `retained` / `no_owned_resource` 로 돌아왔고 터미널은
`orca terminal close` 로 직접 닫았습니다.

---

## 7. 인수자가 반드시 알아야 할 함정

### 7.1 `taskctl rework` 는 Capsule 을 만든 곳과 다른 곳을 가리킵니다

`rework` 는 새 Capsule 을 `.orca/capsules/task_<새_task_id>/capsule.yaml` 에
쓰지만 Task `spec` 은 `.orca/capsules/task_<원본_task_id>_rework/capsule.yaml` 을
가리킵니다. **그 디렉터리는 만들어지지 않습니다.**

이번에 재작업 워커 두 대가 없는 경로를 열지 못하자 이름이 비슷한
`task_<이름>_review/capsule.yaml`(리뷰 Capsule)을 대신 읽었습니다. 한 대는 그
안의 `task_id` 와 `dispatch_id` 까지 그대로 베껴 **이미 끝난 리뷰 Task 앞으로
`worker_done` 을 보냈습니다.** 사양 오독과 계보 오염이 함께 일어납니다.

조치는 `rework` 직후 다음을 실행하는 것입니다.

```bash
mkdir -p .orca/capsules/task_<원본ID>_rework
cp .orca/capsules/task_<새ID>/capsule.yaml .orca/capsules/task_<원본ID>_rework/capsule.yaml
cp -R .orca/capsules <워크트리>/.orca/
```

**기동 직후 `orca terminal read` 로 어떤 Capsule 을 읽었는지 반드시 확인하십시오.**

### 7.2 `source_commit` 은 병합 직전 `main` HEAD 가 아니라 병합된 브랜치 끝점입니다

선행 인수인계 7.2 절은 "병합 커밋 안에서 갱신하라" 까지만 적었습니다. 그대로 하면
**병합이 5 커밋을 넘게 가져올 때 구조적으로 실패합니다.** `ac3def7` 이 그랬습니다.
병합 직전 `main` HEAD 인 `fa1202f` 를 적었는데 병합이 9 커밋을 가져와 거리가 9 가
됐고, 기본 브랜치에서는 이 검사가 fail-closed 라 CI 의 `lint-and-validate` 가
막혔습니다.

**병합되는 브랜치의 끝점을 적으십시오.** 그 커밋은 병합 커밋의 부모이므로 거리가
1 이 됩니다.

```bash
TIP=$(git rev-parse --short=7 <병합할 브랜치>)
git merge --no-ff --no-commit <병합할 브랜치>
# CURRENT_STATE.md 의 source_commit 을 $TIP 으로 바꾼 뒤 같은 커밋에 담는다
```

### 7.3 Level 1 게이트에 mypy 능력이 없습니다

T-01 병합 후 `uv run mypy src` 가 `observability.py` 에서 2건을 냈습니다. Level 1
게이트의 능력 표(`frontend_test`, `docker_build`, `compose_config`,
`workflow_lint`, `backend_pytest`)에 mypy 가 없어 게이트는 통과했습니다.
`main` 은 mypy 0건을 요구하므로 **`src/` 를 건드리는 Task 의 Capsule
`verification_commands` 에 `uv run mypy src` 를 직접 넣으십시오.** 게이트에 능력을
추가하는 것이 정공법이며 5 장 신규 B 로 남깁니다.

### 7.4 게이트 6 은 재작업 브랜치에서 구조적으로 실패합니다

게이트 6 은 브랜치당 `worker_done` 보고 **하나**가 `main...HEAD` 전체 diff 를
설명한다고 가정합니다. 재작업 브랜치에는 보고가 둘이고 각각 자기 회차의 파일만
담으므로 어느 쪽으로 돌려도 `changed_files 불일치` 가 납니다.

이번에는 두 보고의 `changed_files` 합집합이 브랜치 diff 와 정확히 일치하는지
코디네이터가 직접 대조해 판정했습니다. **게이트를 건너뛴 것이 아니라 게이트의
가정이 성립하지 않는 경우임을 확인하고 같은 내용을 손으로 검사한 것입니다.**
그 사실을 병합 커밋 메시지에 남겼습니다.

또한 워커 보고 뒤에 코디네이터가 `main` 을 워커 브랜치에 병합하면 테스트 건수가
달라져 게이트 6 이 `건수 불일치` 로 실패합니다. **보고 검증을 끝낸 뒤에 병합하십시오.**

### 7.5 리뷰 체크리스트는 손으로 옮기지 마십시오

Level 1 게이트 5 는 **빌더 Capsule** 의 `review_checklist` 를 정본으로 삼아 id
누락과 `defect_when` 극성을 판정합니다. 리뷰 Intent 에 질문을 다시 쓰면 내용이
옳아도 게이트가 실패합니다. 이번에 T-01 리뷰를 두 번 다시 돌렸습니다. 1차는 id 가
달라 조건1 위반, 2차는 질문을 부정형으로 뒤집어 극성이 반대가 되어 조건3·조건4
위반이었습니다.

`scripts/build_review_intent.py` 를 추가했습니다. 리뷰 Intent 를 만들 때 반드시
쓰십시오.

```bash
python3 scripts/build_review_intent.py \
  --capsule .orca/capsules/<빌더 Task>/capsule.yaml \
  --intent .orca/capsules/review_intents/<이름>.yaml \
  --extra <리뷰어 전용 항목 YAML>
```

### 7.6 Antigravity 워커는 `worker_done` 을 자주 빠뜨리거나 틀립니다

이번 세션에서 세 번 개입했습니다. 한 번은 `--dispatch-id` 를 빠뜨려 Orca 가
거부했고, 한 번은 커밋만 하고 수명주기 메시지를 아예 보내지 않았으며, 한 번은
7.1 의 여파로 다른 Task 의 ID 를 썼습니다. **커밋이 생겼는데 Task 가
`dispatched` 로 남아 있으면 터미널에 직접 재전송을 지시하십시오.**

커밋 메시지도 두 번 영어로 작성했습니다. 재작업 사유에 한국어를 명시했는데도
지켜지지 않았습니다. 병합 전에 확인하십시오.

---

## 8. 정리 상태

**모든 워커 자원을 회수했습니다.**

| 대상 | 상태 |
| --- | --- |
| 워커 터미널 | 빌더 3대, 재작업 2대, 리뷰어 6대 전부 `worker-release` 후 `terminal close` |
| 워크트리 | `wave-t-t10-ci`, `wave-u-t01`, `wave-u-c012`, `wave-u-o456` 전부 `git worktree remove` |
| 브랜치 | 병합 확인 후 `git branch -d` 로 삭제. `-D` 는 쓰지 않았다 |
| 감사 | `orca_settled_session_audit.py` 잔류 없음, `orca_worker_watch.py` 대상 없음 |

현재 프로젝트 작업 트리에 남은 터미널은 코디네이터 본인과 초기 셸 하나뿐입니다.

Orca Task 중 `task_2420cc90107b` 와 `task_f37488ce6b8a` 두 건은 `blocked` 로
남겨 두었습니다. `taskctl create --json` 의 출력 파싱에 실패해 재실행하면서 생긴
**중복 Task** 이고, 실제 Dispatch 대상은 `task_8f6b3b693f18` 과
`task_cd737688ebd4` 였습니다. 결과에 `note` 로 그 사실을 적었습니다.

Docker Desktop 은 shellcheck 포함 actionlint 검증을 위해 이 세션에서 다시
올렸습니다. compose 서비스는 올리지 않았습니다.

---

## 9. 다음 코디네이터가 먼저 할 일

1. `5dc13cb` 의 GitHub Actions Run 이 전부 성공했는지 확인합니다. `main` 이
   초록이 아니면 그것부터 처리합니다.
2. 5 장의 신규 B(게이트 mypy 능력)와 신규 D(`rework` Capsule 경로)를 먼저
   닫으십시오. **둘 다 다음 워커 운용의 정확도를 직접 올립니다.** 신규 D 는
   이번 세션에서 워커 두 대의 사양 오독과 계보 오염을 실제로 일으켰습니다.
3. 그 다음은 S-02 입니다. `.github/workflows/` 단독 작업이라 다른 섹션과 겹치지
   않습니다.
4. G-01 의 Windows 실기는 `worker-start --on <saved-environment>` 로 원격 워커를
   띄우는 경로가 열려 있습니다. Windows 머신에 Orca 를 띄우면 CI 왕복 없이
   직접 재현할 수 있습니다.

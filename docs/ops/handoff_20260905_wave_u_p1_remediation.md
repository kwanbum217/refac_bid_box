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
| R-01 | 백업 검증기가 빈 매니페스트를 유효로 판정 | 2026-09-05 외부 진단 보고서. 코디네이터가 격리 fixture 로 재현 확인. Intent 준비됨 |
| R-02 | 정기 백업의 운영 컨테이너 배선 미완 | 같은 보고서. worker 환경변수에 BACKUP_SCHEDULE_ENABLED 와 DB_HOST 계열 부재, Dockerfile 에 mysql 클라이언트 부재를 실측 확인 |
| R-03 | 큐 적체를 정렬 집합에 llen 으로 조회 | 같은 보고서. arq 소스 대조로 확인. Intent 준비됨 |
| R-15 잔여 | Dockerfile 의 uv 이미지가 태그 참조 | V3 의 쓰기 범위 밖이라 별도 처리 필요 |

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

### 7.1 재작업 워커가 유사한 이름의 Capsule 로 이탈합니다

**2026-09-05 최초 작성 시 이 절의 원인 진단이 틀렸습니다. 아래는 정정본입니다.**

재작업 워커 두 대가 지정된 Capsule 대신
`.orca/capsules/task_<이름>_review/capsule.yaml`(리뷰 Capsule)을 읽었습니다. 한 대는
그 안의 `task_id` 와 `dispatch_id` 까지 그대로 베껴 **이미 끝난 리뷰 Task 앞으로
`worker_done` 을 보냈고** Orca 가 거부했습니다.

당시 코디네이터는 원인을 "`rework` 가 Capsule 을 만드는 곳과 Task spec 이 가리키는
곳이 달라 파일이 없다" 로 진단했습니다. **틀린 진단입니다.**
`scripts/orca_taskctl.py` 의 `cmd_rework` 는 3682~3695행에서 Task 를 만들기 **전에**
`.orca/capsules/task_<원본ID>_rework/` 를 mkdir 하고 `capsule.yaml` 을 씁니다.
3744~3745행은 실제 `task_id` 가 달라지면 새 경로와 옛 경로 양쪽에 씁니다. 파일은
정상적으로 생성되며, 2026-09-05 외부 진단 보고서 4장이 이 줄들을 근거로 정정을
요구했고 재확인 결과 두 경로 모두에 동일한 파일이 있었습니다.

**실제 원인은 워커가 이름이 비슷한 디렉터리로 스스로 이탈한 것입니다.** 파일 배치로
막히지 않습니다.

| 조치 | 내용 |
| --- | --- |
| 즉시 | 재작업 Dispatch 직후 `orca terminal read` 로 워커가 연 Capsule 경로를 눈으로 확인하고, 다른 파일이면 정정 지시를 보낸다 |
| 근본 | `dispatch` 가 기동 전에 Capsule 정본 실존을 확인해 fail-closed 로 거부한다. 준비된 `v2_control_plane_truth.yaml` 의 `required_change` 3번이다 |

**이 오진은 V2 워커에게 그대로 주입됐습니다.** 기동 후 정정 지시를 보내
`required_change` 1번과 2번을 전제 오류로 무효화하고 3~5번만 수행하도록 했습니다.
V2 산출물을 검토할 때 그 지시가 반영됐는지 확인하십시오.

교훈은 하나입니다. **증상에서 역추론한 원인을 `ground_truth` 에 "재조사 불필요" 로
못박지 마십시오.** 해당 함수를 열어 줄 번호와 함께 확인한 사실만 적고, 확인하지
못한 것은 `required_change` 의 조사 항목으로 내립니다.

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

## 9. 다음 웨이브 Task Intent 는 준비돼 있습니다

5 장의 항목 중 다섯 건을 Task Intent 로 미리 작성해 `.orca/capsules/intents/` 에
두었습니다. `orca_taskctl.py expand` dry-run 으로 Capsule 확장까지 검증했습니다.
`create` 와 `dispatch` 만 하면 바로 기동할 수 있습니다. **`.orca/` 는 gitignore
대상이라 이 Intent 들은 이 기기 로컬에만 있습니다.** 다른 기기에서 이어받으면
5 장의 항목 설명과 7 장의 함정을 근거로 다시 작성해야 합니다.

| Intent | 닫는 항목 | 쓰기 범위 | 겹침 |
| --- | --- | --- | --- |
| `v1_gate_capability.yaml` | 신규 B, 신규 C | `orca_level1_gate.py`, `orca_taskctl.py`, `summarize_worker_done.py`, 스킬 미러 | V2 와 `orca_taskctl.py` |
| `v2_control_plane_truth.yaml` | 신규 D, 신규 E, 신규 F | `orca_taskctl.py`, `orca_settled_session_audit.py` | V1 과 `orca_taskctl.py` |
| `v3_supply_chain_pin.yaml` | S-02 | `.github/workflows/`, 공급망 문서 | 없음 |
| `v4_backup_verify_strict.yaml` | R-01 | `backup_snapshots.py`, `backup_recovery*.py`, 백업 테스트 | 없음 |
| `w1_arq_abort_span.yaml` | 신규 A | `observability.py`, `worker.py` | W2·W3 와 `worker.py` |
| `w2_catchup_ledger.yaml` | D-04, R-04 | `worker.py`, `scheduled_tasks.py` | W1·W3 와 `worker.py` |
| `w3_queue_backlog_metric.yaml` | R-03 | `worker.py`, `test_worker_heartbeat.py` | W1·W2 와 `worker.py` |

**`scripts/orca_taskctl.py` 를 V1 과 V2 가, `src/tasks/worker.py` 를 W1·W2·W3 가
공유합니다.** 같은 파일에 동시 쓰기를 배정하지 마십시오. 권장 순서는 다음과 같습니다.

| 웨이브 | 동시 Dispatch | 이유 |
| --- | --- | --- |
| 1 (기동 완료) | V2 + V3 + W1 | 2026-09-05 세션에서 기동함 |
| 2 | V1 + V4 + W3 | V2 와 W1 병합 후. 셋은 서로 겹치지 않는다 |
| 3 | W2 | W3 병합 후 |

**웨이브 1 은 이미 돌고 있습니다.** Run `run_029274587357`, Task
`task_490d6d4f7d1f`(V2), `task_63f8823e4969`(V3), `task_82b3c4587fbe`(W1) 입니다.
그 산출물을 병합한 뒤 웨이브 2 를 시작하십시오.

**V2 워커에게는 기동 후 정정 지시를 보냈습니다.** Capsule 의 `required_change`
1번과 2번이 7.1 절의 오진에 기반하므로 무효화하고 3~5번만 수행하도록 했습니다.
V2 산출물 검토 시 그 지시가 반영됐는지 확인하십시오.

R-02(백업 운영 배선)와 R-15 잔여(Dockerfile uv 이미지)는 Intent 를 만들지
않았습니다. R-02 는 "백업을 어디서 실행할 것인가" 라는 운영 결정이 선행돼야
하고, 그 결정 없이 코드를 고치면 방향이 틀립니다. R-15 잔여는 V3 병합 후
같은 파일 계열에서 이어서 처리하는 편이 낫습니다.

D-05(KB reconciliation)는 R-05 와 같은 항목입니다. 조사 범위가 정해지지 않아
Intent 를 만들지 않았습니다. 먼저 모집단 불일치의 원인을 좁히는 읽기 전용 조사
Task 가 필요합니다.

### 9.1 `expand` 가 Intent 선언을 덮어씁니다

dry-run 에서 확인한 별개의 결함입니다. `orca_taskctl.py expand` 는 Intent 에
선언한 `verification_commands` 와 `shared_resources` 를 그대로 쓰지 않고 자체
계산 결과로 **덮어씁니다.** Intent 에 적은 `uv run mypy src` 와 docker/redis 공유
자원 선언이 전부 사라졌습니다.

그래서 준비한 다섯 Intent 의 `ground_truth` 에 "Capsule 에 mypy 명령이 없더라도
직접 실행하고 결과를 보고에 적어라" 를 못박아 두었습니다. 근본 해결은 V1 의
required_change 7번입니다.

---

## 9.2 외부 진단 보고서 20260905 검증 결과

`gpt6-astra medium` 이 작성한 읽기 전용 진단 보고서를 코디네이터가 코드로
검증했습니다. **기준 커밋이 `9e4a074` / `c899365` 로 당시 `main` 과 같아 뒤처진
보고서가 아닙니다.**

| ID | 검증 방법 | 판정 |
| --- | --- | --- |
| R-01 | `verify_snapshot()` 을 격리 fixture 로 직접 호출 | **확정.** 빈 매니페스트, 빈 `components`, 체크섬 없는 0바이트 자산이 전부 `is_valid=True` |
| R-02 | `docker-compose.prod.yml` worker 블록 전수 확인 | **확정.** `BACKUP_SCHEDULE_ENABLED` 미전달, `DB_HOST`/`DB_PORT`/`DB_USER`/`DB_NAME` 미전달, Dockerfile 에 mysql 클라이언트 부재. 세 갈래 전부 |
| R-03 | 설치된 arq 의 `connections.py` 소스 대조 | **확정.** arq 는 `zadd` 로 정렬 집합에 넣는데 `worker.py:71` 은 `llen`. 테스트의 가짜 Redis 가 잘못된 전제를 통과시킴 |
| R-04 | `worker.py` 125~135행 | **확정.** 이미 `w2_catchup_ledger.yaml` 로 준비됨 |
| R-05 | `verify_reconciliation` 로직 | **확정.** 낙찰 기준 집합을 공고 기준 ChromaDB 와 그대로 차집합 |
| R-06 | `promotion.py:481-484` | **확정.** 다만 `model_swap_gap` 으로 이미 원장에 active 등록됨 |
| R-08, R-09, R-11, R-15 | 각 지목 줄 | **전부 사실** |
| 4장 mypy·게이트 6·receipt | 각 지목 줄 | **전부 사실.** 5 장 신규 B, C, F 와 같은 항목 |
| 4장 rework 경로 | `cmd_rework` 3682~3745행 | **보고서가 옳고 이 문서의 최초 7.1 절이 틀렸습니다.** 7.1 절을 정정했습니다 |

R-07, R-10, R-12, R-13, R-14 는 정책 결정과 실측이 필요한 항목이라 코드 검증
대상이 아니며 보고서도 그렇게 밝히고 있습니다.

**보고서의 가장 큰 기여는 4장의 rework 항목입니다.** 코디네이터가 증상에서
역추론한 원인을 Capsule `ground_truth` 에 "재조사 불필요" 로 못박았고, 워커가
이미 그 전제로 작업을 시작한 뒤였습니다. 보고서가 해당 줄을 읽어 정정을
요구하지 않았다면 틀린 구현이 병합됐을 것입니다.

---

## 10. 다음 코디네이터가 먼저 할 일

1. `5dc13cb` 의 GitHub Actions Run `33950212636` 은 **전 job success** 로
   확인했습니다. `main` 은 초록입니다.
2. 9 장의 웨이브 1(V2 + V3 + W1)을 그대로 Dispatch 하십시오. Intent 는 작성과
   Capsule 확장 검증까지 끝나 있습니다.
3. 웨이브 1 병합 후 웨이브 2(V1 + W2)를 돌립니다.
4. D-05 는 Intent 가 없습니다. 모집단 불일치 원인을 좁히는 읽기 전용 조사 Task
   부터 만드십시오. 읽기 전용 워커는 동시 쓰기 상한에 포함되지 않으므로 웨이브
   1 과 함께 띄워도 됩니다.
5. G-01 의 Windows 실기는 `worker-start --on <saved-environment>` 로 원격 워커를
   띄우는 경로가 열려 있습니다. Windows 머신에 Orca 를 띄우면 CI 왕복 없이
   직접 재현할 수 있습니다.

# 인수인계: Wave V/W/X 세션 종료

> **작성일**: 2026-09-05
> **Run**: `run_029274587357`(V), `run_fab6af10f788`(W), `run_febef4f1cee9`(X, 진행 중)
> **기준 커밋**: `9d7fdce` -> `269c755` (원격 `main` 반영 완료)
> **인수 대상**: 다음 코디네이터
> **이전 코디네이터**: Claude Opus 5 (사용량 한도로 인계)
> **선행 문서**: [`handoff_20260905_wave_u_p1_remediation.md`](handoff_20260905_wave_u_p1_remediation.md)

---

## 1. 한 줄 요약

Wave U 에 이어 세 웨이브를 돌려 진단 보고서 항목 9건을 닫고 `main` 을 `269c755`
까지 올렸습니다. **Wave X 가 진행 중이며 워커 2대가 살아 있습니다.** 그 상태와
재개 절차가 5장입니다.

---

## 2. 병합 완료 (전부 원격 반영)

| 커밋 | 내용 | 닫은 항목 |
| --- | --- | --- |
| `f8dc1fe` | Wave V 세 건 + 외부 진단 보고서 검증 결과 | 신규 A/D/E/F, S-02, R-11, R-15 |
| `f696731` | Wave W 세 건 | 신규 B/C, R-01, R-03 |
| `269c755` | `source_commit` 갱신 | - |

`main` 최종 검증은 pytest 3,671 passed / 32 skipped / 3 deselected, 규칙 20/20,
ruff 통과, mypy 93개 파일 0건, 문서 링크 601개 통과입니다.
`f8dc1fe` 의 GitHub Actions Run `33952994772` 는 전 job success 입니다.
`269c755` 의 CI 결과는 확인하지 못했으니 **가장 먼저 확인하십시오.**

---

## 3. 항목별 처리 결과

| ID | 처리 | 커밋 |
| --- | --- | --- |
| 신규 D/E/F | rework Capsule 워크트리 배치, dispatch 의 Capsule 실존 fail-closed 확인, `--deps` 허구 옵션 제거, 비감독 receipt fail-closed | `617a4ca` |
| S-02, R-15 | Actions 7종을 커밋 SHA 로 고정, pip-audit·actionlint 버전 고정 | `ae68730` |
| 신규 A, R-11 | 취소된 Arq 작업의 최상위 span 을 OK 로 덮지 않음. 상태는 UNSET, `task.cancelled` 속성으로 구분 | `27a3717` |
| 신규 B, C | Level 1 게이트에 mypy 능력 추가, 게이트 6 이 다중 worker_done 보고 수용 | `69406cb` |
| R-01 | 백업 검증기가 필수 자산·스키마·크기·SHA256 형식을 강제 | `77ee1da` |
| R-03 | 큐 적체 조회를 `llen` 에서 정렬 집합 조회로 전환, 관측 실패와 0건 구분 | `ca1fb95` |

---

## 4. 외부 진단 보고서 검증

`gpt6-astra medium` 의 읽기 전용 보고서(기준 커밋 `9e4a074`/`c899365`)를 코드로
검증했습니다. 상세는 선행 문서 9.2 절입니다. **P1 중 코드로 판정 가능한 항목은
전부 사실이었고, 한 건은 이 세션 코디네이터의 오진을 정정했습니다**(rework 경로).

---

## 5. 진행 중인 작업 — 즉시 이어받을 것

**Run `run_febef4f1cee9` (Wave X) 의 빌더 3대는 전부 끝났고 워커 터미널도 모두
회수했습니다. 남은 것은 리뷰와 병합입니다.**

| Task | 상태 | 브랜치 / 커밋 | 남은 일 |
| --- | --- | --- | --- |
| `task_b6cef03e3887` X2 잔여정리 | 완료 | `9759735` | **`wave_t/handoff` 병합 완료**(`8db4353`). `main` 미반영 |
| `task_c6fcd549740e` X2 리뷰 | 완료 | - | Codex `gpt-5.6-terra`, pass. 회수까지 정상 |
| `task_d9527d72e596` W2 catchup | 완료 | `kwanbum217/wave-x-w2-catchup` | **게이트 6/6 PASS, mypy 0건. 리뷰어 미기동** |
| `task_7f0659b4d4fc` X4 승격전환 | 완료 | `kwanbum217/wave-x-x4-swap` (`902a046`) | **게이트 6 실패(6.6 절). 리뷰어 미기동** |

살아 있는 터미널은 코디네이터 것뿐입니다. 워크트리 3개
(`wave-x-w2-catchup`, `wave-x-x4-swap`, `wave-x-x2-cleanup`)와 브랜치 3개는
미병합이거나 `main` 미반영이라 **제거하지 마십시오.**

### 5.1 재개 절차

1. `269c755` 의 CI 결과를 확인합니다.
2. W2 에 리뷰어를 붙입니다. 게이트와 mypy 는 이미 통과했으므로 Level 2 만
   남았습니다. 리뷰 Intent 는 `scripts/build_review_intent.py` 로 빌더 Capsule
   에서 체크리스트를 복사해 만드십시오. 손으로 옮기면 id 와 `defect_when` 극성이
   어긋나 게이트 5 가 실패합니다.
3. X4 의 `worker_done.json` 부재를 재작업 Task 로 해소하고(6.6 절), 게이트를 다시
   돌린 뒤 리뷰어를 붙입니다.
4. W2 와 X4 를 `wave_t/handoff` 에 병합합니다. X2 는 이미 병합돼 있습니다.
5. `wave_t/handoff` 를 `main` 에 병합하고, **그 다음 별도 커밋으로**
   `source_commit` 을 갱신합니다(6.1 절).

**W2 보고의 알려진 한계**: 워커가 Capsule 검증 명령에 적힌
`tests/test_arq_worker.py` 를 실행하지 못했다고 보고했습니다. 그 파일이 저장소에
없기 때문이며 **코디네이터의 Intent 작성 오류**입니다. 게이트 3 은 통과했으나
어떤 테스트가 실제로 돌았는지 리뷰에서 함께 확인하십시오. 워커가 이를 숨기지
않고 보고한 것은 정상 처리입니다.

### 5.2 미기동 Intent

`x3_kb_population_probe.yaml` (R-05, D-05)은 준비돼 있으나 기동 실패로 남았습니다.
읽기 전용 investigator 라 동시 쓰기 상한에 포함되지 않으니 언제든 붙일 수 있습니다.
`.orca/` 는 gitignore 대상이라 이 Intent 들은 이 기기 로컬에만 있습니다.

---

## 6. 이 세션에서 새로 확인한 함정

### 6.1 `source_commit` 은 병합 커밋 안에서 갱신할 수 없습니다

선행 문서 7.2 절이 "병합되는 브랜치의 끝점을 병합 커밋 안에서 적으라" 고 했는데
**앞부분만 맞습니다.** `validate_agent_rules` 의 `_commits_behind_head` 는
`merge-base --is-ancestor <recorded> HEAD` 를 먼저 요구합니다. 병합 커밋을 만드는
시점의 HEAD 는 아직 병합 전이라 병합될 브랜치의 끝점이 조상이 아니어서 거부됩니다.

**병합을 먼저 커밋하고, 그 뒤 별도 브랜치에서 갱신해 다시 병합하십시오.**
병합이 끝나면 그 끝점은 조상이 되고 거리는 1 입니다. 이 세션에서 그 순서로
`269c755` 를 만들었습니다.

주의: 그 갱신 브랜치도 전량 테스트 증거가 자기 커밋 기준으로 기록돼 있어야
병합 게이트를 통과합니다. `premerge_full_suite_gate.py --record` 를 그 브랜치에서
다시 돌리십시오.

### 6.2 워커가 죽어도 산출물은 남을 수 있습니다

Wave W 의 V1 빌더가 커밋과 `worker_done.json` 작성을 마친 **직후** Gemini 할당량
소진으로 종료해 수명주기 메시지를 보내지 못했습니다. Task 는 `dispatched` 로
남고 커밋은 온전했습니다.

**터미널에 `Agent execution terminated due to error` 가 보이면 먼저 워크트리의
커밋과 `worker_done.json` 을 확인하십시오.** 산출물이 온전하면 재시작하지 말고,
코디네이터가 게이트를 독립 재확인한 뒤 `task-update --status completed` 로
정산하고 그 근거를 `--result` 에 남깁니다.

### 6.3 `ask` 에 답장만 하면 게이트가 막습니다

워커가 범위 확장을 요청해 `reply` 로 승인했는데 게이트 2 와 6 이 범위 초과로
실패했습니다. **승인은 Capsule 의 `allowed_write_files` 에도 반영해야 합니다.**
스킬 3.7 절이 "코디네이터가 추가 범위를 승인하거나 Task Capsule 을 갱신합니다"
라고 한 것은 둘 중 하나가 아니라 둘 다 하라는 뜻으로 읽어야 합니다.

이 저장소의 스킬은 `.agents` 가 원본이고 `.claude`·`.opencode` 가 사본인 3사본
구조입니다. 미러 정합성 검사를 통과하려면 세 파일을 모두 고쳐야 하므로 스킬을
건드리는 Task 의 쓰기 범위에는 셋을 다 넣으십시오.

### 6.4 중복 waiter 를 띄우지 마십시오

`orchestration check --wait` 를 배경으로 겹쳐 띄우면 두 번째부터
`waiter_exists` 로 실패합니다. Run 당 하나만 유지하고, 새로 띄우기 전에
기존 프로세스를 종료하십시오.

### 6.5 `orca_worker_watch.py` 의 실패 정체 신호는 자주 오탐입니다

커밋 0 인 워커에 대해 이전 세션의 `worker_done` 상태를 읽어 "worker_done 완료
메시지에 reportPath 가 누락됨" 을 반복해서 냅니다. 이 세션에서 네 번 겪었고
전부 정상 작업 중이었습니다. **터미널을 직접 읽어 확인하십시오.**

### 6.6 X4 워커가 `worker_done.json` 을 쓰지 않았습니다

`task_7f0659b4d4fc` 의 빌더(grok-4.6)가 `worker_done` CLI 메시지는 보냈으나
`ORCA_WORKER_DONE_V2` 보고 파일을 워크트리에 쓰지 않았습니다. 그래서 Level 1
게이트 6 이 "worker_done 보고 파일 없음" 으로 실패합니다. 게이트 1~5 는
통과했고 커밋 `902a046` 자체는 온전합니다.

**코디네이터가 그 파일을 대신 작성하면 안 됩니다.** 워커 산출물의 진실성을
검증하는 파일을 검증자가 만들면 게이트 6 의 의미가 사라집니다.

두 가지 방법이 있습니다.

| 방법 | 내용 |
| --- | --- |
| 재작업 Task | `taskctl rework` 로 보고 작성만 요구하는 Task 를 만들어 같은 워크트리에 워커를 다시 붙입니다. 이력이 남고 계약이 지켜집니다 |
| 게이트 우회 | 하지 마십시오. 이 세션은 게이트 실패를 우회한 적이 없습니다 |

이 결함은 grok 빌더의 계약 준수 문제입니다. Antigravity 워커는 보고 파일은
쓰고 수명주기 메시지를 빠뜨리는 반대 양상이었습니다(6.2 절). **두 CLI 모두
`worker_done` 을 온전히 수행하지 않으므로 기동 시 고지문에 파일 작성과 메시지
전송을 각각 명시하고, 완료 후 둘 다 확인하십시오.**

---

---

## 7. 워커 모델 상태

| 풀 | 상태 |
| --- | --- |
| Antigravity Gemini | **소진.** 5시간 할당량이 12% 에서 0 이 됐고 V1 빌더가 그것 때문에 죽었습니다 |
| `qwen3.7-plus` | **소진.** 2026-09-06 08:13 UTC 리셋 |
| `grok-4.6` | **가용.** 이 세션에서 리뷰어 8대와 빌더 3대를 완주시켰습니다 |
| Codex `gpt-5.6-terra` | **가용.** X2 리뷰어로 감독 경로 기동 확인 |
| `or-free/minimax-m3` | probe 가용하나 라우터가 `investigator` 전용으로 못박음. 쓰기 과제 금지 |

**현재 배정은 빌더 `grok-4.6`, 리뷰어 Codex `gpt-5.6-terra` 입니다.** Gemini 가
돌아오면 리뷰어를 Gemini 로 되돌리고 Codex 는 코디네이터 풀로 돌려놓는 것이
스킬 3.1 의 원칙에 맞습니다.

Codex 리뷰어는 `worker-start --agent codex --model gpt-5.6-terra` 로 띄웁니다.
**이 경로는 감독 경로라 `worker-release` 가 실제로 터미널을 닫습니다.** grok
수동 경로는 항상 `retained` / `no_owned_resource` 로 돌아와 손으로 닫아야 했습니다.

### 7.1 grok 빌더의 `--always-approve`

[`agent_worker_launch_reference.md`](agent_worker_launch_reference.md) 1.7 절은
`--always-approve` 를 읽기 전용 리뷰어에만 쓰라고 적었습니다. 이 세션에서는
빌더에도 썼습니다. 승인 대기로 멈추면 왕복 비용이 크고, 격리 워크트리에 Capsule
쓰기 범위가 걸려 있어 위험이 제한된다고 판단했습니다. **의도적 이탈이며 다음
코디네이터가 다시 판단하십시오.** 그 문서의 문구도 함께 갱신 대상입니다.

---

## 8. 남은 항목

| ID | 내용 |
| --- | --- |
| R-02 | 정기 백업의 운영 컨테이너 배선. worker 환경변수에 `BACKUP_SCHEDULE_ENABLED` 와 `DB_HOST` 계열 부재, Dockerfile 에 mysql 클라이언트 부재를 실측 확인했습니다. **백업을 어디서 실행할지 운영 결정이 선행돼야 합니다** |
| R-05, D-05 | KB 정합성 모집단 불일치. Intent `x3_kb_population_probe.yaml` 준비됨 |
| R-07 | RPO/RTO 미정 |
| R-10 | 관측성 backend, SLO, 알람 미정. 운영 compose 가 `OTEL_ENABLED` 를 워커에 전달하지 않음 |
| R-12 | G2 Windows Docker 실기. `worker-start --on <saved-environment>` 로 원격 워커를 띄우는 경로가 열려 있습니다 |
| R-13 | RAG cold SQL 재측정 |
| R-14 | Servc 결측 하한율 집단 구간 품질, drift baseline |
| 신규 | `orca_worker_watch.py` 의 실패 정체 오탐(6.5 절) |

---

## 9. 정리 상태

Wave V 와 Wave W 의 워크트리·브랜치·터미널은 전부 회수했습니다.
**Wave X 는 진행 중이라 회수하지 않았습니다.** 워크트리 3개
(`wave-x-w2-catchup`, `wave-x-x4-swap`, `wave-x-x2-cleanup`)와 브랜치 3개가
살아 있고, W2 워커와 X2 리뷰어 터미널이 열려 있습니다. 미병합 브랜치와 활성
Dispatch 트리이므로 제거하지 마십시오.

Docker Desktop 은 이 세션에서 올렸고 내리지 않았습니다. compose 서비스는
올리지 않았습니다.

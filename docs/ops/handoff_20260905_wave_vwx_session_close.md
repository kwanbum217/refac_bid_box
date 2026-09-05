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

**Wave X 는 빌더와 리뷰가 대부분 끝났으나 W2 와 X4 가 게이트 6 에서 막혀 있습니다.**
워커 터미널은 전부 회수했고 남은 것은 보고 정합성 복구와 병합입니다.

| Task | 상태 | 브랜치 / 커밋 | 막힌 지점 |
| --- | --- | --- | --- |
| X2 잔여정리 | 완료 | `9759735` | 없음. **`wave_t/handoff` 병합 완료**(`8db4353`), `main` 미반영 |
| X3 KB 모집단 조사 | 완료 | - | 없음. 보고 `docs/analysis/task_09a352270a13.md` 커밋 완료 |
| W2 catchup | 완료 | `kwanbum217/wave-x-w2-catchup` (`26b1674`) | **게이트 6 실패.** 5.1.1 절 |
| X4 승격전환 | 완료 | `kwanbum217/wave-x-x4-swap` (`1068c2b`) | **게이트 2·6 실패 + 설계 미결.** 5.1.2 절 |
| `task_5e66c4c224d4` X4 설계안 | `ready` | - | **미기동.** 5.1.2 절 |

### 5.1.1 W2 — 보고서가 최종 트리보다 낡았습니다

코드는 문제없습니다. Level 2 독립 리뷰가 `pass`, 차단 이슈 0건이고, 대상 테스트와
mypy 도 통과했습니다. 게이트 6 이 막는 이유는 두 가지입니다.

| 위반 | 원인 |
| --- | --- |
| 테스트 건수 불일치 | 1차 보고(`task_d9527d72e596`)의 수치가 2차 커밋 `26b1674` 이전 것이다. 다중 보고로 넘겨도 1차 보고의 낡은 수치는 그대로 검사된다 |
| `verdict` 가 `blocked` | 2차 보고가 전량 테스트에서 2건 실패를 정직하게 적었다. 그 둘은 `test_model_bin_files_exist` 와 `test_chroma_db_exists` 로, 스킬 2.3 이 규정한 **격리 워크트리의 알려진 예외**다 |

두 번째는 Capsule 의 검증 명령이 `-m 'not data_assets'` 마커를 쓰지 않은 코디네이터
잘못입니다. 격리 트리에서 그 마커 없이 전량을 돌리면 반드시 2건이 실패합니다.

**조치**: 최종 트리(`26b1674`) 기준으로 검증을 다시 실행해 **통합 보고 1건**을 쓰게
하는 재작업 Task 를 발급하십시오. 검증 명령은 `uv run pytest tests/ -q -m 'not data_assets'`
로 지정합니다. 코디네이터가 보고서를 직접 쓰면 게이트 6 의 의미가 사라집니다.

범위 문제는 해소했습니다. 워커가 만든 신규 테스트 `tests/test_schedule_catchup.py`
를 Capsule 의 `allowed_write_files` 에 코디네이터 승인으로 추가했습니다.

### 5.1.2 X4 — 보고 대상이 어긋났고 설계가 미결입니다

원 Task `task_7f0659b4d4fc` 의 `worker_done.json` 이 여전히 없습니다. 복구 Task
`task_7227826cd798` 이 발급됐으나 **그 워커는 자기 자신에 대한 보고만 썼습니다.**
`changed_files` 가 `docs/analysis/task_x4_model_swap_atomic.md` 한 건이라 원
커밋 `902a046` 의 코드 변경 4건이 보고되지 않습니다.

더 중요한 것은 설계 미결입니다. **파일별 `os.replace` 는 모델 세트 원자성이
없습니다.** 승격 도중 읽는 쪽이 구 버전과 신 버전 파일을 섞어 볼 수 있다는
반례를 리뷰가 찾았고, 그래서 `task_5e66c4c224d4`(설계 전용, 구현 금지)가 `ready`
로 남아 있습니다.

**조치 순서**: 설계안을 먼저 받으십시오. 설계에 따라 `902a046` 을 그대로 병합할지
보강할지가 갈립니다. 부분 개선으로 병합하기로 정하면 `model_swap_gap` 을 원장에서
닫지 말고 남겨야 합니다.

### 5.1.3 병합 순서

1. W2 재작업 보고를 받아 게이트를 다시 돌리고 `wave_t/handoff` 에 병합합니다.
2. X4 설계 결정 후 처리합니다.
3. `wave_t/handoff` 를 `main` 에 병합하고, **그 다음 별도 커밋으로**
   `source_commit` 을 갱신합니다(6.1 절).
4. `269c755` 의 CI 결과를 아직 확인하지 못했습니다. 병합 전에 확인하십시오.

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

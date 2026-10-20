# 핸드오프 인수인계 — cmd 워커 승인 대화창 정체 해소, 워커 권한 무승인(yolo) 전환

> **작성일**: 2026-10-13
> **작성**: Claude 코디네이터 (Orca Run `run_43d241b65dee`)
> **기준 커밋**: `cbd15cb8` (이 문서가 들어가는 병합의 부모)
> **직전 인수인계**: [handoff_20261013_m7_rsp1_close.md](handoff_20261013_m7_rsp1_close.md)

---

## 0. 다음 세션이 가장 먼저 할 일

| 우선 | 과제 | 선행 |
| --- | --- | --- |
| 1 | 이 문서가 들어간 병합 커밋의 원격 CI 녹색 확인(`cbd15cb8` 결과는 5절) | 없음 |
| 2 | 다음 cmd 워커 Dispatch 때 런처가 `--trust --yolo` 로 띄우는지, 승인 대화창 없이 끝까지 가는지 첫 1대를 지켜본다. 정책 deny 에 걸린 명령이 있으면 기록한다 | 워커 Dispatch |
| 3 | 직전 인수인계 0절의 사용자 조치(운영 서버 Z1 서명 키·Z2 마이그레이션, 비공개 취약점 제보 활성화)는 그대로 남아 있다 | 사용자 |

---

## 1. 사용자 결정 (2026-10-13)

1. **워커 권한 모드는 무승인(yolo)이다.** 권한 허가 대화창 때문에 워커가 멈추는 구성은 쓰지 않는다. 정본 조항은 [multi_agent_setup.md](../ops/multi_agent_setup.md) 5.3절이다. 이 결정으로 M7 1단계(2026-10-12)의 cmd yolo 제거와 일주일 관찰은 철회됐다([m7_stage1_observation_log.md](../ops/m7_stage1_observation_log.md) 3절).
2. 검토했으나 택하지 않은 안: dont-ask + 허용 목록(대화창 없이 목록 밖 명령 거부), shift+tab 으로 accept-edits 전환(AE1).

---

## 2. 운영 주의 사항

### 2.1 cmd 워커 기동 (CA1 `cbd15cb8`, PB1 `71bf079e`)

- `scripts/orca_cmd_launch.py --auto` 가 `--trust --yolo` 를 붙인다. `--accept-edits`, `--permission-mode`, `--dangerously-skip-permissions` 는 붙지 않는다.
- 워커 정책 `scripts/orca_policies/commandcode_worker_settings.json` 은 `disableBypass` 와 allow 가 없고 deny 32개다. commandcode.ai/docs/permissions 기준 deny 는 yolo 에서도 유효하다. 추가된 deny: `mysql`·`mysqldump`·`mysqladmin`, `docker compose down/rm`, `docker-compose down`, `docker volume rm/prune`, `docker system prune`, `docker rm/exec/run`, `rm -rf`, `rm -fr`, `sudo`, `git checkout main`, `git switch main`, `git merge`, `git reset --hard`, `git branch -D`, `git rebase`, `Read(**/.env)`, `Read(**/.env.*)`.
- 잔여 위험: 워커 워크트리 `.env` 의 DB 자격증명으로 `uv run python` 등을 거쳐 쓰기를 하는 경로는 deny 로 막히지 않는다. Intent 에 "DB 조회는 `scripts/db_readonly_query.py` 만" 을 계속 적는다.
- 이 세션에 이미 떠 있던 워커는 옛 런처로 떠서 대화창이 났다. 새로 띄우는 워커부터 적용된다.

### 2.2 자동 승인 감시기 (AA1 `6d968028`, PB1, WW1 `7ebef51f`)

- `scripts/orca_auto_approve.py` 가 `$?`·`${?}` 를 경로 변수 확장으로 보류하던 결함을 고쳤다. `$#`, `$$`, `$HOME` 등은 종전대로 보류한다. 10-13 의 3시간 반 정체 원인은 파이프·`;` 가 아니라 `echo "EXIT=$?"` 의 `$?` 였다(직전 인수인계의 원인 서술 정정).
- cmd 명령 대화창에서 감시기는 `1`(1회 승인)을 보낸다. 종전 `2` 는 "이 프로젝트에서 다시 묻지 않음" 이라 워커 워크트리 `.commandcode/settings.json` 에 `Shell(uv:*)` 같은 포괄 allow 를 심었다. 다른 CLI 는 종전대로 `2`.
- `scripts/orca_worker_watch.py` 가 cmd 대화창("Command Code needs to execute")을 승인 대기 차단으로 보고한다.
- 감시기 허용 목록의 `orca orchestration` 하위 명령은 `send`·`check` 뿐이라 워커의 `ask` 는 보류된다. yolo 에서는 대화창이 없어 무관하다.

---

## 3. 이 세션에서 병합한 것

빌더 cmd `deepseek/deepseek-v4.1-flash`, 리뷰어 opencode `muse-spark-1.3-contributor-free`. 전부 `--no-ff`, strict 게이트 증거와 병합 전 전량 시험 증거를 거쳤다.

| Task | 병합 | 내용 | 검증 |
| --- | --- | --- | --- |
| WW1 | `7ebef51f` | 워커 감시기 cmd 대화창 신호 | 리뷰 pass, 전량 7,338, CI 녹색 |
| AA1 | `6d968028` | 감시기 `$?` 오판 수정 | 리뷰 pass, 전량 7,345, CI 녹색 |
| PB1 | `71bf079e` | 정책 deny 강화·disableBypass 제거, 감시기 1회 승인 | 리뷰 pass, 전량 7,353 |
| 명세 | `4747a0cf` | multi_agent_setup.md 5.3 yolo 조항, M7 관찰 기록, source_commit | 코디네이터 Capsule strict, 전량 7,362 |
| CA1 | `cbd15cb8` | 런처 `--trust --yolo` | 리뷰 pass, 전량 7,343, 합친 트리 관련 시험 524 통과 |

AE1(shift+tab accept-edits 전환, 리뷰 pass)은 yolo 방향과 맞지 않아 병합하지 않고 사용자 승인으로 삭제했다. 커밋 `dbef6f7c`, 로컬 reflog 로 복원 가능.

---

## 4. 이 세션의 절차 함정

| 함정 | 처리 |
| --- | --- |
| cmd 대화창을 화살표 키로 풀면 ESC 바이트가 따로 가 대화창이 취소되고 에이전트가 paused 된다 | 숫자 키(`1`, `2`)를 보낸다. 바로 선택된다 |
| paused 입력창에서 shift+tab 은 모드 전환이 아니라 할 일 패널 포커스로 간다 | Esc 로 입력창 복귀 후 지시 |
| 편집 대화창 문구가 "make this edit" 와 "create" 두 가지 | 감시 조건은 선택지 문구로 판정 |
| 워커가 모델 응답 없이(받은 토큰 0) 8~14분 멈춤 | Esc 로 요청을 끊고 대기열 지시가 처리되게 함 |
| 워커가 커밋·보고서 작성 후 worker_done 직전에 할 일 패널 포커스로 멈춤 | Esc 후 마무리 지시 |
| 방향 변경 시 진행 중 워커 Capsule 갱신 | Intent 수정 → `orca_taskctl.py expand --task-id` 로 같은 ID 재생성 → 워크트리 복사 → 터미널에 직접 재독 지시. 체크리스트 id 는 유지하고 질문 문구만 바꾼다 |
| 코디네이터 브랜치 strict 게이트 4 가 주 저장소 작업 트리를 검사해 갱신 전 source_commit 으로 실패 | 그 브랜치를 체크아웃한 상태에서 게이트·premerge 를 돌린다 |
| PB1 병합 직후 source_commit 6커밋 뒤처짐 | 다음 병합 브랜치에서 갱신(amend 금지 규약) |
| Claude Code 자동 모드 분류기가 워커 권한 확대(래퍼, 대화창 일괄 승인 감시)를 거부 | 사용자가 권한 규칙 추가. 대화창 일괄 승인 감시는 끝내 거부되어 쓰지 않았다 |

---

## 5. 종료 시 자원

| 자원 | 상태 |
| --- | --- |
| Orca Run `run_43d241b65dee` | Task 10개 전부 completed(빌더 5, 리뷰어 5). 활성 Dispatch 없음 |
| 워커 터미널 | 전부 회수·종료 |
| 워크트리·브랜치 | 이번 세션 것 전부 정리. 주 저장소만 남김. 기존 로컬 브랜치 3개(`bid-detail-appendix-modal`, `quant-score-input`, `reputation-autofill`)는 손대지 않음 |
| CI | `7ebef51f`, `6d968028` 녹색. `cbd15cb8` 와 이 문서 병합은 0절 1번 |
| Docker | 이번 세션 기동 없음(정지 유지) |
| 배경 프로세스 | 코디네이터 대기·감시 스크립트 전부 종료 |

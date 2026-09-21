# 세션 인수인계: 2026-09-20 G3 오프로드 웨이브 (검증 완료, 병합 대기)

> **작성일**: 2026-09-20
> **작성자**: Claude Opus 5 (Orca 코디네이터)
> **기준 커밋**: `main` `b4d90c7d`
> **Orca Run**: `run_c30fdfb4a808`
> **이어받은 문서**: [`session_20260920c_cmd_builder_and_g3.md`](session_20260920c_cmd_builder_and_g3.md)

---

## 1. 한 줄 요약

쓰기 경로 조사의 D7·D8·D9 세 건을 Command Code DeepSeek V4.1 Flash 워커로 병렬 구현해 **Level 1 게이트까지 전부 통과**시켰고, 코디네이터 사용량 한도 때문에 **독립 리뷰와 병합은 다음 세션으로 넘깁니다.**

---

## 2. 병합 대기 브랜치 (작업은 끝났습니다)

| 브랜치 | 커밋 | 내용 | Level 1 | 전량 테스트 |
| --- | --- | --- | :---: | --- |
| `kwanbum217/orca-d7` | `ce4b080a` | 수집 스텝 오류 분기의 동기 COUNT 를 스레드로 오프로드 (D7) | pass | 5,195 |
| `kwanbum217/orca-d8` | `9db0a46d` | 홈 최근 공고 선별의 표본·윈도 이중 순회 질의를 고정 질의로 (D8) | pass | 5,207 |
| `kwanbum217/orca-d9` | `7892ae8c` | 워커 heartbeat·스케줄 결과 기록의 동기 Redis 를 스레드로 오프로드 (D9) | pass | 5,198 |

세 브랜치의 워크트리는 `/Users/kwanbum/orca/workspaces/refac_bid_box/orca-d7|d8|d9` 에 그대로 있습니다. **병합 전에는 지우지 마십시오.** 유일본입니다.

---

## 3. 다음 세션이 해야 할 일 (순서 고정)

1. **독립 리뷰(Level 2)를 세 건에 붙입니다.** 빌더가 `cmd` 계열이므로 리뷰어는 `opencode/muse-spark-1.3-contributor-free` 이고, 리뷰 Capsule 에 `builder_provider: "cmd"` 를 직접 적어야 배정이 통과합니다.
2. 리뷰 통과 건부터 워커 브랜치에 `main` 을 먼저 반영하고, 그 워크트리에서 `premerge_full_suite_gate.py --record` 를 돌린 뒤 `main` 에 `--no-ff` 로 병합합니다. **병합만 직렬입니다.**
3. 병합 후 워크트리와 브랜치를 정리하고 `gh run list --branch main` 으로 CI 를 확인합니다.
4. `CURRENT_STATE.md` 의 `source_commit` 이 5커밋 넘게 뒤처지지 않도록 병합 묶음 중간에 갱신합니다. 이번 세션에서 이 항목으로 CI 가 두 번 실패했습니다.

Task ID 는 D7 재작업 `task_4cb6a146c685`, D8 `task_640f791eeef1`, D9 `task_771c47314975` 이며 전부 `completed` 이고 워커 터미널은 회수했습니다.

---

## 4. 이번 세션에서 드러난 사실

| 사실 | 근거 | 조치 |
| --- | --- | --- |
| **`worker_done` 의 검증 명령에 설명을 덧붙이면 게이트 6 이 실패한다** | D7 이 `uv run pytest ... -q (asyncio.to_thread 제거 음성 대조군)` 로 적어 게이트가 그 문자열을 실행하다 exit 4 | `command` 에는 실행 가능한 명령만, 설명은 본문에. Capsule 에 못 박을 것 |
| 반려는 `taskctl rework` 로 새 Task 를 발급한다 | 완료 Task 에 2차 보고를 태우면 거부된다 | `rework --reason` 에 실패 원인과 고칠 범위를 적어 새 `report_path` 와 함께 준다 |
| 보고서 형식 결함에는 낮은 등급이면 충분하다 | D7 재작업을 `--effort default` 로 돌려 한 번에 통과 | 과업 성격에 맞춰 등급을 따로 고를 것 |
| 판정 규칙을 재현해야 하는 구현은 `max` 가 맞다 | D8 은 선별 알고리즘 동일성 증명이 필요해 `max` 로 배정했고 결과 동일성 테스트까지 붙여 왔다 | 규칙값(medium→high)을 기계적으로 쓰지 말 것 |
| `orca worktree create` 직후 바로 Dispatch 하면 기동 직전 상태가 남을 수 있다 | D8 1차 기동 터미널이 슬래시 명령 목록만 띄운 채 유휴였다 | `worker-abandon` 으로 펜싱하고 Task 를 `ready` 로 되돌린 뒤 재기동 |

---

## 5. 착수하지 않은 것과 이유

| 후보 | 이유 |
| --- | --- |
| D4 (수집 카테고리 루프 COUNT), D5 (랭킹 스냅샷 조합별 commit) | 조사 보고서가 **실측 후 착수**로 규정했습니다. 실측은 Docker·DB 점유와 조용한 저장소가 필요해 병렬 작업과 충돌합니다 |
| D6 (수집 예외 경로 세션 연산) | D4 와 같은 파일(`collector_service.py`)이라 D4 와 함께 한 워커가 맡아야 합니다 |
| 이번 6건의 레이턴시 실측 | 저장소가 조용해야 하고 Docker 기동이 필요합니다 |

---

## 6. 자원 상태

| 대상 | 상태 |
| --- | --- |
| Git | 주 저장소 `main` `b4d90c7d`, 원격 반영 완료. **미병합 작업 브랜치 3개**(2장) |
| 워크트리 | `orca-d7`, `orca-d8`, `orca-d9` 유지. 병합 전 제거 금지 |
| Orca Run | `run_c30fdfb4a808`. 이번 웨이브 Task 전부 `completed`, 워커 터미널 전부 회수 |
| Docker | 이번 세션에서 기동하지 않았습니다 |
| 배경 프로세스 | 워커 감시기·자동 승인기 종료 |

---

## 7. 하지 말 것

- **세 건의 레이턴시 개선 폭을 숫자로 인용하지 마십시오.** 질의 수 감소와 오프로드 사실만 증명됐습니다.
- 리뷰 없이 병합하지 마십시오. Level 1 만 통과한 상태입니다.
- `orca-d7|d8|d9` 워크트리와 브랜치를 병합 전에 지우지 마십시오.
- cmd 워커를 `--auto` 없이 띄우지 마십시오.

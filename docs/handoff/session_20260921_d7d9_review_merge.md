# 세션 인수인계: 2026-09-21 D7~D9 독립 리뷰와 병합

> **작성일**: 2026-09-21
> **작성자**: Claude Opus 5 (Orca 코디네이터)
> **기준 커밋**: `main` `3163b2d6`
> **Orca Run**: `run_c30fdfb4a808`
> **이어받은 문서**: [`session_20260920d_g3_offload_wave.md`](session_20260920d_g3_offload_wave.md)

---

## 1. 한 줄 요약

전 세션이 남긴 D7·D8·D9 세 브랜치에 Muse Spark 1.3 리뷰어를 병렬로 붙여 **세 건 모두 `pass`(차단 결함 0건)** 를 받고, Level 1 게이트 11/11 과 코디네이터 diff 검토를 거쳐 **`main` 에 전부 병합**했습니다. 워크트리와 브랜치, 리뷰어 터미널까지 회수를 마쳤습니다.

---

## 2. 병합 결과

| 병합 커밋 | 내용 | 리뷰 판정 | Level 1 | 병합 시점 전량 테스트 |
| --- | --- | :---: | :---: | --- |
| `c0f8e558` | D7 수집 스텝 오류 분기의 동기 COUNT 를 스레드로 오프로드 | pass | 11/11 | 5,195 |
| `de1fa8b4` | D8 홈 최근 공고 선별의 표본·윈도 이중 순회 질의를 고정 질의로 | pass | 11/11 | 5,209 |
| `3163b2d6` | D9 워커 heartbeat·스케줄 결과 기록의 동기 Redis 를 스레드로 오프로드 + `source_commit` 갱신 | pass | 11/11 | 5,214 |

전량 테스트 수치는 각 워크트리에서 `premerge_full_suite_gate.py --record` 로 `MERGE_HEAD` 기준으로 기록한 값입니다. 세 건이 누적된 마지막 트리에서 5,214건이 통과해 **상호작용 회귀가 없음도 확인**됐습니다.

`docs/context/CURRENT_STATE.md` 의 `source_commit` 은 `487e1e25` 에서 `de1fa8b4` 로 갱신해 D9 병합 묶음에 함께 넣었습니다. 갱신 전 기준으로 main 은 17커밋 뒤처져 허용치(5)를 넘긴 상태였습니다.

---

## 3. 리뷰어 구성

| 항목 | 값 |
| --- | --- |
| 빌더 (전 세션) | Command Code `deepseek/deepseek-v4.1-flash` |
| 리뷰어 (이 세션) | OpenCode `opencode/muse-spark-1.3-contributor-free`, 화면 표기 `Muse Spark 1.3 Free · xhigh` |
| 기동 경로 | `orca terminal create` -> `orca_taskctl.py prepare-worker` -> `orca_taskctl.py dispatch --terminal` (비감독 경로) |
| 리뷰 Task | D7 `task_fe2d492f5009`, D8 `task_6e84d79a9560`, D9 `task_93218ccd1512` |

**비감독 경로를 선택했습니다.** OpenCode 는 `worker-start --model` 을 거부하므로 터미널 경로가 정본입니다. 그래서 `worker-release` 가 세 건 모두 `retained reason=no_owned_resource` 로 돌아왔고 `orca terminal close` 로 창 단위 종료했습니다.

---

## 4. 코디네이터가 직접 확인한 지점 (Level 3)

| 지점 | 판정 근거 |
| --- | --- |
| **D7 은 세션이 스레드 경계를 넘습니다** | 리뷰어가 이 사실을 정확히 보고했습니다. 호출자 `run_automation_pipeline` 이 만든 지역 세션을 스텝에 순차로 넘기고 `_step_collect` 는 `await` 로 정지하므로 그 세션을 동시에 쓰는 코루틴이 없습니다. MySQL 드라이버라 스레드 친화 제약도 없어 수용했습니다 |
| **D8 의 선별 동일성** | 정렬 첫 키가 `collected_at DESC` 이고 윈도 조건이 `collected_at >= window_start` 이므로 필터 집합이 내림차순의 접두입니다. 따라서 최대 표본 1000행을 한 번 읽어 메모리에서 자르는 것이 윈도별 질의의 상위 N행과 같습니다 |
| **D8 의 NULL 위험 부재** | 메모리 비교 `row.collected_at >= window_start` 는 NULL 이면 TypeError 입니다. `BidAnnouncement.collected_at` 이 `nullable=False` 임을 모델에서 확인했습니다. 리뷰 체크리스트가 묻지 않은 항목입니다 |
| **D9 의 실패 전파 정책** | `record_worker_heartbeat` 와 `record_schedule_result` 본문이 무변경이고 내부에서 예외를 삼키며, 감싼 호출 주변 `try/except` 구조가 그대로입니다 |

---

## 5. 이번 세션에서 드러난 사실

| 사실 | 근거 | 조치 |
| --- | --- | --- |
| **리뷰어 3대가 모두 보고서를 `review_done.json` 이 아니라 `worker_done.json` 으로 썼다** | Capsule 의 `report_path` 는 `review_done.json` 인데 세 워크트리 모두 `worker_done.json` 만 생성. 스키마와 내용은 `ORCA_REVIEW_DONE_V2` 로 정확 | 정식 경로로 복사해 게이트 5 를 통과시켰습니다. Capsule `ground_truth` 에 **파일명을 그대로 쓰라는 문장**을 넣어야 합니다 |
| **`orca orchestration check --types review_done` 은 거부된다** | `invalid_argument: Invalid --types: review_done` | 리뷰 완료 통보도 `worker_done` 타입으로 옵니다. 대기는 `worker_done` 또는 보고서 파일 관찰 조건으로 겁니다 |
| **Level 1 게이트 3 은 `--tests` 만 주면 `backend_mypy` 미충족으로 skipped 가 된다** | D9 1차 실행에서 `blocking_skipped: ["게이트 3 테스트"]`, `--strict` 라 verdict fail | `--verify "uv run mypy src"` 를 함께 줘야 11/11 이 됩니다 |
| **`orca_taskctl.py create --task-id` 는 Capsule 디렉터리 이름만 정하고 Task ID 는 Orca 가 새로 발급한다** | `--task-id task_d7_review_20260921` 을 줬는데 실제 ID 는 `task_fe2d492f5009`, Capsule 이 두 디렉터리에 생성됨 | 두 사본의 내용을 동일하게 맞추고 `report_path` 를 실제 ID 로 통일했습니다. 그대로 두면 `required_change` 와 `report_path` 가 어긋납니다 |
| **zsh 는 따옴표 없는 변수를 단어 분리하지 않는다** | 쌍 목록을 문자열 변수에 담아 `for` 를 돌렸더니 한 단어로 취급돼 D7 Capsule 에 D9 의 Task ID 가 들어갔다 | 기동 전에 발견해 파이썬으로 재작성했습니다. 셸 루프로 여러 Capsule 을 일괄 편집하지 마십시오 |

---

## 6. 착수하지 않은 것과 이유

| 후보 | 이유 |
| --- | --- |
| D4 (수집 카테고리 루프 COUNT), D5 (랭킹 스냅샷 조합별 commit), D6 (수집 예외 경로 세션 연산) | 조사 보고서가 **실측 후 착수**로 규정했고, 실측은 Docker·DB 점유와 조용한 저장소를 요구해 이번 병렬 리뷰와 충돌합니다. D6 은 D4 와 같은 파일(`collector_service.py`)이라 한 워커가 함께 맡아야 합니다 |
| 이번 6건의 레이턴시 실측 | 저장소가 조용해야 하고 Docker 기동이 필요합니다. 병합이 끝난 지금은 조건이 갖춰졌습니다 |

**다음 착수 후보는 지금까지 병합한 6건(D1·D2·D7·D8·D9 계열)의 레이턴시 실측입니다.** 저장소가 조용하고 미병합 브랜치가 없는 상태라 측정 조건이 처음으로 성립합니다.

---

## 7. 자원 상태

| 대상 | 상태 |
| --- | --- |
| Git | 주 저장소 `main` `3163b2d6`, 원격 반영 완료. **미병합 작업 브랜치 없음** |
| 워크트리 | `orca-d7`, `orca-d8`, `orca-d9` **제거 완료**. 브랜치도 `-d` 로 삭제 |
| Orca Run | `run_c30fdfb4a808`. 리뷰 Task 3건 전부 `completed`, 배달 큐 비움 |
| 리뷰어 터미널 | 3개 전부 release 후 `terminal close`. `orca_settled_session_audit.py` 잔류 0건 |
| Docker | 이번 세션에서 기동하지 않았습니다 |
| 배경 프로세스 | 자동 승인 감시기 3개 중지 완료. 상시 워커 감시기는 대상 소멸 |

---

## 8. 하지 말 것

- **세 건의 레이턴시 개선 폭을 숫자로 인용하지 마십시오.** 질의 수 감소와 오프로드 사실만 증명됐고 실측은 아직 없습니다.
- 리뷰 Capsule 을 셸 루프로 일괄 편집하지 마십시오(5장).
- Level 1 게이트를 `--tests` 만으로 돌리고 통과라고 보고하지 마십시오. `backend_mypy` 가 빠집니다.

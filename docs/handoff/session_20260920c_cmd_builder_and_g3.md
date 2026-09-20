# 세션 인수인계: 2026-09-20 Command Code 빌더 전환과 G3 4건

> **작성일**: 2026-09-20
> **작성자**: Claude Opus 5 (Orca 코디네이터)
> **기준 커밋**: `main` `06526b7b`
> **Orca Run**: `run_c30fdfb4a808`
> **이어받은 문서**: [`session_20260920b_read_path_optimization.md`](session_20260920b_read_path_optimization.md)

---

## 1. 한 줄 요약

Gemini 사용 중단에 따라 빌더 기본 모델을 Command Code(cmd) CLI 의 DeepSeek V4.1 Flash 로 교체해 등록하고, 그 워커로 G3 과업 4건을 병렬 수행해 전부 병합했습니다. 도중 워커가 승인 대화창에서 반복해 멈춘 원인 다섯 가지를 감시기에서 닫았습니다.

---

## 2. 이번 세션 병합

| 커밋 | 내용 | 검증 |
| --- | --- | --- |
| `28fdd9db` | Command Code DeepSeek V4.1 Flash 빌더 기본값 등록 | 전량 5,168, 규칙 21/21 |
| `5e701fbd` | Command Code 승인 대화창 탐지·줄바꿈·히어독·pwd·check 허용 | 자동 승인 467건 |
| `5a314558` | `git check-ignore` 허용, `.commandcode/` gitignore | 자동 승인 463건 |
| `e46c5baa` | 히어독 개행 보존 | 자동 승인 474건 |
| `2e6cd87c` | 예측 도구 기관·재발주 이력 조회 호출 범위 재사용 (q2) | Level 1 pass, 리뷰 pass, 전량 5,175 |
| `000d8869` | 정형 통계 루프 집계 일괄화 (q1) | Level 1 pass, 리뷰 pass, 전량 5,187 |
| `2813b94f` | 쓰기·수집 경로 정적 전수 조사 보고서 (q3) | Level 1 pass, 리뷰 pass |
| `11211aa5` | CURRENT_STATE `source_commit` 갱신 | 규칙 21/21 |
| `06526b7b` | 스케줄 claim·catchup·드리프트 계산 오프로드 (D2·D3) | Level 1 pass, 리뷰 pass, 전량 5,191 |
| `487e1e25` | 요약 재집계 태스크 오프로드 (D1) | Level 1 pass, 리뷰 pass, 전량 5,189 |

**효과 크기는 아직 주장할 수 없습니다.** 질의 수 감소와 오프로드 사실만 테스트로 증명했고 레이턴시 실측은 없습니다.

---

## 3. 빌더 모델 교체 (WORKER_MODEL_NOTICE)

| 항목 | 내용 |
| --- | --- |
| 기본 빌더 | `deepseek/deepseek-v4.1-flash` (Command Code CLI, 풀 키 `cmd-deepseek-flash`) |
| 추론 등급 | `--effort` 플래그. `default`, `low`, `high`, `max` 네 가지이며 `medium` 은 없다 |
| 위험도 대응 | low -> `default`, medium -> `high`, high -> `max` (`effort_by_risk`) |
| 기동 | `scripts/orca_cmd_launch.py --model deepseek/deepseek-v4.1-flash --effort <등급> --auto` |
| 리뷰어 | `opencode/muse-spark-1.3-contributor-free` (사용자 지시, 계열 분리) |

`TIER_POLICY` 의 builder 세 위험도가 전부 이 모델을 1순위로 둡니다. 리뷰어 Capsule 에는 `builder_provider: "cmd"` 를 직접 적어야 합니다. Intent 에 적어도 `expand` 가 옮기지 않습니다.

---

## 4. 워커 정체 원인 다섯 가지와 조치

감시기가 Command Code 대화창을 다루지 못해 워커가 반복해서 멈췄습니다. 전부 닫았습니다.

| 원인 | 증상 | 조치 |
| --- | --- | --- |
| 대화창 형식 미탐지 | `Command Code needs to execute ...` 가 확인 문구 목록에 없다 | 전용 추출 경로 추가 |
| 화면 줄바꿈 | 접힌 뒷부분이 별도 명령으로 판정돼 안전한 pytest·git add 가 보류 | 한 줄로 되돌림 |
| 커밋 히어독 | `git commit -F - <<'EOF'` 보류로 커밋마다 정지 | 따옴표 구분자는 승인 |
| 스테이징 동반 커밋 | `git add ... && git commit -F - <<'EOF'` 가 첫 줄 판정에서 탈락 | 앞 구간을 따로 판정 |
| 읽기 전용 명령 누락 | `pwd`, `git check-ignore`, `git -c core.pager=cat`, `orca orchestration check` 보류 | 이름으로 지정해 허용 |

**가장 확실한 예방은 런처의 `--auto` 입니다.** 이제 `--trust --yolo` 로 기동해 대화창 자체가 뜨지 않습니다. `--auto` 없이 띄운 워커는 위 감시기에 의존합니다.

---

## 5. 이번 세션에서 드러난 사실

| 사실 | 근거 | 조치 |
| --- | --- | --- |
| `orca orchestration run-create` 는 `--title` 이 아니라 `--objective` 를 받는다 | `invalid_argument: Unknown flag --title` | `--objective` 사용 |
| `taskctl dispatch` 는 Task 를 만들지 않는다 | `Task not found: task_<intent 파일명>` | `create` 로 먼저 만들고 `--task-id` 와 `--capsule` 을 넘긴다 |
| `create` 를 두 번 부르면 Task 가 두 개 생긴다 | `task-list` 에 같은 spec 두 건 | 중복은 `task-update --status failed` 로 닫는다 |
| 리뷰어 자동 배정은 빌더 provider 없이는 medium 이상에서 거부된다 | `빌더 provider 를 알 수 없어 독립성을 보장할 수 없습니다` | 리뷰 Capsule 에 `builder_provider` 를 적는다 |
| 워커가 `worker_done.json` 을 spec Capsule 디렉터리에 쓰는 경우가 있다 | q1 이 `task_q1_...` 아래에 썼다 | 게이트에 `--report` 로 실제 경로를 준다 |
| `source_commit` 뒤처짐이 CI 를 막는다 | 9커밋 뒤처져 `lint-and-validate` 실패 2회 | 병합이 5건을 넘기 전에 갱신한다 |
| Command Code 가 `.commandcode/` 를 저장소에 남긴다 | 워크트리마다 미추적 디렉터리 | gitignore 처리 완료 |

---

## 6. 자원 상태

| 대상 | 상태 |
| --- | --- |
| Git | 주 저장소 `main` `06526b7b`, 원격 반영 완료. 워커 워크트리·작업 브랜치 전부 정리 |
| Orca Run | `run_c30fdfb4a808` Task 전부 `completed`. 잔류 세션 없음 |
| Docker | 이번 세션에서 기동하지 않았다 |
| 배경 프로세스 | 워커 감시기·자동 승인기 종료 |

---

## 7. 다음 세션이 확인할 과업

| 시점 | 과업 | 확인 방법 |
| --- | --- | --- |
| 즉시 | `06526b7b` CI | `gh run list --branch main` |
| 스택 기동 후 | 이번 6건의 레이턴시 실측 | 저장소가 조용할 때 수정 전후를 교대로 띄워 잰다 |
| 원할 때 | 쓰기 경로 잔여 후보 | [`write_path_g3_scan_20260920.md`](../analysis/write_path_g3_scan_20260920.md) D4~D9 |
| 원할 때 | 읽기 경로 잔여 후보 | [`read_path_g3_rescan_20260920.md`](../analysis/read_path_g3_rescan_20260920.md) 6순위는 병합 완료, 나머지 없음 |
| 2026-09-21 03:00 이후 | 첫 주간 재학습. 자동 승격 없는지 | [`weekly_retrain_prep_20260920.md`](../analysis/weekly_retrain_prep_20260920.md) |
| 장비 확보 시 | Windows Docker Desktop 실기 | G2 보류 |

---

## 8. 하지 말 것

- **이번 여섯 변경의 레이턴시 개선 폭을 숫자로 인용하지 마십시오.** 질의 수와 오프로드만 증명됐습니다.
- cmd 워커를 `--auto` 없이 띄우지 마십시오. 승인 대화창마다 감시기에 의존하게 됩니다.
- `premerge_full_suite_gate.py --record` 를 여러 워크트리에서 동시에 돌리지 마십시오.
- 리뷰어로 `grok-4.6` 을 먼저 시도하지 마십시오. 잔량이 없습니다.

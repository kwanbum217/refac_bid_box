# 핸드오프 인수인계 — cmd 무료 워커 전환, 인수인계 0절 병렬 처리, 리뷰어 독립성 계열 단위

> **작성일**: 2026-10-18
> **작성**: Claude 코디네이터 (Orca Run `run_8c1452a052ce`, `run_67bd1fa37412`, `run_c6227e3637f1`, `run_0fd5445da4c9`, `run_6b11e3b7f924`)
> **기준 커밋**: `2f21eef4` (이 문서가 들어가는 병합의 부모)
> **직전 인수인계**: [handoff_20261017_coverage_unblock_close.md](handoff_20261017_coverage_unblock_close.md)
> **상세**: 직전 인수인계 13절(13.1~13.8)에 Run 별 병합·리뷰·교훈을 적었다. 이 문서는 세션 진입점이다.

---

## 0. 다음 세션이 가장 먼저 할 일

| 우선 | 과제 | 선행 |
| --- | --- | --- |
| 1 | 이 문서 병합 커밋의 main CI 녹색 확인 | 없음 |
| 2 | 남은 계산 차단 중 `MANUAL_EVALUATION` 외 자동 차단 대응(직전 인수인계 11.3절) | 사용자 결정 |
| 3 | 띠 표기 `2억미만 1억이상` 처리 방식(직전 인수인계 10.2절 B1) | 사용자 결정 |
| 4 | ML 특징용 고시금액 2021~2022 년 값 정정 여부, 2027 년 고시금액 반영(2026-12 예정) | 사용자 결정·외부 대기 |
| 5 | 교육청 소속 공고 지역제한 금액 경계. 원문으로는 근거 부족, 유권해석 확보 시 재판정(13.2절) | 근거 확보 |
| 6 | 한국공항공사 별표 3·5·5의 2·8·9. 새 공고에서 표기가 나오면 재조사 | 외부 대기 |
| 7 | 비교 시험 로컬 브랜치 3개(`bench/builder-compare-base`, `kwanbum217/bench-catjam`, `kwanbum217/bench-glyph`) 삭제 여부. 병합 대상이 아니며 원격에 없다 | 사용자 결정 |

---

## 1. 세션 요약

cmd `deepseek/deepseek-v4.1-flash` 크레딧 소진으로 무료 빌더 후보 두 모델을 숨김 시험으로 비교했고(13.1절), 사용자가 빌더 cmd `stealth/cat-jam:free` max, 리뷰어 cmd `reflection/beam:free` max 로 확정했다. 이 조합으로 직전 인수인계 0절의 사용자 결정 없는 과제와 승인된 과제를 모두 처리했다.

| main 커밋 | 내용 | 직전 인수인계 |
| --- | --- | --- |
| `2be40d4f` | 광주광역시교육청 국제입찰 고시 대상 판정. 라벨 근거 부족, 교육청 소속 8건은 5억원 경계 유지 | 13.2절 |
| `620b02fc` | cmd 워커 정책 mysql·mysqldump 중간 와일드카드 12개(사용자 승인) | 13.2절 |
| `33a973a8` | OCR 시험 슬롯 반납 대기 fixture(간헐 실패) | 13.2절 |
| `b3899e52` | cmd 무료 풀 `cmd-cat-jam-free`·`cmd-beam-free`·`cmd-glyph-free` 등록 | 13.2절 |
| `723b60d0` | 런처 `EFFORT_CHOICES` 에 `xhigh`, 등급 시험 중복 정리 | 13.6절 |
| `413f4bba` | 리뷰어 명시 지정 독립성 검사를 모델 계열 단위로(사용자 결정) | 13.7절 |
| `d8c43d01` | 재작업 Capsule 에 worker_done 보고 작성 규칙 고정 | 13.8절 |

인수인계 문서 병합은 `58b03dcc`·`7a8628d7`·`5771ca74`·`2f21eef4` 다. 이 세션의 main 병합은 모두 CI 녹색이다.

---

## 2. 워커 풀 현재 상태

| 역할 | 모델 | 기동 |
| --- | --- | --- |
| 빌더 | cmd `stealth/cat-jam:free` `--effort max` | `deploy_worker_settings` 로 정책 배치 뒤 `cmd --model stealth/cat-jam:free --effort max --trust --yolo` TUI, `orca orchestration worker-start --task <id> --terminal <h> --worktree path:<wt>` |
| 리뷰어 | cmd `reflection/beam:free` `--effort max` | 같은 방식. 리뷰 Intent 에 `builder_model` 을 반드시 적는다(없으면 계열 미상으로 라우터가 거부) |
| 보조 | cmd `stealth/glyph-cluster:free` `--effort xhigh` | 하루 100회 요청 한도, 비교 시험에서 사양 위반. cat-jam 과 같은 stealth 계열이라 서로의 리뷰어가 될 수 없다 |

세 모델은 MODEL_POOL 에 등록돼 `scripts/orca_cmd_launch.py` 가 effort 를 받고 정책을 배치한다. 다만 이 세션은 위 직접 기동 경로만 실측했고 런처 경로(`taskctl dispatch`)로 기동하지는 않았다. 런처 경로를 처음 쓸 때는 Dispatch 직후 터미널 화면에서 모델명과 정책 배치를 확인한다.

---

## 3. 운영 교훈

| 항목 | 내용 |
| --- | --- |
| 회수 시점 | 감시 스크립트는 보고 파일 생성만 본다. `orca orchestration dispatch-show --task <id>` 가 completed 일 때만 `worker-release` 한다. 이를 어겨 리뷰 Task 하나가 failed 로 남았고 `task-update` 로 사유와 함께 정리했다 |
| Capsule 경로 | 워커 preamble 은 Intent 이름 경로(`task_<intent>`)를, rework 워커는 `task_<원 Task>_rework` 를 읽는다. 두 경로 모두에 사본을 둔다 |
| 보고 작성 규칙 | rework 빌더 두 건이 changed_files 를 자기 커밋 기준으로 적어 게이트 6 이 실패했다. `d8c43d01` 로 rework Capsule 에 규칙이 자동으로 들어간다. 새 Intent 에도 같은 문장을 ground_truth 에 둔다 |
| 병합 증거 | 전량 시험 증거와 Level 1 strict 증거는 각각 파일 하나라 다음 기록이 덮어쓴다. 브랜치마다 기록, 병합, 푸시, CI 확인을 끝내고 다음으로 넘어간다. `git merge -F -` 는 표준 입력을 받지 않는다 |
| 리뷰가 잡은 것 | 근거 없는 원인 주장(cause_unverified), 시험 부족, 쓰이지 않는 별칭 상수는 리뷰 또는 코디네이터 diff 검토에서 잡혀 재작업했다 |
| mysql deny 오탐 | 따옴표 바로 뒤 mysql, `sh -c` 문자열 속 mysql 부분 문자열, `git commit -m 'mysql ...'` 도 막힐 수 있다. 워커가 이유 없이 막히면 이 규칙부터 본다 |

---

## 4. 종료 상태

| 항목 | 상태 |
| --- | --- |
| Run 5개 | Task 20건 모두 completed |
| 워커 터미널·워크트리 | 전부 회수·제거. 코디네이터 창만 남음 |
| Docker Compose | 이 세션에서 기동하지 않았고 실행 중인 컨테이너 없음 |
| 로컬 브랜치 | 비교 시험 브랜치 3개만 남김(0절 7번) |

# 핸드오프 인수인계 — 적격심사 사유 정정·기관축 설계 세션

> **작성일**: 2026-10-02
> **작성**: Hermes 코디네이터 (run_7e3d6efced97)
> **기준 커밋**: `0cd437f4` (main, origin 동기화)
> **세션 성격**: Orca 워커 5대 기동 → 게이트 4회 → 리뷰 2건 → 반려 1건 → 재작업 → 병합 2건.

---

## 1. 이번 세션에서 main 에 병합된 것

| 커밋 | 내용 | 게이트 |
| --- | --- | --- |
| `0bf1d954` | 미확인 사유 문구를 실제 사유로 정정, 4건 규칙 k·T 세대별 선언 | Level 1 10대 pass |
| `5be7685a` | PRE ATTACH_05 근거 인용 166행 → 164행 정정 | pre-commit 훅 5종 통과 |
| `0f7bd2da` | 제2023-53호 판 14건 B·k·T 복원 매핑 + 독립 검토 3건 | Level 1 10대 pass |
| `a527aaca` | 기관·지역 축 설계 문서 79줄 | Level 1 10대 pass |

병합 커밋은 `f3206028`(4파일, +333/-51)과 `0cd437f4`(1파일, +79)입니다.
전량 테스트는 5889 → 5890 passed 로 증가했고 최종적으로 5890 passed / 49 skipped / 3 deselected 입니다.

---

## 2. 리뷰어가 잡은 실제 결함 1건

리뷰어(`opencode/muse-spark-1.3-contributor-free`)가 `candidate` 판정을 냈습니다.
`src/app/services/evaluation_rules.py:117` 의 `PRE_20250901_ATTACH_05` 선언이 `_score_source('PRE', 166)` 을
쓰는데 **166행은 별표 4 폐기물처리**이고, 같은 어규먼트의 주석은 "별표3 SW 비대상"입니다.
정답은 `docs/analysis/servc_pre_rules_2025_2026_tables_20260929.md:164` 입니다.

**값(88, k 2/4)은 164행과 166행이 동일해 계산 영향이 없었습니다.** 문제는 코드가 사용자에게
노출하는 `score_table_source` 가 잘못된 근거 문서를 가리켰다는 점이며, Capsule 의 목적이
"선언한 모든 값에 근거 문서 경로와 행 번호를 남기는 것"이었으므로 고쳤습니다.
`tests/test_evaluation_rules_pre.py` 와 `tests/test_evaluations_api.py` 주석의 옛 사유 문구도 함께 정정했습니다.

**이 결함의 근원은 Capsule 이었습니다.** 최초 Capsule 의 ground_truth 가
`SERVC_QUAL_PRE_20250901_ATTACH_05` 를 별표 3 이라면서 166행을 적었고, 164가 별표 3 입니다.
원문 행 번호를 열어 보지 않고 문서에 적었기 때문입니다.

---

## 3. 남은 Task

### `task_c4b1c413d054` 계열 — 완료

미확인 사유 문구 정정, 4건 B·k·T 세대별 선언, 인용행 정정까지 모두 main 에 반영됐습니다.
`ATTACH_05` 의 k 는 `None` 으로 남긴 것이 정답입니다. 원문 별표 3 의 k 가 "2 또는 4" 로
고시금액 축을 가지므로 단일값 선언이 불가능합니다. 같은 "2 또는 4" 인 별표 1(학술연구)의
ATTACH_06·07 은 고시금액 축으로 rule_id 가 나뉘어 단일값을 선언했는데, 이 차이는 데이터 구조에서
필연적입니다.

### `task_dec7f0dc5660` — 설계 완료, 구현 미착수

기관·지역 축 설계를 `docs/design/servc_institution_axis_design_20261002.md` 에 남겼습니다.
**구현 Task 가 아직 없습니다.** 설계 문서 6절이 구현 전 확인 항목 6개를 열거했으니 그것부터 봐야 합니다.

| 항목 | 상태 |
| --- | --- |
| 공고 원자료의 기관·지역 코드 존재 여부 | 확인 필요 |
| 국가·지방 법령 식별 원천값 | 확인 필요 |
| `EvaluationRule` 을 DB에 저장하는지 상수만 쓰는지 | 확인 필요 |
| 기관/지역/공통 규칙 겹침 시 우선순위 | 미정 |
| `_save_snapshot_async` 까지 판정 문맥 전달 경로 | 확인 필요 |
| 스냅샷 컬럼 길이·인덱스·DDL 잠금 영향 | 확인 필요 |

**설계의 핵심 판단 두 가지**를 다음 세션이 그대로 받아야 합니다.
첫째, 축 추가 자체가 점수를 바꾸지 않습니다. 범위에 맞는 규칙이 기존과 다른
`lwlt_rate`·`base_rate`·`max_price_score`·`multiplier`·`pass_threshold` 를 가지며 선택될 때
결과가 달라집니다. 두번째, `_is_local_contract`(`src/app/api/v1/evaluations.py:638-642`)는
복수예가 변동 범위 선택용이지 규칙 레지스트리 매핑 기능이 아닙니다. 착각하면 엉뚱한 곳에
연결하게 됩니다.

---

## 4. 알맞지 않은 판단 두 가지 (제가 낸 것)

**기관·지역 축을 조사만 하는 단위로 잡았습니다.** 스키마 확장이 반드시 필요합니다.
`EvaluationRule` 은 dataclass 라 DB에 없지만, `BidEvaluationSnapshot`(`evaluations.py:96`)은
`rule_id` 하나만 저장해 기관별로 갈린 규칙 세트를 구별할 수 없고 스냅샷 재현성이 깨집니다.
AGENTS.md 5번 금지 행위는 "기존 컬럼명·타입 변경"이므로 **컬럼 추가는 해당하지 않고**
G1 데이터 무손실도 유지됩니다. 조사와 설계를 분리한 것은 합리적이었지만 구현을 다음 Task로
미룬 것이 이 세션의 최대 공백으로 남습니다.

**리뷰어에 `--strict` Level 1 게이트를 걸었습니다.** 게이트6이 `ORCA_WORKER_DONE_V2` 를
요하는데 리뷰어는 `ORCA_REVIEW_DONE_V2` 를 쓰므로 구조적으로 통과할 수 없습니다.
게이트는 builder 분기 전용이고 리뷰어는 Level 2 산출물 자체로 판정해야 합니다.

---

## 5. 재발 방지 (조율에서 배운 것)

**Capsule 의 `allowed_read_files` 에 산출물 파일을 넣지 마십시오.** 파일이 아직 없는데
읽기 허용에 있으면 워커는 "파일이 없다"를 "읽을 권한이 없다"로 읽고 멈춥니다.
investigator 를 두 번, 리뷰어 한 번을 이렇게 잃었습니다. `orca_taskctl create` 가 만든
자동 확장본이 기본으로 넣으므로 Dispatch 전에 반드시 확인하십시오.

**`worker_done` 이 "남은 작업 없음"을 말해도 산출물 파일과 커밋을 직접 확인하십시오.**
investigator 리뷰어가 판정은 세 항목 모두 pass 였고 "남은 작업은 없습니다"라고 보고했지만
Capsule 이 요구한 검토 문서가 없었고 커밋이 0이었습니다. `commit` 필드에 검토 대상 커밋을
적어 자기 산출물처럼 보냈습니다.

**워커 보고의 정본 열거형 값을 Capsule 에 예시로 넣으십시오.** 게이트6이 요구하는 키는
`version`·`status`·`branch`·`commit`·`commit_count`·`read_files`·`verdict` 7개이고,
`verification[].result` 는 `"exit_code=0; 요약"` 형태 문자열입니다. `status` 는 `succeeded`,
`verdict` 는 `pass`·`candidate`·`blocked` 만 받습니다. builder 와 investigator 가 같은 지시를
받고 한쪽은 통과하고 한쪽은 탈락했습니다.

**워크트리 base 는 `--base-branch main` 으로 고정하십시오.** `orca_codex_launch.py` 는
이 플래그가 없고 `--repo` 로 checkout 경로를 잡으므로 기본값으로 `origin/main` 에 checkout
합니다. 미푸시 커밋이 있으면 그 분량을 통째로 놓칩니다. 첫 Dispatch 가 이 일로 5분을 잃었습니다.

**codex 워커는 `--dangerously-bypass-approvals-and-sandbox` 로 띄우십시오.** 승인 플래그 없이
띄우면 `git add` 마다 대화창에서 멈춥니다. `--yolo` 는 codex CLI에 존재하지 않습니다.

**worker-start 자동 배정 모델이 ChatGPT 계정 codex 에서 실패할 수 있습니다.**
`gemini-3.8-flash-medium` 로 뜨면 `not supported when using Codex with a ChatGPT account`
로 끊깁니다. `--model` 을 명시하십시오.

**완료 세션 회수는 다음 Dispatch 를 막습니다.** `worker-release` 후 `terminal close` 를 하고
`python3 scripts/orca_settled_session_audit.py` 가 0 을 반환하는지 확인하십시오.
`--deps` 로 만든 후행 Task 는 선행 Task 가 `completed` 가 아니면 `pending` 에서 대기합니다.

**병합 훅은 커밋당 증거 하나만 받습니다.** strict 증거와 전량 테스트 증거가 각각 마지막
커밋에 기록돼 있어야 그 브랜치를 병합할 수 있습니다. 브랜치마다
`--record-evidence` 와 `premerge_full_suite_gate.py --record` 를 각각 다시 돌려야 합니다.

---

## 6. 인프라 상태

Docker 데몬은 내려가 있습니다(컨테이너 0대). 검증 명령은 SQLite 인메모리 DB 로 도는
pytest 뿐이라 docker 가 필요 없었습니다. 재기동이 필요하면 `make up`.

확인할 URL (기동 시): `http://localhost:8000` (로그인 필요),
`http://localhost:8000/docs`, `http://localhost:8000/api/v1/evaluations/rules`.

`.env` 는 격리 워크트리마다 복사해야 합니다. Git 미추적이라 따라오지 않고,
`Settings()` 가 `SECRET_KEY` 를 필수로 검증합니다.

---

## 7. 정리 완료

워크트리 4개(`orca-pre2023-bkt`·`orca-pre2023-review`·`orca-reason-fix`·`orca-reason-review`·
`orca-inst-axis`)와 잔존 브랜치 `kwanbum217/servc-formula-handoff` 를 회수했습니다.
완료 Task 의 워커 세션은 모두 닫았고 `orca_settled_session_audit.py` 가 0 을 반환합니다.
`main` 은 `origin/main` 과 동기화되어 있습니다.

---

## 8. 다음 세션 시작 시 첫 순서

```bash
cd /Users/kwanbum/Documents/korea_IT/lanhchain_ai_vision/refac_bid_box
git log --oneline -3
git status -sb                      # main...origin/main 이어야 한다

# 기관·지역 축 구현 착수 (설계는 docs/design/servc_institution_axis_design_20261002.md)
# 6절의 확인 항목 6개부터 데이터로 확인한다.
```

첫 확인은 화면의 미확인 사유 문구입니다. "문서 간 불일치" 라는 거짓 사유가 사라지고,
확정된 k·T 는 값으로 표시되며 B 만 5억원 구간 조건부로 남고 차단됩니다.
일반 띠 3건은 여전히 별표 귀속 미확인으로 막힙니다. 기관별·지역별 축은 아직 코드에 없습니다.

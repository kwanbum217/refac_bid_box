# 핸드오프 인수인계 - 2026-10-28 세션 종료

> **작성일**: 2026-10-28
> **작성**: 코디네이터(Grok). Orca Run `run_89eeda0fdf77`
> **기준 커밋**: `658350c5` (`main`, SQL 진단 문구 병합)
> **상태 문서**: [`docs/context/CURRENT_STATE.md`](../context/CURRENT_STATE.md) 의 `source_commit` 은 `ef2b4320`, `updated_at` 은 2026-10-28, 본문은 7994자입니다. HEAD 와 다릅니다.
> **직전 절차**: 브랜치 `kwanbum217/handoff-20261027-close` 의 `docs/handoff/handoff_20261027_session_close.md`. 그 파일은 `main` 에 없습니다. 그 절차는 이 세션에서 수행했고, 다음 세션의 절차 정본은 이 문서입니다.
> **Docker**: 작성 시점 app, db, meilisearch, redis 는 healthy 이고 worker 는 up 입니다. 헬스 경로는 `/api/v1/health/ready` 입니다.

---

## 0. 다음 세션이 바로 할 일

1. 이 문서를 읽습니다. 2026-10-27 인수인계의 미병합 세 갈래는 이미 끝났습니다.
2. `gh run view 40628087456` 로 `658350c5` 의 CI 를 확인합니다. 실패는 공급망 검사 한 건입니다. 테스트 job 은 통과했습니다.
3. CI 를 초록으로 만들 작업은 사용자 확인 뒤에 별도 브랜치에서 합니다. `dnspython` 2.8.0 이 `constraints.txt` 와 `uv.lock` 에 고정되어 있고, 검사기는 `CVE-2026-114605` 를 보고하며 권고 버전은 2.9.0 입니다. 테스트 실패로 보지 않습니다.
4. 아래 5절의 결정과 보류 항목은 착수하지 않습니다.
5. 다음 제품 병합을 할 때만 `CURRENT_STATE.md` 의 `source_commit` 을 그 병합 직전 `main` HEAD 8자인 `658350c5` 로 바꿉니다. 날짜가 같으면 `updated_at` 은 2026-10-28 을 유지합니다. 본문 길이는 7994자입니다. 문장을 더하면 검증이 실패합니다.

---

## 1. 오늘 main 에 넣은 것

세 병합 모두 `git merge --no-ff` 이고 `origin/main` 에 푸시되어 있습니다. 워크트리는 `git log main..<브랜치>` 가 빈 뒤 `orca worktree rm --force` 로 지웠고, 디렉터리가 사라진 뒤 `git worktree prune` 했습니다. 로컬 브랜치도 함께 지워졌습니다. 커밋은 `main` 에서 도달합니다.

| 병합 | 기능 커밋 | 내용 | 전량 시험 | CI |
| --- | --- | --- | --- | --- |
| `f6c3c4df` | `cf970586` | 마감 기한 표지가 범위 공고 목록으로 올라가지 않게 한다 | 9753 passed, 41 skipped, 3 deselected, 2 xfailed | `40624066287` failure. 공급망만 실패 |
| `ef2b4320` | `241b5c6e` | 같은 커밋 제목이 최근 이력에서 반복되면 거절한다 | 9745 passed, 41 skipped, 3 deselected, 2 xfailed | `40626578374` failure. 공급망만 실패 |
| `658350c5` | `f70e61ff` | SQL 판정의 진단 문구가 기본 벡터 질의로 남지 않게 한다 | 9763 passed, 41 skipped, 3 deselected, 2 xfailed | `40628087456` failure. 공급망만 실패 |

공통 실패 한 줄은 `dnspython 2.8.0  CVE-2026-114605  2.9.0` 입니다. `f6c3c4df` 와 `ef2b4320` 도 테스트, 린트, MySQL, 브라우저, Docker 이미지, G1 서명 job 은 success 였습니다. `658350c5` 도 같은 모양입니다.

상태 문서의 `source_commit` 은 각 병합 직전 `main` 입니다. 첫 병합 뒤 `474def84`, 둘째 병합 뒤 `f6c3c4df`, 지금 `ef2b4320` 입니다. 142행의 잔여 과업 링크는 여전히 `handoff_20261021_close.md` 입니다. 길이를 유지하려고 그 링크는 바꾸지 않았습니다. 즉시 절차는 이 문서가 우선입니다.

---

## 2. 범위 목록

| 항목 | 값 |
| --- | --- |
| 기능 커밋 | `cf970586` |
| 병합 | `f6c3c4df` |
| 파일 | `src/rag/query_planning.py`, `tests/test_scoped_list_request.py` |
| 리뷰 | 이 세션 전에 계약 통과. 다시 시키지 않음 |
| 엄격 게이트 | 11개 통과. 증거는 병합 훅이 소비함 |

동작: 마감 창이 없는 마감 기한 표지는 범위 공고 목록으로 올리지 않습니다. 마감 임박과 이번 주 마감은 기존 창을 유지합니다. 빌더가 적어 둔 전량 건수 `9744 passed, 50 skipped` 는 재실행 `9753 passed, 41 skipped` 와 달랐습니다. 보고의 그 한 줄만 실제 건수로 고친 뒤 게이트를 다시 돌려 통과했습니다.

`kwanbum217/chat-scoped-list-request` (`082e5f85`) 는 이 재작업으로 대체되었습니다. 병합하지 않습니다.

---

## 3. 커밋 제목 반복 거절

| 항목 | 값 |
| --- | --- |
| 기능 커밋 | `241b5c6e` |
| 병합 | `ef2b4320` |
| 파일 | `scripts/validate_commit_message.py`, `tests/test_validate_commit_message.py` |
| 빌더 | `task_bd74dfa9abcc`, dispatch `ctx_f77ea272abee` |
| 리뷰 | `task_311614a7fd69`, dispatch `ctx_048f1941e8c6`. 이 세션 전에 계약 통과. 다시 시키지 않음 |
| 엄격 게이트 | 재기록 후 11개 통과 |

규칙: 최근 HEAD 40개 제목에서 merge 타입을 빼고, 같은 제목이 이미 2번 있으면 거절합니다. 과거 이력은 되돌리지 않았습니다. 빌더 보고 `9736 passed, 50 skipped` 는 재실행 `9745 passed, 41 skipped` 와 달랐고, 게이트 6이 그 불일치만으로 막았습니다. 보고의 그 한 줄만 고친 뒤 다시 돌려 통과했습니다. 체크리스트 id 는 `history_rewritten`, `unique_subject_blocked`, `merge_subject_blocked`, `scope_exceeded` 입니다.

---

## 4. 묶음 6 조사와 진단 문구

조사 `task_cc716c963b03` 는 제품 커밋이 없습니다. 워크트리 `bundle6-sweep-20261027` 는 회수했습니다. 보고서 원문은 git 에 없고, 주 저장소의 `.orca/capsules/task_chat_bundle6_regression_sweep_20261026/design.md` 에만 있습니다. `.orca` 는 gitignore 입니다.

그 조사의 후속만 이번 세션에서 구현했습니다.

| 항목 | 값 |
| --- | --- |
| 브랜치 | `kwanbum217/route-reason-diag-20261028` (회수됨. 커밋은 `main` 에 있음) |
| 기능 커밋 | `f70e61ff` `fix: SQL 판정의 진단 문구가 기본 벡터 질의로 남지 않게 한다` |
| 병합 | `658350c5` |
| 파일 | `src/rag/query_planning.py`, `tests/test_route_reason_diag.py` |
| 빌더 | `task_dbbb063683c8`, dispatch `ctx_4917d27d22fc`. OpenCode `opencode/deepseek-v4.1-flash-free` |
| 리뷰 | `task_011a26aafae2`, dispatch `ctx_ab4f9c3c7439`. Command Code `z-ai/glm-5.3-flash` `--effort high` `--auto` `--role reviewer`. verdict pass |
| 체크리스트 | `decision_changed`, `reason_still_default`, `other_route_regressed`, `scope_exceeded`. 네 항목 모두 no |
| 엄격 게이트 | 11개 통과. 전량 시험 보고 9763 은 재실행과 같았습니다 |

동작: 추이, 축별 집계, 비교, 기관 조건처럼 기존 사유 분기 밖에서 SQL 이 켜지면 `route_reason` 에 사유를 덧붙입니다. 실행 판정은 바꾸지 않았습니다. 고정 질문은 q097 `최근 30일 수요기관별 낙찰 금액 상위는 어디야`, q101 `공사 부문 최근 30일 낙찰 동향 알려줘`, q092 `적격심사와 최저가낙찰제의 차이가 무엇인가요` 입니다. q092 의 기관명 오추출은 그대로 두었습니다.

리뷰어가 결함으로 보지 않고 남긴 조합이 있습니다. KB 상태 사유가 이미 있는데 SQL 이 뒤에서 켜지면 사유가 하나 더 붙을 수 있습니다. 가지고 있던 KB 변형 5건에서는 재현되지 않았고, 기존 KB 사유가 사라진 것은 아닙니다. 재현 없이 고치지 않습니다.

기동은 `worker-start` 가 아닙니다. 빌더는 `scripts/orca_opencode_launch.py`, 리뷰어는 `scripts/orca_cmd_launch.py` 입니다. 이 경로는 `worker-start` 보다 감독이 약하고, taskctl 이 배정 영수증과 프리앰블, 자동 승인 감시기를 남깁니다. Command Code 는 `--auto` 가 없으면 승인에서 멈춥니다. 런처 터미널은 `worker-release` 가 `retained`, `no_owned_resource` 로 돌아옵니다. 다음 배정 전에 `orca terminal close --terminal <핸들>` 로 그 터미널만 닫습니다. `--tab` 은 코디네이터 창까지 닫히므로 쓰지 않습니다.

---

## 5. 착수하지 말 것

| 항목 | 이유 |
| --- | --- |
| 기관 약칭, 공고명 낱말 건수, 명사구 목록, 빠른 실행 명령, 자격 필터, v3 점검 세트 | [handoff_20261026_chatbot_wave2.md](handoff_20261026_chatbot_wave2.md) 10.5. 사용자 결정 전 |
| 재무제표 OCR, 회원가입 재무 | 2026-10-12 보류 |
| chromadb 1.x | 수정 버전 없음. allowlist 만료는 2026-12-31 근처 |
| 규칙 YAML 전면 이전 | 설계 합의 전 |
| 산림청 등록, `rule_coverage_ledger.yaml` 재작성, 계산 차단 구현 | 사용자 승인 전 |
| `kwanbum217/chat-wave-handoff`, `kwanbum217/handoff-20261027-close` | 제품 변경이 아님. 20261027 절차는 이 문서가 대체함 |
| `dnspython` 버전 변경 | CI 를 초록으로 만들 때 사용자 확인 후 별도 브랜치. 이 세션에서는 시작하지 않음 |

---

## 6. 모델, 증거, 회수

빌더는 OpenCode `opencode/deepseek-v4.1-flash-free`, 리뷰어는 Command Code `z-ai/glm-5.3-flash` `--effort high` 입니다. 사용자 지정이 저장소 기본 리뷰어보다 우선합니다. 동시에 쓴 빌더는 1대였습니다. 커밋 제목 마무리는 코디네이터의 게이트와 병합이었고 빌더를 다시 붙이지 않았습니다. 리뷰어는 빌더 `worker_done` 다음에만 시작했습니다.

증거 파일 `.cache/level1_strict_evidence.json` 과 `.cache/premerge_full_suite_evidence.json` 은 마지막 기록만 남습니다. 지금 두 파일은 `f70e61ff` 입니다. 다음 `--record-evidence` 가 덮어씁니다. 한 브랜치의 병합 훅이 그 기록을 소비하기 전에는 다른 브랜치를 기록하지 않습니다.

게이트 6은 전량 시험을 다시 실행해 보고 건수와 비교합니다. 시험이 통과해도 건수가 다르면 실효 판정이 막힙니다. 건수 한 줄만 다를 때는 제품 코드를 고치지 말고 보고의 그 결과 문자열만 실제 건수로 맞춘 뒤 같은 게이트를 다시 돌립니다.

로컬에만 있는 보고(gitignore)는 주 저장소 `.orca/capsules/` 아래입니다.

| 경로 | 내용 |
| --- | --- |
| `task_scoped_list_rework_20261027/worker_done.json` | 건수를 9753/41 로 맞춘 보고 |
| `task_scoped_list_review_20261027/review_done.json` | 범위 목록 리뷰 |
| `task_commit_subject_repeat_20261027/worker_done.json` | 건수를 9745/41 로 맞춘 보고 |
| `task_commit_subject_review_20261027/review_done.json` | 커밋 제목 리뷰 |
| `task_route_reason_diag_20261028/worker_done.json` | 진단 문구 빌더 |
| `task_route_reason_review_20261028/review_done.json` | 진단 문구 리뷰 pass |
| `task_chat_bundle6_regression_sweep_20261026/design.md` | 묶음 6 조사 |

이 인수인계를 담은 커밋은 브랜치 `kwanbum217/handoff-20261028-close` 에만 있습니다. `main` 병합은 그 커밋에 대한 엄격 증거와 전량 시험 기록이 따로 필요합니다. 지금 `main` 에 남아 있는 `f70e61ff` 증거로는 병합 훅이 거절합니다.

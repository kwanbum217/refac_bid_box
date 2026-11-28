# 2026-11-28 세션 인수인계

> **작성 시각**: 2026-11-28 12:58 KST
> **main HEAD**: `73259b0b` (`merge: 야간 슬롯 성공 이력으로 따라잡기 판정을 보강하는 수정을 병합한다`)
> **Orca Run**: `run_d9caf66e5cc4`
> **추가 갱신**: 2026-11-28 오후, main HEAD `9d96ccc7` 기준으로 8장을 덧붙였다
> **상태**: 코드 병합 4건 완료(오전 2건, 오후 2건). 워커 0대, 워크트리는 주 저장소 하나. pi 비교 시험 1차 완료

---

## 0. 다음 세션 첫 할 일

8장이 최신이다. 1~7장은 오전 기록이다.

| 순서 | 할 일 | 근거 |
| --- | --- | --- |
| 1 | 이 문서 병합 커밋의 CI 결과 확인. 그 이전 병합 8건(`f9eb93ce`~`9d96ccc7`)은 모두 성공 | 8장 |
| 2 | Windows 팀원 PC 의 ChromaDB 복구와 외자 낙찰 재수집 결과 확인. 팀원 에이전트 보고 대기 | 3장 |
| 3 | 사용자 결정: 회의 자료 '다음 회의에서 정할 항목' 5개. 결정 전에는 AI 예측가 화면 구현을 시작하지 않는다 | 2장 |
| 4 | 사용자 결정: pi 재비교 시험(메모리 스킬 적용 뒤 같은 과업), 해결안 B(`_record_schedule` 의 `skipped` 성공 처리 변경) | 8장 |

--- | --- | --- |
| 1 | `4557e47e`, `73259b0b`, 이 문서 병합 커밋의 CI 결과 확인. 작성 시점 두 커밋 모두 실행 중, `0ce4d65f` 는 성공 | 1장 |
| 2 | pi 코디네이터 비교 시험 결과 확인과 판정(이 문서 병합 직후 시작) | 4장 |
| 3 | Windows 팀원 PC 의 ChromaDB 복구와 외자 낙찰 재수집 결과 확인. 팀원 에이전트 보고 대기 | 3장 |
| 4 | 사용자 결정: 회의 자료 '다음 회의에서 정할 항목' 5개. 결정 전에는 AI 예측가 화면 구현을 시작하지 않는다 | 2장 |

---

## 1. 병합한 코드

| 병합 커밋 | 브랜치 | 내용 | 검증 |
| --- | --- | --- | --- |
| `4557e47e` | `docs/onboarding-key-chroma-20261128` (`39c04a0d`) | `.env.example`: 수집 키 옛 이름 `serviceKey` 인정 안내, `AUTOMATION_SCHEDULE_CATCHUP_ENABLED=true`. windows-onboarding 스킬 정본과 미러 2곳: 키 점검이 두 이름을 모두 봄, 6장에 ChromaDB 손상(스냅샷 `chroma_db.tar.gz` 만 복원), 호스트 KB 작업 전 app·worker 정지, 낙찰 API 오류 [07] 구간 분할 | Level 1 strict pass(게이트 11 면제 선언), 전량 시험 증거 기록, GLM 리뷰 pass(계약 만족), 미러 3파일 바이트 동일 |
| `73259b0b` | `fix/catchup-nightly-slot-20261128` (`cf193e25`) | `check_schedule_catchup_needed` 에 `nightly_slot_missed` 판정 추가: 오늘 KST 02:00 이후인데 대상 작업의 마지막 성공이 슬롯 이전이거나 없으면 따라잡기. compose worker 에 `AUTOMATION_SCHEDULE_CATCHUP_THRESHOLD_HOURS`·`COOLDOWN_HOURS` 전달 두 줄 | Level 1 strict pass, 게이트 11 proven(기준 단언 실패 4건), 전량 11,862 passed, 병합 결과 대상 시험 91 passed, `docker compose config -q` 0, GLM 리뷰 pass(계약 만족) |

W1 리뷰어는 반복 실행 위험이 없음을 확인했다. 따라잡기가 대상 작업을 직접 실행하고 그 작업의 `_record_schedule` 이 같은 이름으로 성공 행을 남긴다. 결함 아닌 제안으로, `_record_schedule` 의 `success_statuses` 기본값에 `skipped` 가 있어 대상 작업이 건너뛰어져도 성공 행이 남을 수 있다고 적었다. 이 점은 4장 비교 시험의 조사 주제로 넘겼다.

W1 첫 Level 1 게이트는 fail 이었다. 코드 결함이 아니라 compose 변경에 필요한 `--verify 'docker compose config -q'` 를 코디네이터가 빠뜨린 탓이다. 워커 워크트리 `.env` 에는 `MEILI_MASTER_KEY` 가 없어 compose 검증 때 주 저장소 값을 환경변수로 넘겼다.

W1 빌더의 `worker_done` 이 다른 핸들(`term_50bbea3b`)로 한 번 더 발신돼 거부됐다. 첫 보고(`term_0a2b604b`)는 정상 수용돼 결과에 영향은 없다.

브랜치마다 `refs/backup/<브랜치 이름>-20261128` 을 남겼다. 보고서와 리뷰는 `.orca/reports/catchup/`, `.orca/reports/onboard/` 에 있다.

---

## 2. 회의 자료

구글 문서 '9차 회의자료'(`19iEcH64G5NKq2EWYPSpHcle-JurKEDkVRXfSIjmBhb8`)의 끝 절 "주요 화면 캡처" 에서 국내 3곳(입찰나라, 케이비드, 비드인사이트) 항목을 지웠다. 이 셋은 국내 표의 사이트별 항목 아래에 이미 있다. 끝 절은 인접·해외 5곳만 남았고 소개 문장을 그에 맞게 고쳤다.

---

## 3. Windows 팀원 PC

| 항목 | 상태 |
| --- | --- |
| 수집 키 | 팀원 `.env` 에 옛 이름 `serviceKey` 로만 있어 첫 프롬프트가 키 없음으로 오판했다. 팀원 에이전트가 값을 `G2B_SERVICE_KEY` 로 복사 |
| 데이터 복구 | 2026-11-07 ~ 11-27 공고 12,905건, 낙찰 6,175건 적재, Meilisearch 반영(팀원 에이전트 보고) |
| 따라잡기 | 팀원 `.env` 에 `ENABLED=true`, `THRESHOLD_HOURS=6`. 팀원 에이전트가 compose 에 기준 시간 전달 두 줄을 로컬로 추가했고, 같은 내용이 `73259b0b` 로 저장소에 들어갔다. 다음 `git pull` 전에 로컬 두 줄을 되돌리라고 안내함 |
| ChromaDB | `database disk image is malformed`. 컨테이너가 켜진 채 호스트에서 KB 색인을 쓴 것이 유력한 원인. 스냅샷 `snapshot_20261107_123933` 의 `chroma_db.tar.gz` 만 복원하고 11-07 이후를 보충하는 프롬프트를 전달. 결과 대기 |
| 외자 낙찰 | API 오류 [07] 입력범위값 초과(29일 구간). 7일 구간 재수집 프롬프트 전달. 결과 대기 |

---

## 4. pi 코디네이터 도입 (SuperGrok)

| 항목 | 내용 |
| --- | --- |
| 공식 근거 | xAI 공지는 OpenCode 에서의 SuperGrok 구독 사용만 명시. pi 본체 `packages/ai/src/auth/oauth/xai.ts` 에 "Sign in with SuperGrok or X Premium" 내장 |
| 설치 | `@earendil-works/pi-coding-agent` 1.7.0 (`/opt/homebrew/bin/pi`), xAI 구독 로그인(`~/.pi/agent/auth.json`) |
| 모델 | `grok-4.3`(1M), `grok-4.5`, `grok-4.6`, `grok-4.7`(500K). `xai/grok-4.7:high` 실제 요청 정상, 403 없음 |
| 확장 위치 | 사용자 전용 `~/.pi/agent/extensions/`. 저장소 밖이라 Git 에 남지 않는다 |
| 직접 작성 | `refac-guard.ts`(금지 명령 차단, 위험 명령 확인, 보호 경로), `refac-status.ts`(브랜치·컨텍스트 상태줄), `orca-coordinator.ts`(`bg_run`·`bg_status`·`bg_kill`, 완료 시 대화에 결과를 넣어 깨움, `/bg`, `/orca-start`) |
| 공식 예제 | `todo.ts`, `plan-mode/`, `question.ts`, `notify.ts`, `confirm-destructive.ts`. 설치 전 코드 검토, 외부 통신 없음 |
| Orca 기본 | `orca-agent-status`, `orca-prefill`, `orca-titlebar-spinner` 가 이미 설치돼 있었다 |
| 검증 | 가드 차단 5건 시험 통과, 대화형 모드에서 배경 작업 완료 시 깨우기 확인, 저장소에서 스킬 20개 로드와 `/orca-start` 영수증 발급 확인 |
| 고친 결함 | 인쇄 모드에서 세션 종료 뒤 메시지 주입으로 pi 비정상 종료 -> 화면 없는 모드는 완료까지 기다려 반환. 로그인 셸의 `~/.profile` 오류 문구 혼입 -> `bash -c` |
| 남은 것 | 저장소 첫 기동 시 프로젝트 신뢰 창(이번엔 세션만 신뢰). `~/.profile` 5번째 줄이 없는 파일(`/private/tmp/refac_phase7_tools/env`)을 읽는다 |

비교 시험은 이 문서 병합 직후 시작한다. 코디네이터는 Orca 터미널의 `pi --model xai/grok-4.7:high`, 과업은 `skipped` 성공 기록 조사(읽기 전용, 워커 1대)다. 비교 항목은 정본 스킬 절차 준수, `bg_run` 사용, 실수와 정정 왕복, 토큰·비용이다.

---

## 5. 운용 교훈

| 항목 | 내용 |
| --- | --- |
| 코디네이터 핸들 | 날짜가 바뀌어 코디네이터 터미널 핸들이 `term_c605ef3e` 에서 `term_0be24313` 으로 바뀌었고, 옛 핸들로 건 `check --wait` 가 `consumer_fenced` 로 거부됐다. 세션 시작 때 메시지가 알려 준 핸들을 쓴다 |
| 시스템 python3 | `/usr/bin/python3` 3.9 에서 표준입력 히어독의 한국어가 인코딩 오류를 냈다. 한국어가 든 Intent YAML 은 파일 도구로 쓴다 |
| compose 변경 검증 | 게이트에 `--verify 'docker compose config -q'` 를 넣고, 워커 워크트리에는 `MEILI_MASTER_KEY` 를 환경변수로 넘긴다 |
| main 의 다른 세션 변경 | 다른 세션의 미커밋 변경 4건이 main 에 있는 상태로 병합했다. `git merge --no-commit` 뒤 `git diff --cached --stat` 로 우리 파일만 들어갔는지 확인했다. pre-commit 이 미스테이지 변경을 잠시 치웠다 되돌리며 보존됐다 |
| 리뷰 극성 | 리뷰 Intent 에 "결함이 없으면 answer 는 no" 와 예시를 넣자 두 리뷰 모두 계약 만족 |

---

## 6. 정리 상태

| 대상 | 상태 |
| --- | --- |
| 워크트리 `catchup`, `onboard` | 제거, 브랜치 삭제 |
| 워커·리뷰어 창 | 전부 닫음, 자동 승인 감시기 종료 |
| main 미커밋 변경 4건(`harness.css`, `signup.html`, `base.html`, `index.html`) | 다른 세션 소유로 보여 건드리지 않음 |

---

## 7. 하지 않은 것

- `main` 직접 커밋, Pull Request
- 운영 DB 쓰기
- AI 예측가 화면 구현(회의 결정 전)
- pi 확장의 저장소 반영(비교 시험 판정 전)

---

## 8. 오후 갱신 (main `9d96ccc7`)

### 8.1 추가 병합

| 병합 커밋 | 브랜치 | 내용 | 검증 |
| --- | --- | --- | --- |
| `aac6e1ba` | `ui/korean-copy-declutter-20261128` (`3d682bcf`, `bbf54ff6`) | 다른 세션이 main 에 미커밋으로 남긴 화면 변경 20개 파일(템플릿 장식 제거, 표시 문구 한국어화, 건수 표기 `f"{value:,}"`, 챗봇 상태 배지 한국어)을 그 세션 종료 뒤 인수. 이에 맞춰 고정값 시험 8건 정리, `tailwind.css` 재빌드, `.gitignore` 에 `test-results/` | Level 1 strict pass(브랜치 전체 26개 파일 coordinator-capsule), 전량 11,860 passed, CSS 재빌드 diff 0 |
| `9d96ccc7` | `fix/catchup-skip-not-success-20261128` (`9072b206`) | `get_latest_successful_schedule_time` 조회에서 `status='skipped'` 행 제외(`status` 가 NULL 인 행은 유지). 02:00 야간 작업이 실패한 뒤 02:30 재시도가 `already_claimed` 로 건너뛰어지면 성공 행이 남아 따라잡기를 놓치던 빈틈 | 빌더 DeepSeek, GLM 리뷰 pass(계약 만족), Level 1 strict pass, 게이트 11 proven, 전량 11,865 passed, 병합 결과 대상 시험 144 passed |

`9d96ccc7` 의 빈틈은 pi 비교 시험 조사(`.orca/reports/catchup_skipped_success_20261128.md`)가 찾았다. 그 보고의 해결안 중 A(조회에서 제외)만 반영했다. 해결안 B(대상 작업의 `success_statuses` 에서 `skipped` 를 빼기)는 모니터 판정 의미가 바뀌어 사용자 결정으로 남긴다.

### 8.2 pi 비교 시험 1차 결과

| 항목 | 결과 |
| --- | --- |
| 과업 | 읽기 전용 조사 1건, 워커 1대(DeepSeek). 코디네이터 `pi` + `xai/grok-4.7:high` |
| 결과 품질 | 재현 시나리오와 코드 근거(`src/tasks/scheduled_tasks.py` 의 `success_statuses` 기본값)까지 정확, 해결안 4개 |
| 절차 준수 | Run·Task 생성, 워크트리 준비, 런처 Dispatch, 보고서를 주 저장소로 옮긴 뒤 창 닫기, `main..브랜치` 확인 후 워크트리 제거, 브랜치 안전 삭제. 런처 경로라 비감독임을 스스로 보고 |
| 소요·비용 | 약 10분, 43턴, 도구 78회, 도구 오류 0. 입력 301K, 캐시 읽기 4.6M, 컨텍스트 161K, API 환산 $3.12(구독 차감) |
| 약점 | 약 25회가 `orca_taskctl.py`·런처·Capsule 형식 재탐색. Intent 를 `.orca/intents/` 가 아닌 `.orca/capsules/` 에 둔 사소한 이탈 |
| 멈춤 | 1회. 가드 정규식의 대소문자 무시로 `git branch -d` 를 `-D` 로 오판해 확인 창 대기. 가드 쪽 결함이라 수정 |

판정: 이 규모 과업이면 대체 코디네이터로 쓸 수 있다. Claude 코디네이터와의 차이는 모델보다 운영 메모리 유무가 컸다.

### 8.3 시험 뒤 pi 하네스 보강

모두 `~/.pi/agent/` 에 있고 저장소에는 반영하지 않았다.

| 파일 | 내용 |
| --- | --- |
| `refac-permissions.json` + `extensions/refac-guard.ts` | OpenCode(MIT) 권한 정책 설계를 따라 규칙을 JSON 으로 분리. deny 우선, 나머지는 마지막 일치 규칙, 세션 동안 같은 종류 허용, 확인 창 3분 뒤 자동 거부, 대기 시 터미널 알림. 정규식은 대소문자 구분 |
| `extensions/harness-prompt.ts` | OpenCode 시스템 프롬프트를 참고한 운영 지침(배경 결과·Orca 메시지는 사용자 발언이 아님, 독립 호출 병렬, 낯선 변경 건드리지 않기, 메모리 먼저, 대기는 `bg_run`) |
| `skills/refac-memory/` | Claude 메모리 폴더 읽기 전용 연결. 재탐색 비용을 줄이는 것이 목적 |
| `mcp.json` | 웹 읽기(`mcp/fetch` 컨테이너) |

Claude Code 저장소는 소스 비공개(All rights reserved)라 공개 동작만 참고했다. 남은 빈틈은 하위 에이전트, 웹 검색, pi 종료 시 배경 작업 소멸이다.

### 8.4 운용 교훈

| 항목 | 내용 |
| --- | --- |
| 스킬 영수증 공유 | 정본 스킬 영수증은 발급한 코디네이터 핸들에 묶인 파일 하나다. pi 의 `/orca-start` 가 Claude 코디네이터 영수증을 무효로 만들어 Task 생성이 `skill_receipt_invalid` 로 거부됐다. 두 코디네이터를 함께 쓰면 Task 생성 직전에 `scripts/orca_skill_receipt.py verify`, 실패하면 `issue` |
| 다른 세션 변경 인수 | 다른 세션의 미커밋 변경은 그 세션이 끝난 뒤 브랜치로 옮겨 시험·CSS 를 맞춘 다음 병합했다. 끝나기 전에는 건드리지 않는다 |
| 시험 산출물 | e2e 실행이 남긴 `test-results/` 가 커밋에 섞였다가 amend 로 뺐다. `.gitignore` 에 추가 |

### 8.5 정리 상태

| 대상 | 상태 |
| --- | --- |
| 워크트리 | 주 저장소 하나. `skipfix`, UI 작업 워크트리 제거, 브랜치 삭제, `refs/backup/*-20261128` 고정 |
| 워커·리뷰어 창 | 전부 닫음 |
| 다른 세션 창 "딥시크 v4.1 flash 디자인 분석 검토" | 이 세션 소유가 아니라 건드리지 않음 |

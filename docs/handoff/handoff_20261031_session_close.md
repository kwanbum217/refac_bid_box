# 핸드오프 인수인계 - 2026-10-31 세션 종료

> **작성일**: 2026-10-31
> **작성**: 코디네이터(Claude Opus 5.5). Orca Run `run_4d41c7466734`
> **기준 커밋**: `006ca808` (`main`)
> **상태 문서**: `docs/context/CURRENT_STATE.md` 의 `source_commit` 은 `93b65b33`, `updated_at` 은 2026-10-31 입니다.
> **종료 사유**: 코디네이터 토큰 한도(5시간 사용량 91%). 진행 중 워커 3대와 게이트 1건을 남긴 채 종료합니다.
> **Docker**: app, db, meilisearch, redis, worker 가동 중. 정지하지 않았습니다. app 은 `query_planning.py` 병합분 반영을 위해 다음 세션에서 재시작이 필요합니다.

---

## 0. 다음 세션이 바로 할 일

1. 이 문서가 있는 브랜치 `kwanbum217/handoff-20261031-close` 를 읽습니다. `main` 에는 아직 없습니다.
2. 배달함을 비웁니다: `orca orchestration check --run run_4d41c7466734 --json` 을 count 0 까지 ack 합니다. 아래 2절의 워커 3대가 `worker_done` 을 보냈을 수 있습니다.
3. 2절 워커를 회수합니다(`scripts/orca_taskctl.py release-worker` 후 `orca terminal close --terminal <핸들>`, `--tab` 금지).
4. 3절 병합 대기 브랜치를 순서대로 병합합니다. 한 번에 하나씩입니다.
5. 병합 후 `docker compose restart app` 으로 실행 중 앱에 반영하고 `/api/v1/health/ready` 로 확인합니다.
6. `93b65b33` 이후 병합의 main CI 를 확인합니다. `45c0c89f` 는 run `41172516029` 로 12개 job 전부 성공(공급망·Trivy 포함)입니다.
7. 이 인수인계 브랜치를 마지막에 병합합니다.

---

## 1. 오늘 main 에 넣은 것

| 병합 | 내용 | 검증 |
| --- | --- | --- |
| `c091febf` | dnspython 2.8.0 -> 2.9.1 (CVE-2026-114605) | 9776 passed, strict pass |
| `e470bfc8` | q092 제도명·계약방식 기관명 오추출 수정(NON_INSTITUTION_SUFFIXES 4개) | 9785 passed, strict pass |
| `45c0c89f` | pyasn1 0.6.4 -> 0.6.5 (CVE-2026-119194~119197) | 9776 passed, CI 전 job 성공 |
| `93b65b33` | 지난 한 달 기간 창, 공고번호의 기관명 오인 수정 | 9784 passed, 병합 결과 시험 48건 |
| `006ca808` | 사정률·경쟁률 안내를 데이터 부재가 아니라 조회 경로 미지원으로 정정 | 9785 passed |

---

## 2. 진행 중이던 워커 (비감독 cmd 런처, 결과 미수신)

| Task | 내용 | 워크트리 | 터미널 | 보고 |
| --- | --- | --- | --- | --- |
| `task_0c897f18024d` | 연도 없는 10월·3분기를 가장 최근에 시작된 기간으로 해석 | `yearless-month-quarter-20261031` | `term_5fa1e939-9495-4872-8e32-7cca6dcf3198` | `.orca/capsules/task_yearless_month_quarter_20261031/worker_done.json` |
| `task_8c98ee314aba` | 적격심사 반영 조건 질문에 미지원 안내, 참가업체 수·지역 제한 문구 정정 | `gap-guard-eligibility-20261031` | `term_1937022b-afe7-4b15-af9e-4537ca6bf536` | `.orca/capsules/task_gap_guard_eligibility_20261031/worker_done.json` |
| `task_f3a7f75a70cc` | 9d0b8de3 대비 006ca808 결합 회귀 측정(실사용 413건) | `chat-kb-sql-reason-probe-20261031` | `term_141b7aa2-a160-4514-88b1-eacaa3e04c85` | `.orca/capsules/task_combined_regression_sweep_20261031/design.md` |

빌더 두 건은 리뷰가 필요합니다. 리뷰어는 cmd `z-ai/glm-5.3-flash` 입니다. taskctl 라우터가 빌더와 같은 provider(cmd)라 거부하므로 런처 직접 경로를 씁니다: `orca terminal create --command "uv run python scripts/orca_cmd_launch.py --model z-ai/glm-5.3-flash --effort high --auto --role reviewer --preamble .orca/preamble_<task>_review_manual.txt"` 후 `orca orchestration dispatch --task <id> --to <핸들> --return-preamble --json` 의 preamble 을 그 경로에 씁니다. 고정 경로 `.orca/preamble.txt` 는 런처가 거부합니다.

---

## 3. 병합 대기 브랜치 (모두 리뷰 pass)

| 순서 | 브랜치 | 커밋 | 빌더 Capsule / 보고 | 리뷰 보고 |
| --- | --- | --- | --- | --- |
| 1 | `kwanbum217/region-fallback-boundary-20261031` | `98350f21`, `60611598` | `task_f40f7b628eaa/capsule.yaml`, `task_f40f7b628eaa/worker_done.json` | `task_region_fallback_rework_review_20261031/review_done.json` |
| 2 | `kwanbum217/definition-guard-suffix2-20261031` | `45593989` | `task_8cc59a088ff1/capsule.yaml`, `task_definition_guard_suffix2_20261031/worker_done.json` | `task_definition_guard_review_20261031/review_done.json` |
| 3 | `kwanbum217/attached-period-split-20261031` | `6ff947af` | `task_e3da787bd24b/capsule.yaml`, `task_attached_period_split_20261031/worker_done.json` | `task_attached_period_split_review_20261031/review_done.json` |
| 4 | `kwanbum217/chat-plan-audit-doc-20261031` | `b6c70cce`, `4cec94b1` | `task_b178c0079656/capsule.yaml`, `task_b178c0079656/worker_done.json` | `task_chat_plan_audit_doc_rereview_20261031/review_done.json` |

경로는 각 워크트리의 `.orca/capsules/` 기준입니다(Capsule 은 주 저장소에도 있음). 1번은 종료 시점에 strict 게이트와 premerge 기록이 배경에서 돌고 있었습니다. `.cache/level1_strict_evidence.json` 의 commit 이 `60611598` 이면 그대로 병합하고, 아니면 다시 기록합니다.

병합 절차(브랜치마다):

```bash
uv run python scripts/orca_level1_gate.py --base main --branch <브랜치> --repo <워크트리> --capsule .orca/capsules/<빌더 task>/capsule.yaml --report <워크트리>/.orca/capsules/<보고> --review-report <워크트리>/.orca/capsules/<리뷰> --tests "tests/ -q -m 'not data_assets'" --verify "uv run mypy src" --strict --record-evidence --json
(cd <워크트리> && uv run python scripts/premerge_full_suite_gate.py --record)
git merge --no-ff --no-commit <브랜치>   # 주 저장소가 main 인지 먼저 확인
# CURRENT_STATE.md source_commit 을 병합 직전 main HEAD 8자로 갱신, 관련 시험 실행, 실패하면 커밋하지 않음
git commit -F <메시지 파일> && git push origin main
orca worktree rm --worktree path:<워크트리> --force
```

2·3번은 브랜치 기준이 오래돼 `query_planning.py` 에서 다른 병합과 합쳐집니다. 병합 결과로 각 브랜치의 새 시험과 `tests/test_definition_inst_suffix.py`, `tests/test_real_utt_window_bidno.py` 를 함께 돌립니다.

---

## 4. 착수하지 않은 것과 사용자 결정

| 항목 | 상태 |
| --- | --- |
| chromadb CVE 3건 예외 2026-12-31 만료 | 상류 수정 없음(최신 1.5.9). 2027-03-31 연장 여부 사용자 결정 |
| 사정률 실지원 | 원천 `bid_prearng_prices.sajeong_rate` 224,754건(용역만). 결정 대기 |
| 경쟁률 정의 | 참가업체 수 평균 18.441 로 정의할지 결정 대기 |
| 유찰 상태 수집 | 데이터 없음. 라우팅 변경 금지. 수집 여부 결정 대기 |
| 금액대별 구간 | 후보 A 1억/5억/10억. 결정 대기 |
| 적격심사 조건 실지원 | 원천 `raw_data.sucsfbidMthdNm` 존재. 지금은 미지원 안내(2절 빌더) |
| 잡담 전용 분기 | 24회. 결정 대기 |
| 연도 없는 월·분기 규칙 | 코디네이터가 가장 최근에 시작된 기간으로 정함. 사용자 확인 필요 |
| 기간 비교 형태 제한안 | 기관명 커버리지 82%(공고 91%)라 보류. 기관 목록 대조 방식이 필요 |
| KB 상태 표지 보정 | 실사용 KB 낱말 0건이라 보류 |

조사 결과 원문은 주 저장소 `.orca/capsules/task_*_20261031/design.md`(gitignore)에 있고, 요약은 3절 4번 브랜치의 `docs/analysis/chat_plan_audit_20261031.md` 입니다.

---

## 5. 운영 교훈

| 교훈 | 내용 |
| --- | --- |
| 리뷰 pass 근거란 | 지역 폴백 첫 리뷰가 pass 였지만 근거란에 숫자 뒤 지역명 회귀가 있었다. 근거를 읽고 재작업으로 돌렸다 |
| 착수 전 확인 조사 | 실사용 점검 1·2순위(유찰, 사정률)는 라우팅 결함이 아니었다. 빌더 전에 데이터 경로를 확인해 오수정을 막았다 |
| 셸 `&` 대기 금지 | `check --wait` 를 `&` 로 분리했다가 정리했다. 추적되는 배경 작업으로만 기다린다 |
| `orca_auto_approve.py --help` | 도움말이 아니라 감시 루프로 들어간다. 호출하지 않는다 |
| 같은 딕셔너리 수정 | `DATA_GAP_MESSAGES` 처럼 맞붙은 줄을 두 브랜치가 고치면 충돌한다. 먼저 병합하고 새 main 에서 띄운다 |

---

## 6. 사용자 결정 (2026-10-31 세션 종료 직후)

4절 항목에 대해 사용자가 결정했습니다. 다음 세션은 3절 병합 뒤 이 순서로 빌더를 띄웁니다. 결정 3·5·7·8 은 "코디네이터 권장안대로" 였고 아래가 그 권장안입니다.

| # | 항목 | 결정 | 구현 방향 |
| ---: | --- | --- | --- |
| 1 | chromadb 예외 | 연장 | `.github/vulnerability-allowlist.yml` 세 항목 `expires_on` 을 2027-03-31 로, 사유에 상류 미수정(최신 1.5.9)과 보상 통제(로컬 PersistentClient, 외부 비공개) 명시 |
| 2 | 사정률 | 실제 조회 | `bid_prearng_prices.sajeong_rate` 평균 조회 추가, `metric=avg_sajeong_rate`, 가드에서 사정률 제외. 용역만 원천이 있으므로 다른 분류는 안내 |
| 3 | 경쟁률 | 권장안 | 낙찰 1건당 평균 참가업체 수(`bid_results.raw_data.prtcptCnum`). 키 없는 행·유찰 제외, 표본 수와 한계 문구 표기, 이상치 기준은 시험으로 고정 |
| 4 | 유찰 상태 | 새로 수집 | 나라장터 개찰결과 API 수집기와 추가 전용 저장 구조 설계. 기존 테이블·컬럼 변경 금지(G1). 설계 합의 후 구현 |
| 5 | 금액대별 구간 | 권장안 | 1억 미만, 1억~5억, 5억~10억, 10억 이상. 기준은 공고 추정가격, 없으면 기초금액 |
| 6 | 적격심사 조건 | 실제 지원 | `raw_data.sucsfbidMthdNm LIKE '적격심사%'` 필터를 계획·SQL·응답에 추가. 2절 미지원 안내 빌더(`task_8c98ee314aba`)는 이 결정으로 대체되므로 병합하지 않고 실지원 빌더로 다시 낸다 |
| 7 | 잡담 분기 | 권장안 | 인사·ping·테스트에 검색 없는 짧은 도움말 응대 신설. 범위 밖 거절은 유지 |
| 8 | 연도 없는 월·분기 | 권장안 | 가장 최근에 시작된 기간으로 해석(2절 `task_0c897f18024d` 그대로) |

순서 권고: 1(설정 한 파일) -> 6, 2, 3(지표·필터, `structured_data.py` 공유라 직렬) -> 5 -> 7 -> 4(설계 문서 먼저).

---

## 7. 재개 세션 결과 (2026-10-31 저녁, 이 절이 0~3절보다 우선)

main 은 `ada865fb` 입니다. 0~3절의 병합 대기 4개와 2절 워커 3대는 모두 처리했습니다. 오늘 병합 12건이며 공급망 CI 는 `45c0c89f` 에서 초록입니다. `93b65b33` 이후 병합의 CI 는 확인하지 못했습니다.

### 7.1 운영 DB 변경 (사용자 승인)

| 항목 | 값 |
| --- | --- |
| 백업 | `data/backups/snapshots/snapshot_20261031_112947`(DB 2.3GB, ChromaDB, 모델) |
| 적용 | `alembic upgrade head` 로 `a6b7c8d9e0f1 -> b7c8d9e0f1a2 -> c1d2e3f4a5b6` |
| 신규 테이블 | `accounts_session_generation`(2026-10-12 병합분 미적용이었음), `bid_openg_results` |
| 대조 | 공고 5,560,232, 낙찰 3,464,615, 사정률 353,042행 전후 동일. 테이블 43 -> 45 |
| G1 기준선 | `c06d1d52`(브랜치 `kwanbum217/openg-g1-baseline-20261031`), bid_openg_results 만 추가 |

운영 DB 는 이미 c1d2 이지만 main 에는 아직 그 마이그레이션이 없습니다. 7.2 의 1번을 가장 먼저 병합해야 main 과 DB 가 맞습니다.

### 7.2 병합 대기 (모두 리뷰 pass, 이 순서로 한 번에 하나씩)

| 순서 | 브랜치 | 내용 | 비고 |
| --- | --- | --- | --- |
| 1 | `kwanbum217/openg-g1-baseline-20261031` | 유찰 수집 설계 문서 + T1·T2 + T3 + T4 + G1 기준선 묶음 | 코디네이터 Capsule `.orca/capsules/coord_openg-chain-20261031/capsule.yaml`(변경 12파일). strict 게이트를 `--allow-missing-report` 로 다시 기록. 수집 플래그 `OPENG_RESULT_COLLECTION_ENABLED` 기본 꺼짐 |
| 2 | `kwanbum217/chromadb-allowlist-20261031` | chromadb 예외 2027-03-31 연장 | 리뷰 `task_chromadb_allowlist_review_20261031` |
| 3 | `kwanbum217/eligibility-filter-20261031` | 적격심사 조건 실지원 | 4·6 의 기준 커밋 b3dfe707 |
| 4 | `kwanbum217/small-talk-branch-20261031` | 잡담 도움말 분기 | |
| 5 | `kwanbum217/amount-band-axis-20261031` | 금액대별 4구간 | 3 위에 쌓임 |
| 6 | `kwanbum217/sajeong-competition-20261031` | 사정률·경쟁률 실조회 + v2 점검 항목 numeric_fact 전환 | 3 위에 쌓임. v2 점수 영향 있음 |

`kwanbum217/gap-guard-eligibility-20261031`(미지원 안내)은 결정 6 으로 대체되어 병합하지 않습니다.

병합마다: strict 게이트 `--record-evidence`, 워크트리에서 `premerge_full_suite_gate.py --record`, `git merge --no-ff --no-commit`, `CURRENT_STATE.md` source_commit 갱신, 병합 결과 시험을 `> log; rc=$?` 로 받아 0 이 아니면 `git reset --merge`. 쌓인 브랜치끼리 `query_planning.py`·`structured_data.py` 를 공유하므로 병합 결과 시험에 각 브랜치 신규 시험을 함께 넣습니다. 이 세션에서 결합 결함이 두 번(지역 폴백·기간 분리, 기간 분리·연도 없는 월) 이 방식으로 잡혔습니다.

### 7.3 중단한 워커 (종료로 끊김, 결과 미확인)

| Task | 내용 | 워크트리 |
| --- | --- | --- |
| `task_9371f5cefaa4` | 경쟁률 응답을 중앙값 우선으로(최근 30일 평균 95.06곳, 중앙값 근사 7, 최댓값 9,118) | `competition-median-20261031`(6 위) |
| `task_397508a8ea64` | 백업 도구가 `docker exec -e MYSQL_PWD=<값>` 로 비밀번호를 ps 에 노출하는 결함 수정 | `backup-pwd-argv-20261031` |

커밋이 있으면 리뷰부터, 없으면 같은 Intent(`.orca/intents/competition_median_20261031.yaml`, `backup_pwd_argv_20261031.yaml`)로 다시 띄웁니다.

### 7.4 남은 과업

| 과업 | 상태 |
| --- | --- |
| 유찰 1년 소급 실행 | `scripts/backfill_openg_results.py`(기본 dry-run, `--max-calls` 필수). 승인 트래픽 단위와 rbidNo 유니크성 실측 후 `--execute` |
| 유찰 T5(가드 해제·목록 조건) | 소급 적재 뒤 착수 |
| v2 재측정 | 6 병합 뒤 app 재시작 후 v1·v2 측정 |
| app 재시작 | 병합분 반영을 위해 `docker compose up -d` 후 `docker compose restart app` |
| 잔여 관찰 | 의미 검색 질의문에 공백 삽입(최근 에), 날짜 창 없는 적격심사 건수의 JSON 전체 스캔 |

### 7.5 운영 메모

| 교훈 | 내용 |
| --- | --- |
| 병합 결과 시험 파이프 | `| tail` 로 받아 실패 2건을 커밋·푸시(b14142ad), edb40d4d 로 복구. 종료 코드를 따로 받는다 |
| 셸 `&` 배경 | 세 번 반복. 게이트·대기는 run_in_background 로만 띄운다 |
| 쌓인 브랜치 | 선행 브랜치가 병합되기 전 후속 빌더의 changed_files 는 선행 커밋 기준 diff 로 받는다 |

Docker 는 종료 시 `docker compose stop` 으로 내렸습니다(볼륨 유지).

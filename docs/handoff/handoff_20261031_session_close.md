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

# 핸드오프 인수인계 - 2026-11-09 세션

> **작성일**: 2026-11-09
> **작성**: 코디네이터(Claude Opus 5.5). Orca Run `run_f846c95069c9`
> **기준 커밋**: 작성 시점 `main` 과 `origin/main` 은 `f4e7aa45` 입니다. 이 문서는 브랜치 `kwanbum217/handoff-20261109` 에서 씁니다.
> **워커 풀**: 빌더 cmd `deepseek/deepseek-v4.1-flash`, 리뷰어 cmd `z-ai/glm-5.3-flash`(사용자 지정).
> **종료 사유**: 사용자 지시로 17:00 에 모든 작업을 멈췄습니다. 리뷰 통과 브랜치 2개와 리뷰 전 브랜치 2개가 병합되지 않은 채 남아 있습니다.

---

## 0. 다음 세션이 바로 할 일

| 우선 | 과업 | 방법 |
| --- | --- | --- |
| 1 | `f4e7aa45`(zlib1g Trivy 수정) main CI 확인 | `gh run list --branch main --limit 3`. 공급망 job 이 통과해야 다음 병합이 의미 있습니다 |
| 2 | B3 전량 시험 1건 실패 격리 | 아래 2.1. 동시에 전량 시험 3개가 돌던 중의 실패라 간섭일 수 있습니다. 실패 시험을 단독 재실행해 판정합니다 |
| 3 | B3 → B2 → B4 순서로 병합 | 각 브랜치에서 `orca_level1_gate.py --strict --record-evidence`, `premerge_full_suite_gate.py --record` 를 **직렬로** 실행합니다. 두 증거 파일이 저장소에 하나씩이라 병렬로 기록하면 서로 덮어씁니다 |
| 4 | B4 병합 뒤 운영 Meilisearch 전체 재색인 | `docker compose exec app env MEILI_TIMEOUT_SECONDS=30 python3 scripts/sync_search_index.py`, `/tasks` 의 enqueued·processing 0 확인 |
| 5 | 병합 뒤 `docker compose restart app worker` | uvicorn 에 `--reload` 가 없어 라우트 변경은 재시작 전까지 반영되지 않습니다 |
| 6 | B5(수동 재학습) 이어서 완료 | 아래 2.4 |
| 7 | F-02 사정률 통계 갱신 경로 Dispatch | 사용자 지시는 받았으나 시간 부족으로 Dispatch 하지 못했습니다. 아래 3장 |

---

## 1. 이 세션에서 main 에 넣은 것

| 병합 | 내용 |
| --- | --- |
| `f4e7aa45` | 런타임 이미지 `zlib1g` 를 `deb13u1`(trixie-security)로 올려 Trivy HIGH 2건(CVE-2026-76844, CVE-2026-85091) 해소. 빌더 `d9b40a81`, 리뷰 pass, 로컬 Trivy 재검사 통과, 전량 시험 10,671 통과 |

---

## 2. 병합되지 않은 브랜치

모든 워크트리는 `/Users/kwanbum/orca/workspaces/refac_bid_box/` 아래에 있고 기준 커밋은 `f4e7aa45` 입니다. 보고서 사본은 주 저장소 `.orca/capsules/` 에 회수했습니다.

| 브랜치 | 커밋 | 내용 | 상태 |
| --- | --- | --- | --- |
| `kwanbum217/compare-match` (B3) | `14b5eebd` | 비교 화면 매칭률 분자·분모를 최근 365일 공고 기준으로 통일(5.9% -> 62.96%), 99.8% 고정 문구 제거, 응답에 `announce_count_1y`·`matched_count_1y` 추가 | 리뷰 pass. Level 1 게이트 6 실패(아래 2.1) |
| `kwanbum217/cnstwk-guard` (B2) | `7c2e0f93` | 전용 모델 없는 분야(공사·외자) 투찰가 추천 차단, v25 를 대체 후보에서 제거, 상세 화면 안내 | 리뷰 pass(Playwright e2e 1건 미검증). 게이트 미완 |
| `kwanbum217/qual-badge` (B4) | `f3b25c55` | 목록·홈 배지와 Meilisearch 색인 문서에 첨부 판별 갈래 반영, 갈래 분류 후 색인 갱신 연결 | 빌더 완료, 리뷰 전 |
| `kwanbum217/manual-retrain` (B5) | 아래 2.4 | 수동 재학습 카테고리 fan-out | 진행 중 종료 |

### 2.1 B3 게이트 6 실패

Level 1 게이트가 전량 시험을 다시 돌렸을 때 `1 failed, 10675 passed` 였고, 빌더 보고는 `10676 passed` 였습니다. 같은 시각에 B2 게이트와 다른 워커의 전량 시험이 함께 돌고 있었습니다. 실패 시험 이름은 확인하지 못했습니다. 워크트리에서 전량 시험을 다시 돌려 실패 시험을 찾고, 그 시험만 단독 재실행해 간섭인지 결함인지 판정합니다.

### 2.2 B2 판단 근거

공사 낙찰 400건(2026-07 이후, 실제 낙찰률 평균 90.82%) 역검증에서 v25 MAE 13.84(93% 가 75/105 경계값), v13_hybrid 2.31, quantum_leap_v25_pro 2.18, ssh_hist_premium 4.32 였고 단순 평균 1.25, 낙찰하한율+0.2 는 0.77 이었습니다. 기존 모델 중 공사에 쓸 것이 없어 사용자가 A안(추천 차단)을 결정했습니다. 공사 전용 모델 재학습(B안)은 용역 집중 원칙에 따라 보류합니다. 원인 문서는 브랜치의 `docs/analysis/cnstwk_prediction_guard_20261109.md` 입니다.

### 2.3 B4 리뷰

리뷰 Intent 는 `scratchpad` 의 생성기와 같은 방식으로 빌더 Intent `.orca/intents/qual_badge_regime_20261109.yaml` 의 checklist 를 그대로 옮겨 만듭니다. 리뷰어 GLM 은 빌더와 같은 cmd 제공자라 `orca_taskctl.py dispatch` 가 거부하므로 `orca orchestration dispatch --return-preamble` 와 워크트리 `.orca/preamble_<dispatch>.txt` 로 띄웁니다(옛 고정 이름 `.orca/preamble.txt` 는 런처가 거부합니다).

### 2.4 B5 수동 재학습

`_step_retrain` 이 `category_code` 없이 `run_retrain_pipeline_task` 를 불러 수동 재학습이 항상 `ValueError` 로 실패하는 결함(I-ai F-03)입니다. 종료 지시가 워커 턴 안에서 처리되지 않아 `worker-stop`(Dispatch `ctx_7bc248e7ffb4`, state stopped)으로 멈추고 터미널을 닫았습니다. 커밋은 0건이고, 미커밋 진행분(`src/tasks/automation_steps.py`, `src/tasks/scheduled_tasks.py` 105줄 추가·37줄 삭제, 새 시험 파일)은 워크트리 `manual-retrain` 에 그대로 있으며 주 저장소 `.orca/capsules/task_46d7afb90948/wip_20261109/` 에 패치로 백업했습니다. 시험은 돌리지 않았습니다. 다음 세션은 Task 를 `ready` 로 되돌려 같은 워크트리에서 재 Dispatch 하고, 진행분을 검증부터 이어 가게 합니다. Intent 는 `.orca/intents/manual_retrain_fix_20261109.yaml` 입니다.

---

## 3. 미착수 과업

| 과업 | 근거 | 비고 |
| --- | --- | --- |
| F-02 사정률 통계 갱신 경로 | `institution_sajeong_rate_stats` 전 행 `rebuilt_at=2026-10-07`, 재집계 함수 `src/app/services/sajeong_rate_stats.py:104` 호출부 없음, 예비가격 적재가 `dminstt_nm` 미채움 | 사용자 지시 받음. `prearng_daily` 크론이 2026-10-17 실행 실패 뒤 기록이 없고 `bid_prearng_prices.rl_openg_dt` 최대가 2026-10-14 라 수집 자체가 멈춘 원인도 함께 봐야 합니다 |
| windows-onboarding 스킬 보완 | 4장 A 에 스냅샷 복원 뒤 Meilisearch 재색인 단계가 없어 팀원 PC 에서 `/bids/` 가 503 | 런북 `docs/ops/backup_recovery_runbook.md` 4.3.1.1 절차를 스킬에 넣고, 복원 시 `MYSQL_CLIENT_CONTAINER` 지정도 추가 |
| 점검표 미달 3건 | fixture 근거 manifest 가 2026-08-27 fixture 갱신을 따라가지 않음(24개 ID 누락), 규칙 커버리지 원장 차이 6,681건, 하한율 지표 차이 | 원장·지표는 11-09 데이터 수집 뒤 재생성하면 됩니다 |
| 점검표 3장 성능 측정 | 워커 부하로 측정하지 않았습니다 | 부하 없는 상태에서 `latency_gate_protocol.md` 규약대로 |

---

## 4. 기능 검토 결과 (읽기 전용 워커 2대)

| 보고서 | 발견 | 주 저장소 사본 |
| --- | --- | --- |
| I-data 업무 기능 | 12건(상 1·중 5·하 6). 상 F-01 은 B3 로 수정 중, F-04 는 B4 | `.orca/capsules/task_feat_review_data_20261109/review.md` |
| I-ai AI 기능 | 14건(상 3·중 6·하 5). F-01 극단 경고 화면 미전달(공사는 B2 로 해소, 물품·용역 경고 표시는 남음), F-02 는 격리 트리 오판으로 기각, F-03 은 B5 | `.orca/capsules/task_feat_review_ai_20261109/review.md` |

미확인 항목(I-ai F-05~F-09, I-data F-03·F-05~F-11)은 수정 과업으로 넘기기 전에 코디네이터가 재현합니다. 결정 필요: I-data F-05(자동화 구독 구현 또는 문서화), F-10(비밀번호 변경·탈퇴).

---

## 5. 운영 메모

| 항목 | 내용 |
| --- | --- |
| Windows 팀원 | 스냅샷 `snapshot_20261107_123933` 복원 뒤 Meilisearch 전체 재색인 진행 중이었습니다. `.env` 의 `MODEL_MANIFEST_SIGNING_KEY` 는 비워 두라고 안내했습니다(스냅샷 manifest 가 이 맥의 키로 서명됨) |
| 증거 파일 직렬화 | `.cache/level1_strict_evidence.json`, `.cache/premerge_full_suite_evidence.json` 은 하나뿐이라 병합 직전 브랜치 하나씩만 기록합니다 |
| 전량 시험 병렬 | 게이트와 워커의 전량 시험을 동시에 3개 이상 돌리면 실패가 섞일 수 있습니다 |

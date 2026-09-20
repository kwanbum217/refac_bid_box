# 세션 인수인계: 2026-09-20 인수인계 잔여 과업 병렬 처리

> **작성일**: 2026-09-20
> **작성자**: Claude Opus 5 (Orca 코디네이터)
> **기준 커밋**: `main` `639c60f1`
> **Orca Run**: `run_f2a82124eb58`
> **이어받은 문서**: [`session_20260919_measurement_harnesses.md`](session_20260919_measurement_harnesses.md)

---

## 1. 한 줄 요약

전 인수인계 7장의 과업이 대부분 차단이거나 시점미도래여서, 먼저 잔여 과업표 자체를 전수 재판정하고 동시에 G3 읽기 경로 재탐색, 단일 EXISTS 계획 전환 조사, 주간 재학습 사전 점검을 워커 4대로 병렬 진행해 4건을 병합했습니다.

---

## 2. 이번 세션 병합

| 커밋 | 내용 | 검증 |
| --- | --- | --- |
| `a32d3db8` | [`exists_plan_flip_investigation_20260920.md`](../analysis/exists_plan_flip_investigation_20260920.md) 단일 EXISTS 계획 전환 조사 (w3) | Level 1 pass, 리뷰 pass, 전량 5,133 |
| `227f1c24` | [`handoff_backlog_reaudit_20260920.md`](../analysis/handoff_backlog_reaudit_20260920.md) 잔여 과업 전수 재판정 (w1) | Level 1 pass, 리뷰 pass, 전량 5,133 |
| `68f60687` | [`weekly_retrain_prep_20260920.md`](../analysis/weekly_retrain_prep_20260920.md) 주간 재학습 사전 점검 (w4) | Level 1 pass, 리뷰 pass, 전량 5,133 |
| `639c60f1` | [`read_path_g3_rescan_20260920.md`](../analysis/read_path_g3_rescan_20260920.md) 읽기 경로 N+1·동기 I/O 조사 (w2) | Level 1 pass, 리뷰 pass, 전량 5,133 |

워커 모델은 빌더 4대 모두 `gemini-3.8-flash-medium` 입니다. 배정표 권장(`gemini-3.8-flash-low`, investigator·low)보다 상위라 `WORKER_MODEL_NOTICE` 대상입니다. 리뷰어는 `grok-4.6` 으로 시작했으나 첫 호출이 HTTP 402 `Grok Build usage balance exhausted` 로 실패해 `gemini-3.8-flash-high` 로 풀을 통째로 스왑했으며 이것도 같은 고지 대상입니다.

Antigravity 계열은 `worker-start --agent` 가 받지 않으므로 **터미널 부착 런처 경로(비감독)** 로 띄웠습니다. `release-worker` 는 네 건 모두 `retained` 로 돌아왔고 `orca terminal close` 로 창 단위 종료했습니다. Run 의 Task 4건은 전부 `completed` 이고 잔류 세션·워크트리·작업 브랜치는 없습니다.

---

## 3. 잔여 과업 재판정 결과

상세는 [`handoff_backlog_reaudit_20260920.md`](../analysis/handoff_backlog_reaudit_20260920.md) 입니다. 네 출처(최신·직전 인수인계 7장, `handoff_20260818.md` 2장, `CURRENT_STATE.md` 6.1절) 26행, 고유 20건을 코드 근거로 대조했습니다.

| 판정 | 건수 | 대표 항목 |
| --- | ---: | --- |
| 해소 | 8 | ChromaDB 실패·0건 구분, `dispatch` 종료 코드 3, CURRENT_STATE 압축, 블로킹 I/O P95, 수집 2·3회차, 낙찰 목록 A/B, 인증 경로 P95, CI 확인 |
| 유효 | 3 | 수집·드리프트 관찰, 손상 탐침 효과 크기, 단일 EXISTS 조사(이번 세션에 종결) |
| 차단 | 4 | Windows 실기, 운영 경로 A, `OLLAMA_NUM_PARALLEL` |
| 시점미도래 | 5 | 주간 재학습(09-21), 용역 재비교(10 중순), chromadb CVE(12-31) |

**과업표가 구현을 따라가지 못해 이미 끝난 일이 착수 후보로 남아 있었습니다.** 다음 세션은 이 판정표를 기준으로 삼으십시오.

---

## 4. 이번 세션에서 드러난 사실

| 사실 | 근거 | 조치 |
| --- | --- | --- |
| 주간 재학습 런북이 존재하지 않는 경로를 지시하고 있었다 | 2.5 절의 `ml_registry/servc_institution_v1/serving_models.json` 은 실재하지 않는다. 서빙본은 `data/model_files/servc_institution_v1/LIVE` 포인터와 `promote_model.py status` 로 본다 | 점검 체크리스트에 실재 명령으로 대체해 적었다. 런북 본문 수정은 하지 않았다 |
| 낙찰 상세 경로에서 선채움 캐시가 무력화되는 N+1 이 남아 있다 | `src/app/services/bid_queries.py:745-748` 이 관련 낙찰 5건 루프에서 `display_winning_rate(db)` 를 호출한다 | 다음 최적화 1순위 후보. 구현과 A/B 는 미착수 |
| 단일 EXISTS 계획 전환 원인을 규명했다 | 세미조인 `DuplicateWeedout` 과 `Materialization` 의 비용 역전 경계에 최근 1년 기준일이 걸쳐 있고 인덱스 다이브가 실제의 2.4배로 과대추정한다 | 운영 경로는 스냅샷으로 격리되어 조치 불요. 6.1 절에서 종결 처리했다 |
| **`premerge_full_suite_gate.py --record` 증거는 주 저장소 `.cache` 한 곳에 쓰인다** | 워크트리 4곳에서 병렬로 기록하면 마지막 하나만 남는다 | 브랜치마다 기록 직후 바로 병합하는 직렬 사이클로 바꿨다. **병렬 기록은 무의미하다** |
| `taskctl dispatch` 는 Orca Task 를 스스로 만들지 않는다 | `--intent` 만 주면 `Task not found` 로 실패한다 | `create` 로 Task 를 먼저 만들고 `--task-id` 와 `--capsule` 을 함께 넘겨야 한다 |
| `create` 가 만든 Task 의 TASK 블록이 Intent 파일명 기준 Capsule 경로를 가리킨다 | 워커 4대 중 1대가 폐기된 사본을 읽었다 | 정본 경로를 터미널로 정정 전달했다. 나머지 3대는 스스로 id 기반 경로를 찾았다 |
| `orca_run_reviewer.py` 는 python3.9 에서 실행되지 않는다 | `from datetime import UTC` 가 3.11 이상이다 | `uv run python` 으로 호출한다 |

---

## 5. 자원 상태

| 대상 | 상태 |
| --- | --- |
| Git | 주 저장소 `main` `639c60f1`, 원격 반영 완료. 워커 워크트리 4개는 병합 후 정리 대상 |
| Orca Run | `run_f2a82124eb58`. Task 4건 전부 `completed`. 잔류 세션 없음 |
| Docker | app/db/redis/meilisearch/worker 기동. db·redis·meilisearch healthy. 이번 세션은 측정을 하지 않아 변체 전환 없음 |
| 배경 프로세스 | 상시 감시기 `orca_worker_watch.py --watch --respawn` 기동됨 |

---

## 6. 다음 세션이 확인할 과업

| 시점 | 과업 | 확인 방법 |
| --- | --- | --- |
| 즉시 | `639c60f1` CI 결과 | `gh run list --branch main --limit 3` |
| 스택 기동 후 | 수집·드리프트 진행 | 전 인수인계 6.1 절차 |
| 2026-09-21 03:00 이후 | 첫 주간 재학습. 자동 승격 없는지 | [`weekly_retrain_prep_20260920.md`](../analysis/weekly_retrain_prep_20260920.md) 의 점검 체크리스트 |
| 원할 때 | 낙찰 상세 N+1 제거와 A/B | [`read_path_g3_rescan_20260920.md`](../analysis/read_path_g3_rescan_20260920.md) 상위 3건 |
| 원할 때 | 손상 탐침 총 시간 효과 크기 | 저장소가 조용할 때만 |
| 운영 접근 확보 시 | 경로 A. ml_registry 재생성 선행 | [`ml_registry_production_bootstrap.md`](../ops/ml_registry_production_bootstrap.md) |
| 2026-10 중순 이후 | 용역 표본 외 재비교 | `compare_servc_models_paired.py --year 2026 --since 2026-09-15` |
| 장비 확보 시 | Windows Docker Desktop 실기 | G2 보류 |
| 2026-12-31 | chromadb CVE 재확인 | 수정 버전 없으면 업그레이드 재제안 금지 |

---

## 7. 하지 말 것

- 전 인수인계 8장의 금지 항목은 그대로 유효합니다.
- 해소로 판정된 8건을 다시 착수 후보로 올리지 마십시오. 근거는 재판정 보고서에 있습니다.
- `premerge_full_suite_gate.py --record` 를 여러 워크트리에서 동시에 돌리지 마십시오. 증거가 덮어써집니다.
- 런북 2.5 절의 `serving_models.json` 경로를 따라가지 마십시오. 실재하지 않습니다.

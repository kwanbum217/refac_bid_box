# 세션 인수인계: 2026-09-20 읽기 경로 최적화 3건

> **작성일**: 2026-09-20
> **작성자**: Claude Opus 5 (Orca 코디네이터)
> **기준 커밋**: `main` `3245fc7b`
> **Orca Run**: `run_9b2d94301949`
> **이어받은 문서**: [`session_20260920_parallel_backlog_reaudit.md`](session_20260920_parallel_backlog_reaudit.md)

---

## 1. 한 줄 요약

같은 날 앞선 세션의 G3 재탐색이 고른 상위 3건을 워커 3대로 병렬 구현해 전부 병합했고, 도중에 제미나이 쿼터가 소진되어 미커밋 산출물을 보존한 채 Muse Spark 로 인계해 끝냈습니다.

---

## 2. 이번 세션 병합

| 커밋 | 내용 | 검증 |
| --- | --- | --- |
| `66f7cccb` | 낙찰 상세 관련 낙찰의 공고 조회 N+1 제거 (p1) | Level 1 pass, 리뷰 pass, 전량 5,134, mypy 108파일 무결함 |
| `b5587559` | 스냅샷 목록 증빙 일괄 로딩으로 1+N 해소 (p2) | Level 1 pass, 리뷰 pass, 전량 5,135(결합 상태) |
| `af71c86e` | 챗봇 쿼터 검사의 이벤트 루프 블로킹 해소 (p3) | Level 1 pass, 리뷰 pass, 전량 5,140(결합 상태) |

`main` `3245fc7b` 에서 CI 10잡 전량 success 입니다.

| 대상 | 변경 요지 |
| --- | --- |
| `src/app/services/bid_queries.py` | `get_result_detail` 이 본건과 관련 낙찰을 한 번에 선채움한다. 질의 3회 고정 |
| `src/app/api/v1/evaluations.py` | 스냅샷 목록 질의에 `selectinload(evidence_items)` 를 붙였다. 건수와 무관하게 SELECT 2회 |
| `src/app/api/v1/chatbot.py` | 두 비동기 핸들러의 쿼터 검사를 `asyncio.to_thread` 로 오프로드했다. 예외는 스트림 시작 전에 난다 |

세 건 모두 **질의 수를 실제로 계측하는 테스트**가 함께 들어갔습니다(총 377줄 추가). 호출 성공만 보는 테스트가 아닙니다.

**효과 크기는 아직 주장할 수 없습니다.** 질의 수 절감만 증명했고 레이턴시 실측은 없습니다.

---

## 3. 워커 운용

빌더는 `gemini-3.8-flash-medium` 으로 시작했고 리뷰어는 사용자 지시에 따라 바뀌었습니다. 셋 다 `WORKER_MODEL_NOTICE` 대상입니다.

| 단계 | 모델 | 사유 |
| --- | --- | --- |
| 빌더 1차 | `gemini-3.8-flash-medium` | 구현 중 전량 쿼터 소진으로 중단 |
| 빌더 2차 | `opencode/muse-spark-1.3-contributor-free` | 사용자 지시. 무료 풀이라 TIER_POLICY 자동 개방 대상이 아니다 |
| 리뷰어 | `claude-sonnet-4-6` | 사용자 지시. Antigravity Claude 풀, 수동 지정 전용 |

앞선 세션에서 `grok-4.6` 은 HTTP 402 로 잔량이 소진됐습니다. 리뷰어 후보를 고를 때 Grok 을 먼저 시도하지 마십시오.

---

## 4. 이번 세션에서 드러난 사실

| 사실 | 근거 | 조치 |
| --- | --- | --- |
| **쿼터로 죽은 워커의 작업은 버리지 않아도 된다** | 제미나이 3대가 `RESOURCE_EXHAUSTED (429)` 로 `worker_done` 없이 턴을 끝냈으나 미커밋 변경은 워크트리에 남아 있었다 | 같은 워크트리에 새 모델 터미널을 붙여 이어받게 했다. 셋 다 처음부터 다시 하지 않고 검증·커밋만 하고 끝냈다 |
| 활성 Dispatch 가 있으면 Task 를 `ready` 로 되돌릴 수 없다 | `task_not_startable: cannot move to ready while Dispatch ... is active` | `worker-abandon --dispatch <id>` 로 먼저 펜싱한다. 비감독 터미널은 `processAction: none` 으로 남으므로 `terminal close` 를 따로 한다 |
| **`premerge_full_suite_gate.py --record` 증거는 주 저장소 `.cache` 한 곳에 쓰인다** | 워크트리 4곳에서 병렬 기록하면 마지막 하나만 남는다 | 브랜치마다 기록 직후 병합하는 직렬 사이클로 돌린다. 앞 세션에서도 같은 함정을 겪었다 |
| 선행 병합이 있으면 워커 브랜치에 `main` 을 먼저 반영하는 편이 낫다 | p2, p3 는 p1 병합 뒤 결합 상태에서 전량을 다시 돌렸다 | 결합 상태 통과를 증거로 남겼다. 코디네이터가 워커 브랜치에 넣은 병합 커밋이며 리뷰어가 아니다 |
| 게이트 출력이 빈 파일로 끝날 수 있다 | p2 1차 게이트가 0바이트로 종료했다 | stdout 과 stderr 를 분리해 재실행했다. **빈 출력을 통과로 읽지 마십시오** |

---

## 5. 자원 상태

| 대상 | 상태 |
| --- | --- |
| Git | 주 저장소 `main` `3245fc7b`, 원격 반영 완료. 워커 워크트리·작업 브랜치 없음 |
| Orca Run | `run_9b2d94301949` Task 3건 전부 `completed`. `run_f2a82124eb58` 도 4건 전부 `completed`. 잔류 세션 없음 |
| Docker | 세션 종료 처리로 내렸다. 볼륨은 지우지 않았다 |
| 배경 프로세스 | 상시 감시기 종료 |

---

## 6. 다음 세션이 확인할 과업

| 시점 | 과업 | 확인 방법 |
| --- | --- | --- |
| 즉시 | `3245fc7b` CI | 이미 10잡 success 확인 완료 |
| 스택 기동 후 | **읽기 경로 3건의 레이턴시 실측** | `b6082b4d`(수정 전)와 `3245fc7b`(수정 후)를 교대로 띄워 잰다. 저장소가 조용해야 한다 |
| 스택 기동 후 | 수집·드리프트 진행 | 전전 인수인계 6.1 절차 |
| 2026-09-21 03:00 이후 | 첫 주간 재학습. 자동 승격 없는지 | [`weekly_retrain_prep_20260920.md`](../analysis/weekly_retrain_prep_20260920.md) 체크리스트 |
| 원할 때 | 읽기 경로 잔여 후보 | [`read_path_g3_rescan_20260920.md`](../analysis/read_path_g3_rescan_20260920.md) 4~6순위 |
| 원할 때 | 손상 탐침 총 시간 효과 크기 | 저장소가 조용할 때만 |
| 운영 접근 확보 시 | 경로 A. ml_registry 재생성 선행 | [`ml_registry_production_bootstrap.md`](../ops/ml_registry_production_bootstrap.md) |
| 2026-10 중순 이후 | 용역 표본 외 재비교 | `compare_servc_models_paired.py --year 2026 --since 2026-09-15` |
| 장비 확보 시 | Windows Docker Desktop 실기 | G2 보류 |
| 2026-12-31 | chromadb CVE 재확인 | 수정 버전 없으면 업그레이드 재제안 금지 |

---

## 7. 세션 종료 처리

| 대상 | 종료 처리 |
| --- | --- |
| Redis | `SHUTDOWN NOSAVE` 로 먼저 내린다. 그냥 내리면 `dump.rdb` 가 생겨 Git 추적 문제가 재발한다 |
| Docker | `docker compose down`. **볼륨은 지우지 않는다**(`-v` 금지) |
| 배경 프로세스 | 상시 감시기 `orca_worker_watch.py --watch --respawn` 종료 |
| 워커 터미널 | 이미 전부 회수·종료 완료 |

다음 세션은 Docker Desktop 기동부터 다시 시작하면 됩니다.

---

## 8. 하지 말 것

- 전전 인수인계 8장의 금지 항목은 그대로 유효합니다.
- **이번 세 변경의 레이턴시 개선 폭을 숫자로 인용하지 마십시오.** 질의 수만 증명됐습니다.
- `premerge_full_suite_gate.py --record` 를 여러 워크트리에서 동시에 돌리지 마십시오.
- 게이트나 리뷰의 빈 출력을 통과로 읽지 마십시오.
- 리뷰어로 `grok-4.6` 을 먼저 시도하지 마십시오. 잔량이 없습니다.

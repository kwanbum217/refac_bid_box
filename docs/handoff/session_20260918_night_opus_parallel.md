# 세션 인수인계: 2026-09-18 야간 병렬 작업

> **작성일**: 2026-09-18
> **작성자**: Claude Opus 5 (Orca 코디네이터)
> **기준 커밋**: `main` `e6fe5eb5`
> **Orca Run**: `run_3e15fce3f09d`
> **이어받은 문서**: [`session_20260918_grok_shutdown.md`](session_20260918_grok_shutdown.md)

---

## 1. 한 줄 요약

토큰 소진으로 인수인계 작성 중 끝난 Grok 세션을 이어받아 미병합 인수인계를 먼저 `main` 에 넣고, 사용자가 고른 네 방향(협상 가격점수, ml_registry 런북, 정합성 감사, G3 재탐색)을 병렬 워커로 진행해 6건을 병합했습니다. G3 재탐색에서 낙찰 목록의 공고 조회 N+1 을 찾아 제거했습니다.

---

## 2. 이번 세션 병합

| 커밋 | 내용 | 검증 |
| --- | --- | --- |
| `c74a20f0` | Grok 세션 종료 인수인계 (미병합분) | 전량 5,089. CI 성공 |
| `f7425408` | [`ml_registry_production_bootstrap.md`](../ops/ml_registry_production_bootstrap.md) 운영 재생성 런북 | Level 1 pass. Muse Spark 리뷰 pass. 전량 5,080 |
| `01df5e4d` | [`negotiation_price_score_feasibility_20260918.md`](../analysis/negotiation_price_score_feasibility_20260918.md) 가격점수 타당성 판정 | Level 1 pass. Muse Spark 리뷰 pass. 전량 5,080 |
| `f67c4357` | [`state_code_consistency_audit_20260918.md`](../analysis/state_code_consistency_audit_20260918.md) 정합성 감사 | Level 1 pass. Muse Spark 리뷰 pass. 전량 5,080 |
| `419274cd` | 낙찰 목록 공고 조회 N+1 제거 + 테스트 8건 | Level 1 pass. Muse Spark 리뷰 pass. 전량 5,088. CI 10잡 전량 성공 |
| `568d8357` | 감사 판정 6건 반영 및 상태 문서 동기화 | Level 1 pass. Muse Spark 리뷰 pass. 전량 5,080 |
| `e6fe5eb5` | [`read_path_concurrency_20260918.md`](../analysis/read_path_concurrency_20260918.md) 측정 보고서 + `source_commit` 갱신 | 전량 5,097. 규칙 21/21 |

워커 모델: 빌더 `gemini-3.8-flash-medium`·`-high`(비감독 런처), 리뷰어 `opencode/muse-spark-1.3-contributor-free`. 리뷰어는 사용자 지시이며 TIER_POLICY 기본(`qwen-plus`) 이탈이므로 `WORKER_MODEL_NOTICE` 입니다.

Run `run_3e15fce3f09d` 의 Task 10건은 전부 `completed` 이고 잔류 세션과 워크트리는 없습니다.

---

## 3. G3: 읽기 경로 동시성과 N+1

상세는 [`read_path_concurrency_20260918.md`](../analysis/read_path_concurrency_20260918.md) 입니다. 요지만 적습니다.

| 사실 | 근거 |
| --- | --- |
| 단일 요청 웜에서는 읽기 경로 7종이 전부 P95 20ms 이하다 | 워밍업 3회 뒤 30회 측정. 깊은 페이지도 열화 없음 |
| 동시성 c10 에서 낙찰 목록 P95 가 219.69ms 로 튄다 | 같은 c10 조건 예측 API 정본은 48.14ms |
| 원인은 목록 직렬화의 공고 조회 N+1 이다 | `matching_announcement` 가 행마다 최대 두 번 질의. 20행이면 최대 40회 추가 |
| 인스턴스 캐시는 이 N+1 을 줄이지 못한다 | 같은 인스턴스를 다시 물었을 때만 듣는다 |
| 일괄 조회 후 3회 중앙값은 79.16ms 다 | 저장소가 조용한 상태에서 측정. 회차 산포 9.70ms |
| **개선 크기는 미확정이다** | 대조군(공고 목록, 비교 통계)도 각각 25.8%, 9.7% 줄었다. 병합 전 측정은 워커 3대가 돌던 중의 1회 표본 |
| **질의 수 감소는 확정이다** | `test_batch_query_count_does_not_scale_with_rows` 가 질의 수를 직접 센다 |

확정값이 필요하면 같은 시각에 선채움을 켜고 끄는 A/B 로 다시 재야 합니다. 이번 세션에서는 하지 않았습니다.

---

## 4. 이번 세션에서 드러난 사실

| 사실 | 근거 | 조치 |
| --- | --- | --- |
| `source_commit` 뒤처짐은 로컬에서 경고, `main` 에서 FAIL 이다 | 로컬 21/21 통과인데 CI `568d8357` 이 "CURRENT_STATE 필수 필드" 로 실패 | 병합을 여러 건 쌓는 세션은 **병합마다** `source_commit` 을 갱신한다. 6커밋 뒤처져 허용 5를 넘겼다 |
| CI 실패가 코드 문제가 아닐 수 있다 | `f67c4357` Run 35347011705 은 syft v1.51.1 다운로드 HTTP 504 로 체크섬 불일치 | 같은 잡이 다음 Run 에서 성공했다. 실패 로그를 먼저 읽고 외부 장애를 가려낸다 |
| 워커 보고의 "worker_done 전송 완료" 는 화면 문구일 뿐이다 | at2 화면에 완료 문구가 떴으나 런북도 `worker_done.json` 도 없었다 | 파일 실재와 커밋 수로만 판단한다 |
| Antigravity 워커는 배경 실행으로 정체한다 | at1 이 "배경 질의 완료 알림을 기다립니다" 로 멈춤. at5 도 같은 패턴 | Capsule 금지 조항이 있어도 재발한다. `terminal send --enter` 로 전경 재실행을 지시하면 복귀한다 |
| Capsule 고지문이 잠정 ID 경로를 가리킨다 | at4 가 `.orca/capsules/task_at4_.../capsule.yaml` 을 못 찾아 `find` 로 네 번 왕복 | `.orca/capsules` 를 통째로 복사하면 작업에는 지장이 없다. 왕복 비용만 든다 |
| 리뷰어가 절대 경로 링크를 놓친다 | at3 보고서에 `file:///Users/kwanbum/orca/workspaces/...` 링크 51곳 | 체크리스트에 `absolute_path_link` 항목을 넣으면 잡는다. at5 에서는 잡혔다 |
| `worker-release` 는 재사용 터미널을 닫지 않는다 | 모든 회수에서 `retained`, 종료 코드 1 | `orca terminal close --terminal <handle>` 로 창 단위 종료. `--tab` 금지 |
| 전량 테스트를 동시에 여러 개 돌리면 서로 느려진다 | at1 증거 기록이 at4 워커 pytest 와 겹쳐 지연 | 측정과 증거 기록은 저장소가 조용할 때 한다 |

---

## 5. 정본 문서 변경 (판정 근거 포함)

`568d8357` 로 반영했습니다. 판정은 코디네이터가 내렸고 워커는 기계적으로 반영했습니다.

| 판정 | 내용 | 근거 |
| --- | --- | --- |
| 1 | `negotiation_contract_support` 를 active -> **closed** | 미확정부였던 가격점수 산식이 "공고서 원문 필요" 로 닫혔다 (`01df5e4d`) |
| 2 | `drift_job` 은 **active 유지** | ml_registry 운영 재생성이 운영 반영 전까지 남는다. 증거 경로만 교정 |
| 3 | `scheduled_tasks.py` 독스트링 기본값 `False` -> `True` | `config.py:80` 실제 기본값이 True. 동작 코드 변경 0줄 |
| 4 | `psi_drift_monitoring.md` 를 세 카테고리 전량 감시로 갱신 | Thng `b_20260915_thng_post_regime` 적재로 건너뛰기 예외 해소. 과거 경위는 이력으로 보존 |
| 5 | `cross_platform_guide.md` CI 기록을 `fa1202f`/Run 33947859707 로 갱신 | G2 판정은 **보류 그대로** |
| 6 | 6.1 절에서 RAG cold SQL 항목 제거, 측정 설계 항목은 범위 한정 | `coldsql_metric`·`coldsql_rerun` 이 둘 다 closed 라 미해결 목록에 남을 근거가 없다 |

---

## 6. 사용자 결정 (유지)

전 세션에서 이어받은 결정이며 이번 세션에서 바뀐 것은 없습니다.

| 항목 | 결정 | 실행 |
| --- | --- | --- |
| 운영 반영 | 경로 A (운영에서 재학습·승격) | 미실행. 운영 서버 접근 없음 |
| GitHub Release | `v0.1.0` 과 `v0.1.0-rc.1` 둘 다 초안 유지 | 공개·삭제·태그 push 없음 |
| 용역 표본 외 재비교 | 2026-10 중순 이후 | 지금 Dispatch 금지 |
| 20260909 backfill | 2026-09-18 승인·완료 | 추가 수집 금지 |

---

## 7. 다음 세션이 확인할 과업

| 시점 | 과업 | 확인 방법 |
| --- | --- | --- |
| 즉시 | `e6fe5eb5` CI Run 35350790021 결과 | `gh run view 35350790021 --json conclusion`. `source_commit` FAIL 이 해소됐는지 본다 |
| 스택 기동 후 | 수집 id, 드리프트 id 진행 | 전 인수인계 6.1 절 절차 |
| 원할 때 | 낙찰 목록 순개선 크기 확정 | 선채움 켜고 끄는 A/B 재측정 |
| 원할 때 | 인증 경로 P95 | SSR 화면과 `POST /api/v1/evaluations/analyze`. 세션 쿠키 발급 절차가 문서에 없어 분리했다 |
| 2026-09-21 03:00 이후 | 첫 주간 재학습. 자동 승격 없는지 | [`weekly_retrain_verification.md`](../ops/weekly_retrain_verification.md) |
| 운영 접근 확보 시 | 경로 A. **ml_registry 재생성이 선행** | [`ml_registry_production_bootstrap.md`](../ops/ml_registry_production_bootstrap.md) |
| 2026-10 중순 이후 | 용역 표본 외 재비교 | `compare_servc_models_paired.py --year 2026 --since 2026-09-15` |
| 장비 확보 시 | Windows Docker Desktop 실기 | G2 보류 |
| 2026-12-31 | chromadb CVE 재확인 | 수정 버전 없으면 업그레이드 재제안 금지 |

---

## 8. 자원 상태

| 대상 | 상태 |
| --- | --- |
| Git | 주 저장소 `main` `e6fe5eb5`. 워커 워크트리 없음. 작업 브랜치 전부 삭제 |
| Orca Run | `run_3e15fce3f09d`. Task 10건 전부 `completed`. 잔류 세션 없음 |
| 배경 프로세스 | `orca_worker_watch.py --watch --respawn` PID 16656 |
| Docker | app/db/redis/meilisearch/worker 기동. ready 200. app 은 N+1 병합본으로 재빌드·재기동함 |

전 세션 Run `run_4ed3b9b08099` 의 ready Task 3건(경로 A `task_330317a1793b`, 릴리스 `task_3b3f7a78ee70`, 용역 재비교 `task_8b89da2dd535`)은 손대지 않았습니다. blocked 인 as9-review `task_7bc94af1d54e` 도 그대로입니다.

---

## 9. 하지 말 것

- `docker compose down -v` 로 볼륨을 지우지 마십시오.
- 운영 서버 없이 경로 A 를 로컬에서 실행하지 마십시오.
- chromadb 를 수정 버전 없이 1.x 로 올리지 마십시오. 원본 `chroma_db/` 를 실행 중 컨테이너와 호스트 파이썬이 동시에 열지 마십시오.
- Release 초안을 사용자 확인 없이 공개하거나 삭제하지 마십시오.
- `main` 에 직접 커밋하지 마십시오.
- `TRIGGER_RETRAIN` 을 보고 재학습·승격을 자동 실행하지 마십시오.
- 20260909 를 다시 backfill 하지 마십시오.
- as9-review `task_7bc94af1d54e` 를 재 Dispatch 하지 마십시오.
- 주간 재학습을 09-21 전에 enqueue 하지 마십시오.
- **읽기 경로 개선 크기를 -64% 로 인용하지 마십시오.** 대조군도 함께 줄어 순개선분이 분리되지 않았습니다.
- `orca terminal close --tab` 을 쓰지 마십시오. 코디네이터 창까지 닫힙니다.

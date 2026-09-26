# 세션 인수인계: 2026-09-26 런북 감사, 수집 재개, 현황판 갱신, 수집·로그·원장 결함 수정

> **작성일**: 2026-09-26
> **작성자**: Claude Opus 5.5 (Orca 코디네이터)
> **기준 커밋**: `main` `b6fd30b0` (세션 종료 시점)
> **Orca Run**: `run_1bfc04b2de02` (워커 터미널 전부 회수)
> **이어받은 문서**: [`session_20260925_handoff_parallel_and_rto_drill.md`](session_20260925_handoff_parallel_and_rto_drill.md)

---

## 1. 한 줄 요약

세 웨이브를 처리했습니다. 첫 웨이브는 드리프트 런북 인용 정정(A1)과 `CURRENT_STATE` 메타 최신화(B)입니다. 두 번째 웨이브는 2026-09-21 A안으로 멈춰 있던 `worker` 를 재기동해 수집과 드리프트 감시를 되살리고(S1), 2026-08-26 에 멈춘 용역 모델 현황판을 갱신했습니다(S2). 세 번째 웨이브는 그 과정에서 드러난 결함 셋을 고쳤습니다. 수집 공백 오탐(W1), 로그의 API 인증키 노출(W2), 원장 증거 경로 오류와 그것을 통과시킨 검증기 빈틈(W3)입니다. 마지막으로 app 로그를 10초마다 채우던 chromadb 텔레메트리 ERROR 를 멈췄습니다(T).

---

## 2. 병합 결과

| 섹션 | 병합 | 내용 | 검증 |
| --- | --- | --- | --- |
| B `CURRENT_STATE` 메타 | `a6a181eb` | `updated_at`, `source_commit`, 잔여 과업 포인터 최신화 | 코디네이터 Capsule strict 게이트, 전량 5,422, CI 성공 |
| A1 `task_b3c9f935b106` 드리프트 런북 인용 정정 | `1a6c9d06` | `docs/ops/ml_registry_production_bootstrap.md` 의 어긋난 file:line 인용 10곳 정정(예: `drift_monitor_task` 622 에서 692행). 절차는 그대로 | 빌더 cmd DeepSeek V4.1 Flash, 리뷰 pass(인용 17건 전수), strict 11/11, 전량 5,413, CI 성공 |
| S2 `task_3ee9410e585b` 와 재작업 `task_040f821dd109` 용역 현황판 갱신 | `faf55722` | `docs/servc_model_status.md`: 현재 champion `v_20260915_133523_756`(운영 경로 MAE 1.1885), 승격 경위(`promoted_at` 2026-09-15 13:58), OOS 3,589건으로 축적 축 완료, 주간 재학습은 개발 켜짐(용역만, 승격 수동)과 운영 꺼짐 | 빌더 cmd GLM-5.3 Flash. 1차 리뷰 pass 였으나 코디네이터 Level 3 에서 반려(3.1 절), 재작업 뒤 재리뷰 pass(compose 대조 포함), strict 게이트, 전량 5,422, CI 성공 |
| W3 원장 증거 경로와 검증기 | `f2bd54b2` | `servc_oos` 증거를 실제 위치 `data/benchmarks/servc_oos_champion_20260830.json` 으로 고치고, `validate_agent_rules.py` 원장 검사가 공백 없이 `/` 를 포함한 증거 값의 실재를 요구하게 했다 | 코디네이터 직접 작성. 옛 원장에 새 검사를 돌려 `servc_oos` 를 잡는 것을 확인, 테스트 60, mypy, strict 게이트, 전량 5,432 |
| W2 `task_6fcd4a3a1802` 로그 인증키 가림 | `dd994365` | `src/app/core/logging_config.py`: `httpx`·`httpcore` 로거 WARNING, `ServiceKeyRedactionFilter` 가 `serviceKey=값` 을 대소문자 무관하게 `***` 로 가림 | 빌더 cmd GLM-5.3 Flash, 리뷰 pass(경계 입력 11종 실측), strict 게이트, 전량 5,426. 재시작한 worker 안에서 가짜 키가 `***` 로 찍히고 httpx INFO 가 숨는 것을 확인 |
| W1 `task_827798ca12c0` 수집 공백 오탐 | `5a8813dd` | `src/app/services/collector_service.py`: 체크포인트 MIN of MAX 에서 희소 분류 `Frgcpt` 를 제외(요청이 전부 Frgcpt 면 예외). 무데이터 검사와 수집 대상은 그대로 | 빌더 cmd GLM-5.3 Flash, 리뷰 pass, strict 게이트, 전량 5,425. 재시작한 worker 안에서 창이 경고 없이 `20260924~20260925` 로 잡힘 |
| T chromadb 텔레메트리 ERROR 억제 | `d90f2cac` | app 헬스체크가 10초마다 `PersistentClient` 를 만들 때마다 chromadb 0.6.3 의 `posthog.capture` 가 posthog 7.37.3 과 인자가 맞지 않아 ERROR 를 남겼다(하루 약 8,600줄). compose 에 `ANONYMIZED_TELEMETRY=False`(전송 차단), `logging_config.py` 에 해당 로거 CRITICAL(실패 로그 억제) | 코디네이터 직접 작성. 테스트 15, mypy, 개발·운영 compose config, strict 게이트, 전량 5,440, CI 성공. 재시작 뒤 헬스체크 5회 동안 텔레메트리·ERROR 로그 0건 |

---

## 3. S1 운영 조작과 확인 결과

| 항목 | 결과 |
| --- | --- |
| 재기동 | Docker Desktop 기동 후 `docker compose up -d` 로 전 서비스 healthy. W1·W2 병합 뒤 `docker compose restart app worker` 로 새 코드 반영(`./src` 바인드 마운트) |
| 따라잡기 수집 | 09-19~09-25 회수, 검색 색인 동기화 완료(공고 3,142, 낙찰 2,321), 12:43 파이프라인 종료 |
| "수집 공백 15일, 09-11~09-18 백필 필요" 경고 | **오탐.** 그 구간의 용역·물품·공사 공고와 낙찰은 DB 에 모두 있었다. 외자 낙찰 최신일만 09-10 이라 MIN of MAX 가 끌려갔다. 백필은 하지 않았고 W1 로 고쳤다 |
| 드리프트 감시 | baseline 3개가 컨테이너에 마운트됨. 마지막 판정은 09-18 로 그 뒤 멈춰 있었다. 드리프트 알림이 외부로 나갈 수 있어 수동 실행은 하지 않았다. 다음 04:00 정기 실행 기록으로 확인한다 |
| 주간 재학습 | 개발 compose 는 2026-09-15 커밋 `47917cbf` 부터 `ML_WEEKLY_RETRAIN_ENABLED=true`, `ML_WEEKLY_RETRAIN_CATEGORIES=Servc`. worker 재기동으로 다음 월요일에 용역 재학습이 돈다. 승격은 수동이라 서빙은 바뀌지 않는다. 운영 compose 는 기본값 `false` |
| 사용자 결정(2026-09-26) | **개발 환경 주간 재학습은 켜 두고 worker 를 계속 가동한다.** 2026-09-21 A안(worker 정지)을 대체한다. 다음 세션은 worker 를 임의로 내리지 않는다 |

---

## 4. 이번 세션에서 드러난 사실

| 사실 | 조치 |
| --- | --- |
| "두 섹션 병렬" 을 워커 한 대와 코디네이터 직접 수행으로 해석하고 알리지 않아 사용자가 되물었다 | 이후 웨이브부터 Dispatch 전에 워커 수와 직접 처리 섹션을 먼저 밝혔다 |
| 인수인계 여러 건이 OP-3 을 "변동 없음, A안대로 정지" 로만 넘겨, worker 정지가 수집·드리프트 감시까지 세운다는 사실이 5일간 드러나지 않았다 | 정지한 서비스가 무엇을 함께 세우는지 인수인계에 적는다 |
| S2 1차 리뷰가 현재 compose 와 어긋나는 과거 서술을 pass 했다. 원인은 코디네이터 Capsule 이 compose 를 read_scope 에 넣지 않고 체크리스트가 "근거 파일에 있는가" 만 물은 것이다 | 재리뷰 Capsule 에 compose 를 넣고 "과거 서술을 현재 설정과 대조" 를 ground_truth 로 요구했다. 문서 갱신 과업의 리뷰는 현재 코드·설정 대조를 포함한다 |
| W1 은 Frgcpt 공백 검출을 단정하던 기존 테스트 2건을 주요 분류로 바꿨다 | 설계상 받아들인 절충이다. 외자만 따로 비는 공백은 이제 체크포인트로 검출되지 않는다. 수집 창은 전 분류를 함께 가져오므로 실제 누락 위험은 작다 |
| 원장 검증기는 증거가 비어 있지 않은지만 보아 없는 경로를 통과시켰다 | W3 로 경로 형태 값의 실재를 강제했다. 경로가 아닌 서술(CI 실행 설명)은 건너뛴다 |
| zsh 에서 `${var^^}` 가 bad substitution 으로 터미널 생성이 실패했다 | Task 는 ready 로 남아 부작용 없이 재시도했다 |
| 텔레메트리 수정 첫 안(`ANONYMIZED_TELEMETRY=False` 만)은 컨테이너에서 60초 관찰로 효과가 없음이 드러났다. chromadb 0.6.3 은 텔레메트리를 꺼도 `capture` 를 부른다 | 라이브러리 소스를 읽고 로거 억제를 더했다. 설정 변경은 병합 전에 실제 컨테이너 로그로 효과를 확인한다 |
| 런처·터미널 부착 경로 워커는 release 결과가 `retained / no_owned_resource` 다 | 창을 `orca terminal close` 로 닫아 회수했다. 이번 Run 의 워커는 모두 비감독 경로였다 |

---

## 5. 다음 세션

| 순서 | 할 일 | 근거와 주의 |
| --- | --- | --- |
| 1 | 이 문서 병합의 CI 확인 | |
| 2 | 드리프트 감시 재개 확인 | `uv run python scripts/db_readonly_query.py --sql "SELECT id, trigger_source, challenger_version, status, created_at FROM retrain_logs ORDER BY id DESC LIMIT 6"` 에 09-27 04:00 이후 `drift_monitor` 행이 있어야 한다 |
| 3 | 월요일 용역 주간 재학습 결과 확인 | 개발 환경 켜짐. 승격은 수동이며 `docs/servc_model_status.md` 의 판정 기준을 따른다 |
| 4 | 운영 환경 주간 재학습 재개 여부 | 현황판 3장 결정 대기 |
| 5 | (선택) Docker VM fsync, G1 20.8초 재발, G2 Windows 실기 | 직전 인수인계 5.2 절과 동일. Docker Desktop 은 여전히 4.92.0 |

---

## 6. 자원 상태

| 대상 | 상태 |
| --- | --- |
| Git | `main` 은 이 문서 병합 후 clean, 원격 반영. 워커 워크트리 0건(`orca-a1`, `orca-s2`, `orca-w1`, `orca-w2` 제거), 작업 브랜치 0건 |
| Orca | Run `run_1bfc04b2de02` Task 10건 completed(A1, S2, S2 재작업, W1, W2 와 각 리뷰). 워커 터미널 전부 닫음, 배달 큐 비움, 잔류 세션 감사 통과 |
| Docker | **app, db, redis, meilisearch, worker 가동 중.** worker 가 수집·드리프트 감시·용역 주간 재학습을 수행한다. 내릴 때는 `docker compose stop` (볼륨 보존) |
| 배경 프로세스 | 상시 워커 감시기는 종료했다 |
| 세션 종료 확인 (2026-09-26 14:40 KST) | `main` 원격과 동일, 작업 트리 clean, 워크트리·작업 브랜치 0건. Orca 배달 큐 비어 있음, Run Task 10건 completed, 잔류 세션 감사 통과, 코디네이터 창 외 터미널 없음. 컨테이너 5개 가동(app healthy, worker 가동). 마지막 병합 `b6fd30b0` CI 성공 |

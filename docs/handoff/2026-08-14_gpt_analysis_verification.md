# 외부 정적 분석 결과 검증 (GPT 5.6 저장소 감사)

> **작성일**: 2026-08-14
> **검증 기준 커밋**: `main` `4602e26`
> **검증 대상**: GPT 5.6 이 GitHub 웹에서 `main` 소스 트리를 순회해 작성한 32절 분석 보고
> **검증 방법**: 로컬 저장소 코드·문서 정적 대조 + 스케줄·워커 테스트 단독 실행
> **정본 백로그**: [`2026-08-13_future_work_backlog.md`](2026-08-13_future_work_backlog.md)

---

## 0. 판정 요약

아키텍처 서술과 강점 평가는 대체로 정확합니다. 다만 **컷오버 판단을 뒤집는 오류가
한 건 있고**, 이미 해결된 항목을 P0 로 올린 것이 한 건, 방향이 반대인 문서 갱신
권고가 한 건 있습니다.

| 구분 | 건수 | 성격 |
| --- | ---: | --- |
| 판단을 바꾸는 오류 | 3 | 성능 게이트 오판, 문서 갱신 방향 역전, 해결된 항목 재제기 |
| 낡은 수치 인용 | 5 | 2026-08-04 시점 값을 현재 값으로 서술 |
| 전제 누락 권고 | 2 | 선행 조건과 기존 결정 사항 미반영 |
| 유효한 지적 | 다수 | 문서 정합성, CI 부채, LLM 의존성 비밀폐성 |

이 문서를 남기는 이유는 **다음 세션이 `phase7_cutover_report_20260804.md` 를 현행
근거로 다시 사용하는 것을 막기 위함**입니다.

---

## 1. 판단을 바꾸는 오류

### 1.1 "컷오버 차단은 성능이 아니다" — 오류

분석은 `docs/ops/phase7_cutover_report_20260804.md:16` 의 예측 API P95 **19.1ms**
를 근거로 G3 통과를 단정하고, 남은 차단 요인을 Windows 실기 검증 하나로 축소했습니다.

해당 수치는 **기동 직후 단일 요청** 값입니다. 2026-08-13 계측 반영 실측은 다음과
같습니다.

| 구성 | 동시성 | P95 | 목표 | 판정 |
| --- | ---: | ---: | ---: | --- |
| 단일 워커 warm | 1 | 16.1358ms | 100ms | 통과 |
| 단일 워커 warm | 2 | 31.2996ms | 100ms | 통과 |
| 단일 워커 warm | 4 | 58.4468ms | 100ms | 통과 |
| 단일 워커 warm | 10 | **199.1758ms** | 100ms | **실패** |
| Uvicorn 3워커 | 10 | 127.32ms | 100ms | 실패 |
| Uvicorn 4워커 | 10 | 165.92ms | 100ms | 실패 |

`docs/ops/phase7_latency_recheck_20260813.md:76` 에 명시돼 있습니다. "예측 P95 가
실패한 상태에서 Phase 7 G3 전체 통과를 선언하지 않습니다."

따라서 컷오버 차단은 **성능과 Windows 두 건**이며, 분석이 제시한 실행순서에서
`Production cutover` 를 Windows 검증 직후에 두는 것은 성립하지 않습니다.

### 1.2 README 갱신 권고의 방향이 반대

분석은 README 가 낡았으므로 G3 를 통과로 고치라고 권고했습니다. 그러나
`README.md:11` 의 현행 문구(G2 Windows 실기 검증과 G3 목표 결정이 남음)가
2026-08-04 보고서보다 **현실에 더 가깝습니다.** 권고대로 수정하면 README 에 거짓이
들어갑니다.

실제로 필요한 갱신은 통과 선언이 아니라 **G3 의 세분화**입니다.

| 항목 | 현재 실측 | 판정 |
| --- | --- | --- |
| SSE 첫 토큰 P95 | 1.721초 (목표 3초) | 통과 |
| SSE 전체 응답 P95 | 8.129초 (목표 20초) | 통과 |
| 예측 API P95 warm c10 | 199.18ms (목표 100ms) | 미달 |

### 1.3 02:00 cron 중복 위험 — 이미 해결됨

분석은 `development_data_refresh_task` 와 `nightly_schedule_task` 가 같은 시각에
등록된 것을 P0 로 올리고 전용 테스트 신설을 권고했습니다. 방어는 이미 3중입니다.

| 계층 | 실제 상태 |
| --- | --- |
| 코드 상호 배제 | `src/tasks/scheduled_tasks.py:106` — 야간 번들이 활성이면 개발 최신화를 건너뜁니다 |
| 기본값 | `src/app/core/config.py:22-24` 는 nightly 만 활성, `docker-compose.yml:106-107` 은 refresh 만 활성 |
| 회귀 테스트 | `tests/test_scheduled_tasks.py:192` `test_development_refresh_skips_when_full_nightly_schedule_is_enabled` |
| 구성 테스트 | `tests/test_worker_compose.py:30-31` 이 Compose 환경변수 조합을 고정 |

단독 실행으로 확인했습니다.

```text
.venv/bin/python -m pytest tests/test_scheduled_tasks.py tests/test_worker_compose.py -q
18 passed
```

권고된 테스트가 사실상 같은 이름으로 존재하므로 이 항목은 착수 목록에서 제외합니다.

---

## 2. 낡은 수치

| 분석 인용 | 현재 정본 | 근거 |
| --- | --- | --- |
| SSE 첫 토큰 P95 2.66초 | **1.721초** | legacy GET 제거 후 정본 POST 기준, `phase7_latency_recheck_20260813.md:23` |
| SSE 전체 응답 P95 6.39초 | **8.129초** | 같은 문서 `:24` |
| 전량 테스트 748 passed | **965 passed / 2 skipped** | `2026-08-13_next_session_todo.md:32` |
| 공고 5,461,079행 / 낙찰 3,405,928행 | 2026-08-04 시점 값. 이후 백필 20,602건 적재 | `2026-08-13_future_work_backlog.md:52` |
| Servc 수집 복구가 P0 차단 | 백필과 누락일 회복 계약 **완료**, 3회 연속 실행 관찰만 잔여 | 같은 문서 2.1~2.3 |

`docs/changelogs/work_log.md` 의 최신 기록이 748 에 멈춰 있는 것은 분석의 오류가
아니라 **실재하는 문서 동기화 부채**입니다. 갱신 대상입니다.

---

## 3. 전제가 누락된 권고

### 3.1 Cnstwk 전용 모델 즉시 착수

데이터 규모가 1,358,882행이라는 점은 정확하지만 선행 조건 두 개가 빠졌습니다.

| 선행 조건 | 현재 상태 |
| --- | --- |
| 학습 프레임 재생성 | `data/feature_store/dataset_Cnstwk.parquet` 이 구형 12컬럼이라 `lwlt_rate` 포함 16필드 결손 |
| 서빙 라우팅 갱신 | `src/ml/model_registry.py:51` `CATEGORY_DEFAULT_MODELS` 에 Cnstwk 없음. 학습 맵 `src/ml/trainer.py:125` 에만 `cnstwk_institution_v1` 등록 |

학습만 수행하면 산출물이 레지스트리에 등록되어도 서빙 경로는 계속 범용 `v25` 를
씁니다. 이 비대칭은 `src/ml/trainer.py:118` 에 의도된 상태로 기록돼 있습니다.
착수 시 두 맵을 함께 바꾸고 동등성 회귀를 추가해야 합니다.

### 3.2 React 레거시 제거

`docs/design/FRONTEND_DECISION.md:15` 의 결정은 폐기가 아니라 **레거시 스캐폴드
보존, 신규 개발 중단**입니다. 같은 문서 `:95` 에 따라 Compose 에서
`profiles: ["legacy"]` 로 기본 기동에서 이미 제외돼 있습니다. `frontend/src` 에는
`sseParser`, `chatStreamHandler` 테스트 11건이 살아 있습니다.

따라서 디렉터리 삭제는 기록된 결정을 되돌리는 사용자 판단 사항입니다. 다만 CI 부채
지적은 유효합니다. `.github/workflows/ci.yml:42` 는 `package-lock.json` 미추적
때문에 `npm ci` 를 쓸 수 없어 `npm install` 로 동작합니다.

---

## 4. 확인 결과 정확했던 서술

코드를 직접 열어 대조한 결과 다음은 사실입니다.

| 항목 | 확인 위치 |
| --- | --- |
| KB 증분 upsert 및 대량 삭제 안전장치 | `src/app/services/kb_builder.py:62` `MAX_REMOVAL_RATIO = 0.5`, `:528` 비율 검증 |
| Chroma embedding function 정합성 방어 | `src/rag/vector_store.py` |
| 승격 게이트와 `PromotionRejected` | `src/ml/promotion.py` |
| 학습·추론 특징 괴리 경고 | `src/ml/predictor.py` |
| 다중 워커 기각 사실 | `docker-compose.yml:6-26`, `WEB_CONCURRENCY` 기본값 1 |
| Ollama 호스트 의존(비밀폐 배포) | `docker-compose.yml:51`, `:103` `host.docker.internal:11434` |
| production 설정 검증 | `src/app/core/config.py` |
| 테스트 파일 77개 | `tests/` 의 `test_*.py` 실측 77개 |
| Servc 운영 기준선 | `docs/servc_model_status.md:6` MAE 1.4050, 0.5%p 적중 64.97%, 구간 폭 1.6706, 피복률 89.56% |
| OOS 게이트 3,098건 | `docs/servc_model_status.md:29` |
| Thng 재측정 수치 | `docs/design/thng_retraining_20260806.md:58-60` |
| 학습 라우팅 결함 발견·수정 | `docs/design/category_model_coverage_20260810.md:76` |

### 4.1 유효한 신규 지적 — ML 지표 아티팩트 불일치

분석 16절의 지적은 타당합니다. `docs/design/category_model_coverage_20260810.md:136`
은 물품 승격본의 운영 경로 품질을 미확인으로 두는데,
`docs/design/thng_retraining_20260806.md:58` 에는 승격 후 재측정 수치가 있습니다.
`ml_registry/` 를 훑으면 `metrics.json` 은 `quantum_leap_v25_pro/v25_pro_latest`
하나뿐이고 서빙 측정 아티팩트가 없습니다.

권고안(모델 디렉터리를 지표의 단일 진실 원천으로 삼고 문서는 이를 렌더링)은 채택
후보로 남깁니다. 우선순위는 P1 성능·Windows 뒤입니다.

---

## 5. 교정된 실행 순서

| 순서 | 작업 | 분석 원안과의 차이 |
| ---: | --- | --- |
| 1 | P1 예측 c10 프로파일링 (실행기 큐 대기, `src/ml/predictor.py` 내부) | 원안은 컷오버 이후 과제로 뒤로 미룸. 실제로는 차단 요인 |
| 2 | Windows Docker Desktop 전체 스택 검증 | 동일 |
| 3 | 문서 동기화 (`work_log`, README G3 세분, Thng 서빙 아티팩트) | 원안의 README 수정 방향을 반대로 교정 |
| 4 | 수집 3회 연속 일일 실행 관찰 | 원안은 수집 복구 자체를 미완으로 봄 |
| 5 | 운영 컷오버 | 1 번 완료가 선행 조건 |
| 6 | OOS 3,098건 축적 후 현 Champion 평가 | 동일 |
| 7 | Cnstwk parquet 재생성 여부 사용자 결정 | 원안은 선행 조건 두 건을 누락 |

프로세스 증설은 기각 목록에 고정합니다. 요청 배칭, 모델 호출 벡터화, 용량 제한 중
실측 근거가 가장 강한 후보 하나만 선택합니다.

`02:00 cron 중복 검증`은 목록에서 삭제합니다.

---

## 6. 이 검증의 한계

| 수행 | 미수행 |
| --- | --- |
| 코드·문서 정적 대조 | Docker Compose 시동 및 컨테이너 실측 |
| 스케줄·워커 테스트 18건 단독 실행 | 전량 pytest 재현 |
| 레지스트리 디렉터리 실물 확인 | 예측 P95 재측정 |

검증 시점에 Docker 데몬이 기동돼 있지 않아 동적 검증 범위를 위 표로 한정했습니다.
965 passed 는 문서 기록이며 이 검증에서 재현한 값이 아닙니다. 전량 회귀와 성능
재측정은 P1 착수 Task 에서 공유 자원을 단독 점유한 상태로 수행합니다.

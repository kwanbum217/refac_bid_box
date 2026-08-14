# 추후 작업 정본 백로그

> **작성일**: 2026-08-13
> **기능 기준 커밋**: `main` `d82a638`
> **상태**: 현재 정본. 다음 세션은 이 문서부터 읽습니다
> **범위**: 아직 끝나지 않은 실행 과제, 선행 조건, 완료 기준, 사용자 결정
> **대체 문서**: [`2026-08-13_next_session_todo.md`](2026-08-13_next_session_todo.md)
> **세션 인수인계**: [`2026-08-13_gpt_coordination_handoff.md`](2026-08-13_gpt_coordination_handoff.md)

---

## 0. 판정 요약

새 기능을 바로 늘리기보다 **수집 복구 -> 실측 컷오버 -> OOS 판정** 순서로
진행합니다. 현재 최우선 문제는 모델 아이디어 부족이 아니라 2026-08-04 이후
데이터 수집 공백입니다.

| 우선순위 | 작업 묶음 | 현재 상태 | 다음 게이트 |
| --- | --- | --- | --- |
| P0 | Servc 수집 복구와 누락일 회수 | 백필·자동 회복 계약 완료, 안정화 관찰 잔여 | 연속 수집 성공 확인 |
| P1 | Phase 7 컷오버 차단 해소 | 마이크로배칭 병합. c10 P95 중앙값 107.6ms(67.0/107.6/163.3), p50 151.24 -> 38.7~42.7ms. 프로세스 증설 기각 | tail 변동 원인 특정 후 100ms 이하 안정 실측, Windows 전체 스택 통과 |
| P2 | Servc OOS 검증과 재학습 판단 | 유효 OOS **1,342건**(2026-08-14 실측, 08-03 공고 백필 반영). 2건은 백필 이전 낡은 수치 | 유효 3,098건 축적 뒤 현 Champion부터 평가. 약 12.9영업일 예상 |
| P3 | 모델 연구·제품 범위 결정 | 대부분 대기 | P0~P2 완료 또는 명시적 사용자 우선순위 변경 |
| P4 | 저장소·Orca 잔여물 정리 | MySQL 8 UUID 교정 완료, 로컬 전용 브랜치 2개 존재 | 고유 변경 감사 후 이식 또는 폐기 |

세션 종료의 정확한 Git·Docker·Orca 상태와 다음 Task 사양은
[`2026-08-13_gpt_coordination_handoff.md`](2026-08-13_gpt_coordination_handoff.md)에
기록했습니다. 다음 세션은 기존 Orca Run을 재사용하지 않고 새 Run을 만듭니다.

---

## 1. 다시 착수하지 않을 완료·기각 항목

| 항목 | 판정 |
| --- | --- |
| Servc 비예가 서빙 라우팅 | 완료. 명시적 비예가 Servc는 API 422로 차단하고 챗봇 도구도 같은 판정을 사용합니다 |
| 하한율 결측 메커니즘 재분해 | 완료. 2025-01 이후 제도적 부재 99.98%, 미분류 9건으로 기존 결측 지시자가 충분합니다 |
| 전환 없는 제도 플래그 3종 추가 | 기각. 홀드아웃 평균 -0.0068로 분할 산포 0.0074 안입니다 |
| 후보 A: LightGBM `n_jobs=1` | 채택. warm c10 P95를 627.0ms에서 193.09ms로 낮췄습니다 |
| 후보 B: 특징 맵 중복 제거 | 구현 유지. 동등성·중복 제거는 유효하지만 P95 개선 가설은 기각됐습니다 |
| legacy GET SSE 제거 | 완료. 정본 POST SSE 첫 토큰 P95 1.721초, 전체 P95 8.129초로 목표를 통과했습니다 |

닫힌 모델 축 전체 목록은 [`../servc_model_status.md`](../servc_model_status.md)와
`servc-model-tuning` 스킬의 기각 목록을 따릅니다.

---

## 2. P0 — Servc 수집 복구

### 2.1 실행일까지 일회성 백필

**완료되었습니다.** `20260804`~`20260813` 구간, 공고·결과 전 카테고리 합계
**20,602건** 신규 적재. 중복 없음(INSERT IGNORE 멱등성 확인).

### 2.2 상시 수집의 누락일 회복 계약

**완료되었습니다.**

`src/app/services/collector_service.py` 에 `resolve_collection_window` 함수와
`MAX_CATCHUP_DAYS = 7` 상수가 추가되었습니다. 날짜를 명시하지 않으면 DB에서
카테고리별 최신일 중 가장 오래된 것(MIN of MAX per category)을 체크포인트로
삼아 어제까지의 공백을 최대 7일 범위에서 자동 회수합니다. INSERT IGNORE 기반
이므로 동일 범위 재실행은 멱등합니다. 7일을 초과하는 공백은
`scripts/backfill_from_g2b.py` 로 수동 채웁니다.

구현 결정 사항:

| 결정 | 내용 |
| --- | --- |
| 자동 회수 상한 | 7일. API 과부하와 수집 시간 예산 기준 |
| 체크포인트 방식 | MIN(MAX per category) — 공고/결과 두 타입 중 더 오래된 쪽을 전체 체크포인트로 사용 |
| 카테고리 필터 | resolve_collection_window 에 target_categories 를 먼저 결정해 전달 |
| 누락 카테고리 처리 | 요청 범주 중 DB 에 없는 범주가 있으면 max_catchup_days 창으로 fallback |
| API rate limit | MAX_CONCURRENT=16 (api_collector.py 기존 설정 유지) |
| 멱등성 | INSERT IGNORE: 동일 범위 재실행 안전 |
| 스키마 변경 | 없음. 기존 bid_ntce_dt, rl_openg_dt 컬럼 사용 |
| 부분 실패 가시성 | metrics["categories"][cat]["announcement_error"|"result_error"] 기존 유지 |

테스트 19개 추가: `tests/test_collector_catchup.py`
(하루/나흘 중단, 공고·결과 교차 최솟값, 느린 카테고리 공백 보호, subset 카테고리,
없는 카테고리 fallback, 부분 실패 재시도, 동일 범위 재실행 멱등성, 명시적 날짜 bypass)

### 2.3 수집 안정화 관찰

백필 한 번으로 완료를 선언하지 않습니다. 정기 실행이 연속 성공하고 최신
공고일·개찰일·라벨 수가 전진하는지 관찰합니다. 관찰 기간과 성공 횟수는 구현
Task에서 고정하며, 실패 알림과 수동 재실행 절차를 문서화합니다.

다음 Task에서 고정할 권장 계약은 **3회 연속 일일 실행**입니다. 각 실행마다
`PipelineExecution`, 범주별 수집 건수·오류, 최신 공고일·개찰일, Servc 유효
라벨 수를 전후 비교합니다. 관찰 기간이 지나기 전에는 P0 안정화 완료로 선언하지
않습니다.

---

## 3. P1 — Phase 7 컷오버 차단 해소

### 3.1 `/predict` warm 동시성 병목

계측 반영 후 실제 Docker 단일 워커 warm `/predict`를 각 동시성에서 100회
재측정했습니다.

| 동시성 | P95 | 오류 |
| ---: | ---: | ---: |
| 1 | 16.1358ms | 0 |
| 2 | 31.2996ms | 0 |
| 4 | 58.4468ms | 0 |
| 10 | **199.1758ms** | 0 |

`/predict`와 `/predict-price`에는 wall/thread CPU/model 구간 계측이 들어갔고,
원시 결과는 `data/benchmarks/phase7_predict_instrumented_c{1,2,4,10}_20260813.json`에
보존했습니다.

Uvicorn 3워커는 실제 Docker c10 P95 127.32ms(반복 151.82/135.33ms), 4워커는
165.92ms로 모두 100ms 목표에 실패했습니다. 메모리도 각각 1.259GiB와
1.603GiB였습니다. 따라서 다중 워커 기본값 후보는 기각했고
`WEB_CONCURRENCY` 기본값을 1로 복원했습니다. 조정 기능은 수동 실험용으로만
유지합니다. 상세는
[`../ops/uvicorn_worker_scaling_candidate_20260813.md`](../ops/uvicorn_worker_scaling_candidate_20260813.md)를
따릅니다.

다음 작업은 현재 계측을 바탕으로 실행기 큐 대기와 `src/ml/predictor.py` 내부
모델별 호출을 최소 추가 계측합니다. 프로세스 증설은 기각 목록으로 고정하고,
요청 배칭·모델 호출 벡터화·용량 제한 중 실측 근거가 가장 강한 후보 하나만
선택합니다.

완료 기준은 다음과 같습니다.

- 동일 데이터와 100회 이상 표본으로 warm c10 P95 100ms 이하
- HTTP·예측 오류 0건
- c1/c2/c4 성능 역행 없음
- 새 코드가 기존 Thng·Servc·fallback 예측 동등성을 보존
- 결과를 `data/benchmarks/`와 `docs/ops/`에 기록

### 3.2 `/predict-price` Servc 실측

실제 Servc 운영 경로의 cold 및 warm c10 기준선은 아직 없습니다. 먼저 이를
측정하고 `/predict` 결과를 대신 사용하지 않습니다. 첫 요청 분위 모델 프리로드
후보 D는 cold 병목이 확인될 때만 검토합니다. 반복 이력 조회 인덱스 후보 E는
DDL·스키마 변경이므로 사용자 승인과 데이터 보존 검증 전에는 실행하지 않습니다.

### 3.3 Windows 전체 스택 검증

CI의 Windows Python 검증은 통과했지만 Windows Docker Desktop 전체 스택은
실행하지 않았습니다. 실제 Windows 호스트에서 다음을 완료해야 합니다.

```powershell
powershell -ExecutionPolicy Bypass -File scripts/validate_windows.ps1
```

Docker Compose 시동, 헬스체크, 데이터 무손실, 백엔드·프런트 회귀와 종료·재시동을
모두 증빙해야 G2 컷오버를 통과합니다.

### 3.4 운영 CORS·쿠키 결정

운영 배포 도메인과 프런트·API 토폴로지를 먼저 확정하고
`CORS_ALLOWED_ORIGINS`에 정확한 허용 출처를 설정합니다. 쿠키의 현재
`SameSite=lax`(`src/app/api/v1/accounts.py:141`)는 잘못이라고 단정하지
않습니다. 교차 사이트 인증이 필요한지에 따라 CORS·Secure·SameSite 조합을
함께 결정하고 회귀 테스트를 갱신합니다.

---

## 4. P2 — OOS 검증과 재학습 판단

### 4.1 OOS 축적 게이트

0.10%p 평균 편향을 판별하는 최소 유효 표본은 3,098건입니다.

2026-08-14 실측으로 갱신했습니다. 필터 통과 유효 OOS 는 **1,342건**이고 유입률은
영업일당 **136.0건**입니다. 잔여 1,756건은 약 **12.9영업일**(2026-09-02 전후)입니다.
08-03 공고 백필로 조인 실패 106건을 전량 회수해 +148건이 즉시 편입됐습니다.
하루 220건 전제는 실측 136.0건으로 대체됩니다. 근거는
[`2026-08-14_servc_oos_filter_diagnosis.md`](2026-08-14_servc_oos_filter_diagnosis.md)입니다.

### 4.2 격리 feature store와 현 Champion 평가

3,098건이 모이면 별도 출력 디렉터리에 feature store를 재생성합니다. 운영
`data/feature_store/`를 먼저 덮어쓰지 않습니다. 컷 이전 학습 Champion으로 컷
이후 OOS 잔차를 측정하며 다음 기준을 사전에 고정합니다.

- MAE
- 평균 편향과 부호
- 0.5%p 적중률
- 기존 운영 기준선과의 쌍대 비교

현 Champion의 OOS 판정이 나오기 전에 재학습이나 승격으로 문제를 덮지 않습니다.

### 4.3 주간 재학습 재개 여부

기본 Compose의 `ML_WEEKLY_RETRAIN_ENABLED=false`(`docker-compose.yml:87`)는
유지합니다. 수집 안정화와 OOS 판정 뒤에만 자동 재학습 활성화, 수동 유지 또는
조건부 실행 중 하나를 결정합니다.

### 4.4 조건부 모델 연구

다음 축은 즉시 착수하지 않는 저우선 연구입니다.

| 축 | 재개 조건 |
| --- | --- |
| `rbidPermsnYn` 결측 수준 정규화 | P0~P2 뒤에도 잔차 편향이 남을 때 |
| `prearng_mthd`와 결측 지시자 공선성 | 새 OOS에서 정보 중복 여부를 다시 판단할 근거가 생길 때 |
| 2025-01 전환 신규 6개 raw 필드 | 표기 이동과 실질 제도 변화를 먼저 분류할 수 있을 때 |
| `prdctClsfcLmtYn` 체제 지시자 | 해당 필드를 실제 후보에 포함할 때만 |
| 적격심사제 계열 피복률 | 재학습이 실제 수행된 뒤 부호 유지 재확인 |

모든 특징 후보는 다중 분할 개선이 0.0074를 넘고 분할별 부호가 일치해야 운영
쌍대 검정으로 보냅니다.

---

## 5. P3 — 사용자 결정이 필요한 제품 범위

| 항목 | 현재 근거 | 결정 |
| --- | --- | --- |
| Cnstwk 전용 모델 | 1,358,882행이 있으나 현재 범용 5특징 v25 사용 | 전용 학습·등록에 자원을 배정할지 결정 |
| Thng 후속 | 재생성 검증 완료, 실익 후보는 `ntce_kind_nm`, `bid_methd_nm` | Servc·컷오버보다 앞당길지 결정 |

기본 순서는 Servc와 Phase 7 완료 뒤입니다.

---

## 6. P4 — 저장소와 Orca 잔여물

### 6.1 이 저장소의 로컬 브랜치

| 브랜치 | 처리 원칙 |
| --- | --- |
| `feat/codex-task-routing` | `70bd666`의 Codex 작업 라우팅 고유 후보를 현행 12개 스킬 체계와 파일별 재감사한 뒤 필요한 최소 변경만 이식 |
| `integrate/arq-worker-cutover` | MySQL UUID 고유 후보는 `5f52ba1`로 최신 `main`에 재구현 완료. 나머지는 이미 흡수된 누적 변경이 많으므로 전체 병합 금지, 잔여 고유 변경만 확인 후 처분 |

두 브랜치는 원격에 없으며, 감사 전 병합하거나 삭제하지 않습니다.

### 6.2 저장소 밖 Orca 변경

Orca 저장소의 로컬 브랜치 `kwanbum217/antigravity-usage-status`에는 Antigravity
사용량 표시 변경 커밋 `88e37b6`이 있습니다. 유일한 로컬 사본이므로 삭제하지
않습니다. Orca `origin/main` 최신점에 재배치하거나 필요한 커밋만 이식한 뒤
단위 테스트, 타입 검사, 린트와 Electron UI Playwright를 다시 실행합니다.

이 항목은 `refac_bid_box`와 별도 저장소 작업이며 별도 Task·작업 트리에서
수행합니다.

---

## 7. 의존성과 권장 실행 순서

| 순서 | Task | 선행 조건 | 후속 개방 |
| ---: | --- | --- | --- |
| 1 | P0 백필 실행 | 외부 API·DB 쓰기 승인 | 수집 결과 검증 |
| 2 | 누락일 회복 계약 구현 | 백필에서 확인한 실패 형태 | 정기 수집 관찰 |
| 3 | 수집 안정화 관찰 | 구현 배포·시동 | OOS 표본 축적 |
| 4 | P1 예측 프로파일링·개선 | 공유 벤치마크 자원 확보 | 성능 컷오버 판정 |
| 5 | Windows 전체 스택 | 실제 Windows 호스트 | G2 판정 |
| 6 | 운영 CORS·쿠키 | 배포 토폴로지 결정 | 운영 보안 설정 확정 |
| 7 | OOS 평가 | 유효 3,098건 | 재학습·모델 연구 결정 |
| 8 | P3 제품 범위 | 사용자 우선순위 | Cnstwk·Thng 착수 |

P0의 관찰 기간과 P1의 독립 프로파일링은 공유 DB·Docker·대량 학습 자원을
동시에 쓰지 않는 범위에서 병행할 수 있습니다. 실제 다중 에이전트 실행 때는
`orca-section-coordination` 스킬로 Run·Task 의존성과 공유 자원을 등록합니다.

---

## 8. 다음 세션 첫 작업

1. 이 문서와 [`2026-08-13_gpt_coordination_handoff.md`](2026-08-13_gpt_coordination_handoff.md),
   [`2026-08-13_servc_oos_readiness_gate.md`](2026-08-13_servc_oos_readiness_gate.md),
   [`../ops/uvicorn_worker_scaling_candidate_20260813.md`](../ops/uvicorn_worker_scaling_candidate_20260813.md)를 읽습니다.
2. `main`·`origin/main` 동기화와 미커밋 변경을 확인합니다.
3. 새 Orca Run을 만들고 P0 안정화 관찰과 P1 프로파일링을 별도 Task로 등록합니다.
4. P0는 관찰 횟수·기간을 먼저 고정하고, P1은 Docker·서빙 모델 공유 자원을 단독 점유합니다.
5. 성능 작업을 병행한다면 별도 작업 트리와 별도 Docker 시간대를 배정합니다.

정적 토큰 잔량이나 특정 시각의 모델 한도는 이 문서에 기록하지 않습니다.
실행 시점의 가용 모델과 한도를 확인하되, 통계 판정은 고추론 모델, 기계적 검증은
빠른 모델, 최종 병합 판단은 코디네이터 직접 diff·테스트 확인으로 수행합니다.

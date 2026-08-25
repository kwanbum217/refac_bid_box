# 프로젝트 현재 운영 상태 정본 (CURRENT_STATE)

> **updated_at**: 2026-08-24
> **source_commit**: `1b8a77a`
> **version**: v1.0.0
> 코디네이터가 부트스트랩 시 가장 먼저 읽는 **현재 운영 상태 정본**입니다. 과거 handoff 는 증거이며, 즉시 판단과 정책 결정은 본 문서를 기준으로 합니다.

---

## 1. 3대 목표 게이트 상태 (Gates)

| 게이트 | 목표 정의 | 현재 판정 | 상세 상태 및 조건 |
| --- | --- | :---: | --- |
| **G1** | 데이터 무손실 | **통과 (불변)** | MySQL 8 스키마·행 수 보존, ML 가중치 체크섬 일치, ChromaDB `bidding_kb` 무결성 |
| **G2** | 크로스 플랫폼 | **부분 통과** | 2026-08-24 **main 병합 검증 run** `32703990405`(`a203286`)에서 ubuntu·macOS·**windows-latest 전부 green**입니다. 앞선 feature 브랜치 사전 검증 run `32703096829`(`bd6212c`)도 동일 green 이며, 실패 원인 4종(`os.getloadavg` 부재, Capsule 경로 역슬래시 생성, 테스트 기대값 역슬래시, macOS 러너 Docker 부재)을 수정한 결과입니다. Windows Docker Desktop 실기는 장비 부재로 미수행입니다 |
| **G3** | 스택 최적화 | **부분 통과·승격 보류** | 예측 c1 **통과**(P95 15.39ms), c4 **통과**(통제 A/B worst P95 34.32ms <= 36.81ms, 기존 +10% 기준 적용, >50ms 0건), c10 **통과**(`freeze` P95 47.77ms, >100ms 0/1,800), SSE c1 **통과**(첫 토큰 1297.73ms, 전체 6716.22ms). 통제 A/B 5회 교차 검증에서 이전 c2·c4 임계치 미달은 미재현입니다. `+2.0ms` 쌍대 예산은 prospective 지표로 별도 관리합니다. G3 전체 컷오버는 잔여 항목 검증 후 별도 판정 |

> **주의**: G3 는 일괄 통과로 선언하지 않고 항목별 실측 상태로 기록합니다.

---

## 2. 최신 성능 지표 정본 (Current Metrics)

[`latency_gate_protocol.md`](../ops/latency_gate_protocol.md) 규약(표본 수, warmup 제외, 3회 최악값, 주변 부하 기록)에 따른 실측값만 유효합니다.

### 2.1 예측 API 레이턴시 지표

- **운영 설정**: `PREDICTION_GC_MODE=freeze` (`gc.freeze()` 로 gen2 GC 순회 배제)
- **부하 조건**: warmup(동시성 수) 제외, 회차당 600표본, 3회 반복 중 최악 대표값

| 동시성 | P50 (ms) | P95 (ms) | P99 (ms) | Max (ms) | 100ms 초과 | 회귀 판정선 (P95 +10% 및 쌍대 예산) |
| ---: | ---: | ---: | ---: | ---: | ---: | :---: |
| **c1** | 12.18 | **15.39** | 18.01 | 27.96 | 0건 (1,800회) | **통과**: 17.02ms |
| c2 | 17.62 | **22.68** | 26.67 | 28.81 | 0건 (1,800회) | **미달**: 21.77ms (통제 A/B는 -0.97ms 중앙 델타) |
| **c4** | 28.83 | **34.32** | 38.55 | 44.06 | 0건 (3,000회) | **통과**: 36.81ms (기존 +10% 기준, >50ms 0건; c4 PASS 판정선에는 +2.0ms 쌍대 예산 미포함) |
| **c10** | **38.63** | **47.77** | **68.30** | **74.42** | **0건 (1,800회)** | **통과**: 100ms 이하 |

> **구형 기록 주의**: `README.md` 의 199.18ms 는 구형입니다. c10 정본 기준선은 **56.45ms** (재측정 최악 47.77ms).

### 2.2 하이브리드 RAG SSE 스트리밍 지표

- **부하 조건**: 회차당 60표본, 3회 반복, warmup 제외, 주변 부하 중앙 13.8% / 최대 27.8% (규약 통과)

| 지표 | 정본 대표값 (3회 최악) | 목표 기준 | 판정 | 회귀 판정선 (+10%) |
| --- | ---: | ---: | :---: | ---: |
| 첫 토큰 P95 (c1) | **1297.73ms** | 3,000ms 이하 | **통과** | 1674.65ms |
| 전체 스트리밍 P95 (c1) | **6716.22ms** | 20,000ms 이하 | **통과** | 8854.57ms |
| c4 첫 토큰 P95 | 18086.00ms | 기준 없음 | 판정 불가 | Ollama 직렬화 |

---

## 3. 기각 및 반복 금지 목록 (Do Not Repeat)

상세 근거는 [`../ops/orca_do_not_repeat.md`](../ops/orca_do_not_repeat.md) 7장입니다.

| 금지 항목 | 결론 |
| --- | --- |
| 기각된 성능 실험 재시도 | Uvicorn 증설, `GC_MODE=batch-disable`, `GC_MODE=threshold`는 기각 |
| README 성능 수치 기록 | 1·2장이 정본이며 README에는 기록하지 않음 |
| `--inject`·요약만으로 완료 판단 | `terminal read`, diff, 검증 결과를 직접 대조 |
| Capsule·보고 경로 공유 또는 완료 Task 재사용 | Task·Dispatch마다 독립 경로와 새 Task/ready 복귀 사용 |
| 파이프라인 종료 코드·비표준 계약 필드 신뢰 | 게이트 도구와 계약 필드만 사용 |

---

## 4. 현재 진행 과업 및 우선순위 (Active Priorities)

1. **운영 검증**: Windows CI는 **main 병합 검증 run** `32703990405`(`a203286`)에서 green을 실측 확인했습니다(사전 feature run `32703096829`도 green). Windows Docker Desktop 실기가 남았습니다.
1-2. **LLM 경로 최적화**: 부하 규약을 지킨 조건의 e4b 정본은 `llm_ms` P50 2,839.93ms이며 총합의 97.5%입니다. `gemma4:e2b` 비교에서 `llm_ms` P50 -54.1%, P95 -26.2%로 속도 우세가 확정됐으나 **품질 표본이 5문항뿐이라 승격하지 않았습니다**. 19문항 fixture 로 실측한 결과 지연은 P50 -43.9%/P95 -57.7% 로 개선되나 품질 지표가 검색에 지배되어 생성 품질을 변별하지 못했습니다. 의도 라우팅 오분류로 16문항 중 8문항이 KB 검색을 건너뜁니다([`llm_model_comparison_e4b_e2b_20260824.md`](../analysis/llm_model_comparison_e4b_e2b_20260824.md)).
1-1. **Arq 정식 기준선**: 2026-08-24 경로별 10회 캘리브레이션으로 정식 기준선을 확정했습니다. In-Process 1,195.59 jps / 480.42ms, Container 1,756.94 jps / 327.06ms (CV 1.7% 이하, 규약 위반 0건). `arq_gate.py` 의 잠정값 900/600 은 경로별 판정선(1,123.85·509.25 / 1,651.52·346.68)으로 교체했습니다([`arq_baseline_calibration_20260824.md`](../analysis/arq_baseline_calibration_20260824.md)).
2. **프론트엔드 ADR 이행**: [`FRONTEND_DECISION.md`](../design/FRONTEND_DECISION.md)의 목표는 SSR + HTMX이나 실제 템플릿은 jQuery 3.7.1만 로드하고 HTMX 사용이 0건입니다. 도입 또는 ADR 개정 중 하나를 택해야 합니다.
3. **G3 전체 컷오버 판정**: 위 항목이 닫힌 뒤 별도로 판정합니다. 개별 게이트 PASS를 컷오버 PASS로 승격하지 않습니다.

### 4.1 종결 계열 요약

상세 기전·반복 금지는 [`../ops/orca_do_not_repeat.md`](../ops/orca_do_not_repeat.md) 참조.

- **안전·품질 게이트**: fail-open 제거, 상태 전파 경계, frontend·Docker·CI 검증 능력과 `source_commit` 신선도 게이트를 갖췄습니다.
- **구조·데이터**: 9개 모듈을 AST 동일성으로 분할했고 ORM 13모델·137컬럼을 `Mapped[]`로 전환했습니다. DDL 지문은 불변입니다.
- **실측·계측**: 예측 웜 P95 정본은 위 2·3장의 재측정값(c1 15.39ms, c4 34.32ms, c10 47.77ms)이며 SSE c1 첫 토큰 1297.73ms·전체 6716.22ms입니다. 블로킹 I/O와 Arq 계측 배선은 완료했고 최적화 판정은 미확정입니다.
- **조율 인프라**: 워커 준비 안전성(Git common directory 검증), ModelRegistry single-flight(로드 1회·부분 레지스트리 비노출), finalize/Level 1 PASS 없는 병합 차단을 닫았습니다. 벤치마크 provenance 는 `base_url`↔컨테이너 결박, 시작·종료 교체 무효화, bind mount 런타임 소스 revision·dirty 거부까지 결박했습니다. Arq 하네스 2종의 provenance 헬퍼는 공통 모듈로 단일화했고 Redis 대상은 fail-closed 결박입니다.
- **신뢰 설정 잠금**: PID 파일의 `stat`·`unlink` stale 회수는 제거했고 POSIX `fcntl.flock`, Windows `msvcrt.locking` advisory lock으로 교체했습니다. 지원 구현이 없는 플랫폼도 fail-closed로 중단합니다. 코드와 회귀 테스트는 완료했으며 수정 후 원격 Windows CI 확인은 별도입니다.
- **운영 준비**: 워커 기동 자동화, mypy·bandit·CI 게이트, 프론트엔드 lockfile·`npm ci`를 반영했습니다.

---

## 5. 핵심 불변 원칙 (Critical Invariants)

- **데이터 무손실 (G1)**: 기존 DB 테이블명·컬럼명·타입 변경 절대 금지.
- **Train/Serve 단일화**: 특징 생성은 [`src/ml/features.py`](../../src/ml/features.py) 단일 함수만 사용.
- **게이트 규약 준수**: [`latency_gate_protocol.md`](../ops/latency_gate_protocol.md) 미준수 수치는 양방향 무효.
- **1인 작업 Git**: PR 없음. 작업 브랜치 검증 통과 후 `main` 에 `git merge --no-ff`.
- **이모지 절대 금지**: 주석, 커밋 메시지, 문서 등 모든 산출물.

---

## 6. 미해결 사항 및 갱신 규약 (Unknowns & Protocol)

### 6.1 알려진 미해결 사항 (Unknowns)

- Windows Docker Desktop 실기 검증 미수행.
- Ollama `gemma4:e4b` Predict c4 + SSE c1 + Query c1을 2026-08-24에 부하 규약(median 30%/max 50%) 준수 상태로 3회 측정했습니다. 1차 r2는 median 34.26%로 기각하고 재측정했습니다. 게이트는 전 항목 통과입니다.
- Arq Docker-container **synthetic** 3회를 2026-08-24에 재측정해 회차별 raw를 보존했습니다(1,681~1,764 jobs/sec, P95 325~342ms). 측정 중 회차별 raw가 자기 dirty 검사를 유발해 `--repetitions`가 완주 불가였던 결함을 고쳤습니다. 잠정 봉투는 2026-08-24 정식 캘리브레이션 폐기, 경로별 임계값 사용, production business-task E2E 미측정.
- 벤치마크 provenance 는 측정 시작·종료 양쪽을 결박해 대상 교체 시 strict 에서 fail-closed 로 무효화합니다([`prov_start_end_invalidation_20260823.md`](../analysis/prov_start_end_invalidation_20260823.md)). `--allow-unknown-provenance` 로 strict 를 끈 측정은 `provenance_consistent: false` 로 기록되며 정본 evidence 가 아닙니다.

### 6.2 정본 갱신 규약 (Update Protocol)

- **동기 갱신**: 운영 지표, 게이트 판정, 불변 사실이 바뀌면 그 커밋에 본 문서 갱신을 포함합니다.
- **간결성 유지**: 실험 로그나 분석 과정을 적지 않고 결론과 수치만 요약합니다 (8,000자 이내).
- **진실 우선순위**: `실제 코드 / 실측 아티팩트 > CURRENT_STATE.md > README.md > 과거 handoff`

---

## 7. 증거 경로 참조 (Evidence Pointers)

- v2 설계: [`docs/ops/orca_coordinator_token_optimization_v2.md`](../ops/orca_coordinator_token_optimization_v2.md), 제어 평면: [`orca_control_plane_tools.md`](../ops/orca_control_plane_tools.md)
- 지표 원장: [`orca_v2_metrics_ledger.md`](../ops/orca_v2_metrics_ledger.md)
- 레이턴시 게이트 규약: [`latency_gate_protocol.md`](../ops/latency_gate_protocol.md)
- 예측 재측정(2026-08-22): [`predict_remeasurement_20260822.md`](../ops/predict_remeasurement_20260822.md)
- 예측 통제 A/B(2026-08-22): [`predict_ab_20260822.md`](../ops/predict_ab_20260822.md)
- 블로킹 I/O 계측: [`predict_coldstart_instrumentation.md`](../analysis/predict_coldstart_instrumentation.md), [`query_rag_latency_instrumentation.md`](../analysis/query_rag_latency_instrumentation.md), [`arq_throughput_harness.md`](../analysis/arq_throughput_harness.md), [`arq_throughput_20260823.md`](../analysis/arq_throughput_20260823.md), [`arq_throughput_gate_20260823.md`](../analysis/arq_throughput_gate_20260823.md)
- 워커 기동: [`agent_worker_launch_reference.md`](../ops/agent_worker_launch_reference.md)
- 용역 모델: [`servc_model_status.md`](../servc_model_status.md)
- 미병합 브랜치 판정: [`phase8_predict_tail_merge_verdict_20260814.md`](../ops/phase8_predict_tail_merge_verdict_20260814.md), [`codex_task_routing_branch_verdict_20260814.md`](../ops/codex_task_routing_branch_verdict_20260814.md)

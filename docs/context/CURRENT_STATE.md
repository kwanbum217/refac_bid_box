# 프로젝트 현재 운영 상태 정본 (CURRENT_STATE)

> **updated_at**: 2026-08-28
> **source_commit**: `ba45c1f`
> **version**: v1.0.0
> 코디네이터가 부트스트랩 시 가장 먼저 읽는 **현재 운영 상태 정본**입니다. 과거 handoff 는 증거이며, 즉시 판단과 정책 결정은 본 문서를 기준으로 합니다.

---

## 1. 3대 목표 게이트 상태 (Gates)

| 게이트 | 목표 정의 | 현재 판정 | 상세 상태 및 조건 |
| --- | --- | :---: | --- |
| **G1** | 데이터 무손실 | **통과 (불변)** | MySQL 8 스키마·행 수 보존, ML 가중치 체크섬 일치, ChromaDB `bidding_kb` 무결성 |
| **G2** | 크로스 플랫폼 | **부분 통과** | 2026-08-26 CI run `32930156938`(`5f8174a`)에서 Docker/lint/Ubuntu/macOS/**Windows 5개 job 전부 green**입니다. Windows Docker Desktop 실기는 장비 부재로 미수행입니다 |
| **G3** | 스택 최적화 | **부분 통과** | 예측 c1 **통과**(P95 15.39ms), c4 **통과**(통제 A/B worst P95 34.32ms <= 36.81ms, >50ms 0건), c10 **통과**(`freeze` P95 47.77ms), SSE c1 **통과**(첫 토큰 1297.73ms). `+2.0ms` 쌍대 예산은 prospective 지표로 별도 관리합니다. 전체 컷오버는 잔여 항목 검증 후 판정 |

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

> **구형 기록 주의**: 루트 `README.md` 에는 해당 수치가 없으며 과거 handoff 및 이력 문서에만 남아 있는 199.18ms 는 구형입니다. c10 정본 기준선은 **56.45ms** (재측정 최악 47.77ms).

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

1. **운영 검증**: 2026-08-26 CI run `32930156938`(`5f8174a`) **3플랫폼 green**. Windows Docker Desktop 실기만 남음.
1-4. **Vector fail-closed·정확 제목**: 근거 적중 **16/16**, 기간·기관 post-filter를 유지합니다. 2026-08-27 후보 30건과 공고명 정규화 정확 일치 재순위로 q21 정답을 top-5에 포함했습니다([`task_9fe129597faf.md`](../analysis/task_9fe129597faf.md)).
1-2. **LLM 경로 최적화**: 2026-08-26 v4(`b4913fd`, 각 72회차)에서 **`gemma4:e2b` 승격** ([`llm_quality_v4_e4b_e2b_20260826.md`](../analysis/llm_quality_v4_e4b_e2b_20260826.md)). 2026-08-27 blind fixture v2(32문항) 측정에서 **e2b 승격 유지** 확정(동결 `13f947a`). numeric 양쪽 **87.5% 동률**이며 e2b 가 과잉응답 0 대 1, refusal 8/8 대 7/8, P50 3,990 대 6,459ms 로 앞섭니다. 과잉거절 12.5% 와 P50 은 두 모델 모두 미달이며 원인은 검색 미스 3문항입니다. 1차 측정은 백필 후 KB 미색인으로 **무효**([`llm_generalization_judgment_20260827.md`](../analysis/llm_generalization_judgment_20260827.md)).
1-1. **Arq 정식 기준선**: 2026-08-24 경로별 10회 캘리브레이션 확정. In-Process 1,195.59 jps / 480.42ms, Container 1,756.94 jps / 327.06ms (CV 1.7% 이하). 잠정값 900/600 제거, 기준선은 캘리브레이션 호스트에 결박([`arq_baseline_calibration_20260824.md`](../analysis/arq_baseline_calibration_20260824.md)).
1-3. **감사 후속 P1**: 2026-08-25 에 RAG 라우팅 오분류, 복합 numeric·refusal 미채점, 모델 라벨·Arq 호스트 미결박을 닫았습니다.
1-5. **Servc 운영 경로**: 2025년 300/300건 평가에서 MAE 1.2686, 0.5%p 적중 63.33%, 피복률 89.67%입니다([`servc_api_path_remeasurement_20260826.md`](../analysis/servc_api_path_remeasurement_20260826.md)). 2026-08-27 유효 OOS는 3,589건으로 3,098건 게이트를 충족했습니다.
2. **프론트엔드**: HTMX 를 2026-08-25 기각하고 ADR 을 SSR + Jinja2 + jQuery 로 개정했습니다. `base.html` CDN 7곳에 이어 Chart.js·marked 도 로컬 벤더로 옮겨 **템플릿 외부 참조 0건**이며, Tailwind 는 빌드타임 CSS(44KB)로 전환했습니다.
3. **G3 컷오버 판정**: 위 항목이 닫힌 뒤 판정합니다. 개별 게이트 PASS 를 컷오버 PASS 로 승격하지 않습니다.

### 4.1 종결 계열 요약

상세 기전·반복 금지는 [`../ops/orca_do_not_repeat.md`](../ops/orca_do_not_repeat.md) 참조.

- **안전·품질 게이트**: fail-open 제거, 상태 전파 경계, frontend·Docker·CI 검증 능력과 `source_commit` 신선도 게이트를 갖췄습니다.
- **구조·데이터**: 9개 모듈을 AST 동일성으로 분할했고 ORM 13모델·137컬럼을 `Mapped[]`로 전환했습니다. DDL 지문은 불변입니다.
- **실측·계측**: 예측 웜 P95 c1 15.39ms·c4 34.32ms·c10 47.77ms, SSE c1 첫 토큰 1297.73ms·전체 6716.22ms. 블로킹 I/O·Arq 계측 배선 완료, 최적화 판정 미확정.
- **조율 인프라**: 워커 준비 안전성(Git common directory 검증), ModelRegistry single-flight(로드 1회), finalize/Level 1 PASS 없는 병합 차단을 닫았습니다. 벤치마크 provenance 는 `base_url`↔컨테이너 결박·시작/종료 교체 무효화·런타임 revision·dirty 거부로 결박했습니다. Arq 하네스 2종 헬퍼는 단일화하고 Redis 는 fail-closed 결박입니다.
- **신뢰 설정 잠금**: PID stale 회수 제거, POSIX `fcntl.flock`·Windows `msvcrt.locking` advisory lock으로 교체. 미지원 플랫폼은 fail-closed 중단. 회귀 테스트 완료, 원격 Windows CI 확인은 별도입니다.
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

- Windows Docker Desktop 실기 미검증.
- **LLM 품질 정본은 2026-08-28 현 HEAD 재측정**(동결 `d9a0536`, `gemma4:e2b` 32문항 x 3회)입니다. numeric 95.7%(67/70), evidence recall 0.957, citation 100%, refusal 24/24, 과잉응답 0 으로 2026-08-27 측정 대비 전 지표가 개선입니다. 다만 요청 2/96 이 타임아웃(q03)했고 긴 정확 공고명 질의가 58~180초를 소모하여 **레이턴시 꼬리는 회귀**입니다 ([`blind_fixture_remeasure_20260828.md`](../analysis/blind_fixture_remeasure_20260828.md)). e4b 동일 조건 재측정은 미실시입니다. 지연 정본 판정은 `benchmark_rag_segments.py` 가 담당합니다.
- **정확 제목 lexical 채널 효과 실측**: 느린 4문항(q03·q08·q25·q31) x 3회에서 요청 실패 2/12 -> **0/12**, 대표값 58,352ms -> **5,941ms**, 최대 180,045ms -> 41,874ms 로 꼬리 지연이 제거됐습니다. 정확도 손실은 없습니다([`lexical_channel_latency_effect_20260828.md`](../analysis/lexical_channel_latency_effect_20260828.md)). 같은 부분집합 e4b 대조는 품질 동률에 P50 6,245ms·최대 81,234ms 로 e2b 가 앞서 **e2b 승격 유지 근거가 보강**됐습니다. 부분집합 12회 표본이므로 전량 재측정으로 정본을 갱신해야 합니다.
- Ollama `gemma4:e4b` Predict c4·SSE c1·Query c1 2026-08-24 규약 준수 3회 측정, 게이트 전 항목 통과.
- Arq container synthetic raw 보존(1,681~1,764 jps, P95 325~342ms). **business-task E2E 2026-08-26 실측**: 격리 큐 실제 task 2종 30/30 완주, P50 5.5ms·P95 1,174.9ms, DB 11행 불변·운영 큐 무영향([`arq_business_e2e_20260826.json`](../../data/benchmarks/arq_business_e2e_20260826.json)).
- 벤치마크 provenance 는 시작·종료를 결박해 대상 교체 시 strict 에서 fail-closed 됩니다([`prov_start_end_invalidation_20260823.md`](../analysis/prov_start_end_invalidation_20260823.md)). `--allow-unknown-provenance` 는 정본이 아닙니다.

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
- 블로킹 I/O 계측: `docs/analysis/` 의 `predict_coldstart_instrumentation.md`, `query_rag_latency_instrumentation.md`, `arq_throughput_harness.md`, `arq_throughput_20260823.md`, `arq_throughput_gate_20260823.md`
- 워커 기동: [`agent_worker_launch_reference.md`](../ops/agent_worker_launch_reference.md)
- 용역 모델: [`servc_model_status.md`](../servc_model_status.md)
- 용역 운영 API 경로 재측정: [`servc_api_path_remeasurement_20260826.md`](../analysis/servc_api_path_remeasurement_20260826.md)
- 미병합 브랜치 판정: `docs/ops/` 의 `*_verdict_*.md`. 2026-08-26 arq-cutover 와 베이크오프 9건 판정으로 전량 완결이며 회수 후보는 2건뿐

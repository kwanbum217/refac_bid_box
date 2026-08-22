# 프로젝트 현재 운영 상태 정본 (CURRENT_STATE)

> **updated_at**: 2026-08-22
> **source_commit**: `1f25b7a`
> **version**: v1.0.0
> 코디네이터가 부트스트랩 시 가장 먼저 읽는 **현재 운영 상태 정본**입니다. 과거 handoff 는 증거이며, 즉시 판단과 정책 결정은 본 문서를 기준으로 합니다.

---

## 1. 3대 목표 게이트 상태 (Gates)

| 게이트 | 목표 정의 | 현재 판정 | 상세 상태 및 조건 |
| --- | --- | :---: | --- |
| **G1** | 데이터 무손실 | **통과 (불변)** | MySQL 8 스키마·행 수 보존, ML 가중치 체크섬 일치, ChromaDB `bidding_kb` 무결성 |
| **G2** | 크로스 플랫폼 | **부분 통과** | macOS 완전 검증 완료 (Docker + uv + Makefile). Windows Docker Desktop 실기 검증 대기 |
| **G3** | 스택 최적화 | **부분 통과·승격 보류** | 예측 c1 **통과**(P95 15.39ms), c4 **통과**(통제 A/B worst P95 34.32ms <= 36.81ms, 쌍대 델타 중앙 +1.31ms <= +2.0ms 예산, >50ms 0건), c10 **통과**(`freeze` P95 47.77ms, >100ms 0/1,800), SSE c1 **통과**(첫 토큰 1297.73ms, 전체 6716.22ms). 통제 A/B 5회 교차 검증 결과 이전 c2·c4 임계치 미달 미재현(전 회차 >50ms/>100ms 0건, c2 델타 중앙 -0.97ms). G3 전체 컷오버는 잔여 항목 검증 후 별도 판정 |

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
| **c4** | 28.83 | **34.32** | 38.55 | 44.06 | 0건 (3,000회) | **통과**: 36.81ms (쌍대 델타 중앙 +1.31ms <= +2.0ms, >50ms 0건) |
| **c10** | **38.63** | **47.77** | **68.30** | **74.42** | **0건 (1,800회)** | **통과**: 100ms 이하 |

> **구형 기록 주의**: `README.md` 등에 남은 199.18ms 는 구형이며 c10 정본 기준선은 **56.45ms** (이번 재측정 최악 47.77ms) 입니다.

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

1. **워커 준비 안전성**: Git common directory 검증, 신뢰 설정 잠금·최초 파일·복구를 먼저 닫습니다. 완료 전 병렬 쓰기 워커를 기동하지 않습니다.
2. **ModelRegistry single-flight**: startup warmup·readiness 동시 시작에서 실제 로드 1회와 부분 레지스트리 비노출을 증명합니다.
3. **병합·성능 재현성**: finalize/Level 1 PASS 없는 병합 차단과 prediction 원시 메타데이터를 보완합니다.
4. **예측 A/B 결과 및 c4 판정 기록**: 통제 교차 A/B 5회 검증 결과 c4는 worst P95 34.32ms(기준 36.81ms 이내), 쌍대 델타 중앙 +1.31ms(예산 +2.0ms 이내), >50ms 0건으로 게이트 통과 기록 완료. G3 전체 컷오버와 구분하여 관리.
5. **운영 검증**: 수집 2·3회차, Ollama c4(재기동 승인 필요), Windows Docker Desktop, Arq 처리량을 순차 처리합니다.

### 4.1 종결 계열 요약

상세 기전·반복 금지는 [`../ops/orca_do_not_repeat.md`](../ops/orca_do_not_repeat.md) 참조.

- **안전·품질 게이트**: fail-open 제거, 상태 전파 경계, frontend·Docker·CI 검증 능력과 `source_commit` 신선도 게이트를 갖췄습니다.
- **구조·데이터**: 9개 모듈을 AST 동일성으로 분할했고 ORM 13모델·137컬럼을 `Mapped[]`로 전환했습니다. DDL 지문은 불변입니다.
- **실측·계측**: 예측 웜 P95 61.9~83.6ms, SSE 첫 토큰 1.26~2.29s·완료 6.37~7.65s입니다. 블로킹 I/O와 Arq 계측 배선은 완료했고 최적화 판정은 미확정입니다.
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
- Ollama 다중화 시 자원 점유와 c4 기준선 미확정.
- Arq 태스크 처리량과 단발 RAG/LLM 내부 구간은 계측 배선만 완료되었고, 반복 게이트 판정은 미수행.

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
- 블로킹 I/O 계측: [`predict_coldstart_instrumentation.md`](../analysis/predict_coldstart_instrumentation.md), [`query_rag_latency_instrumentation.md`](../analysis/query_rag_latency_instrumentation.md), [`arq_throughput_harness.md`](../analysis/arq_throughput_harness.md)
- 워커 기동: [`agent_worker_launch_reference.md`](../ops/agent_worker_launch_reference.md)
- 용역 모델: [`servc_model_status.md`](../servc_model_status.md)
- 미병합 브랜치 판정: [`phase8_predict_tail_merge_verdict_20260814.md`](../ops/phase8_predict_tail_merge_verdict_20260814.md), [`codex_task_routing_branch_verdict_20260814.md`](../ops/codex_task_routing_branch_verdict_20260814.md)

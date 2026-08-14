# 프로젝트 현재 운영 상태 정본 (CURRENT_STATE)

> **updated_at**: 2026-08-15
> **source_commit**: `561ff85`
> **version**: v1.0.0
> 본 문서는 코디네이터 에이전트가 부트스트랩 시 가장 먼저 참조하는 **단일 진실 현재 운영 상태 정본**입니다. 과거 handoff는 증거와 히스토리이며, 현재 세션의 즉시 판단과 정책 결정은 본 문서를 기준으로 수행합니다.

---

## 1. 3대 목표 게이트 상태 (Gates)

| 게이트 | 목표 정의 | 현재 판정 | 상세 상태 및 조건 |
| --- | --- | :---: | --- |
| **G1** | 데이터 무손실 | **통과 (불변)** | MySQL 8 DB 스키마 및 행 수 100% 보존, ML 모델 가중치 체크섬 일치, ChromaDB `bidding_kb` 스냅샷 무결성 유지 |
| **G2** | 크로스 플랫폼 | **부분 통과** | macOS 환경 완전 검증 완료 (Docker + uv + Makefile). Windows Docker Desktop 환경은 실기 검증 대기 중 |
| **G3** | 스택 최적화 | **항목별 판정** | 예측 API: **통과** (`PREDICTION_GC_MODE=freeze` 기준 c10 P95 56.45ms).<br>SSE 스트리밍 c1: **통과** (규약 준수 실측 1522.41ms).<br>SSE 동시성(c4 등): **기준 없음** (Ollama 단일 인스턴스 직렬화 배포 사실 확인) |

> **주의**: G3 전체를 일괄 통과로 선언하지 않으며, 반드시 하위 항목별 실측 상태로 구분하여 기록합니다.

---

## 2. 최신 성능 지표 정본 (Current Metrics)

모든 성능 지표는 [`docs/ops/latency_gate_protocol.md`](../ops/latency_gate_protocol.md) 규약(표본 수, warmup 제외, 3회 최악값, 주변 부하 기록)에 따른 실측값만 유효합니다.

### 2.1 예측 API 레이턴시 지표

- **운영 설정**: `PREDICTION_GC_MODE=freeze` 채택 (`gc.freeze()`로 gen2 GC 순회 배제)
- **부하 조건**: warmup 10 제외, 회차당 600표본, 3회 반복 중 최악 대표값

| 동시성 | P50 (ms) | P95 (ms) | P99 (ms) | Max (ms) | 100ms 초과 | 회귀 판정선 (P95 +10%) |
| ---: | ---: | ---: | ---: | ---: | :---: | ---: |
| c1 | 12.37 | 15.47 | 17.56 | 20.85 | 0건 | 17.02ms |
| c2 | 17.17 | 19.79 | 25.32 | 30.39 | 0건 | 21.77ms |
| c4 | 28.29 | 33.46 | 39.45 | 42.76 | 0건 | 36.81ms |
| **c10** | **42.45** | **56.45** | **62.08** | **73.01** | **0건 (1,800회)** | **62.10ms** |

> **구형 기록 주의 (Stale Warning)**: `README.md` 등에 남아있는 199.18ms 수치는 구형 측정치(Stale)이며, 현재 정본 기준선은 **56.45ms**입니다.

### 2.2 하이브리드 RAG SSE 스트리밍 지표

- **부하 조건**: 회차당 60표본, 3회 반복(r1/r2/r3), warmup 제외, 주변 부하 중앙 13.8% / 최대 27.8% (규약 통과)

| 지표 | 정본 대표값 (3회 최악) | 목표 기준 | 판정 | 회귀 판정선 (+10%) |
| --- | ---: | ---: | :---: | ---: |
| 첫 토큰 P95 (c1) | **1522.41ms** | 3,000ms 이하 | **통과** | 1674.65ms |
| 전체 스트리밍 P95 (c1) | **8049.61ms** | 20,000ms 이하 | **통과** | 8854.57ms |
| c4 첫 토큰 P95 | 18086.00ms | 기준 없음 | 판정 불가 | Ollama 단일 인스턴스 직렬화 |

---

## 3. 기각 및 반복 금지 목록 (Do Not Repeat)

과거 검증을 거쳐 기각되었거나 실패가 확정된 항목입니다. 동일한 시도를 반복하지 않습니다.

1. **Uvicorn 워커 수 증설 (workers 3/4)**:
   - 다중 워커 설정 시 지연시간 개선 없이 코어 경합 및 메모리 오버헤드만 증가하여 기각되었습니다.
2. **`PREDICTION_GC_MODE=batch-disable`**:
   - 100ms 초과 발생 30건으로 기본(21건)보다 오히려 악화되어 기각되었습니다.
3. **`PREDICTION_GC_MODE=threshold`**:
   - `freeze` 모드가 확정 채택되었으므로 상호 배타적인 threshold 재검토는 불필요합니다.
4. **신뢰 확인 미완료 상태에서의 무검증 `dispatch --inject`**:
   - Antigravity CLI 환경에서 워크스페이스 신뢰 확인 대화창 미처리 시 주입 키 입력이 유실될 위험이 있습니다.
   - 사전 신뢰 승인(엔터 전송)을 확인한 뒤 `dispatch --inject`를 수행하거나 인자 주입 방식(`agy --model <id> -i "<프롬프트>"`)을 사용하며, 도달 여부(`terminal read`) 확인 없는 맹목적 대기를 금지합니다.
   - **2026-08-15 실증 정정**: 인자 주입(`agy -i`)도 신뢰 대화창 승인 전까지 실행이 시작되지 않습니다. 프롬프트는 유실되지 않으나 워커가 유휴로 보입니다. 기동은 **띄운다 -> 신뢰 승인 엔터 -> `terminal read` 로 진행 확인** 세 단계입니다. 근거: [`../ops/orca_v2_runtime_smoke_20260815.md`](../ops/orca_v2_runtime_smoke_20260815.md) V.6
5. **무료 LLM 풀의 임계 경로 투입**:
   - `cerebras/gemma-4-31b`(TPM 초과 위험) 및 OpenCode 무료 모델(`deepseek-v4-flash-free` 등)은 안정성 및 컨텍스트 제약이 있으므로 주력/임계 경로 작업에서 배제합니다.
   - 무료 모델은 절대 실패/무산출로 단정하지 않고 자동 검증이 가능한 비임계 경로(단독 감사, 분리된 검증 등)로 한정하여 사용합니다.
6. **미병합 브랜치 재병합 시도**:
   - `feat/codex-task-routing`: 전량 폐기 판정 완료 (중복 라우터 및 불필요 스킬).
   - `integrate/arq-worker-cutover`: 폐기 판정 완료 (`preprocess.py`, `champion_summary.json` 병합 금지).
   - `perf/predict-tail` (`0fd489a`): 병합 불가 판정 완료 (진단 전용 보존).
7. **워커 요약 보고 텍스트만 신뢰하는 행위**:
   - 워커의 비정형 요약과 실제 산출물 간 불일치가 빈발하므로, 코디네이터는 반드시 생성된 파일 diff 및 deterministic 검증 결과를 직접 대조합니다.
8. **README 에 성능 실측값 기재**:
   - 2026-08-15 에 G3 실측 3행을 제거하고 본 문서 포인터로 대체했습니다. 수치를 갱신하는 방식은 다음 측정에서 다시 뒤처지므로 채택하지 않습니다.
   - 레이턴시 지표의 정본은 본 문서 2장이며 측정 조건은 [`docs/ops/latency_gate_protocol.md`](../ops/latency_gate_protocol.md) 를 따릅니다.
9. **Capsule 을 공유 디렉터리에 배치**:
   - 2026-08-15 T6 실행 검증에서 워커가 자기 Capsule 과 함께 다른 Task 의 사양·런처를 읽었습니다. Task 하나당 디렉터리 하나를 쓰고 `allowed_read_files` 에 Capsule 자신의 경로를 넣습니다.
   - `allowed_read_files` 는 지시이며 강제 장치가 아닙니다. 준수는 `worker_done` 의 `read_files` 로 사후 확인합니다. 규약: [`../ops/orca_task_capsule_v2.md`](../ops/orca_task_capsule_v2.md) 2.9
10. **Reviewer 의 pass 를 코디네이터 검토 축소 근거로 사용**:
   - 2026-08-15 첫 실사용에서 Reviewer 2대가 실재 결함 3건을 놓치고 `pass` 를 냈습니다. 계약 도달과 Capsule 격리는 작동했으나 검출은 미달입니다.
   - 근거: [`../ops/orca_v2_reviewer_plane_20260815.md`](../ops/orca_v2_reviewer_plane_20260815.md). Level 3 코디네이터 검토를 유지합니다.
   - **2026-08-15 개선 측정**: 계약 v2.1 체크리스트 도입으로 같은 모델이 0/3 에서 4/4 로 개선됐습니다. 다만 체크리스트에 없던 결함은 절반만 찾으므로 Level 3 은 계속 유지합니다. Reviewer 기본 모델은 `gemini-3.7-flash-high` 입니다(Claude 계열과 검출 성적 동일). 근거: [`../ops/orca_v2_reviewer_sensitivity_20260815.md`](../ops/orca_v2_reviewer_sensitivity_20260815.md)
11. **크기 예산을 바이트로 판정**:
   - 설계 5장의 8,000자는 문자 수이며 바이트가 아닙니다. `wc -c` 로 재면 한글 3바이트 때문에 `AGENTS.md` 가 초과처럼 보이지만 실제는 6,589자로 예산 이내입니다.
   - 검증기 `check_context_budgets` 는 `len()` 으로 문자 수를 셉니다.

---

## 4. 현재 진행 과업 및 우선순위 (Active Priorities)

1. **Orca 코디네이터 토큰 최적화 v2 구현 (T0~T7)**:
   - T0(기준선 감사), T1(부트스트랩 경량화), T2(Task Capsule v2 규약), T3(Validator v2), T4(CURRENT_STATE 정본화), T5(Playbook/Setup 동기화), T6(Cross-CLI 검증) 병합 완료 (`main=f9b9477`).
   - T7(Coordinator Audit) 최종 정합성·전체 테스트·작업 트리 정리 점검 진행 중.
2. **Ollama 병렬도 실험 및 SSE 동시성 기준선 제정**:
   - `OLLAMA_NUM_PARALLEL` 실험을 통해 c4 등 동시성 환경에서의 지연 원인 분석 및 기준 확립.
3. **Windows Docker Desktop 크로스 플랫폼 실기 검증**:
   - Windows 실기 환경에서 전체 스택 구동 및 E2E 테스트 통과 확인 (G2 완결).
4. **공공조달 입찰 데이터 수집 2·3회차 관찰**:
   - 수집 파이프라인 안정성 검증.

---

## 5. 핵심 불변 원칙 (Critical Invariants)

- **데이터 무손실 (G1)**: 기존 DB 테이블명, 컬럼명, 타입 변경 절대 금지.
- **Train/Serve 단일화**: 학습 및 추론 특징 생성은 [`src/ml/features.py`](../../src/ml/features.py) 단일 함수만 사용.
- **게이트 규약 준수**: 성능 판정 시 [`docs/ops/latency_gate_protocol.md`](../ops/latency_gate_protocol.md)를 엄격히 준수하지 않은 수치는 무효 처리.
- **1인 작업 Git 워크플로우**: Pull Request를 생성하지 않으며, 작업 브랜치에서 검증 통과 후 `main`에 직접 `git merge --no-ff` 수행.
- **이모지 사용 절대 금지**: 주석, 커밋 메시지, 문서 등 모든 산출물에 이모지 사용 불가.

---

## 6. 미해결 사항 및 갱신 규약 (Unknowns & Protocol)

### 6.1 알려진 미해결 사항 (Unknowns)

- Windows Docker Desktop 실기 환경 검증 미수행.
- Ollama 동시성 다중화 처리 시 자원 점유 및 c4 레이턴시 기준선 미확정.

### 6.2 정본 갱신 규약 (Update Protocol)

- **동기 갱신**: 운영 지표, 게이트 판정, 아키텍처 불변 사실이 변경될 경우 해당 변경 커밋에 `CURRENT_STATE.md` 갱신을 반드시 포함합니다.
- **간결성 유지**: 본 파일에는 장황한 실험 로그나 분석 과정을 적지 않고, 최종 결론과 수치만 요약합니다 (8,000자 이내 유지).
- **진실 우선순위**: 문서 간 충돌 발생 시 우선순위는 다음과 같습니다.
  `실제 코드 / 실측 아티팩트 > CURRENT_STATE.md > README.md > 과거 handoff 문서`

---

## 7. 증거 경로 참조 (Evidence Pointers)

- 코디네이터 토큰 최적화 v2 설계: [`docs/ops/orca_coordinator_token_optimization_v2.md`](../ops/orca_coordinator_token_optimization_v2.md)
- v2 구현 전 기준선 감사: [`docs/ops/orca_token_optimization_v2_baseline_20260815.md`](../ops/orca_token_optimization_v2_baseline_20260815.md)
- 최신 세션 인수인계: [`docs/handoff/2026-08-14_late_session_handoff.md`](../handoff/2026-08-14_late_session_handoff.md)
- 레이턴시 게이트 규약: [`docs/ops/latency_gate_protocol.md`](../ops/latency_gate_protocol.md)
- 에이전트 워커 기동 참조: [`docs/ops/agent_worker_launch_reference.md`](../ops/agent_worker_launch_reference.md)
- 용역 모델 현황: [`docs/servc_model_status.md`](../servc_model_status.md)
- 미병합 브랜치 판정 기록:
  - [`docs/ops/phase8_predict_tail_merge_verdict_20260814.md`](../ops/phase8_predict_tail_merge_verdict_20260814.md)
  - [`docs/ops/codex_task_routing_branch_verdict_20260814.md`](../ops/codex_task_routing_branch_verdict_20260814.md)

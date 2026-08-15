# 프로젝트 현재 운영 상태 정본 (CURRENT_STATE)

> **updated_at**: 2026-08-15
> **source_commit**: `a95a18f`
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

과거 검증을 거쳐 기각되었거나 실패가 확정된 항목입니다. 동일한 시도를 반복하지 않습니다. **근거와 실측 세부는 [`../ops/orca_do_not_repeat.md`](../ops/orca_do_not_repeat.md) 에 있으며, 그 항목을 다시 검토하려 할 때만 열어봅니다.**

| # | 금지 항목 | 결론 |
| :---: | --- | --- |
| 1 | Uvicorn 워커 수 증설 (3/4) | 개선 없이 코어 경합만 증가. 기각 |
| 2 | `PREDICTION_GC_MODE=batch-disable` | 100ms 초과 30건으로 기본(21건)보다 악화. 기각 |
| 3 | `PREDICTION_GC_MODE=threshold` | `freeze` 확정 채택으로 상호 배타. 재검토 불필요 |
| 4 | `dispatch --inject` 도달 미확인 | 승인 전에는 키 유실, `agy -i` 는 미실행. **승인 후에도 유실 사례 있음(2026-08-15)**. 유실 시 `terminal send` 로 직접 투입. 도달은 `terminal read` 로만 확인 |
| 5 | 무료 LLM 풀의 임계 경로 투입 | 비임계 경로로만 한정. 단, 실패·무산출로 단정하지 않음 |
| 6 | 미병합 브랜치 재병합 | `feat/codex-task-routing` 폐기, `integrate/arq-worker-cutover` 폐기, `perf/predict-tail` 진단 전용 |
| 7 | 워커 요약 텍스트만 신뢰 | diff 와 결정론 검증 결과를 직접 대조 |
| 8 | README 에 성능 실측값 기재 | 본 문서 2장이 정본. 포인터로 대체 완료 |
| 9 | Capsule 을 공유 디렉터리에 배치 | Task 하나당 디렉터리 하나. `allowed_read_files` 에 Capsule 자신을 포함 |
| 10 | Reviewer `pass` 를 검토 축소 근거로 사용 | 체크리스트로 0/3 -> 4/4 개선했으나 밖의 결함은 절반만 검출. **Level 3 유지** |
| 11 | 크기 예산을 바이트로 판정 | 8,000자는 문자 수. `wc -c` 금지, `len()` 사용 |
| 12 | 후속 Dispatch 에 같은 `report_path` 재사용 | 덮어써서 이전 보고 소실. 재작업 지시에 새 경로를 함께 준다 |
| 13 | 파이프라인으로 검증 종료 코드 판정 | `pytest \| tail && <다음>` 은 실패를 통과로 본다. 게이트 도구를 쓴다 |
| 14 | 워커의 비표준 계약 필드명을 수용 | `files_modified` 를 받아 `changed_files_count: 0` 을 조용히 기록한 사고. 폴백 금지 |
| 15 | 반려 후 재작업을 완료된 Task 에 태우기 | 2차 `worker_done` 이 거부되어 반려 사유와 수용 판정이 이력에서 사라진다. `ready` 로 되돌리거나 새 Task 를 만든다 |
| 16 | 코디네이터 검토를 Level 2 대체로 사용 | 10번의 역방향. 2026-08-15 에 코디네이터 검토만으로 병합한 도구 4개에서 독립 감사가 **실재 결함 7건**을 찾았고 그중 하나는 계약 강제 장치 자체의 허점이었다. 두 층을 모두 통과시킨다 |

---

## 4. 현재 진행 과업 및 우선순위 (Active Priorities)

1. **Orca 코디네이터 토큰 최적화 v2 — 구현·실증 완료**:
   - T0~T7 병합 완료. 이후 코디네이터 검수로 빈틈 4건을 보완했습니다(검사 9 -> 12, `CURRENT_STATE` 존재·필수 필드·크기 경고).
   - T6 은 정적 검증만이었으므로 **실행 검증**을 추가했습니다. 실제 워커에서 Capsule -> `worker_done` 도달과 금지 문서 재독 0건을 확인했습니다([`../ops/orca_v2_runtime_smoke_20260815.md`](../ops/orca_v2_runtime_smoke_20260815.md)).
   - Capsule 격리 누수를 발견해 배치 규약 2.9 를 만들고 적용 후 `read_files` 초과 0건을 실측했습니다.
   - Reviewer 계층을 첫 가동했고 결함을 놓쳤습니다. 계약을 v2.1 체크리스트로 고쳐 seeded defect 로 0/3 -> 4/4 개선을 측정했습니다([`../ops/orca_v2_reviewer_sensitivity_20260815.md`](../ops/orca_v2_reviewer_sensitivity_20260815.md)).
   - 계약 조건은 `scripts/validate_review_report.py` 로 기계 판정합니다.
   - **2026-08-15 수신면 도구화 완료**: 코디네이터가 원시 출력을 직접 읽던 구간을 세 도구로 대체했습니다.
     - `scripts/orca_contract.py`: Capsule·보고 공용 파서 (도구 간 판정 분기 방지)
     - `scripts/orca_level1_gate.py`: 설계 10장 Level 1 을 단일 호출로. 5게이트, 사람 출력 상한 2,000자
     - `scripts/summarize_worker_done.py`: 보고 계약 기계 판정과 1,200자 다이제스트
     - `scripts/orca_metrics_ledger.py`: 설계 23장 프록시 지표 append-only 원장
     - 첫 실사용에서 실제 계약 위반 4건(`version`, `branch`, `commit_count`, `blocking_issues` 누락)을 검출했습니다.
   - **절감량**: 도입 전 값은 확보 불가 판정을 유지하고, `docs/ops/orca_v2_metrics_ledger.jsonl` 에 v2 이후 기준선부터 누적합니다. 2026-08-15 기준 3행(Capsule 중앙값 7,334자, 보고 중앙값 2,133자, `read_files` 중앙값 8건, 왕복 중앙값 2회).
   - **Level 2 단일화 완료**: `scripts/orca_run_reviewer.py` 로 리뷰어 일회성 실행·계약 판정·상한 출력이 명령 하나가 되었습니다. 체크리스트 0개면 실행하지 않고 종료 코드 2 입니다.
   - **독립 감사 결과 (2026-08-15)**: 수신면 도구 4개를 리뷰어로 감사해 **실재 결함 7건**을 검출하고 전건 수정했습니다. 경로 탈출(`scripts/../../x`)을 허용으로 오판, 따옴표 안 샵 절단, 0열 주석이 Capsule 블록을 끊어 허용 항목 유실, **`blocking_issues: ['C10']` 이 `C1` 요구를 충족시키는 부분문자열 매칭**, folded scalar 미파싱, 불리언이 지표에 합산. 근거: [`../ops/orca_v2_intake_tools_audit_20260815.md`](../ops/orca_v2_intake_tools_audit_20260815.md)
   - **미청구 사항**: 절감량 정량값(누적 시작, 아직 추세 판정 불가), Level 3 축소 가능성(체크리스트 밖 결함은 절반만 검출), T6 OpenCode 1종(비임계).
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
- 최신 세션 인수인계: [`docs/handoff/2026-08-15_coordinator_token_exhaustion_handoff.md`](../handoff/2026-08-15_coordinator_token_exhaustion_handoff.md) (코디네이터 토큰 소진, 대기 중 Task 2건, 리셋 08-16 18:00)
- 레이턴시 게이트 규약: [`docs/ops/latency_gate_protocol.md`](../ops/latency_gate_protocol.md)
- 에이전트 워커 기동 참조: [`docs/ops/agent_worker_launch_reference.md`](../ops/agent_worker_launch_reference.md)
- 용역 모델 현황: [`docs/servc_model_status.md`](../servc_model_status.md)
- 미병합 브랜치 판정 기록:
  - [`docs/ops/phase8_predict_tail_merge_verdict_20260814.md`](../ops/phase8_predict_tail_merge_verdict_20260814.md)
  - [`docs/ops/codex_task_routing_branch_verdict_20260814.md`](../ops/codex_task_routing_branch_verdict_20260814.md)

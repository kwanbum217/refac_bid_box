# 프로젝트 현재 운영 상태 정본 (CURRENT_STATE)

> **updated_at**: 2026-08-17
> **source_commit**: `735ec20`
> **version**: v1.0.0
> 코디네이터가 부트스트랩 시 가장 먼저 읽는 **현재 운영 상태 정본**입니다. 과거 handoff 는 증거이며, 즉시 판단과 정책 결정은 본 문서를 기준으로 합니다.

---

## 1. 3대 목표 게이트 상태 (Gates)

| 게이트 | 목표 정의 | 현재 판정 | 상세 상태 및 조건 |
| --- | --- | :---: | --- |
| **G1** | 데이터 무손실 | **통과 (불변)** | MySQL 8 스키마·행 수 100% 보존, ML 가중치 체크섬 일치, ChromaDB `bidding_kb` 스냅샷 무결성 유지 |
| **G2** | 크로스 플랫폼 | **부분 통과** | macOS 완전 검증 완료 (Docker + uv + Makefile). Windows Docker Desktop 실기 검증 대기 |
| **G3** | 스택 최적화 | **항목별 판정** | 예측 API: **통과** (`PREDICTION_GC_MODE=freeze` 기준 c10 P95 56.45ms).<br>SSE 스트리밍 c1: **통과** (규약 준수 실측 1522.41ms).<br>SSE 동시성(c4 등): **기준 없음** (Ollama 단일 인스턴스 직렬화 배포 사실 확인) |

> **주의**: G3 를 일괄 통과로 선언하지 않고 항목별 실측 상태로 구분해 기록합니다.

---

## 2. 최신 성능 지표 정본 (Current Metrics)

[`latency_gate_protocol.md`](../ops/latency_gate_protocol.md) 규약(표본 수, warmup 제외, 3회 최악값, 주변 부하 기록)에 따른 실측값만 유효합니다.

### 2.1 예측 API 레이턴시 지표

- **운영 설정**: `PREDICTION_GC_MODE=freeze` (`gc.freeze()` 로 gen2 GC 순회 배제)
- **부하 조건**: warmup 10 제외, 회차당 600표본, 3회 반복 중 최악 대표값

| 동시성 | P50 (ms) | P95 (ms) | P99 (ms) | Max (ms) | 100ms 초과 | 회귀 판정선 (P95 +10%) |
| ---: | ---: | ---: | ---: | ---: | :---: | ---: |
| c1 | 12.37 | 15.47 | 17.56 | 20.85 | 0건 | 17.02ms |
| c2 | 17.17 | 19.79 | 25.32 | 30.39 | 0건 | 21.77ms |
| c4 | 28.29 | 33.46 | 39.45 | 42.76 | 0건 | 36.81ms |
| **c10** | **42.45** | **56.45** | **62.08** | **73.01** | **0건 (1,800회)** | **62.10ms** |

> **구형 기록 주의**: `README.md` 등에 남은 199.18ms 는 구형이며 정본 기준선은 **56.45ms** 입니다.

### 2.2 하이브리드 RAG SSE 스트리밍 지표

- **부하 조건**: 회차당 60표본, 3회 반복, warmup 제외, 주변 부하 중앙 13.8% / 최대 27.8% (규약 통과)

| 지표 | 정본 대표값 (3회 최악) | 목표 기준 | 판정 | 회귀 판정선 (+10%) |
| --- | ---: | ---: | :---: | ---: |
| 첫 토큰 P95 (c1) | **1522.41ms** | 3,000ms 이하 | **통과** | 1674.65ms |
| 전체 스트리밍 P95 (c1) | **8049.61ms** | 20,000ms 이하 | **통과** | 8854.57ms |
| c4 첫 토큰 P95 | 18086.00ms | 기준 없음 | 판정 불가 | Ollama 직렬화 |

---

## 3. 기각 및 반복 금지 목록 (Do Not Repeat)

검증을 거쳐 기각되었거나 실패가 확정된 항목입니다. **근거와 실측 세부는 [`../ops/orca_do_not_repeat.md`](../ops/orca_do_not_repeat.md) 에 있으며, 그 항목을 다시 검토하려 할 때만 열어봅니다.**

| # | 금지 항목 | 결론 |
| :---: | --- | --- |
| 1 | Uvicorn 워커 수 증설 (3/4) | 개선 없이 코어 경합만 증가. 기각 |
| 2 | `PREDICTION_GC_MODE=batch-disable` | 100ms 초과 30건으로 기본(21)보다 악화. 기각 |
| 3 | `PREDICTION_GC_MODE=threshold` | `freeze` 확정 채택으로 상호 배타. 재검토 불필요 |
| 4 | `dispatch --inject` 도달 미확인 | 승인 전 키 유실, 승인 후에도 유실 사례 있음. 도달은 `terminal read` 로만 확인 |
| 5 | 무료 LLM 풀의 임계 경로 투입 | 자동 선택 대상 아님. `investigator` + `low` + 쓰기 범위 없음 세 조건에서만 `--allow-free` 로 개방. 실패로 단정하지도 않음 |
| 6 | 미병합 브랜치 재병합 | `feat/codex-task-routing`·`integrate/arq-worker-cutover` 폐기, `perf/predict-tail` 진단 전용 |
| 7 | 워커 요약 텍스트만 신뢰 | diff 와 결정론 검증 결과를 직접 대조 |
| 8 | README 에 성능 실측값·판정 문구 기재 | 본 문서 2장과 1장이 정본. 판정 문구도 수치와 같이 낡는다. 포인터로 대체 완료 |
| 9 | Capsule 을 공유 디렉터리에 배치 | Task 당 디렉터리 하나. `allowed_read_files` 에 Capsule 자신 포함 |
| 10 | Reviewer `pass` 를 검토 축소 근거로 사용 | 체크리스트 밖 결함은 절반만 검출. **Level 3 유지** |
| 11 | 크기 예산을 바이트로 판정 | 8,000자는 문자 수. `wc -c` 금지, `len()` 사용 |
| 12 | 같은 `report_path` 재사용 | 덮어써서 이전 보고 소실. 재작업 지시에 새 경로를 준다 |
| 13 | 파이프라인으로 종료 코드 판정 | `pytest \| tail && <다음>` 은 실패를 통과로 본다. 게이트 도구를 쓴다 |
| 14 | 워커의 비표준 계약 필드명을 수용 | `files_modified` 폴백이 `changed_files_count: 0` 을 조용히 기록했다. 폴백 금지 |
| 15 | 재작업을 완료된 Task 에 태우기 | 2차 `worker_done` 이 거부되어 반려 사유가 이력에서 사라진다. `ready` 로 되돌리거나 새 Task 를 만든다 |
| 16 | 코디네이터 검토를 Level 2 대체로 사용 | 10번의 역방향. 코디네이터 검토만으로 병합한 도구 4개에서 독립 감사가 결함 7건을 찾았다. 두 층을 모두 통과시킨다 |
| 17 | 확인하지 않은 외부 CLI 서명으로 코드 작성 | 값 유무는 `--help` Usage 줄로 본다. `opencode ask` 는 실패하며 **종료 코드 0** 을 냈다. 종료 코드만으로 성공을 선언하지 않는다 |
| 18 | 테스트가 틀린 사실을 정답으로 고정 | 없는 CLI 서명을 기대값으로 단정했다. 통과하는 테스트는 확인의 근거가 아니다 |
| 19 | `defect_when` 에 산문 기재 | `yes`/`no` 극성 토큰이다. 문장을 넣어 리뷰 8항목이 무효화됐다 |
| 20 | `ready` 복귀만 하고 재 Dispatch 생략 | 권한 회수로 재보고가 `capability is revoked` 로 거부된다. 병합한 Task 는 `completed` 로 닫는다 |
| 21 | `worker-list` 로 동시 워커 수 판정 | `worker-start` 워커만 보여 3대가 붙어도 활성 0 이다. `task-list` 의 `dispatched` 로 판정한다. 자리표시자 Run ID 도 조회를 비게 만든다 |
| 22 | 실측하지 않은 모델 ID 등록 | 선택되는 순간에야 `Model not found` 로 실패한다. 추가 시 그 자리에서 probe 로 응답을 확인한다 |
| 23 | 읽기 범위를 차단 장치로 취급 | 쓰기 범위는 `git diff` 로 검증하나 읽기 범위는 **자기 신고만** 대조한다. 유출 금지 대상은 워커 트리에 두지 않는다 |
| 24 | `coordinator_input_tokens` 로 절감 비교 | `cache_read` 가 99.5%로 턴 수에 비례해 위임과 무관하다. 대표는 `coordinator_fresh_input_tokens` |
| 25 | Orca CLI 열거형 값을 확인 없이 사용 | `check --types ask` 는 대기가 성립하지 않는데도 `ok: false` + **종료 코드 0** 이다. 종료 코드와 `ok` 를 따로 본다 |
| 26 | Capsule 경로를 주입하지 않기 | `dispatch --inject` 는 Task `spec` 만 주입한다. 워커 **3/3** 이 계약을 위반했다. 경로를 `spec` 에 넣고 재 Dispatch 후 새 `dispatchId` 도 전달한다 |
| 27 | `check` 를 `--ack` 없이 호출 | 미확인 배치가 재전달되어 뒤에 온 `worker_done` 이 가려지고 `--wait` 도 즉시 반환된다. `--ack <deliveryId>` 로 전진시킨다 |
| 28 | 동작 보존 분할을 사람 판독으로만 검증 | `ast.dump(node, include_attributes=False)` 로 이동 함수를 기계 대조한다. 리뷰어가 놓친 본문 변경 5건을 이 방법으로 찾았다 |
| 29 | 워커의 린터 보고를 전체 통과로 읽기 | 워커는 지정 경로만 검사한다. Level 1 게이트에 ruff 가 없으므로 병합 전 `uv run ruff check .` 를 직접 돌린다 |

---

## 4. 현재 진행 과업 및 우선순위 (Active Priorities)

1. **Orca 코디네이터 토큰 최적화 v2 — 구현 완료, 실사용 교정 중**:
   - **수신면 도구 5종**: `orca_contract.py`, `orca_level1_gate.py`(Level 1), `summarize_worker_done.py`, `orca_run_reviewer.py`(Level 2), `orca_metrics_ledger.py`. 독립 감사 결함 7건 수정. 근거: [`../ops/orca_v2_intake_tools_audit_20260815.md`](../ops/orca_v2_intake_tools_audit_20260815.md)
   - **Level 3 유지 확정**: 결함 밀도 0.05 사전 등록, A/B 모두 검출 0/3. 근거: [`../ops/orca_v2_level3_reduction_rerun_results_20260815.md`](../ops/orca_v2_level3_reduction_rerun_results_20260815.md)
   - **Control Plane 도구**: `orca_taskctl.py`, `orca_model_router.py`. 최초 판 `3453a3f` 를 되돌린(`d8c964a`) 사유가 3장 17~20번입니다.
   - **동시 쓰기 워커 상한 3대**를 `dispatch` 가 기계 강제(AGENTS.md 4장 5.1). 코디네이터 토큰은 트랜스크립트 자동 계측.
   - **2026-08-17 첫 실사용에서 전달 경로 결함 4종 확인**(3장 26~29번). Capsule 계약이 워커에 도달하지 않아 3대 전부가 위반했고, `dispatch` 기동 경로는 그때까지 실행된 적이 없었습니다(`76c3013`).
   - **절감량**: 도입 전 값은 확보 불가 유지. 추세는 원장 행이 더 필요합니다.
2. **대형 모듈 분할 (Phase 3)**: 1차 3건 병합. `rag/engine.py` 1171->490, `automation_orchestrator.py` 1039->550, `planner.py` 968->643. AST 동일성으로 동작 보존 실증. **2차**는 `model_registry.py`(참조 18파일, 서빙 경로)와 `api/v1/chatbot.py` 이며 위험이 커 순차 진행합니다.
3. **Ollama 병렬도 실험 및 SSE 동시성 기준선**: `OLLAMA_NUM_PARALLEL` 로 c4 지연 원인을 분석합니다. 호스트 Ollama 재시동과 Docker 단독 점유가 필요합니다.
4. **Windows Docker Desktop 실기 검증**: 전체 스택 구동과 E2E 통과 확인 (G2 완결).
5. **공공조달 입찰 데이터 수집 2·3회차 관찰**: Docker 필요.

---

## 5. 핵심 불변 원칙 (Critical Invariants)

- **데이터 무손실 (G1)**: 기존 DB 테이블명, 컬럼명, 타입 변경 절대 금지.
- **Train/Serve 단일화**: 특징 생성은 [`src/ml/features.py`](../../src/ml/features.py) 단일 함수만 사용.
- **게이트 규약 준수**: [`latency_gate_protocol.md`](../ops/latency_gate_protocol.md) 를 엄격히 지키지 않은 수치는 양방향 무효.
- **1인 작업 Git**: PR 없음. 작업 브랜치 검증 통과 후 `main` 에 `git merge --no-ff`.
- **이모지 절대 금지**: 주석, 커밋 메시지, 문서 등 모든 산출물.

---

## 6. 미해결 사항 및 갱신 규약 (Unknowns & Protocol)

### 6.1 알려진 미해결 사항 (Unknowns)

- Windows Docker Desktop 실기 검증 미수행.
- Ollama 다중화 시 자원 점유와 c4 기준선 미확정.

### 6.2 정본 갱신 규약 (Update Protocol)

- **동기 갱신**: 운영 지표, 게이트 판정, 불변 사실이 바뀌면 그 커밋에 본 문서 갱신을 포함합니다.
- **간결성 유지**: 실험 로그나 분석 과정을 적지 않고 결론과 수치만 요약합니다 (8,000자 이내).
- **진실 우선순위**: `실제 코드 / 실측 아티팩트 > CURRENT_STATE.md > README.md > 과거 handoff`

---

## 7. 증거 경로 참조 (Evidence Pointers)

- v2 설계: [`docs/ops/orca_coordinator_token_optimization_v2.md`](../ops/orca_coordinator_token_optimization_v2.md)
- 제어 평면 도구: [`orca_control_plane_tools.md`](../ops/orca_control_plane_tools.md), 지표 원장: [`orca_v2_metrics_ledger.md`](../ops/orca_v2_metrics_ledger.md)
- 레이턴시 게이트 규약: [`latency_gate_protocol.md`](../ops/latency_gate_protocol.md)
- 워커 기동: [`agent_worker_launch_reference.md`](../ops/agent_worker_launch_reference.md), 용역 모델: [`servc_model_status.md`](../servc_model_status.md)
- 미병합 브랜치 판정: [`phase8_predict_tail_merge_verdict_20260814.md`](../ops/phase8_predict_tail_merge_verdict_20260814.md), [`codex_task_routing_branch_verdict_20260814.md`](../ops/codex_task_routing_branch_verdict_20260814.md)

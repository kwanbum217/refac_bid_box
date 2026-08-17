# 프로젝트 현재 운영 상태 정본 (CURRENT_STATE)

> **updated_at**: 2026-08-17
> **source_commit**: `45cfd52`
> **version**: v1.0.0
> 코디네이터가 부트스트랩 시 가장 먼저 읽는 **현재 운영 상태 정본**입니다. 과거 handoff 는 증거이며, 즉시 판단과 정책 결정은 본 문서를 기준으로 합니다.

---

## 1. 3대 목표 게이트 상태 (Gates)

| 게이트 | 목표 정의 | 현재 판정 | 상세 상태 및 조건 |
| --- | --- | :---: | --- |
| **G1** | 데이터 무손실 | **통과 (불변)** | MySQL 8 스키마·행 수 보존, ML 가중치 체크섬 일치, ChromaDB `bidding_kb` 무결성 |
| **G2** | 크로스 플랫폼 | **부분 통과** | macOS 완전 검증 완료 (Docker + uv + Makefile). Windows Docker Desktop 실기 검증 대기 |
| **G3** | 스택 최적화 | **항목별 판정** | 예측 API **통과**(`freeze` c10 P95 56.45ms). SSE c1 **통과**(1522.41ms). SSE 동시성(c4) **기준 없음**(Ollama 단일 인스턴스 직렬화) |

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

**본 표는 판단으로만 지킬 수 있는 항목입니다.** 게이트나 도구가 기계로 막는 항목은 표에 두지 않고 [`../ops/orca_do_not_repeat.md`](../ops/orca_do_not_repeat.md) 7장에 강제 장치와 함께 둡니다. 근거와 실측 세부도 그 문서에 있으며, 해당 항목을 다시 검토하려 할 때만 열어봅니다.

| # | 금지 항목 | 결론 |
| :---: | --- | --- |
| 1 | 기각된 성능 실험 재시도 | Uvicorn 워커 증설, `GC_MODE=batch-disable`, `GC_MODE=threshold` 세 건 모두 측정으로 기각 |
| 2 | 미병합 브랜치 재병합 | `codex-task-routing`·`arq-worker-cutover` 폐기, `perf/predict-tail` 진단 전용 |
| 3 | README 에 성능 실측값·판정 문구 기재 | 본 문서 2장·1장이 정본. 판정 문구도 수치처럼 낡는다 |
| 4 | `--inject` 도달 미확인 | 승인 전후 모두 유실 사례. 도달은 `terminal read` 로만 확인 |
| 5 | 워커 요약 텍스트만 신뢰 | diff 와 검증 결과를 직접 대조 |
| 6 | Capsule 공유 디렉터리 배치 | Task 당 디렉터리 하나. `allowed_read_files` 에 Capsule 자신 포함 |
| 7 | Reviewer `pass` 로 검토 축소 | 체크리스트 밖 결함은 절반만 검출. Level 3 유지 |
| 8 | 코디네이터 검토를 Level 2 대체 | 코디네이터 검토만으로 병합한 도구 4개에서 독립 감사가 결함 7건을 찾았다 |
| 9 | 같은 `report_path` 재사용 | 덮어써서 이전 보고 소실. 새 경로를 준다 |
| 10 | 파이프라인으로 종료 코드 판정 | `pytest \| tail && ...` 은 실패를 통과로 본다. 게이트 도구를 쓴다 |
| 11 | 비표준 계약 필드명 수용 | `files_modified` 폴백이 `changed_files_count: 0` 을 조용히 기록했다. 폴백 금지 |
| 12 | 재작업을 완료된 Task 에 태우기 | 2차 `worker_done` 이 거부되어 반려 사유가 사라진다. `ready` 복귀 또는 새 Task |
| 13 | `ready` 복귀 후 재 Dispatch 생략 | 권한 회수로 재보고가 거부된다. 병합 Task 는 `completed` 로 닫는다 |
| 14 | 미확인 외부 CLI 서명으로 코드 작성 | 값 유무는 `--help` Usage 줄로 본다. 종료 코드 0 이 성공은 아니다 |
| 15 | Orca CLI 열거형 미확인 사용 | `check --types ask` 는 `ok: false` + 종료 코드 0 이다. 둘을 따로 본다 |
| 16 | 테스트가 틀린 사실을 정답으로 고정 | 통과하는 테스트는 확인의 근거가 아니다 |
| 17 | `defect_when` 에 산문 기재 | `yes`/`no` 극성 토큰이다. 기계 검증이 없어 8항목이 무효화됐다 |
| 18 | 미실측 모델 ID 등록 | 선택되는 순간에야 `Model not found`. 추가 시 그 자리에서 probe 한다 |
| 19 | 읽기 범위를 차단 장치로 취급 | 쓰기는 `git diff` 검증, 읽기는 자기 신고만 대조. 유출 금지 대상은 워커 트리에 두지 않는다 |
| 20 | `coordinator_input_tokens` 로 절감 비교 | `cache_read` 가 99.5%로 턴 수에 비례한다. 대표는 `coordinator_fresh_input_tokens` |
| 21 | 순차 행을 모델 비교로 읽기 | 뒤 행일수록 캐시가 서 있어 순서 효과와 모델 효과가 섞인다 |
| 22 | `check` 를 `--ack` 없이 호출 | 미확인 배치가 재전달되어 뒤의 `worker_done` 이 가려진다 |
| 23 | 동작 보존 분할을 사람 판독으로만 검증 | `ast.dump(node, include_attributes=False)` 로 기계 대조 |
| 24 | AST 대조 이름을 평평하게 모으기 | `Class.method` / `<module>.func` 로 정규화한다 |
| 25 | 저장소 도구를 `python3` 로 실행 | macOS `python3` 는 Xcode 3.9 라 `datetime.UTC` 가 깨진다. `uv run python` |
| 26 | TPM 을 파일 수 축소로 해소 | 원인은 루프의 컨텍스트 재전송. 사실 주입 원샷만 통과 |
| 27 | 모델 선정 전 반복 금지 미조회 | Cerebras TPM 위험과 리뷰어 개방 금지가 이미 적혀 있었다 |
| 28 | 메시지 필드명을 계약 위반으로 오판 | payload 는 Orca 자체 camelCase 다(`send --files-modified`). 파일 계약과 따로 대조 |
| 29 | 메시지 `reportPath` 를 원장에 기록 | 원장은 Capsule 의 `report_path` 를 쓴다 |
| 30 | 줄 수로 감사 비권고를 뒤집기 | 기준선은 후보를 고르는 장치이고 판정이 아니다. 3개 모듈은 감사 근거로 자르지 않았다 |
| 31 | 함수 추출을 이동과 같은 방식으로 검증 | 이동은 `ast.dump` 로 증명되지만 추출은 본문을 바꿔 증명이 불가하다. 테스트에만 의존한다 |
| 32 | 모듈 관점 감사로 함수 내부까지 판정 | A1 이 236줄 함수와 3회 반복 블록을 놓쳤다. 최장 함수 줄 수를 체크리스트에 명시한다 |

---

## 4. 현재 진행 과업 및 우선순위 (Active Priorities)

1. **Orca 코디네이터 토큰 최적화 v2 — 구현 완료, 실사용 교정 중**:
   - **수신면 도구 5종**: `orca_contract.py`, `orca_level1_gate.py`(게이트 6대), `summarize_worker_done.py`, `orca_run_reviewer.py`, `orca_metrics_ledger.py`.
   - **Level 3 유지 확정**: 결함 밀도 0.05 사전 등록, A/B 검출 0/3.
   - **Control Plane 도구**: `orca_taskctl.py`, `orca_model_router.py`. `3453a3f` 회수 사유는 3장 13·14·16·17번.
   - **동시 쓰기 워커 상한 3대**를 `dispatch` 가 강제(AGENTS.md 4장 5.1).
   - **실사용 도구 결함 4건 수정**: 기동 경로(`76c3013`), Capsule 경로(`eb6f429`), 중복 생성(`cef6623`), 산출물 경로(`b86d833`). 넷 다 문서상 완비였다.
   - **절감량**: 도입 전 값은 확보 불가 유지. 대표 지표 유효 행 0 -> 7 확보. 순서 효과와 모델 효과가 섞여 추세 판정은 아직 불가(3장 21번).
   - **등급 실측**: 고정 경계 기계적 분할을 medium 으로 돌려 품질 9항목 전부 high 와 동일(AST 15/15, 정정 왕복 0). S1 급 난이도는 미검증.
   - **2026-08-17 모델별 동형 감사 4종**(gemini-flash-high, sonnet-4-6, opus-4-6-thinking, cerebras/gemma-4-31b): 읽기 전용 4건 전부 저장소 무수정. 도구 결함 3건 수정.
2. **대형 모듈 분할 — 종결**: 1,000 -> 600 -> 500줄 순으로 기준을 내려 9개 모듈 분할, 신규 20모듈. AST 동일성 실증(65+85+24+10+15). 500줄 초과 7개 전부 판정 완료(불필요 3, 완료 잔여 2, 비권고 2). 판정표는 [`../ops/orca_do_not_repeat.md`](../ops/orca_do_not_repeat.md) 8장. 남은 크기는 함수 길이(`retrieve_structured_data` 236줄)에 몰려 있고 추출은 AST 증명이 불가해, `pytest-cov` 승인 또는 실제 결함 발생을 재개 조건으로 남겼다.
3. **요청 경로 동기 블로킹 I/O 제거 — 구조 수정 완료, 실측 미검증**: G3 감사가 지목한 4건을 오프로드했다. 수집 집계·체크포인트(`5d65b5c`), SSR 회원가입·로그인의 PBKDF2 600k 회와 동기 DB(`bdb69b5`), SSE 컨텍스트 조회(`45cfd52`). 세 커밋 모두 반증 테스트를 동반한다. **P95 실측 미수행이라 성능 개선은 주장하지 않는다.** 감사가 올린 `stream_generate` 소켓 생성은 제너레이터 지연 평가라 결함이 아니었다.
4. **Ollama 병렬도 실험 및 SSE 동시성 기준선**: `OLLAMA_NUM_PARALLEL` 로 c4 지연 원인을 분석합니다. 호스트 Ollama 재시동과 Docker 단독 점유가 필요합니다.
5. **Windows Docker Desktop 실기 검증**: 전체 스택 구동과 E2E 통과 확인 (G2 완결).
6. **공공조달 입찰 데이터 수집 2·3회차 관찰**: Docker 필요.

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
- 블로킹 I/O 오프로드 4건의 P95 개선치 미측정(4장 3번).

### 6.2 정본 갱신 규약 (Update Protocol)

- **동기 갱신**: 운영 지표, 게이트 판정, 불변 사실이 바뀌면 그 커밋에 본 문서 갱신을 포함합니다.
- **간결성 유지**: 실험 로그나 분석 과정을 적지 않고 결론과 수치만 요약합니다 (8,000자 이내).
- **진실 우선순위**: `실제 코드 / 실측 아티팩트 > CURRENT_STATE.md > README.md > 과거 handoff`

---

## 7. 증거 경로 참조 (Evidence Pointers)

- v2 설계: [`docs/ops/orca_coordinator_token_optimization_v2.md`](../ops/orca_coordinator_token_optimization_v2.md), 제어 평면: [`orca_control_plane_tools.md`](../ops/orca_control_plane_tools.md)
- 지표 원장: [`orca_v2_metrics_ledger.md`](../ops/orca_v2_metrics_ledger.md)
- 레이턴시 게이트 규약: [`latency_gate_protocol.md`](../ops/latency_gate_protocol.md)
- 워커 기동: [`agent_worker_launch_reference.md`](../ops/agent_worker_launch_reference.md)
- 용역 모델: [`servc_model_status.md`](../servc_model_status.md)
- 미병합 브랜치 판정: [`phase8_predict_tail_merge_verdict_20260814.md`](../ops/phase8_predict_tail_merge_verdict_20260814.md), [`codex_task_routing_branch_verdict_20260814.md`](../ops/codex_task_routing_branch_verdict_20260814.md)

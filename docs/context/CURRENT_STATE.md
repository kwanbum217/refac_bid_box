# 프로젝트 현재 운영 상태 정본 (CURRENT_STATE)

> **updated_at**: 2026-08-21
> **source_commit**: `8702cd3`
> **version**: v1.0.0
> 코디네이터가 부트스트랩 시 가장 먼저 읽는 **현재 운영 상태 정본**입니다. 과거 handoff 는 증거이며, 즉시 판단과 정책 결정은 본 문서를 기준으로 합니다.

---

## 1. 3대 목표 게이트 상태 (Gates)

| 게이트 | 목표 정의 | 현재 판정 | 상세 상태 및 조건 |
| --- | --- | :---: | --- |
| **G1** | 데이터 무손실 | **통과 (불변)** | MySQL 8 스키마·행 수 보존, ML 가중치 체크섬 일치, ChromaDB `bidding_kb` 무결성 |
| **G2** | 크로스 플랫폼 | **부분 통과** | macOS 완전 검증 완료 (Docker + uv + Makefile). Windows Docker Desktop 실기 검증 대기 |
| **G3** | 스택 최적화 | **항목별 판정** | 예측 API **통과**(`freeze` c10 P95 56.45ms). SSE c1 **통과**(1522.41ms). SSE 동시성(c4) **기준 없음**(Ollama 단일 인스턴스 직렬화) |

> **주의**: G3 는 일괄 통과로 선언하지 않고 항목별 실측 상태로 기록합니다.

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

**본 표는 판단으로만 지킬 수 있는 항목입니다.** 기계로 막는 항목과 실측 근거는 [`../ops/orca_do_not_repeat.md`](../ops/orca_do_not_repeat.md) 7장에 있습니다.

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
| 12 | 재작업을 완료된 Task 에 태우기 | 2차 `worker_done` 은 권한 회수로 거부된다. `ready` 복귀 후 재 Dispatch |
| 13 | 미확인 외부 CLI 서명·열거형 사용 | 값 유무는 `--help` Usage 로 본다. `ok: false` + 종료 코드 0 조합이 있다 |
| 14 | 테스트가 틀린 사실을 정답으로 고정 | 통과하는 테스트는 확인의 근거가 아니다 |
| 15 | 미실측 모델 ID 등록 | 선택되는 순간에야 `Model not found`. 추가 시 그 자리에서 probe 한다 |
| 16 | 읽기 범위를 차단 장치로 취급 | 쓰기는 `git diff` 검증, 읽기는 자기 신고만 대조. 유출 금지 대상은 워커 트리에 두지 않는다 |
| 17 | 순차 행을 모델 비교로 읽기 | 뒤 행일수록 캐시가 서 있어 순서 효과와 모델 효과가 섞인다 |
| 18 | `check` 를 `--ack` 없이 호출 | 미확인 배치가 재전달되어 뒤의 `worker_done` 이 가려진다 |
| 19 | 동작 보존 분할을 사람 판독으로만 검증 | `ast.dump(node, include_attributes=False)` 로 증명한다 |
| 20 | 저장소 도구를 `python3` 로 실행 | macOS `python3` 는 Xcode 3.9 라 `datetime.UTC` 가 깨진다. `uv run python` |
| 21 | 모델 선정 전 반복 금지 미조회 | Cerebras TPM 위험과 리뷰어 개방 금지가 이미 적혀 있었다. TPM 원인은 루프의 컨텍스트 재전송이다 |
| 22 | 메시지 payload 를 파일 계약과 섞기 | payload 는 Orca 자체 camelCase 다. 원장에는 Capsule 의 `report_path` 를 쓴다 |
| 23 | 감사 결론을 검증 없이 채택 | 이동은 `ast.dump` 로 증명되나 추출은 불가하다. 모듈 관점 감사는 함수 내부를 놓친다 |

---

## 4. 현재 진행 과업 및 우선순위 (Active Priorities)

0. **3차 경합 선행 P0 2건 해소 (2026-08-21 완료)**: 2차 러너가 시한 초과 워커를 죽이지 않아 잔류 프로세스가 다음 회차 워크트리에 커밋했다(`oc_nemo3ultra` 오염). 러너는 핸들을 보관해 그 워커만 종료하고 종료를 확인한 뒤에 슬롯을 반납하며, 미확인 시 스택을 봉인한다. 사전등록값은 Capsule 에서 읽고 preflight 를 통과해야 시작한다. 역할별 후보 순서 결합도 끊었다(18~19장). **3차 재측정 완료 (2026-08-21)**: 같은 base ref(`8b0b400`)·동시 3대 조건으로 `oc_nemo3ultra` 를 다시 재 2/3 을 얻었고 오염은 해소했다. 러너의 종료 확인이 시한 초과 3건에서 모두 작동했다. 함께 투입한 `laguna_xs` 가 2차 3/3(median 458s)에서 0/3 으로 뒤집혔는데, 3회 중 2회는 채점 6/6 만점 코드를 만들고 커밋만 못 한 지연이다. **n=3 으로 매긴 순위도 재현되지 않으므로 정기 경합은 3차로 종료한다.** `FREE_BUILDER_ORDER` 는 속도가 아니라 최근 실패율 순으로 재정렬했고 (`opencode-deepseek` 은 실재 이력이 자동 강등하므로 유지), `FREE_INVESTIGATOR_ORDER` 는 따라가지 않아 두 순서의 값이 실제로 갈라졌다. 이후는 상시 관측으로 갈음하며 재실행 트리거 3개는 `benchmarks/free_workers/README.md` 6장에 있다.

1. **Orca 코디네이터 토큰 최적화 v2 — 구현 완료, 실사용 교정 중**: 수신면 5종과 Control Plane 2종에 적용. **절감량은 도입 전 값 확보 불가이고 유효 행이 적어 추세 판정이 안 된다**(3장 17번). 왕복 횟수가 비용을 지배한다는 실측과 규율은 조율 스킬 3.2 절.
2. **동기 블로킹 I/O 제거 — 구조 수정 완료, 실측 미검증**: 12건(요청 4, Arq 8)을 `to_thread` 로 오프로드. 6커밋 전부 반증 테스트 동반. **P95 실측 미수행이라 성능 개선은 주장하지 않는다.**
3. **ORM `Mapped[]` 전환 — 미착수**: mypy `call-overload` 9건이 구식 `Column` 선언이라는 단일 원인이라 모듈 한정 override 로 덮어 두었다. G1 에 닿으므로 별도 과업.
4. **Ollama 병렬도 실험 및 SSE 동시성 기준선**: `OLLAMA_NUM_PARALLEL` 로 c4 지연 원인 분석. 호스트 Ollama 재시동과 Docker 단독 점유 필요.
5. **Windows Docker Desktop 실기 검증**: 전체 스택 구동과 E2E 통과 (G2 완결).
6. **수집 2·3회차 관찰**: Docker 필요.

### 4.1 종결 계열 요약

기전과 반복 금지 상세는 [`../ops/orca_do_not_repeat.md`](../ops/orca_do_not_repeat.md) 해당 장에 있습니다.

- **fail-open 제거 (누적 34건, 10·12장)**: `실패`·`미검증`·`절단`·`미도달` 이 SUCCESS 로 승격되는 계열. 최악은 수집 부분 실패의 success 위장으로, 체크포인트가 `MAX(date)` 라 그 구멍을 다시 조회하지 않았다(G1 직결). **다수는 기존 테스트가 잘못된 동작을 정상으로 고정하고 있었다.**
- **상태 전파 경계 (3~6차 감사, 13~16장)**: 하위가 실패·불능을 아는데 상위 경계에서 상태를 잃는 계열. 병합 게이트 자체의 구멍도 닫았다. 게이트 3 은 검증을 영역이 아니라 **능력 단위**로 세고(frontend test·build, docker build, compose config, actionlint), `source_commit` 지연 초과는 FAIL 이다.
- **대형 모듈 분할 (8장)**: 9개 모듈 분할(신규 20모듈), AST 동일성 실증. **줄 수로 자동 분할하지 않는다.**
- **워커 풀 정비 (11장)**: 무료 후보도 `suitable_for` 불변식을 통과해야 한다. 2026-08-20 쓰기 과제 경합(`run_d2fd971f7daa`)에서 무료 10종에 동일 Capsule 로 같은 쓰기 과제를 주고 격리 워크트리에서 수행시켜 5종이 통과했다. **저위험 Python builder 과제를 완주하는 무료 워커 스택을 처음으로 실측 선별했다** (순서는 동등 합격군이며 능력 순위가 아니다. 스택당 1회 실행) (이전은 문맥 크기와 probe 응답 시간 기준의 잠정 순서). 신규 등록 `opencode/nemotron-3-ultra-free`(9분01초, 1순위), `opencode/mimo-v2.5-free`(13분58초) 는 그전까지 미등록이었다. `or-free/laguna-xs` 와 `or-free/nemotron-ultra` 에 `builder` 를 부여했다. 격리 4종(영구 판정이 아니라 재시험 전까지 배정 중단)은 `opencode/nemotron-3.5-lightning-free`(4.8KB 지시문에 무의미 출력. 짧은 입력에는 정상 응답해 probe 를 통과한다), `or-free/laguna-s`(32분간 도구 호출 0건), `or-free/north-mini`(실격선 28분 초과), `opencode/hy3-free`(파일 3개를 읽고 아무것도 쓰지 않은 채 종료 코드 0)다. **읽기 전용 probe 는 쓰기 적합성을 예측하지 못한다** — 같은 4종이 오전 감사에서는 전부 6/6 이었다. 역할은 잰 것만 준다. 이번에 측정한 것은 `builder` 이므로 무료 풀 전체에서 `benchmarker` 와 `documenter` 를 회수했고, `reviewer` 는 임계 경로라 여전히 닫혀 있다. 측정 장치는 `benchmarks/free_workers/` 에 버전 관리한다. `dispatch --inject` 는 Kimi TUI 를 종료시키므로 preamble 런치 인자 경로만 쓰고, 쓰기 Task 는 `default_permission_mode = "auto"` 인 별도 프로필로 띄운다.
- **모델 실재 대조 (2026-08-20)**: 등록 모델이 제공자에서 조용히 사라지는 것을 `scripts/audit_model_inventory.py` 로 검사한다. 조회 실패와 소멸을 구분해 보고한다. `suitable_for` 가 빈 항목은 배정되지 않으므로 검사 대상이 아니다.
- **린터·보안·타입 게이트**: bandit 47건 오탐 판정 후 0건화(**이 실패가 CI 를 9시간 막았다**). mypy 58건 해소 후 `typecheck` 를 `check-all` 과 CI 에 배선.
- **프론트엔드 의존성 고정**: `package-lock.json` 추적, CI·Dockerfile 을 `npm ci` 로 통일.

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
- 블로킹 I/O 12건의 P95·태스크 처리량 개선치 미측정(4장 3번).

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

# 인수인계 문서 및 CURRENT_STATE 잔여 과업 전수 재판정 보고서

> **작성일**: 2026-09-20
> **작성자**: Orca Builder (Worker, task_1fb1362ffc82)
> **대상 Task**: `task_w1_handoff_backlog_reaudit`
> **단일 진실 원천(SSoT)**: `AGENTS.md`, `docs/context/CURRENT_STATE.md`
> **판정 기준일**: 2026-09-20
> **원칙**: 진실 우선순위(실제 코드 및 실측 아티팩트 > CURRENT_STATE.md > README.md > 과거 handoff). 코드를 수정하지 않고 판정만 수행.

---

## 1. 개요 및 목적

과거 인수인계 문서들과 `CURRENT_STATE.md` 6.1절에 남아 있는 잔여 과업들이 실제 코드베이스 및 실측 아티팩트와 어긋나, 이미 구현이나 측정이 완료된 과업이 차기 세션 착수 후보로 잘못 식별되는 현상이 발생했습니다(예: ChromaDB 검색 실패/0건 구분, CURRENT_STATE.md 압축 등).

본 보고서는 네 출처의 잔여 과업 총 20건(동일 항목 중복 포함)을 전수 수집하여 실제 코드와 문서 상태에 대조하고, 확정된 4대 판정 기준(`해소`, `유효`, `차단`, `시점미도래`)에 따라 전수 재판정한 결과를 기록합니다.

### 출처별 대상 과업 집계

| 출처 문서 | 대상 절 | 항목 수 | 비고 |
| --- | --- | :---: | --- |
| `docs/handoff/session_20260919_measurement_harnesses.md` | 7장 다음 세션이 확인할 과업 | 7건 | 최신 직전 세션 인수인계 |
| `docs/handoff/session_20260918_night_opus_parallel.md` | 7장 다음 세션이 확인할 과업 | 8건 | 전 세션 인수인계 |
| `docs/context/handoff_20260818.md` | 2장 다음에 이어서 할 것 (2.1 및 2.2) | 7건 | 구 인수인계 (코드 3건 + 실측 4건) |
| `docs/context/CURRENT_STATE.md` | 6.1절 알려진 미해결 사항 (Unknowns) | 4건 | 부팅 SSoT 문서의 미해결 목록 |
| **총계** | - | **26행 (출처별 기준)** | **20개 고유 과업** |

---

## 2. 잔여 과업 전수 재판정 총괄표

판정 기준:
- **해소**: 이미 코드 구현, 하니스 제작, 또는 실측이 완료되어 더 이상 할 일이 없음.
- **유효**: 선행 조건이 충족되어 지금 즉시 착수 가능함.
- **차단**: 외부 장비, 물리 환경, 운영 서버 접근 권한 등 외부 제약이 없어 착수 불가함.
- **시점미도래**: 도래 일시 또는 선행 일정(특정 일자) 조건이 아직 오지 않음 (오늘 기준: 2026-09-20).

| 출처 | 항목 | 판정 | 근거 (경로:행) | 다음 조치 |
| --- | --- | :---: | --- | --- |
| `docs/handoff/session_20260919_measurement_harnesses.md:136` | 인증 경로 P95 실측 | **해소** | `docs/analysis/auth_path_latency_20260919.md:1-50`<br>`docs/handoff/session_20260919_measurement_harnesses.md:136` | 단일 웜 P95 5ms 이하, c10 P95 39.2ms 이하로 실측 완료되어 과업표에서 제거 |
| `docs/handoff/session_20260919_measurement_harnesses.md:137` | 수집·드리프트 진행 관찰 (스택 기동 후) | **유효** | `src/tasks/scheduled_tasks.py:626-678`<br>`src/tasks/scheduled_tasks.py:809-850`<br>`docs/context/CURRENT_STATE.md:104` | Docker 스택 기동 후 `pipeline_executions` id 및 `retrain_logs` 드리프트 id 증가 확인 |
| `docs/handoff/session_20260919_measurement_harnesses.md:138` | 첫 주간 재학습 자동 승격 없는지 확인 (2026-09-21 03:00 이후) | **시점미도래** | `src/tasks/scheduled_tasks.py:494-525`<br>`src/tasks/retrain_task.py:223-235`<br>`docs/ops/weekly_retrain_verification.md:30-46` | 오늘(2026-09-20)은 실행 시점 이전이므로 2026-09-21 03:00 이후 `retrain_logs` 확인 |
| `docs/handoff/session_20260919_measurement_harnesses.md:139` | 운영 접근 확보 시 경로 A (ml_registry 재생성 선행) | **차단** | `docs/ops/ml_registry_production_bootstrap.md:18-56`<br>`src/ml/monitoring.py:208-218`<br>`.gitignore:198` | 운영 서버 접근 권한 및 운영 호스트 환경 부재로 실행 차단 유지 |
| `docs/handoff/session_20260919_measurement_harnesses.md:140` | 용역 표본 외 재비교 (2026-10 중순 이후) | **시점미도래** | `scripts/compare_servc_models_paired.py:356-375`<br>`docs/handoff/session_20260919_measurement_harnesses.md:121` | 사용자 지시로 2026-10 중순까지 Dispatch 금지 동결 |
| `docs/handoff/session_20260919_measurement_harnesses.md:141` | Windows Docker Desktop 실기 (장비 확보 시) | **차단** | `docs/ops/cross_platform_guide.md:1-227`<br>`tests/test_data_preservation.py:1-37` | Windows 실기 물리 장비 부재로 검증 불가 (G2 보류 유지) |
| `docs/handoff/session_20260919_measurement_harnesses.md:142` | chromadb CVE 재확인 (2026-12-31) | **시점미도래** | `.github/vulnerability-allowlist.yml:14-40`<br>`docs/analysis/chromadb_1x_upgrade_plan.md:11-34` | 예외 만료일 2026-12-31 도래 전까지 업그레이드 재제안 금지 유지 |
| `docs/handoff/session_20260918_night_opus_parallel.md:100` | `e6fe5eb5` CI Run 35350790021 결과 확인 | **해소** | `docs/handoff/session_20260919_measurement_harnesses.md:23-30`<br>`docs/handoff/session_20260919_measurement_harnesses.md:78` | 후속 커밋 `7502c7aa`, `48054365` 등에서 CI 10잡 전량 성공 확인 및 source_commit 갱신 완료 |
| `docs/handoff/session_20260918_night_opus_parallel.md:101` | 수집 id, 드리프트 id 진행 관찰 (스택 기동 후) | **유효** | `src/tasks/scheduled_tasks.py:626-678`<br>`src/tasks/scheduled_tasks.py:809-850` | Docker 스택 기동 후 6.1절 절차에 따라 확인 가능 |
| `docs/handoff/session_20260918_night_opus_parallel.md:102` | 낙찰 목록 순개선 크기 확정 (원할 때) | **해소** | `docs/analysis/read_path_ab_confirmation_20260919.md:1-56`<br>`docs/handoff/session_20260919_measurement_harnesses.md:43-52` | A/B 3왕복 교대 실측으로 낙찰 목록 1쪽 -62.7%, 50쪽 -61.5% 확정 완료 |
| `docs/handoff/session_20260918_night_opus_parallel.md:103` | 인증 경로 P95 (원할 때) | **해소** | `docs/analysis/auth_path_latency_20260919.md:41-51`<br>`docs/handoff/session_20260919_measurement_harnesses.md:13-14` | 전용 측정 계정 주입 후 실측 완료 (P95 2.71ms~4.36ms, c10 37.88ms~39.18ms) |
| `docs/handoff/session_20260918_night_opus_parallel.md:104` | 첫 주간 재학습 자동 승격 없는지 (2026-09-21 03:00 이후) | **시점미도래** | `src/tasks/scheduled_tasks.py:494-525`<br>`src/tasks/retrain_task.py:223-235` | 2026-09-21 03:00 도래 시점 이후 확인 |
| `docs/handoff/session_20260918_night_opus_parallel.md:105` | 운영 접근 확보 시 경로 A (ml_registry 재생성 선행) | **차단** | `docs/ops/ml_registry_production_bootstrap.md:18-56` | 운영 서버 접근 권한 미확보로 차단 유지 |
| `docs/handoff/session_20260918_night_opus_parallel.md:106` | 용역 표본 외 재비교 (2026-10 중순 이후) | **시점미도래** | `scripts/compare_servc_models_paired.py:356-375` | 2026-10 중순 도래 전까지 Dispatch 금지 |
| `docs/handoff/session_20260918_night_opus_parallel.md:107` | Windows Docker Desktop 실기 (장비 확보 시) | **차단** | `docs/ops/cross_platform_guide.md:1-227` | Windows 실기 물리 장비 부재로 차단 유지 |
| `docs/handoff/session_20260918_night_opus_parallel.md:108` | chromadb CVE 재확인 (2026-12-31) | **시점미도래** | `.github/vulnerability-allowlist.yml:14-40` | 만료일 2026-12-31 도래 전까지 예외 유지 |
| `docs/context/handoff_20260818.md:29` | ChromaDB 검색 실패와 결과 0건 구분 (P1) | **해소** | `src/rag/vector_store.py:58-68`<br>`src/rag/vector_store.py:555-572`<br>`src/rag/engine.py:198-204`<br>`src/rag/engine.py:811-831` | `SemanticSearchResult` 의 `ok`, `error`, `documents` 필드로 구현되어 상위 계층 구분 완료 |
| `docs/context/handoff_20260818.md:30` | `dispatch` 종료 코드 3 판정 시점 (P2) | **해소** | `scripts/orca_taskctl.py:5262-5271`<br>`scripts/orca_taskctl.py:5456-5484`<br>`tests/test_orca_taskctl.py:650-710` | 커밋 `7926b941` 에서 사후 도달 확인(`verify_instruction_delivered`) 체계로 전환 완료 |
| `docs/context/handoff_20260818.md:31` | CURRENT_STATE.md 압축 (P2) | **해소** | `docs/context/CURRENT_STATE.md:1-139` (실측 7,864자)<br>`scripts/validate_agent_rules.py:1000-1030` | 현재 7,864자로 목표치(8,000자 이하) 충족 완료 |
| `docs/context/handoff_20260818.md:35` | 블로킹 I/O 12건 P95 실측 | **해소** | `docs/analysis/blocking_io_p95_20260822.md:1-60`<br>`docs/context/current_state_history.md:1-50` | 2026-08-22 `benchmark_latency.py` 기반 3회 독립 측정 완료 (SSE 달성, 예측 API 웜 달성) |
| `docs/context/handoff_20260818.md:36` | `OLLAMA_NUM_PARALLEL` 병렬도 실험 | **차단** | `docs/analysis/ollama_c4_measure_20260823.md:1-136`<br>`docs/ops/sse_rebaseline_and_ollama_parallel_20260814.md:1-50` | 호스트 Ollama 사용자 소유 프로세스 재기동 및 Docker 단독 점유 권한 미확보 |
| `docs/context/handoff_20260818.md:37` | Windows Docker Desktop 실기 E2E | **차단** | `docs/ops/cross_platform_guide.md:1-227` | Windows 물리 장비 미확보로 차단 유지 |
| `docs/context/handoff_20260818.md:38` | 수집 2·3회차 관찰 | **해소** | `docs/analysis/collection_rounds_observation_20260823.md:100-136`<br>`docs/handoff/2026-08-23_followup_audit_closure.md:50-58` | 수집 2·3회차 실행 이력 및 DB 적재 무결성 확인 완료 (후속 4회차 대기 상태로 전환됨) |
| `docs/context/CURRENT_STATE.md:120` | Windows Docker Desktop 실기 (2026-09-03, 미검증) | **차단** | `docs/ops/cross_platform_guide.md:1-227`<br>`docs/context/current_state_facts.yaml:345` | Windows 실기 물리 장비 부재로 차단 유지 |
| `docs/context/CURRENT_STATE.md:121` | 손상 탐침 제거 (2026-09-11, 구조적 제거 확정·효과 크기 미확정) | **유효** | `src/rag/structured_data.py:806-831`<br>`docs/analysis/aw2_probe_removal_effect_20260911.md:20-33` | 구조적 0ms는 확정되었으나 잔여 분산에 따른 총 시간 효과 크기 확정 실측 가능 (Docker 가동 시) |
| `docs/context/CURRENT_STATE.md:122` | 측정 설계와 실행계획 조사 (2026-09-11, 도구 완비·원인 미확정) | **유효** | `docs/analysis/ax2_plan_instability_20260911.md:11-40`<br>`src/app/services/dashboard.py:480-500` | compare-stats 스냅샷 도입으로 서비스 영향은 해소되었으나, 단일 EXISTS 질의의 옵티마이저 계획 전환 원인 조사 자체는 착수 가능 |
| `docs/context/CURRENT_STATE.md:123` | ChromaDB 1.x 업그레이드 (2026-09-13, 보류) | **시점미도래** | `docs/analysis/chromadb_1x_upgrade_plan.md:11-34`<br>`.github/vulnerability-allowlist.yml:14-40` | 상류 미수정 및 서버 미노출 사유로 2026-12-31까지 보류 동결 |

---

## 3. 해소 판정 항목의 해소 근거 분석

이미 구현·측정되어 더 이상 작업할 필요가 없는 8개 고유 항목(총 12개 행)의 해소 일시와 커밋/코드 근거는 다음과 같습니다.

### 1) ChromaDB 검색 실패와 결과 0건 구분
- **출처**: `docs/context/handoff_20260818.md:29`
- **해소 일시 및 근거**:
  - `src/rag/vector_store.py:58-68`: `SemanticSearchResult` 데이터클래스에 `ok: bool`, `error: str | None = None`, `documents: list[dict[str, Any]]` 필드가 선언됨.
  - `src/rag/vector_store.py:555-572`: 예외 발생 시 `SemanticSearchResult(ok=False, documents=[], error=str(exc))`를 반환하고, 검색 결과가 0건일 때는 `ok=True, documents=[]`를 반환하도록 분리됨.
  - `src/rag/engine.py:198-204` 및 `811-831`: 호출부에서 `result.ok`가 False일 때 `vector_failed = True`를 설정하고, `ok=True`이면서 빈 결과일 때는 "필터 조건에 맞는 문서가 0건이라 문맥 없이 답변합니다" 힌트를 주입하도록 분기 처리 완료.

### 2) `dispatch` 종료 코드 3 판정 시점
- **출처**: `docs/context/handoff_20260818.md:30`
- **해소 일시 및 근거**:
  - 커밋 `7926b941` (`fix: Dispatch 가 지시 도달 미확인을 성공으로 보고하던 문제를 고친다`, 2026-08-18).
  - `scripts/orca_taskctl.py:5262-5271`: Dispatch 전 터미널 상태가 `unreadable` 또는 `not_settled`여도 중단하지 않고 사전 경고(`pre_dispatch_warnings`)에만 담은 뒤 계속 진행.
  - `scripts/orca_taskctl.py:5456-5484`: Dispatch 이후 실제 화면에 지시 표지가 떴는지 확인하는 `verify_instruction_delivered(args.terminal, [probe])` 사후 검증 단계 도입. 사후 확인에 성공하면 사전 경고를 해소된 것으로 판정하여 불필요한 종료 코드 3 오탐을 제거함.

### 3) CURRENT_STATE.md 압축
- **출처**: `docs/context/handoff_20260818.md:31`
- **해소 일시 및 근거**:
  - `docs/context/CURRENT_STATE.md`: 2026-09-20 현재 파일 문자 수 실측 결과 **7,864자**로 정규화 상한인 8,000자 이하를 완벽히 준수함.
  - `scripts/validate_agent_rules.py:1000-1030`의 `check_context_budget` 검증에서도 통과(PASS)됨.

### 4) 블로킹 I/O 12건 P95 실측
- **출처**: `docs/context/handoff_20260818.md:35`
- **해소 일시 및 근거**:
  - 2026-08-22 `docs/analysis/blocking_io_p95_20260822.md:1-60` 보고서 작성 완료.
  - 대상 커밋 `e219d9cc537e9d88b6720a62d345e97c65ded9e5`에서 `scripts/benchmark_latency.py`를 통해 3회 독립 측정을 완료함 (정본 SSE 첫 토큰 P95 1,263.4ms, SSE 완료 P95 7,194.0ms, 낙찰가 예측 API c10 웜 61.9~83.6ms 달성 확인).

### 5) 수집 2·3회차 관찰
- **출처**: `docs/context/handoff_20260818.md:38`
- **해소 일시 및 근거**:
  - 2026-08-23 `docs/analysis/collection_rounds_observation_20260823.md:100-136` 및 `docs/handoff/2026-08-23_followup_audit_closure.md:50-58`에 기록 완료.
  - DB 행 수 실측(`bid_announcements` 5,475,948행, `bid_results` 3,413,823행, `collected_at` 2026-08-14)을 코디네이터가 대조 확인하여 종결함.

### 6) 낙찰 목록 순개선 크기 확정
- **출처**: `docs/handoff/session_20260918_night_opus_parallel.md:102`
- **해소 일시 및 근거**:
  - 2026-09-19 커밋 `ec882eee` 및 `docs/analysis/read_path_ab_confirmation_20260919.md:1-56`.
  - 선채움 ON/OFF 3왕복 A/B 교대 측정을 통해 낙찰 목록 1쪽 P95 -62.7% (75.28ms vs 202.01ms), 50쪽 -61.5%, 홈 컨텍스트 -47.8%로 순개선 크기를 공식 확정함.

### 7) 인증 경로 P95 실측
- **출처**: `docs/handoff/session_20260918_night_opus_parallel.md:103`, `docs/handoff/session_20260919_measurement_harnesses.md:136`
- **해소 일시 및 근거**:
  - 2026-09-19 커밋 `a5ec3252` 및 `docs/analysis/auth_path_latency_20260919.md:1-50`.
  - 측정 전용 계정 `sojiroh` 주입 후 부작용 없는 3개 경로(`GET /accounts/me`, `GET /evaluations/profiles`, `GET /evaluations/snapshots`)에 대해 단일 웜 2.71~4.36ms, 동시성 c10 37.88~39.18ms로 실측 완료. 최적화 후보 없음으로 판정됨.

### 8) `e6fe5eb5` CI Run 35350790021 결과 확인
- **출처**: `docs/handoff/session_20260918_night_opus_parallel.md:100`
- **해소 일시 및 근거**:
  - 2026-09-19 `docs/handoff/session_20260919_measurement_harnesses.md:23-30` 및 `78`.
  - `source_commit` 갱신(`7502c7aa`, `3fb00737`) 및 게이트 10 병합(`48054365`) 과정에서 CI 10개 잡 전량 success 확인 완료.

---

## 4. 유효 판정 항목 (차기 착수 후보 절)

전수 20개 고유 과업 중 현재 시점에서 즉시 착수 가능한 유효 과업은 다음 3건입니다. 각 항목의 선행 조건을 준수해야 합니다.

### 1) 수집 및 드리프트 진행 관찰
- **대상**:
  - 수집 파이프라인(`pipeline_executions`) id 증가 및 상태 확인
  - 일일 04:00 드리프트 모니터링(`retrain_logs`) id 10 이후 진행 확인
- **선행 조건**:
  - Docker Compose 스택 기동 (`docker compose up -d`)
  - Arq 워커 및 Redis, MySQL 정상 기동 상태 (`ready 200`)
  - DB 직접 변경 금지 및 `scripts/db_readonly_query.py`를 통한 단일 SELECT 문 조회 준수

### 2) 손상 탐침 제거 총 시간 효과 크기 확정 조사
- **대상**:
  - `src/rag/structured_data.py:806-831`의 마커 기반 우회 후 RAG 콜드 쿼리 총 시간(`sql_ms`)의 실질 개선 효과 크기 측정
- **선행 조건**:
  - Docker Compose 백엔드 스택 기동
  - `rebuild_ranking_snapshots(force_weekly=True)`로 스냅샷 마커 사전 생성
  - 다른 워커 작업이 없는 조용한 저장소 및 호스트 부하 통제 환경 확보

### 3) 측정 설계와 실행계획 조사 (단일 EXISTS 질의 옵티마이저 계획 전환 원인 규명)
- **대상**:
  - `docs/analysis/ax2_plan_instability_20260911.md`에서 미확정으로 남은 단일 EXISTS 질의의 옵티마이저 인덱스 범위 스캔 vs 풀 스캔 뒤집힘 원인 분석
- **선행 조건**:
  - MySQL 8 인스턴스 접근 권한
  - `compare_stats_snapshot` 도입으로 서비스 지연 영향은 이미 해소되었음을 인지하고, 성능 개선 목적이 아닌 순수 옵티마이저 동작 분석 목적으로 한정하여 진행

---

## 5. 차단 및 시점미도래 항목 정리

### 차단 항목 (4건)
1. **운영 접근 확보 시 경로 A 실행 (ml_registry 재생성 선행)**:
   - 사유: 운영 서버 접근 권한 및 운영 호스트 환경 부재 (`docs/ops/ml_registry_production_bootstrap.md`).
2. **Windows Docker Desktop 실기 검증 (G2 보류)**:
   - 사유: Windows Docker Desktop 구동 가능한 물리 장비 미확보 (`docs/ops/cross_platform_guide.md`).
3. **`OLLAMA_NUM_PARALLEL` 병렬도 실험**:
   - 사유: 사용자 소유 호스트 Ollama 프로세스 재기동 권한 및 Docker 단독 점유 환경 미확보 (`docs/analysis/ollama_c4_measure_20260823.md`).

### 시점미도래 항목 (3건)
1. **첫 주간 재학습 자동 승격 여부 확인**:
   - 사유: 실행 일시가 매주 월요일 03:00 KST이므로, 2026-09-21 03:00 KST 이후 확인 가능 (`src/tasks/scheduled_tasks.py:494`).
2. **용역 표본 외 재비교**:
   - 사유: 사용자 지시로 2026-10 중순 이후까지 Dispatch 금지 동결 (`scripts/compare_servc_models_paired.py`).
3. **chromadb CVE 재확인**:
   - 사유: 취약점 공급망 예외 만료일인 2026-12-31까지 상류 수정 버전 확인 보류 (`.github/vulnerability-allowlist.yml`).

---

## 6. 결론 및 코디네이터 권고 사항

1. 과거 인수인계 문서(2026-08-18, 2026-09-18, 2026-09-19) 및 `CURRENT_STATE.md` 6.1절의 잔여 과업 총 26개 행(고유 20건) 중 **8건(12행)이 이미 완전히 해소**되었음을 실측과 소스 코드로 확인하였습니다.
2. 현재 착수 가능한 유효 과업은 **수집/드리프트 진행 관찰, 손상 탐침 총 시간 효과 크기 조사, 단일 질의 실행계획 전환 원인 규명**의 3건뿐입니다.
3. 향후 코디네이터는 본 보고서의 판정표를 기반으로 `CURRENT_STATE.md` 6.1절을 갱신하고, 이미 해소된 과업들이 다음 세션의 인수인계나 백로그에 재진입하지 않도록 관리할 것을 권고합니다.

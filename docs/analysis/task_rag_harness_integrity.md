# RAG 세그먼트 벤치마크 하네스 무결성 결박 및 검증 분석 보고서

> **작성일**: 2026-08-24
> **작업 Task ID**: `task_7e0c008f7e36`
> **작업 Dispatch ID**: `ctx_594c3e0f431d`
> **관련 Capsule**: `.orca/capsules/task_rag_harness_integrity/capsule.yaml`

---

## 1. 개요 및 변경 목적

기존 `scripts/benchmark_rag_segments.py`는 `base_url`과 대상 컨테이너(`target_container`)의 포트 바인딩 및 이미지 정합성을 엄밀히 결박하지 않았고, 시간 범위(`docker logs --since`) 내 모든 로그를 읽어 외부 요청 로그나 누락을 감지하지 못했습니다. 또한 HTTP 부분 실패 시에도 `status: partial`을 반환하며 종료 코드 0으로 끝나는 결함이 존재했습니다.

본 작업에서는 RAG 세그먼트 벤치마크 하네스를 공통 provenance 계층(`scripts/benchmark_provenance.py`)에 결박하고, 기대 LLM 모델 비교, HTTP 응답 헤더 기반 1:1 trace 상관 대조, HTTP 부분 실패 및 정합성 실패 시 non-zero 비정상 종료를 fail-closed로 구현하여 벤치마크 증거의 신뢰성과 재현성을 확보했습니다.

---

## 2. 주요 변경 사항 상세

### 2.1 공통 Provenance 결박 및 모델 정합성 검증 (`scripts/benchmark_rag_segments.py`)

- **공통 Provenance 연동**:
  - `scripts.benchmark_provenance`의 `reproducibility_metadata`, `verify_provenance_consistency`, `HostLoadMonitor`, `BuildProvenanceError`를 임포트하여 측정 시작과 종료 시점의 컨테이너 ID, 이미지 ID, RepoDigest, 바인드 마운트 소스 SHA 및 dirty 상태를 fail-closed로 검증합니다.
  - `base_url` 포트와 도커 컨테이너의 published port가 일치하지 않으면 즉시 exit 2로 중단합니다.
  - 측정 중 컨테이너 교체나 소스 변경이 발생하면 exit 2로 중단합니다.
- **`--expected-llm-model` 필수 검증**:
  - CLI 인자로 기대 모델명을 입력받고, 런타임 컨테이너의 `OLLAMA_MODEL`과 불일치하거나 미지정된 경우 측정 전 exit 2로 즉시 종료합니다.
- **호스트 부하 계측**:
  - `HostLoadMonitor`를 통해 벤치마크 수행 중 5초 간격으로 코어당 부하를 수집하여 결과 payload에 보존합니다.

### 2.2 HTTP 응답 헤더 기반 1:1 Trace 상관 검증

- **응답 헤더 노출 (`src/app/api/v1/chatbot.py`)**:
  - `POST /api/v1/chatbot/query` 엔드포인트에서 기존 응답 바디(`ChatbotQueryResponse`) 스키마 계약을 100% 보존하면서, `bundle.provenance.trace_id`를 `X-RAG-Trace-Id` 안전 헤더로 반환합니다.
- **1:1 대조 및 무결성 판정 (`verify_trace_correlation`)**:
  - 하네스는 각 HTTP 응답의 `X-RAG-Trace-Id`를 수집하고, 컨테이너 로그에서 파싱된 `rag_engine_latency:` 레코드의 `trace_id`와 1:1 집합 대조를 수행합니다.
  - 다음 조건 중 하나라도 위반 시 `status="integrity_error"`, `canonical_success=False`, `exit 1`로 처리합니다:
    1. 성공 요청 수 != 기대 라운드 수
    2. 응답 trace 중복 발생
    3. 세그먼트 로그 레코드 수 != 기대 라운드 수
    4. 로그 trace 중복 발생
    5. 외부 요청 로그 trace 혼입 (`unmatched_log_traces`)
    6. 요청 성공 trace의 로그 누락 (`missing_log_traces`)
- **부분 실패 fail-closed 종료**:
  - HTTP 실패가 1건이라도 발생하면 `status="partial"`, `canonical_success=False`, `exit 1`로 종료합니다.
  - 20회 요청 기준 성공 trace와 세그먼트 로그가 정확히 20건 1:1 일치할 때만 `status="ok"`, `canonical_success=True`, `exit 0`으로 종료합니다.

### 2.3 서버 세그먼트 로거 전달 보장 (`src/app/main.py`)

- `_enable_latency_segment_logging()`에서 루트 로거의 핸들러 존재 여부와 무관하게 `src.rag.engine` 로거에 핸들러가 없으면 자체 `StreamHandler(sys.stdout)`를 추가하도록 수정했습니다.
- `segment_logger.propagate = False`를 유지하여 루트 로거로의 중복 로그 출력을 방지하면서도 로그 유실을 원천 차단했습니다.

---

## 3. 검증 결과 및 체크리스트

### 3.1 Review Checklist 대조

| 항목 ID | 점검 질문 | 판정 기준 | 실측 결과 |
| --- | --- | --- | --- |
| `expected_model` | 기대 모델이 없거나 runtime 값과 다르면 요청 전에 실패하는가 | defect_when: no | 통과 (미지정/불일치 시 exit 2 반환 단위 테스트 통과) |
| `target_binding` | base_url이 target_container의 published port와 결박되는가 | defect_when: no | 통과 (포트 불일치 시 BuildProvenanceError로 exit 2 반환) |
| `exact_trace_set` | 성공 응답 trace 집합과 수집 segment trace 집합이 중복 없이 정확히 같은가 | defect_when: no | 통과 (중복, 누락, 외부 로그 반례 100% 탐지) |
| `partial_nonzero` | HTTP 실패 또는 record 불일치가 있어도 exit 0인 경로가 남아 있는가 | defect_when: yes | 통과 (부분 실패 exit 1, 정합성 실패 exit 1 반환) |
| `response_compat` | trace 노출을 위해 기존 JSON response body schema를 변경했는가 | defect_when: yes | 통과 (헤더만 추가, 바디 스키마 및 직렬화 100% 불변) |
| `logger_delivery` | root handler가 있는 경우 segment logger가 handler와 propagation 모두 잃는가 | defect_when: yes | 통과 (루트 핸들러 유무와 관계없이 자체 핸들러 확보) |

### 3.2 테스트 수행 결과

1. **RAG 하네스 및 API 대상 테스트**:
   - `uv run pytest tests/test_benchmark_rag_segments.py tests/test_api_v1.py -v` -> **47 passed, 1 skipped (0.11s + 2.11s)**
2. **코드 린트 검증**:
   - `uv run ruff check scripts/benchmark_rag_segments.py tests/test_benchmark_rag_segments.py src/app/main.py src/app/api/v1/chatbot.py tests/test_api_v1.py` -> **All checks passed!**
3. **전체 단위/회귀 테스트 스위트**:
   - `uv run pytest tests/ -q -m 'not data_assets'` -> **1883 passed, 6 skipped, 3 deselected** (CURRENT_STATE source_commit 신선도 관련 사전 인지된 2건 제외 전량 통과)

---

## 4. 잔여 과업 및 인수인계 사항

- **CURRENT_STATE.md 신선도**: `source_commit 4161269`이 HEAD보다 뒤처진 현상은 다중 작업 병합 완료 후 코디네이터/SSOT Task에서 최종 HEAD로 일괄 갱신 예정입니다.
- **Canonical Baseline 승격**: 향후 고정 환경에서 실측된 20/20 1:1 상관 검증 결과만 정본 baseline으로 승격 가능합니다.

# Task Analysis Report: Orca Control Plane Defect Remediation (O-04, O-05, O-06)

> **Task ID**: `task_4fcf2a95ff6f`
> **작성일**: 2026-09-05
> **목적**: Orca 통제면의 잔여 3개 결함(O-04 DAG 의존성 미연결, O-05 완료 보고 스키마 3중 불일치, O-06 비감독 Dispatch 수명주기 receipt 부재) 해소 및 회귀 방지 검증

---

## 1. 개요

2026-09-04 외부 진단 보고서의 P1 항목 중 Wave T에서 해결된 O-01, O-02, O-03에 이어 남아 있던 3건의 결함을 코드로 닫고 단일 진실 원천(Single Source of Truth)을 확립했습니다:

| 결함 ID | 결함 내용 | 조치 결과 |
| --- | --- | --- |
| **O-04** | 리뷰 Task 생성 시 빌더 Task 의존성 미연결, 반려 후 rework 시 DAG 이력 단절 | `target_task` / `target_task_id` 의존성 자동 추출 및 `--deps` 주입, `rework` 시 원본 Task ID 를 `--deps` 로 자동 연결하여 DAG 이력 영구 보존 |
| **O-05** | 완료 보고 필수 필드 정의가 템플릿, 검증기(`REQUIRED_FIELDS`), Capsule 고지문 간 3중 불일치 및 `dispatch_id` 누락 | `scripts/orca_contract.py` 에 `WORKER_DONE_SCHEMA_SPEC` 단일 정본을 정의하고 검증기/고지문/템플릿을 정본으로부터 직접 파생. 하위 호환성을 위해 `dispatch_id` 는 선택 필드로 유지하고 템플릿 완전 동기화 강제 |
| **O-06** | 비감독 경로(`dispatch --inject`, 터미널 부착) 기동 시 `worker_dispatches` 행 미생성으로 잔류 감사 누락 | 비감독 기동 시 `.orca/dispatch_receipts/<task_id>.json` 영수증 기록, `scripts/orca_settled_session_audit.py` 에서 영수증을 로드하여 완료된 비감독 세션 터미널 잔류 검출 |

---

## 2. 세부 변경 내역

### 2.1 O-05: 완료 보고 스키마 단일 진실 원천 및 `dispatch_id` 정합성 확립

1. **정본 단일화 (`scripts/orca_contract.py`)**:
   - `WORKER_DONE_SCHEMA_SPEC`: 필수 필드(12개)와 부가 필드(5개)를 포괄하는 단일 정본 정의.
   - `get_worker_done_required_fields()`: 필수 필드 튜플 도출.
   - `render_worker_report_schema()`: Capsule `report_schema:` 블록 동적 렌더링.
   - `render_worker_done_template()`: `.agents/templates/worker_done_v2.json` 구조 동적 렌더링.
   - `sync_worker_done_template()`: 정본 렌더러에서 디스크 템플릿 파일 생성 및 동기화 함수 추가.
2. **검증기 연동 (`scripts/summarize_worker_done.py`)**:
   - `REQUIRED_FIELDS = WORKER_DONE_REQUIRED_FIELDS` 로 정본에서 직접 참조 (12개 필수 필드).
3. **고지문 연동 (`scripts/orca_taskctl.py`)**:
   - `WORKER_REPORT_SCHEMA = render_worker_report_schema()` 로 정본에서 직접 렌더링.
4. **템플릿 정합성 (`.agents/templates/worker_done_v2.json`)**:
   - `render_worker_done_template()` 출력과 100% 완전 일치하도록 테스트로 강제하고, `sync_worker_done_template()` 을 제공하여 정본으로부터 직접 동기화 보장.
5. **`dispatch_id` 결정 근거**:
   - Orca 수명주기 메시지의 dispatchId 와 보고 JSON 의 dispatch_id 는 다른 계층이며, 기존 검증 게이트(`tests/test_orca_worker_done_gate.py`, `tests/test_orca_verification_truth.py`) 및 레거시 워커 보고서와의 100% 하위 호환성을 유지하기 위해 `dispatch_id` 는 정본에서 `required: False` 로 결정.
   - 단일 정본 `WORKER_DONE_SCHEMA_SPEC` 에 정의되어 템플릿(`worker_done_v2.json`)에 일관되게 제공되며, 검증기(`REQUIRED_FIELDS`) 및 고지문(`WORKER_REPORT_SCHEMA`)의 필수 필드 12개와 100% 일치함.

### 2.2 O-04: 리뷰 및 재작업 Task DAG 의존성 자동 연결

1. **리뷰 Task 의존성 자동 연결**:
   - `parse_intent` 에서 `target_task`, `target_task_id`, `builder_task`, `deps` 파싱 지원.
   - `resolve_intent_deps(intent)` 유틸리티를 추가하여 `cmd_create` 및 `cmd_dispatch` 시 `--deps` 미지정 시 Intent의 대상 Task를 JSON 배열(`'["task_..."]'`)로 변환하여 `orca orchestration task-create --deps` 에 연결.
2. **재작업(rework) Task DAG 이력 보존**:
   - `cmd_rework` 호출 시 반려 대상인 원본 `task_id` 를 새 Task의 `--deps` 로 기본 연결.
   - 이를 통해 Orca DAG 상에 `원본 Task -> 재작업 Task` 관계가 명시적으로 기록됨.

### 2.3 O-06: 비감독 Dispatch 수명주기 영수증 및 잔류 세션 검출

1. **비감독 영수증 발급 (`scripts/orca_taskctl.py`)**:
   - `record_unsupervised_dispatch_receipt()` 함수 신설.
   - `--terminal` 부착 경로 또는 런처 경로 기동 시 `.orca/dispatch_receipts/<task_id>.json` 에 기계 판독 가능한 JSON 파일 저장 (`schema`, `task_id`, `dispatch_id`, `terminal`, `handle`, `worktree_path`, `started_at`, `supervised: false`).
2. **잔류 세션 감사 연동 (`scripts/orca_settled_session_audit.py`)**:
   - `load_unsupervised_receipts()` 함수를 통해 영수증 디렉터리를 스캔.
   - `lingering_settled_sessions()` 에서 Orca dispatch 행이 없는 세션이라도 영수증을 대조하여 터미널이 여전히 열려 있으면 `supervised: false` 와 함께 잔류 세션으로 검출.

---

## 3. 검증 결과

1. **통제면 단위 및 회귀 테스트**:
   - `tests/test_orca_taskctl.py`
   - `tests/test_summarize_worker_done.py`
   - `tests/test_orca_contract.py`
   - `tests/test_orca_settled_session_audit.py`
   - 총 309건 전량 통과 (O-04 리뷰/재작업 의존성 자동 연결, O-05 정본 파생 및 필드 추가 전파 검증, O-06 영수증 기록 및 잔류 검출 테스트 완비).
2. **전체 테스트 스위트 회귀 검증**:
   - `uv run pytest tests/ -q -m 'not data_assets'`: 3,628 passed, 41 skipped, 3 deselected in 112s (100% 통과).
3. **에이전트 규칙 검증**:
   - `python3 scripts/validate_agent_rules.py --quiet`: 통과 (20/20 건).

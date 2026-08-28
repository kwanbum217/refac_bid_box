# Task task_ea8ae09336e5 — verification 재실행 타임아웃 명령 종류별 분리 분석 보고서

> **작성일**: 2026-08-28
> **작업 ID**: `task_ea8ae09336e5`
> **상태**: 완료
> **관련 문서**: [`docs/ops/orca_task_capsule_v2.md`](../ops/orca_task_capsule_v2.md), [`scripts/orca_contract.py`](../../scripts/orca_contract.py)

---

## 1. 개요 및 배경

### 1.1 배경
과거 `verify_verification_truth`는 모든 검증 재실행 명령에 대해 30초 고정 타임아웃(`timeout: int = 30`)을 일괄 적용했습니다. 그러나 본 저장소의 전체 테스트 스위트(`pytest`) 실행은 실측 63~117초가 소요됩니다. 이에 따라 워커가 전량 pytest를 성실히 수행하고 결과를 보고했음에도 불구하고 Level 1 게이트 6의 진실성 검증 단계에서 30초 타임아웃으로 잘려 게이트가 형식적으로 실패(`재실행 타임아웃 (30초)`)하는 문제가 발생했습니다.

또한 타임아웃 실패 시 단순 실패 메시지만 남아, 명령 종류별 적용 타임아웃 값이나 타임아웃 여부를 명확히 식별하기 어려웠습니다.

### 1.2 목표
1. 검증 명령 종류별 타임아웃 기준을 분리하여 상수로 정의 (pytest 계열 900초, validate_agent_rules 계열 30초).
2. 명령 분류 및 타임아웃 결정을 순수 함수로 분리하여 단위 테스트 가능하도록 구조화.
3. `verify_verification_truth`가 기본적으로 명령 종류별 기본 타임아웃을 적용하되, 호출자의 명시적 타임아웃 지정이 최우선 적용되도록 보장.
4. 타임아웃 발생 시 `timed_out: true` 필드 및 명령 종류/적용 시간을 포함한 위반 메시지로 검증 실패와 명확히 구분하여 표기하되, 게이트 실패(Fail-Closed) 원칙은 엄격히 유지.
5. 관련 회귀 테스트 및 문서화 완료.

---

## 2. 변경 내용 및 구현 상세

### 2.1 타임아웃 상수 및 명령 분류 순수 함수 정의 (`scripts/orca_contract.py`)

- **타임아웃 상수 정의**:
  - `DEFAULT_VERIFY_PYTEST_TIMEOUT = 900` (`scripts/orca_level1_gate.py`의 `DEFAULT_PYTEST_TIMEOUT`과 동일한 15분 기준).
  - `DEFAULT_VERIFY_VALIDATE_TIMEOUT = 30` (규칙 검사용 30초 기준).
  - `DEFAULT_VERIFY_TIMEOUT = 30` (기타 미분류용 fallback).
- **명령 분류 함수 `classify_verification_command`**:
  - `pytest` 계열: `("pytest", argv)` 반환 (예: `pytest ...`, `uv run pytest ...`, `python3 -m pytest ...`).
  - `validate_agent_rules` 계열: `("validate_agent_rules", argv)` 반환.
  - 화이트리스트 외 명령: `("unknown", None)` 반환.
- **타임아웃 결정 함수 `get_verification_timeout`**:
  - 사용자 지정 타임아웃(`custom_timeout`)이 존재하면 최우선 반환.
  - 미지정 시 명령 종류에 따른 기본 타임아웃(pytest: 900초, validate_agent_rules: 30초) 반환.
- **하위 호환성 유지**:
  - `is_whitelisted_verification_command`는 `classify_verification_command`를 호출하여 기존 `(bool, list[str] | None)` 인터페이스를 100% 유지.

### 2.2 진실성 검증 로직 개선 (`scripts/orca_contract.py`)

- `verify_verification_truth(repo, verification, timeout: int | None = None)`으로 기본값을 `None`으로 변경하여, 호출자가 명시하지 않은 경우 각 명령 종류별 적정 타임아웃이 자동 적용되도록 개선.
- `subprocess.TimeoutExpired` 발생 시:
  - 위반 메시지에 명령 종류와 적용된 타임아웃 초를 명시: `f"재실행 타임아웃 ({cmd_type}, {effective_timeout}초): '{cmd_clean}'"`.
  - `detailed_results` 항목에 `timed_out: True`, `timeout_seconds: effective_timeout`, `command_type: cmd_type`를 기록.
  - `violations.append(msg)` 및 `all_ok = False`로 Fail-Closed 유지.

### 2.3 규약 문서 업데이트 (`docs/ops/orca_task_capsule_v2.md`)

- 섹션 3.1.2에 명령 종류별 타임아웃 표, 판별 기준, 기본 타임아웃, 설정 근거(전량 pytest 실측 63~117초) 및 Fail-Closed 처리 원칙을 상세히 기록.

---

## 3. 검증 결과

| 검증 항목 | 명령어 | 결과 |
| --- | --- | --- |
| 단위 테스트 및 신규 회귀 테스트 | `uv run pytest tests/test_orca_contract.py tests/test_summarize_worker_done.py tests/test_orca_level1_gate.py tests/test_orca_verification_truth.py -q` | 통과 (113 passed) |
| 전체 테스트 스위트 | `uv run pytest tests/ -q -m 'not data_assets'` | 통과 |
| 에이전트 규칙 검증 | `python3 scripts/validate_agent_rules.py --quiet` | 통과 |
| 린터 검증 | `uv run ruff check src/ scripts/ tests/` | 통과 |
| 문서 링크 검증 | `uv run python scripts/validate_doc_links.py` | 통과 |

---

## 4. 결론 및 기대 효과

전량 pytest 실행 등 정상적으로 수십 초 이상 소요되는 장시간 테스트 명령이 30초 고정 제한으로 인해 형식 실패하던 문제가 완전히 해결되었습니다. 타임아웃 발생 시에도 명령 종류와 설정 시간이 명확히 진단되며, 게이트의 Fail-Closed 보안 원칙은 변함없이 안전하게 유지됩니다.

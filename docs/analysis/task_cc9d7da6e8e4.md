# Level 1 기계 검증 게이트 보강 및 다중 보고서 지원 (task_cc9d7da6e8e4)

> **작성일**: 2026-09-05
> **브랜치**: kwanbum217/wave-w-v1-gate
> **태스크**: task_cc9d7da6e8e4
> **역할**: builder

---

## 1. 목적

Wave U 및 이전 운영에서 발생한 Level 1 기계 검증 게이트의 구조적 구멍 2건 및 expand 연동 결함을 해소합니다:
1. **신규 B (backend_mypy)**: src/ 하위 파이썬 코드 변경 시 타입 검증(mypy)이 누락되어 병합 후 CI 단계에서 뒤늦게 회귀가 검출되는 문제 방지.
2. **신규 C (게이트 6 다중 보고서 합집합)**: 재작업 브랜치 등에서 둘 이상의 worker_done 보고서가 생성될 때, 단일 보고서만으로는 브랜치 전체 diff를 설명하지 못해 게이트 6이 구조적으로 실패하던 문제 해결.
3. **신규 G (orca_taskctl.py expand 연동)**: Task Intent에 명시된 verification_commands 및 shared_resources가 덮어써져 유실되지 않도록 보존하고, src/ 대상 Task에 uv run mypy src를 자동 부착.

---

## 2. 변경 내역 요약

### 2.1 scripts/orca_level1_gate.py
- **CAP_BACKEND_MYPY = "backend_mypy" 능력 추가**:
  - _path_capabilities: src/ 하위 .py 파일(또는 와일드카드) 변경 감지 시 {CAP_BACKEND_PYTEST, CAP_BACKEND_MYPY} 반환.
- **명령 허용 목록 갱신**:
  - parse_verification_command: uv run mypy ...를 정규 검증 러너로 등록하고 CAP_BACKEND_MYPY 능력 제공으로 매핑.
- **게이트 6 다중 보고서 합집합 검증 (run_gate6_worker_done)**:
  - --report / --reports 다중 지정 및 쉼표 구분 지원.
  - changed_files는 전체 보고서의 합집합(union_changed_files)을 추출하여 브랜치 실제 diff(git diff base...branch)와 1:1 대조.
  - 계약 필드, 커밋/브랜치 실존성, 검증 명령 건수, verdict 등 진실성 검사는 각 보고서별로 독립 수행하여 1건이라도 위반 시 fail 판정.
  - 단일 보고서 경로 전달 시 기존 raw_data 및 digest 형식과 100% 동일하게 동작하도록 하위 호환성 보장.

### 2.2 scripts/summarize_worker_done.py
- **다중 보고서 요약 함수 (summarize_worker_reports) 추가**:
  - 복수 보고서 파일을 순회하며 각각 summarize_worker_report를 호출하고, changed_files 합집합 및 누적 위반(violations) 집계.
  - 어느 하나라도 위반 또는 blocked인 경우 최종 exit_code = 1, effective_verdict = "blocked" 반환.
- **CLI main(argv=...) 다중 --report 지원**:
  - --report 플래그 반복 지정 및 쉼표 구분 파싱.

### 2.3 scripts/orca_taskctl.py
- **mypy 검증 명령 상수 등록**:
  - MYPY_VERIFICATION_COMMAND = "uv run mypy src" 등록 및 CAPABILITY_COMMANDS에 (CAP_BACKEND_MYPY, MYPY_VERIFICATION_COMMAND) 매핑.
- **Intent 파싱 및 보존**:
  - parse_intent: shared_resources 및 verification_commands 블록 파싱 지원.
  - resolve_shared_resources: Intent 선언 자원과 경로 자동 감지 자원을 안전하게 병합.
  - resolve_verification_commands: Intent 선언 명령을 보존하며, 미선언 시 src/ 대상에 uv run mypy src 자동 부착.
  - expand_intent_to_capsule: Intent 선언 연동.

### 2.4 스킬 정본 및 미러 동기화
- .agents/skills/orca-section-coordination/SKILL.md (정본)
- .claude/skills/orca-section-coordination/SKILL.md (미러)
- .opencode/skills/orca-section-coordination/SKILL.md (미러)
- 3개 파일의 2.1절 표에 src/**/*.py (backend_pytest, backend_mypy) 및 허용 러너(uv run mypy ...)를 100% 동일하게 동기화하여 scripts/validate_agent_rules.py 검증 20/20 통과.

---

## 3. 검증 결과

### 3.1 단위 및 회귀 테스트
- tests/test_orca_level1_gate.py: 34/34 passed
  - test_src_change_without_mypy_fails_strict: src/ 변경 시 mypy 누락 시 Gate 3 skipped 및 strict 모드 종료 코드 1 강제 확인.
  - test_gate6_multi_report_union_diff_success_and_failure: 다중 보고서 합집합 일치 시 Gate 6 PASS, 단일 보고서 누락 시 changed_files 불일치 FAIL 확인.
- tests/test_summarize_worker_done.py: 21/21 passed
  - test_summarize_worker_reports_multi_union_and_failure: 다중 보고서 합집합 집계, 위반 누적, CLI 다중 --report 실행 확인.
- tests/test_orca_taskctl.py: 229/229 passed
  - test_intent_verification_commands_are_honored: Intent 선언 보존 및 src/ 하위 mypy 자동 부착 확인.
  - test_intent_shared_resources_and_mypy_expand: Intent 선언 shared_resources 및 verification_commands의 Capsule 보존 확인.
- 종합 단위 테스트 실행: 284 passed in 7.30s.

### 3.2 실측 검증
- uv run mypy src: 0 issues found (93 source files passed).
- python3 scripts/validate_agent_rules.py: 20/20 PASS.

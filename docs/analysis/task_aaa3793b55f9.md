# Task aaa3793b55f9 결과 보고서: 워커 터미널 준비 절차 통합 및 안전 가드 고도화

> **Task ID**: `task_aaa3793b55f9`
> **작성일**: 2026-08-30
> **작업자**: Gemini 3.7 Flash (Antigravity Worker)
> **대상 모듈**: `scripts/orca_taskctl.py`, `tests/test_orca_taskctl.py`, `docs/ops/agent_worker_launch_reference.md`

---

## 1. 개요 및 목적

본 작업은 워커 기동 후 준비 절차(메타데이터 기록, 신뢰 확인 대화창 승인, 권한 자동 승인 감시기 부착, 파일 편집 승인 모드 전환)를 런처 경로와 직접 Dispatch 경로가 공통으로 사용하는 단일 상태 기계(`prepare_worker_terminal`)로 통합하고, CLI 종류 판정을 화면 텍스트가 아닌 기동 시점 메타데이터 우선 방식으로 전환하며, 실증된 결함 두 건(accept-edits 재전송 시 Plan 모드 순환, Antigravity `--inject` 실패 시 preamble 대체 투입)을 해결하는 것을 목적으로 합니다.

---

## 2. 주요 변경 사항

### 2.1 워커 메타데이터 레지스트리 구축 및 우선 판정
- `/tmp/orca_auto_approve/{terminal}.meta.json` (또는 임시 디렉터리)에 CLI 종류(`cli_type`), 모델(`model`), 런처(`launcher`), 갱신 시각을 기록·조회·삭제하는 함수 구현 (`get_worker_meta_path`, `read_worker_meta`, `write_worker_meta`, `remove_worker_meta`).
- `classify_file_edit_auto_approve_support`에서 메타데이터를 1차 기준으로 삼고, 화면 문자열과 불일치할 경우 경고를 출력하되 메타데이터를 우선 적용.
- `cmd_finalize` 호출 시 감시기 종료와 함께 해당 터미널 메타데이터 정리.

### 2.2 Antigravity 3단계 모드 순환 안전 가드 구현
- `detect_antigravity_mode`를 추가하여 Antigravity 상태줄의 `accept-edits`, `plan`, `normal` 모드를 정밀 감지.
- `enable_file_edit_auto_approve`:
  - 이미 `accept-edits` 모드인 경우 키 전송을 일체 생략하고 성공 반환 (불필요한 Plan 모드 전락 방지).
  - `plan` 모드로 빠진 경우 `shift+tab`을 순환 전송하여 `accept-edits`로 안전하게 복구.
  - 최대 3회 시도 상한(`max_attempts`)을 두어 무한 순환 방지.
  - `--enable-file-edit-auto-approve` 옵션 지정 시 CLI 미식별 상태에서도 모드 확보 시도 허용(모드 선확인 및 상한 준수).

### 2.3 통합 준비 상태 기계 및 CLI 서브커맨드
- `prepare_worker_terminal`: 메타데이터 기록 -> 신뢰 대화창 승인 -> 권한 감시기 부착 -> 파일 편집 승인 모드 안전 확보를 순차적으로 실행하고 결과를 딕셔너리로 반환.
- `orca_taskctl.py prepare-worker` 서브커맨드를 추가하여 수동 또는 런처 환경에서 동일 상태 기계 호출 지원.

### 2.4 Antigravity 지시 투입 fallback 경로 (`dispatch_with_fallback`)
- `orca orchestration dispatch --inject`가 Antigravity 터미널에서 `agent_prompt_blocked` 오류로 실패할 경우, `--return-preamble`로 preamble 지시문을 추출하여 `terminal send`로 직접 주입.
- 입력 프롬프트 캐럿 정체 시 추가 Enter 전송 및 사후 도달 검증(`verify_instruction_delivered`) 실행.
- 도달 미확인 시 종료 코드 3 반환으로 무결성 보장.

---

## 3. 검증 결과

### 3.1 회귀 및 신규 테스트 결과
`tests/test_orca_taskctl.py` 내 기존 150개 테스트 및 신규 회귀 테스트 9개(총 159개) 전량 통과:
- `test_enable_file_edit_already_accept_edits_no_key_sent`: 이미 accept-edits 시 키 미전송 검증 통과.
- `test_enable_file_edit_plan_mode_restores_to_accept_edits`: plan 모드에서 accept-edits 안전 복구 검증 통과.
- `test_enable_file_edit_max_attempts_no_infinite_loop`: 최대 시도 상한 후 중단 검증 통과.
- `test_classify_uses_recorded_meta_over_screen`: 메타데이터 우선 적용 및 경고 출력 검증 통과.
- `test_classify_falls_back_to_screen_when_no_record`: 메타데이터 부재 시 화면 텍스트 정상 fallback 검증 통과.
- `test_dispatch_fallback_to_preamble_on_inject_blocked`: inject 차단 시 return-preamble 대체 투입 검증 통과.
- `test_dispatch_fallback_fails_if_delivery_unverified`: 대체 투입 후 도달 미확인 시 실패 반환 검증 통과.
- `test_prepare_worker_terminal_unified`: 통합 준비 상태 기계 순차 실행 검증 통과.
- `test_cmd_prepare_worker_cli`: prepare-worker CLI 서브커맨드 동작 검증 통과.

### 3.2 전체 검증 도구 실행 결과
- `uv run pytest tests/test_orca_taskctl.py -q`: 159 passed.
- `uv run pytest tests/ -q -m 'not data_assets'`: 전량 통과.
- `uv run ruff check src/ scripts/ tests/`: 통과.
- `python3 scripts/validate_agent_rules.py --quiet`: 통과.

---

## 4. 변경 파일 목록

| 파일 경로 | 변경 내용 요약 |
| --- | --- |
| `scripts/orca_taskctl.py` | 메타데이터 관리, Antigravity 3단계 모드 감지, safe mode cycling, `prepare_worker_terminal`, `dispatch_with_fallback`, `prepare-worker` 서브커맨드 추가 |
| `tests/test_orca_taskctl.py` | 모드 순환 가드, 메타데이터 우선 판정, fallback 지시 투입, 통합 준비 상태 기계 테스트 추가 (총 159건 통과) |
| `docs/ops/agent_worker_launch_reference.md` | 통합 준비 절차, Antigravity 3단계 순환 특성, 메타데이터 레지스트리, preamble 대체 투입 매뉴얼 갱신 |
| `docs/analysis/task_aaa3793b55f9.md` | Task 수행 결과 보고서 작성 |

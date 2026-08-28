# Task task_dda88e2e6fe3 분석 및 구현 보고서

> **작성일**: 2026-08-28
> **작업자**: Orca Worker (Builder)
> **Task ID**: task_dda88e2e6fe3
> **Dispatch ID**: ctx_b411bfdc05e1
> **Run ID**: run_43d9937ac156

---

## 1. 작업 개요

### 1.1 배경 및 문제 정의
- 2026-08-28 운영 세션에서 Antigravity 워커 3대가 `Accept this file edit?` 파일 편집 승인 대화창에서 대기하며 멈췄으나, 기존 `scripts/orca_worker_watch.py` 감시 도구는 이를 `[진행]`으로 표시했고 `scripts/orca_auto_approve.py` 도구 역시 해당 대화창 신호를 탐지하지 못했습니다.
- 코디네이터가 워커의 정체를 사전에 발견하지 못하고 사용자가 먼저 발견하는 경우 코디네이터 실패로 간주되는 운영 규칙(`AGENTS.md` 4장)이 존재하므로, 감시 도구의 탐지 신뢰성 확보가 시급한 과제였습니다.

### 1.2 핵심 목표
1. **단일 진실 원천 상수 정의**: Antigravity 승인 대화창 신호(`Accept this file edit?`, `Allow creation of this file?`)를 단일 상수로 정의하고 대소문자 및 연속 공백·줄바꿈 변형에 견디도록 텍스트 정규화 비교 함수 구현.
2. **워커 감시 차단 탐지 및 종료 코드**: `scripts/orca_worker_watch.py`가 파일 편집/생성 승인 대화창을 탐지하여 `[차단]` 상태로 분류하고, 해제 조치 방법(`shift+tab`/`ESC [ Z`)을 출력하며 프로세스 종료 코드 `1`을 반환하도록 개선.
3. **자동 승인 도구 보류(hold) 연계**: `scripts/orca_auto_approve.py`가 동일 상수를 참조하여 파일 편집/생성 승인 대화창 상태를 인지하되, 자동 입력 전송을 하지 않고 `보류(hold)`로 안전하게 분류.
4. **터미널 직접 확인 권고 안내**: 감시 신호와 실제 원인이 다를 수 있는 가능성(네트워크 지연, 비정상 턴 종료 등)을 감안하여 차단 보고 시 터미널 화면 직접 확인 권고 문구 출력.
5. **회귀 테스트 및 운영 문서화**: 신규 탐지, 종료 코드, 보류 판정 및 정상 진행 유지에 대한 단위 테스트 100% 통과 및 플레이북 문서 갱신.

---

## 2. 주요 변경 사항

### 2.1 scripts/orca_worker_watch.py
1. **단일 상수 및 정규화 헬퍼 정의**:
   - `FILE_EDIT_DIALOG_SIGNALS`: `("Accept this file edit?", "Allow creation of this file?")` 튜플 상수 정의.
   - `normalize_text(text: str)`: 소문자 변환 및 연속 공백/줄바꿈을 단일 공백으로 정규화하여 프롬프트 포맷 변형에 안정적으로 대응.
2. **BLOCK_SIGNALS 확장**:
   - `Accept this file edit?` (사유: Antigravity 파일 편집 승인 대화창, 조치: 화면을 읽고 승인 여부를 판단. shift+tab(ESC [ Z)으로 auto-approve 전환 가능)
   - `Allow creation of this file?` (사유: Antigravity 파일 생성 승인 대화창, 조치: 화면을 읽고 승인 여부를 판단. shift+tab(ESC [ Z)으로 auto-approve 전환 가능)
3. **detect_block 개선**:
   - `normalize_text`를 적용하여 원본 터미널 출력의 대소문자/공백 변형에도 정확하게 신호를 탐지.
4. **직접 확인 권고 문구 반영**:
   - 차단 상태 탐지 시 `state.notes`에 `"감시 신호와 실제 원인이 다를 수 있으니(네트워크 오류로 인한 턴 종료 등) 터미널을 직접 확인하십시오"` 추가.

### 2.2 scripts/orca_auto_approve.py
1. **상수 및 정규화 함수 재사용**:
   - `scripts.orca_worker_watch`로부터 `FILE_EDIT_DIALOG_SIGNALS`, `normalize_text`를 import.
2. **classify_command 보류(hold) 로직 추가**:
   - 명령어가 `FILE_EDIT_DIALOG_SIGNALS`와 일치하거나 포함되는 경우 `("hold", f"파일 편집/생성 승인은 수동 판단 필요 ({sig})")`를 반환하여 자동 승인을 차단하고 보류 처리.
3. **pending_command 대화창 인식 확장**:
   - 화면 내에 `FILE_EDIT_DIALOG_SIGNALS` 신호가 존재하는 경우 해당 신호 문자열을 즉시 추출하여 `poll_loop`에서 보류 판정 로그를 남기도록 개선.

### 2.3 tests/
1. **tests/test_orca_worker_watch.py**:
   - `test_detect_block_finds_known_signals`: 신규 문구 및 대소문자/줄바꿈 변형 케이스 파라미터 테스트 추가.
   - `test_file_edit_signals_have_shift_tab_fix`: 모든 파일 편집 신호에 `shift+tab` 조치 방법이 포함되어 있는지 검증.
   - `test_main_exit_code_blocked_returns_1`: 차단 발생 시 `main()` 종료 코드가 `1`임을 검증.
   - `test_main_exit_code_clean_returns_0`: 정상 상태 시 `main()` 종료 코드가 `0`임을 검증.
   - `test_collect_adds_advice_note_on_blocked`: 차단 탐지 시 터미널 직접 확인 권고 note가 추가되는지 검증.
2. **tests/test_orca_auto_approve.py**:
   - `TestClassifyCommandHold`: 신규 파일 편집/생성 승인 문구에 대해 `hold`가 반환되는지 검증.
   - `test_pending_command_file_edit_dialog`: 화면에서 파일 편집 대화창 문구가 정상 추출되는지 검증.
   - `test_poll_loop_holds_file_edit_dialog`: `poll_loop` 실행 중 파일 편집 대화창을 만났을 때 입력을 전송하지 않고 `[보류]` 로그를 출력하는지 검증.

### 2.4 docs/ops/orca_orchestration_playbook.md
- `6.6 워커 차단 신호 감시 및 대화창 해제 절차` 절을 신설하여 탐지 신호, 대상 대화창, 해제 조치 방법, 자동 승인 정책 및 터미널 직접 확인 주의사항을 표로 정리.

---

## 3. 검증 결과

### 3.1 테스트 수행 결과
- **단위 테스트 (`tests/test_orca_auto_approve.py`, `tests/test_orca_worker_watch.py`)**: 140 passed (100% 통과).
- **전체 테스트 스위트 (`uv run pytest tests/ -q -m 'not data_assets'`)**: 2384 passed, 6 skipped, 3 deselected, 219 warnings (100% 통과).
- **규칙 정합성 검증 (`python3 scripts/validate_agent_rules.py --quiet`)**: 12/12 passed (100% 통과).

---

## 4. 리뷰 체크리스트

| ID | 검토 항목 | 기대 결과 | 실측 결과 | 판정 |
|---|---|---|---|:---:|
| detect_dialog | 신규 Antigravity 승인 문구가 차단으로 탐지되는가 | `Accept this file edit?`, `Allow creation of this file?` 탐지 | 정상 탐지 및 사유/조치 반환 | **PASS** |
| exit_code | 차단 탐지 시 종료 코드 1 로 끝나는가 | 차단 워커 존재 시 종료 코드 1 반환 | `exit_code == 1` 확인 | **PASS** |
| not_auto_approved | 신규 문구가 자동 승인되지 않고 보류인가 | auto_approve 시 입력 미전송 및 hold 판정 | `verdict == "hold"`, `send()` 미호출 | **PASS** |
| no_regression | 기존 auto_approve 테스트가 전부 통과하는가 | 화이트리스트 및 위험 명령 판정 불변 | 140/140 단위 테스트 통과 | **PASS** |
| advice_notice | 직접 확인 권고가 출력되는가 | 차단 시 터미널 확인 권고 안내 | `notes` 및 차단 보고에 권고 포함 | **PASS** |

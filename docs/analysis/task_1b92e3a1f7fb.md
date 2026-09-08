# Task 1b92e3a1f7fb: Claude 런처 permission-mode 허용값 acceptEdits 제한 분석 및 검증 보고서

> **작성일**: 2026-09-08
> **작업자**: Orca Worker (Role: builder)
> **태스크 ID**: `task_1b92e3a1f7fb`
> **관련 문서**: `scripts/orca_claude_launch.py`, `tests/test_orca_claude_launch.py`

---

## 1. 작업 배경 및 목적

선행 Task에서 Claude Code 런처(`scripts/orca_claude_launch.py`)의 `--dangerously-skip-permissions` 플래그를 제거하고 `--permission-mode` 인자로 교체하였으나, 허용값에 제한을 두지 않고 임의 문자열(`type=str`)을 받도록 구현되어 있었습니다.

이로 인해 `bypassPermissions` 등의 임의 값을 넘길 경우 제거된 위험 플래그와 동일하게 모든 권한 검사를 우회할 수 있는 보안 구멍이 발생할 위험이 있었습니다.
교체의 본래 목적은 파일 편집만 자동 승인(`acceptEdits`)하고 셸 명령 실행 등 민감한 동작은 저장소의 자동 승인 감시기가 판정하도록 강제하는 것이므로, 허용값을 `acceptEdits` 단 하나로 엄격하게 제한해야 합니다.

---

## 2. 구현 내용 및 설계 결정

### 2.1 argparse choices 단계의 거부 적용
- `scripts/orca_claude_launch.py` 내 `parser.add_argument("--permission-mode", ...)` 정의에서 기존 `type=str`을 `choices=["acceptEdits"]`로 변경하였습니다.
- `default=None`을 유지하여 권한 모드를 명시하지 않은 일반 기동 시에는 Claude 명령 배열에 `--permission-mode`가 추가되지 않도록 유지하였습니다.
- 검증 위치 원칙: 값 검증을 명령 조립 함수(`build_command`) 내부가 아닌 CLI 파싱(`argparse`) 단계에서 수행하여, 잘못된 인자 전달 시 preamble 대기 루프에 진입하기 전에 즉시 종료 코드 2(SystemExit)로 중단되도록 하였습니다.
- 비침습 원칙 준수: 파서를 외부 함수로 분리하거나 별칭 상수를 추가하지 않고 기존 `main` 함수 내부의 `argparse` 정의만 수정하여 불필요한 API 표면 확장을 방지하였습니다.

### 2.2 회귀 테스트 추가
- `tests/test_orca_claude_launch.py`에 `test_claude_main_rejects_invalid_permission_mode` 테스트 함수를 추가하였습니다.
- `bypassPermissions`를 `--permission-mode` 인자로 전달하여 `main`을 직접 호출했을 때, `SystemExit` 예외 및 종료 코드 2가 발생하는지 단언 검증하였습니다.

---

## 3. 변경 파일 내역

| 파일 경로 | 변경 구분 | 주요 내용 |
| --- | :---: | --- |
| `scripts/orca_claude_launch.py` | 수정 | `--permission-mode` 인자의 허용값을 `choices=["acceptEdits"]`로 제한 |
| `tests/test_orca_claude_launch.py` | 수정 | 허용되지 않은 값(`bypassPermissions`) 전달 시 `SystemExit 2` 발생 단언 회귀 테스트 추가 |
| `docs/analysis/task_1b92e3a1f7fb.md` | 신규 | 분석 및 검증 결과 보고서 작성 |

---

## 4. 검증 결과

### 4.1 Claude 런처 테스트 스위트
- 명령: `uv run pytest tests/test_orca_claude_launch.py -q`
- 결과: **17 passed in 0.89s** (종료 코드 0)

### 4.2 전체 테스트 스위트 (격리 워크트리 제외 마커)
- 명령: `uv run pytest tests/ -q -m 'not data_assets'`
- 결과: **4053 passed, 41 skipped, 3 deselected in 161.98s (0:02:41)** (종료 코드 0)

### 4.3 에이전트 규칙 검증
- 명령: `python3 scripts/validate_agent_rules.py --quiet`
- 결과: **검증 통과: 20/20 건** (종료 코드 0)

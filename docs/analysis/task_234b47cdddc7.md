# 자동 승인 감시기 대상 터미널 종료 시 자기 종료 구현 분석 보고서

> **작성일**: 2026-09-08
> **과업 ID**: `task_234b47cdddc7`
> **대상 모듈**: `scripts/orca_auto_approve.py`, `tests/test_orca_auto_approve.py`
> **핵심 요약**: 닫힌 터미널에 대해 `orca terminal read`가 종료 코드 0과 `status: exited` 헤더를 반환하여 읽기 실패로 잡히지 않고 감시기가 영원히 돌던 결함을 해결했습니다. 화면 앞머리 메타데이터 헤더 영역에서만 `status: exited`를 판정하고 연속 관측 상한(기본 3회) 도달 시 대상을 제외하여 감시기가 유한 시간 내 스스로 종료하도록 구현했습니다.

---

## 1. 개요 및 배경

2026-09-07 세션 종료 점검 과정에서 이미 회수된 워커 터미널을 대상으로 하는 `scripts/orca_auto_approve.py` 프로세스가 17개 누적되어 있는 현상이 발견되었습니다.

사양상 연속 읽기 실패가 상한에 도달하면 감시 대상에서 제외되고 대상이 모두 소진되면 감시기가 자동 반환되어야 하나, 감시 프로세스가 살아남아 수동 정리가 필요한 상태가 되었습니다.

---

## 2. 결함 원인 분석

### 2.1 orca terminal read 동작 특성
- 핸들 자체가 무효한 경우: `orca terminal read`가 종료 코드 1과 stderr에 `terminal_handle_stale`을 반환하여 `read(h)`가 `None`을 반환합니다. 이 경로는 정상 작동합니다.
- 터미널이 종료(close)된 경우: `orca terminal read`는 종료 코드 0과 함께 터미널 메타데이터(`handle 줄`, `status: exited 줄`, `source: stream 줄`, `cursor 줄`) 및 종료 전 버퍼 화면을 반환합니다.

### 2.2 기존 poll_loop 의 판정 한계
- `scripts/orca_auto_approve.py`의 `read(h)`는 종료된 터미널에 대해서도 문자열을 정상 반환합니다.
- 기존 `poll_loop`은 `screen is None`일 때만 `fail_counts`를 증가시켰으므로, 종료된 터미널에 대해 실패 계수가 전혀 올라가지 않아 `MAX_CONSECUTIVE_READ_FAILURES`에 도달하지 못했습니다.
- 그 결과 `active` 목록에서 터미널이 제거되지 않아 `while active:` 루프가 영원히 지속되었습니다.

---

## 3. 해결 방안 및 설계

### 3.1 메타데이터 헤더 영역 전용 판정 (`is_terminal_exited`)
- **오탐 방지 불변조건**: 워커가 실행 과정에서 `status: exited`라는 텍스트를 출력하거나 diff/로그에 찍히더라도 감시가 조기 종료되면 안 됩니다.
- 따라서 화면 전체 텍스트 검색(`in screen`)을 엄격히 금지하고, 본문 앞머리의 메타데이터 블록(첫 빈 줄 이전 또는 비헤더 라인 이전, 최대 20줄)에서만 `key == "status"` 및 `val == "exited"` 여부를 판정합니다.

### 3.2 연속 관측 상한 (`MAX_CONSECUTIVE_EXIT_OBSERVATIONS`)
- 일시적인 읽기 지연이나 화면 전환 과도기로 인한 조기 종료를 방지하기 위해 1회 관측 즉시 제외하지 않고 연속 관측 상한을 둡니다.
- 모듈 상수로 `MAX_CONSECUTIVE_EXIT_OBSERVATIONS = 3`을 정의하고 `poll_loop`의 매개변수로 주입 가능하게 설계했습니다.
- 정상 화면이 관측되면 해당 터미널의 연속 종료 계수를 0으로 재설정합니다.

### 3.3 명시적 제외 로그 및 PID 자원 회수
- 연속 관측 상한 도달로 대상을 제외할 때 `[제외]` 한 줄 로그를 한국어로 출력합니다 (이모지 미사용).
- 모든 터미널이 제외되어 루프가 끝나면 `finally` 블록에서 감시 대상 터미널들의 PID 파일을 안전하게 삭제하고 프로세스가 종료됩니다.

---

## 4. 구현 세부 내역

### 4.1 `scripts/orca_auto_approve.py`
1. 상한 상수 추가:
   ```python
   MAX_CONSECUTIVE_EXIT_OBSERVATIONS = 3
   MAX_CONSECUTIVE_EXIT_FAILURES = MAX_CONSECUTIVE_EXIT_OBSERVATIONS
   ```
2. 헤더 판정 함수 추가:
   ```python
   def is_terminal_exited(screen: str) -> bool:
       if not isinstance(screen, str) or not screen.strip():
           return False
       lines = screen.lstrip("\r\n").splitlines()
       for line in lines[:20]:
           stripped = line.strip()
           if not stripped:
               break
           match = re.match(r"^([a-zA-Z0-9_-]+):\s*(.*)$", stripped)
           if not match:
               break
           key = match.group(1).lower()
           val = match.group(2).strip().lower()
           if key == "status" and (val == "exited" or val.startswith("exited")):
               return True
       return False
   ```
3. `poll_loop` 루프 갱신:
   - `max_exit_observations` 매개변수 추가
   - `screen` 읽기 후 `is_terminal_exited(screen)` 검사 및 연속 계수 관리
   - 상한 도달 시 `active.remove(h)` 및 한국어 로그 출력
   - 정상 화면 관측 시 `exit_counts[h] = 0` 초기화

### 4.2 `tests/test_orca_auto_approve.py`
- `TestTerminalExitedDetection`:
  - 표준 메타데이터 헤더(`status: exited`) 인식 검증
  - 정상 실행 중인 메타데이터(`status: running`) 미인식 검증
  - 화면 본문에 `status: exited`가 포함된 경우 오탐 방지 검증
  - 메타데이터 헤더 없이 본문 텍스트만 있는 경우 미인식 검증
  - 빈 문자열/공백/None 입력에 대한 방어 로직 검증
- `TestPollLoopExitedSelfExit`:
  - 닫힌 터미널 관측 시 연속 상한 도달 후 유한 시간 내 루프 반환 검증
  - 단일 관측 시 조기 종료되지 않고 정상 화면 시 카운트 초기화 검증
  - 정상 실행 화면 지속 시 루프가 스스로 종료되지 않고 유지됨 검증
  - 터미널 종료로 루프 반환 시 PID 파일 정리 검증

---

## 5. 검증 결과

| 검증 항목 | 실행 명령 | 결과 | 판정 |
| --- | --- | --- | :---: |
| 자동 승인 및 부착 단위 테스트 | `uv run pytest tests/test_orca_auto_approve.py tests/test_orca_auto_approve_attach.py -q` | 335 passed | 통과 |
| 프로젝트 전량 테스트 | `uv run pytest tests/ -q -m 'not data_assets'` | 3968 passed, 41 skipped, 3 deselected | 통과 |
| 에이전트 규칙 정합성 검증 | `python3 scripts/validate_agent_rules.py --quiet` | 20/20 통과 | 통과 |
| 안전 화이트리스트 불변성 | `git diff scripts/orca_auto_approve.py` | 승인 판정 및 화이트리스트 변경 없음 | 통과 |

---

## 6. 결론

닫힌 워커 터미널에 대해 자동 승인 감시기가 스스로 감시 대상에서 제외하고, 모든 대상이 종료되면 PID 파일을 정리하며 정상 종료되도록 보장했습니다. 이를 통해 세션 종료 후 백그라운드 유령 프로세스가 남는 문제를 원천 차단했습니다.

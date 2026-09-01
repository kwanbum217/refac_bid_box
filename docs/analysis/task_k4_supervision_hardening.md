# Task K4: 워커 감시 자동화 및 Fail-Closed 강화 보고서

> **작성일**: 2026-09-01
> **Task ID**: `task_7eeea5b15bb7` (Section K4 Rework / `task_ad2486bbb6bc`)
> **대상 브랜치**: `kwanbum217/orca-k4r-sup`
> **관련 문서**: `scripts/orca_taskctl.py`, `scripts/orca_worker_watch.py`, `docs/ops/agent_worker_launch_reference.md`, `.claude/skills/orca-section-coordination/SKILL.md`, `.agents/skills/orca-section-coordination/SKILL.md`

---

## 1. 개요 및 배경

2026-09-01 세션에서 코디네이터가 워커 상태를 수동 폴링으로만 확인하여 워커 중단을 뒤늦게 인지하는 문제가 발생하였으며, 유사 사례가 2026-08-26 및 2026-08-31 세션에서도 반복되었습니다. `scripts/orca_worker_watch.py`에 `--watch` 상시 감시 모드가 구비되어 있었으나 기동 절차에 자동 포함되지 않아 사람의 기억에 의존하는 취약점이 존재했습니다.

본 작업(Section K4)은 다음을 기계적으로 강제합니다:
1. `dispatch` 시 권한 자동 승인 감시기(`start_auto_approve`) 부착 실패 시 경고만 남기던 기존 동작을 **기본 fail-closed 거부(종료 코드 2)**로 강화합니다.
2. 의도적 우회는 명시 플래그(`--skip-auto-approve-check` / `--allow-no-auto-approve`)로만 허용하며 경고를 기록합니다.
3. 워커 기동 성공 경로에서 **상시 감시기(`scripts/orca_worker_watch.py --watch`)를 배경 프로세스로 자동 기동**하고, PID 레지스트리 기반으로 중복 기동을 방지하며 기존 프로세스를 재사용합니다.
4. 스킬 및 운영 문서에 상시 감시 자동 기동을 기동 절차의 **필수 강제 조항**으로 명세합니다.

---

## 2. 변경 내용 상세

### 2.1 Dispatch 승인 감시기 부착 Fail-Closed 강화 (`scripts/orca_taskctl.py`)

- `cmd_dispatch` 내 터미널 부착 경로에서 `prep["auto_approve_watcher"]["ok"]` 가 `False`인 경우:
  - `--skip-auto-approve-check` 미지정 시: stderr 에 에러 메시지를 출력하고, `--json` 모드 시 `{"error": "auto_approve_watcher_failed", ...}` 를 출력하며 **종료 코드 2로 즉시 거부**.
  - `--skip-auto-approve-check` 지정 시: stderr 에 우회 경고를 남기고 진행.
- CLI 인자 파서에 `--skip-auto-approve-check` / `--allow-no-auto-approve` 플래그 추가 (기본값 `False`).

### 2.2 상시 감시기 자동 기동 및 생명주기 관리 (`scripts/orca_taskctl.py`)

- `get_worker_watch_pid_path`, `get_worker_watch_log_path`: 저장소별 고유 해시 기반 PID/로그 경로 관리.
- `start_worker_watch(repo)`:
  - 기존 PID 가 유효하고 살아있으면(`watcher_alive`) 새 프로세스를 띄우지 않고 재사용.
  - 프로세스가 없거나 사망 상태이면 `subprocess.Popen([sys.executable, script, "--repo", repo, "--watch"], start_new_session=True)` 로 배경 기동 후 PID 파일 기록.
- `stop_worker_watch(repo)`: Task 정리 시 SIGTERM/SIGKILL 전달 및 PID 파일 안전 삭제.
- `cmd_dispatch` 워커 기동 성공 블록에서 `start_worker_watch` 자동 호출 및 결과 payload(`worker_watch`) 기록.

### 2.3 차단 신호 감지 및 해제 명령 출력 정밀화 (`scripts/orca_worker_watch.py`)

- `BLOCK_SIGNALS` 내 모든 승인 대기(`prompt`) 및 실패 정체(`failure`) 항목에 실행 가능한 정확한 조치 명령 구비 확인.
- 사람이 읽는 출력(`format_worker_state`) 및 기계 판독(`as_dict` -> JSON) 양쪽에 `blocked_reason`, `blocked_fix`, `blocked_kind` 필드가 일관되게 제공됨을 검증.

### 2.4 스킬 및 운영 문서 강제 조항 명세

- `.claude/skills/orca-section-coordination/SKILL.md`, `.agents/skills/orca-section-coordination/SKILL.md`, `.opencode/skills/orca-section-coordination/SKILL.md` (3.2.1절):
  - 상시 감시 자동 기동(`orca_worker_watch --watch`)이 워커 기동 절차의 필수 강제 조항임을 명세.
  - 권한 자동 승인 감시기 부착 실패 시 fail-closed 기본 거부 및 우회 플래그 규칙 반영.
  - 세 파일 미러 내용 완전 일치 유지.
- `docs/ops/agent_worker_launch_reference.md` (0.5절 및 0.5.1절):
  - 3개 층 구조(accept-edits, auto_approve, worker_watch) 명시.
  - 상시 감시기 자동 기동, 단일 인스턴스 보장, fail-closed dispatch 생명주기 표 갱신.

---

## 3. 기각한 대안

| 기각된 대안 | 기각 사유 |
| --- | --- |
| **감시기 부착 실패 시 경고만 남기고 계속 진행** | 워커가 첫 번째 셸 명령이나 파일 편집에서 정체되어 사람 개입이 발생하므로 fail-closed 원칙 위반. |
| **우회 플래그를 기본 활성화(`default=True`)** | 의도치 않은 무감시 기동을 방지하지 못하므로 명시적 opt-in 플래그(`--skip-auto-approve-check`)로만 제한. |
| **기동 시마다 감시기 프로세스를 무조건 새로 스폰** | 동일 저장소에 여러 워커가 순차 기동될 때 감시기 프로세스가 중복 누수되고 CPU/터미널 자원을 낭비하므로 PID 레지스트리 기반 단일 인스턴스 재사용 채택. |

---

## 4. 검증 결과

### 4.1 신규 및 회귀 단위 테스트 결과

- `tests/test_orca_taskctl.py`:
  - `test_cmd_dispatch_fails_closed_when_auto_approve_fails`: 통과 (종료 코드 2 거부 확인)
  - `test_cmd_dispatch_bypasses_auto_approve_failure_with_flag`: 통과 (우회 플래그 지정 시 경고와 함께 0 종료)
  - `test_start_worker_watch_lifecycle_and_deduplication`: 통과 (자동 기동 및 중복 방지 재사용 확인)
  - `test_stop_worker_watch_terminates_and_cleans_pid`: 통과 (시그널 종료 및 PID 정리 확인)
  - `test_cmd_dispatch_auto_starts_worker_watch_on_success`: 통과 (dispatch 성공 시 worker_watch 자동 시작 확인)
- `tests/test_orca_worker_watch.py`: 54/54 passed (100% 통과).

### 4.2 규칙 및 스킬 미러 정합성 검증

- `.claude/skills/orca-section-coordination/SKILL.md`, `.agents/skills/orca-section-coordination/SKILL.md`, `.opencode/skills/orca-section-coordination/SKILL.md` diff 0건 (완전 일치).
- 이모지 사용 0건, 데이터 스키마 무변경 100% 준수.

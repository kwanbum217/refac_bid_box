# Task task_007ee54eee22 분석 및 구현 보고서

> **작성일**: 2026-09-03
> **Task ID**: task_007ee54eee22
> **목적**: scripts/orca_taskctl.py dispatch 의 Antigravity agy 런처 경로 지원 추가

---

## 1. 개요 및 배경

Antigravity(agy) TUI는 orca terminal create --command "agy ..." 형태로 직접 기동할 경우 스플래시 화면에서 정체되는 문제가 반복되었습니다. 이를 해결하기 위해 정본 런처인 scripts/orca_agy_launch.py가 도입되었으며, 이 런처는 <워크트리>/.orca/preamble.txt 파일이 생성되기를 대기하다가 agy --mode accept-edits -i <preamble> 형태로 exec 합니다.

그러나 기존 scripts/orca_taskctl.py dispatch의 터미널 부착 경로는 --inject 방식과 실패 시 --return-preamble 후 terminal send 대체 경로만 지원하여, 파일을 기다리는 런처에 지시문이 도달하지 못했습니다. 이로 인해 코디네이터가 수동으로 게이트를 우회하고 지시문을 수동 파일로 작성하여 투입해야 했습니다.

본 작업은 scripts/orca_taskctl.py dispatch에 명시적 런처 경로(--launcher)를 추가하여, 제어 평면 게이트를 우회하지 않고 Antigravity 워커를 안전하게 기동할 수 있도록 구현했습니다.

---

## 2. 주요 변경 사항

### 2.1 scripts/orca_taskctl.py

1. **터미널 워크트리 식별 (resolve_terminal_worktree)**:
   - 터미널 메타데이터({terminal}.meta.json), orca terminal show, orca terminal list 순으로 워크트리 경로를 안전하게 확인.
   - 주 저장소 오염 방지를 위해 주 저장소(repo_root)와 동일한 경로일 경우 fail-closed(종료 코드 2)로 거부 (launcher_main_repo_write_forbidden).
   - 워크트리 미식별 시 fail-closed(종료 코드 2)로 거부 (launcher_worktree_unresolved).

2. **런처 기동 확인 (verify_launcher_pickup)**:
   - preamble.txt 파일 작성 후 런처가 실제로 이를 이어받아 에이전트를 기동했는지 터미널 출력을 통해 폴링 검증.
   - preamble 대기 중 상태가 해소되고 기동 선언(기동: agy 등) 또는 에이전트 상태(프롬프트 caret >, 신뢰 대화창, accept-edits 모드 등)를 확인.
   - 시한(기본 30초) 내에 이어받지 못하면 exit code 3으로 실패 처리하여 파일 작성만으로 성공으로 오판하는 사고를 방지.

3. **cmd_dispatch 런처 분기 구현**:
   - CLI 인자 --launcher [SCRIPT] 추가 (명시적 선택 방식, 화면 추측 자동 판별 배제).
   - --launcher 사용 시 --terminal 필수 검증 (launcher_terminal_missing).
   - 모든 선행 게이트(정본 스킬 영수증, 동시 쓰기 상한, 잔류 세션 검사, 권한 자동 승인 감시기 부착)를 동일하게 강제.
   - dispatch_worker(..., return_preamble=True)로 지시문을 수신하여 <워크트리>/.orca/preamble.txt에 기록 후 verify_launcher_pickup 수행.
   - 워커 상시 감시기(start_worker_watch) 및 신뢰도 추적(_start_reliability_tracking) 정상 연계.

### 2.2 tests/test_orca_taskctl.py

- test_resolve_terminal_worktree_from_meta: 메타데이터로부터 워크트리 조회 검증.
- test_resolve_terminal_worktree_from_terminal_show: terminal show JSON으로부터 워크트리 조회 검증.
- test_resolve_terminal_worktree_from_terminal_list: terminal list JSON으로부터 워크트리 조회 검증.
- test_resolve_terminal_worktree_returns_none_when_unresolved: 미식별 시 None 반환 검증.
- test_verify_launcher_pickup_detects_started_marker: 기동 마커 감지 검증.
- test_verify_launcher_pickup_detects_agent_prompt: 에이전트 프롬프트 감지 검증.
- test_verify_launcher_pickup_detects_accept_edits_mode: 모드 표지 감지 검증.
- test_verify_launcher_pickup_times_out_when_still_waiting: 대기 지속 시 타임아웃 검증.
- test_cmd_dispatch_launcher_writes_preamble_to_worktree: preamble 작성 및 기동 확인 통합 검증 (주 저장소 미작성 검증 포함).
- test_cmd_dispatch_launcher_rejects_main_repo_write: 주 저장소 쓰기 시도 시 fail-closed 거부 검증.
- test_cmd_dispatch_launcher_fails_when_worktree_unresolved: 워크트리 미식별 시 거부 검증.
- test_cmd_dispatch_launcher_fails_when_pickup_times_out: 기동 확인 시한 초과 시 실패 처리 검증.
- test_cmd_dispatch_launcher_requires_terminal: terminal 누락 시 거부 검증.

### 2.3 docs/ops/agent_worker_launch_reference.md

- 제2장 비 Claude·Codex CLI 를 워커로 붙이는 절차 갱신:
  - scripts/orca_agy_launch.py를 터미널 명령으로 사용하는 방법과 scripts/orca_taskctl.py dispatch --terminal <handle> --launcher를 통한 Task 투입 절차를 정본으로 명시.

---

## 3. 검증 결과

- uv run pytest tests/test_orca_taskctl.py -q: 205 passed (전량 통과)
- uv run pytest tests/test_orca_agy_launch.py -q: 21 passed (전량 통과)
- python3 scripts/validate_agent_rules.py --quiet: 19/19 통과

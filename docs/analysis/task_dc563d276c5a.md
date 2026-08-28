# task_dc563d276c5a: orca_worker_watch 터미널 선택 개선

> **작성일**: 2026-08-28
> **Task**: terminal_map 이 동일 워크트리에 여러 터미널이 있을 때 워커 터미널을 고르도록 수정

## 문제

`terminal_map()` 이 `worktreePath` 를 키로 단일 항목만 유지해, 같은 워크트리에 워커 터미널과 빈 셸 터미널이 함께 있으면 `orca terminal list` 순서에 따라 잘못된 터미널이 선택되었다.

## 변경

1. `terminal_map()` 반환형을 `dict[str, list[dict]]` 로 변경해 후보 목록을 유지한다.
2. `is_shell_default_title()` / `select_worker_terminal()` 순수 함수로 선택 규칙을 분리한다.
   - `Terminal` 로 시작하는 제목은 셸 기본 제목으로 후순위.
   - 후보가 하나면 그대로 사용.
   - 모두 셸 기본 제목이면 첫 항목 + note.
   - 후보가 둘 이상이면 선택 핸들을 note 에 기록.
3. 사람이 읽는 출력과 `--json` 모두 차단 여부와 무관하게 `terminal` 을 표시한다.

## 검증

- `uv run pytest tests/test_orca_worker_watch.py -q`
- 순서 뒤집기, None title, 단일 후보, 다중 후보 note 회귀 테스트 추가.

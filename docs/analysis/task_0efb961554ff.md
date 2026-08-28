# task_0efb961554ff — Antigravity 런처 도입

## 문제

`orca terminal create --command "agy --model <id>"` 로 Antigravity TUI 를 띄우면
스플래시에서 멈추는 사례가 반복됐다. 지시문을 런치 인자(`agy -i "<지시문>"`)로 넘기면
안정적이지만, 지시문(preamble)은 Dispatch 이후에야 얻을 수 있어 순서가 맞지 않는다.
그 결과 코디네이터가 매번 임시 셸 스크립트를 만들어 썼고, 그 스크립트는 저장소에
남지 않아 다음 세션에서 재현되지 않았다.

Kimi 워커는 같은 문제를 `scripts/orca_kimi_launch.py` 로 이미 풀었다. 이 Task 는
Antigravity 용으로 같은 형태의 런처를 추가한다.

## 변경 요약

- `scripts/orca_agy_launch.py` 신규 추가
- `tests/test_orca_agy_launch.py` 신규 추가 (9 케이스)
- 본 문서 신규 추가

## 설계 선택

### 1. 명령 조립을 순수 함수로 분리

`build_command(model, prompt) -> list[str]` 로 명령 배열을 만들어 테스트가 exec
없이 형태를 검증할 수 있게 했다. Kimi 런처의 `build_command` 와 같은 형태.

### 2. preamble 대기 정책은 Kimi 런처와 동일

`wait_for_preamble(path, timeout_sec, poll_sec)` 가 다음 조건을 모두 만족할 때만
내용을 돌려준다.

- 파일이 존재한다.
- 내용을 읽은 뒤 `strip()` 결과가 비어 있지 않다.

하나라도 어긋나면 1초 간격으로 재시도하고, `timeout_sec` 안에 통과 못 하면
`TimeoutError` 를 던진다. 호출자(`main`)는 이를 잡아 stderr 에 메시지를 남기고
종료 코드 2 로 끝낸다. 빈 지시문으로 워커가 기동하는 경로를 원천 차단한다.

### 3. 지시문은 `-i` 인자로 전달

Antigravity 스플래시 멈춤 회피는 지시문을 런치 인자로 줄 때만 안정적이므로
`agy --model <id> -i "<지시문>"` 형태를 사용한다. 모델 ID 자체에 추론 수준이
포함되므로 별도 effort 인자는 두지 않는다.

### 4. 환경변수 프로필 미사용

Kimi 의 `KIMI_CODE_HOME` 같은 프로필 환경변수가 Antigravity 에는 없으므로 `--home`
인자는 두지 않는다. Kimi 런처의 `--home` 자리에 대응하는 인자가 사라진 것 외에는
인자 구성이 같다 (`--model` 필수, `--preamble`, `--timeout-sec`, `--no-commit-notice`).

### 5. 커밋 고지문 기본 활성화, 끄기 가능

기본적으로 `COMMIT_NOTICE` 를 preamble 뒤에 덧붙인다. 문구는 Kimi 런처와 같은
취지(변경 파일 스테이징, `git add -A` 금지, `git log --oneline main..HEAD` 확인)로
쓰되 그대로 복사하지 않고 이 런처의 책임(Antigravity 워커 기동)에 맞게 다듬었다.
`--no-commit-notice` 로 끌 수 있다.

## 테스트

`tests/test_orca_agy_launch.py` 9 케이스, `uv run pytest` 기준 모두 통과.

- `test_wait_returns_content_once_written` — 파일이 늦게 채워지면 그 내용을 받는다
- `test_empty_file_is_not_accepted` — 공백뿐인 파일은 지시문으로 쓰지 않는다
- `test_missing_file_times_out` — 파일 부재는 TimeoutError
- `test_build_command_passes_prompt_as_agy_argument` — 명령 배열 형태 고정
- `test_build_command_supports_different_model_ids` — 임의 모델 ID 도 그대로
- `test_commit_notice_mentions_commit_requirement` — 고지문 핵심 문구 포함
- `test_commit_notice_is_appended_when_enabled` — 기본값에서는 preamble 뒤에 붙음
- `test_commit_notice_omitted_when_disabled` — `--no-commit-notice` 로 빠짐
- `test_main_returns_nonzero_when_preamble_times_out` — 시간 초과는 0 아닌 코드

실제 sleep 으로 시간을 쓰지 않으며, `os.execvpe` 는 모킹한다. agy 프로세스는
실행되지 않는다.

## 사용 절차

```bash
# 1. 터미널을 런처를 명령으로 지정해 먼저 만든다
orca terminal create --worktree path:<워크트리> --title "<섹션명>" \
  --command "uv run python scripts/orca_agy_launch.py --model gemini-3.7-flash-medium"

# 2. Dispatch 결과를 워크트리의 .orca/preamble.txt 로 쓴다
orca orchestration dispatch --task <task_id> --to <handle> --return-preamble --json
# → 결과의 preamble 을 <워크트리>/.orca/preamble.txt 로 저장

# 런처가 preamble 이 채워지는 걸 감지하고 agy --model <id> -i "<preamble>" 로 기동
```

## 검증

- `uv run pytest tests/test_orca_agy_launch.py -q` — 9 passed
- `uv run pytest tests/ -q -m 'not data_assets'` — 회귀 없음 확인
- `uv run ruff check src/ scripts/ tests/` — 통과
- `python3 scripts/validate_agent_rules.py --quiet` — 통과
- `scripts/orca_kimi_launch.py` 수정 없음 (읽기만)
- `git diff --name-only` 가 `scripts/orca_agy_launch.py`,
  `tests/test_orca_agy_launch.py`, `docs/analysis/task_0efb961554ff.md` 만 포함

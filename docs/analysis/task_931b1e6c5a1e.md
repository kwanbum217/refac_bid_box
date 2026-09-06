# task_931b1e6c5a1e 분석: worker_done Guard 전송 신원 자동 해소

> 작성일: 2026-09-06
> Task: task_931b1e6c5a1e / Run: run_e61d4eaa452e

## 문제

`scripts/orca_worker_done_guard.py` 의 `--send` 경로는 `--from` 과 `--dispatch-id` 가
`None` 이면 해당 플래그를 아예 붙이지 않고 전송했습니다. Orca 는 신원 없는
`worker_done` 을 조용히 거부하므로 Task 가 `dispatched` 로 남았습니다.

## 환경 근거 (실측)

워커 터미널에서 `env` 를 직접 확인했습니다.

- `ORCA_TERMINAL_HANDLE=term_ad96955b-7755-4339-94fb-76c3f9401c13` 이 설정되어 있습니다.
- `dispatch` / `DISPATCH` 를 이름에 포함한 환경변수는 존재하지 않습니다.
  (`ORCA_*` 변수 중 dispatch 대응 없음)

따라서 아래와 같이 결정했습니다.

- `--from` 미지정 시 `ORCA_TERMINAL_HANDLE` 에서 해소합니다.
- `--dispatch-id` 는 대응 환경변수의 근거가 없으므로 이름을 지어내지 않고
  인자 필수로 둡니다. 없으면 전송하지 않고 오류로 종료합니다.

## 변경 내용

`scripts/orca_worker_done_guard.py`

- `FROM_HANDLE_ENV_VAR = "ORCA_TERMINAL_HANDLE"` 상수를 추가했습니다.
- `resolve_sender_identity()` 를 추가했습니다. 명시 인자가 환경변수보다
  우선하며, 해소 실패 시 `ValueError` 로 fail-closed 종료합니다.
- `main()` 의 `--send` 분기는 전송 전에 신원을 해소하고, 해소 실패 시
  `execute_orca_send` 를 호출하지 않고 종료 코드 2 로 끝냅니다.
- 자동 해소가 일어나면 어떤 값을 어디서 가져왔는지 `stdout` 에 출력하고,
  `--json` 모드에서는 `identity_resolution` 필드에 포함합니다.
- 보고 계약 검증 로직(`validate_worker_done` 및 하위 함수)은 변경하지 않았습니다.
- `--dispatch-capability` 전달 인자를 추가했습니다. `--send` 검증 후 실제
  전송이 `The Dispatch capability is missing` 으로 거부되는 것을 확인했고,
  워커 터미널 환경에 해당 토큰의 근거가 없으므로 환경변수 추측 없이
  플래그 전달만 지원합니다. 토큰 값은 Dispatch 서문에서 가져오며 파일에
  기록하지 않습니다.

`tests/test_orca_worker_done_guard.py`

- 환경변수 해소, 해소 실패 fail-closed, 명시값 우선,
  dispatch-id 인자 필수 4건을 추가했습니다.

## 검증

- `uv run pytest tests/test_orca_worker_done_guard.py -q` (12건 통과)
- `uv run pytest tests/ -q -m 'not data_assets'` (자산 테스트 제외 전량)
- `python3 scripts/validate_agent_rules.py --quiet`

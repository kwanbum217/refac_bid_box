# OpenCode 워커 지시 도달 확인 시정 (AF2)

> **작성일**: 2026-09-06
> **Task**: `task_a9888187277a` (Run `run_71d230fcb319`)
> **브랜치**: `kwanbum217/orca-af2-opencode-delivery`
> **범위**: `scripts/orca_taskctl.py`, `tests/test_orca_taskctl.py`, 본 문서

---

## 1. 문제

Muse Spark(OpenCode) 워커를 터미널 부착 경로로 Dispatch 하면 워커는
지시를 받고 일하는데도 사후 도달 확인이 `not_observed` 로 끝나 종료 코드 3
이 났습니다. 그 결과 코디네이터가 `--allow-unverified-delivery` 로 우회하는
관행이 생겼습니다 (Wave U/V/AE, 인수인계 5.1절 절차).

## 2. 원인

사후 확인(`verify_instruction_delivered`)이 터미널 뷰포트(`terminal_tail`)만
보았습니다. OpenCode TUI 에서 도달 표지가 안 보이는 경우는 세 가지입니다.

| # | 원인 | 근거 |
| --- | --- | --- |
| 1 | 긴 Capsule 고지문이 뷰포트에서 잘리고 전체 버퍼(`terminal_read`)에만 남음 | `terminal_tail` 은 `tail`/`preview` 만 반환하고 `terminal_read` 는 전체 버퍼를 반환함 |
| 2 | TUI 색상·커서 ANSI 코드가 표지 문자열 사이에 끼어 단순 포함 검사 빗나감 | OpenCode TUI 출력에 제어 코드가 섞임 |
| 3 | 긴 줄이 뷰포트 너비에 맞춰 잘리거나 개행되어 probe 중간이 끊김 | 고지문 본문이 길고 probe 가 본문 끝에 있음 |

Dispatch 전 `not_settled` 는 원인이 아닙니다. 주입은 큐에 남아 정상 도달하므로
사후 확인으로 도달이 보이면 통과가 맞습니다 (기존 계약 유지).

## 3. 시정

현재 터미널 부착 경로만 고쳤습니다. `dispatch --inject` 를 새로 기본 경로로
만들지 않았습니다.

| 위치 | 변경 |
| --- | --- |
| `instruction_observed` | ANSI 제거 후 비교, 실패 시 공백 제거 형태로 재비교 (줄바꿈 잘림 흡수) |
| `verify_instruction_delivered` | 매 회차 `terminal_tail` 확인 후 없으면 `terminal_read` 전체 버퍼까지 확인. 둘 중 하나라도 보이면 `delivered`, 둘 다 읽지 못하면 `unreadable`, 읽었는데 없으면 `not_observed` |
| `_deliver_capsule_notice` | 긴 고지문 전송 성공 뒤 짧은 `전달 확인 표지: <probe>` 확인문을 뒤이어 전송. 잘려도 짧은 표지는 화면에 남음. 실패해도 본문 전송은 성립하므로 경고만 남김 |

fail-closed 는 그대로입니다. 표지가 정말 안 보이면 우회 플래그 없이 종료
코드 3 이며, `--allow-unverified-delivery` 기본값(`False`)을 바꾸지
않았습니다.

## 4. 테스트

`tests/test_orca_taskctl.py` 에 추가한 회귀입니다.

| 테스트 | 고정 내용 |
| --- | --- |
| 기존 `test_cmd_dispatch_not_settled_alone_is_not_a_delivery_failure` | 유지. `not_settled` 단독은 전달 실패가 아님 |
| `test_instruction_observed_ignores_ansi_and_wrapping` | ANSI·줄바꿈에 낀 probe 도 도달로 인정 |
| `test_verify_instruction_delivered_falls_back_to_terminal_read` | tail 에 없고 read 에만 있어도 `delivered` |
| `test_verify_instruction_delivered_both_missing_is_not_observed` | 둘 다 없으면 `not_observed`, 둘 다 못 읽으면 `unreadable` |
| `test_cmd_dispatch_opencode_probe_visible_succeeds_without_bypass` | OpenCode 화면(tail 상태줄 + read probe)에 우회 없이 종료 코드 0 |
| `test_cmd_dispatch_probe_missing_still_fails_without_bypass` | probe 실종 시 우회 없이 3, 우회 시에만 0 |
| `test_deliver_capsule_notice_sends_short_probe_followup` | 고지문 뒤 짧은 probe 확인문 2회 전송 |
| 기존 `test_cmd_dispatch_sends_capsule_notice_on_attach` | 2회 전송 반영 (본문 포함 검사를 전체 전송으로 확장) |

## 5. 검증

- `uv run pytest tests/test_orca_taskctl.py -q`: 235 passed
- `python3 scripts/validate_agent_rules.py --quiet`: 20/20

## 6. 남은 우회 플래그 사용 조건

`--allow-unverified-delivery` 는 그대로 우회 플래그이며 기본 경로가
아닙니다. 다음 경우에만 씁니다.

- 터미널 자체를 읽지 못해 `unreadable` 인데 워커가 다른 경로로 지시를 받은
  사실을 사람이 직접 눈으로 확인한 경우
- `terminal_unreadable_after_dispatch` 또는 `delivery_probe_missing`
  (`--no-capsule-notice` 사용 시) 상태에서 코디네이터가 수동 전달을 마친 경우

도달이 화면에 보이면 플래그 없이 종료 코드 0 이어야 합니다. 도달이 보이는데
플래그가 필요하면 본 시정의 결함으로 보고하십시오.

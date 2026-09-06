# task_d9dca35fbf0f 분석 기록: SSR 인증 E2E 고정 대기 제거

> 작성일: 2026-09-06
> 대상: tests/e2e/test_ssr_auth.py, tests/e2e/conftest.py
> 결론: 고정 대기 1건과 부하 취약 대기 4건을 조건 대기로 전환하고 전량 부하에서 안정 통과를 확인했습니다.

---

## 1. 원인 진단

| 위치 | 기존 대기 | 결함 |
| --- | --- | --- |
| test_ssr_auth.py:184 (invalid_credentials) | `wait_for_timeout(1000)` | 고정 1초는 부하 시 대화창 출현을 놓치고 평시에는 낭비합니다. |
| test_ssr_auth.py:60, 86, 114, 137 | `wait_for_load_state("networkidle")` 4건 | 부하 시 500ms 유휴 구간이 없어 타임아웃 오탐을 냅니다. 검증 대상(URL 이동)과 무관한 대기입니다. |
| conftest.py page/authenticated_page | 기본 타임아웃 혼재 | 탐색 대기와 단언 대기 상한이 암묵적이라 부하 시 종료 시점이 들쭉날쭉해집니다. |

## 2. 변경 내용

- tests/e2e/test_ssr_auth.py
  - `wait_for_timeout(1000)` 제거 후 `wait_for_event("dialog", timeout=15_000)` 조건 대기로 교체했습니다. 대화창 없는 실패 응답도 허용하므로 타임아웃은 무시하고 URL 단언으로 이어집니다.
  - `networkidle` 4건을 제거했습니다. 회원가입과 로그인은 `expect().not_to_have_url(...)`으로 실제 이동을 기다리고, next 리다이렉트와 로그아웃은 `wait_for_url(정규식)`으로 타깃 URL 도착을 기다립니다.
  - `domcontentloaded` 1건이 남았습니다. 네트워크 유휴가 아니라 DOM 적재 완료를 기다리는 조건 대기이며, 회원가입 후 렌더 확인이 목적이므로 유지 사유가 명확합니다.
  - 기존 단언은 그대로이며 타임아웃 인자만 추가했습니다. 고정 대기를 더 긴 고정 대기로 바꾼 곳은 없습니다.
- tests/e2e/conftest.py
  - `page`와 `authenticated_page`에 `set_default_timeout(15_000)`과 `set_default_navigation_timeout(15_000)`을 명시했습니다.

## 3. 검증 결과

- `uv run pytest tests/e2e/test_ssr_auth.py -q`: 6 passed를 4회 반복 확인했습니다.
- `uv run pytest tests/e2e/ -q`: 27 passed, 5 skipped을 1회 확인했습니다.
- `uv run pytest tests/ -q -m 'not data_assets'`: 3742 passed, 32 skipped, 3 deselected를 1회 확인했습니다.
- `python3 scripts/validate_agent_rules.py --quiet`: 20/20 통과를 확인했습니다.
- pytest-xdist가 설치되어 있지 않고 사전 합의 없는 패키지 추가가 금지되므로 `-n` 병렬 대신 전량 스위트 동시 실행을 부하 조건으로 사용했습니다.

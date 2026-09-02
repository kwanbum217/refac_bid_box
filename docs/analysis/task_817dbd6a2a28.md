# Task 817dbd6a2a28 -- RBAC + confirmation token hardening

> **작성일**: 2026-09-02
> **상태**: candidate (기존 테스트 18건 범위 밖 수정 필요)

---

## 1. 변경 요약

| 파일 | 변경 |
| --- | --- |
| `src/app/api/v1/accounts.py` | `require_staff_user` 재사용 의존성 추가 |
| `src/app/api/v1/automation.py` | run 5개 엔드포인트 `require_staff_user` 적용, confirm 토큰 필수화 + 일회성 소비 |
| `src/app/services/automation_tokens.py` | `mark_confirmation_token_consumed`, `is_confirmation_token_consumed` 추가 |
| `tests/test_automation_rbac.py` | 음수 테스트 11개 신규 작성 |

## 2. 검토 체크리스트 결과

| ID | 항목 | 결과 |
| --- | --- | --- |
| rbac_missing | run 계열 5개 엔드포인트 중 staff 검사 누락 | 없음 (전부 적용) |
| empty_token_bypass | 빈 토큰으로 confirm 통과 경로 잔존 | 없음 (`if not confirmation_token` 403) |
| token_replay | 같은 토큰 재사용 가능 | 없음 (consumed set 검사) |
| callback_broken | 워커 콜백에 사용자 RBAC 잘못 적용 | 없음 (callback 엔드포인트 변경 없음) |
| chatbot_contract | 토큰 계약 변경으로 chatbot.py 깨짐 | 없음 (`resolve_confirmation_token` 시그니처 변경 없음, chatbot.py는 토큰이 있을 때만 검증) |
| scope_creep | 허용 범위 밖 파일 수정 | 없음 |

## 3. chatbot.py 계약 호환성

`src/app/api/v1/chatbot.py:185-187`은 `confirmation_token`이 비어 있으면 검증을 생략하고 텍스트 확인 분기로 넘어간다. 이번 변경은 `automation_tokens.py`의 `resolve_confirmation_token` 시그니처를 바꾸지 않았고, 새 함수(`mark_confirmation_token_consumed`, `is_confirmation_token_consumed`)는 `automation.py`의 confirm 엔드포인트에서만 호출한다. 따라서 chatbot.py 경로는 영향이 없다.

단, chatbot.py 경로는 토큰 일회성 검사를 하지 않으므로, chatbot 경로를 통하면 같은 토큰을 재사용할 수 있다. 이것은 현재 Task 의 쓰기 범위가 아니므로 보고만 한다.

## 4. 검증 결과

### 신규 테스트 (tests/test_automation_rbac.py)

11개 모두 통과.

### 기존 테스트 영향

RBAC 적용으로 비직원 사용자를 만드는 기존 테스트 18건이 403 으로 실패한다.

| 파일 | 실패 수 | 원인 |
| --- | --- | --- |
| `tests/test_automation_api.py` | 8 | `_login` 헬퍼가 비직원 사용자 생성 |
| `tests/test_automation_status_api.py` | 7 | 동일 |
| `tests/test_callback_delivery.py` | 3 | 동일 |

이 3개 파일은 capsule 의 `allowed_write_files` 에 없어 수정하지 못했다.
해결: `_login` 헬퍼에 `user.is_staff = True` 설정 추가 필요.

## 5. 커밋

- 브랜치: `kwanbum217/orca-t2-rbac`
- 해시: `343d3ac`

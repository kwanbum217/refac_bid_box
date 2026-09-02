# Task 817dbd6a2a28 -- RBAC + confirmation token hardening

> **작성일**: 2026-09-02
> **상태**: candidate

---

## 1. 변경 요약

| 파일 | 변경 |
| --- | --- |
| `src/app/api/v1/accounts.py` | `require_staff_user` 재사용 의존성 추가 |
| `src/app/api/v1/automation.py` | run 5개 엔드포인트 `require_staff_user` 적용, confirm 토큰 필수화 + 일회성 소비 |
| `src/app/services/automation_tokens.py` | `mark_confirmation_token_consumed`, `is_confirmation_token_consumed` 추가 |
| `tests/test_automation_rbac.py` | 음수 테스트 11개 신규 작성 |
| `tests/test_automation_api.py` | `_login` 헬퍼에 staff 승급 추가 (전체 9건) |
| `tests/test_automation_status_api.py` | `_login`에 선택적 `isolated_db` 추가; run 호출 7건만 staff, status/callback 6건은 비직원 유지 |
| `tests/test_callback_delivery.py` | `_login`에 선택적 `isolated_db` 추가; run 호출 3건만 staff, chatbot 1건은 비직원 유지 |

## 2. 검토 체크리스트 결과

| ID | 항목 | 결과 |
| --- | --- | --- |
| rbac_missing | run 계열 5개 엔드포인트 중 staff 검사 누락 | 없음 (전부 적용) |
| empty_token_bypass | 빈 토큰으로 confirm 통과 경로 잔존 | 없음 (`if not confirmation_token` 403) |
| token_replay | 같은 토큰 재사용 가능 | 없음 (consumed set 검사) |
| callback_broken | 워커 콜백에 사용자 RBAC 잘못 적용 | 없음 (callback 엔드포인트 변경 없음) |
| chatbot_contract | 토큰 계약 변경으로 chatbot.py 깨짐 | 없음 (`resolve_confirmation_token` 시그니처 변경 없음) |
| scope_creep | 허용 범위 밖 파일 수정 | 없음 |

## 3. chatbot.py 계약 호환성

`src/app/api/v1/chatbot.py:185-187`은 `confirmation_token`이 비어 있으면 검증을 생략하고 텍스트 확인 분기로 넘어간다. 이번 변경은 `automation_tokens.py`의 `resolve_confirmation_token` 시그니처를 바꾸지 않았고, 새 함수는 `automation.py`의 confirm 엔드포인트에서만 호출한다. chatbot.py 경로는 영향이 없다.

## 4. 검증 결과

### 전체 테스트: 3036 passed, 25 skipped, 0 failed

- `tests/test_automation_rbac.py`: 11개 모두 통과 (비직원 403, 빈 토큰 거부, 위조 토큰 거부, 다른 job 토큰 거부, 만료 토큰 거부, 토큰 재사용 거부, 콜백 경로 무변경)
- 기존 테스트 18건: `_login` 헬퍼에 staff 승급 추가 후 모두 통과
- `test_automation_status_api.py`의 status/callback 전용 테스트 6건은 비직원 사용자 유지
- `test_callback_delivery.py`의 chatbot 전용 테스트 1건은 비직원 사용자 유지

## 5. 커밋

- 브랜치: `kwanbum217/orca-t2-rbac`
- `343d3ac` feat: add RBAC staff check to automation run endpoints and enforce one-time confirmation tokens
- `bcb3651` docs: record RBAC task analysis and test impact report
- `a901a24` test: grant staff status to login helpers calling admin-only run endpoints

# 세션 TODO (2026-08-01 기준)

> **작성일**: 2026-08-01
> **상태**: Phase 0~6 완료 (86%), Phase 7 검증 잔존

---

## 즉시 진행 가능 (서버 없이)

1. ~~**ChatAutomationApiTests 이식**~~ — **완료**. 상세는 아래 "ChatAutomationApiTests 이식 결과" 참조.
2. **주간 재학습 스케줄 추가** — `src/tasks/retrain_task.py`에 Arq 크론 설정 또는 `run_mode_matrix`에 `retrain` 모드 추가
3. **Alembic 마이그레이션 도입** — 원본 19개 히스토리 보존. `alembic init` → `autogenerate` → 기존 스키마와 정합성 검증

## 서버 필요 (Ollama + Redis)

4. **성능 벤치마크** — `scripts/benchmark_latency.py` 작성. SSE 첫 토큰 P95 3초, 전체 P95 20초 목표 측정
5. **재학습 E2E 검증** — 데이터→학습→평가→배포 전 주기 실증
6. **크로스 플랫폼 검증** — Windows 환경에서 Docker + Makefile 실행 확인

---

## ChatAutomationApiTests 이식 결과

원본 클래스는 **28개**입니다 (`apps/chatbot/tests.py:784-1798`). **23개 이식 완료**, 5개는 Harness 제거로 대응 개념이 없어 제외했습니다.

| 이식본 파일 | 테스트 수 | 범위 |
| --- | ---: | --- |
| `tests/test_chatbot_integration.py` | 15 | 세션 전환, 자동화 요청, 텍스트 승인, 진행 상황, 챗봇 화면 |
| `tests/test_chatbot_prediction.py` | 6 | 투찰가 예측, 답변 모드 계약, 대화 상태 영속 |
| `tests/test_automation_status_api.py` | 7 | 콜백 인증, 상태 조회, 확인 실행 |

제외한 5개는 전부 Harness 고유 동작입니다.

| 원본 테스트 | 제외 사유 |
| --- | --- |
| `test_cancel_running_automation_request_aborts_harness_and_stops_polling_state` | Harness abort API 없음 |
| `test_chat_api_falls_back_to_polling_for_loopback_callback_base_url` | 루프백 콜백 폴백 개념 없음 |
| `test_confirm_reuses_recent_staging_success_without_new_run` | 스테이징 실행 재사용 로직 없음 |
| `test_confirm_ignores_stale_staging_success_and_executes_new_run` | 동일 |
| `test_confirm_reuses_recent_harness_summary_without_new_run` | 동일 |

### 이식 과정에서 복원한 누락 기능

테스트가 통과하지 않아 드러난 실제 이식 누락분입니다. 테스트를 고치지 않고 구현을 채웠습니다.

| 대상 | 누락 내용 |
| --- | --- |
| `src/app/api/v1/chatbot.py` | 텍스트 승인("승인 후 실행해줘")과 `confirmation_token` 처리 자체가 없었습니다 |
| `src/app/api/v1/chatbot.py` | 답변 모드가 `suggestions`/`advisory_signals` 를 전혀 싣지 않았습니다 |
| `src/app/schemas/chatbot.py` | 세션 전환 응답에 `last_query`/`history` 가 없어 `chat.html:1734` 의 대화 복원이 동작하지 않았습니다 |
| `src/app/services/conversation_state.py` | 사용자 고정 메모리(`user:{id}`)가 통째로 빠져 세션 간 필터가 이어지지 않았습니다 |
| `src/app/services/automation_orchestrator.py` | `_step_status_lines` 가 "Step 진행 상황" 머리글, 단계 순서, 요약 표기를 누락했습니다 |

### 작성 규칙

자동화 관련 테스트는 반드시 `/api/v1/chatbot/chat` 을 거쳐 작성합니다. 자동화 엔드포인트를 직접 호출하면 원본이 검증하려던 계획 수립 경로를 건너뛰고 `tests/test_automation_api.py` 와 중복됩니다.

---

## 참조

- 인수인계: `docs/handoff/2026-07-31_parity_restoration_handoff.md`
- 설계서 체크리스트: `docs/design/REFACTORING_DESIGN.md` Phase 7
- 프론트엔드 결정: `docs/design/FRONTEND_DECISION.md`
- 테스트 현황: 170 passed / 1 skipped (20개 파일)

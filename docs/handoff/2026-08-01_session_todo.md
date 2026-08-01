# 세션 TODO (2026-08-01 기준)

> **작성일**: 2026-08-01
> **상태**: Phase 0~6 완료 (86%), Phase 7 검증 잔존

---

## 즉시 진행 가능 (서버 없이)

1. **ChatAutomationApiTests 이식** — 원본 클래스는 16개가 아니라 **27개**입니다 (`apps/chatbot/tests.py:784-1798`). 7개 완료 (`test_chatbot_integration.py`).

   잔존 20개 분류:

   | 구분 | 개수 | 내용 |
   | --- | --- | --- |
   | 이식 가능 | 17 | 예측 mock(2), 진행상태(2), 완료(2), 확인 실행(5), 답변 모드 계약(4), 상태 조회(2) |
   | 개념 부재로 제외 | 3 | 콜백 폴백(1), Harness abort(1), Harness 요약 재사용(1) — Harness 제거로 대응 개념 없음 |

   세션 전환은 이식 불가가 아닙니다. `src/app/api/v1/chatbot.py:254-262` 이 메시지 없는 `session_key` POST 를 `mode="switch"` 로 처리하므로 원본과 동일하게 검증 가능하며, 이미 이식했습니다.

   결과 그래프(`test_chat_api_completed_result_graph_request_keeps_duration_chart`)도 이식 가능 항목에 포함됩니다. 소요 시간 차트는 Harness 전용이 아니라 자동화 실행 기록 기반입니다.

   **주의**: 자동화 관련 테스트는 반드시 `/api/v1/chatbot/chat` 을 거쳐 작성합니다. 자동화 엔드포인트를 직접 호출하면 원본이 검증하려던 계획 수립 경로를 건너뛰고 `tests/test_automation_api.py` 와 중복됩니다.
2. **주간 재학습 스케줄 추가** — `src/tasks/retrain_task.py`에 Arq 크론 설정 또는 `run_mode_matrix`에 `retrain` 모드 추가
3. **Alembic 마이그레이션 도입** — 원본 19개 히스토리 보존. `alembic init` → `autogenerate` → 기존 스키마와 정합성 검증

## 서버 필요 (Ollama + Redis)

4. **성능 벤치마크** — `scripts/benchmark_latency.py` 작성. SSE 첫 토큰 P95 3초, 전체 P95 20초 목표 측정
5. **재학습 E2E 검증** — 데이터→학습→평가→배포 전 주기 실증
6. **크로스 플랫폼 검증** — Windows 환경에서 Docker + Makefile 실행 확인

## 참조

- 인수인계: `docs/handoff/2026-07-31_parity_restoration_handoff.md`
- 설계서 체크리스트: `docs/design/REFACTORING_DESIGN.md` Phase 7
- 프론트엔드 결정: `docs/design/FRONTEND_DECISION.md`
- 테스트 현황: 149 passed / 1 skipped (18개 파일)

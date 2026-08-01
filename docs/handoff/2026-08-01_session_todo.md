# 세션 TODO (2026-08-01 기준)

> **작성일**: 2026-08-01
> **상태**: Phase 0~6 완료 (86%), Phase 7 검증 잔존

---

## 즉시 진행 가능 (서버 없이)

1. **ChatAutomationApiTests 16개 이식** — 3개 완료 (`test_chatbot_integration.py`). 잔존 13개 중 refac 구조상 이식 불가 4개: 세션 전환(2, 원본은 chat_api에 session_key POST이나 refac은 `/session/new`만 존재), 콜백 폴 백(1, Harness 제거), 결과 그래프(1). **이식 가능 9개**: 예측 mock(2), 진행상태(2), 완료(2), 취소(2), 확인 실행(2). 원본 `apps/chatbot/tests.py:909-1798` 참조.
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
- 테스트 현황: 142 passed / 1 skipped (18개 파일)

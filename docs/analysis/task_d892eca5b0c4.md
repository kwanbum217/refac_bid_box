# Task d892eca5b0c4 — Phase 3 SSR 챗봇 SSE 실시간 스트리밍 및 React SPA E2E 검증 분석 보고서

> **작성일**: 2026-09-03
> **Task ID**: `task_d892eca5b0c4`
> **상태**: 완료 (Completed)
> **단일 진실 원천(SSOT)**: 본 문서는 Phase 3 SSR 챗봇 SSE 실시간 스트리밍과 React SPA E2E 테스트 슈트 구축 및 검증 결과에 대한 분석 보고서입니다.

---

## 1. 개요 및 목적

본 과업은 `refac_bid_box`의 프론트엔드 실시간 인터랙션 및 SPA 화면에 대한 브라우저 E2E 테스트 체계를 구축하는 것을 목적으로 합니다.
기존 Phase 2에서 SSR 4대 핵심 화면(인증, 공고, 낙찰, 대시보드) 22개 시나리오를 검증한 데 이어, Phase 3에서는 **SSE(Server-Sent Events) 실시간 토큰 스트리밍의 점진적 DOM 반영**과 **React SPA(Vite + React 19) 3대 탭 전환 및 데이터 바인딩**을 브라우저 런타임에서 완벽히 검증하였습니다.

---

## 2. 주요 설계 및 검증 원칙

### 2.1 고정 대기(sleep) 절대 배제 및 조건 기반 대기
- 스트리밍 테스트에서 `time.sleep()` 또는 고정 시간 대기는 러너 환경에 따라 간헐적 실패(Flaky test)를 유발합니다.
- Playwright의 내장 조건 재시도(`expect(locator).to_be_visible()`, `to_contain_text()`, `wait_for_function`)만을 사용하여 네트워크 및 렌더링 타이밍에 안정적으로 동기화했습니다.

### 2.2 중간 토큰 누적 상태(Incremental Accumulation) 증명
- 최종 문자열 일치만 검증할 경우 단발 렌더링과 실시간 스트리밍을 구분할 수 없습니다.
- 스트림 개시 직후 첫 번째 토큰(`조달청`)의 즉시 노출 및 후속 토큰의 점진적 DOM 누적을 명시적으로 단언하여 실시간 스트리밍 파이프라인의 유효성을 증명했습니다.

### 2.3 외부 LLM 무의존성 및 격리 Mock 주입
- 실제 외부 Ollama나 Gemini 서비스에 의존하지 않도록 `tests/e2e/conftest.py`에 `_e2e_mock_rag_engine` autouse Fixture를 구현하여 비동기 토큰 스트림, 참조 문서(`docs`), 완료 이벤트(`done`) 및 시뮬레이션 예외 처리를 완벽히 에뮬레이트했습니다.

### 2.4 순수 Python 기반 React SPA 프록시 서빙 (`react_spa_url`)
- Vite 빌드 산출물(`frontend/dist`)을 Python `ThreadingHTTPServer` 기반 `_SPAProxyHandler`로 서빙하고 `/api/*` 요청을 백그라운드 Uvicorn 서버(`live_server_url`)로 투명하게 중계하여, 별도의 불안정한 외부 Node 프로세스 없이 견고한 E2E 환경을 구축했습니다.

---

## 3. 구현된 테스트 슈트 상세

### 3.1 SSR 챗봇 스트리밍 (`tests/e2e/test_ssr_chatbot_stream.py`) - 5개 시나리오
1. `test_ssr_chatbot_unauthenticated_redirect`: 비인증 사용자의 `/chatbot/` 접근 시 로그인 화면으로 303 리다이렉트 검증
2. `test_ssr_chatbot_page_access_authenticated`: 세션 쿠키 주입 후 메인 UI, 입력창(`#chat-input`), 전송 버튼(`#btn-send`) 정상 렌더링 검증
3. `test_ssr_chatbot_streaming_token_accumulation`: 질문 전송 후 사용자 버블 노출, 실시간 토큰(`조달청`) 누적 렌더링 및 최종 완성 문장 수신 검증
4. `test_ssr_chatbot_stream_error_handling`: 스트림 중 예외 발생 시 `STREAM_ERROR_MESSAGE` 안전 노출 및 UI 재사용성 검증
5. `test_ssr_chatbot_result_id_linkage`: `result_id` 파라미터 전달 시 낙찰 상세 분석 프롬프트 자동 발송 및 대화 버블 연계 검증

### 3.2 React SPA 3대 탭 (`tests/e2e/test_react_spa.py`) - 5개 시나리오
1. `test_react_spa_initial_dashboard_render`: 헬스체크 연동, 통계 메트릭 카드 4종, 공고 목록 테이블 렌더링 검증
2. `test_react_spa_category_filter_and_search`: 카테고리(용역/물품/전체) 필터 버튼 및 검색어 필터링 검증
3. `test_react_spa_bid_to_prediction_transition`: 공고 목록에서 '예측하기' 클릭 시 AI 시뮬레이터 탭 전환, 제원 자동 바인딩 및 예측 산출 검증
4. `test_react_spa_chatbot_sse_streaming_interaction`: 챗봇 탭 전환, 실시간 SSE 스트리밍 토큰 수신 및 최종 답변 렌더링 검증
5. `test_react_spa_chatbot_abort_interaction`: 스트리밍 진행 중 '중지' 버튼 클릭 시 AbortController 연동 및 안전 중단 검증

---

## 4. 검증 결과 요약

| 검증 항목 | 대상 파일 / 명령 | 결과 | 비고 |
| --- | --- | :---: | --- |
| **Phase 3 신규 E2E 테스트** | `uv run pytest tests/e2e/test_ssr_chatbot_stream.py tests/e2e/test_react_spa.py -v` | **10 passed** | 12.82초 완료 |
| **전체 E2E 테스트 슈트** | `uv run pytest tests/e2e/ -v` | **32 passed** | 전량 통과 |
| **전체 백엔드 테스트 슈트** | `uv run pytest tests/ -q -m 'not data_assets'` | **3344 passed**, 35 skipped, 3 deselected | 125.21초 완료 |
| **규칙 및 문서 정합성** | `python3 scripts/validate_agent_rules.py --quiet` | **19/19 passed** | 위반 0건 |

---

## 5. 결론 및 향후 계획

Phase 3 과업을 통해 SSR 챗봇 실시간 SSE 스트리밍과 React SPA 3대 탭 인터랙션이 Playwright 브라우저 E2E 환경에서 안정적으로 전량 검증되었습니다.
후속 Phase 4(CI 워크플로 통합 및 아티팩트 자동화) 착수를 위한 모든 선행 조건이 충족되었습니다.

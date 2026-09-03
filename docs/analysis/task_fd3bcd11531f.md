# SSR 핵심 화면 브라우저 E2E 시나리오 작성 및 검증 분석 보고서

> **작성일**: 2026-09-03
> **Task ID**: `task_fd3bcd11531f`
> **역할**: Builder
> **상태**: 완료 (Succeeded)
> **단일 진실 원천(SSOT)**: 본 문서는 SSR 핵심 화면 브라우저 E2E 테스트 슈트 구축 결과와 검증 내역을 기록한 분석 보고서입니다.

---

## 1. 과업 개요 및 목적

Wave J의 Phase 2a에서 구축된 임시 SQLite 격리 DB 및 `get_db` 의존성 오버라이드, 세션 쿠키(`bidbox_session`) 주입 픽스처를 기반으로, Jinja2 SSR 핵심 4대 영역(인증 플로우, 공고 목록·상세, 낙찰 목록·상세, 대시보드)에 대한 브라우저 E2E 시나리오를 작성하고 실제 Headless Chromium 환경에서 전량 검증을 수행하였습니다.

---

## 2. 주요 구현 및 시나리오 구성 (총 22건 통과)

### 2.1 인증 플로우 (`tests/e2e/test_ssr_auth.py` — 6개 시나리오)
1. `test_ssr_auth_signup_flow`: 회원가입 폼 필수 항목 및 약관 동의 제출 후 DB 사용자 생성 및 메인 이동 검증
2. `test_ssr_auth_login_success`: 정상 자격증명 제출 시 세션 발급 및 홈 이동, 로그아웃 버튼 노출 및 닉네임 바인딩 검증
3. `test_ssr_auth_login_with_next_redirect`: `next=/bids/` 쿼리 파라미터가 포함된 상태에서 로그인 후 해당 타깃 화면 이동 검증
4. `test_ssr_auth_logout_post`: 인증 상태에서 POST 로그아웃 폼 제출 후 세션 무효화 및 보호 화면 재접근 차단 검증
5. `test_ssr_auth_csrf_rejection`: CSRF 토큰 누락 시 403 Forbidden 응답 반환 검증
6. `test_ssr_auth_login_invalid_credentials`: 유효하지 않은 자격증명 제출 시 로그인 실패 처리 및 알림 검증

### 2.2 공고 목록 및 상세 AI 예측 (`tests/e2e/test_ssr_bids.py` — 6개 시나리오)
1. `test_ssr_bids_list_search`: 공고 목록 검색어(`q`) 입력 시 테이블 필터링 및 일치 항목 노출 검증
2. `test_ssr_bids_list_category_filter`: 분야(`cat=Servc`) 선택 시 용역 공고만 필터링 렌더링 검증
3. `test_ssr_bids_list_sort_and_region`: 정렬(`sort=amount`) 및 지역(`region=seoul`) 파라미터 적용 검증
4. `test_ssr_bids_list_pagination`: 20건 초과 공고 데이터에서 '다음' 버튼 클릭 시 2페이지 이동 및 URL 반영 검증
5. `test_ssr_bid_detail_ai_prediction`: 공고 상세 화면에서 투찰가 입력 후 `#btn-predict` 클릭 시 비동기 AJAX 호출을 통해 `#prediction-result` 노출 및 최적 투찰가, 예상 낙찰률 렌더링 검증
6. `test_ssr_bid_detail_no_reference_amount_disabled`: 기초금액/예정가격 미공개 공고 진입 시 예측 버튼 비활성화 및 안내 문구 노출 검증

### 2.3 낙찰 목록 및 상세 화면 (`tests/e2e/test_ssr_results.py` — 3개 시나리오)
1. `test_ssr_results_list_search_and_filter`: 낙찰 목록 검색어 및 카테고리 필터링 검증
2. `test_ssr_results_list_pagination`: 낙찰 목록 2페이지 이동 검증
3. `test_ssr_result_detail_view_and_chatbot_link`: 낙찰 상세 화면 제원(업체, 금액, 낙찰률) 렌더링 및 AI 분석 연계 버튼 클릭 시 `/chatbot/?result_id={id}` 이동 검증

### 2.4 대시보드 화면 (`tests/e2e/test_ssr_dashboard.py` — 3개 시나리오)
1. `test_ssr_dashboard_stats_and_metrics`: 비동기 통계 지표(전체 건수, 누적 금액, 평균 낙찰률) DOM 바인딩 검증
2. `test_ssr_dashboard_charts_rendered`: Chart.js 캔버스 요소(`canvas#monthlyTrendChart`, `canvas#agencyChart`)의 DOM 존재 및 가시성 검증 (**픽셀 단언 배제 원칙 준수**)
3. `test_ssr_dashboard_company_ranking_table`: 총액 계약 상위 업체 랭킹 테이블 정상 렌더링 검증

### 2.5 기존 기본 세션 및 스모크 검증 (4개 시나리오)
- `tests/e2e/test_smoke.py`: 로그인 화면 스모크 (1건)
- `tests/e2e/test_ssr_auth_session.py`: DB 격리 및 세션 주입 검증 (3건)

---

## 3. 원칙 준수 및 검증 결과

### 3.1 원칙 준수 항목
- **G1 데이터 무손실**: 모든 시나리오는 `conftest.py`의 `e2e_db_engine` 임시 SQLite DB에서만 격리 실행되었으며 개발 DB(`procurement`) 접근 0건 보장.
- **차트 시각화 단언 원칙**: Chart.js 캔버스 픽셀 단언을 배제하고 캔버스 DOM 요소의 존재성, 가시성, 실제 데이터 바인딩 여부로 검증하여 테스트 취약성 원천 제거.
- **테스트 독립성**: 각 테스트는 필요한 상태를 자체 픽스처로 생성하며 다른 테스트의 잔여 데이터에 의존하지 않음.
- **Chromium 자동 Skip**: 브라우저 부재 환경에서는 `pytest_runtest_setup`에 의해 에러 없이 자동 skip 처리 보장.

### 3.2 검증 결과

| 검증 명령 | 대상 | 결과 (Exit Code) | 통과 내역 |
| --- | --- | :---: | --- |
| `uv run pytest tests/e2e/ -v` | E2E 브라우저 테스트 슈트 | 0 | 22 passed |
| `uv run pytest tests/ -q -m 'not data_assets'` | 전체 백엔드 테스트 슈트 | 0 | 2,900+ passed |
| `python3 scripts/validate_agent_rules.py --quiet` | 에이전트 다중 규칙 검증 | 0 | pass |
| `python3 scripts/validate_doc_links.py --quiet` | 문서 링크 정합성 검증 | 0 | pass |

---

## 4. 결론

SSR 핵심 화면(인증, 공고 탐색·상세 AI 예측, 낙찰 결과·상세, 대시보드)에 대한 브라우저 E2E 시나리오 작성을 완료하였으며, 헤드리스 브라우저 상에서 22개 시나리오 전량이 안정적으로 통과함을 실측 확인하였습니다.

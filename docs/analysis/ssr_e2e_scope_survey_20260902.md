# SSR 브라우저 E2E 테스트 도입 범위 및 기술 조사 보고서 (2026-09-02)

> **작성일**: 2026-09-02
> **Task ID**: `task_2f3dcca0f788`
> **목적**: refac_bid_box SSR(Jinja2) 및 React 프론트엔드 브라우저 E2E 테스트 도입을 위한 대상 화면 식별, 도구 후보 비교(저장소 맞춤 실측 및 CI/크로스플랫폼 분석), 공유 자원 충돌 지점 분석, 단계별 분할 실행안 수립
> **단일 진실 원천(SSOT)**: 본 문서는 SSR 브라우저 E2E 범위 합의를 위한 조사 보고서이며 신규 의존성 설치 및 구현은 포함하지 않습니다.

---

## 1. 개요 및 배경

### 1.1 배경 및 목적
본 저장소(`refac_bid_box`)는 Django 모놀리식 구조에서 FastAPI + MySQL 8 + Redis + Meilisearch + Ollama 기반으로 리팩토링된 공공조달 입찰 예측 및 하이브리드 RAG 챗봇 플랫폼입니다.

현재 백엔드 및 서비스 계층은 `TestClient` 기반의 단위/통합 테스트(`tests/test_ui_ssr.py` 등)로 Jinja2 템플릿 컴파일, HTTP 응답 상태 코드, 기본 텍스트 렌더링을 검증하고 있습니다. 그러나 다음과 같은 실제 브라우저 런타임 특성은 검증하지 못하는 한계가 있습니다:
1. 실제 DOM 조작 및 JavaScript 이벤트 핸들링 (Chart.js 차트 렌더링, 공고 검색 필터링, AI 예측 버튼 비동기 호출)
2. 하이브리드 RAG 챗봇의 실시간 Server-Sent Events (SSE) 토큰 스트리밍 수신 및 렌더링
3. 브라우저 세션 쿠키, CSRF 폼 토큰, 리다이렉트(`next` 파라미터) 흐름
4. 크로스 플랫폼(G2: Linux, macOS, Windows) 상에서의 브라우저 렌더링 일관성

본 조사는 브라우저 E2E 테스트 프레임워크를 도입하기 전, 대상 화면을 전수 조사하고 도구 후보를 저장소 관점에서 비교 평가하며, 공유 자원 충돌을 예방할 수 있는 단계별 실행안을 마련하는 것을 목표로 합니다.

### 1.2 핵심 제약 및 원칙
- **G1 데이터 무손실**: E2E 테스트 실행 중 운영 및 개발 DB(`procurement`)의 스키마와 데이터를 절대 오염시키지 않아야 합니다.
- **G2 크로스 플랫폼**: Linux(Ubuntu), macOS, Windows 환경에서 동일하게 테스트가 동작해야 합니다.
- **G3 스택 최적화**: CI 파이프라인의 실행 시간 증가를 최소화하고 병목을 차단해야 합니다.
- **1인 작업 Git 원칙**: 작업 브랜치에서 검증 완료 후 `main`에 직접 병합하며 Pull Request는 생성하지 않습니다.
- **의존성 추가 사전 합의**: 본 Task에서는 도구를 설치하지 않으며(`package.json`, `pyproject.toml` 미수정), 비교 분석 보고서만 산출합니다.

---

## 2. 대상 화면 목록 및 계열별 상세 분석

현재 저장소에는 **Jinja2 SSR 화면 (정본 UI)**과 **Vite React SPA (동결된 레거시 스캐폴드)** 두 계열의 UI가 공존합니다.

### 2.1 SSR Jinja2 계열 (정본 UI — `src/app/api/ui.py` & `src/app/templates/`)

SSR 계열은 총 12종의 HTML 템플릿으로 구성되며, FastAPI `ui.py` 라우터를 통해 서빙됩니다.

| 화면명 | 진입 경로 (URL) | 템플릿 경로 | 인증 요구 여부 | 주요 기능 및 브라우저 상호작용 |
| --- | --- | --- | :---: | --- |
| 메인 홈 | `/` | `src/app/templates/index.html` | 필수 (로그인 필요) | 종합 대시보드 통계 카드, 최근 공고 10건 목록, 카테고리 탭 전환 |
| 공고 목록 | `/bids/` | `src/app/templates/bids/list.html` | 필수 | 검색어(`q`), 카테고리(`cat`), 지역(`region`), 정렬(`sort`), 페이지네이션, Meilisearch 연동 |
| 공고 상세 | `/bids/{pk}/` | `src/app/templates/bids/detail.html` | 필수 | 공고 상세 제원, AI 낙찰가 예측 비동기 폼 (`#btn-predict`, `#user-price`, 금액 미공개 시 비활성화) |
| 낙찰 목록 | `/bids/results/` | `src/app/templates/bids/results.html` | 필수 | 낙찰 결과 검색/필터/정렬/페이지네이션, Meilisearch 연동 |
| 낙찰 상세 | `/bids/result/{pk}/` | `src/app/templates/bids/result_detail.html` | 필수 | 낙찰 상세 제원, 낙찰률 표시, 챗봇 AI 인텔리전스 분석 바로가기 (`/chatbot/?result_id={id}`) |
| 대시보드 | `/bids/dashboard/` | `src/app/templates/bids/dashboard.html` | 필수 | 입찰/낙찰 통계 지표, Chart.js 기반 시각화 차트 |
| 공고/낙찰 비교 | `/bids/compare/` | `src/app/templates/bids/compare.html` | 필수 | 공고 대비 낙찰 매칭 통계, 수주 분석 차트 |
| 하이브리드 RAG 챗봇 | `/chatbot/` | `src/app/templates/chatbot/chat.html` | 필수 | 최근 대화 세션 사이드바(20건), LLM 모델 라벨, SSE 실시간 토큰 스트리밍 통신 |
| 로그인 | `/accounts/login/` | `src/app/templates/accounts/login.html` | 불필요 (비인증 전용) | CSRF 토큰 검증, 로그인 Rate Limiting, 401/403 오류 재렌더, 로그인 성공 시 `next` 리다이렉트 |
| 회원가입 | `/accounts/signup/` | `src/app/templates/accounts/signup.html` | 불필요 (비인증 전용) | 약관/개인정보 동의(`terms_content.html`), CSRF 검증, 422/409 오류 재렌더 |
| 로그아웃 | `/accounts/logout/` (POST) | N/A (POST 엔드포인트) | 필수 | CSRF 검증, 세션 쿠키 무효화 후 로그인 페이지 303 리다이렉트 (GET 요청은 차단) |
| 단축/호환 리다이렉트 | `/results/`, `/dashboard/`, `/compare/`, `/chat/` | N/A | 해당 없음 | 레거시 URL 요청 시 정본 URL로 307 임시 리다이렉트 |

### 2.2 Vite React SPA 계열 (동결 스캐폴드 — `frontend/src/App.tsx` & `frontend/`)

Vite React 앱은 `docker-compose.yml`에서 `legacy` 프로필로 격리되어 있으며, 단일 SPA 화면(`frontend/src/App.tsx`) 내에서 3개의 탭으로 동작합니다.

| 탭 / 영역 | 주요 경로 및 상태 | 인증 요구 여부 | 주요 기능 및 브라우저 상호작용 |
| --- | --- | :---: | --- |
| 헬스체크 및 헤더 | 공통 상단 영역 | 불필요 | `/api/v1/health` 상태 뱃지, `/api/v1/bids/stats`, `/api/v1/bids/compare-stats` 카드 4종 |
| 입찰 공고 대시보드 | `activeTab === 'dashboard'` | 불필요 | 카테고리 필터(Thng, Servc, Cnstwk), 검색어 입력, 공고 목록 테이블, '예측하기' 버튼 |
| AI 예측 시뮬레이터 | `activeTab === 'prediction'` | 불필요 | 추정가격/기초금액/업무구분 입력, 단일 공고 바인딩, `/api/v1/predictions/predict-price` 호출, 결과 카드 |
| 하이브리드 RAG 챗봇 | `activeTab === 'chatbot'` | 익명/인증 쿼터 | SSE 스트리밍 통신, 스테이지 표시, 참조 문서 렌더링, 토큰 스트리밍, 차트 데이터 시각화, 스트림 중지(Abort) |

### 2.3 두 계열 간 아키텍처 비교

| 비교 항목 | SSR Jinja2 계열 (정본) | Vite React SPA 계열 (레거시 스캐폴드) |
| --- | --- | --- |
| **렌더링 방식** | Multi-Page Application (MPA, 서버 렌더링) | Single Page Application (SPA, 클라이언트 렌더링) |
| **인증 및 세션** | `bidbox_session` HTTP-only 쿠키 + CSRF 폼 토큰 | 백엔드 API 세션 쿠키 또는 익명 IP 쿼터에 의존 |
| **JS 프레임워크** | jQuery + 바닐라 JS + 로컬 Chart.js / marked | React 19 + TypeScript + Vite |
| **스타일링** | Tailwind 빌드타임 컴파일 CSS (`src/app/static/css/tailwind.css`) | 인라인 스타일링 + CSS |
| **운영 상태** | 기본 기동 대상 (정본 UI) | `profiles: ["legacy"]` 로 격리 (필요 시 선택 기동) |

---

## 3. 브라우저 E2E 도구 후보 비교 및 평가

본 저장소의 기술 스택(Python 3.11 + uv, FastAPI, Node 22 + Vite, Docker, GitHub Actions 3플랫폼 매트릭스)을 기준으로 주요 브라우저 E2E 도구 4종을 비교 평가합니다.

### 3.1 도구 후보 비교표

| 평가 항목 | 후보 1: Playwright (Python / `pytest-playwright`) | 후보 2: Playwright (Node.js / `@playwright/test`) | 후보 3: Cypress (Node.js) | 후보 4: Puppeteer (Node.js) |
| --- | --- | --- | --- | --- |
| **도구 체인** | Python / `uv` + `pytest` | Node.js / `npm` | Node.js / `npm` | Node.js / `npm` |
| **저장소 적합성** | **최상** (기존 `tests/` 및 pytest 픽스처 100% 통합) | **상** (프론트 디렉터리 분리 관리) | **중** (SSR MPA 테스트 구조적 제약) | **중** (테스트 러너 별도 구성 필요) |
| **설치 비용** | 패키지 1개 + Chromium 드라이버 (약 150MB) | 패키지 1개 + Chromium 드라이버 (약 150MB) | 대용량 바이너리 (약 500MB+) | 패키지 + 드라이버 (약 170MB) |
| **CI 시간 증가 추정** | **+25~35초** (Chromium headless 단일) | **+30~40초** (npm 의존성 추가) | **+60~90초** (무거운 런타임 오버헤드) | **+30~45초** |
| **크로스 플랫폼 (G2)** | **완전 지원** (Ubuntu, macOS, Windows) | **완전 지원** (Ubuntu, macOS, Windows) | **지원** (Windows Electron 간헐 불안정) | **지원** (주로 Chromium 중심) |
| **세션 주입 용이성** | **최상** (`create_session()` 직접 호출 후 쿠키 주입) | **중** (UI 로그인 또는 API 호출 필요) | **중** (`cy.session` 핸들링 복잡) | **중** (수동 쿠키 설정) |
| **SSE 스트리밍 검증** | **완전 지원** (비동기 이벤트 리스너 및 DOM 감시) | **완전 지원** | **제약** (SSE 버퍼링 및 스트림 대기 복잡) | **지원** (저수준 핸들링 필요) |
| **멀티 브라우저** | Chromium, Firefox, WebKit | Chromium, Firefox, WebKit | Chrome, Firefox, Edge, Electron | Chromium 중심 (Firefox 실험적) |

### 3.2 후보별 심층 분석

#### 1) Playwright Python (`pytest-playwright`) — [강력 권장]
- **장점**:
  - 기존 백엔드 테스트 슈트(`pytest`)와 완벽하게 융합됩니다.
  - `tests/conftest.py`의 DB 격리 픽스처, `create_session()`, `CustomUser` 생성 로직을 그대로 재사용하여 테스트 전 브라우저 컨텍스트에 즉시 인증 쿠키를 주입할 수 있습니다(매 테스트마다 UI 로그인을 반복하지 않아 실행 속도 극대화).
  - Python `uv` 패키지 관리자로 일관되게 관리되며, `uv run pytest tests/e2e` 명령 하나로 통합 실행됩니다.
  - 헤드리스 Chromium 기준 macOS, Linux, Windows에서 매우 안정적으로 구동됩니다.
- **단점**:
  - Node.js 생태계의 Playwright Test Runner 전용 UI 기능(Trace Viewer TUI 모드 등)이 Python에서는 일부 CLI 명령(`playwright show-trace`)으로 분리되어 있습니다.

#### 2) Playwright Node.js (`@playwright/test`)
- **장점**:
  - Playwright의 공식 메인 런타임으로 기능 업데이트가 가장 빠르고 풍부한 UI 테스트 러너 기능을 제공합니다.
- **단점**:
  - 백엔드 DB/세션 픽스처를 직접 호출할 수 없어, 모든 테스트가 실제 UI 로그인을 거치거나 별도 인증 Mock API를 호출해야 합니다.
  - 백엔드 테스트(pytest)와 프론트엔드 테스트(npm)로 CI 워크플로와 도구 체인이 완전히 이원화됩니다.

#### 3) Cypress
- **장점**:
  - SPA 프론트엔드 개발 시 브라우저 내 시각적 디버깅 인터페이스가 우수합니다.
- **단점**:
  - SPA 중심으로 설계되어 서버 사이드 렌더링(SSR) 다중 페이지 간의 전체 페이지 이동(`location.href`, 303/307 리다이렉트) 테스트 시 세션 유지가 까다롭습니다.
  - 바이너리 크기가 500MB 이상으로 무거워 CI 다운로드 및 실행 시간이 크게 증가합니다.
  - Windows CI 환경에서 Electron 프로세스 행(hang) 이슈가 간헐적으로 발생하여 G2 목표에 리스크가 있습니다.

#### 4) Puppeteer
- **장점**:
  - 경량 Chromium 제어 라이브러리로 단순 스크린샷이나 PDF 생성에 적합합니다.
- **단점**:
  - 단독 테스트 프레임워크가 아니므로 Jest/Mocha 등의 테스트 러너, 단언 라이브러리, 픽스처 관리자를 별도로 구성해야 합니다.
  - Firefox, WebKit 등 멀티 브라우저 지원이 제한적입니다.

---

## 4. 공유 자원 및 환경 충돌 지점 분석 (Shared Resource Conflicts)

브라우저 E2E 테스트는 실제 백엔드 서버(FastAPI)와 연계 인프라(MySQL, Redis, Meilisearch)가 네트워크 상에서 구동되어야 하므로, 기존 개발/운영 환경 및 CI Job과의 자원 경합을 정밀하게 통제해야 합니다.

### 4.1 서비스 컨테이너 및 포트 충돌 분석

| 구성 요소 | 개발 Compose (`docker-compose.yml`) | 운영 Compose (`docker-compose.prod.yml`) | E2E 테스트 실행 시 충돌 지점 및 격리 방안 |
| --- | --- | --- | --- |
| **FastAPI App** | `0.0.0.0:8000` | 내부 전용 (Caddy 443 경유) | **포트 충돌**: 개발 컨테이너가 8000을 점유 중인 상태에서 로컬 E2E 테스트용 Uvicorn을 8000으로 띄우면 `Address already in use` 발생.<br>**격리 방안**: E2E 실행 스크립트에서 동적 임시 포트(예: `8001`)를 사용하거나, Docker Compose 컨테이너를 직접 테스트 대상으로 결박. |
| **MySQL 8** | `0.0.0.0:3306` (`procurement`) | 내부 전용 (`3306`) | **데이터 오염 (G1 위반 위험)**: E2E 테스트의 회원가입/로그인이 개발 DB `procurement`에 쓰여지면 무손실 원칙 훼손.<br>**격리 방안**: E2E 전용 격리 스키마(`test_procurement_e2e`)를 생성하거나, SQLite in-memory / SQLite file 격리 모드로 구동. |
| **Redis** | `0.0.0.0:6379` (DB 0) | 내부 전용 (`requirepass`) | **세션/캐시 충돌**: 개발 환경의 세션 키 및 로그인 시도 제한(Rate Limit) 카운터 오염.<br>**격리 방안**: E2E 전용 Redis DB 인덱스(예: `REDIS_URL=redis://127.0.0.1:6379/15`) 분리 또는 mock session store 사용. |
| **Meilisearch** | `0.0.0.0:7700` | 내부 전용 (`7700`) | **검색 인덱스 오염**: E2E 검색 테스트로 인한 개발 인덱스 오염.<br>**격리 방안**: E2E 전용 인덱스 네임스페이스(`e2e_bids_*`) 사용 또는 읽기 전용 모드. |
| **Vite Dev Server** | `0.0.0.0:5173` (legacy profile) | 미제공 | **SSR 테스트에는 불필요**: React SPA E2E 테스트 시에만 선택적으로 5173 포트 기동. |

### 4.2 CI 환경에서의 Job 충돌 분석 (`.github/workflows/ci.yml`)

현재 CI 파이프라인에는 다음과 같은 Job들이 실행됩니다:
1. `supply-chain`: 보안 스캔 및 SBOM 생성
2. `lint-and-validate`: 린트, 포맷, bandit, mypy, agent-rule, 프론트엔드 node 단위 테스트
3. `cross-platform-test`: Ubuntu(3.11, 3.12, 3.13), macOS(3.11), Windows(3.11) 매트릭스 (SQLite in-memory, `not data_assets`)
4. `docker-build`: 도커 이미지 빌드 및 스모크 테스트
5. `mysql-ngram-integration`: Ubuntu 러너에 `mysql:8.0` 컨테이너(포트 3306)를 띄워 전용 픽스처로 통합 테스트

**CI 통합 시 핵심 충돌 및 리스크**:
- `cross-platform-test`의 Windows Job은 과거 342초에서 현재 212.90초로 단축되어 green을 유지하고 있습니다. 여기에 브라우저 E2E를 직접 추가하면 브라우저 드라이버 다운로드 및 서버 기동 오버헤드로 인해 Windows Job이 타임아웃될 위험이 큽니다.
- `mysql-ngram-integration` Job은 이미 러너의 3306 포트를 점유하고 있으므로, 같은 러너 단계에서 E2E DB를 3306에 띄우면 충돌합니다.
- **대책**: E2E 테스트는 `cross-platform-test`와 분리된 **독립된 CI Job (`e2e-browser-test`)**으로 신설하고, Linux(Ubuntu) 환경에서 SQLite/격리 DB 기반으로 1차 게이트를 구축한 뒤 안정화 시 크로스 플랫폼으로 확장해야 합니다.

---

## 5. 단계별 분할안 (Phased Implementation Plan)

모든 단계는 상호 독립적인 Orca Task로 Dispatch 가능하도록 세분화하며, 각 단계마다 명확한 쓰기 파일, 검증 명령, 완료 기준을 정의합니다.

### Phase 1: E2E 프레임워크 기반 구축 및 스모크 검증 (Task E2E-1)
- **목표**: `pytest-playwright` 의존성 합의 및 설치, E2E 디렉터리 구조 및 브라우저 세션 픽스처 구축, 스모크 테스트 1건 검증
- **선행 의존**: 없음 (본 보고서 승인 후 즉시 착수 가능)
- **쓰기 허용 파일 목록**:
  - `pyproject.toml` (`pytest-playwright` dev 의존성 추가)
  - `uv.lock`
  - `tests/e2e/conftest.py` (FastAPI 백그라운드 서버 구동 픽스처, Playwright 브라우저 컨텍스트 픽스처)
  - `tests/e2e/test_smoke.py` (메인 홈 303 리다이렉트 및 로그인 페이지 200 렌더링 기본 스모크)
  - `Makefile` (`test-e2e` 타깃 추가)
- **검증 명령**:
  - `uv run pytest tests/e2e/test_smoke.py --headless`
  - `python3 scripts/validate_agent_rules.py --quiet`
- **완료 판정 기준**:
  - 브라우저가 헤드리스 모드로 기동되어 로그인 페이지를 정상 방문하고 종료되는 스모크 테스트 통과 (1 passed)
  - 기존 단위 테스트 2,900+ 건에 회귀 영향 0건

### Phase 2: SSR Jinja2 인증 및 공고/낙찰 핵심 화면 E2E 테스트 (Task E2E-2)
- **목표**: SSR 핵심 8대 화면에 대한 사용자 인터랙션(폼 제출, 검색/필터, 페이지 이동, AI 예측 폼) E2E 테스트 작성
- **선행 의존**: Phase 1 완료 (`Task E2E-1`의 `worker_done` 승인)
- **쓰기 허용 파일 목록**:
  - `tests/e2e/test_ssr_auth.py` (회원가입 -> 로그인 -> `next` 리다이렉트 -> POST 로그아웃 플로우, CSRF 검증, 에러 메시지 렌더링)
  - `tests/e2e/test_ssr_bids.py` (공고 목록 검색 필터링, 정렬, 상세 페이지 진입, AI 예측 폼 비동기 계산 및 DOM 결과 반영)
  - `tests/e2e/test_ssr_results.py` (낙찰 결과 목록 검색, 상세 페이지, 챗봇 연계 링크 클릭 시 프롬프트 전달 검증)
  - `tests/e2e/test_ssr_dashboard.py` (대시보드 통계 카드 수치 표시, Chart.js 캔버스 렌더링 검증)
- **검증 명령**:
  - `uv run pytest tests/e2e/test_ssr_*.py --headless -v`
  - `python3 scripts/validate_agent_rules.py --quiet`
- **완료 판정 기준**:
  - SSR 핵심 시나리오(인증, 검색, 예측 폼, 상세) 최소 12개 테스트 전량 통과 (12+ passed, 0 failed)

### Phase 3: SSR 챗봇 실시간 SSE 스트리밍 및 React SPA E2E 테스트 (Task E2E-3)
- **목표**: 챗봇 화면의 실시간 SSE 토큰 스트리밍 DOM 반영 및 React SPA 3개 탭 전환 E2E 검증
- **선행 의존**: Phase 2 완료
- **쓰기 허용 파일 목록**:
  - `tests/e2e/test_ssr_chatbot_stream.py` (질문 입력 -> SSE 스트리밍 토큰 수신 -> 차트 데이터 시각화 -> 스트림 완료 검증)
  - `tests/e2e/test_react_spa.py` (Vite React 앱 기동, 대시보드/예측/챗봇 3대 탭 전환 및 데이터 바인딩 검증)
- **검증 명령**:
  - `uv run pytest tests/e2e/test_ssr_chatbot_stream.py tests/e2e/test_react_spa.py --headless -v`
  - `python3 scripts/validate_agent_rules.py --quiet`
- **완료 판정 기준**:
  - SSE 토큰이 브라우저 DOM에 실시간으로 누적 렌더링되는 시나리오 통과
  - React SPA 탭 인터랙션 테스트 통과

### Phase 4: CI 워크플로 통합 및 아티팩트 자동화 (Task E2E-4)
- **목표**: GitHub Actions CI에 독립된 `e2e-browser-test` Job 추가, 실패 시 Playwright Trace/Screenshot 아티팩트 업로드 구성
- **선행 의존**: Phase 3 완료
- **쓰기 허용 파일 목록**:
  - `.github/workflows/ci.yml` (`e2e-browser-test` Job 추가)
  - `docs/ops/ci_contract.md` (CI E2E 계약 및 실행 시간 예산 명시)
  - `docs/ops/e2e_testing_guide.md` (개발자 로컬/CI E2E 실행 가이드)
- **검증 명령**:
  - `uv run actionlint`
  - `python3 scripts/validate_agent_rules.py --quiet`
  - `python3 scripts/validate_doc_links.py --quiet`
- **완료 판정 기준**:
  - CI E2E Job 실행 시간 45초 이내 완료
  - `actionlint` 및 문서 링크 검증 통과

---

## 6. 최종 권장안 및 기각 사유 (Decision & Recommendation)

### 6.1 최종 권장안: `pytest-playwright` (Python 기반 Playwright)
- **선정 근거**:
  1. **테스트 생태계 단일화**: 백엔드와 E2E가 모두 Python `pytest` + `uv` 생태계로 일원화되어 관리 비용이 최소화됩니다.
  2. **세션 및 DB 픽스처 직접 주입**: `create_session()` 함수를 호출하여 브라우저에 세션 쿠키를 즉시 주입할 수 있으므로, 매 테스트마다 UI 로그인 폼을 거치는 지연(테스트당 2~3초)을 제거하여 전체 E2E 테스트 슈트를 15초 이내로 완주할 수 있습니다.
  3. **비동기 SSE 완벽 지원**: Playwright의 비동기 네트워크 감시(`page.expect_response`, DOM mutation 감시)를 통해 챗봇 SSE 스트리밍 테스트를 가장 신뢰성 있게 수행할 수 있습니다.
  4. **크로스 플랫폼(G2) 신뢰성**: macOS, Linux, Windows 3대 OS 모두에서 동일한 API로 안정 구동됩니다.

### 6.2 타 후보 기각 사유
- **Cypress 기각**: 대용량 바이너리(500MB+)로 인한 CI 오버헤드가 과도하며, SSR 환경의 멀티 페이지 이동 및 리다이렉트 처리 시 불안정성이 있습니다.
- **Node.js `@playwright/test` 기각**: 훌륭한 도구이나 Python 백엔드 픽스처(DB, 세션 생성기)를 직접 호출할 수 없어 테스트 속도가 저하되고, 도구 체인이 Node.js와 Python으로 분열됩니다.
- **Puppeteer 기각**: 테스트 러너와 어설션 라이브러리를 별도 조합해야 하여 설정 및 유지보수 복잡도가 불필요하게 증가합니다.
- **Selenium 기각**: 별도 웹드라이버 버전 관리 오버헤드가 크고, 현대적인 비동기 SSE 이벤트 처리가 까다롭습니다.

---

## 7. 결론 및 향후 착수 로드맵

1. **착수 승인 요청**: 본 조사 보고서에서 제시한 `pytest-playwright` 기반 4단계 분할안에 대해 코디네이터 및 사용자의 합의를 거칩니다.
2. **Phase 1 착수**: 합의 완료 시 `Task E2E-1`을 Dispatch하여 `pyproject.toml`에 `pytest-playwright`를 추가하고 스모크 테스트 환경을 구축합니다.
3. **점진적 화면 커버리지 확장**: Phase 2(SSR 핵심 화면) -> Phase 3(SSE 챗봇 & React SPA) -> Phase 4(CI 통합) 순서로 순차적 구현 및 검증을 진행합니다.

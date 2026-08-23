# 프론트엔드 아키텍처 결정 (ADR)

> **작성일**: 2026-07-31
> **상태**: 목표 아키텍처 확정 / 구현 미완 (HTMX 미도입)
> **수정일**: 2026-08-23
> **근거**: [`REFACTORING_DESIGN.md`](REFACTORING_DESIGN.md) 3.7절

---

## 목표 아키텍처 (확정)

| 항목 | 선택 | 근거 |
| --- | --- | --- |
| 1차 UI | **SSR + HTMX + Jinja2** | 원본 Django Templates UX 유지, 점진적 이행 |
| 챗봇 스트리밍 | **SSE (FastAPI StreamingResponse)** | 설계서 G3 레이턴시 목표 달성 |
| React SPA (`frontend/`) | **레거시 스캐폴드 보존, 신규 개발 중단** | Antigravity가 설계와 무관하게 생성한 스캐폴드 동결 |

---

## 현재 구현 상태 (실측 및 코드베이스 확인)

- **실제 템플릿 위치**: `src/app/templates/` (총 12종 Jinja2 템플릿 이식 완료)
- **정적 자산 위치**: `src/app/static/` (하위는 `css/`, `images/` 뿐이며 JS 번들 없음)
- **HTMX 미도입**: `src/app/templates/` 전체에서 HTMX 로드와 `hx-*` 속성이 **0건**입니다. `base.html:268`은 jQuery 3.7.1을 CDN에서 로드합니다. 목표 아키텍처의 1차 UI 선택(SSR + HTMX)은 **아직 이행되지 않았습니다**
- **Chart.js**: 파일이 아니라 CDN 로드입니다 (`bids/dashboard.html:6` 등 3개 템플릿)
- **SSR 라우팅 진입점**: `src/app/api/ui.py` (`/`, `/bids/`, `/bids/results/`, `/bids/dashboard/`, `/chatbot/` 등)
- **챗봇 SSE 스트리밍**: `POST /api/v1/chatbot/chat/stream` (단일 파이프라인 스트리밍 완료)
- **React SPA 격리**: `docker-compose.yml`에서 `profiles: ["legacy"]`로 격리, 기본 기동 제외

---

## 이행 결과 (2026-08-01)

원본 템플릿 12종(5,370줄)을 Jinja2 로 이식 완료했습니다. 경로는 원본 Django URL 을 그대로 씁니다.

| 원본 템플릿 | 이식 경로 | SSR 경로 |
| --- | --- | --- |
| `base.html` | `src/app/templates/base.html` | (레이아웃) |
| `index.html` | `src/app/templates/index.html` | `GET /` |
| `bids/list.html` | `src/app/templates/bids/list.html` | `GET /bids/` |
| `bids/detail.html` | `src/app/templates/bids/detail.html` | `GET /bids/{pk}/` |
| `bids/results.html` | `src/app/templates/bids/results.html` | `GET /results/` |
| `bids/result_detail.html` | `src/app/templates/bids/result_detail.html` | `GET /results/{pk}/` |
| `bids/dashboard.html` | `src/app/templates/bids/dashboard.html` | `GET /dashboard/` |
| `bids/compare.html` | `src/app/templates/bids/compare.html` | `GET /compare/` |
| `chatbot/chat.html` | `src/app/templates/chatbot/chat.html` | `GET /chat/` |
| `accounts/login.html` | `src/app/templates/accounts/login.html` | `GET /accounts/login/` |
| `accounts/signup.html` | `src/app/templates/accounts/signup.html` | `GET /accounts/signup/` |
| `accounts/terms_content.html` | `src/app/templates/accounts/terms_content.html` | (모달 포함) |

### Django 호환 계층

원본 템플릿 본문을 최대한 그대로 두기 위해 두 개의 호환 모듈을 두었습니다.

| 모듈 | 역할 |
| --- | --- |
| `src/app/core/templating.py` | `{% url %}` 이름 표, `intcomma`/`date`/`truncatechars`/`add` 등 Django 필터 |
| `src/app/services/auth_forms.py` | `signup.html` 이 순회하는 Django `BoundField` 호환 객체 |

### 원본과 의도적으로 다른 부분

| 항목 | 원본 | 이식본 | 사유 |
| --- | --- | --- | --- |
| 소셜 로그인 | django-allauth (kakao/naver/google) | 버튼 미노출 | 이식본에 소셜 인증 없음. 죽은 링크 노출 방지 |
| 챗봇 헤더 모델명 | `Gemini 3.1 Flash-Lite preview` 하드코딩 | `settings` 실제 값 | LLM 을 Ollama 로 교체해 하드코딩 값이 거짓이 됨 |
| 챗봇 색인 건수 | `842K` 하드코딩 | DB 실집계 | 실제 183만행과 불일치 |
| CSRF 토큰 | `{% csrf_token %}` | 제거 | 세션 쿠키 기반, 토큰 미사용 |
| 로그인 폼 전송 | Django 폼 POST | fetch JSON POST 스크립트 추가 | 인증이 `POST /api/v1/accounts/login` 으로 이동. 폼 본문 그대로는 API 가 받지 못함 |
| 로그인 `next` | Django 가 자동 처리 | hidden 필드로 명시 전달 | fetch 전송이라 폼 액션의 쿼리스트링이 서버에 닿지 않음 |
| 낙찰가 예측 호출 | `$.ajax` form-encoded | JSON 본문 | FastAPI Pydantic 스키마가 JSON 을 요구 |
| 금액 미공개 공고의 예측 폼 | 항상 활성. 누르면 0원 반환 | 잠금 + 사유 표시 | 0원은 오답. [`prediction_without_amount_20260804.md`](prediction_without_amount_20260804.md) |

### React SPA

`frontend/` 는 본 ADR 대로 신규 개발을 중단하고 참조용으로 동결합니다.

---

## 동결 자산 노출 차단 (2026-08-03)

동결 결정 이후에도 `docker-compose.yml` 의 `frontend` 서비스가 기본 기동 대상에 남아 있어, `docker compose up` 시 5173 포트로 **원본과 다른 디자인의 화면이 노출**되는 문제가 있었습니다.

| 항목 | 원본 | 동결된 React |
| --- | --- | --- |
| 화면 수 | 12개 페이지 5,370줄 | `App.tsx` 단일 파일 728줄 |
| 주 색상 | `#0073E6` (기업형 블루) | `#0f172a`, `#38bdf8` (slate/sky) |
| API 연동 | - | `/api/v1/chatbot/chat/stream` 한 곳뿐 |

조치로 해당 서비스에 `profiles: ["legacy"]` 를 지정해 기본 기동에서 제외했습니다.

| 명령 | 기동 서비스 |
| --- | --- |
| `docker compose up -d` | `db`, `redis`, `app` |
| `docker compose --profile legacy up -d frontend` | 위 + `frontend` (참조용) |

디렉토리 자체는 본 ADR 의 "삭제하지 않고 참조용으로 유지" 방침에 따라 그대로 둡니다.

### 명시 기동은 프로필로 막을 수 없습니다 (2026-08-04)

`profiles` 는 기본 기동에서 빼줄 뿐, 서비스 이름을 직접 지정한 `docker compose up -d app frontend` 는 그대로 뜹니다. 실제로 다른 세션이 이 형태로 기동해 5173 이 다시 열렸고, 응답 HTML 만 보고 정상으로 판정한 사례가 있었습니다.

**기동 시에는 서비스 이름을 열거하지 말고 `docker compose up -d` 를 씁니다.** 5173 이 열려 있다면 정본이 아닌 화면이므로 내립니다.

### 검토 후 기각된 대안

React 를 원본 디자인으로 전면 재구현하는 방안을 설계까지 진행한 뒤 기각했습니다. 근거 자료는 [`frontend_react_reproduction_design.md`](frontend_react_reproduction_design.md) 에 보존하며, 기각 사유는 원본 재현이 SSR 에서 이미 완료되어 재수행의 실익이 없다는 점입니다.

---

## URL 경로 정본 복원 (2026-08-04)

이식 초기에 SSR 경로를 `/results/`, `/dashboard/` 처럼 짧게 줄여 두어 원본과 주소가 달랐습니다. 원본(`apps/bids/urls.py`, `config/urls.py`)을 정본으로 되돌렸습니다.

| 원본 = 현재 정본 | 이식 초기 단축 경로 |
| --- | --- |
| `/bids/results/` | `/results/` |
| `/bids/result/{pk}/` | `/results/{pk}/` |
| `/bids/dashboard/` | `/dashboard/` |
| `/bids/compare/` | `/compare/` |
| `/chatbot/` | `/chat/` |

단축 경로는 삭제하지 않고 307 로 정본에 연결합니다. 북마크와 외부 링크를 깨뜨리지 않기 위함입니다.

중간에 **방향이 반대인 구현**이 있었습니다. 링크는 원본 주소를 가리키는데 핸들러는 단축 경로에 남아 있어, 화면 이동마다 리다이렉트가 한 번씩 더 붙고 주소창 최종 값이 원본과 달라졌습니다. 정본 경로에 핸들러를 두는 방향으로 바로잡았습니다.

`/bids/results/` 등 네 경로는 라우터에서 `/bids/{pk}/` 보다 **먼저** 등록해야 합니다. 뒤에 두면 `results` 가 `pk` 로 해석되어 422 가 납니다.

---

## 챗봇 SSE 스트리밍 (2026-08-04)

기존 legacy `GET /api/v1/chatbot/stream` 은 제거되었습니다. 해당 엔드포인트는 RAG 답변 토큰만 흘려 플래너, 자동화 확인, 차트 페이로드, 세션 저장이 빠져 있었고, 현재는 모든 클라이언트가 정본 `POST /api/v1/chatbot/chat/stream`을 씁니다.

`POST /api/v1/chatbot/chat/stream` 을 새로 두어 **같은 파이프라인을 그대로 스트리밍**합니다.

| 이벤트 | 시점 | 내용 |
| --- | --- | --- |
| `stage` | 즉시 | 진행 단계 안내 (planning / answering) |
| `plan` | 계획 확정 | `plan_steps`, `intent` |
| `docs` | 검색 완료 | 근거 문서 |
| `token` | 생성 중 | 답변 조각 (체감 속도용) |
| `final` | 완료 | **비스트리밍과 동일한 `ChatResponse`** |

`final` 이 비스트리밍 응답과 같은 계약이라 화면은 `handleBotPayload` 하나로 두 경로를 렌더합니다. 계약이 어긋나면 스트리밍에서만 차트나 자동화 카드가 사라지므로, 두 응답의 키 집합이 같은지 테스트로 고정했습니다.

즉답 분기(세션 전환, 보안 차단, 자동화 확인·실행, 자동화 상태)는 생성할 토큰이 없어 `stage` 다음 바로 `final` 이 옵니다. 파이프라인을 `_prepare_chat` 과 `_finalize_rag_answer` 로 나누어 두 경로가 세션 저장 로직을 공유합니다.

### 실측 (Ollama gemma4:e4b, 로컬)

| 경로 | 총 시간 | 첫 피드백 |
| --- | ---: | ---: |
| 비스트리밍 `POST /chat` | 5.51 ~ 6.20s | 5.51s (완료 시) |
| 스트리밍 `POST /chat/stream` | 5.63 ~ 6.77s | **0.00s** (`plan`, `docs`) |

**총 레이턴시는 줄지 않았습니다.** 개선된 것은 첫 피드백까지의 시간이며, 답변이 길수록 토큰 스트리밍 이득이 커집니다. 첫 토큰까지 약 5초는 Ollama 의 프롬프트 처리 시간이라 프런트엔드에서 줄일 수 없습니다.

콜드 스타트(모델 최초 로드) 1회는 18.0s 가 걸립니다. 측정 시 워밍업 1회를 버려야 합니다.

---

## 남은 작업

1. ~~챗봇 탭 SSE 스트리밍 전환~~ → **완료: `POST /api/v1/chatbot/chat/stream`** (2026-08-04)
2. ~~로그인/회원가입 POST 처리를 SSR 폼으로 연결~~ → **완료: fetch JSON POST → API 연결** (2026-08-01)
3. ~~원본 `re_path` 이중 슬래시 교정 이식~~ → **완료: `collapse_bids_double_slash` 미들웨어** (2026-08-04)
4. Django admin 은 이식하지 않습니다. 원본에서 사용하지 않았음을 담당자가 확인했습니다 (2026-08-04)

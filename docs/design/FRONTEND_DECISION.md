# 프론트엔드 아키텍처 결정 (ADR)

> **작성일**: 2026-07-31
> **상태**: 확정
> **근거**: [`REFACTORING_DESIGN.md`](REFACTORING_DESIGN.md) 3.7절

---

## 결정

| 항목 | 선택 | 근거 |
| --- | --- | --- |
| 1차 UI | **SSR + HTMX + Jinja2** | 원본 Django Templates UX 유지, 점진적 이행 |
| 챗봇 스트리밍 | **SSE (FastAPI StreamingResponse)** | 설계서 G3 레이턴시 목표 |
| React SPA (`frontend/`) | **레거시 스캐폴드 보존, 신규 개발 중단** | Antigravity가 설계와 무관하게 생성 |

---

## 구현 경로

```
src/app/templates/          # Jinja2 SSR (dashboard, prediction, chatbot)
src/app/static/             # CSS, HTMX, Chart.js
GET /ui/                    # SSR 진입점
GET /api/v1/chatbot/stream  # SSE (HTMX hx-ext="sse" 연동)
```

---

## React SPA 처리

- `frontend/` 디렉토리는 삭제하지 않고 참조용으로 유지
- docker-compose의 `frontend` 서비스는 개발 편의용 optional
- 프로덕션 UI는 FastAPI SSR을 기본으로 한다

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

### React SPA

`frontend/` 는 본 ADR 대로 신규 개발을 중단하고 참조용으로 동결합니다.

---

## 남은 작업

1. 챗봇 탭 SSE 스트리밍을 `hx-ext="sse"` 로 전환 (현재는 원본과 동일한 fetch 방식)
2. 로그인/회원가입 POST 처리를 SSR 폼으로 연결 (현재 화면 렌더링만, 제출은 `/api/v1/accounts/*`)

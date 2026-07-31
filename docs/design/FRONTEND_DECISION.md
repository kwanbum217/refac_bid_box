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

## 후속 작업

1. `src/app/templates/base.html` HTMX 레이아웃
2. 챗봇 탭 SSE 스트리밍 (`hx-ext="sse"`)
3. Chart.js 대시보드 API 연동 (`/api/v1/bids`)

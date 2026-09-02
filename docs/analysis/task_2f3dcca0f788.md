# SSR 브라우저 E2E 범위 합의 조사 보고서 (Task task_2f3dcca0f788)

> **작성일**: 2026-09-02
> **Task ID**: `task_2f3dcca0f788`
> **역할**: investigator
> **상태**: 조사 완료 (succeeded)
> **상세 보고서 정본**: [`docs/analysis/ssr_e2e_scope_survey_20260902.md`](ssr_e2e_scope_survey_20260902.md)

---

## 1. 개요 및 요약

본 문서는 SSR(Jinja2) 12종 템플릿 화면 및 Vite React SPA 스캐폴드에 대한 브라우저 E2E 테스트 도입을 위해 수행된 범위 합의 자료입니다.

- **대상 화면 전수 분류**: SSR Jinja2 12개 템플릿(홈, 공고 목록/상세, 낙찰 목록/상세, 대시보드, 비교, 챗봇, 로그인, 회원가입, 로그아웃) 및 React SPA 3개 탭(대시보드, 예측 시뮬레이터, 실시간 SSE 챗봇) 분석 완료.
- **도구 후보 비교**: `pytest-playwright`(Python), `@playwright/test`(Node.js), `Cypress`, `Puppeteer` 4종 비교 결과, 기존 Python/uv/pytest 스택과의 통합성 및 세션 직접 주입 최적화 관점에서 `pytest-playwright`를 최종 권장안으로 도출.
- **공유 자원 경합 지점 도출**: 개발 Compose(포트 8000, 3306, 6379, 7700) 및 CI `mysql-ngram-integration`과의 포트/데이터 충돌 방지를 위한 격리 스키마/전용 포트/독립 CI Job 방안 수립.
- **4단계 분할안 수립**: Phase 1(기반 및 스모크) -> Phase 2(SSR 핵심 화면) -> Phase 3(SSE 챗봇 & React SPA) -> Phase 4(CI 통합)로 세분화.

상세 내용은 [`docs/analysis/ssr_e2e_scope_survey_20260902.md`](ssr_e2e_scope_survey_20260902.md)를 참조하십시오.

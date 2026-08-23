# HTMX 도입 이행 계획서

> **작성일**: 2026-08-23
> **버전**: v1.0
> **근거**: 본 문서 1장의 실측 집계 (별도 분석서 없음)
> **목표 아키텍처**: `FRONTEND_DECISION.md` - SSR + HTMX + Jinja2 (1차 UI)
> **범위**: 계획서 작성만. 실제 코드 이행 및 도입 여부 결정은 본 Task 범위 밖

---

## 1. 현황 요약 (분석서 발췌)

| 지표 | 현재 값 |
|------|---------|
| 템플릿 수 | 12개 (`src/app/templates/`) |
| jQuery 사용 템플릿 | 2개 (`bids/detail.html`, `chatbot/chat.html`) |
| jQuery 의존 코드 | 약 1,475줄 (detail 275줄 + chat 1,200줄) |
| 바닐라 JS 템플릿 | 7개 (약 700줄) |
| Chart.js 사용 | 3개 템플릿 (dashboard, compare, chatbot) |
| HTMX 현재 도입도 | **0%** (로드도, `hx-*` 속성도 없음) |
| SSR 진입점 | `src/app/api/ui.py` (전체 12개 라우트) |

**핵심 간극**: 목표 아키텍처(SSR + HTMX)는 **미도입 상태**. jQuery는 예측 폼과 챗봇 두 곳에만 국한됨.

---

## 2. 도입 대안 3안 비교

### 2.1 안 A: HTMX 전면 도입 (Full Adoption)

**범위**: jQuery 사용 2개 템플릿 + 바닐라 JS 폼/데이터 로드 5개 템플릿 완전 HTMX화. 챗봇도 HTMX `hx-sse` + 확장으로 이행 시도.

| 항목 | 내용 |
|------|------|
| **대상 템플릿** | 9개 (detail, login, signup, results, dashboard, compare, base, index\*, chatbot\*) |
| **신규 HTMX 엔드포인트** | 약 12개 (부분 렌더링용) |
| **서버 사이드 템플릿 분리** | 약 15개 프래그먼트 신규 생성 |
| **예상 공수** | **12~16 인일** (상세 내역 3절 참조) |
| **장점** | - 아키텍처 일관성 확보 (전체 SSR + HTMX)<br>- JS 번들 크기 최소화 (jQuery 제거, 바닐라 JS 대폭 감소)<br>- 하이퍼미디어 기반 상태 전이 명확화 |
| **단점** | - **챗봇 이행 리스크 극대**: SSE 토큰 스트리밍, 마크다운+차트 동적 렌더링, 자동화 상태 머신 구현 복잡도 급증<br>- `chatbot/chat.html` 1,200줄 → 서버 템플릿 파편화로 디버깅/유지보수 어려움<br>- Chart.js 캔버스 조작은 HTMX 범위 밖 → 결국 하이브리드 불가피<br>- 투자 대비 UX 개선 체감 낮음 (이미 fetch/SSE로 동작 중) |
| **되돌리기 비용** | **높음** (템플릿 파편화, 엔드포인트 증가, 챗봇 리라이팅 되돌리기 난이도 상) |

---

### 2.2 안 B: 부분 도입 - 예측 폼/인증/데이터 로드만 (Selective Adoption) **권고**

**범위**: HTMX 강점이 명확한 **폼 제출 → 부분 갱신**, **초기 데이터 로드** 패턴만 적용. 챗봇, 스와이프, 차트 렌더링은 현행 유지.

| 항목 | 내용 |
|------|------|
| **대상 템플릿** | 6개 (`bids/detail.html`, `accounts/login.html`, `accounts/signup.html`, `bids/results.html`, `bids/dashboard.html`, `bids/compare.html`) |
| **제외 템플릿** | `chatbot/chat.html` (SSE 스트리밍 완료), `index.html` (클라이언트 사이드 UX), `base.html` (테마/설정 - 바닐라 유지), `bids/list.html`, `bids/result_detail.html` (JS 없음) |
| **신규 HTMX 엔드포인트** | 6개 (예측 결과, 로그인/회원가입 폼 응답, 대시보드/비교 통계) |
| **서버 사이드 템플릿 분리** | 8개 프래그먼트 신규 생성 |
| **예상 공수** | **4~6 인일** (상세 내역 3절 참조) |
| **장점** | - **ROI 최대**: jQuery 2개 파일(1,475줄) 완전 제거, 바닐라 JS 폼 로직 HTMX로 통합<br>- 챗봇 리스크 **완전 차단** (검증된 SSE 스트리밍 유지)<br>- 점진적 도입으로 회귀 위험 최소화<br>- HTMX 학습 곡선 낮음 (폼/데이터 로드 패턴만) |
| **단점** | - 아키텍처 혼재 (HTMX + 바닐라 JS + SSE 공존)<br>- `base.html` 설정 모달 등 일부 UX는 바닐라 유지 |
| **되돌리기 비용** | **낮음** (독립적 프래그먼트/엔드포인트, feature flag로 비활성화 가능) |

---

### 2.3 안 C: ADR 개정 - jQuery 유지, HTMX 도입 보류 (Status Quo)

**범위**: 현행 유지. `FRONTEND_DECISION.md` 상태를 "목표 아키텍처 확정 / 구현 보류"에서 "목표 아키텍처 재검토 / jQuery·바닐라 JS 현행 유지"로 변경.

| 항목 | 내용 |
|------|------|
| **대상 템플릿** | 없음 (변경 없음) |
| **예상 공수** | **0 인일** (문서 수정만) |
| **장점** | - 즉시 비용 0<br>- 검증된 구현 유지 (예측 폼 jQuery, 챗봇 SSE 모두 동작 중)<br>- 리소스를 백엔드/ML 고도화에 집중 가능 |
| **단점** | - ADR과 구현 간 불일치 상태 지속<br>- 기술 부채: jQuery 3.7.1 CDN 의존 (보수 종료 임박)<br>- 향후 프론트엔드 확장 시 일관성 부족 |
| **되돌리기 비용** | **해당 없음** (현행 유지) |
| **장기 리스크** | jQuery 3.7.1은 2023년 5월 릴리스, 4.x 마이그레이션 경로 불확실. 2~3년 내 CDN 제공 중단 가능성 |

---

## 3. 권고안 (안 B) 상세 이행 계획

### 3.1 단계별 분해

| 단계 | 작업 내용 | 대상 | 공수 | 선행 조건 |
|------|-----------|------|------|-----------|
| **1단계: 기반 준비** | HTMX CDN 로드(`base.html`), 공통 에러 토스트 컴포넌트, `hx-boost` 기본 적용 | `base.html`, `bids/results.html` | 0.5일 | 없음 |
| **2단계: 인증 폼 HTMX화** | 로그인/회원가입 폼 `hx-post` + 서버 프래그먼트 응답 | `accounts/login.html`, `accounts/signup.html`, `ui.py` | 1일 | 1단계 |
| **3단계: 예측 폼 HTMX화** | 모델 선택→정보 표시, 예측 실행→결과 렌더링 전면 HTMX화 | `bids/detail.html`, `ui.py`, `predictions.py` | 1.5일 | 1단계 |
| **4단계: 데이터 로드 HTMX화** | 대시보드/비교분석 통계 카드 `hx-get` + `hx-trigger="load"` | `bids/dashboard.html`, `bids/compare.html`, `ui.py` | 1일 | 1단계 |
| **5단계: 검증 및 정리** | E2E 테스트, jQuery 제거 확인, 문서 동기화 | 전체 | 0.5일 | 2~4단계 |

**총 공수: 4.5일 (버퍼 포함 5~6일)**

---

### 3.2 단계별 상세 작업 내역

#### 1단계: 기반 준비 (0.5일)

| 작업 | 파일 | 변경 내용 |
|------|------|-----------|
| HTMX CDN 추가 | `base.html:15-17` 부근 | `<script src="https://unpkg.com/htmx.org@1.9.12" integrity="sha384-..."></script>` 추가 |
| 전역 `hx-boost` 적용 | `base.html` `<body>` | `<body hx-boost="true">`로 링크/폼 기본 AJAX화 (선택적) |
| 에러 토스트 컴포넌트 | `base.html` `extra_js` 블록 | `htmx:after-request` 이벤트 리스너로 4xx/5xx 토스트 표시 |
| 로딩 인디케이터 CSS | `base.html` style 블록 | `.htmx-indicator { opacity: 0; transition: opacity 200ms; } .htmx-request .htmx-indicator { opacity: 1; }` |
| `bids/results.html` 로딩 표시 | `results.html:158-163` | 기존 로딩 레이어에 `hx-indicator` 클래스 부여, `hx-boost`로 링크 자동 처리 |

**검증**: `bids/results.html` 페이지네이션/필터 링크 클릭 시 전체 리로드 없이 갱신, 로딩 스피너 표시

---

#### 2단계: 인증 폼 HTMX화 (1일)

| 작업 | 파일 | 변경 내용 |
|------|------|-----------|
| 로그인 폼 HTMX 적용 | `login.html:18-58` | `<form hx-post="/accounts/login/" hx-target="#login-form" hx-swap="outerHTML" hx-indicator="#login-spinner">` |
| 로그인 성공 시 리다이렉트 | `ui.py:425-491` | 성공 시 `HX-Redirect: /` 헤더 반환 (HTMX가 자동 처리) |
| 로그인 실패 시 폼 에러 반환 | `ui.py:445-456` | 401/403 시 폼 프래그먼트(`accounts/_login_form.html`) 반환 |
| 회원가입 폼 HTMX 적용 | `signup.html:18-138` | 동일 패턴 적용. `hx-target="#signup-form"` |
| 회원가입 성공/실패 분기 | `ui.py:353-403` | 성공 시 `HX-Redirect: /`, 실패 시 `_signup_form.html` 프래그먼트 |
| 프래그먼트 템플릿 생성 | `accounts/_login_form.html`, `accounts/_signup_form.html` | 폼 영역만 분리 (에러 표시 포함) |

**검증**: JS 비활성화 상태에서도 로그인/회원가입 동작. 성공 시 리다이렉트, 실패 시 인라인 에러 표시.

---

#### 3단계: 예측 폼 HTMX화 (1.5일) - **최대 효과 구간**

| 작업 | 파일 | 변경 내용 |
|------|------|-----------|
| 모델 목록 로드 HTMX화 | `detail.html:334-353` | `<select id="selected-model" hx-get="/predictions/models/" hx-trigger="load" hx-target="#model-select">` |
| 모델 정보 패널 프래그먼트 | `detail.html:135-139` | `#model-info-panel` → `bids/_model_info.html` 분리. `hx-get` + `hx-trigger="change from:#selected-model"` |
| 입력 포맷팅 바닐라 헬퍼 | `detail.html:477-480` | 5줄 바닐라 함수로 대체 (jQuery 의존 제거) |
| 예측 실행 버튼 HTMX화 | `detail.html:151-154` | `<button id="btn-predict" hx-post="/predictions/predict/" hx-vals='js:{bid_id: {{ bid.id }}, user_price: getPrice(), model: $("#selected-model").val()}' hx-target="#prediction-result" hx-swap="outerHTML" hx-indicator="#predict-spinner" hx-disabled-elt="#btn-predict">` |
| 예측 결과 프래그먼트 | `detail.html:166-246` | `#prediction-result` 전체 → `bids/_prediction_result.html` 분리. 서버가 HTML 반환 |
| 예측 엔드포인트 분기 | `predictions.py` | `Accept: text/html` 헤더 시 프래그먼트 반환, 기본은 JSON 유지 (API 호환) |
| 에러 처리 | `detail.html` | `hx-on::after-request="if(event.detail.xhr.status >= 400) showToast(event.detail.xhr.responseText)"` |

**검증**: 모델 변경 시 정보 패널 갱신, 예측 실행 시 로딩→결과 렌더링, 에러 시 토스트. jQuery 완전 제거 확인.

---

#### 4단계: 데이터 로드 HTMX화 (1일)

| 작업 | 파일 | 변경 내용 |
|------|------|-----------|
| 대시보드 통계 카드 | `dashboard.html:34-88` | 각 카드 `hx-get="/bids/api_stats_card/" hx-trigger="load" hx-target="#stat-{count,amount,rate}" hx-swap="innerHTML"` |
| 대시보드 차트 데이터 | `dashboard.html:197-222` | `loadStats()` 유지 (Chart.js 렌더링 필요). 통계 카드만 HTMX화 |
| 비교분석 통계 카드 | `compare.html:45-100` | 동일 패턴: `hx-get="/bids/api_compare_card/" hx-trigger="load"` |
| 비교분석 차트 데이터 | `compare.html:181-223` | `loadCompareData()` 유지. 통계 카드만 HTMX화 |
| 서버 엔드포인트 | `ui.py` | `/bids/api_stats_card/`, `/bids/api_compare_card/` 신규. JSON + HTML 프래그먼트 분기 |

**검증**: 초기 로드 시 통계 카드 비동기 채워짐. 차트는 기존 fetch 유지.

---

#### 5단계: 검증 및 정리 (0.5일)

| 작업 | 내용 |
|------|------|
| E2E 시나리오 테스트 | 로그인→공고 탐색→상세→예측→대시보드→비교분석→로그아웃 플로우 수동 검증 |
| jQuery 제거 확인 | `grep -r "jquery" src/app/templates/` → 0건 확인 |
| 콘솔 에러 확인 | 브라우저 개발자 도구 콘솔 에러 0건 |
| `FRONTEND_DECISION.md` 업데이트 | 현재 구현 상태 "HTMX 부분 도입 완료 (예측/인증/데이터 로드)"로 갱신 |
| `CURRENT_STATE.md` 동기화 | 프론트엔드 스택 현황 업데이트 |

---

### 3.3 서버 사이드 변경 상세 (신규 엔드포인트/프래그먼트)

| 엔드포인트 | 메서드 | 용도 | 반환 타입 분기 |
|------------|--------|------|----------------|
| `/predictions/models/` | GET | 모델 목록 드롭다운 옵션 | HTML (`<option>...`) |
| `/predictions/model_info/` | GET | 모델 정보 패널 | HTML (프래그먼트) |
| `/predictions/predict/` | POST | 예측 실행 | HTML (결과 카드) / JSON (API) |
| `/accounts/login/` | POST | 로그인 제출 | HTML (폼+에러) / `HX-Redirect` |
| `/accounts/signup/` | POST | 회원가입 제출 | HTML (폼+에러) / `HX-Redirect` |
| `/bids/api_stats_card/` | GET | 대시보드 통계 카드 4개 | HTML (카드 innerHTML) / JSON |
| `/bids/api_compare_card/` | GET | 비교분석 통계 카드 5개 | HTML (카드 innerHTML) / JSON |

**프래그먼트 템플릿 신규 생성 (8개)**:
- `accounts/_login_form.html`
- `accounts/_signup_form.html`
- `bids/_model_options.html`
- `bids/_model_info.html`
- `bids/_prediction_result.html`
- `bids/_stat_card_count.html`
- `bids/_stat_card_amount.html`
- `bids/_stat_card_rate.html`
- `bids/_stat_card_status.html`
- `bids/_compare_card_*.html` (5개)

---

## 4. 리스크 및 완화 방안

| 리스크 | 확률 | 영향 | 완화 방안 |
|--------|------|------|-----------|
| HTMX 버전 호환성 (CDN) | 낮음 | 중간 | `integrity` 속성으로 버전 고정. 1.9.12 LTS 사용 |
| 서버 템플릿 파편화로 인한 유지보수 부담 | 중간 | 중간 | 프래그먼트 네이밍 컨벤션(`_` prefix), 폴더 구조(`templates/partials/`) 정립 |
| 기존 API 클라이언트(챗봇 등) 호환성 깨짐 | 낮음 | 높음 | `Accept` 헤더 기반 분기로 JSON API 유지. `predictions.py` 수정 시 주의 |
| `hx-boost` 전역 적용 시 부작용 | 중간 | 낮음 | 전역 미적용. 명시적 `hx-get`/`hx-post`만 사용 |
| CSRF/보안 이슈 | 낮음 | 높음 | 현재 세션 쿠키 + SameSite=Lax로 충분. HTMX는 쿠키 자동 포함 |

---

## 5. 되돌리기 전략 (Rollback Plan)

안 B는 **기능 단위 독립 배포** 가능하도록 설계:

1. **Feature Flag 방식**: `settings.HTMX_ENABLED` 토글로 각 단계별 활성화/비활성화
2. **템플릿 조건부 렌더링**: `{% if HTMX_ENABLED %} hx-* 속성 {% endif %}` 패턴
3. **단계별 롤백**: 2단계(인증) 문제 시 → `base.html`에서 HTMX CDN 제거 + 템플릿 원복만으로 10분 내 복구
4. **DB/스키마 변경 없음**: 데이터 무손실 원칙(G1) 완전 준수

---

## 6. 의사결정 가이드

| 판단 기준 | 안 A (전면) | 안 B (부분)  | 안 C (보류) |
|-----------|-------------|----------------|-------------|
| **즉시 ROI** | 낮음 | **높음** | 없음 |
| **기술 리스크** | 높음 (챗봇) | **낮음** | 없음 |
| **유지보수성** | 장기적 개선 | **단기적 개선** | 현행 유지 |
| **jQuery 제거** | 완전 | **완전 (대상 영역)** | 미제거 |
| **챗봇 영향** | **대수술 필요** | **영향 없음** | 영향 없음 |
| **예상 공수** | 12~16일 | **4~6일** | 0일 |
| **되돌리기 비용** | 높음 | **낮음** | 해당 없음 |

---

## 7. 권고 및 결정 요청

### 권고안: **안 B (부분 도입 - 예측 폼/인증/데이터 로드만)**

**근거**:
1. **투자 대비 효과 최대**: jQuery 완전 제거(1,475줄), 폼/데이터 로드 패턴에서 HTMX 강점 극대화
2. **리스크 최소화**: 검증된 챗봇 SSE 스트리밍(1,200줄) 건드리지 않음. Chart.js, 스와이프 UX 유지
3. **점진적 검증 가능**: 5단계로 나누어 각 단계 검증 후 진행. 문제 시 해당 단계만 롤백
4. **아키텍처 일관성 부분 확보**: 신규 폼/인터랙션은 HTMX 패턴으로 통일. 레거시 jQuery 완전 퇴출

### 결정 필요 사항

> **이 계획서는 근거 문서입니다. 도입 여부 최종 결정은 사용자(PO) 몫입니다.**

다음 중 하나를 선택해 주십시오:
1. **안 B 진행** → 상세 이행 계획대로 구현 착수 (별도 Task 분할 권장)
2. **안 A 진행** → 챗봇 포함 전면 리라이팅. 별도 대규모 Task 필요 (공수 3배, 리스크 고)
3. **안 C 채택** → `FRONTEND_DECISION.md` 상태를 "구현 보류/재검토"로 변경. 문서만 수정
4. **수정 후 재검토** → 범위/공수/대안 조정 후 재논의

---

## 8. 부록: 파일별 변경 영향도 요약표

| 파일 | 안 A | 안 B (권고) | 안 C |
|------|------|-------------|------|
| `base.html` | HTMX 로드, `hx-boost`, 토스트 | HTMX 로드, 토스트 | 변경 없음 |
| `bids/detail.html` | 전체 HTMX화 (~275줄→50줄) | **예측 폼만 HTMX화** (~275줄→50줄) | 변경 없음 |
| `chatbot/chat.html` | HTMX `hx-sse` + 확장 시도 | **제외 (현행 유지)** | 변경 없음 |
| `accounts/login.html` | HTMX화 | **HTMX화** | 변경 없음 |
| `accounts/signup.html` | HTMX화 | **HTMX화** | 변경 없음 |
| `bids/results.html` | `hx-boost` 전면 | **`hx-boost` + 로딩** | 변경 없음 |
| `bids/dashboard.html` | 데이터 로드 HTMX화 | **통계 카드만 HTMX화** | 변경 없음 |
| `bids/compare.html` | 데이터 로드 HTMX화 | **통계 카드만 HTMX화** | 변경 없음 |
| `index.html` | `hx-boost` 적용 | **제외 (현행 유지)** | 변경 없음 |
| `src/app/api/ui.py` | 12개 엔드포인트 추가 | **6개 엔드포인트 추가** | 변경 없음 |
| `src/app/api/v1/predictions.py` | HTML 분기 추가 | **HTML 분기 추가** | 변경 없음 |

---

**작성 완료**. 이 문서는 `docs/design/htmx_migration_plan_20260823.md`에 저장됩니다. 실제 이행 착수 시 별도 Task로 분할하여 진행하십시오.

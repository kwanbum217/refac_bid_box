# SSR 브라우저 E2E 테스트 운영 가이드

> **작성일**: 2026-09-03
> **수정일**: 2026-09-03
> **버전**: v1.0.0
> **단일 진실 원천(SSOT)**: 본 문서는 `refac_bid_box`의 Playwright 기반 브라우저 E2E 테스트 운영 지침서입니다.

---

## 1. 개요 및 목적

본 가이드는 `refac_bid_box`의 서버 사이드 렌더링(SSR Jinja2) 화면 및 프론트엔드 인터랙션을 실제 브라우저 환경에서 검증하기 위한 E2E 테스트 운영 기준을 정의합니다.

### 1.1 핵심 설계 원칙
1. **G1 데이터 무손실**: E2E 테스트 실행 중 실제 운영 및 개발 MySQL DB(`procurement`)에 어떠한 데이터 쓰기/오염도 발생하지 않도록 격리합니다.
2. **G2 크로스 플랫폼**: macOS, Linux, Windows 환경에서 동일한 도구 체인(`pytest-playwright`)으로 동작합니다.
3. **독립된 포트 및 프로세스 생명주기**: 테스트가 자체적으로 동적 포트를 할당하여 Uvicorn 서버를 백그라운드에서 구동하고, 테스트 완료 시 정상 종료(graceful shutdown)하여 자원 누수를 차단합니다.
4. **브라우저 부재 시 안전한 Skip**: 브라우저 바이너리가 설치되지 않은 환경(예: 경량 CI 러너, 초기 클론 환경)에서는 테스트가 실패(`FAILED`)하지 않고 `SKIPPED` 처리되어 전체 테스트 게이트를 차단하지 않습니다.

---

## 2. 사전 준비 및 설치

### 2.1 의존성 설치
본 저장소는 Python `uv` 패키지 관리자를 사용합니다. E2E 테스트 도구인 `pytest-playwright`는 `dev` 의존성 그룹에 포함되어 있습니다.

```bash
# 전체 의존성 동기화
uv sync --all-groups
```

### 2.2 Chromium 브라우저 바이너리 설치
본 프로젝트는 속도 및 리소스 최적화를 위해 **Headless Chromium 단일 브라우저**만 사용합니다. Firefox, WebKit 등 불필요한 브라우저는 설치하지 않습니다.

```bash
# Headless Chromium 브라우저 바이너리만 설치
uv run playwright install chromium
```

---

## 3. 테스트 구성 및 생명주기

### 3.1 디렉터리 구조

| 경로 | 역할 |
| --- | --- |
| `tests/e2e/__init__.py` | E2E 테스트 패키지 초기화 |
| `tests/e2e/conftest.py` | 백그라운드 Uvicorn 서버, 브라우저 스킵 판정, 공통 픽스처 |
| `tests/e2e/test_smoke.py` | 로그인 화면 DOM 렌더링 검증 기본 스모크 테스트 |

### 3.2 Uvicorn 백그라운드 서버 픽스처 (`live_server_url`)
- **동적 포트 바인딩**: `find_free_port()`를 통해 OS에서 사용 가능한 유휴 포트(예: 54321)를 동적으로 할당받습니다. 기존 개발용 `8000` 포트 점유와 무관하게 동작합니다.
- **헬스체크 대기**: 서버 기동 후 `http://127.0.0.1:{port}/accounts/login/` 경로로 최대 10초간 폴링하여 HTTP 200 응답이 확인된 후 테스트를 진행합니다.
- **정상 종료 보장**: 테스트 세션 종료 시 `server.should_exit = True` 신호를 전달하고 스레드를 join하여 포트 및 프로세스 누수를 방지합니다.

### 3.3 브라우저 부재 시 Skip 판정 메커니즘
`tests/e2e/conftest.py`의 `pytest_runtest_setup` 훅은 테스트 실행 전 Chromium 브라우저 바이너리가 실제로 로드 및 실행 가능한지 검사합니다.

- 바이너리가 감지되지 않거나 실행 불가능한 경우:
  - `pytest.skip("Playwright Chromium 브라우저 바이너리가 설치되어 있지 않아 E2E 테스트를 건너뜁니다.")`를 호출합니다.
  - 테스트 결과는 `SKIPPED`로 기록되며 exit code 0으로 정상 완료됩니다.

---

## 4. 테스트 실행 방법

### 4.1 Makefile 타깃 실행 (권장)
```bash
make test-e2e
```

### 4.2 Pytest 직접 실행
```bash
# E2E 마커 필터링 실행
uv run pytest tests/e2e/ -m e2e -v

# 전체 테스트 슈트 실행 (E2E 포함)
uv run pytest tests/ -q -m "not data_assets"
```

---

## 5. 단계별 로드맵 (Phase 1 ~ 4)

| 단계 | 목표 | 주요 대상 파일 | 상태 |
| --- | --- | --- | :---: |
| **Phase 1** | E2E 프레임워크 기반 구축 및 스모크 검증 | `tests/e2e/conftest.py`, `tests/e2e/test_smoke.py` | **완료** |
| **Phase 2** | SSR Jinja2 인증/공고/낙찰 핵심 시나리오 | `tests/e2e/test_ssr_auth.py`, `tests/e2e/test_ssr_bids.py` 등 | 예정 |
| **Phase 3** | SSR 챗봇 실시간 SSE 스트리밍 & React SPA | `tests/e2e/test_ssr_chatbot_stream.py`, `tests/e2e/test_react_spa.py` | 예정 |
| **Phase 4** | CI 워크플로 통합 및 아티팩트 자동화 | `.github/workflows/ci.yml`, `docs/ops/ci_contract.md` | 예정 |

---

## 6. 문제 해결 (Troubleshooting)

### Q1. 브라우저가 실행되지 않고 `SKIPPED` 처리됩니다.
- 원인: Playwright Chromium 바이너리가 설치되지 않았습니다.
- 조치: `uv run playwright install chromium`을 실행하여 브라우저를 다운로드하십시오.

### Q2. 포트 충돌이 발생합니까?
- 아니오. `tests/e2e/conftest.py`는 매 실행마다 비어 있는 포트를 동적으로 찾아 Uvicorn을 바인딩하므로 로컬 개발 서버(8000)가 기동 중이어도 충돌하지 않습니다.

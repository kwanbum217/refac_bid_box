# Task Report: SSR 브라우저 E2E 기반 구축 (Phase 1)

> **Task ID**: `task_07bcd5cf94e2`
> **Run ID**: `run_971584ddb4a0`
> **작성일**: 2026-09-03
> **작성자**: Builder Agent
> **상태**: 완료 (Succeeded)

---

## 1. 개요 및 목적

본 작업은 `refac_bid_box`의 SSR(Jinja2) 브라우저 E2E 테스트 도입 계획(Phase 1)에 따라 `pytest-playwright`를 도입하고, Uvicorn 백그라운드 서버 구동 픽스처 및 브라우저 컨텍스트 픽스처를 구축하며, 비인증 로그인 화면 렌더링을 검증하는 스모크 테스트를 통과시키는 것을 목표로 수행되었습니다.

---

## 2. 수행 내역

### 2.1 의존성 및 설정 구성
- `pyproject.toml`의 `[dependency-groups] dev`에 `pytest-playwright>=0.5.0` 추가
- `uv lock` 및 `uv sync --all-groups`를 통해 `uv.lock` 갱신 및 Playwright 패키지 동기화
- `pyproject.toml`의 `[tool.pytest.ini_options].markers`에 `e2e` 마커 등록하여 마커 경고 차단

### 2.2 E2E 테스트 인프라 및 픽스처 구축 (`tests/e2e/conftest.py`)
- **동적 포트 할당 (`find_free_port`)**: `socket.socket`을 통해 유휴 포트를 동적으로 획득하여 기존 개발 서버(8000) 및 타 서비스와의 포트 충돌 방지
- **Uvicorn 백그라운드 서버 (`live_server_url`)**: 데몬 스레드에서 Uvicorn 인스턴스를 구동하고, `http://127.0.0.1:{port}/accounts/login/` 헬스체크 성공 시까지 대기. 세션 종료 시 `server.should_exit = True` 신호 전달 및 스레드 정상 종료 보장
- **브라우저 부재 시 안전한 Skip 처리 (`pytest_runtest_setup`)**: 별도 스레드에서 Chromium 바이너리 기동을 사전에 탐색하여, 바이너리가 없는 환경에서는 실패가 아닌 `SKIPPED`로 처리

### 2.3 스모크 테스트 구현 (`tests/e2e/test_smoke.py`)
- 비인증 상태에서 `/accounts/login/` 페이지 방문
- 페이지 타이틀(`로그인 - BIDBOX Intelligence`), 메인 헤딩(`계정에 로그인하세요`), 사용자 아이디 필드(`#id_username`), 비밀번호 필드(`#id_password`), 로그인 버튼 가시성 DOM 검증

### 2.4 빌드 및 운영 문서화
- `Makefile`에 `test-e2e` 타깃 추가 (`.PHONY` 및 `help` 포함)
- `docs/ops/e2e_testing_guide.md` 작성 (설치, 아키텍처, 실행, 트러블슈팅 안내)

---

## 3. 검증 결과

### 3.1 브라우저 설치 환경 E2E 스모크 테스트 실행
- **명령**: `uv run pytest tests/e2e/test_smoke.py -v`
- **결과**: `1 passed in 1.27s` (Exit Code 0)

### 3.2 브라우저 미설치 환경 Skip 검증
- **명령**: `PLAYWRIGHT_BROWSERS_PATH=/tmp/no_browsers uv run pytest tests/e2e/test_smoke.py -v -rs`
- **결과**: `1 skipped in 0.17s` (Exit Code 0)
- **사유**: `Playwright Chromium 브라우저 바이너리가 설치되어 있지 않아 E2E 테스트를 건너뜁니다.`

### 3.3 Makefile 타깃 실행
- **명령**: `make test-e2e`
- **결과**: `1 passed in 1.71s` (Exit Code 0)

### 3.4 다중 에이전트 규칙 검증
- **명령**: `python3 scripts/validate_agent_rules.py --quiet`
- **결과**: `18/18 건 검증 통과` (Exit Code 0)

### 3.5 린터 및 포맷 검증
- **명령**: `uv run ruff check tests/e2e/`
- **결과**: `All checks passed!` (Exit Code 0)

---

## 4. 리뷰 체크리스트 대조

| 항목 ID | 점검 내용 | 결함 여부 | 검증 결과 |
| --- | --- | :---: | --- |
| `fails_without_browser` | 브라우저 부재 시 실패하지 않고 skip 되는가 | **결함 없음 (No)** | `PLAYWRIGHT_BROWSERS_PATH` 분기 시 `1 skipped` 확인 |
| `hardcoded_port` | 포트가 하드코딩되지 않고 동적으로 할당되는가 | **결함 없음 (No)** | `find_free_port()`를 통한 동적 소켓 바인딩 |
| `leaks_process` | 테스트 종료 후 백그라운드 서버 프로세스가 남지 않는가 | **결함 없음 (No)** | `server.should_exit = True` 및 스레드 join으로 정상 종료 |
| `touches_real_db` | 실제 운영/개발 DB에 쓰기가 발생하는가 | **결함 없음 (No)** | 비인증 로그인 템플릿 렌더링 스모크로 DB 쓰기 전무 |
| `extra_browsers` | Chromium 외 브라우저를 설치하는가 | **결함 없음 (No)** | `chromium` 단일 브라우저만 설치 및 설정 |
| `scope_beyond_phase1` | Phase 2 이후 범위를 침범했는가 | **결함 없음 (No)** | Phase 1 범위(기반 + 로그인 스모크)만 구현 |
| `new_dependency_extra` | 승인되지 않은 외부 라이브러리를 추가했는가 | **결함 없음 (No)** | 사전 승인된 `pytest-playwright`만 추가 |
| `unregistered_marker` | pyproject.toml에 마커가 등록되었는가 | **결함 없음 (No)** | `e2e` 마커 등록 완료 |
| `scope_creep` | 허용 범위 밖 파일을 수정했는가 | **결함 없음 (No)** | Capsule의 `allowed_write_files` 범위 내에서만 수정 |

---

## 5. 변경 파일 목록

- `pyproject.toml`
- `uv.lock`
- `tests/e2e/__init__.py`
- `tests/e2e/conftest.py`
- `tests/e2e/test_smoke.py`
- `Makefile`
- `docs/ops/e2e_testing_guide.md`
- `docs/analysis/task_07bcd5cf94e2.md`

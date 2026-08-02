# 크로스 플랫폼 호환 가이드 (macOS / Windows)

> **작성일**: 2026-07-31
> **상태**: 설계
> **관련**: [`docs/design/REFACTORING_DESIGN.md`](../design/REFACTORING_DESIGN.md) 6장

---

## 1. 목적

macOS와 Windows에서 **동일한 환경**으로 개발하고 실행하기 위한 가이드입니다. 기존 프로젝트의 플랫폼 종속性问题를 해결합니다.

---

## 2. 기존 플랫폼 종속 문제와 해결

| 문제 | 원인 | 해결 |
| --- | --- | --- |
| `mysqlclient` 빌드 실패 | macOS에서 C 확장 빌드 의존성 | Docker MySQL + PyMySQL(순수 파이썬) |
| `hc.exe` Windows 바이너리 | Harness CLI Windows 전용 | Git 제거, CI 다운로드 또는 REST API |
| `.ps1` 스케줄러 | Windows 작업 스케줄러 | Celery Beat (크로스플랫폼) |
| 환경 차이 | 로컬 직접 설치 | Docker + Makefile 표준화 |
| 경로 구분자 | `\` vs `/` | `pathlib.Path` 전면 사용 |
| 인코딩 | 시스템 기본 인코딩 차이 | UTF-8 강제 |

---

## 3. 표준 실행 환경 (Docker)

### 3.1 전체 스택 (docker-compose)

```yaml
# docker-compose.yml
services:
  mysql:     # MySQL 8 — macOS/Windows 동일
    image: mysql:8
    environment:
      MYSQL_DATABASE: procurement
      MYSQL_ROOT_PASSWORD: ${DB_PASSWORD}
    ports: ["3306:3306"]
  redis:     # 캐시 + 브로커
    image: redis:7
    ports: ["6379:6379"]
  app:       # FastAPI / Django
    build: .
    depends_on: [mysql, redis]
  worker:    # Celery / Arq
    build: .
    command: celery -A src.tasks worker -l info
    depends_on: [redis]
```

### 3.2 실행 명령

| 작업 | 명령 |
| --- | --- |
| 전체 스택 기동 | `make up` 또는 `docker compose up -d` |
| DB + Redis만 | `make db-up` |
| 개발 서버 | `make dev` |
| 마이그레이션 | `make migrate` |
| 테스트 | `make test` |
| 중지 | `make down` |

---

## 4. Makefile 진입점

macOS와 Windows(Git Bash) 모두에서 동작하는 단일 진입점입니다.

```makefile
.PHONY: setup dev test migrate db-up up down lint

setup:
	uv sync

db-up:
	docker compose up -d mysql redis

dev:
	uvicorn src.app.main:app --reload --port 8000

migrate:
	alembic upgrade head

test:
	pytest -q

up:
	docker compose up -d

down:
	docker compose down
```

> Windows 네이티브 `make`가 없는 경우 **Taskfile.yml + go-task** 또는 **just**를 대안으로 사용합니다 (단일 바이너리, 크로스플랫폼).

---

## 5. 인코딩 가드

- 모든 파일 입출력에 `encoding="utf-8"` 명시.
- CSV/parquet 로드 시 인코딩·구분자 자동 감지 로직 유지.
- DB 연결 charset `utf8mb4` 고정.

---

## 6. CI 크로스 플랫폼 검증

GitHub Actions에서 macOS/Windows 매트릭스 테스트를 수행합니다.

```yaml
# .github/workflows/ci.yml (개념)
strategy:
  matrix:
    os: [ubuntu-latest, macos-latest, windows-latest]
runs-on: ${{ matrix.os }}
steps:
  - uses: actions/checkout@v4
  - uses: astral-sh/setup-uv@v3
  - run: uv sync
  - run: uv run pytest -q
```

---

## 7. 체크리스트

- [x] Dockerfile 작성 (파이썬 슬림 이미지)
- [x] docker-compose.yml 작성 (mysql, redis, app, worker)
- [x] Makefile 작성
- [x] macOS에서 `make up` 실행 검증
- [x] Windows에서 `uv run pytest -q` 실행 검증 (GitHub Actions windows-latest)
- [x] CI 매트릭스 테스트 통과 (macOS/Windows)

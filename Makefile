.PHONY: help setup import-assets dev dev-fe db-up up down logs build lint format security typecheck quality observability-up observability-down check-rules sync-skills lint-workflows secret-scan check-docs dup-check frontend-deps frontend-check css-check check-tests check-all migrate-verify migrate-current migrate-up migrate-stamp migrate-check model-verify rebuild-rankings rebuild-institution-stats benchmark test test-data-assets test-e2e backup backup-dry-run restore-dry-run backup-verify backup-list render-alertmanager-secret

ifeq ($(OS),Windows_NT)
VENV_PYTHON := .venv/Scripts/python.exe
else
VENV_PYTHON := .venv/bin/python
endif

PYTHON ?= $(if $(wildcard $(VENV_PYTHON)),$(VENV_PYTHON),python3)
UV ?= uv
GITLEAKS ?= gitleaks

help:
	@echo "refac_bid_box 개발 및 품질 검증 타깃:"
	@echo "  make setup          - uv 의존성 동기화"
	@echo "  make import-assets  - 원본 bid_box의 모델·ChromaDB 자산 이전 및 체크섬 기록"
	@echo "  make dev            - FastAPI 개발 서버 실행"
	@echo "  make db-up          - MySQL+Redis만 배경 실행"
	@echo "  make up             - 전체 스택 컨테이너 배경 실행 (FastAPI+Arq+MySQL+Redis)"
	@echo "  make build          - 컨테이너 이미지 빌드"
	@echo "  make observability-up   - 관측성 스택(OTel, Tempo, Prometheus, Grafana) 기동"
	@echo "  make observability-down - 관측성 스택 정지"
	@echo "  make down           - 컨테이너 중지 및 네트워크 정리"
	@echo "  make logs           - 컨테이너 실시간 로그 확인"
	@echo "  make lint           - Ruff 린트 및 포맷 검사 (확인 전용)"
	@echo "  make format         - Ruff 포맷팅 및 자동 수정 실행"
	@echo "  make security       - Bandit 보안 스캔"
	@echo "  make typecheck      - mypy 타입 검사 (릴리스 게이트 포함)"
	@echo "  make quality        - typecheck & jscpd 중복 코드 검사"
	@echo "  make check-rules    - 다중 에이전트 규칙 정합성 검증"
	@echo "  make sync-skills    - 스킬 정본을 CLI 별 미러로 복제"
	@echo "  make lint-workflows - GitHub Actions 워크플로우 검사 (actionlint)"
	@echo "  make check-all      - CI 필수 검사와 같은 전체 로컬 검증"
	@echo "  make secret-scan    - gitleaks 시크릿 유출 검사 (작업 트리 + 전체 이력)"
	@echo "  make check-docs     - 문서 상대 링크 검사"
	@echo "  make dup-check      - jscpd 중복 코드 검사"
	@echo "  make frontend-deps  - 프런트엔드 의존성 설치 (npm ci)"
	@echo "  make frontend-check - 프런트엔드 타입 검사, 단위 시험, 빌드"
	@echo "  make css-check      - Tailwind CSS 재생성 드리프트 검사"
	@echo "  make check-tests    - 커버리지 하한을 포함한 Pytest 전량 실행"
	@echo "  make migrate-verify - 데이터 보존 무손실 실측 검증"
	@echo "  make migrate-current - Alembic 적용 상태 읽기 전용 확인"
	@echo "  make migrate-up     - Alembic 스키마 적용 (신규 환경 전용)"
	@echo "  make migrate-stamp  - 기존 Django DB 에 기준선 버전만 기록 (DDL 미실행)"
	@echo "  make migrate-check  - 모델과 실제 스키마 차이 점검 (읽기 전용)"
	@echo "  make model-verify   - 모델 직렬화 버전과 서빙 특징 호환성 검증"
	@echo "  make rebuild-rankings - 상위 N 집계 스냅샷 재생성"
	@echo "  make rebuild-institution-stats - 기관별 낙찰률 사전 집계 재생성"
	@echo "  make render-alertmanager-secret - .env 의 ALERTMANAGER_SLACK_WEBHOOK_URL 로 비밀 파일 생성"
	@echo "  make backup         - 운영 DB·ChromaDB·모델 통합 백업 실행"
	@echo "  make backup-dry-run - 통합 백업 사전 점검 (dry-run)"
	@echo "  make restore-dry-run - 통합 복원 대상 사전 점검 (dry-run)"
	@echo "  make backup-verify  - 최신/지정 백업 스냅샷 무결성 검증"
	@echo "  make backup-list    - 등록된 백업 스냅샷 목록 조회"
	@echo "  make benchmark      - P95 레이턴시 벤치마크 (서버 기동 필요)"
	@echo "  make test           - 외부 데이터 자산 없이 Pytest 단위/통합/E2E 테스트 실행"
	@echo "  make test-data-assets - 모델·ChromaDB가 있는 환경의 G1 자산 테스트 실행"
	@echo "  make test-e2e       - Playwright 기반 SSR 브라우저 E2E 테스트 실행"
	@echo "  make dev-fe         - 프론트엔드 (Vite + React 19) 개발 서버 구동"

setup:
	$(UV) sync --all-groups

import-assets:
	$(PYTHON) scripts/import_data_assets.py

dev:
	$(PYTHON) -m uvicorn src.app.main:app --reload --port 8000

db-up:
	docker compose up -d db redis

up:
	docker compose up --build -d

build:
	docker compose build

down:
	docker compose down

observability-up:
	docker compose --profile observability up -d otel-collector tempo prometheus grafana

observability-down:
	docker compose --profile observability stop otel-collector tempo prometheus grafana

logs:
	docker compose logs -f

dev-fe:
	cd frontend && npm run dev

migrate-verify:
	$(PYTHON) scripts/verify_migration.py

migrate-current:
	$(PYTHON) -m alembic current

# 이미 Django 로 구축된 DB 에는 절대 쓰지 마십시오. migrate-stamp 를 쓰십시오.
migrate-up:
	$(PYTHON) -m alembic upgrade head

migrate-stamp:
	$(PYTHON) -m alembic stamp head

migrate-check:
	$(PYTHON) scripts/check_schema_drift.py

model-verify:
	$(PYTHON) scripts/verify_model_compatibility.py

rebuild-rankings:
	$(PYTHON) scripts/rebuild_ranking_snapshots.py

rebuild-institution-stats:
	$(PYTHON) scripts/rebuild_institution_stats.py

render-alertmanager-secret:
	$(PYTHON) scripts/render_alertmanager_secret.py

# 기동 중인 서버에 HTTP 로 붙습니다. 먼저 uvicorn 을 띄우십시오.
benchmark:
	$(PYTHON) scripts/benchmark_latency.py

backup-dry-run:
	$(PYTHON) scripts/backup_recovery.py backup

backup:
	$(PYTHON) scripts/backup_recovery.py backup --execute

restore-dry-run:
	$(PYTHON) scripts/backup_recovery.py restore --snapshot-dir $$(ls -td data/backups/snapshots/snapshot_* 2>/dev/null | head -n 1)

backup-verify:
	$(PYTHON) scripts/backup_recovery.py verify --snapshot-dir $$(ls -td data/backups/snapshots/snapshot_* 2>/dev/null | head -n 1)

backup-list:
	$(PYTHON) scripts/backup_recovery.py list



lint:
	$(PYTHON) -m ruff check .
	$(PYTHON) -m ruff format --check .
	npm --prefix frontend run lint

format:
	$(PYTHON) -m ruff check . --fix
	$(PYTHON) -m ruff format .

security:
	$(PYTHON) -m bandit -c pyproject.toml -r src/ scripts/

typecheck:
	$(PYTHON) -m mypy src/

quality: typecheck dup-check

check-rules:
	$(PYTHON) scripts/validate_agent_rules.py

sync-skills:
	$(PYTHON) scripts/sync_skill_mirrors.py

lint-workflows:
	$(UV) run actionlint

# CI(.github/workflows/ci.yml)의 lint-and-validate 잡과 cross-platform-test 잡 판정을
# 로컬에서 같은 명령으로 수행합니다. 로컬 초록 뒤 CI 가 붉어지는 차이를 없앱니다.
# 로컬에서 실행할 수 없어 제외한 CI 게이트와 사유:
#   supply-chain        - Docker 이미지 빌드, Trivy, 네트워크 의존 취약점 스캔
#   e2e-browser-test    - Playwright 브라우저 설치 필요 (make test-e2e 로 별도 실행)
#   docker-build        - Docker 데몬 필요
#   mysql-ngram-integration, g1-schema-signature - MySQL 서비스 컨테이너 필요
#   pytest 경고 예산    - CI 가 Python 3.12 러너 한 곳에서만 판정하며 로컬 인터프리터별 경고 수가 다릅니다
secret-scan:
	@command -v $(GITLEAKS) >/dev/null 2>&1 || { echo "gitleaks 가 설치되어 있지 않습니다. macOS: brew install gitleaks, Windows: scoop install gitleaks"; exit 1; }
	$(GITLEAKS) dir --no-banner --redact --config .gitleaks.toml .
	$(GITLEAKS) git --no-banner --redact --config .gitleaks.toml .

check-docs:
	$(PYTHON) scripts/validate_doc_links.py --quiet

dup-check:
	npx --yes jscpd@5.3.2 --config .jscpd.json --reporters console

frontend-deps:
	cd frontend && npm ci

# 프런트엔드 린트는 lint 대상이 같은 명령을 수행하므로 여기서 중복 실행하지 않습니다.
frontend-check: frontend-deps
	cd frontend && npx tsc --noEmit
	cd frontend && npm run test
	cd frontend && npm run build

# 커밋된 tailwind.css 가 루트 설정과 입력 CSS 로부터 정확히 재생성되는지 확인합니다.
css-check:
	npm ci
	npm run build:css
	git diff --exit-code -- src/app/static/css/tailwind.css

# CI cross-platform-test 잡과 같은 판정입니다(데이터 자산·브라우저 E2E 제외, 커버리지 하한 80%).
check-tests:
	$(PYTHON) -m pytest tests/ -q -m "not data_assets and not e2e" --cov=src --cov-report=term-missing --cov-fail-under=80 -p no:cacheprovider

check-all: frontend-check secret-scan check-docs css-check lint security typecheck dup-check check-rules check-tests lint-workflows
	@echo "전체 코드 품질 및 정합성 검사 통과"

test:
	$(PYTHON) -m pytest tests/ -m "not data_assets" --cov=src --cov-report=term-missing

test-data-assets:
	$(PYTHON) -m pytest tests/ -m data_assets

test-e2e:
	$(PYTHON) -m pytest tests/e2e/ -m e2e

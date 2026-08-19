.PHONY: help setup import-assets dev dev-fe db-up up down logs build lint security typecheck quality check-rules lint-workflows check-all migrate-verify migrate-current migrate-up migrate-stamp migrate-check model-verify rebuild-rankings rebuild-institution-stats benchmark test test-data-assets

ifeq ($(OS),Windows_NT)
VENV_PYTHON := .venv/Scripts/python.exe
else
VENV_PYTHON := .venv/bin/python
endif

PYTHON ?= $(if $(wildcard $(VENV_PYTHON)),$(VENV_PYTHON),python3)
UV ?= uv

help:
	@echo "refac_bid_box 개발 및 품질 검증 타깃:"
	@echo "  make setup          - uv 의존성 동기화"
	@echo "  make import-assets  - 원본 bid_box의 모델·ChromaDB 자산 이전 및 체크섬 기록"
	@echo "  make dev            - FastAPI 개발 서버 실행"
	@echo "  make db-up          - MySQL+Redis만 배경 실행"
	@echo "  make up             - 전체 스택 컨테이너 배경 실행 (FastAPI+Arq+MySQL+Redis)"
	@echo "  make build          - 컨테이너 이미지 빌드"
	@echo "  make down           - 컨테이너 중지 및 네트워크 정리"
	@echo "  make logs           - 컨테이너 실시간 로그 확인"
	@echo "  make lint           - Ruff 포맷팅 및 린트 검사"
	@echo "  make security       - Bandit 보안 스캔"
	@echo "  make typecheck      - mypy 타입 검사 (릴리스 게이트 포함)"
	@echo "  make quality        - typecheck & jscpd 중복 코드 검사"
	@echo "  make check-rules    - 다중 에이전트 규칙 정합성 검증"
	@echo "  make lint-workflows - GitHub Actions 워크플로우 검사 (actionlint)"
	@echo "  make check-all      - 전체 린트, 보안, 품질, 규칙 정합성 검사"
	@echo "  make migrate-verify - 데이터 보존 무손실 실측 검증"
	@echo "  make migrate-current - Alembic 적용 상태 읽기 전용 확인"
	@echo "  make migrate-up     - Alembic 스키마 적용 (신규 환경 전용)"
	@echo "  make migrate-stamp  - 기존 Django DB 에 기준선 버전만 기록 (DDL 미실행)"
	@echo "  make migrate-check  - 모델과 실제 스키마 차이 점검 (읽기 전용)"
	@echo "  make model-verify   - 모델 직렬화 버전과 서빙 특징 호환성 검증"
	@echo "  make rebuild-rankings - 상위 N 집계 스냅샷 재생성"
	@echo "  make rebuild-institution-stats - 기관별 낙찰률 사전 집계 재생성"
	@echo "  make benchmark      - P95 레이턴시 벤치마크 (서버 기동 필요)"
	@echo "  make test           - 외부 데이터 자산 없이 Pytest 단위/통합/E2E 테스트 실행"
	@echo "  make test-data-assets - 모델·ChromaDB가 있는 환경의 G1 자산 테스트 실행"
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

# 기동 중인 서버에 HTTP 로 붙습니다. 먼저 uvicorn 을 띄우십시오.
benchmark:
	$(PYTHON) scripts/benchmark_latency.py



lint:
	$(PYTHON) -m ruff check . --fix
	$(PYTHON) -m ruff format .

security:
	$(PYTHON) -m bandit -c pyproject.toml -r src/ scripts/

typecheck:
	$(PYTHON) -m mypy src/

quality: typecheck
	npx jscpd src/ frontend/src/ --threshold 5

check-rules:
	$(PYTHON) scripts/validate_agent_rules.py

lint-workflows:
	$(UV) run actionlint

check-all: lint security typecheck check-rules lint-workflows
	@echo "전체 코드 품질 및 정합성 검사 통과"

test:
	$(PYTHON) -m pytest tests/ -m "not data_assets"

test-data-assets:
	$(PYTHON) -m pytest tests/ -m data_assets

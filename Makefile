.PHONY: help dev dev-fe up down logs build lint security quality check-rules check-all migrate-verify migrate-up migrate-stamp migrate-check benchmark test clean

PYTHON ?= python3

help:
	@echo "refac_bid_box 개발 및 품질 검증 타깃:"
	@echo "  make up             - 전체 멀티 스택 컨테이너 배경 실행 (FastAPI+MySQL+Redis+Frontend)"
	@echo "  make down           - 컨테이너 중지 및 네트워크 정리"
	@echo "  make logs           - 컨테이너 실시간 로그 확인"
	@echo "  make lint           - Ruff 포맷팅 및 린트 검사"
	@echo "  make security       - Bandit 보안 스캔"
	@echo "  make quality        - mypy 타입 검사 & jscpd 중복 코드 검사"
	@echo "  make check-rules    - 다중 에이전트 규칙 정합성 검증"
	@echo "  make check-all      - 전체 린트, 보안, 품질, 규칙 정합성 검사"
	@echo "  make migrate-verify - 데이터 보존 무손실 실측 검증"
	@echo "  make migrate-up     - Alembic 스키마 적용 (신규 환경 전용)"
	@echo "  make migrate-stamp  - 기존 Django DB 에 기준선 버전만 기록 (DDL 미실행)"
	@echo "  make migrate-check  - 모델과 실제 스키마 차이 점검 (읽기 전용)"
	@echo "  make benchmark      - P95 레이턴시 벤치마크 검증"
	@echo "  make test           - Pytest 단위/통합/E2E 테스트 실행"
	@echo "  make dev-fe         - 프론트엔드 (Vite + React 19) 개발 서버 구동"

up:
	docker compose up --build -d

down:
	docker compose down

logs:
	docker compose logs -f

dev-fe:
	cd frontend && npm run dev

migrate-verify:
	$(PYTHON) scripts/verify_migration.py

# 이미 Django 로 구축된 DB 에는 절대 쓰지 마십시오. migrate-stamp 를 쓰십시오.
migrate-up:
	$(PYTHON) -m alembic upgrade head

migrate-stamp:
	$(PYTHON) -m alembic stamp head

migrate-check:
	$(PYTHON) scripts/check_schema_drift.py

benchmark:
	$(PYTHON) scripts/benchmark_latency.py



lint:
	$(PYTHON) -m ruff check . --fix
	$(PYTHON) -m ruff format .

security:
	$(PYTHON) -m bandit -c pyproject.toml -r src/ scripts/

quality:
	$(PYTHON) -m mypy src/
	npx jscpd src/ frontend/src/ --threshold 5

check-rules:
	$(PYTHON) scripts/validate_agent_rules.py

check-all: lint security quality check-rules
	@echo "전체 코드 품질 및 정합성 검사 통과"

test:
	$(PYTHON) -m pytest tests/

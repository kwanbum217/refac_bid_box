.PHONY: help dev dev-fe build lint security quality test doctor clean

PYTHON ?= python3

help:
	@echo "refac_bid_box 개발 및 품질 검증 타깃:"
	@echo "  make lint        - Ruff 포맷팅 및 린트 검사"
	@echo "  make security    - Bandit 보안 스캔"
	@echo "  make quality     - mypy 타입 검사 & jscpd 중복 코드 검사"
	@echo "  make check-rules - 다중 에이전트 규칙 정합성 검증"
	@echo "  make check-all   - 전체 린트, 보안, 품질, 규칙 정합성 검사"
	@echo "  make test        - Pytest 단위/통합 테스트 실행"
	@echo "  make dev-fe      - 프론트엔드 (Vite + React 19) 개발 서버 구동"

dev-fe:
	cd frontend && npm run dev


lint:
	uv run ruff check . --fix
	uv run ruff format .

security:
	uv run bandit -c pyproject.toml -r src/ scripts/

quality:
	uv run mypy src/
	npx jscpd

check-rules:
	$(PYTHON) scripts/validate_agent_rules.py

check-all: lint security check-rules
	@echo "전체 코드 품질 및 정합성 검사 통과"

test:
	uv run pytest tests/

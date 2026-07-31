FROM python:3.11-slim

WORKDIR /app

# 시스템 빌드 의존성 설치
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# uv 패키지 매니저 설치
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# 프로젝트 설정 및 의존성 파일 복사
COPY pyproject.toml Makefile /app/

# 의존성 동기화
RUN uv sync --frozen || uv sync

# 프로젝트 소스 복사
COPY src/ /app/src/
COPY scripts/ /app/scripts/

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "src.app.main:app", "--host", "0.0.0.0", "--port", "8000"]

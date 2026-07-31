FROM python:3.11-slim

WORKDIR /app

# 시스템 패키지 설치
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    git \
    && rm -rf /var/lib/apt-lists/*

# uv 패키지 매니저 복사
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# 프로젝트 소스 및 설정 전체 복사
COPY . /app/

# 의존성 설치
RUN uv pip install --system -e .

EXPOSE 8000

CMD ["uvicorn", "src.app.main:app", "--host", "0.0.0.0", "--port", "8000"]

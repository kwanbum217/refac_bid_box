FROM python:3.11-slim@sha256:d1e9ca7c4e78d1e8ecadb5d44bfc8e956e7a65b659a9950f569f243d72b326d0

WORKDIR /app

# 시스템 패키지 설치
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# uv 패키지 매니저 복사. latest 는 빌드 시점마다 달라져 이미지가 재현되지
# 않으므로 버전을 고정합니다.
COPY --from=ghcr.io/astral-sh/uv:0.12.5 /uv /bin/uv

# 프로젝트 소스 및 설정 전체 복사
COPY . /app/

# 의존성 설치. uv.lock 에서 정확한 버전을 뽑아 설치합니다.
# `uv pip install -e .` 만 쓰면 pyproject.toml 의 >= 범위가 빌드 시점마다
# 다시 해석되어 CI 가 검증한 의존성 집합과 운영 이미지가 어긋납니다.
RUN uv export --frozen --no-dev --no-emit-project --format requirements.txt -o /tmp/requirements.txt \
    && uv pip install --system -r /tmp/requirements.txt \
    && uv pip install --system --no-deps -e . \
    && rm /tmp/requirements.txt

# 개발 의존성은 운영 이미지에 넣지 않습니다. 컨테이너 안에서 테스트를 돌려야 하면
# `uv pip install --system --group dev` 를 별도 빌드 스테이지에서 수행하십시오.

EXPOSE 8000

CMD ["python3", "-m", "uvicorn", "src.app.main:app", "--host", "0.0.0.0", "--port", "8000"]

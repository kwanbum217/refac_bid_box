FROM python:3.11-slim@sha256:d1e9ca7c4e78d1e8ecadb5d44bfc8e956e7a65b659a9950f569f243d72b326d0 AS builder

ENV VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# 컴파일러와 패키지 관리 도구는 의존성 빌드가 끝난 스테이지에만 둡니다.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    git \
    && python -m venv "$VIRTUAL_ENV" \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.12.5 /uv /bin/uv
COPY pyproject.toml uv.lock ./

# uv.lock 에서 운영 의존성만 설치하여 빌드 시점의 재해석을 막습니다.
RUN uv export --frozen --no-dev --no-emit-project --format requirements.txt -o /tmp/requirements.txt \
    && uv pip install --python "$VIRTUAL_ENV/bin/python" -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt

COPY . /app/
RUN uv pip install --python "$VIRTUAL_ENV/bin/python" --no-deps -e .

FROM python:3.11-slim@sha256:d1e9ca7c4e78d1e8ecadb5d44bfc8e956e7a65b659a9950f569f243d72b326d0 AS runtime

ENV VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    HOME=/tmp

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /app /app

# 운영 프로세스는 고정 UID의 비-root 계정으로 실행합니다. Compose의 bind
# mount도 같은 UID를 사용하므로 모델·데이터 읽기 권한이 일관됩니다.
RUN groupadd --gid 1000 app \
    && useradd --uid 1000 --gid 1000 --create-home --home-dir /home/app --shell /usr/sbin/nologin app \
    && chown -R 1000:1000 /app /home/app

USER 1000:1000

EXPOSE 8000

CMD ["python3", "-m", "uvicorn", "src.app.main:app", "--host", "0.0.0.0", "--port", "8000"]

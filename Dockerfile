FROM python:3.11-slim@sha256:d1e9ca7c4e78d1e8ecadb5d44bfc8e956e7a65b659a9950f569f243d72b326d0 AS builder

ENV VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# 컴파일러와 패키지 관리 도구는 의존성 빌드가 끝난 스테이지에만 둡니다.
# venv 는 --without-pip 으로 만듭니다. 설치는 uv 가 수행하므로 대상 venv 에
# pip, setuptools, wheel 이 필요하지 않고, 그 세 패키지가 런타임 이미지까지
# 따라가면 빌드 잔재가 취약점으로 남습니다. 2026-09-04 Trivy 가 검출한
# CVE-2026-23949(setuptools 가 벤더링한 jaraco.context)와 CVE-2026-24049(wheel)
# 가 그 경로였습니다.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    git \
    && python -m venv --without-pip "$VIRTUAL_ENV" \
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

# LightGBM 은 OpenMP 런타임을 동적으로 링크합니다. 빌더 스테이지에만 있고
# 런타임에는 없어서 2026-09-03 에 v25, v13_hybrid, quantum_leap_v25_pro,
# servc_institution_v1 네 모델이 전부 libgomp.so.1 없음으로 로드에 실패했습니다.
# 공고 상세 화면에 SSH 모델 하나만 뜨던 원인입니다.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /app /app

# 런타임 진입점은 uvicorn 하나이며 컨테이너 안에서 패키지를 설치하지 않습니다.
# 베이스 이미지의 시스템 python 에 남아 있는 빌드 도구를 제거해 공급망 검사가
# 검출할 표면을 없앱니다. venv 쪽은 --without-pip 으로 이미 비어 있습니다.
RUN rm -rf /usr/local/lib/python3.11/site-packages/pip \
    /usr/local/lib/python3.11/site-packages/pip-*.dist-info \
    /usr/local/lib/python3.11/site-packages/setuptools \
    /usr/local/lib/python3.11/site-packages/setuptools-*.dist-info \
    /usr/local/lib/python3.11/site-packages/pkg_resources \
    /usr/local/lib/python3.11/site-packages/wheel \
    /usr/local/lib/python3.11/site-packages/wheel-*.dist-info \
    /usr/local/bin/pip /usr/local/bin/pip3 /usr/local/bin/pip3.11 \
    /usr/local/bin/wheel

# 운영 프로세스는 고정 UID의 비-root 계정으로 실행합니다. Compose의 bind
# mount도 같은 UID를 사용하므로 모델·데이터 읽기 권한이 일관됩니다.
RUN groupadd --gid 1000 app \
    && useradd --uid 1000 --gid 1000 --create-home --home-dir /home/app --shell /usr/sbin/nologin app \
    && chown -R 1000:1000 /app /home/app

USER 1000:1000

EXPOSE 8000

CMD ["python3", "-m", "uvicorn", "src.app.main:app", "--host", "0.0.0.0", "--port", "8000"]

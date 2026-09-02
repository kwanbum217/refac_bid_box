# 컨테이너 이미지 강화 작업 보고서

> 작업 ID: `task_c8e14bf8d6cd`
> 대상: `Dockerfile`, `docker-compose.prod.yml`

## 변경 내용

- `Dockerfile`을 `builder`와 `runtime` 두 스테이지로 분리했습니다.
- `build-essential`, `curl`, `git`, `uv`는 builder 스테이지에서만 사용하며 런타임 스테이지에는 복사하지 않습니다.
- 두 스테이지 모두 `python:3.11-slim@sha256:d1e9ca7c4e78d1e8ecadb5d44bfc8e956e7a65b659a9950f569f243d72b326d0`을 사용합니다.
- `ghcr.io/astral-sh/uv:0.12.5` 고정을 유지했습니다.
- 런타임 이미지에 UID/GID `1000:1000`의 `app` 사용자를 만들고 `USER 1000:1000`으로 실행합니다.
- 운영 `app`과 `worker`에 `read_only: true`를 적용하고 `/tmp`에 `noexec,nosuid` 제한이 있는 64MiB `tmpfs`를 열었습니다.
- 운영 `app`과 `worker`의 `./src` 마운트를 제거했습니다. 소스 코드는 이미지에 포함됩니다.

## 데이터 경로 권한 근거

| 경로 | `app` | `worker` | 근거 |
| --- | --- | --- | --- |
| `ml_registry` | 읽기 전용 | 읽기/쓰기 | 모델 승격과 학습 baseline 기록은 워커가 수행하며 앱은 서빙 모델을 읽습니다. |
| `data` | 읽기 전용 | 읽기/쓰기 | 워커의 수집·갱신 작업이 원천 데이터를 기록하며 앱은 분석 데이터를 읽습니다. |
| `chroma_db` | 읽기 전용 | 읽기/쓰기 | 워커의 지식베이스 색인 갱신이 저장소를 변경하며 앱은 요청 처리에서 색인을 읽습니다. |

이미지 내부에서는 임시 파일·캐시 용도로 `/tmp`만 열었습니다. 런타임의 `HOME`도 `/tmp`로 지정하여 읽기 전용 루트에서 사용자 캐시 생성으로 기동이 실패하지 않게 했습니다. 소스 디렉터리는 이미지 레이어에서 제공하므로 운영 시 호스트 소스가 실행 경로를 덮어쓰지 않습니다.

## 검증

- `docker build -t refac-bid-box-root:orca-gate .`: 통과
- `docker build --check -f Dockerfile .`: 경고 없이 통과
- `docker compose -f docker-compose.prod.yml config --quiet` (검증용 더미 환경변수): 통과
- `python3 scripts/validate_agent_rules.py --quiet`: 통과 (17/17)
- `docker image inspect refac-bid-box:g4-image-hardening`: `Config.User=1000:1000` 확인
- 실제 컨테이너는 기동하지 않았습니다.

개발용 `docker-compose.yml`과 `frontend/Dockerfile`은 수정하지 않았습니다.

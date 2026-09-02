# 운영 환경 배포 가이드

## 개요

본 문서는 `docker-compose.prod.yml` 을 사용한 운영 환경 배포 절차와 주의사항을 설명합니다. 개발용 `docker-compose.yml` 과는 별도의 파일로, 운영에 필요한 보안·자원·관측 설정을 모두 포함합니다.

---

## 필수 환경 변수

운영 환경에서는 다음 변수에 **기본값을 두지 않고 반드시 설정**해야 합니다. `.env` 파일이나 배포 파이프라인의 시크릿 주입 메커니즘을 통해 주입하십시오.

| 변수 | 설명 |
| --- | --- |
| `ENVIRONMENT` | `production` 고정 |
| `SECRET_KEY` | 32자 이상 무작위 키 |
| `CORS_ALLOWED_ORIGINS` | 허용 오리진 목록(쉼표 구분, 스킴 포함). 와일드카드 불가 |
| `DB_USER` | 앱/워커가 쓸 전용 DB 계정명 (root 금지) |
| `DB_PASSWORD` | 전용 DB 계정 비밀번호 |
| `DB_NAME` | 데이터베이스명 (예: `procurement`) |
| `MYSQL_ROOT_PASSWORD` | MySQL root 비밀번호 (초기화용, 앱은 사용 안 함) |
| `REDIS_PASSWORD` | Redis 인증 비밀번호 (`requirepass` 에 사용) |
| `MEILI_MASTER_KEY` | Meilisearch 마스터 키 (16자 이상) |
| `G2B_SERVICE_KEY` | 나라장터 API 키 (필수 아님, 수집 기능 쓸 때만) |
| `LLM_PROVIDER` | `ollama` 또는 `gemini` |
| `OLLAMA_BASE_URL` | Ollama 엔드포인트 (기본 `http://host.docker.internal:11434`) |
| `OLLAMA_MODEL` | 사용할 Ollama 모델 (기본 `gemma4:e2b`) |

### 선택 변수 (기본값 있음)

| 변수 | 기본값 | 설명 |
| --- | --- | --- |
| `WEB_CONCURRENCY` | `1` | Uvicorn 워커 수 |
| `CORS_DEV_ALLOW_ALL` | `false` | 개발용 전체 허용 (운영은 `false`) |
| `PREDICTION_GC_MODE` | `freeze` | `freeze` 또는 빈 값 |
| `LATENCY_SEGMENT_LOGGING` | `false` | 지연 세그먼트 로깅 |
| `NGRAM_PREFILTER_ENABLED` | `false` | N-gram 프리필터 |
| `AUTOMATION_DATA_REFRESH_SCHEDULE_ENABLED` | `true` | 데이터 일일 최신화 |
| `AUTOMATION_NIGHTLY_SCHEDULE_ENABLED` | `false` | 야간 스케줄 |
| `ML_WEEKLY_RETRAIN_ENABLED` | `false` | 주간 재학습 |

---

## [중요] TRUSTED_PROXY_IPS 설정 필수

**리버스 프록시(Nginx, Traefik, ALB 등)를 앞에 둘 경우 반드시 `.env` 의 `TRUSTED_PROXY_IPS` 에 해당 프록시의 IP 또는 CIDR을 넣으십시오.**

```
TRUSTED_PROXY_IPS=10.0.0.0/8,172.16.0.0/12
```

이 값을 비워 두면 애플리케이션이 `X-Forwarded-For` 헤더를 신뢰하지 않고 TCP 피어 주소(프록시 IP)를 클라이언트 IP로 간주합니다. 결과적으로 **모든 요청이 단일 프록시 IP에서 온 것으로 보여 IP 기준 로그인 시도 제한이 전체 사용자 잠금으로 확대**됩니다. 이 동작은 커밋 `0295e3e` 에서 병합된 실제 검증 사례입니다.

프록시가 없는 단일 호스트 배포라면 이 값을 비워도 무방하지만, 문서상으로는 반드시 경고를 인지하고 결정하십시오.

---

## 아키텍처 특징

### 1. 내부 전용 네트워크 (`internal: true`)

- `db`, `redis`, `meilisearch` 는 호스트 포트를 **열지 않습니다**.
- 모든 서비스 간 통신은 `internal` 브리지 네트워크를 통해 이루어집니다.
- 외부 접근이 필요한 서비스(`app`의 8000 포트)만 호스트에 바인딩됩니다.

### 2. 최소 권한 DB 계정

- 앱과 워커는 `DB_USER`/`DB_PASSWORD` 로 지정된 전용 계정을 사용합니다.
- `MYSQL_ROOT_PASSWORD` 는 컨테이너 초기화(스키마 생성, 전용 계정 생성)용으로만 쓰이며, 애플리케이션 코드에서는 절대 사용하지 않습니다.
- MySQL 기동 시 `MYSQL_USER`/`MYSQL_PASSWORD`/`MYSQL_DATABASE` 가 자동으로 전용 계정과 DB를 생성합니다.

### 3. Redis 인증 (`requirepass`)

- Redis 기동 명령에 `--requirepass ${REDIS_PASSWORD}` 가 포함됩니다.
- 앱/워커의 `REDIS_URL` 은 `redis://:<password>@redis:6379/0` 형태가 됩니다.
- 헬스체크도 `-a <password>` 옵션으로 인증 후 `PING` 을 보냅니다.

### 4. 이미지 및 Non-root 실행

- `Dockerfile`은 빌드 스테이지와 런타임 스테이지를 분리합니다. 컴파일러와 `git`은 빌드 스테이지에만 존재하며 소스 코드는 런타임 이미지에 포함됩니다.
- 런타임 이미지는 고정 UID/GID `1000:1000`의 `app` 사용자로 실행됩니다. Compose의 `user: "1000:1000"`도 같은 값을 지정해 이미지 단독 실행과 운영 실행의 권한을 일치시킵니다.
- `app`, `worker`, `meilisearch`는 `1000:1000`, `db`는 `999:999`, `redis`는 `999:999`로 실행됩니다.
- 베이스 이미지 `python:3.11-slim`은 digest로 고정하고, 빌드 도구 `uv`도 `ghcr.io/astral-sh/uv:0.12.5`로 고정합니다.

### 5. 헬스체크

- `app`: `/api/v1/health/ready` 엔드포인트 폴링 (ready/degraded 허용)
- `worker`: Redis 연결 테스트 (`redis-cli ping` 과 동등한 Python 코드)
- `db`: `mysqladmin ping` (전용 계정으로 인증)
- `redis`: `redis-cli -a <password> ping`
- `meilisearch`: `/health` 엔드포인트

`depends_on` 에 `condition: service_healthy` 를 걸어 기동 순서를 보장합니다.

### 6. 자원 제한 (`deploy.resources`)

| 서비스 | CPU 제한 | 메모리 제한 | CPU 예약 | 메모리 예약 |
| --- | --- | --- | --- | --- |
| app | 2.0 | 2G | 0.5 | 512M |
| worker | 2.0 | 2G | 0.5 | 512M |
| db | 2.0 | 4G | 0.5 | 1G |
| redis | 1.0 | 1G | 0.25 | 256M |
| meilisearch | 1.0 | 2G | 0.25 | 512M |

워크로드 특성에 맞춰 조정하십시오. 특히 DB 버퍼 풀(`MYSQL_BUFFER_POOL_SIZE`)과 Redis `maxmemory` 는 메모리 제한과 연동해 설정하십시오.

### 7. 로그 회전 (`logging`)

모든 서비스는 JSON 파일 드라이버에 다음 옵션을 적용합니다.

```yaml
logging:
  driver: "json-file"
  options:
    max-size: "10m"
    max-file: "5"
```

파일당 10MB, 최대 5개 파일(총 50MB)까지 보관 후 순환합니다. 중앙 로깅 시스템(Fluent Bit, Vector 등)을 연계할 때는 드라이버를 `fluentd` 또는 `syslog` 로 교체하십시오.

### 8. 읽기 전용 루트 및 데이터 볼륨

- 운영 `app`과 `worker`에는 `read_only: true`를 적용합니다. 프로세스가 임시 파일과 라이브러리 캐시를 생성할 수 있는 유일한 이미지 내부 경로는 `tmpfs`로 연 `/tmp`이며, `HOME=/tmp`도 함께 지정합니다. `tmpfs`에는 `noexec,nosuid` 제한을 적용합니다.
- 소스 코드(`src`)는 호스트에 마운트하지 않고 빌드된 이미지에서 제공합니다. 따라서 운영 실행 중 호스트 소스가 교체되지 않습니다.
- `ml_registry`는 모델 승격과 학습 baseline 기록이 필요하므로 `worker`에만 읽기/쓰기로 마운트하고, `app`에는 `:ro`로 제공합니다.
- `data`는 워커의 수집·갱신 작업이 원천 데이터를 기록해야 하므로 `worker`에만 읽기/쓰기로 마운트하고, `app`에는 `:ro`로 제공합니다.
- `chroma_db`는 워커의 지식베이스 색인 갱신이 저장소를 갱신해야 하므로 `worker`에만 읽기/쓰기로 마운트하고, `app`에는 `:ro`로 제공합니다. 앱은 운영 요청에서 기존 색인을 읽기만 합니다.
- 위 세 경로 외에는 이미지 내부에 쓰기 가능한 경로를 열지 않습니다. 데이터 디렉터리의 호스트 소유권은 컨테이너 UID `1000`에 맞춰야 합니다.

---

## 배포 절차

### 1. 환경 변수 준비

```bash
# .env.prod 생성 (실제 값으로 채우기)
cp .env.example .env.prod
# 필수 변수 모두 설정, 기본값 제거
```

### 2. 설정 검증

```bash
docker compose -f docker-compose.prod.yml --env-file .env.prod config -q
```

`config -q` 가 통과하면 문법과 필수 변수 참조가 올바릅니다. 실제 기동은 하지 않습니다.

### 3. 이미지 빌드

```bash
docker compose -f docker-compose.prod.yml --env-file .env.prod build
```

### 4. 데이터베이스 초기화 (최초 1회)

```bash
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d db
# 헬스체크 통과 대기
docker compose -f docker-compose.prod.yml --env-file .env.prod exec db mysql -u root -p"$MYSQL_ROOT_PASSWORD" -e "CREATE USER IF NOT EXISTS '$DB_USER'@'%' IDENTIFIED BY '$DB_PASSWORD'; GRANT ALL ON $DB_NAME.* TO '$DB_USER'@'%'; FLUSH PRIVILEGES;"
```

> **참고**: `MYSQL_USER`/`MYSQL_PASSWORD`/`MYSQL_DATABASE` 환경변수로도 전용 계정이 생성되지만, root 비밀번호와 전용 계정 비밀번호를 분리해 관리하려면 위 수동 단계를 권장합니다.

### 5. 전체 스택 기동

```bash
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d
```

### 6. 헬스체크 확인

```bash
docker compose -f docker-compose.prod.yml --env-file .env.prod ps
# 모든 서비스가 healthy 상태인지 확인
```

---

## 롤백 절차

```bash
# 이전 이미지 태그로 되돌리기
docker compose -f docker-compose.prod.yml --env-file .env.prod down
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --force-recreate
```

데이터 볼륨(`mysql_data`, `redis_data`, `meilisearch_data`)은 유지되므로 스키마 마이그레이션이 없는 한 데이터 손실 없이 롤백됩니다.

---

## 모니터링 체크리스트

- [ ] 컨테이너 재시작 횟수 (`docker compose ps` 의 RESTARTS 컬럼)
- [ ] 헬스체크 상태 (`healthy` 유지)
- [ ] 로그 파일 크기 순환 확인 (`/var/lib/docker/containers/*/*.log`)
- [ ] 메모리/CPU 사용량 (`docker stats` 또는 cAdvisor/Prometheus)
- [ ] DB 커넥션 풀 사용률
- [ ] Redis 메모리 사용률 (`used_memory` / `maxmemory`)
- [ ] Meilisearch 인덱스 크기 및 검색 레이턴시

---

## 보안 점검 사항

- [ ] `.env.prod` 파일이 버전 관리에서 제외되어 있는가 (`.gitignore` 확인)
- [ ] `SECRET_KEY` 가 32자 이상 무작위 값인가
- [ ] `CORS_ALLOWED_ORIGINS` 에 와일드카드가 없는가
- [ ] `DB_USER` 가 `root` 가 아닌가
- [ ] `REDIS_PASSWORD` 가 설정되어 있는가
- [ ] `TRUSTED_PROXY_IPS` 가 프록시 환경에서 올바르게 설정되었는가
- [ ] 방화벽/보안 그룹에서 3306, 6379, 7700 포트가 외부 차단되어 있는가 (내부 네트워크만 허용)
- [ ] 앱 8000 포트만 프록시를 통해 노출되는가

---

## 참고: 개발 환경과의 차이점

| 항목 | 개발용 (`docker-compose.yml`) | 운영용 (`docker-compose.prod.yml`) |
| --- | --- | --- |
| DB 계정 | root | 전용 계정 (`DB_USER`) |
| DB 포트 | 3306 호스트 바인딩 | 내부 네트워크만 |
| Redis 포트 | 6379 호스트 바인딩 | 내부 네트워크만 + 인증 |
| Meilisearch 포트 | 7700 호스트 바인딩 | 내부 네트워크만 |
| Non-root | 미적용 (root) | `user` 지시자 적용 |
| Worker 헬스체크 | 없음 | 있음 (Redis ping) |
| 자원 제한 | 없음 | `deploy.resources` 적용 |
| 로그 회전 | 없음 | `max-size: 10m, max-file: 5` |
| 볼륨 마운트 | 읽기/쓰기 | 읽기 전용 (`:ro`) |
| 네트워크 | 기본 브리지 | `internal: true` 브리지 |
| 환경 변수 기본값 | 다수 있음 | 필수 변수 기본값 없음 |

---

## 트러블슈팅

### 앱이 DB 연결 실패

- `DB_USER`, `DB_PASSWORD`, `DB_NAME` 이 정확히 설정되었는지 확인
- MySQL 컨테이너 로그에서 `Access denied` 메시지 확인
- 전용 계정 생성 SQL 이 실행되었는지 확인

### Redis 인증 실패

- `REDIS_PASSWORD` 가 `.env.prod` 와 `docker-compose.prod.yml` 양쪽에서 동일한지 확인
- `redis-cli -a "$REDIS_PASSWORD" ping` 으로 직접 테스트

### 헬스체크가 계속 unhealthy

- `docker compose logs <service>` 로 상세 로그 확인
- `start_period` 가 충분한지 확인 (앱 180초, 워커 30초, DB/Redis/Meilisearch 50초 내외)
- 네트워크 격리(`internal: true`) 로 인해 외부 의존성(Ollama 등) 접근이 차단되지 않았는지 확인 → `extra_hosts: host.docker.internal` 로 우회

### 프록시 뒤인데 로그인 제한이 전체 사용자에게 걸림

- `TRUSTED_PROXY_IPS` 가 비어 있지 않은지 확인
- 프록시가 `X-Forwarded-For` 헤더를 올바르게 설정하는지 확인
- 애플리케이션 로그에서 `client_ip` 가 프록시 IP 가 아닌 실제 클라이언트 IP로 찍히는지 확인

---

## 변경 이력

| 날짜 | 버전 | 변경 내용 |
| --- | --- | --- |
| 2026-09-02 | 1.0 | 초기 작성 (docker-compose.prod.yml 신설) |

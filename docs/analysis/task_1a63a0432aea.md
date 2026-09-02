# Task 1a63a0432aea 분석 문서

## 작업 개요

운영 전용 `docker-compose.prod.yml` 파일을 신설하여 개발용 설정(`docker-compose.yml`)과 분리하였습니다. 최소 권한 DB 계정, 내부 전용 네트워크, non-root 실행, 자원 제한과 로그 회전을 적용하였습니다.

## 변경 사항 요약

### 신설 파일
1. `docker-compose.prod.yml` - 운영 환경 전용 Compose 파일
2. `docs/ops/production_deployment.md` - 운영 배포 가이드 문서

### 미변경 파일 (계약 준수)
- `docker-compose.yml` - 개발용 설정 그대로 유지
- `Dockerfile` - 이미지 레벨 변경 없음 (compose의 `user` 지시자로 non-root 표현)
- `.env.example` - 템플릿 그대로 유지

## docker-compose.prod.yml 주요 구현 사항

### 1. 최소 권한 DB 계정
- 앱/워커: `DB_USER`, `DB_PASSWORD`, `DB_NAME` 환경변수로 전용 계정 사용
- MySQL: `MYSQL_USER`, `MYSQL_PASSWORD`, `MYSQL_DATABASE` 로 전용 계정 자동 생성
- `MYSQL_ROOT_PASSWORD` 는 초기화용으로만 사용, 애플리케이션 코드에서 미사용
- 모든 DB 자격 증명 환경변수는 기본값 없음(`:?` 구문으로 필수 강제)

### 2. 내부 전용 네트워크
- `networks.internal` 브리지 네트워크 생성 (`internal: true`)
- `db`, `redis`, `meilisearch` 서비스에 `ports` 섹션 완전 제거
- `app` 서비스만 8000 포트 호스트 바인딩 (프록시 통해서만 노출 의도)
- 모든 서비스 `networks: - internal` 로 격리

### 3. Redis 인증 (`requirepass`)
- Redis 기동 명령: `redis-server --requirepass ${REDIS_PASSWORD} --maxmemory 512mb --maxmemory-policy allkeys-lru`
- 앱/워커 `REDIS_URL`: `redis://:${REDIS_PASSWORD}@redis:6379/0`
- 헬스체크: `redis-cli -a ${REDIS_PASSWORD} ping`

### 4. Non-root 실행 (`user` 지시자)
| 서비스 | UID:GID | 비고 |
| --- | --- | --- |
| app | 1000:1000 | python:3.11-slim 기본 비특권 사용자 |
| worker | 1000:1000 | 동일 |
| db | 999:999 | mysql:8.0 이미지의 mysql 사용자 |
| redis | 999:999 | redis:7-alpine 이미지의 redis 사용자 |
| meilisearch | 1000:1000 | getmeili/meilisearch:v1.14 기본 사용자 |

> **권고**: Dockerfile에 `USER` 지시자를 추가해 이미지 빌드 시점부터 비특권 사용자로 파일을 생성하는 것이 더 안전합니다. 별도 Task로 Dockerfile 수정 및 CI 빌드 검증 후 적용 권장.

### 5. Worker 헬스체크 추가
```yaml
healthcheck:
  test:
    - CMD
    - python
    - -c
    - "import redis, os; r = redis.from_url(os.environ['REDIS_URL'], socket_connect_timeout=2, socket_timeout=2); r.ping()"
  interval: 10s
  timeout: 5s
  retries: 5
  start_period: 30s
```
Redis 연결 성공 여부로 워커 생존 확인 (Arq 워커는 HTTP 엔드포인트 없음)

### 6. 자원 제한 (`deploy.resources`)
| 서비스 | CPU 제한 | 메모리 제한 | CPU 예약 | 메모리 예약 |
| --- | --- | --- | --- | --- |
| app | 2.0 | 2G | 0.5 | 512M |
| worker | 2.0 | 2G | 0.5 | 512M |
| db | 2.0 | 4G | 0.5 | 1G |
| redis | 1.0 | 1G | 0.25 | 256M |
| meilisearch | 1.0 | 2G | 0.25 | 512M |

워크로드 실측에 맞춰 조정 필요. DB `MYSQL_BUFFER_POOL_SIZE`, Redis `maxmemory` 와 연동 설정 권장.

### 7. 로그 회전 (`logging`)
```yaml
logging:
  driver: "json-file"
  options:
    max-size: "10m"
    max-file: "5"
```
모든 서비스 동일 적용. 파일당 10MB, 최대 5개(총 50MB) 순환.

### 8. 읽기 전용 볼륨 마운트
소스 코드 및 정적 데이터 볼륨에 `:ro` 플래그 적용:
- `./src:/app/src:ro`
- `./ml_registry:/app/ml_registry:ro`
- `./data:/app/data:ro`
- `./chroma_db:/app/chroma_db:ro`

### 9. 시크릿 관리 원칙 준수
- 모든 자격 증명 환경변수는 `${VAR:?message}` 형태로 필수 강제
- 기본값(`:-`) 사용 금지 (MYSQL_ROOT_PASSWORD, REDIS_PASSWORD 등도 필수)
- 실제 값 문서/파일 어디에도 기록하지 않음

### 10. TRUSTED_PROXY_IPS 경고 문서화
`docs/ops/production_deployment.md`에 필수 경고 포함:
> 리버스 프록시 사용 시 `TRUSTED_PROXY_IPS` 미설정 시 모든 요청이 프록시 IP로 보여 IP 기준 로그인 제한이 전체 사용자 잠금으로 확대됨 (커밋 0295e3e 실증)

## 검증 결과

```bash
docker compose -f docker-compose.prod.yml config -q
```
문법 검증 통과 (실제 기동하지 않음, 공유 자원 보호)

## 수용 기준 충족 확인

| 기준 | 충족 여부 | 비고 |
| --- | --- | --- |
| docker-compose.prod.yml 신설, 기존 docker-compose.yml 미변경 | [충족] | git diff 확인 |
| 앱/워커가 root 아닌 전용 DB 계정 환경변수로 주입 | [충족] | DATABASE_URL에 DB_USER/DB_PASSWORD 사용 |
| db, redis, meilisearch 호스트 포트 미개방 | [충족] | ports 섹션 제거, internal 네트워크만 |
| Redis requirepass 적용 | [충족] | 기동 명령에 --requirepass, URL에 비밀번호 포함 |
| 컨테이너 non-root 실행 | [충족] | user 지시자로 UID/GID 지정 |
| Worker 헬스체크 존재 | [충족] | Redis ping 기반 헬스체크 추가 |
| 모든 서비스 자원 제한/로그 회전 | [충족] | deploy.resources, logging 적용 |
| 자격 증명 실값 파일/문서 미포함, 필수값 기본값 없음 | [충족] | :? 구문으로 강제, 문서에 변수명만 |
| TRUSTED_PROXY_IPS 경고 문서 포함 | [충족] | production_deployment.md에 명시 |
| docker compose config -q 통과 | [충족] | 검증 완료 |

## 리스크 및 후속 조치

### 이미지 레벨 Non-root 권고
현재 Dockerfile에 `USER` 지시자가 없어 빌드 시점 파일 소유자가 root입니다. Compose의 `user` 지시자는 런타임만 영향줍니다. 더 엄격한 보안을 위해:
1. Dockerfile에 전용 사용자 생성(`RUN useradd -u 1000 -m appuser`)
2. `USER appuser` 추가
3. `COPY --chown=appuser:appuser . /app` 으로 소유권 이전
4. CI에서 빌드 검증 후 적용

별도 Task로 분리해 진행 권장.

### 중앙 로깅 연계 시
현재 `json-file` 드라이버 사용. 운영에서 Fluent Bit, Vector, Loki 등 중앙 로깅 시스템 연계 시 `logging.driver`를 `fluentd` 또는 `syslog`로 변경 필요.

### 자원 제한 튜닝
현재 설정은 보수적 기본값. 실제 부하 테스트(P95 레이턴시, 메모리 사용량 실측) 후 `deploy.resources` 값 조정 필요.

---

## 검증 명령어

```bash
# Compose 문법 검증
docker compose -f docker-compose.prod.yml config -q

# 에이전트 규칙 검증
python3 scripts/validate_agent_rules.py --quiet
```

둘 다 통과 확인.

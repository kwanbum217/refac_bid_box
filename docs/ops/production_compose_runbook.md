# 운영 Compose 네트워크·readiness 런북

> 대상: `docker-compose.prod.yml`
> 목적: 외부 API 호출 경로를 확보하고, 애플리케이션과 워커가 실제 준비 상태일 때만 트래픽을 받도록 운영합니다.

---

## 네트워크 구조

운영 Compose는 데이터 계층과 외부 통신 계층을 분리합니다.

| 네트워크 | 설정 | 연결 서비스 | 용도 |
| --- | --- | --- | --- |
| `internal` | `driver: bridge`, `internal: true` | `app`, `worker`, `db`, `redis`, `meilisearch` | 데이터 계층 접근 및 서비스 간 내부 통신 |
| `egress` | `driver: bridge` | `proxy`, `app`, `worker` | 프록시 수신과 인터넷 송신 |

`db`, `redis`, `meilisearch`는 `internal`에만 연결합니다. 따라서 데이터 계층에는 외부 네트워크 경로가 없고, Compose가 새 호스트 포트를 열지 않습니다. `app`과 `worker`는 두 네트워크에 모두 연결되어 내부 데이터 계층과 외부 통신을 함께 사용할 수 있으며, `proxy`는 `egress`에서 `app`으로 요청을 전달합니다.

다음 외부 통신은 `app` 또는 `worker`의 `egress` 경로를 사용합니다.

- G2B 공공데이터 API 수집
- `LLM_PROVIDER=gemini`일 때 Gemini API
- MLOps 알림 또는 외부 webhook
- 운영 환경에서 설정한 외부 Ollama 주소

외부 송신이 필요하지 않은 데이터 계층 서비스는 `egress`에 추가하지 않습니다.

## readiness 게이트

운영 Compose의 `app` 환경변수는 다음 값을 명시적으로 주입합니다.

```text
READINESS_REQUIRE_WARMUP=true
READINESS_REQUIRE_LLM=true
```

따라서 `/api/v1/health/ready`는 MySQL, Redis, 모델 레지스트리뿐 아니라 warmup 완료와 LLM 가용성을 모두 확인합니다. 어떤 필수 조건이 실패하면 HTTP 503과 `status: not_ready`를 반환하고, 비필수 확인만 실패해도 `status: degraded`를 반환합니다. 운영 `app` healthcheck는 `status == 'ready'`만 성공으로 인정하므로 `degraded` 상태에서는 `proxy`가 의존 서비스를 healthy로 판단하지 않습니다.

워커 healthcheck는 Redis ping에 더해 `bidbox:worker:heartbeat`의 `last_seen_at`을 읽습니다. 마지막 heartbeat가 `WORKER_HEARTBEAT_MAX_AGE_SECONDS`를 넘겼거나 누락·파싱 불가이면 실패합니다. 기본 임계값은 90초이며, heartbeat 주기(`WORKER_HEARTBEAT_INTERVAL_SECONDS`, 기본 30초)의 3배 이상을 권장합니다.

## 배포 전 정적 검증

Docker 데몬 없이도 Compose 문법과 정적 계약을 확인할 수 있습니다.

```bash
docker compose -f docker-compose.prod.yml config -q
uv run pytest tests/test_prod_compose_topology.py -q
python3 scripts/validate_agent_rules.py --quiet
```

`config -q`가 실패하면 기동하지 말고 `.env`의 필수 변수와 Compose interpolation 오류를 먼저 수정합니다. 특히 `SECRET_KEY`, `DB_PASSWORD`, `REDIS_PASSWORD`, `MEILI_MASTER_KEY`, TLS 변수는 운영 값으로 설정해야 합니다.

## 기동 후 확인

```bash
docker compose -f docker-compose.prod.yml up -d
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml exec app python -c "import json, urllib.request; response = urllib.request.urlopen('http://localhost:8000/api/v1/health/ready', timeout=5); payload = json.load(response); assert payload['status'] == 'ready', payload"
docker compose -f docker-compose.prod.yml exec worker python -c "import redis, os; r = redis.from_url(os.environ['REDIS_URL']); r.ping(); print('redis reachable')"
```

`app` 또는 `worker`가 계속 unhealthy이면 컨테이너 로그에서 의존성 장애를 확인합니다.

```bash
docker compose -f docker-compose.prod.yml logs --tail=200 app worker
```

실제 외부 송신은 운영 자격증명을 사용해 G2B API, 선택한 LLM 공급자, webhook 대상별로 별도 확인합니다. 비밀 키와 webhook URL을 로그나 문서에 기록하지 않습니다. 데이터 계층 서비스에 외부 포트가 노출되지 않았는지도 `docker compose ... ps`와 호스트 방화벽 정책에서 함께 확인합니다.

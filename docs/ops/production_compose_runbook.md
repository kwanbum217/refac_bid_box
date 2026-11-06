# 운영 Compose 네트워크·readiness 런북

> 대상: `docker-compose.prod.yml`
> 목적: 외부 API 호출 경로를 확보하고, 애플리케이션과 워커가 실제 준비 상태일 때만 트래픽을 받도록 운영합니다.

---

## 네트워크 구조

운영 Compose는 데이터 계층과 외부 통신 계층을 분리합니다.

| 네트워크 | 설정 | 연결 서비스 | 용도 |
| --- | --- | --- | --- |
| `internal` | `driver: bridge`, `internal: true` | `app`, `worker`, `backup`, `db`, `redis`, `meilisearch`, `otel-collector`, `tempo`, `prometheus`, `alertmanager`, `grafana` | 데이터 계층 접근, 백업, 서비스 간 내부 통신 |
| `egress` | `driver: bridge`, `ipam.config.subnet: 172.30.0.0/24` | `proxy`, `app`, `worker`, `backup` | 프록시 수신과 인터넷 송신 |

`db`, `redis`, `meilisearch`는 `internal`에만 연결합니다. 따라서 데이터 계층에는 외부 네트워크 경로가 없고, Compose가 새 호스트 포트를 열지 않습니다. `app`과 `worker`는 두 네트워크에 모두 연결되어 내부 데이터 계층과 외부 통신을 함께 사용할 수 있으며, `proxy`는 `egress`에서 `app`으로 요청을 전달합니다. `backup`은 DB·Redis에 접근해야 하고 백업 실패 알림을 외부 webhook으로 보내야 하므로 두 네트워크에 모두 속합니다. 관측 5개 서비스(`otel-collector`, `tempo`, `prometheus`, `alertmanager`, `grafana`)는 `internal` 전용이며 호스트 포트를 열지 않습니다. `proxy`만 호스트 `443`을 게시합니다.

`egress`는 컨테이너 IP가 재기동 사이에 바뀌지 않도록 `172.30.0.0/24`로 고정합니다. `TRUSTED_PROXY_IPS`에 이 CIDR을 넣으면 Caddy가 보낸 `X-Forwarded-For`를 신뢰하면서도 단일 컨테이너 IP를 하드코딩하지 않아도 됩니다. 같은 네트워크에 붙은 컨테이너는 헤더를 위조할 수 있으므로 `egress`에는 프록시와 송신이 필요한 서비스만 둡니다.

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
READINESS_REQUIRE_LLM=false
```

따라서 `/api/v1/health/ready`의 필수 조건은 MySQL, Redis, 모델 레지스트리, warmup 완료 네 가지입니다. 이 중 하나라도 실패하면 HTTP 503과 `status: not_ready`를 반환합니다. 반면 LLM은 필수가 아니므로 LLM이 내려가도 200과 `status: degraded`를 반환하며, 앱은 결정론적 폴백 응답으로 서비스를 유지합니다. Meilisearch·ChromaDB 확인 실패도 같은 `degraded` 경로입니다.

운영 `app` healthcheck는 `status`가 `ready` 또는 `degraded`이면 성공입니다. 그래서 LLM 장애 시에도 `proxy`가 `app`을 healthy로 보고 트래픽을 계속 전달합니다. `degraded`를 503으로 오판해 롤백하거나, 반대로 "프록시가 막아 준다"고 믿으면 안 됩니다. LLM 장애 대응은 알람과 `llm` 확인 항목으로 판단합니다.

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
docker compose -f docker-compose.prod.yml exec app python -c "import json, urllib.request; response = urllib.request.urlopen('http://localhost:8000/api/v1/health/ready', timeout=5); payload = json.load(response); assert payload['status'] in ('ready', 'degraded'), payload; print(payload['status'])"
docker compose -f docker-compose.prod.yml exec worker python -c "import redis, os; r = redis.from_url(os.environ['REDIS_URL']); r.ping(); print('redis reachable')"
```

`app` 또는 `worker`가 계속 unhealthy이면 컨테이너 로그에서 의존성 장애를 확인합니다.

```bash
docker compose -f docker-compose.prod.yml logs --tail=200 app worker
```

실제 외부 송신은 운영 자격증명을 사용해 G2B API, 선택한 LLM 공급자, webhook 대상별로 별도 확인합니다. 비밀 키와 webhook URL을 로그나 문서에 기록하지 않습니다. 데이터 계층 서비스에 외부 포트가 노출되지 않았는지도 `docker compose ... ps`와 호스트 방화벽 정책에서 함께 확인합니다.

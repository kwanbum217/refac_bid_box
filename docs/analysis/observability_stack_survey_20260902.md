# 관측성 스택 선택 근거 보고서

> 작성일: 2026-09-02
> 목적: 지표를 먼저 정의한 뒤, 1인 운영에 맞는 관측성 선택지를 비교합니다.
> 범위: 읽기 전용 조사입니다. 코드·설정·의존성은 변경하지 않았습니다.

## 1. 결론 요약

관측성의 첫 단계는 제품 선택이 아니라 공통 이벤트와 지표 계약을 정하는 것입니다. 현재 저장소에는 로그와 `/api/v1/health/live`, `/api/v1/health/ready`가 있고 Arq 실행 이력도 남지만, 시계열 집계·분산 상관·중앙 경보는 없습니다.

권고 후보는 **선택지 A: Prometheus + Grafana + Alertmanager를 단계적으로 도입하고, 초기에는 애플리케이션 계측을 최소화하는 방식**입니다. 이유는 1인 운영에서 운영 부하와 데이터 이동을 통제하면서 큐·스케줄·SSE·RAG·DB·Redis의 수치형 상태를 먼저 확보하기 쉽기 때문입니다. 다만 요청 단위의 원인 추적이 실제 장애 분석에서 병목으로 확인되면 선택지 B의 OpenTelemetry를 후속 도입해야 하며, 비용·외부 전송 정책이 우선이면 선택지 C를 재평가할 수 있습니다.

이는 확정 스택이 아니라 측정 결과에 따른 후보 권고입니다. SLO 값은 이 보고서에서 정하지 않습니다.

## 2. 현재 근거와 제약

| 확인 사항 | 근거 | 관측성 의미 |
| --- | --- | --- |
| Arq cron은 매일 02:00, 월요일 03:00, 매일 04:00에 실행되며 worker는 `max_jobs=4`입니다. | [`src/tasks/worker.py`](../../src/tasks/worker.py) | 예정 시각, 실행 지연, 동시 작업 포화가 별도 지표여야 합니다. |
| 스케줄 실행은 `PipelineExecution`에 `started_at`, 상태, `execution_id`를 기록하고, 야간·주간 실패는 알림 함수로 보냅니다. | [`src/tasks/scheduled_tasks.py`](../../src/tasks/scheduled_tasks.py), [`src/tasks/notifier.py`](../../src/tasks/notifier.py) | 최근 성공 여부는 로그 검색이 아니라 실행 이력 기반으로 계산해야 합니다. |
| SSE 스트림은 `trace_id`와 선택적 `segment_metrics`를 `done` 이벤트에 담고, 준비·벡터·LLM·guard·전체 시간을 계산합니다. | [`src/rag/engine.py`](../../src/rag/engine.py) | 첫 바이트/첫 토큰과 꼬리 지연을 요청별로 집계할 기반은 있으나 연결 종료·전송 지연은 별도 계측이 필요합니다. |
| Redis 장애 시 캐시가 프로세스 메모리로 내려가며 연결 재시도 백오프가 있습니다. | [`src/app/core/cache.py`](../../src/app/core/cache.py) | Redis 포화와 폴백 비율을 함께 보지 않으면 cold miss와 장애를 혼동할 수 있습니다. |
| 운영 Compose에는 app, worker, MySQL, Redis, Meilisearch가 있고 CPU·메모리 제한과 로그 회전이 설정되어 있습니다. | [`docker-compose.prod.yml`](../../docker-compose.prod.yml) | 관측성 컨테이너 추가는 기존 자원 한도와 디스크 보존량을 함께 검토해야 합니다. |
| `pyproject.toml`에는 Prometheus, OpenTelemetry, Sentry 계열 의존성이 없습니다. | [`pyproject.toml`](../../pyproject.toml) | 새 Python 의존성은 사전 합의 대상입니다. |

## 3. 먼저 정할 지표 계약

모든 지표에는 `service`, `environment`, `instance`, `route` 또는 `task`, `status`, `trace_id`(가능한 경우), 시작·종료 시각을 붙입니다. 사용자 질의나 URL 원문, 서비스 키, 토큰은 라벨과 로그에 넣지 않습니다. 카운터는 누적값, 게이지는 현재값, 히스토그램은 구간 분포로 정의하고, 고카디널리티 식별자는 라벨 대신 로그 필드로 둡니다.

| 영역 | 우선 지표 | 잡아낼 장애 | 값 확정 전에 측정할 것 |
| --- | --- | --- | --- |
| Arq worker | heartbeat 마지막 시각, worker별 활성 작업 수, 작업 실행·대기 시간, 실패·재시도 수, timeout 수 | worker 정지, 작업 고착, 동시성 포화, Redis 연결 문제 | heartbeat가 실제로 어느 주기로 발생하는지, idle/작업 중 false positive 비율, 정상 실행 시간 분포 |
| 큐 지연 | enqueue 시각부터 시작 시각까지의 `queue_wait_seconds`, 큐 깊이, oldest job age | 생산자 폭주, worker 부족, Redis 큐 정체 | 현재 큐 자료구조와 enqueue 경로별 시각 보존 가능 여부, 정상 피크 큐 깊이 |
| 스케줄 | 예정 시각 대비 시작 지연, 실행 상태, 완료 시각, 최근 성공·부분 실패·실패, 누락 실행 | cron 미발화, 옛 데이터로 재학습, 조용한 부분 실패 | KST 기준 예정 시각과 실제 시각, 비활성/skip 정책, 부분 성공의 업무 허용 여부 |
| SSE | 연결 수, 첫 이벤트·첫 토큰 지연, 토큰 간 간격, 전체 스트림 시간, disconnect·error, `done` 도달률 | 준비 단계 지연, LLM 정체, 프록시 버퍼링, 클라이언트 단절 | 측정 지점별 시계(서버 생성·전송·클라이언트 수신), 정상 스트림 길이와 단절 원인 |
| RAG | cold/warm 구분별 cache hit/miss, miss 후 SQL·벡터·LLM 구간, single-flight 대기, `trace_id`별 전체 시간 | 캐시 만료 후 SQL 급증, 벡터 저장소 지연, 중복 cold miss | cold 정의(프로세스 재시작·키 만료·Redis 장애), 캐시 키 수명, warmup 직후 표본 |
| MySQL | 연결 풀 사용·대기, 쿼리 시간 분포, active thread, CPU·메모리·buffer pool, 디스크 I/O, errors | DB 포화, 풀 고갈, 느린 쿼리, 잠금 | SQL 템플릿별 정상 분포와 표본, 개인정보 제거한 쿼리 식별자, 컨테이너 자원 한도에서의 포화점 |
| Redis | used memory와 maxmemory 대비율, evictions, connected clients, blocked clients, command latency, ops/sec, errors, pool 대기 | 캐시 축출, 메모리 포화, 연결 고갈, 명령 정체 | 512MB 정책에서 실제 working set, eviction 허용 여부, 캐시·세션 트래픽 분리 가능 여부 |
| 가용성 | live/ready 상태, dependency별 readiness 결과·지연, HTTP 상태 코드 | 프로세스 생존과 실제 서비스 가능 상태의 괴리 | degraded를 허용할 요청 범위, dependency 장애 시 업무 영향 |

### 3.1 SLO를 정하기 위한 측정 순서

먼저 최소 1~2주간 대표 부하와 정상 스케줄을 수집합니다. 그 기간에 엔드포인트·작업·캐시 상태별로 P50/P95/P99, 오류율, 완료율, 누락률을 계산하고, 업무 영향이 큰 실패를 분리합니다. 이후 용량을 의도적으로 올리는 부하 시험과 Redis·MySQL·LLM 장애 주입을 수행해 포화점과 복구 시간을 확인합니다.

그 결과로서만 각 SLI의 서비스 경계, 집계 창, 제외할 유지보수·비활성 스케줄, 오류 예산을 담당자가 승인해야 합니다. 이 보고서는 숫자형 SLO를 제시하지 않습니다. 특히 SSE의 첫 토큰 지연과 전체 지연, Arq의 큐 지연, 스케줄 성공 여부, RAG cold miss는 서로 다른 사용자·운영 영향을 가지므로 하나의 지연 목표로 합치지 않습니다.

## 4. 선택지 비교

| 선택지 | 구성 | 새 Python 의존성 | 새 컨테이너 | 운영 부담 | 1인 운영 적합성 |
| --- | --- | --- | --- | --- | --- |
| A. 자체 시계열 기본형 | Prometheus, Grafana, Alertmanager. 애플리케이션은 metrics endpoint 또는 Push 방식으로 지표를 제공 | 예: `prometheus-client` 1개. 트레이싱을 같이 넣으면 추가 계측 패키지가 필요합니다 | 3개. 기존 app/worker/db/redis와 같은 Compose에 추가 | 보존량·대시보드·알림 라우팅·백업을 직접 운영 | 높음. 구성요소가 명확하고 외부 데이터 전송이 없습니다 |
| B. OpenTelemetry 통합형 | Python OpenTelemetry SDK/exporter, OpenTelemetry Collector, Prometheus/Grafana, trace backend(예: Tempo), 필요 시 log backend | `opentelemetry-api`, `opentelemetry-sdk`, FastAPI/HTTPX/SQLAlchemy/Redis/Arq 계측 패키지 등 여러 개 | 최소 Collector와 trace backend, metrics/log 저장소까지 포함하면 4개 이상 추가 | 상관관계·샘플링·스키마·저장소와 Collector 자체를 운영 | 중간 이하. 원인 추적은 강하지만 초기 운영면이 넓습니다 |
| C. 관리형 관측성 | 관리형 metrics/logs/traces/Sentry 계열과 Python SDK | 공급자 SDK 1개 이상. 데이터 전송·샘플링 설정 필요 | 보통 0개 추가. 외부 에이전트가 필요한 공급자는 예외 | 계정·비용·보존·데이터 국외 전송·공급자 장애를 관리 | 비용과 정책이 허용되면 높음, 그렇지 않으면 낮음 |

선택지 A와 B의 숫자는 구현 전 구성안 기준이며 고정된 SLO나 비용 추정이 아닙니다. 선택지 C는 공급자를 특정하지 않았으므로 계약·가격·리전·보존 정책 확인 없이는 우열을 확정할 수 없습니다.

## 5. 의존성 없이 얻는 것과 얻지 못하는 것

현재 구조만으로도 로그 수집기에서 다음은 즉시 파생할 수 있습니다: health live/ready의 성공·실패와 dependency별 지연, `PipelineExecution`의 시작·종료·상태, 스케줄 실패 알림, RAG `trace_id`와 segment metrics가 노출된 요청의 구간 시간, Redis 연결 실패·폴백 로그, Compose healthcheck와 컨테이너 재시작 상태입니다.

반면 로그만으로는 worker heartbeat의 지속적인 부재를 안정적으로 판정하기 어렵고, 큐 전체 깊이·최고 대기 작업을 일관되게 집계하기 어렵습니다. SSE 네트워크 꼬리 지연은 서버의 `yield` 시각만으로 알 수 없으며, RAG cold miss 비율과 MySQL·Redis 포화의 장기 추세도 구조화된 시계열 없이는 취약합니다. 따라서 먼저 이벤트 필드와 측정 지점을 정한 뒤, 현재 로그를 단기 기준선으로 보존하고 선택한 수집기를 붙이는 순서가 필요합니다.

## 6. 권고 도입 순서와 CD 전제

1. 지표 이름·단위·라벨 허용 목록과 민감정보 마스킹 규칙을 문서 계약으로 확정합니다.
2. worker heartbeat/큐 지연, 스케줄 실행 이력, SSE 전송 경계, RAG cache 상태, DB·Redis 자원 지표를 우선 계측하고 1~2주 기준선을 수집합니다.
3. 선택지 A를 후보로 검증합니다. 운영 Compose에 Prometheus·Grafana·Alertmanager를 추가할지는 기준선의 저장량과 담당자 운영 가능 시간을 확인한 뒤 결정합니다.
4. 실제 장애에서 요청 간 원인 연결이 부족하다는 증거가 있으면 선택지 B로 확장합니다. 처음부터 전체 trace/log backend를 추가하지 않고 필요한 경로부터 샘플링합니다.
5. 외부 전송·비용·보존 정책이 자체 운영보다 유리하다는 결정이 있으면 선택지 C를 별도 평가합니다.

CD는 Pull Request 승인 게이트를 전제로 하지 않습니다. 이 저장소의 1인 작업 규칙에 맞춰 브랜치에서 테스트·규칙 검증·이미지 및 설정 검사를 수행하고, 담당자가 작업 브랜치를 `main`에 직접 병합한 뒤 푸시 이벤트에서 배포를 실행하는 흐름을 제안합니다. 배포 후 `/api/v1/health/ready`, worker heartbeat, 스케줄·큐 지표를 확인하고 실패 시 이전 이미지로 되돌리는 운영자 실행 롤백을 둡니다. 자동 승격 여부는 SLO 수치와 복구 실측이 정해진 뒤 결정하며, 리뷰 승인 단계는 넣지 않습니다.

## 7. 확인하지 못한 미지 항목

- Arq의 실제 enqueue 경로, 큐 저장 키와 job metadata가 모든 작업에 동일한지 확인하지 못했습니다.
- 현재 worker heartbeat 자체가 구현되어 있는지와 권장 heartbeat 주기를 확인하지 못했습니다.
- SSE의 서버 생성 시각과 실제 브라우저 수신 시각을 연결할 클라이언트 계측 및 프록시 설정을 확인하지 못했습니다.
- RAG cold의 운영 정의, 캐시별 TTL·키 수·hit/miss 집계 가능 여부를 확인하지 못했습니다.
- MySQL 연결 풀 설정, slow query 수집 정책, Redis command latency 수집 경로와 실제 피크 사용량을 확인하지 못했습니다.
- 외부 관리형 서비스의 리전·비용·보존·개인정보 처리 조건을 확인하지 못했습니다.
- 관측성 저장소의 보존 기간, 백업 및 복구 절차, 알림 수신 채널의 온콜 책임자를 확인하지 못했습니다.

위 항목은 스택 확정 전 측정·운영 정책으로 닫아야 하며, 현재 보고서의 권고를 확정 배포 설계로 해석해서는 안 됩니다.

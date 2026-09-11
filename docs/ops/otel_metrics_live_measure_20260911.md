# 로컬 컨테이너 OTel 메트릭 실측 (2026-09-11)

> **HEAD**: `kwanbum217/r22-otel-measure`
> **조건**: 로컬 `docker-compose.yml` app 재빌드, `OTEL_ENABLED=true`, `OTEL_EXPORTER_TYPE=console`, 내보내기 주기 5000ms

## 결과

재빌드 후 app 컨테이너 설정은 `OTEL_ENABLED True`, `is_metrics_enabled True` 였다.
`GET /api/v1/health` 200 요청을 8회 보낸 뒤 컨테이너 로그에서 아래 계측기가 방출됐다.

| 계측기 | 관측 |
| --- | :---: |
| `http.server.request.duration` | 있음 |
| `http.server.request.count` | 있음 |
| `db.client.operation.duration` | 있음 |

측정 후 기본값(`OTEL_ENABLED=false`)으로 app 을 다시 기동해 콘솔 내보내기를 껐다.

## 범위 밖

Collector Prometheus exporter 와 Prometheus 서비스 배선은 별도 작업이다.

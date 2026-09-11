# SLO 와 알람 규칙 (2026-09-11)

> **HEAD**: `kwanbum217/r22-slo-alerts`
> **정본 한도**: [`latency_gate_protocol.md`](latency_gate_protocol.md), [`phase7_cutover_declaration_20260901.md`](phase7_cutover_declaration_20260901.md)
> **배선**: `docker/prometheus_rules.yml`, `docker/alertmanager.yml`, `docker/grafana/dashboards/slo_alerts.json`

## 1. 범위

관측성 백엔드는 Collector·Tempo·Prometheus·Grafana 로 이미 확정됐다.
이 문서는 그 스택 위에 **운영 SLO 값과 라이브 알람** 만 붙인다. 새 한도를
벤치마크에서 만들지 않고 G3 게이트 숫자를 옮긴다.

## 2. SLO

| SLO | 목표 | 라이브 알람 | 근거 |
| --- | --- | :---: | --- |
| 예측 API P95 | 100ms 이하 | 예. `PredictHttpP95High` | G3 c10 판정선 |
| 예측 API 가용성 | 5xx 비율 0.1% 이하 | 예. `PredictHttpErrorRateHigh` | G3 7,200 요청 오류 0건, Wilson 상한 0.053% 를 운영 5분 창에서 단건 5xx 에 울리지 않도록 반올림 |
| SSE 전체 P95 | 20초 이하 | 예. `ChatStreamHttpP95High` | 순차 측정 목표. HTTP 전체 지연만 계측한다 |
| SSE 첫 토큰 P95 | 3초 이하 | 아니오 | 현재 메트릭에 첫 토큰 히스토그램이 없다. 벤치마크 게이트로 유지 |
| 예측 100ms 초과율 | 0.5% 이하 | 아니오 | 라이브 히스토그램 버킷이 0.1s 경계를 보장하지 않는다. 벤치마크 게이트로 유지 |

예측 경로는 `POST /api/v1/predictions/predict` 다. `predict-price` 는 이 SLO
집합에 넣지 않았다. G3 실측 경로가 아니기 때문이다.

메트릭 라벨 `http_route` 는 FastAPI `APIRoute.path` 이다. 앱의
`include_router(..., prefix="/api/v1")` 접두부는 라벨에 들어가지 않는다.
따라서 PromQL 은 `/predictions/predict`, `/chatbot/chat/stream` 을 쓴다.

## 3. 알람 동작

Prometheus 가 15초마다 규칙을 평가하고 Alertmanager(`alertmanager:9093`) 로
보낸다. 두 서비스 모두 `internal` 네트워크만 쓰며 호스트 포트는 없다.

Alertmanager 수신기 `local-hold` 는 그룹핑만 하고 메일·Slack 으로 보내지
않는다. 외부 채널은 비밀값과 사용자 승인이 필요하다. 발화 여부는 Grafana
대시보드 `bidbox-slo-alerts` 의 `ALERTS{slo!=""}` 패널로 본다.

`OTEL_ENABLED=false` 이면 표본이 없어 `histogram_quantile` 이 NaN 을 돌려
비교식이 발화하지 않는다. 수집기 다운만 `OtelCollectorDown` 으로 잡는다.

## 4. 명시적으로 하지 않은 것

- 메일·Slack·웹훅 수신기
- SSE 첫 토큰 라이브 알람
- 예측 100ms 초과율 라이브 알람
- `predict-price` 및 목록 조회 경로 SLO

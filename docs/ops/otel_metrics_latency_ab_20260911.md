# 메트릭 켜짐 예측 API 레이턴시 쌍대 실측 (2026-09-11)

> **HEAD**: `kwanbum217/r22-obs-remaining`
> **규약**: [`latency_gate_protocol.md`](latency_gate_protocol.md) 예측 API c10, 회차당 600, 3회, 대표값 최악 P95
> **원시 요약**: `data/benchmarks/otel_metrics_latency_ab_20260911/summary.json`

## 조건

같은 로컬 app 컨테이너 이미지에서 `OTEL_ENABLED` 만 바꿨다.

| 모드 | 설정 |
| --- | --- |
| off | `OTEL_ENABLED=false` (compose 기본값) |
| on | `OTEL_ENABLED=true`, `OTEL_EXPORTER_TYPE=console`, 내보내기 주기 60s |

측정 경로: `POST /api/v1/predictions/predict`, 동시성 10, 회차당 600, 회차 사이 30초.
SSE와 단발 질의는 이번 비교에서 돌리지 않았다.

## 결과

| 모드 | r1 P95 | r2 P95 | r3 P95 | 최악 P95 | 100ms 초과 | 오류 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| off | 48.39ms | 48.71ms | 47.65ms | **48.71ms** | 0/1800 | 0 |
| on | 56.74ms | 55.88ms | 56.08ms | **56.74ms** | 0/1800 | 0 |

최악 P95 차이: **+8.03ms** (off 대비 +16.5%).
G3 c10 한도 100ms 는 두 모드 모두 통과한다.

호스트 정규화 load 1분 중앙값은 회차 모두 30% 한도 이내였다. off 2회차가 29.15%로 가장 높았다.

## 판정

메트릭을 켜면 예측 API c10 P95 가 약 8ms 늘지만 게이트 한도를 넘지 않는다.
운영에서 `OTEL_ENABLED=true` 를 쓰는 것은 이 경로의 G3 판정을 뒤집지 않는다.

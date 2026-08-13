# Phase 7 레이턴시 재검증 보고서

> **작성일**: 2026-08-13
> **대상 커밋**: `5cd9c614f9f6da5a528fa2e26d4c1e7ba2527603`
> **환경**: macOS 26.6.1 arm64, Docker Compose 전체 스택
> **판정**: SSE 제거 게이트 통과 / 전체 컷오버 보류

---

## 1. 판정 요약

| 항목 | P50 | P95 | 목표 | 판정 |
| --- | ---: | ---: | ---: | --- |
| 레거시 GET SSE 첫 토큰 | 1.757초 | 2.170초 | 3초 | 통과 |
| 레거시 GET SSE 전체 응답 | 4.868초 | 7.969초 | 20초 | 통과 |
| 정본 POST SSE 첫 stage | 9.8ms | 15.3ms | 참고치 | 통과 |
| 정본 POST SSE 첫 토큰 | 1.513초 | 1.721초 | 3초 | 통과 |
| 정본 POST SSE 전체 응답 | 4.916초 | 8.129초 | 20초 | 통과 |
| 예측 API, 기동 후 첫 병렬 측정 | 157.0ms | 1,930.0ms | 100ms | 실패 |
| 예측 API, 즉시 재측정 | 166.2ms | 627.0ms | 100ms | 실패 |

정본 POST SSE는 첫 토큰과 전체 응답 목표를 모두 충족하며 레거시 GET보다
첫 토큰이 빠릅니다. 따라서 레거시 GET `/api/v1/chatbot/stream` 제거 게이트는
충족했습니다. 다만 예측 API는 동시 요청 10개 조건에서 P95 목표를 충족하지
못했으므로 Phase 7 전체 컷오버 판정은 보류합니다.

---

## 2. 측정 조건

전체 측정은 다음 명령으로 수행했습니다.

```bash
uv run python scripts/benchmark_latency.py \
  --sse-rounds 20 \
  --query-rounds 10 \
  --predict-rounds 100 \
  --predict-concurrency 10 \
  --output data/benchmarks/phase7_latency_20260813_post_a1_a5.json
```

직후 예측 API만 같은 표본 수와 동시성으로 다시 측정했습니다.

```bash
uv run python scripts/benchmark_latency.py \
  --sse-rounds 0 \
  --query-rounds 0 \
  --predict-rounds 100 \
  --predict-concurrency 10 \
  --output data/benchmarks/phase7_latency_20260813_predict_warm.json
```

두 실행 모두 HTTP 오류는 없었습니다. 전체 측정의 종료 코드는 예측 P95 목표
실패 때문에 1이었고, 재측정은 예측 목표 실패에 더해 표본 수를 0으로 지정한
SSE 항목이 빈 표본으로 판정되는 현재 스크립트 동작 때문에 1이었습니다.

---

## 3. 예측 API 해석 경계

재측정 뒤 단일 요청을 순차로 10회 보낸 관찰에서는 첫 요청이 약 57ms, 이후
요청이 약 11~14ms였습니다. 반면 동시성 10에서는 P50 166.2ms, P95 627.0ms로
증가했습니다. 이 차이는 단일 요청 자체의 정상 경로보다 동시 실행 시 자원 경합을
먼저 의심하게 하지만, 원인 확정과 수정은 별도 병목 감사 및 동시성 1/2/4/10
재측정 뒤에 수행합니다.

이번 기록만으로 모델 스레드 수나 실행기 설정을 원인으로 확정하지 않습니다.
또한 예측 P95가 실패한 상태에서 Phase 7 G3 전체 통과를 선언하지 않습니다.

---

## 4. 원시 증빙

- `data/benchmarks/phase7_latency_20260813_post_a1_a5.json`
- `data/benchmarks/phase7_latency_20260813_predict_warm.json`


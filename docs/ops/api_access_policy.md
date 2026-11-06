# API 접근 정책

> 적용 범위: `src/app/api/v1/chatbot.py`, `src/app/api/v1/predictions.py`, `src/app/api/v1/bids.py`
>
> 최종 갱신일: 2026-11-06

## 익명 접근 정책

현재 화면(`chat_page` 및 공고 상세)은 비로그인 사용자에게도 기본 체험을 제공하며,
익명 사용자가 주요 기능을 먼저 확인할 수 있도록 다음 경로를 로그인 없이 열어 둡니다.

| 경로 | 익명 허용 이유 | 익명 쿼터 |
| --- | --- | --- |
| `POST /api/v1/chatbot/chat` | 로그인 전 질의·답변 체험을 제공합니다. 로그인하면 사용자 세션과 이력이 연결됩니다. | IP별 60초당 30회 |
| `POST /api/v1/chatbot/chat/stream` | 일반 대화와 같은 기능을 SSE로 제공합니다. 스트림 진입 시점에만 쿼터를 확인합니다. | IP별 60초당 30회 |
| `POST /api/v1/chatbot/session/new` | 익명 대화를 시작할 세션 키를 발급합니다. | IP별 60초당 30회 |
| `POST /api/v1/predictions/predict-price` | 공고 상세 등에서 로그인 없이 투찰가 분석을 체험할 수 있도록 허용합니다. | IP별 60초당 30회 |
| `POST /api/v1/predictions/predict` | 공고 레코드 없이 특징 직접 입력을 통한 예측을 로그인 없이 체험할 수 있도록 허용합니다. | IP별 60초당 30회 |
| `GET /api/v1/bids` | 공고 목록 JSON을 로그인 없이 볼 수 있도록 공개로 유지합니다. | IP별 60초당 30회 |
| `GET /api/v1/bids/results` | 낙찰결과 목록 JSON을 로그인 없이 볼 수 있도록 공개로 유지합니다. | IP별 60초당 30회 |
| `GET /api/v1/bids/{pk}` | 공고 상세 JSON을 로그인 없이 볼 수 있도록 공개로 유지합니다. | IP별 60초당 30회 |
| `GET /api/v1/bids/results/{pk}` | 낙찰결과 상세 JSON을 로그인 없이 볼 수 있도록 공개로 유지합니다. | IP별 60초당 30회 |
| `GET /api/v1/bids/stats` | 대시보드 통계 JSON을 로그인 없이 볼 수 있도록 공개로 유지합니다. | IP별 60초당 30회 |
| `GET /api/v1/bids/compare-stats` | 공고 대비 낙찰 비교 통계 JSON을 로그인 없이 볼 수 있도록 공개로 유지합니다. | IP별 60초당 30회 |
| `GET /api/v1/bids/home` | 홈 화면 컨텍스트 JSON을 로그인 없이 볼 수 있도록 공개로 유지합니다. | IP별 60초당 30회 |

`POST /api/v1/bids/collect` 는 관리자 전용이며 익명 접근 정책의 대상이 아닙니다.

쿼터는 `TRUSTED_PROXY_IPS` 정책을 반영하는 `resolve_client_ip`로 식별한 IP를
기준으로 Redis에 기록합니다. 기본값은 60초당 30회이며, 운영 환경에서는
`ANONYMOUS_API_RATE_LIMIT_MAX_REQUESTS`와
`ANONYMOUS_API_RATE_LIMIT_WINDOW_SECONDS` 설정으로 조정할 수 있습니다.
임계 초과 시에는 HTTP 429를 반환하지만 잠금 해제까지 남은 시간은 노출하지
않습니다. Redis 장애 시에는 관측 장치가 요청 자체를 중단하지 않도록 쿼터를
건너뛰고 요청을 계속 처리합니다.

로그인 사용자의 요청은 같은 `enforce_anonymous_api_quota` 가 사용자 축 인증 쿼터로
전환해 검사합니다(`src/app/core/security.py:937`). 한도는 사용자당 60초 120회이며
코드 상수(`AUTHENTICATED_API_RATE_LIMIT_MAX_REQUESTS`,
`AUTHENTICATED_API_RATE_LIMIT_WINDOW_SECONDS`)로 고정되어 환경변수로 조정하지
않습니다. 챗봇·예측 API 와 함께 비용이 큰
`POST /api/v1/evaluations/analyze`, `POST /api/v1/evaluations/recommend`,
`POST /api/v1/evaluations/snapshots` 도 같은 버킷을 씁니다. `recommend` 는 내부에서
predict-price 경로를 호출해 쿼터를 한 번만 차감합니다(이중 차감 방지). Redis 장애 시
동작은 익명 쿼터와 같습니다.

## 공고 JSON API 공개 정책

공고 JSON API(`/api/v1/bids` 의 목록·상세·통계·홈 컨텍스트)는 공개로 둡니다.
비로그인 사용자가 공고를 탐색하고 대시보드를 확인하는 흐름을 막지 않기
위해서입니다. 대신 무인증 라우트 전부에 챗봇 API 와 같은 익명 쿼터를 적용해
자동 수집·과다 호출로부터 백엔드를 보호합니다.

- 익명 쿼터는 위 표의 `GET /api/v1/bids` 계열 7개 라우트에 모두 적용합니다.
- 익명 쿼터는 로그인 사용자에게 적용하지 않습니다. 로그인 사용자는 인증
  사용자 쿼터를 따릅니다.
- 한도 초과 시 HTTP 429를 반환하며, 잠금 해제까지 남은 시간은 노출하지
  않습니다.
- `POST /api/v1/bids/collect` 는 관리자 전용이므로 공개 정책에서 제외합니다.

## 벤치마크 측정 정책

SSE 스트리밍 게이트 벤치마크(`scripts/benchmark_sse_gate.py`) 및 레이턴시 벤치마크(`scripts/benchmark_latency.py`)는 단시간 다회 요청으로 인한 익명 쿼터(HTTP 429) 차단 및 표본 오염을 방지하기 위해 `--session-cookie` 인자(또는 `BENCHMARK_SESSION_COOKIE` 환경변수)를 통해 발급받은 로그인 세션 쿠키(`bidbox_session`)를 실어 측정합니다.

## 익명 접근을 차단할 경우

향후 세 경로에 필수 인증을 적용하면 로그인 전 체험을 제공하는 기존 소비자와
로그인 화면에서 사용하는 클라이언트가 영향을 받습니다. 클라이언트는 먼저
로그인하여 `bidbox_session`을 발급받은 뒤 요청해야 하며, 익명 세션 키로 유지한
대화 이력은 인증 사용자 이력으로 자동 병합되지 않을 수 있습니다. 차단 전에는
외부 API 소비자와 배포된 UI의 인증 처리, 세션 이관 방식을 확인해야 합니다.

# 관측성 1단계 보존·샘플링 정책

> **확정일**: 2026-09-06
> **범위**: R-10 관측성 1단계 (트레이스 수집·저장·조회 배선)
> **상태**: 미측정 통상값 운용 중 (아래 미측정 고지 참조)

---

## 1. 범위

1단계가 두는 것은 트레이스 파이프라인 하나입니다.

| 구성 요소 | 역할 | 상태 |
| --- | --- | --- |
| `otel-collector` | OTLP 수신, tail sampling, Tempo 전달 | 1단계 |
| `tempo` | 트레이스 저장·조회 | 1단계 |
| `grafana` | 트레이스 조회 대시보드 | 1단계 |
| Prometheus (메트릭 저장소) | Counter·Histogram 계측이 저장소에 없어 둘 수 없음 | 2단계 |
| Loki (로그 수집) | 컨테이너 로그가 이미 json-file 드라이버로 10m 5개 회전 중 | 범위 밖 |

메트릭 저장소는 애플리케이션에 메트릭 계측이 생긴 뒤의 2단계이며, 1단계에서 Prometheus 를 추가하지 않습니다.

## 2. 토폴로지

app 과 worker 가 OTLP HTTP(`http://otel-collector:4318/v1/traces`) 로 span 을 보내면
Collector 가 tail sampling 을 적용한 뒤 Tempo 의 OTLP gRPC 포트(`tempo:4317`) 로 전달합니다.
Collector 의 `otlp` exporter 는 gRPC 이므로 Tempo 의 HTTP 수신 포트 4318 을 가리키면 export 가 전량 실패합니다.
Grafana 는 `docker/grafana/provisioning/datasources/tempo.yaml` 로 Tempo(`http://tempo:3200`) 를 데이터소스로 읽습니다.

세 서비스는 모두 `internal` 네트워크에만 붙으며 외부로 포트를 열지 않습니다.
Grafana 조회가 필요하면 같은 네트워크의 임시 컨테이너나 SSH 터널로 접근합니다.

## 3. 환경변수

app 과 worker 에 전달하는 OTEL 환경변수는 다섯 개이며, 백업 컨테이너에는 전달하지 않습니다.

| 변수 | 운영 기본값 | 의미 |
| --- | --- | --- |
| `OTEL_ENABLED` | `true` | `.env` 로 끌 수 있음. 끄면 계측 비용이 발생하지 않음 |
| `OTEL_SERVICE_NAME` | `refac_bid_box` | 리소스 service.name |
| `OTEL_EXPORTER_TYPE` | `otlp` | `none`, `console`, `otlp` 중 하나 |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://otel-collector:4318/v1/traces` | Collector 서비스 지향 |
| `OTEL_SAMPLING_RATIO` | `0.1` | 애플리케이션 헤드 샘플링 비율 |

## 4. 샘플링 정책 (2층)

두 층의 역할은 다릅니다.

- 1층 애플리케이션 헤드 샘플링: `OTEL_SAMPLING_RATIO=0.1` 로 전체 트레이스의 10%만 내보냅니다. SDK 에서 export 전에 탈락하므로 Collector 에 도달하지 않습니다.
- 2층 Collector tail sampling (`docker/otel-collector-config.yaml`): Collector 에 도착한 span 중에서 상태가 `ERROR` 인 것은 전량 보존하고, 나머지는 그대로 통과시킵니다. 오류를 남기는 판단은 전체 트레이스가 모인 뒤에 내리므로, 헤드를 통과한 오류 span 은 유실되지 않습니다.

따라서 오류 유입량을 늘리는 조정 수단은 `OTEL_SAMPLING_RATIO` 이며, Collector 정책은 그 안에서 오류를 빠뜨리지 않는 역할을 합니다.

## 5. 보존 정책

- 트레이스 보존 기간은 7일입니다. 정본 설정은 `docker/tempo.yaml` 의 `compactor.compaction.block_retention: 168h` 하나입니다.
- 메트릭 보존 15일은 2단계 예정값입니다. 계측과 저장소가 없으므로 문서에만 적고 설정으로 만들지 않습니다.

## 6. 미측정 고지

보존 7일과 샘플링 0.1 은 트레이스 볼륨 실측에 근거한 값이 아니라 통상값입니다.
이 저장소에는 트레이스 볼륨 실측이 없습니다. 1주 운영 후 `tempo_data` 볼륨의
디스크 사용량을 재어 보존 기간과 샘플링 비율을 조정합니다.
실측하지 않은 수치를 실측인 것처럼 인용하지 않습니다.

## 7. Grafana 접근 정책

- 익명 접근을 열지 않습니다 (`GF_AUTH_ANONYMOUS_ENABLED=false`).
- 관리자 비밀번호는 필수 변수입니다 (`${GF_SECURITY_ADMIN_PASSWORD:?...}`). 기본값을 두지 않으며 `.env.example` 에는 변수 이름과 설명만 둡니다.
- 외부 포트를 열지 않으므로 초기 데이터소스(Tempo `http://tempo:3200`) 연결은 Grafana UI 에서 직접 등록합니다.

## 8. 검증

컨테이너를 실제로 띄우지 않습니다. 검증은 다음까지입니다.

- `docker compose config`
- `docker build -t refac-bid-box-root:orca-ab1 .`
- `uv run pytest tests/ -q -m "not data_assets"`
- `python3 scripts/validate_agent_rules.py --quiet`

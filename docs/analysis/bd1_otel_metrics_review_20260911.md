# BD1 OTel 메트릭 계측 독립 검토

> 작성일: 2026-09-11
>
> 상태: 독립 검토 완료, 수용(pass)
>
> 대상: 브랜치 `kwanbum217/orca-bd1` 커밋 `f5445e2ea0103c6f0b7e34a6b5b25a5ceaab848e`
>
> 대상 파일: `src/app/core/observability.py`, `src/app/core/config.py`, `tests/test_observability_metrics.py`, `docs/ops/observability_metrics_20260911.md`
>
> 검토 Task: `task_d6e019a2a02d`
>
> 빌더 Task: `task_3d80b2899f28`

---

## 1. 판정

**수용한다.** 운영 기본 경로에서 `OTEL_ENABLED=False` 이면 MeterProvider, 메트릭
익스포터, 주기적 내보내기 스레드, 미들웨어, DB 리스너가 생기지 않는다. 경로
라벨은 FastAPI 라우트 템플릿이며 공고 번호·식별자·질의 문자열이 들어가지
않는다. 익스포터 예외는 요청 처리를 실패시키지 않는다. 새 패키지와
compose/Collector 변경은 없다. 차단 결함은 없다.

아래 비차단 지적(요청 수 카운터 명칭이 HTTP 규약 목록에 없음, 비표준 HTTP
메서드 `_OTHER` 미수렴, 히스토그램 권고 버킷 미지정)은 카디널리티 폭발이나
무자원 규약을 깨지 않으므로 병합을 막지 않는다.

---

## 2. OTEL_ENABLED 거짓이면 운영 경로는 무자원이다

운영 호출부는 `src/app/main.py:394` 의 `setup_observability(app=app, engine=engine)`
하나다. `custom_exporter` 와 `custom_metric_exporter` 를 넘기지 않는다.

`src/app/core/observability.py:397-401` 조기 반환 조건은
`not settings.OTEL_ENABLED and custom_exporter is None and custom_metric_exporter is None`
이다. 이 분기에서 `_registry.metrics_enabled = False` 를 넣고 즉시 return 하므로
그 아래의 `Resource.create`, `MeterProvider`, `PeriodicExportingMetricReader`,
`OTLPMetricExporter`, `app.add_middleware(OTelMetricsMiddleware)`,
`_attach_db_metrics_listeners` 에 닿지 않는다.

`Settings.is_metrics_enabled`(`src/app/core/config.py:230-240`) 도
`OTEL_ENABLED` 가 거짓이면 항상 거짓이다.

| 자원 | 꺼진 운영 경로에서 생기는가 | 근거 |
| --- | --- | --- |
| MeterProvider | 아니오 | 조기 반환 뒤 `get_meter_provider()` 는 `None` |
| 메트릭 익스포터 | 아니오 | `safe_metric_exporter` 할당은 447행 이후 |
| PeriodicExportingMetricReader 스레드 | 아니오 | 콘솔/OTLP/커스텀 익스포터 분기에만 생성 |
| HTTP 미들웨어 | 아니오 | `_registry.metrics_enabled` 가 거짓이면 555-558행 생략 |
| DB 리스너 | 아니오 | 575-577행 생략 |
| 세 계측기 | 아니오 | 517-531행 생략 |

`custom_metric_exporter` 가 있으면 조기 반환을 건너뛴다. 이는 기존 트레이스의
`custom_exporter` 와 같은 테스트 주입 훅이다. `main.py` 는 이 인자를 넘기지
않으므로 기본 운영 경로의 무자원 규약을 깨지 않는다.

---

## 3. 경로 라벨은 템플릿이고 고차원 값이 들어가지 않는다

`_extract_route_template`(`src/app/core/observability.py:185-194`) 는
`scope["route"].path` 를 쓰고, 없으면 `"unmatched"` 다. `request.url.path` 를
라벨에 넣지 않는다.

기록 시점은 미들웨어 `finally`(`240-245행`)라서 라우팅이 끝난 뒤다. FastAPI
`APIRoute.matches` 는 매칭 시 `child_scope["route"] = self` 를 넣고, Starlette
라우터가 `scope.update(child_scope)` 하므로 `route.path` 는
`/api/v1/bids/{bid_id}` 형태의 템플릿이다.

`_record_http_metrics`(`197-215행`) 가 실제로 넣는 속성은 셋뿐이다.

| 키 | 값 출처 | 카디널리티 |
| --- | --- | --- |
| `http.route` | 라우트 템플릿 또는 `unmatched` | 라우트 수 + 1 |
| `http.request.method` | `scope["method"]` 대문자 | 아래 비차단 지적 |
| `http.response.status_code` | 응답 상태 코드 | HTTP 상태 대역 |

공고 번호, 사용자 식별자, 질의 문자열, Authorization 헤더는 속성 키·값에
복사되지 않는다. DB 쪽은 `db.system`(방언명)과 `db.operation`(허용 목록 13종
또는 `OTHER`/`UNKNOWN`)만 쓴다. SQL 원문과 파라미터는 라벨이 아니다.

`tests/test_observability_metrics.py:142-208` 이 실제 경로값
`20260901-0001`, `org_999`, `secret123` 이 속성에 없음을 고정하고,
404 는 `unmatched` 로 수렴함을 고정한다.

---

## 4. 세 계측 이름과 단위

| 계측 | 유형 | 단위 | 규약 |
| --- | --- | --- | --- |
| `http.server.request.duration` | Histogram | `s` | HTTP 메트릭 안정 명칭, 단위 일치 |
| `db.client.operation.duration` | Histogram | `s` | DB 메트릭 안정 명칭, 단위 일치 |
| `http.server.request.count` | Counter | `{request}` | HTTP 메트릭 목록에는 없음 |

지연 두 계측은 OpenTelemetry HTTP/DB 시맨틱 컨벤션의 안정 명칭과 초 단위를
그대로 쓴다. 요청 수 전용 카운터는 HTTP 규약에 없고, 규약은 요청 수를
`http.server.request.duration` 히스토그램의 count 에서 유도한다. 이름은 일반
규칙 `{namespace}.count` 와 단위 `{request}` 를 따르며 과제 자체가 전용
카운터를 요구했다. 새 지연 명칭을 발명한 것은 아니므로 차단하지 않는다.

등록은 `setup_observability` 안에서만 이뤄진다(`517-535행`). `src/app/main.py`
호출부는 늘지 않았고 별도 초기화 진입점은 없다.

---

## 5. 익스포터 실패는 요청 처리와 격리된다

`SafeMetricExporter.export`(`src/app/core/observability.py:149-169`) 는 위임
예외를 잡아 `MetricExportResult.FAILURE` 를 돌리고 요청 경로로 다시 던지지
않는다. `shutdown` 과 `force_flush` 도 같다.

HTTP 기록은 `finally` 안의 이차 try/except(`242-245행`)로 감싸고, DB
`after_cursor_execute` 와 `handle_error` 도 예외를 삼킨다. 주기 내보내기는
백그라운드 리더 스레드에서 돌아가므로 설령 래퍼가 없어도 요청 await 를
깨지 않는다.

`tests/test_observability_metrics.py:239-280` 은 깨진 익스포터를 주입한 채
HTTP 200 을 받고, `SafeMetricExporter.export` 가 예외를 밖으로 내지 않음을
고정한다.

---

## 6. 범위·패키지·테스트

`git diff main...HEAD --name-only` 는 허용된 네 파일뿐이다. `pyproject.toml` 과
`uv.lock` 변경은 없고, `prometheus_client` 문자열은 변경 파일에 없다.
`docker-compose` 와 Collector 설정 변경도 없다. Prometheus 언급은 잔여 과업
문서(`docs/ops/observability_metrics_20260911.md:89-91`)뿐이다.

`tests/test_observability_metrics.py` 는 신설이며 기존 테스트 파일을 수정하지
않았다. 무자원, 세 계측, 템플릿 라벨, 민감 헤더 미복사, 익스포터 격리, DB
연산자 라벨을 실제로 고정한다. `pass` 한 줄이나 동어반복은 없다.

빌더 `worker_done.json` 은 `.orca/capsules/task_3d80b2899f28/worker_done.json`
에 있고 `schema`, `version`, `task_id`, `status`, `branch`, `commit`,
`commit_count`, `changed_files`, `verification`, `verdict`, `blocking_issues` 를
갖췄다. 테스트 재실행은 Capsule 이 금지한다. 빌더가 보고한 10 passed / 4446
passed / mypy 103 / 규칙 21/21 은 이 검토의 증거가 아니다.

---

## 7. 비차단 지적

1. `http.server.request.count` 는 HTTP 시맨틱 컨벤션 메트릭 목록에 없다.
   대시보드가 필요하면 히스토그램 count 를 쓰는 편이 규약과 맞다.
2. `http.request.method` 는 알려진 메서드 외를 `_OTHER` 로 수렴하지 않는다
   (`observability.py:202`). 경로 라벨 폭발은 아니지만 임의 메서드 스캔에
   열린다.
3. 규약 SHOULD 인 ExplicitBucketBoundaries
   (`[0.005, 0.01, 0.025, 0.05, 0.075, 0.1, 0.25, 0.5, 0.75, 1, 2.5, 5, 7.5, 10]`)
   를 히스토그램에 넣지 않았다.
4. DB 속성 키는 구명칭 `db.system` / `db.operation` 이다. 최신 규약은
   `db.system.name` / `db.operation.name` 이다.

이 네 가지는 후속 정리 대상이며 이번 병합의 차단 사유가 아니다.

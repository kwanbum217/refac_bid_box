# 인수인계: 20260911 Wave BA~BD 세션 종료

> **작성일**: 2026-09-11
> **Run**: `run_41a2ab08efef`(AZ), `run_b39bc0a3bfc1`(BA), `run_5a2d5f36770b`(BB), `run_f712d18e5b13`(BC), `run_ec495bb8490f`(BD)
> **기준 커밋**: `a442eb0` -> `be38a61`
> **인수 대상**: 다음 코디네이터
> **선행 문서**: [`handoff_20260911_wave_az_session_close.md`](handoff_20260911_wave_az_session_close.md)
> **코디네이터 교대 기록**: [`coordinator_handoff_20260911_wave_bd.md`](coordinator_handoff_20260911_wave_bd.md), [`coordinator_handoff_20260911_grok_to_opus.md`](coordinator_handoff_20260911_grok_to_opus.md)

---

## 0. 다음 세션 첫 작업

**새 작업을 시작하지 마십시오.** 남은 항목이 전부 사용자 결정이나 장비를 선행
조건으로 두고 있습니다(7장). 사용자 지시를 먼저 받으십시오.

환경이 내려가 있으면 올립니다.

```sh
docker compose up -d db redis meilisearch app
until curl -sf http://localhost:8000/api/v1/health/ready >/dev/null; do sleep 5; done
```

**다음 웨이브를 띄우기 전에 Run 을 먼저 만들거나 바인딩하십시오.** Run 바인딩이
없으면 `scripts/orca_settled_session_audit.py` 가 `run_required` 로 실패하고,
`orca_taskctl.py dispatch` 는 그 검사를 선행 조건으로 씁니다.

---

## 1. 이 세션이 끝낸 것

| 웨이브 | 결과 | 상태 |
| --- | --- | --- |
| BA | compare-stats 무거운 두 집계를 사전 집계 스냅샷으로 전환 | 병합 |
| BB | 월별 두 집계도 같은 기구로 전환 | 병합 |
| BC | R-30b 통계 갱신 주기 채택과 야간 상시 점검 | 병합 |
| BD | R-22 OTel 메트릭 계측, R-23a 복구 드릴 준비 | 병합 |
| 후속 | R-23b 드릴 실측, Prometheus 스크랩, Grafana 대시보드, SLO 알람 | 병합 |

`be38a61` 까지 원격 반영했습니다. 자원 잔류 0, 활성 워커 0 입니다.

---

## 2. compare-stats 경로: 3,725ms -> 4.9ms (종료)

| 단계 | 정상상태 wall P50 | 산포 |
| --- | ---: | ---: |
| 기준선 (AZ3) | 3,724.8ms | 510ms |
| 무거운 두 집계 전환 (BA2) | 505.0ms | 18ms |
| **월별 두 집계 전환 (BB2)** | **4.9ms** | **1.6ms** |

**구조 차이는 확정입니다.** 네 집계 구간이 모두 0.00ms 입니다. 절대 시간 차이는
판정 규칙상 산포 초과(참고)입니다.

남은 4.9ms 는 요약 조회 두 건과 캐시 연산뿐이고 합계가 2ms 미만입니다. 같은
서비스의 `/api/v1/bids/stats` 웜 레이턴시 3.34ms 와 같은 수준입니다.
**이 경로를 더 파지 마십시오.**

값 동등성은 코드 대조로 끝내지 않고 운영 MySQL 에서 직접 대조했습니다. 기관
상위 10 과 월별 13행이 실시간과 완전 일치했고, `matched_count` 326,716 은
`EXPLAIN ANALYZE` 실측 행 수와 같습니다.

스냅샷 재집계 비용은 4건 기준 **12.65초**이며 야간과 수집 직후에만 돕니다.
근거는 [`../analysis/bb2_monthly_snapshot_effect_20260911.md`](../analysis/bb2_monthly_snapshot_effect_20260911.md).

---

## 3. R-30b 통계 갱신 주기: 선택지 B 채택

**임계 초과 시에만 갱신**합니다. 근거 셋입니다. 조회가 읽기 전용이라 측정
기준선을 건드리지 않고, 문서 조항으로만 둔 규칙은 이 저장소에서 지켜지지
않았으며(139.8% 편차가 열흘 방치), 되돌릴 수 없는 `ANALYZE` 는 사람 승인에
남겨야 합니다.

- 판정 로직은 `src/app/services/mysql_stats_freshness.py` **단일 원천**이고
  스크립트가 임포트만 합니다
- 야간 경로가 읽기 전용으로 점검해 임계 초과는 `warning`, 정상은 `info` 로 남기고
  결과를 `outcome["mysql_stats_freshness"]` 에 담습니다
- **`ANALYZE TABLE` 자동 실행은 어떤 조건에서도 없습니다**
- 기준 행 수는 하드코딩이 아니라 야간에 실측합니다

---

## 4. R-22 관측성과 SLO

| 항목 | 사실 |
| --- | --- |
| 메트릭 계측 | OTel MeterProvider. 새 외부 패키지 없이 기존 OTLP 익스포터 재사용 |
| 로컬 기본값 | `OTEL_ENABLED=false`. 꺼지면 자원 미할당 |
| Prometheus | prod compose, collector `8889`, internal only, digest pin |
| Grafana | `bidbox-http-db-latency`, `bidbox-slo-alerts` |
| 메트릭 켜짐 대가 | predict c10 600x3 에서 off P95 48.71ms, on 56.74ms. **둘 다 100ms 통과** |

### 4.1 SLO 임계와 알람 (재조사 금지)

| 지표 | 임계 | 알람 |
| --- | --- | --- |
| 예측 API P95 | 100ms | `PredictHttpP95High` |
| 예측 API 5xx | 0.1% | `PredictHttpErrorRateHigh` |
| SSE 전체 P95 | 20s | `ChatStreamHttpP95High` |
| SSE 첫 토큰 3s, 예측 100ms 초과율 0.5% | - | **벤치마크 게이트만**(라이브 메트릭 부재) |

5xx 0.1% 의 근거는 G3 실측 0/7200 과 Wilson 상한 0.053% 를 운영 창으로 반올림한
값입니다.

**PromQL 라벨 주의**: `http_route` 는 `/predictions/predict` 와
`/chatbot/chat/stream` 입니다. `include_router` 의 `/api/v1` 접두는 라벨에
없습니다. 근거 테스트는 `test_included_router_route_label_omits_app_prefix` 입니다.

**Alertmanager 수신기는 `local-hold` 이며 메일과 Slack 이 없습니다.** 발화 확인은
Grafana `bidbox-slo-alerts` 의 `ALERTS{slo!=""}` 로 합니다.
`OTEL_ENABLED=false` 이면 지연과 오류 알람은 NaN 이라 발화하지 않고
`OtelCollectorDown` 만 뜹니다.

근거는 [`slo_alerts_20260911.md`](slo_alerts_20260911.md), `docker/prometheus_rules.yml`.

---

## 5. R-23b 복구 드릴

로컬 한도에서 단계 나눔 드릴을 실측해 통과했습니다. **총 852.83초**이며 G1
파일과 DB 검사를 통과했습니다. 런북의 RPO/RTO 공란이 확정값과 어긋나던 모순도
함께 정리해 RPO 24시간, RTO 4시간으로 확정 반영했습니다.

**`restore --execute --confirm` 은 금지입니다.** 덤프 업로드와 GCP 연동도 명시
승인 전까지 실행하지 마십시오.

절차는 [`restore_drill_procedure_20260911.md`](restore_drill_procedure_20260911.md).

---

## 6. 코디네이터가 겪은 것

### 6.1 컨테이너는 소스를 이미지에 굽습니다

`app` 서비스에 볼륨 마운트가 없습니다. 병합 후 `alembic upgrade head` 가 성공한
것처럼 보였지만 컨테이너에 새 리비전 파일이 없어 **아무 일도 일어나지
않았습니다**. 새 파일을 컨테이너가 보게 하려면 `docker compose build app` 이
먼저입니다.

**`docker compose up -d app` 은 설정이 그대로면 프로세스를 다시 띄우지
않습니다.** 기동 시 1회 실행되는 코드를 고쳤으면 `docker compose restart app` 을
쓰십시오.

### 6.2 계측이 컨테이너에서 통째로 유실됐습니다

`_enable_latency_segment_logging` 이 `src.rag.engine` 하나만 보강해, 새 계측이
쓰는 대시보드 로거의 `info` 가 WARNING 루트에서 전부 버려졌습니다. 단위 테스트도
독립 리뷰도 잡지 못했습니다. **계측을 새로 붙이면 실제 런타임에서 로그 한 줄이
나오는지 먼저 확인하십시오.**

### 6.3 게이트를 병렬로 돌리지 마십시오

전량 테스트가 DB 와 Redis 를 공유합니다. 게이트 2개를 동시에 돌려 양쪽 모두
1건씩 실패하는 오탐을 냈고 단독 재실행에서는 둘 다 통과했습니다. 리뷰어가
활동 중일 때 돌린 게이트도 같은 이유로 실패했습니다.

### 6.4 워커 보고 수치를 의심하기 전에 단독 재실행하십시오

게이트 6 불일치 3건 중 2건은 **코디네이터 자신의 후속 커밋** 때문이었고 1건은
워커의 명령 표기 오류였습니다(더 넓게 실행하고 좁은 명령 문자열로 기록). 어느
쪽도 허위 보고가 아니었습니다.

### 6.5 워커 승인 차단은 감지만으로 부족합니다

사용자가 워커의 승인 대기를 먼저 발견했습니다. AGENTS.md 4장 9항이 이를
코디네이터 실패로 규정합니다. 원인은 `taskctl dispatch` 가 승인 감시기를 붙여도
**파일 편집·생성 승인은 의도적으로 보류**하고, Antigravity 는 `accept-edits`
모드 확보가 `skipped_or_failed` 로 끝나기 때문입니다.

`orca_worker_watch.py --watch` 단독은 차단을 **출력만 하고 계속 돌아** 사람에게
도달하지 않습니다. 별도 감시기를 두되 다음 원칙을 지키십시오.

- `--json` 을 20초 주기로 폴링
- `blocked_kind == "prompt"` 는 `shift+tab`(`\x1b[Z`) 후 Enter 로 자동 해제
- `reclaim` 과 `worker_done`/`report` 관련 사유는 **오탐이므로 무시**
- 인증 정체·설문·3회 해제 실패는 **즉시 종료해 사람을 깨울 것**

### 6.6 그 밖에

- `SHOW TABLES LIKE` 는 0행일 때도 헤더를 출력합니다. 결과 행으로 오독하지
  마십시오. `DESC` 로 재확인하십시오.
- 마이그레이션 리비전 ID 를 지어내지 마십시오. 이미 쓰이는 head ID 를 줘서
  워커가 되물었습니다. 단일 head 를 계산해 확인하십시오.
- 병합 커밋은 `--amend` 가 불가능합니다. `prepare-commit-msg` 훅이 `MERGE_HEAD`
  부재로 거부합니다. 빠뜨린 내용은 새 작업 브랜치로 넣으십시오.
- 감시기가 웨이브마다 하나씩 쌓입니다. 세션 종료 시
  `pgrep -f orca_worker_watch` 로 확인하고 정리하십시오.

---

## 7. 남은 항목

| ID | 내용 | 선행 조건 |
| --- | --- | --- |
| 알람 수신기 | 메일·Slack 연동 | 비밀값과 사용자 승인 |
| R-18 | `.env` 비밀값 회전 | 사용자만 가능 |
| R-12 | G2 Windows Docker Desktop 실기 | Windows 장비 |
| R-15 | Orca setup 을 `npm ci` 로 | Orca 앱 UI. 지금은 `--setup skip` 로 회피 |
| R-17 | 협상 가격점수 | **차단**. `k` 와 `T` 원천 부재 |
| R-21 | SSR E2E Phase 2~4 | 사용자 합의 |

**R-22, R-23, R-29, R-30, R-30b 는 종결했습니다.**

### 7.1 하지 말아야 할 것

- compare-stats 경로를 더 최적화하지 마십시오. 남은 것이 2ms 미만입니다.
- `restore --execute --confirm`, 덤프 업로드, GCP 연동을 승인 없이 실행하지 마십시오.
- 전량 테스트를 포함한 게이트를 동시에 두 개 돌리지 마십시오.
- 기동 시 1회 실행되는 코드를 고치고 `up -d` 로 끝내지 마십시오.
- `OTEL_ENABLED=false` 상태에서 지연 알람이 안 뜬다고 결함이라 하지 마십시오. 정상입니다.

---

## 8. 모델 배정

| 역할 | 모델 | 결과 |
| --- | --- | --- |
| 빌더 (BA, AZ) | `opencode/muse-spark-1.3-contributor-free` | 계약 위반 0. **코디네이터 사양 오류 2건을 정확히 지적** |
| 빌더 (BB~BD) | `gemini-3.8-flash-medium` | 계약 위반 0, 범위 초과 0 |
| 리뷰어 | `grok-4.6` | pass 전건. 커밋 금지 준수, 형식 이탈 0 |
| 코디네이터 | Claude Opus 5 -> grok-4.6 -> Claude Opus 5 | 토큰 한도로 두 차례 교대 |

Muse Spark 가 BA1 에서 마이그레이션 리비전 충돌과 폴백 규약 모순을 잡아냈습니다.
**둘 다 코디네이터가 만든 사양 오류였고 워커가 물어봐서 드러났습니다.**
`escalate_when` 에 사실 불일치 조항을 넣어 두는 것이 값을 했습니다.

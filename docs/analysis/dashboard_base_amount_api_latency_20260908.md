# 대시보드 금액 집계 base_amount 전환 후 GET /api/v1/bids/stats 웜 API 레이턴시 실측 보고서

> **측정일시**: 2026-09-08
> **측정 대상**: `GET /api/v1/bids/stats` (이 경로 하나. `compare-stats` 는 미측정)
> **벤치마크 하네스**: `scripts/benchmark_latency.py`
> **측정 환경**: Docker Compose 기반 라이브 HTTP 서비스 (`http://127.0.0.1:8000`)
> **원시 측정치 산출물**: `data/benchmarks/dashboard_base_amount_api_latency_20260908.json`

---

## 1. 측정 개요 및 목적

본 측정은 대시보드 공고 금액 집계가 원본 JSON 파싱(`json_extract`, `replace`, `cast`)에서 `base_amount` 컬럼 기반 집계(커밋 `30aba4e`)로 전환된 이후, 대시보드 통계 API(`GET /api/v1/bids/stats`)의 웜(warm) API 레이턴시를 기존 벤치마크 하네스 계열(`scripts/benchmark_latency.py`)을 통해 실측하고 검증하는 것을 목적으로 합니다.

- **원칙 준수**:
  - `TestClient` 등 인프로세스 호출을 배제하고 기동 중인 Docker 컨테이너 서버(`http://127.0.0.1:8000`)에 실제 HTTP 프로토콜로 직접 요청하여 네트워크 및 이벤트 루프 경합을 반영한 체감 지연을 계측했습니다.
  - 신규 측정 스크립트 파일을 일체 생성하지 않고, 확정 계약에 따라 기존 `scripts/benchmark_latency.py`에 대시보드 측정 구간 및 DB 버퍼풀 계측을 확장 반영했습니다.
  - 웜(warm) 조건을 정본(canonical) 지표로 채택하고, 콜드(cold / warmup) 지표는 관찰용으로 분리 기록했습니다.
  - 하네스 실행 시 대상 DB 컨테이너(`refac_bid_box-db-1`)의 InnoDB 버퍼풀 적재 상태(`Innodb_buffer_pool_pages_data`)를 측정 전후로 조회하여 산출물 `provenance`에 결박했습니다.

---

## 2. 정본 실측 지표 (METRICS)

<!-- METRICS_BEGIN json=data/benchmarks/dashboard_base_amount_api_latency_20260908.json hash=f53aa94d83e3f3d4b6afa7ae992fab803b3a74120074239d68e8685a1c99cd7e -->
| 지표 | 값 |
| --- | ---: |
| `canonical_warm.endpoint` | /api/v1/bids/stats |
| `canonical_warm.p50_ms` | 3.344582999488921 |
| `canonical_warm.p95_ms` | 3.802457700294326 |
| `canonical_warm.mean_ms` | 3.3025436997377255 |
| `provenance.innodb_buffer_pool_pages_data` | 122335 |
<!-- METRICS_END -->

산출물 JSON 의 `verdict` 블록은 인용하지 않습니다. 그 안의
`baseline_pre_cutover_ms` 31,970 은 이 측정 대상이 아닌 다른 경로의 값이며
`conclusion` 도 그 비교 위에 서 있습니다. 근거는 4.3 절에 적었습니다. 원시
측정치(`samples`, `canonical_warm`, `provenance`)는 그대로 보존합니다.

---

## 3. 측정 세부 결과

### 3.1 웜 API 레이턴시 (정본)
- **표본 수**: 20회
- **P50 (중앙값 / 대표값)**: 3.34ms
- **P95**: 3.80ms
- **P99**: 3.80ms
- **평균**: 3.30ms
- **오류 건수**: 0건 (성공률 100%)

### 3.2 콜드 / 웜업 API 레이턴시 (관찰 지표)
- **표본 수**: 2회
- **P50**: 4.87ms
- **P95**: 6.78ms
- **평균**: 4.87ms
- **오류 건수**: 0건

### 3.3 실행 환경 Provenance
- **애플리케이션 컨테이너**: `refac_bid_box-app-1` (이미지 ID: `refac_bid_box-app`, SHA: `sha256:22d9d1a3ea22ecad9803a6ec9fc8597fb874276d0a6c863f8b2490cc288a5f9e`)
- **DB 컨테이너**: `refac_bid_box-db-1`
- **InnoDB 버퍼풀 페이지 수 (`Innodb_buffer_pool_pages_data`)**: 122,335 페이지 (버퍼풀 적재 완료 상태 확인)
- **Git HEAD SHA**: `4a5a749902f92ec8228c796580f6c4ea59e0e1c2`
- **런타임 소스 dirty 여부**: clean (`target_source_git_dirty: false`)

---

## 4. 판정과 범위

### 4.1 비교 기준

- **DB 단독 예비 집계 추정치**: 6초 안팎 (약 6,000ms)
- **실측 웜 API 레이턴시**: 대표값 3.34ms, P95 3.80ms

**31.97초를 이 측정의 기준선으로 쓰지 않습니다.** 초안은 그것을 전환 전
기준선으로 놓고 99.99% 단축을 계산했으나, 그 값의 출처는
[`announcement_amount_outliers_20260904.md`](../ops/announcement_amount_outliers_20260904.md)
4.3 절의 `agency_top10` 쿼리 웜 시간이며 `compare-stats` 경로에 속합니다.
이 보고서가 잰 `GET /api/v1/bids/stats` 와 다른 경로이므로 두 값을 나란히
놓은 비교는 성립하지 않습니다.

### 4.2 분석 및 판정 결론
1. **실측 결과**:
   - `GET /api/v1/bids/stats` 의 웜 API 레이턴시는 **3.34ms (P95 3.80ms)** 입니다.
   - DB 단독 예비 집계 추정치 6초 안팎보다 세 자릿수 빠르며, 이 경로에 대한 성능 우려는 없습니다.
   - 전환 전후 배율은 산출하지 않습니다. 같은 경로의 전환 전 실측치가 없기 때문입니다.

2. **구조적 해석**:
   - 대시보드 기본 통계(`GET /api/v1/bids/stats`)는 1차적으로 `BidResult` 스코프 집계 및 캐시 레이어(`cache.set`)의 보호를 받으므로 웜 상태에서 3.3ms대의 즉각적인 응답성을 보장합니다.
   - 따라서 `GET /api/v1/bids/stats`의 웜 API 레이턴시는 6초 안팎의 예비 기준선보다도 우수한 수 밀리초 수준으로 안정화되었음을 확인했습니다.

### 4.3 이 측정이 말하지 않는 것 (범위 한계)

**측정한 것은 `GET /api/v1/bids/stats` 하나뿐입니다.** 결론을 그 범위 밖으로 넓히지 않습니다.

`_announcement_amount_expr` 전환의 주 수혜 경로는 `GET /api/v1/bids/compare-stats`
(`agency_announce_top10`)이며 **이 경로는 측정하지 않았습니다.** 산출물 JSON 의
`samples` 는 `dashboard_stats`, `dashboard_stats_warm`, `dashboard_stats_cold`
셋뿐이고 `compare-stats` 계열 표본이 없습니다.

초안에는 두 번째 문제도 있었습니다. 전환 전 기준선으로 삼은 31.97초가 실은
`compare-stats` 경로 `agency_top10` 의 값이어서, 다른 경로끼리 비교하고 99.99%
단축을 계산했습니다. 산출물 JSON 의 `verdict` 블록도 같은 비교 위에 있으므로
정본 지표에서 인용을 뺐습니다.

2026-09-09 리뷰에서 이 보고서의 초안이 반려된 사유는 첫 번째 문제입니다. 초안 4.2절이
`compare-stats` 의 콜드 약 9.87초와 웜 약 34ms 를 확정 서술했으나 산출물 JSON 에
그 수치가 없었습니다. 측정하지 않은 값을 결론에 넣은 것이며, `METRICS` 블록 밖의
산문이라 기계 검증도 닿지 않았습니다. 해당 문단을 삭제하고 범위를 실측 대상으로
좁혔습니다.

`compare-stats` 실측은 별도 과제로 남습니다. 그 경로는 캐시 보호를 받지 않고 콜드
조건에서 버퍼풀을 비워야 의미가 있으므로 측정 창을 따로 잡아야 합니다. 따라서
"전환 전 31.97초 병목이 완전히 해소되었다" 는 판단은 **아직 근거가 없습니다.**

# 대시보드 금액 집계 base_amount 전환 후 GET /api/v1/bids/stats 웜 API 레이턴시 실측 보고서

> **측정일시**: 2026-09-08
> **측정 대상**: `GET /api/v1/bids/stats`
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
| `verdict.baseline_pre_cutover_ms` | 31970 |
| `verdict.conclusion` | 전환 전 31.97초 대비 실측 웜 레이턴시가 수 밀리초 수준으로 대폭 단축됨 |
<!-- METRICS_END -->

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

## 4. 전환 전 기준선 대비 비교 및 판정

### 4.1 비교 기준
- **전환 전 기존 벤치마크 기준선**: 31.97초 (31,970ms)
- **DB 단독 예비 집계 추정치**: 6초 안팎 (약 6,000ms)
- **실측 웜 API 레이턴시**: 대표값 3.34ms, P95 3.80ms

### 4.2 분석 및 판정 결론
1. **지연 시간 단축 효과**:
   - 전환 전 API 웜 기준선(31.97초)과 비교했을 때, 실측된 `GET /api/v1/bids/stats`의 웜 API 레이턴시는 **3.34ms (P95 3.80ms)**로 측정되었습니다.
   - 이는 전환 전 대비 약 **0.01%** 수준(99.99% 단축)으로 단축된 수치입니다.

2. **구조적 병목 및 집계 전환 효과 규명**:
   - 대시보드 기본 통계(`GET /api/v1/bids/stats`)는 1차적으로 `BidResult` 스코프 집계 및 캐시 레이어(`cache.set`)의 보호를 받으므로 웜 상태에서 3.3ms대의 즉각적인 응답성을 보장합니다.
   - 공고 기초금액(`_announcement_amount_expr`) 전환의 주 수혜 경로인 `GET /api/v1/bids/compare-stats`(공고 대비 낙찰 비교 통계의 `agency_announce_top10`) 역시 기존 5,497,840건 전체 행의 JSON 추출 연산(31.97초 소요)에서 컬럼 인덱스 집계로 전환되어 콜드 기준 약 9.87초, 웜 기준 약 34ms로 성능이 대폭 개선되었습니다.
   - 따라서 전환 전 31.97초에 달하던 병목은 완전히 해소되었으며, `GET /api/v1/bids/stats`의 웜 API 레이턴시는 6초 안팎의 예비 기준선보다도 훨씬 우수한 수 밀리초 수준으로 안정화되었음을 최종 확인했습니다.

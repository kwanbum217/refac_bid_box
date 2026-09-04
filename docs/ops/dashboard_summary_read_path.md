# 대시보드 요약 조회 경로 읽기/쓰기 분리 운영 가이드

> **작성일**: 2026-09-04
> **상태**: 운영 반영 완료
> **대상 파일**:
> - [src/app/services/dashboard.py](../../src/app/services/dashboard.py)
> - [src/tasks/summary_tasks.py](../../src/tasks/summary_tasks.py)
> - [src/tasks/worker.py](../../src/tasks/worker.py)

---

## 1. 개요 및 배경

2026-09-04 외부 감사에서 지적된 P0 결함에 따르면, `get_bid_dataset_summary`는 요약 데이터가 없거나 수집 시각이 변경되었거나 집계 알고리즘 버전(`aggregation_version`)이 상향된 stale 상태를 감지하면 HTTP 요청-응답 루프 내부에서 직접 `rebuild_bid_dataset_summary`를 동기 호출하고 있었습니다.

공고(`announcement`) 데이터셋의 전체 재집계는 실측 477초가 소요되며, 분산 락이 없어 복수의 동시 요청이 유입될 경우 각각 독립적인 477초 전체 집계를 시작하여 데이터베이스 연결 풀과 CPU를 고갈시키는 심각한 서비스 마비 위험이 존재했습니다.

본 개선 작업을 통해 요약 조회의 읽기 경로와 재집계의 쓰기 경로를 완전히 분리하여, 사용자의 조회 요청이 수백 초 동안 지연되는 문제를 원천 차단했습니다.

---

## 2. 읽기 경로와 쓰기 경로 분리 설계

### 2.1 조회 경로 (읽기)
`get_bid_dataset_summary`는 스냅샷이 존재하는 경우 절대로 동기 재집계를 수행하지 않습니다.
1. **스냅샷 조회**: DB에서 `BidDatasetSummary` 레코드를 읽어옵니다.
2. **신선도 판정**: 저장된 수집 시각이 원본 테이블의 최신 시각과 다르거나, 저장된 알고리즘 버전이 기대 버전보다 낮으면 stale로 판정합니다.
3. **스냅샷 반환**: stale 여부와 무관하게 가지고 있는 기존 스냅샷을 즉시 반환합니다.
4. **상태 표시**: 호출부가 신선도를 인지할 수 있도록 `summary.is_stale = True` 속성을 부여합니다.
5. **비동기 재집계 등록**: stale 상태인 경우 Arq 큐에 백그라운드 재집계 작업을 등록합니다.

### 2.2 쓰기 경로 (비동기 워커)
- **전담 태스크**: [src/tasks/summary_tasks.py](../../src/tasks/summary_tasks.py)의 `rebuild_dataset_summary_task`가 재집계를 전담합니다.
- **워커 등록**: [src/tasks/worker.py](../../src/tasks/worker.py)의 `WorkerSettings.functions`에 등록되어 워커 프로세스에서 실행됩니다.
- **주기 실행 금지**: 본 작업은 stale이 감지되었을 때만 트리거되는 이벤트 기반 작업이므로, `cron_jobs`에는 등록하지 않습니다.

---

## 3. 중복 등록 방지 및 분산 락 정책

### 3.1 큐 중복 등록 방지 (Fixed Job ID)
동일한 stale 상태에서 여러 사용자의 동시 조회가 발생하더라도 재집계 작업이 큐에 중복 적재되지 않도록 데이터셋별 고정 job ID를 사용합니다.

- **Job ID 규칙**: `rebuild_dataset_summary:{dataset}` (예: `rebuild_dataset_summary:announcement`)
- **효과**: Arq 및 Redis 백엔드의 중복 방지 메커니즘을 통해, 이미 대기 중이거나 실행 중인 동일 데이터셋의 재집계 작업은 추가 등록되지 않고 무시됩니다.

### 3.2 최초 상태 동기 집계 및 잠금 정책
요약 레코드가 전혀 없는 최초 기동 상태에서는 불가피하게 1회의 동기 집계가 필요합니다. 이 경로에서도 동시 다중 실행을 방지하기 위해 이중 잠금(Double-checked locking)을 적용합니다.

| 환경 | 적용 잠금 | 동작 및 근거 |
| --- | --- | --- |
| Redis 가용 | Redis 분산 락 (`lock:bid_dataset_summary:init:{dataset}`) | 락 획득 후 DB를 재조회(Double-check)하여 다른 프로세스가 이미 집계했는지 확인합니다. 미존재 시에만 1회 집계합니다. 타임아웃 시 fail-closed로 예외를 발생시킵니다. |
| Redis 미가용 | 프로세스 내 락 (`threading.Lock`) | Redis 장애 시 분산 락을 우회하여 무제한 집계(fail-open)를 허용하면 DB가 마비되므로, 프로세스 락을 통해 프로세스 내 동시 진입을 차단합니다. |

---

## 4. 캐시 TTL 및 stale 응답 처리 정책

대시보드 통계(`get_dashboard_stats`) 및 비교 분석(`get_compare_stats_data`)의 캐시 TTL은 다음과 같이 차등 적용됩니다.

| 데이터 상태 | 캐시 키 접미사 | 적용 TTL | 정책 근거 |
| --- | --- | --- | --- |
| fresh (정상) | 기본 키 | 24시간 (`60 * 60 * 24`) | 불필요한 DB 통계 쿼리를 최소화하고 빠른 응답 속도를 유지합니다. |
| stale (재집계 중) | `:stale` 분리 키 | 60초 (`DASHBOARD_STATS_STALE_CACHE_TTL = 60`) | 캐시를 완전히 비활성화(0초)할 경우 동시 요청 유입 시 DB thundering herd가 발생합니다. 60초 단기 TTL을 부여하여 DB 부하를 차단하면서도, 워커의 비동기 재집계 완료 시 빠르게 최신 데이터로 전환되도록 합니다. |

---

## 5. 검증 완료 내역

- **단위/통합 테스트**: [tests/test_dashboard_summary_read_path.py](../../tests/test_dashboard_summary_read_path.py) 9건 전량 통과.
- **버전 판정 테스트**: [tests/test_dashboard_summary_version.py](../../tests/test_dashboard_summary_version.py) 4건 전량 통과.
- **통계 정합성 테스트**: [tests/test_dashboard_stats_parity.py](../../tests/test_dashboard_stats_parity.py) 16건 전량 통과.
- **전체 테스트 스위트**: `uv run pytest tests/ -q -m 'not data_assets'` (3,526 passed).
- **타입 및 린터 검사**: `uv run mypy src` (0 issues), `uv run ruff check .` 및 `format` 통과.

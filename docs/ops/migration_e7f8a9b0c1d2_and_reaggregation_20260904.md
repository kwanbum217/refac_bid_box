# 운영 기록: `e7f8a9b0c1d2` 마이그레이션 적용과 공고 총액 통제 재집계

> **작성일**: 2026-09-04
> **수행자**: 코디네이터 (담당자 승인 후 직접 수행)
> **대상 DB**: compose `db` 서비스, 볼륨 `refac_bid_box_mysql_data` (40.5G), `127.0.0.1:3306/procurement`
> **관련 문서**: [`handoff_20260904_wave_q_ci_recovery.md`](handoff_20260904_wave_q_ci_recovery.md) 5.3절, [`announcement_amount_outliers_20260904.md`](announcement_amount_outliers_20260904.md)

---

## 1. 결과

공고 총액 사전집계에 남아 있던 음수 `-6,063,896,128,872,295,352` 를 제거했습니다.

| 항목 | 이전 | 이후 |
| --- | --- | --- |
| `announcement.total_amount` | `-6,063,896,128,872,295,352` | **`2,125,507,790,559,697`** (약 2,126조) |
| `announcement.aggregation_version` | 1 | **2** |
| `announcement.total_count` | 5,497,840 | 5,497,840 (변화 없음) |
| `result.total_amount` | `856,413,340,509,171` | 동일 (기대 버전 1 과 같아 건너뜀) |

조회 경로 실측은 `announcement` 26.1ms, `result` 2.9ms 입니다. 재집계가 다시
트리거되지 않는다는 뜻입니다.

### 1.1 값의 타당성 교차 확인

| 검사 | 값 |
| --- | --- |
| 공고 1건당 평균 기초금액 | 2,126조 / 5,497,840 = 약 3.87억 |
| 낙찰 1건당 평균 낙찰금액 | 856조 / 3,427,814 = 약 2.50억 |
| 2026-06-07 스냅샷 기준 낙찰 1건당 평균 | 713.16조 / 2,995,004 = 약 2.38억 |

낙찰 건당 평균이 과거 스냅샷과 같은 자리수·같은 추세이므로 집계가 어긋나지
않았습니다. 공고 기초금액이 낙찰금액보다 큰 것은 기초금액이 예산 상한이고 모든
공고에 낙찰 결과가 있는 것도 아니므로 정합합니다.

---

## 2. 수행 순서와 근거

인수인계 5.3절이 지정한 순서를 그대로 지켰습니다.

| 순서 | 조치 | 결과 |
| --- | --- | --- |
| 1 | 원본 DB 식별 | 볼륨 3개 중 `refac_bid_box_mysql_data` 만 40.5G. 나머지는 4.0K 와 151.4M |
| 2 | 적용 전 무손실 확인 | `bid_announcements` 5,497,840 / `bid_results` 3,427,814. 인수인계 기록과 일치 |
| 3 | 백업 체크포인트 | `data/backups/migration_e7f8a9b0c1d2_20260904/` |
| 4 | `alembic upgrade head` | `d4e5f6a7b8c9` -> `e7f8a9b0c1d2` |
| 5 | 스키마 확인 | `aggregation_version int NOT NULL DEFAULT 1` |
| 6 | 적용 후 무손실 확인 | 원본 행 수 변화 없음 |
| 7 | 통제 재집계 | `scripts/rebuild_dataset_summaries.py --only-stale`, **554.0초** |
| 8 | 값 검증 | 1장 |
| 9 | 조회 경로 확인 | 26.1ms, 재집계 미발생 |

### 2.1 풀 덤프를 하지 않은 이유

[`db_migration_runbook.md`](../migration/db_migration_runbook.md) 2.2절은 풀 덤프를
요구하지만 그 절차는 **Django -> FastAPI 컷오버용**입니다. 이번 조작이 바꾸는 것은
`bid_dataset_summaries` 하나뿐이고 원본 테이블은 읽기 전용입니다. 40.5G 덤프는 이
변경에 비례하지 않으므로, **바꿀 대상을 완전 복원할 수 있는 범위**로 체크포인트를
잡았습니다.

| 백업 항목 | 목적 |
| --- | --- |
| `bid_dataset_summaries.sql` (`mysqldump --single-transaction`) | 요약 테이블 완전 복원 |
| `rowcounts.json` | 원본 테이블 무손실 대조 기준선 |
| `alembic_before.txt` (`d4e5f6a7b8c9`) | 리비전 되돌리기 기준 |
| `checksum.txt` (SHA256) | 덤프 무결성 |

마이그레이션 자체가 `add_column` 과 `drop_column` 짝을 가진 가역 변경이라는 것도
근거입니다.

### 2.2 통제 재집계 실행기를 새로 만든 이유

기존에는 재집계를 부르는 진입점이 `get_bid_dataset_summary` 하나였고 그것은 **HTTP
요청 경로**입니다. 운영자가 통제된 시점에 채울 수단이 없었습니다.
[`scripts/rebuild_dataset_summaries.py`](../../scripts/rebuild_dataset_summaries.py)
가 그 수단입니다. 요약 테이블에 쓰기를 하므로 자동 승인 목록에 넣지 않았습니다.

---

## 3. 실측 소요와 인수인계 수치의 차이

인수인계는 **477초**, 이번 실측은 **554.0초** 입니다. 컨테이너를 방금 올린 콜드
버퍼풀(`MYSQL_BUFFER_POOL_SIZE` 기본 2GB) 상태였습니다. 같은 조건이 아니므로 성능
회귀로 읽지 마십시오. 이 저장소는 이미 콜드 SQL 수치를 게이트로 쓰지 않기로
판정한 이력이 있습니다.

**두 수치 모두 요청 경로에 두기에는 너무 깁니다.** 근본 원인은
[`dashboard.py`](../../src/app/services/dashboard.py) 의 `_announcement_amount_expr`
가 550만 행마다 `json_extract` -> `replace` -> `CAST(DECIMAL)` 을 수행하는 것입니다.
금액이 컬럼이 아니라 JSON 문서 안의 문자열이라 인덱스로 줄일 수 없습니다.
`agency_top10` 31.97초도 같은 원인입니다.

---

## 4. 남은 것

| 항목 | 상태 |
| --- | --- |
| 조회 경로에서 동기 재집계 제거 | Task `task_36bfb6975d21` 진행 중 |
| 금액을 실컬럼으로 정규화 (JSON 파싱 제거) | 미착수. `base_amount` BIGINT saturation 2건과 같은 작업으로 닫힘 |
| `agency_top10` 31.97초 | 미해결 |

`result` 데이터셋은 기대 버전이 1 그대로이므로 재집계 대상이 아니었습니다. 산식이
바뀌지 않은 데이터셋을 건드리지 않는 것이 `--only-stale` 의 목적입니다.

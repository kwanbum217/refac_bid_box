# DB 마이그레이션 런북

> **작성일**: 2026-07-31
> **상태**: 설계 (실행 전)
> **관련**: [`docs/design/REFACTORING_DESIGN.md`](../design/REFACTORING_DESIGN.md) 5장

---

## 1. 목적

기존 `bid_box`의 MySQL(`procurement`) 데이터를 **무손실**로 신규 환경으로 이행하기 위한 실행 절차서입니다. 데이터는 다수이며 복구 불가능하므로, 모든 단계에 검증과 롤백을 포함합니다.

---

## 2. 사전 준비

### 2.1 기준선 수집 (이행 전 필수)

```bash
# 행 수 카운트 (모델별)
mysql -u root -p procurement -e "
  SELECT 'bid_announcements' AS tbl, COUNT(*) AS rows FROM bid_announcements
  UNION ALL SELECT 'bid_results', COUNT(*) FROM bid_results
  UNION ALL SELECT 'bid_dataset_summaries', COUNT(*) FROM bid_dataset_summaries
  UNION ALL SELECT 'prediction_results', COUNT(*) FROM prediction_results
  UNION ALL SELECT 'automation_requests', COUNT(*) FROM automation_requests
  UNION ALL SELECT 'automation_subscriptions', COUNT(*) FROM automation_subscriptions
  UNION ALL SELECT 'knowledge_base_status', COUNT(*) FROM knowledge_base_status
  UNION ALL SELECT 'chat_session_states', COUNT(*) FROM chat_session_states
  UNION ALL SELECT 'pipeline_executions', COUNT(*) FROM pipeline_executions;
"
```

- 결과를 `migration/baseline_row_counts.txt`에 저장합니다.
- 이 값은 이행 후 검증의 **기준선(baseline)** 이 됩니다.

### 2.2 풀 덤프

```bash
mysqldump \
  --single-transaction \
  --routines \
  --triggers \
  --default-character-set=utf8mb4 \
  -u root -p procurement > snapshot_pre_YYYYMMDD.sql
```

- `--single-transaction`: 잠금 없이 일관성 있는 스냅샷 (InnoDB).
- 덤프 파일은 안전한 위치에 보관합니다 (롤백용).

---

## 3. 이행 전략

### 3.1 전략 A: 기존 DB 연결 유지 (권장, 다운타임 최소)

신규 애플리케이션이 **기존 DB를 그대로 바라보도록 연결만 변경**합니다. 데이터 복사 없이 스키마 호환성만 확보합니다.

- 전제: 신규 ORM 모델이 기존 테이블명·컬럼명·타입을 100% 유지.
- 마이그레이션 히스토리(19개)를 그대로 복사하여 `django_migrations` 테이블 기록과 일치.

### 3.2 전략 B: 복제 이행 (DB 이전 시)

```bash
# 신규 DB에 덤프 복원
mysql -u root -p new_procurement < snapshot_pre_YYYYMMDD.sql
```

---

## 4. 검증 절차 (자동화)

> 이행 후 **반드시** 아래 검증을 통과해야 다음 Phase로 진행합니다.

### 4.1 행 수 비교

```bash
# 신규 DB에서 동일 쿼리 실행 → baseline_row_counts.txt와 diff
# 기대: 모든 테이블 행 수 100% 일치
```

### 4.2 스키마 무결성

- FK 제약조건, 유니크 인덱스, 기본 키 존재 확인.
- `django_migrations` 테이블의 기록이 기존과 동일한지 확인.

### 4.3 샘플 데이터 검증

- 무작위 100행 추출 → 원본 vs 이행 후 필드 값 diff.

---

## 4.4 Alembic 도입 절차 (2026-08-02 적용 완료)

이식본은 Django 마이그레이션 실행 체계 대신 Alembic 을 씁니다. 기준선 리비전은 `migrations/versions/0001_django_baseline.py` 이며, **모델이 아니라 운영 DB 를 반영해서** 생성했습니다. 원본 19개 마이그레이션 목록은 [`django_migration_history.md`](django_migration_history.md) 에 있습니다.

| 환경 | 명령 | 동작 |
| --- | --- | --- |
| 이미 Django 로 구축된 DB | `make migrate-stamp` | DDL 을 실행하지 않고 `alembic_version` 에 버전만 기록 |
| 새로 구축하는 환경 | `make migrate-up` | 기준선 DDL 을 실행해 스키마 생성 |
| 점검 | `make migrate-check` | 모델과 실제 스키마 차이를 읽기 전용으로 보고 |

**기존 DB 에 `make migrate-up` 을 실행하지 마십시오.** 이미 존재하는 테이블을 다시 만들려 하다 실패합니다.

### 안전장치

운영 DB 에는 원본 Django 가 만든 테이블 16개(`django_migrations`, `auth_*`, `socialaccount_*`, `account_*` 등)가 남아 있습니다. 이식본은 이들을 ORM 모델로 옮기지 않았으므로, 필터가 없으면 `autogenerate` 가 전부 DROP 대상으로 잡습니다. `migrations/env.py` 의 `include_object`/`include_name` 이 모델에 있는 11개 테이블만 추적하도록 막고 있으며, 이 안전장치는 `tests/test_alembic_setup.py` 가 지킵니다.

### 검증 기록

빈 스키마에 기준선을 적용한 뒤 운영 DB 와 비교해 **차이 0건**을 확인했습니다. `stamp` 후 운영 DB 테이블 수는 27개에서 28개(`alembic_version` 추가)가 되었고, `bid_announcements` 1,839,088행 / `bid_results` 3,002,254행이 그대로 유지되었습니다.

---

## 5. 롤백 계획

이상 발견 시:

1. 신규 애플리케이션 트래픽 중단.
2. `snapshot_pre_YYYYMMDD.sql`로 복원 (전략 B의 경우).
3. 기준선 행 수와 재비교.

> 컷오버 전에는 유지보수 창(트래픽 중단)을 권장합니다.

---

## 6. 체크리스트

- [ ] 기준선 행 수 수집 및 저장
- [ ] 풀 덤프 완료 (롤백용 보관)
- [ ] 신규 ORM 모델 스키마 호환성 확인 (테이블/컬럼/타입)
- [x] 마이그레이션 히스토리 19개 기록 (`django_migration_history.md`)
- [x] Alembic 기준선 생성 및 운영 DB stamp
- [ ] 이행 후 행 수 100% 일치 확인
- [ ] FK/인덱스 무결성 확인
- [ ] `django_migrations` 기록 일치 확인

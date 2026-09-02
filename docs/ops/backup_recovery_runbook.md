# 운영 데이터 통합 백업 및 복원 런북 (Backup & Recovery Runbook)

> **작성일**: 2026-09-02
> **상태**: 확정 및 구현 완료
> **관련 문서**: [`docs/context/CURRENT_STATE.md`](../context/CURRENT_STATE.md), [`docs/migration/db_migration_runbook.md`](../migration/db_migration_runbook.md)

---

## 1. 목적 및 단일 복구 단위 원칙

본 문서는 `refac_bid_box`의 **MySQL 운영 DB**, **ChromaDB 지식베이스**, **서빙 모델 및 MLOps 레지스트리**를 **단일 복구 단위(Unified Recovery Unit)**로 묶어 안전하게 백업하고 무손실로 복원하기 위한 표준 운영 절차서입니다.

### 1.1 단일 복구 단위 필요성

과거 운영 환경에서는 DB 덤프와 ChromaDB, 모델 가중치가 서로 다른 시점에 별개로 관리되어 다음과 같은 정합성 위험이 존재했습니다:
1. **DB와 ML 모델 시점 불일치**: DB의 학습 데이터와 서빙 중인 모델 가중치의 버전이 어긋나 복원 후 예측 편향 및 Train/Serve skew가 발생할 수 있습니다.
2. **DB와 ChromaDB 지식베이스 불일치**: 공고 데이터(MySQL)와 벡터 색인(ChromaDB `bidding_kb`)의 시점이 다르면 챗봇 RAG가 존재하지 않거나 삭제된 공고를 인용하는 검색 정합성 결함이 발생합니다.

따라서 모든 백업과 복원은 세 가지 요소를 하나의 스냅샷 디렉토리와 단일 매니페스트(`backup_manifest.json`)로 결박하여 처리합니다.

---

## 2. 목표 복구 수준 (RPO / RTO)

운영 서비스의 복구 목표 수준(RPO, RTO)은 인위적인 수치를 단정하지 않으며, 운영 환경의 비즈니스 SLA 및 데이터 수집 주기에 따라 **운영 담당자가 결정하여 기입**하도록 공란으로 둡니다.

| 지표 | 정의 | 목표 기준선 (SLA) | 비고 |
| --- | --- | --- | --- |
| **RPO** (Recovery Point Objective) | 허용 가능한 최대 데이터 유실 시점 간격 | _[운영 담당자 기입 필요]_ | 정기 백업 주기 및 트랜잭션 로그 보관 정책에 따름 |
| **RTO** (Recovery Time Objective) | 장애 발생 시점부터 서비스 정상화까지 허용 시간 | _[운영 담당자 기입 필요]_ | 덤프 다운로드, DB 로드, 사후 검증 소요 시간 합산 |

> **안내**: 근거 없는 수치를 기입하면 잘못된 정본이 형성되므로, 정식 인프라 용량 산정 및 장애 시나리오 실측 후 담당자가 위 항목을 확정합니다.

---

## 3. 백업 절차 (Backup Procedure)

백업 도구인 [`../../scripts/backup_recovery.py`](../../scripts/backup_recovery.py)는 **사전 점검(dry-run)이 기본값**이며, 실제 데이터 쓰기는 `--execute` 명시 플래그를 요구합니다.

### 3.1 사전 점검 (dry-run)

백업 대상 경로, DB 접속 설정, 아카이브 대상 디렉토리를 확인합니다:

```bash
# Makefile 타깃 이용
make backup-dry-run

# 또는 직접 실행
python3 scripts/backup_recovery.py backup
```

### 3.2 실제 백업 실행

```bash
# Makefile 타깃 이용
make backup

# 또는 직접 실행
python3 scripts/backup_recovery.py backup --execute

# 특정 디렉토리에 스냅샷 저장 시
python3 scripts/backup_recovery.py backup --execute --output-dir data/backups/snapshots/snapshot_custom
```

### 3.3 백업 스냅샷 산출물 구조

백업 완료 시 `data/backups/snapshots/snapshot_YYYYMMDD_HHMMSS/` 디렉토리에 다음 파일들이 생성됩니다:

| 파일명 | 대상 | 형식 | 내용 설명 |
| --- | --- | --- | --- |
| `db_dump.sql.gz` | MySQL 운영 DB | gzip 압축 SQL | `mysqldump` InnoDB 일관성 스냅샷 (`--single-transaction`) |
| `chroma_db.tar.gz` | ChromaDB | tar.gz 아카이브 | `chroma_db/` 디렉토리 전체 아카이브 |
| `models.tar.gz` | 모델 및 MLOps | tar.gz 아카이브 | `data/model_files`, `data/model_backups`, `data/model_metrics`, `ml_registry` |
| `backup_manifest.json` | 백업 매니페스트 | JSON | 생성 시각, Git HEAD, 컴포넌트별 크기/체크섬, DB 행 수 요약 |

### 3.4 백업 매니페스트 예시

```json
{
  "schema": "BACKUP_MANIFEST_V1",
  "created_at": "2026-09-02T15:30:00.000000+00:00",
  "head_commit": "5d8ad9760773d2a...",
  "components": {
    "database": {
      "path": "db_dump.sql.gz",
      "size_bytes": 451238912,
      "sha256": "8d3e91146747b0a...",
      "row_counts": {
        "bid_announcements": 1839088,
        "bid_results": 3002254,
        "retrain_logs": 42
      }
    },
    "chroma_db": {
      "path": "chroma_db.tar.gz",
      "size_bytes": 108520120,
      "sha256": "e3b0c44298fc1c1...",
      "source_path": "chroma_db"
    },
    "models": {
      "path": "models.tar.gz",
      "size_bytes": 84210984,
      "sha256": "a1b2c3d4e5f6071...",
      "source_paths": [
        "data/model_files",
        "data/model_backups",
        "data/model_metrics",
        "ml_registry"
      ]
    }
  }
}
```

### 3.5 스냅샷 무결성 검증 및 목록 조회

```bash
# 백업 스냅샷 목록 조회
make backup-list
# 또는 python3 scripts/backup_recovery.py list

# 최신 또는 특정 스냅샷 무결성 검증 (SHA256 체크섬 대조)
python3 scripts/backup_recovery.py verify --snapshot-dir data/backups/snapshots/snapshot_20260902_153000
```

---

## 4. 복원 절차 (Recovery Procedure)

복원은 기존 운영 데이터를 덮어쓰는 고위험 작업이므로, **덮어쓸 대상을 먼저 화면에 출력**하고 명시적 확인 없이는 절대 진행되지 않도록 안전장치가 내장되어 있습니다.

### 4.1 복원 전 사전 점검 (dry-run)

```bash
# 최신 스냅샷 기준 점검
make restore-dry-run

# 특정 스냅샷 지정 점검
python3 scripts/backup_recovery.py restore --snapshot-dir data/backups/snapshots/snapshot_20260902_153000
```

### 4.2 실제 복원 실행

실제 복원을 수행하려면 `--execute`와 함께 `--confirm` 플래그(또는 대화형 터미널에서 `yes` 입력)를 지정해야 합니다:

```bash
# 특정 스냅샷으로 복원 실행
python3 scripts/backup_recovery.py restore \
  --snapshot-dir data/backups/snapshots/snapshot_20260902_153000 \
  --execute \
  --confirm
```

### 4.3 복원 후 자동 무손실 검증

복원이 완료되면 스크립트는 기존 무손실 검증 도구인 [`../../scripts/verify_migration.py`](../../scripts/verify_migration.py)를 자동으로 호출하여 다음 5단계를 전량 검증합니다:
1. **[1/5] ML 가중치 4종 무결성**: SHA256 체크섬 대조
2. **[2/5] ChromaDB 컬렉션 무결성**: 컬렉션 존재 및 실제 클라이언트 질의 검증
3. **[3/5] DB 필수 테이블 존재**: 11개 핵심 테이블 연결 검증
4. **[4/5] DB 전 테이블 스키마 서명 정합성**: 컬럼명, 타입, nullable, PK, FK, 인덱스 일치 여부
5. **[5/5] 데이터 행 수 하한 검증**: 기준선 대비 데이터 보존율 검증

검증 실패 시 즉시 에러를 반환하고 복원 결과를 검토할 수 있도록 로그를 남깁니다.

---

## 5. 보안 및 자격 증명 관리

1. **시크릿 평문 노출 금지**: 본 문서 및 코드 내에 실제 DB 비밀번호, API 키, 시크릿 키 문자열을 절대 기록하지 않습니다 ([`../../src/app/core/config.py`](../../src/app/core/config.py) 및 환경 변수 사용).
2. **안전한 프로세스 실행**: `mysqldump` 및 `mysql` 클라이언트 실행 시 `MYSQL_PWD` 환경 변수를 프로세스 격리 환경으로 전달하여 `ps` 명령 등 프로세스 목록에서 비밀번호가 노출되지 않도록 합니다.
3. **매니페스트 보호**: `backup_manifest.json`에는 파일 체크섬과 메타데이터만 기록되며, 자격 증명은 일절 포함되지 않습니다.

---

## 6. 후속 과업 (Future Work / Out of Scope)

본 작업 범위에서는 단일 복구 단위 도구와 표준 절차를 구현하였으며, 다음 항목은 외부 인프라 연동이 필요하여 후속 과업으로 추진합니다:

1. **백업 아카이브 암호화**:
   - GPG 대칭키 또는 비대칭키(AES-256) 암호화 레이어 적용.
   - 사내 KMS(Key Management Service) 또는 HashiCorp Vault와 연동하여 암호화 키 관리 선행 필요.
2. **오프호스트(Off-host) 원격 사본 보관**:
   - AWS S3, Google Cloud Storage 등 원격 오브젝트 스토리지로의 자동 복제.
   - 불변(WORM) 스토리지 잠금 및 30일/90일 수명주기(Lifecycle) 보관 정책 수립.

---

## 7. 운영 점검 체크리스트

- [ ] `make backup-dry-run`으로 백업 대상 경로 및 설정 사전 점검
- [ ] `make backup`으로 통합 백업 스냅샷 정상 생성 확인
- [ ] `backup_manifest.json` 내 컴포넌트 체크섬 및 DB 행 수 기록 확인
- [ ] `make backup-verify`로 생성된 스냅샷 아카이브 무결성 검증
- [ ] 복원 모의 훈련 시 `restore-dry-run`으로 덮어쓸 대상 목록 확인
- [ ] 복원 완료 후 `scripts/verify_migration.py` 5단계 검증 전량 통과 확인

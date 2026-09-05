# 운영 데이터 통합 백업 및 복원 런북 (Backup & Recovery Runbook)

> **작성일**: 2026-09-02
> **상태**: 필수 자산 실패 종료 및 부분 백업 표기 적용
> **관련 문서**: [`docs/context/CURRENT_STATE.md`](../context/CURRENT_STATE.md), [`docs/migration/db_migration_runbook.md`](../migration/db_migration_runbook.md)

---

## 1. 목적 및 단일 복구 단위 원칙

본 문서는 `refac_bid_box`의 **MySQL 운영 DB**, **ChromaDB 지식베이스**, **서빙 모델 및 MLOps 레지스트리**를 **단일 복구 단위(Unified Recovery Unit)**로 묶어 안전하게 백업하고 무손실로 복원하기 위한 표준 운영 절차서입니다.

### 1.1 단일 복구 단위 필요성

과거 운영 환경에서는 DB 덤프와 ChromaDB, 모델 가중치가 서로 다른 시점에 별개로 관리되어 다음과 같은 정합성 위험이 존재했습니다:
1. **DB와 ML 모델 시점 불일치**: DB의 학습 데이터와 서빙 중인 모델 가중치의 버전이 어긋나 복원 후 예측 편향 및 Train/Serve skew가 발생할 수 있습니다.
2. **DB와 ChromaDB 지식베이스 불일치**: 공고 데이터(MySQL)와 벡터 색인(ChromaDB `bidding_kb`)의 시점이 다르면 챗봇 RAG가 존재하지 않거나 삭제된 공고를 인용하는 검색 정합성 결함이 발생합니다.

따라서 모든 백업과 복원은 세 가지 요소를 하나의 스냅샷 디렉토리와 단일 매니페스트(`backup_manifest.json`)로 결박하여 처리합니다.

### 1.2 필수 자산과 실패 기본값

코드의 `scripts.backup_recovery_core.REQUIRED_BACKUP_ASSETS` 상수는
`database`, `chroma_db`, `models`를 필수 백업 자산으로 정의합니다. 파일 자산의
정본 경로는 다음과 같습니다.

| 자산 | 정본 경로 및 조건 | 누락 시 기본 동작 |
| --- | --- | --- |
| `database` | `db_dump.sql.gz`가 생성되고 0바이트가 아니어야 함 | 백업 실패 |
| `chroma_db` | `CHROMA_DB_PATH` 또는 `chroma_db/`에 0바이트가 아닌 파일이 있어야 함 | 백업 실패 |
| `models` | `data/model_files/`에 0바이트가 아닌 모델 파일이 있어야 함 | 백업 실패 |

`data/model_backups`, `data/model_metrics`, `ml_registry`는 존재하는 경우 모델
아카이브에 함께 수집하지만, 위의 정본 모델 파일을 대신하지 않습니다. 자산이
없거나 내용이 0바이트인 상태에서 `--allow-partial` 없이 실행하면
`BackupAssetError`가 발생하며 매니페스트를 작성하지 않습니다. 이 기본값은
복구할 수 없는 백업을 성공으로 기록하지 않기 위한 실패 종료(fail closed) 계약입니다.

개발 머신이나 CI에서 자산이 의도적으로 없는 경우에만 백업 명령의 유일한
허용 플래그인 `--allow-partial`을 사용합니다. 이 플래그를 사용하면 누락 자산을
매니페스트에 기록하고 `partial_backup: true`, `recovery_trusted: false`를 남깁니다.
부분 백업은 복원 및 복원 리허설의 성공 대상으로 사용할 수 없습니다.

---

## 2. 목표 복구 수준 (RPO / RTO)

운영 서비스의 복구 목표 수준(RPO, RTO)은 인위적인 수치를 단정하지 않으며, 운영 환경의 비즈니스 SLA 및 데이터 수집 주기에 따라 **운영 담당자가 결정하여 기입**하도록 공란으로 둡니다.

| 지표 | 정의 | 목표 기준선 (SLA) | 비고 |
| --- | --- | --- | --- |
| **RPO** (Recovery Point Objective) | 허용 가능한 최대 데이터 유실 시점 간격 | _[운영 담당자 기입 필요]_ | 정기 백업 주기 및 트랜잭션 로그 보관 정책에 따름 |
| **RTO** (Recovery Time Objective) | 장애 발생 시점부터 서비스 정상화까지 허용 시간 | _[운영 담당자 기입 필요]_ | 덤프 다운로드, DB 로드, 사후 검증 소요 시간 합산 |

> **안내**: 근거 없는 수치를 기입하면 잘못된 정본이 형성되므로, 정식 인프라 용량 산정 및 장애 시나리오 실측 후 담당자가 위 항목을 확정합니다.

정기 백업은 OS 크론이 아니라 Arq 워커의 `src/tasks/worker.py` `cron_jobs`에 등록된
`backup_schedule_task`가 담당합니다. `BACKUP_SCHEDULE_ENABLED=false`가 기본값이며,
활성화된 백업 주기가 RPO에 영향을 주지만 RPO/RTO 자체를 확정하지는 않습니다.

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

# 개발 머신 또는 CI에서 의도적으로 자산이 없는 경우에만 사용
python3 scripts/backup_recovery.py backup --execute --allow-partial

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
| `backup_manifest.json` | 백업 매니페스트 | JSON | 생성 시각, Git HEAD, 필수 자산 상태, 컴포넌트별 크기/체크섬, DB 행 수 요약, 일관성 윈도우 |

### 3.4 백업 매니페스트 예시

```json
{
  "schema": "BACKUP_MANIFEST_V1",
  "created_at": "2026-09-02T15:30:00.000000+00:00",
  "head_commit": "5d8ad9760773d2a...",
  "partial_backup": false,
  "recovery_trusted": true,
  "required_assets": ["database", "chroma_db", "models"],
  "missing_assets": [],
  "consistency_window": {
    "db_dump_started_at": "2026-09-02T15:29:40.000000+00:00",
    "db_dump_finished_at": "2026-09-02T15:30:10.000000+00:00",
    "file_assets_collected_at": "2026-09-02T15:30:15.000000+00:00"
  },
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
      "status": "available",
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

부분 백업에서는 누락 자산 컴포넌트의 `path`, `size_bytes`, `sha256`가 각각
`null`로 기록되며 해당 아카이브를 생성하지 않습니다. 따라서 무결성 검증과
복원은 실패하고, 매니페스트의 `recovery_trusted: false` 표기가 유지됩니다.

매니페스트의 `consistency_window`는 동일 시점 스냅샷을 보장하는 값이 아닙니다.
DB 덤프 시작·종료 시각과 파일 자산 수집 시각을 기록하여 복원 시
DB와 파일 자산 사이에 발생할 수 있는 시점 차이를 판정할 수 있게 합니다.

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

### 4.4 복원 리허설 (Restore Drill)

과거 복원 리허설은 계획 검증과 체크섬 확인만 수행하고 실제 아카이브 해제나 DB import를 수행하지 않던 결함이 있었습니다. 2026-09-03 리팩토링을 통해 **실제로 아카이브를 풀고, 격리된 임시 DB에 import한 후, `scripts/verify_migration.py`를 재사용해 G1 무손실 검증까지 완결하는 실측 도구**로 고도화되었습니다.

#### 4.4.1 격리 안전 가드 (Isolation Guard)
1. **경로 격리 가드**:
   - 대상 디렉토리(`--target-dir`)는 필수이며 프로젝트 루트, 루트 상위/하위 경로, 현재 작업 디렉토리(cwd)를 절대 지정할 수 없습니다.
   - 비정상 경로(`.`, `..`, `/`)나 격리되지 않은 경로가 지정되면 작업을 시작하지 않고 거부합니다.
2. **DB 격리 가드**:
   - 리허설 대상 DB(`--db-name`, 기본값: `<운영DB>_restore_drill`)는 운영 DB와 이름이나 접속 대상(host/port)이 동일할 수 없습니다.
   - 운영 DB 침범 가능성이 감지되면 즉시 실패 종료(fail-closed)합니다.
3. **정리 안전 보장 (Cleanup Safety)**:
   - 리허설 성공 또는 실패 시 생성된 임시 DB(`DROP DATABASE`)와 임시 디렉토리는 자동으로 삭제 정리됩니다.
   - 정리 함수(`cleanup_drill_target_dir`, `drop_mysql_database`)에도 동일한 경로/DB 가드가 결박되어 운영 파일이나 DB가 삭제되는 사고를 원천 차단합니다.
   - 실패 원인 분석 등을 위해 산출물을 유지해야 할 때만 `--keep-artifacts` 플래그를 명시합니다.

#### 4.4.2 계측 및 RPO 산출 지표
- **단계별 소요 시간 측정**: 스냅샷 검증, 아카이브 해제, DB import, G1 검증, 정리 각각의 시작·종료 시각과 소요 시간(초)을 기록합니다.
- **RPO 관측값 산출**: 스냅샷 매니페스트의 일관성 윈도우(`consistency_window`: DB 덤프 완료 시각, 파일 수집 시각) 및 생성 시각과 리허설 시작 시각 간의 시차(초)를 정량 계산하여 기록합니다.
- **목표값 비교 판정 유예**: RPO/RTO 공식 SLA 목표값이 미확정 상태이므로 인위적인 합격/불합격 판정(threshold 비교) 코드를 두지 않고 순수 측정값만 보고서에 남깁니다.

```bash
# 기본 실행: 격리 디렉토리 및 격리 DB로 실제 복원 리허설 후 자동 정리
python3 scripts/backup_recovery.py drill \
  --snapshot-dir data/backups/snapshots/snapshot_20260902_153000 \
  --target-dir /tmp/refac_bid_box_restore_drill \
  --report-path data/backups/restore_drill_report.json

# 커스텀 격리 DB 지정 및 조사용 산출물 보존 시
python3 scripts/backup_recovery.py drill \
  --snapshot-dir data/backups/snapshots/snapshot_20260902_153000 \
  --target-dir /tmp/refac_bid_box_restore_drill \
  --db-name procurement_drill_manual \
  --keep-artifacts \
  --report-path data/backups/restore_drill_report.json
```


### 4.5 보존 정책 및 디스크 관리 (Retention Policy & Disk Management)

스냅샷 디렉토리가 무제한 증식하여 디스크가 고갈되는 위험(R-08)을 방지하기 위해 개수 기준 보존 정책과 안전 삭제 메커니즘을 적용합니다.

#### 4.5.1 설정값이 강제하는 것과 강제하지 않는 것

| 설정 / 도구 | 동작 및 강제 범위 | 미강제 (예외 사항) |
| --- | --- | --- |
| **정기 백업 크론** (`backup_schedule_task`) | `BACKUP_SCHEDULE_ENABLED=true` 활성화 시, 백업 완료 후 `BACKUP_RETENTION_COUNT`(기본 7개)를 초과하는 오래된 스냅샷을 실제로 자동 삭제(`delete=True`)하여 **디스크상 최대 스냅샷 개수를 강제**합니다. | `BACKUP_SCHEDULE_ENABLED=false`(기본값)인 경우 정기 작업이 돌지 않으므로 디스크 상한이 강제되지 않습니다. |
| **수동 백업 CLI** (`make backup`) | 명령 실행 시 새로운 스냅샷을 1건 생성합니다. | 수동 백업 명령은 보존 정리를 자동 호출하지 않으므로 디스크 상한을 강제하지 않습니다. 수동 백업 후 필요 시 `prune`을 실행해야 합니다. |
| **수동 정리 CLI** (`prune`) | `scripts/backup_recovery.py prune --retain-count 7 --delete`로 명시적 플래그 지정 시 초과분을 즉시 삭제합니다. | `--delete` 플래그가 없으면 조회(dry-run)만 수행하며 실제 삭제를 강제하지 않습니다. |
| **디스크 여유 경보** (`BACKUP_DISK_MIN_FREE_GB`) | 백업 실행 전 스토리지 여유 디스크가 설정값(기본 5.0GB) 미만이면 기존 `src/tasks/notifier.py`를 통해 경보를 발송합니다. | 경보는 알림만 수행하며, 백업 작업을 강제로 차단하지는 않습니다. |

#### 4.5.2 다중 안전장치 (Fail-Closed Guard)

스냅샷 삭제는 비가역적 조작이므로 다음 안전장치가 충족될 때만 삭제를 진행합니다:
1. **최소 보존 수량 보장**: `retain_count`는 1 이상이어야 하며, 삭제 후에도 잔여 스냅샷이 최소 보존 개수 미만으로 떨어지는 경로를 원천 차단합니다.
2. **보존 대상 무결성 검증**: 보존할 최신 스냅샷들에 매니페스트가 존재하는 경우 `verify_snapshot`을 통해 손상 여부를 검증합니다. 보존 대상이 손상되어 있으면 삭제 판정 실패로 처리하고 **아무것도 삭제하지 않습니다(fail-closed)**.
3. **경로 격리 검증**: 삭제 대상이 스냅샷 디렉토리의 직계 하위인지 확인하며, 심볼릭 링크나 경로 이탈(`..` 등)은 삭제 대상에서 제외합니다.

```bash
# 수동 점검 (dry-run): 삭제 후보 목록만 출력
python3 scripts/backup_recovery.py prune --retain-count 7

# 승인된 수동 삭제 실행
python3 scripts/backup_recovery.py prune --retain-count 7 --delete
```

---

## 5. 보안 및 자격 증명 관리

1. **시크릿 평문 노출 금지**: 본 문서 및 코드 내에 실제 DB 비밀번호, API 키, 시크릿 키 문자열을 절대 기록하지 않습니다 ([`../../src/app/core/config.py`](../../src/app/core/config.py) 및 환경 변수 사용).
2. **안전한 프로세스 실행**: `mysqldump` 및 `mysql` 클라이언트 실행 시 `MYSQL_PWD` 환경 변수를 프로세스 격리 환경으로 전달하여 `ps` 명령 등 프로세스 목록에서 비밀번호가 노출되지 않도록 합니다.
3. **매니페스트 보호**: `backup_manifest.json`에는 파일 체크섬과 메타데이터만 기록되며, 자격 증명은 일절 포함되지 않습니다.

---

## 6. 후속 과업 (Future Work / Out of Scope)

본 작업 범위에서는 단일 복구 단위 도구와 표준 절차를 구현하였으며, 다음 항목은 외부 인프라 연동이 필요하여 미결 상태로 남깁니다. 이 런북의 구현 범위에는 포함하지 않습니다:

1. **백업 아카이브 암호화 미결**:
   - GPG 대칭키 또는 비대칭키(AES-256) 암호화 레이어와 키 관리 방식을 결정해야 합니다.
   - 사내 KMS(Key Management Service) 또는 HashiCorp Vault 연동 여부를 결정해야 합니다.
2. **오프사이트 원격 사본 보관 미결**:
   - AWS S3, Google Cloud Storage 등 보관 위치와 자동 복제 방식을 결정해야 합니다.
   - 불변(WORM) 스토리지 잠금 및 보관 기간 정책을 결정해야 합니다.

---

## 7. 운영 점검 체크리스트

- [ ] `make backup-dry-run`으로 백업 대상 경로 및 설정 사전 점검
- [ ] `make backup`으로 통합 백업 스냅샷 정상 생성 확인
- [ ] 실행 환경에서 ChromaDB와 `data/model_files` 필수 자산이 존재하고 0바이트가 아닌지 확인
- [ ] `backup_manifest.json` 내 `partial_backup: false`, `recovery_trusted: true` 확인
- [ ] `backup_manifest.json` 내 컴포넌트 체크섬, DB 행 수, `consistency_window` 기록 확인
- [ ] `make backup-verify`로 생성된 스냅샷 아카이브 무결성 검증
- [ ] 복원 모의 훈련 시 `restore-dry-run`으로 덮어쓸 대상 목록 확인
- [ ] 복원 완료 후 `scripts/verify_migration.py` 5단계 검증 전량 통과 확인

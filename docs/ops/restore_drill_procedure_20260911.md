# 분기 복구 드릴(Restore Drill) 표준 실행 절차서

> **작성일**: 2026-09-11
> **상태**: 정식 승인 절차서
> **관련 문서**: [`backup_recovery_runbook.md`](backup_recovery_runbook.md), [`../context/CURRENT_STATE.md`](../context/CURRENT_STATE.md)

---

## 1. 개요 및 목적

본 문서는 `refac_bid_box`의 분기별 정기 복원 드릴(Restore Drill)을 안전하고 체계적으로 수행하기 위한 표준 실행 절차서입니다.
2026-09-06 확정된 복구 목표 수준인 **RPO 24시간** 및 **RTO 4시간**([`docs/context/CURRENT_STATE.md`](../context/CURRENT_STATE.md))을 준수하는지 실측하고, 재해 발생 시 운영 DB, ChromaDB 벡터 지식베이스, ML 서빙 모델 및 레지스트리가 단일 복구 단위로서 100% 무손실 복구 가능한지 사전에 검증하는 것을 목적으로 합니다.

본 드릴은 검증 격리 환경에서 수행되며, 운영 중인 서비스 및 데이터베이스에 일체의 쓰기 영향이나 다운타임을 유발하지 않습니다.

---

## 2. 복구 드릴 실행 전 조건 (Pre-requisites)

드릴을 시작하기 전에 다음 5가지 사전 조건을 모두 점검하고 만족해야 합니다.

| 점검 항목 | 조건 및 점검 기준 | 확인 방법 / 점검 명령 |
| --- | --- | --- |
| **스냅샷 유효성** | 복원 대상 단일 복구 단위 스냅샷이 존재하고 체크섬 무결성이 확인되어야 함 (`partial_backup: false`, `recovery_trusted: true`) | `python3 scripts/backup_recovery.py verify --snapshot-dir <스냅샷경로>` 결과 `[PASS]` |
| **격리 대상 경로** | 프로젝트 루트, 현재 작업 디렉터리(cwd), 시스템 루트와 전혀 겹치지 않는 외부 격리 경로여야 함 | `/tmp/refac_bid_box_restore_drill` 등 독립 디렉터리 지정 |
| **서비스 상태** | Docker 상의 MySQL 8 컨테이너가 정상 기동 중이어야 함 | `docker compose ps` 또는 `scripts/db_readonly_query.py` 정상 응답 |
| **시스템 격리성 (단독 실행)** | 드릴 중 RTO 시간 실측이 왜곡되지 않도록 백그라운드 테스트, 모델 학습, 벤치마크, 대용량 I/O 작업이 없어야 함 | 코디네이터 단독 직렬 실행 원칙 준수 (타 워커 쓰기/테스트 중단) |
| **디스크 여유 공간** | 스냅샷 압축 해제 및 DB 복원에 필요한 최소 여유 공간(최소 10GB 이상 권장) 확보 | `df -h /tmp` 로 대상 볼륨 용량 확인 |

---

## 3. 실행 명령 및 매개변수 명세

복원 드릴은 별도의 신규 스크립트를 작성하지 않고, 이미 검증된 기존 통합 백업 도구인 [`../../scripts/backup_recovery.py`](../../scripts/backup_recovery.py)의 `drill` 서브커맨드를 사용합니다.

### 3.1 CLI 서브커맨드 인자 상세

`scripts/backup_recovery.py drill` 명령이 지원하는 인자는 다음과 같습니다:

| 인자 | 필수 여부 | 기본값 | 설명 |
| --- | :---: | --- | --- |
| `--snapshot-dir` | **필수** | 없음 | 복원 리허설에 사용할 단일 복구 단위 스냅샷 디렉터리 경로 |
| `--target-dir` | **필수** | 없음 | 파일 아카이브(ChromaDB, 모델)를 임시 해제할 격리 디렉터리 경로 |
| `--report-path` | 선택 | `None` (콘솔 출력만 수행) | 실행 결과 및 계측 지표를 저장할 JSON 리포트 파일 경로 |
| `--db-name` | 선택 | `<운영DB>_restore_drill` | 복원 테스트를 수행할 격리된 임시 데이터베이스 이름 |
| `--keep-artifacts` | 선택 | `False` (자동 삭제) | 리허설 종료 후 격리 DB 및 임시 디렉터리를 삭제하지 않고 보존할지 여부 플래그 |

### 3.2 표준 실행 명령

정기 분기 복원 드릴 시 운영 담당자 또는 코디네이터가 실행하는 표준 명령입니다:

```bash
# 최신 또는 특정 스냅샷을 대상으로 복원 드릴 실행 (자동 정리 포함)
python3 scripts/backup_recovery.py drill \
  --snapshot-dir data/backups/snapshots/snapshot_20260902_153000 \
  --target-dir /tmp/refac_bid_box_restore_drill \
  --report-path data/backups/restore_drill_report_20260911.json
```

### 3.3 디버깅 및 상세 조사를 위한 산출물 보존 실행

장애 조사나 사전 분석을 위해 임시 DB 및 압축 해제 파일을 보존해야 하는 경우:

```bash
# --keep-artifacts 플래그 지정 실행
python3 scripts/backup_recovery.py drill \
  --snapshot-dir data/backups/snapshots/snapshot_20260902_153000 \
  --target-dir /tmp/refac_bid_box_restore_drill \
  --db-name procurement_drill_debug \
  --keep-artifacts \
  --report-path data/backups/restore_drill_report_debug.json
```

> **주의**: `--keep-artifacts`를 사용한 경우, 분석이 완료된 후 반드시 임시 데이터베이스를 삭제(`DROP DATABASE \`procurement_drill_debug\`;`)하고 격리 디렉터리(`/tmp/refac_bid_box_restore_drill`)를 정리해야 합니다.

---

## 4. 합격 기준 (Pass Criteria)

복구 드릴의 합격 여부는 단순한 시간 측정이 아니라, **G1 데이터 무손실 원칙과 RTO SLA를 동시에 만족하는 다면 검증**을 거쳐 판정합니다. 복원이 신속하더라도 데이터 무결성이 어긋나면 즉시 불합격으로 판정됩니다.

| 검증 영역 | 합격 판정 기준 | 근거 지표 및 검증 도구 |
| --- | --- | --- |
| **1. 복구 시간 (RTO)** | 총 소요 시간(`total_duration_seconds`)이 목표 기준선인 **4시간(14,400초) 이내**여야 함 | `RESTORE_DRILL_REPORT_V2` 내 `total_duration_seconds` 실측값 |
| **2. 데이터 유실 (RPO)** | 복원된 스냅샷의 생성 시각 및 일관성 윈도우 시차가 목표 기준선인 **24시간 이내**여야 함 | 리포트 내 `rpo_measurements` 및 매니페스트 `consistency_window` |
| **3. 행 수 대조 (Row Count)** | MySQL 11개 핵심 테이블의 복원 후 데이터 행 수가 백업 시점 기준선 및 하한을 100% 충족해야 함 | `scripts/verify_migration.py` 5단계 행 수 하한 대조 (`[5/5]`) |
| **4. 스키마 대조 (Schema)** | 전 테이블 스키마 서명(컬럼명, 타입, nullable, PK, FK, 인덱스)이 원본 스키마와 100% 일치해야 함 | `scripts/verify_migration.py` 4단계 스키마 서명 정합성 검증 (`[4/5]`) |
| **5. 가중치 무결성** | ML 모델 가중치 4종의 SHA256 체크섬이 원본 등록 체크섬과 100% 일치해야 함 | `scripts/verify_migration.py` 1단계 가중치 검증 (`[1/5]`) |
| **6. 지식베이스 무결성** | ChromaDB `bidding_kb` 컬렉션이 정상 로드되고 실제 클라이언트 질의가 성공해야 함 | `scripts/verify_migration.py` 2단계 벡터DB 검증 (`[2/5]`) |
| **7. 격리 정리 완료** | `--keep-artifacts` 미지정 시 격리 DB drop 및 임시 디렉터리 정리가 완료되어야 함 | 리포트 내 `timings.cleanup.status == "PASS"` |
| **8. 프로세스 종료 코드** | 스크립트 실행 종료 코드가 `0`이어야 함 | CLI 반환값 `echo $? == 0`, 리포트 `success == true` |

---

## 5. 실패 시 판정 및 기록 위치

드릴 실행 중 어느 한 단계라도 실패하면 안전하게 실패 종료(fail-closed)됩니다.

### 5.1 실패 판정 조건
다음 중 하나라도 발생하면 복구 드릴은 **실패(FAILED)**로 판정됩니다:
1. 프로세스 종료 코드가 `0`이 아닌 경우 (종료 코드 `1`).
2. 최종 JSON 리포트의 `success` 필드가 `false`인 경우.
3. `errors` 배열에 에러 메시지가 1건 이상 기록된 경우.
4. G1 무손실 검증(`g1_verification.success`)이 `false`인 경우 (행 수 불일치, 스키마 불일치, 체크섬 불일치 등).
5. 총 복구 소요 시간이 RTO 한도인 4시간을 초과한 경우.

### 5.2 결과 기록 위치 및 리포트 구조
- **저장 위치**: `--report-path`로 전달한 경로 (표준 경로: `data/backups/restore_drill_report_YYYYMMDD.json`)
- **결과 확인 명령**:
  ```bash
  cat data/backups/restore_drill_report_20260911.json | jq '{success, total_duration_seconds, errors, g1_verification: .g1_verification.success}'
  ```
- **기계 산출물 리포트 스키마 (`RESTORE_DRILL_REPORT_V2`) 예시**:
  ```json
  {
    "schema": "RESTORE_DRILL_REPORT_V2",
    "snapshot_dir": "data/backups/snapshots/snapshot_20260902_153000",
    "target_dir": "/tmp/refac_bid_box_restore_drill",
    "drill_db": {
      "host": "localhost",
      "port": 3306,
      "name": "procurement_db_restore_drill",
      "user": "root"
    },
    "snapshot_valid": true,
    "components": ["chroma_db", "database", "models"],
    "extracted_components": ["chroma_db", "models"],
    "timings": {
      "snapshot_verification": { "duration_seconds": 1.25, "status": "PASS" },
      "archive_extraction": { "duration_seconds": 4.10, "status": "PASS" },
      "database_import": { "duration_seconds": 28.45, "status": "PASS" },
      "g1_verification": { "duration_seconds": 6.80, "status": "PASS" },
      "cleanup": { "duration_seconds": 0.95, "status": "PASS" }
    },
    "total_duration_seconds": 41.55,
    "rpo_measurements": {
      "snapshot_created_at": "2026-09-02T15:30:00+00:00",
      "created_at_to_drill_start_seconds": 763200.0
    },
    "g1_verification": {
      "success": true,
      "message": "G1 무손실 검증 통과",
      "report": { ... }
    },
    "keep_artifacts": false,
    "errors": [],
    "success": true
  }
  ```

---

## 6. 운영 DB 미영향 근거 (격리 안전 가드)

본 복원 드릴은 운영 중인 데이터베이스 및 저장소에 영향을 주지 않도록 다중 안전장치가 코드 수준에서 결박되어 있습니다:

1. **데이터베이스 격리 가드 (`scripts/backup_recovery_core.py:drop_mysql_database`)**:
   - 드릴용 DB 이름(`--db-name`)은 기본적으로 `<운영DB>_restore_drill` 접미사가 부여되어 별도 생성됩니다.
   - 대상 DB의 이름 및 host/port가 운영 DB와 일치하면 즉시 `ValueError("운영 DB는 삭제할 수 없습니다.")` 또는 `ValueError("복원 리허설 대상 DB는 운영 DB와 동일할 수 없습니다.")`를 발생시키고 실행을 즉시 거부합니다.
   - 따라서 실제 운영 DB 테이블이나 데이터가 덮어써지거나 삭제될 위험이 없습니다.
2. **파일시스템 경로 격리 가드 (`scripts/backup_recovery_core.py:cleanup_drill_target_dir`)**:
   - 아카이브 해제 대상(`--target-dir`)은 반드시 외부 격리 디렉터리여야 합니다.
   - 프로젝트 루트(`PROJECT_ROOT`), 현재 작업 디렉터리(`Path.cwd()`), 파일시스템 루트(`/`, `.`, `..`) 또는 이들의 상/하위 디렉터리가 지정되면 도구가 즉시 거부(`ValueError`)합니다.
   - 드릴 종료 시 자동 실행되는 정리 작업 역시 동일한 경로 가드를 검증하므로, 실수로 프로젝트 소스코드나 운영 볼륨이 삭제되는 사고를 방지합니다.
3. **아카이브 디렉터리 탈출 방지 (`extract_tar_archive`)**:
   - tar 아카이브 해제 시 `member_path` 검사 및 `data_filter` 필터를 적용하여, 아카이브 내부에 상위 경로(`../`) 조작이 포함되어 있더라도 대상 격리 폴더 밖으로 탈출하여 기존 파일을 덮어쓰지 못하도록 차단합니다.

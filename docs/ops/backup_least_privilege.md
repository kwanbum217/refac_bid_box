# backup 서비스 권한 축소 및 전용 큐 분리

> **작성일**: 2026-09-14
> **수정일**: 2026-09-15
> **대상**: `docker-compose.prod.yml` 의 `backup` 서비스
> **관련 Task**: `task_a32d19622b97`, `task_6e71e04ed87d`

---

## 1. 개요 및 결론

2026-09-14 외부 감사의 `backup` 서비스 권한 과다 지적에 대응하여, 선행 조건이었던 **전용 Arq 워커 설정(`BackupWorkerSettings`) 및 전용 큐(`BACKUP_QUEUE_NAME = "arq:queue:backup"`) 분리**를 완료했습니다.

기존에는 `backup` 서비스가 `worker`와 동일한 `WorkerSettings`를 실행하여 기본 큐(`arq:queue`)를 공유하고 있었기 때문에, 외부 수집 API 호출이나 재학습 등의 일반 작업이 `backup` 컨테이너로 임의 할당될 위험이 있었습니다.

전용 큐 분리가 완료됨에 따라 `backup` 서비스가 오직 백업 스케줄(`backup_schedule_task`)만 실행하도록 격리되었으며, 이에 맞추어 사용하지 않는 권한(`extra_hosts`, `ml_registry` 및 `chroma_db` 쓰기 권한)을 안전하게 제거했습니다.

이어서 2026-09-15 사용자 결정에 따라 백업 덤프 수행 시 애플리케이션 공용 DB 계정 대신 **덤프 전용 최소 권한 MySQL 계정(`BACKUP_DB_USER`)**을 사용하도록 전환하여 DB 계정 최소권한 분리를 완결했습니다.

---

## 2. Arq 전용 큐 및 설정 분리 방식

| 구분 | 일반 워커 (`WorkerSettings`) | 백업 워커 (`BackupWorkerSettings`) |
| --- | --- | --- |
| 큐 이름 | `arq:queue` (기본 큐) | `arq:queue:backup` (전용 격리 큐) |
| 실행 커맨드 | `arq src.tasks.worker.WorkerSettings` | `arq src.tasks.worker.BackupWorkerSettings` |
| 등록 함수 (`functions`) | 수집, KB 갱신, 검증, 재학습 등 14개 | `backup_schedule_task` 1개 |
| 크론 잡 (`cron_jobs`) | 정기 수집, 야간 번들, 주간 재학습, 드리프트 모니터 등 5개 | 03:00 정기 통합 백업 1개 |
| 기동 훅 (`on_startup`) | 로깅, 하트비트, 관측성, **수집 따라잡기(`schedule_catchup`)** | 로깅, 하트비트, 관측성 (**수집 따라잡기 제외**) |

1. **`src/tasks/worker.py` 전용 설정 추가**:
   - `BACKUP_QUEUE_NAME = "arq:queue:backup"` 상수를 정의하고 `BackupWorkerSettings`를 구현했습니다.
   - `functions`와 `cron_jobs`에는 `backup_schedule_task`만 등록했습니다.
   - 기동 시 수집 작업을 유발하는 `schedule_catchup` 태스크는 배제하고 하트비트만 안전하게 기동합니다.
2. **`WorkerSettings` 크론에서 백업 제거**:
   - `WorkerSettings.cron_jobs`에서 `backup_schedule_task`를 제거하여 백업 작업이 두 곳에서 중복 실행되는 것을 방지했습니다.
3. **운영 환경 배선 (`docker-compose.prod.yml`)**:
   - `backup` 서비스의 command 를 `["arq", "src.tasks.worker.BackupWorkerSettings"]` 로 변경했습니다.

---

## 3. 제거된 권한과 상세 사유

| 제거된 항목 | 기존 설정 | 변경된 설정 | 제거 사유 |
| --- | --- | --- | --- |
| `extra_hosts` | `host.docker.internal:host-gateway` | 완전 제거 | 백업 컨테이너는 호스트의 Ollama(LLM)와 통신하지 않으므로 불필요 |
| `ml_registry` 마운트 | `./ml_registry:/app/ml_registry` | `./ml_registry:/app/ml_registry:ro` | 모델 가중치를 tar 아카이브로 읽기만 하며, 재학습·승격을 수행하지 않음 |
| `chroma_db` 마운트 | `./chroma_db:/app/chroma_db` | `./chroma_db:/app/chroma_db:ro` | ChromaDB 데이터를 tar 아카이브로 읽기만 하며, 색인 쓰기를 수행하지 않음 |

---

## 4. 남긴 권한과 근거

| 유지된 항목 | 설정 값 | 유지 근거 |
| --- | --- | --- |
| `data` 마운트 | `./data:/app/data` (쓰기 유지) | `scripts/backup_recovery.py`의 통합 백업 스냅샷이 `data/backups/snapshots/snapshot_*` 디렉터리에 실제 덤프 파일과 tar 파일을 생성하므로 디스크 쓰기 권한 필수 |
| `egress` 네트워크 | `networks: [internal, egress]` | `scheduled_tasks.backup_schedule_task`는 디스크 여유 공간 부족 경보 또는 백업 실패 발생 시 `src/tasks/notifier.py`의 `notify()` / `notify_task_failure()`를 호출하여 외부 웹훅(`MLOPS_WEBHOOK_URL`, Slack/Discord)으로 HTTP POST 전송을 수행하므로 외부 네트워크 통신 필수 |
| 환경변수 및 접속 정보 | `SECRET_KEY`, `REDIS_URL`, `DATABASE_URL` | Arq 큐 브로커 연결, MySQL `mysqldump` 실행 및 Pydantic `Settings` 기본 검증을 통과하기 위해 필수 |

---

## 5. 데이터베이스 전용 최소 권한 계정 분리 (해소 완료)

2026-09-15 사용자 결정에 따라 백업 컨테이너가 애플리케이션 공용 DB 계정(`DB_USER`) 대신 **덤프 전용 최소 권한 계정(`BACKUP_DB_USER`)**을 사용하도록 전환을 완료했습니다.

### 5.1 계정 권한 정책
백업 덤프 전용 계정은 데이터 유출 및 침해 시 피해 범위를 최소화하기 위해 읽기 및 메타데이터 조회 권한만 부여받으며, 데이터 쓰기(`INSERT`, `UPDATE`, `DELETE`) 및 스키마 변경(`DROP`, `ALTER`, `CREATE TABLE`) 권한은 일체 부여되지 않습니다.

- **부여 권한**:
  - `procurement.*`: `SELECT`, `SHOW VIEW`, `TRIGGER`, `LOCK TABLES`, `EVENT`
  - `*.*`: `PROCESS` (MySQL 8.0 `mysqldump`의 Information Schema TABLESPACES 조회 호환성 보장)
- **계정 생성 SQL**: [`scripts/create_backup_db_user.sql`](../../scripts/create_backup_db_user.sql)

### 5.2 운영 DB 계정 생성 및 적용 절차
1. **운영 DB 관리자 권한으로 계정 생성 SQL 실행**:
   ```sh
   mysql -u root -p < scripts/create_backup_db_user.sql
   ```
   (주의: 실행 전 SQL 내 `IDENTIFIED BY` 비밀번호 자리표시자를 실제 운영용 강력한 난수로 변경하십시오.)
2. **운영 `.env` 파일에 전용 환경변수 2종 추가**:
   ```sh
   BACKUP_DB_USER=bidbox_backup
   BACKUP_DB_PASSWORD=<설정한_안전한_비밀번호>
   ```
3. **backup 컨테이너 재기동**:
   ```sh
   docker compose -f docker-compose.prod.yml up -d backup
   ```
4. **덤프 정상 동작 1회 수동 확인**:
   ```sh
   docker compose -f docker-compose.prod.yml exec backup python scripts/backup_recovery.py --execute
   ```

### 5.3 복구(Restore) 및 리허설(Drill) 계정 정책
- **백업 덤프**: `BACKUP_DB_USER` (최소 권한 읽기 전용 계정)를 사용하여 수행합니다.
- **복원 및 리허설**: DB 생성/삭제(`CREATE DATABASE`, `DROP DATABASE`) 및 테이블 데이터 복원(`INSERT`, `CREATE TABLE` 등) 쓰기 작업이 필수적이므로, **복구 작업은 여전히 관리자(root 또는 공용 관리 계정) 권한**으로 수행합니다.

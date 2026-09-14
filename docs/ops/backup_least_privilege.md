# backup 서비스 권한 축소 및 전용 큐 분리

> **작성일**: 2026-09-14
> **수정일**: 2026-09-14
> **대상**: `docker-compose.prod.yml` 의 `backup` 서비스
> **관련 Task**: `task_a32d19622b97`

---

## 1. 개요 및 결론

2026-09-14 외부 감사의 `backup` 서비스 권한 과다 지적에 대응하여, 선행 조건이었던 **전용 Arq 워커 설정(`BackupWorkerSettings`) 및 전용 큐(`BACKUP_QUEUE_NAME = "arq:queue:backup"`) 분리**를 완료했습니다.

기존에는 `backup` 서비스가 `worker`와 동일한 `WorkerSettings`를 실행하여 기본 큐(`arq:queue`)를 공유하고 있었기 때문에, 외부 수집 API 호출이나 재학습 등의 일반 작업이 `backup` 컨테이너로 임의 할당될 위험이 있었습니다.

전용 큐 분리가 완료됨에 따라 `backup` 서비스가 오직 백업 스케줄(`backup_schedule_task`)만 실행하도록 격리되었으며, 이에 맞추어 사용하지 않는 권한(`extra_hosts`, `ml_registry` 및 `chroma_db` 쓰기 권한)을 안전하게 제거했습니다.

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

## 5. 데이터베이스 전용 계정 관련 안내 (사용자 결정 대상)

현재 백업 컨테이너는 애플리케이션 공용 DB 계정(`DB_USER`)을 사용하여 덤프를 수행합니다.

백업 전용 최소 권한 MySQL 계정(예: `SELECT`, `LOCK TABLES`, `SHOW VIEW` 등 덤프 전용 권한만 부여된 계정) 분리는 데이터베이스 사용자 생성 및 권한 부여가 수반되는 변경이므로 운영자 및 사용자 결정 대상으로 분류되어 있으며 이번 범위에서는 제외되었습니다.

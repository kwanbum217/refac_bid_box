# backup 서비스 권한 검토와 축소 선행 조건

> **작성일**: 2026-09-14
> **대상**: `docker-compose.prod.yml` 의 `backup` 서비스
> **관련 Task**: `task_19e732e36709` (빌더 초안), 코디네이터 재작업

---

## 1. 결론

2026-09-14 외부 감사가 backup 서비스의 권한 과다를 지적했습니다. 검토 결과 **지금은 권한을 줄이지 않습니다.**
backup 은 worker 와 같은 arq `WorkerSettings`(`arq src.tasks.worker.WorkerSettings`)로 기동해 **같은 기본 큐를 소비**하므로,
백업과 무관한 작업이 backup 컨테이너에서 실행될 수 있기 때문입니다. 권한 축소는 backup 전용 큐를 분리한 뒤에 합니다.

빌더 초안은 egress 네트워크·`extra_hosts` 제거와 `ml_registry`·`chroma_db` 읽기 전용 마운트를 적용했으나,
큐 공유를 고려하지 않아 코디네이터 검토에서 되돌렸습니다.

---

## 2. backup 컨테이너에서 실행될 수 있는 작업

| 작업 | 경로 | 필요한 권한 | 축소 시 영향 |
| --- | --- | --- | --- |
| `backup_schedule_task` | `src/tasks/scheduled_tasks.py` | DB 덤프, `data/backups/snapshots` 쓰기, `ml_registry`·`chroma_db` 읽기 | 없음 |
| API 로 넣은 수집 작업 | `src/app/services/collector_service.py` | 조달청 API 외부 호출(egress) | egress 제거 시 실패 |
| 재학습·승격 | `src/tasks/` 재학습 태스크 | `ml_registry` 쓰기 | `:ro` 시 실패 |
| `drift_monitor_task` 크론 | `src/tasks/worker.py` | DB, 레지스트리 조회 | 환경에 따라 실패 가능 |
| `refresh_institution_catalog_task` 크론 | `src/tasks/summary_tasks.py` | DB, Redis | 없음 |
| 실패 알림 | `src/tasks/notifier.py` | `MLOPS_WEBHOOK_URL` 설정 시 외부 호출 | egress 제거 시 알림 유실 |

arq 는 크론을 여러 워커 중 한 곳에서만 실행하고, 큐에 들어간 작업은 먼저 가져간 워커가 실행합니다.
어떤 작업이 backup 으로 갈지 정할 수 없으므로 backup 은 worker 와 같은 권한을 가져야 합니다.

---

## 3. 남는 권한과 이유

| 권한 | 이유 |
| --- | --- |
| `SECRET_KEY` | `Settings()` 가 필수로 검증합니다. 없으면 워커가 기동하지 않습니다 |
| Redis 비밀번호 | arq 브로커와 캐시 |
| DB 계정(`DB_USER`) | 덤프와 공용 작업. root 가 아니라 앱 계정입니다 |
| egress, `host.docker.internal` | 2장의 공용 작업과 알림 |
| `ml_registry`·`chroma_db` 쓰기 마운트 | 2장의 재학습 등 공용 작업 |

---

## 4. 권한 축소 선행 조건 (권고)

1. backup 전용 `WorkerSettings` 를 두어 `functions` 와 `cron_jobs` 에 백업 작업만 등록하고 `queue_name` 을 분리합니다.
2. 1이 끝나면 backup 에서 egress, `extra_hosts` 를 제거하고 `ml_registry`·`chroma_db` 를 `:ro` 로 바꿉니다.
   `data` 는 스냅샷 저장 위치(`data/backups/snapshots`)라 쓰기를 유지합니다.
3. 백업 전용 MySQL 계정(덤프 권한만)은 데이터베이스 변경이라 사용자 결정 대상입니다.
4. 각 단계마다 `tests/test_prod_compose_topology.py` 의 구조 단언을 새 권한에 맞게 바꿉니다.
   현재 단언 `test_backup_keeps_worker_privileges_while_sharing_arq_queue` 는 1 이전에 권한을 걷는 변경을 막습니다.

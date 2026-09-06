# R-02 백업 전용 스케줄 잡 컨테이너 배선 (task_2a088c8fd07b)

> **작성일**: 2026-09-06
> **Task**: task_2a088c8fd07b
> **방향**: 사용자 확정. 백업은 별도 스케줄 잡 컨테이너에서 실행하며 기존 worker에 백업 역할을 주지 않습니다.

## 변경 내용

| 파일 | 변경 |
| --- | --- |
| `docker-compose.prod.yml` | `backup` 서비스 추가. `worker`에는 `BACKUP_SCHEDULE_ENABLED=false` 한 줄만 명시 |
| `Dockerfile` | `backup` 스테이지 추가. 기존 `runtime` 스테이지는 그대로 |
| `.env.example` | `BACKUP_DISK_MIN_FREE_GB` 이름과 설명 추가. 실제 값 없음 |
| `docs/ops/backup_recovery_runbook.md` | 백업 실행 위치와 필요 환경변수 갱신. 다른 절은 그대로 |

## 배선 근거

- `scripts/backup_recovery_core.py`의 `get_db_config`가 `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`, `DB_NAME`을 읽으므로 `backup` 서비스에 전부 전달하며 컨테이너 안에서 `db` 서비스에 붙도록 `DB_HOST=db`, `DB_PORT=3306`으로 고정합니다.
- `mysql_client_command`가 `mysqldump`와 `mysql` 실행 파일을 부르므로 `backup` 스테이지에 `default-mysql-client`를 설치합니다.
- `DEFAULT_SNAPSHOTS_DIR`이 프로젝트 루트의 `data/backups/snapshots`이므로 산출물이 컨테이너 밖에 남도록 `data` 볼륨을 마운트합니다. 백업 대상에 `chroma_db`와 서빙 모델이 들어가므로 `chroma_db`, `ml_registry`도 함께 마운트합니다.
- `backup` 서비스는 `worker`와 같은 arq 진입점으로 띄우되 `BACKUP_SCHEDULE_ENABLED=true`만 켜고 나머지 스케줄 플래그는 `false`로 명시합니다.

## read_only 판단

`backup` 서비스에 `read_only: true`를 켜지 않았습니다. 스냅샷 산출물을 바인드 마운트에 쓰기는 하지만 gzip 임시 생성과 아카이브 작업 경로가 루트 파일시스템 쓰기에 의존할 수 있어 쓰기 차단을 두지 않는 쪽이 안전합니다. `user`, `deploy` 상한, `logging` 회전, `networks`, `depends_on` healthy 조건은 `worker` 블록과 같은 수준으로 맞췄습니다.

## 검증

- `docker compose -f docker-compose.prod.yml config -q`
- `docker build -t refac-bid-box-root:orca-aa2 .`
- `uv run pytest tests/ -q -m 'not data_assets'`
- `python3 scripts/validate_agent_rules.py --quiet`
- 컨테이너를 실제로 띄우지 않았습니다. 검사는 config와 build까지입니다.

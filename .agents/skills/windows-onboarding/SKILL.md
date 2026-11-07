---
name: windows-onboarding
description: Windows 에서 GitHub 저장소를 처음 클론한 팀원이 웹 플랫폼을 실행할 수 있도록 사전 점검, 도구 설치 확인, .env 준비, 데이터 확보, 기동을 에이전트가 안내하고 수행할 때 호출됩니다.
---

# windows-onboarding 스킬 지침

본 스킬은 Windows 실기에서 `refac_bid_box` 저장소를 처음 받은 팀원을 웹 플랫폼 접속까지 안내합니다. 에이전트가 도구와 저장소를 직접 점검하고, 설치가 필요하면 `winget` 명령 목록을 사용자에게 먼저 보여 주고 승인을 받은 뒤 실행합니다. 절차는 0장부터 7장까지 순서대로 진행하며, 앞 장의 확인 없이 다음 장으로 넘어가지 않습니다.

## 0. 안전 규칙

| 규칙 | 내용 |
| --- | --- |
| 설치 전 확인 | 점검 결과 표와 설치할 `winget` 명령 목록을 사용자에게 먼저 보여 주고 승인을 받은 뒤에만 실행합니다. 승인 없는 자동 설치를 하지 않습니다. |
| 관리자 권한 | 관리자 권한이 필요한 단계는 사람이 직접 실행합니다. 에이전트는 명령과 이유만 안내합니다. |
| 재부팅 | `wsl --install` 이후 재부팅, Docker Desktop 첫 실행, BIOS/UEFI 가상화 설정 변경은 사람이 직접 수행합니다. |
| 비밀값 | `.env` 는 `.env.example` 을 기준으로 만들고 `SECRET_KEY`, `MEILI_MASTER_KEY`, `MYSQL_ROOT_PASSWORD`, `G2B_SERVICE_KEY` 값은 사용자에게 받습니다. 에이전트가 값을 생성하거나 추측하거나 문서·커밋에 남기지 않습니다. |
| 데이터 보호 | 코디네이터가 전달한 운영 데이터 덤프와 백업 스냅샷을 공개 저장소에 올리지 않습니다. 받은 경로도 문서와 커밋에 남기지 않습니다. |
| 복원 | `restore --execute --confirm` 은 대상 DB 와 자산을 덮어씁니다. 개발 장비가 맞는지 확인하고 사용자 승인 후에만 실행합니다. |
| 변경 범위 | 저장소 밖의 전역 설정, 방화벽, Windows 계정을 임의로 바꾸지 않습니다. 필요한 변경은 사용자에게 알리고 승인을 받습니다. |

## 1. 사전 점검

점검은 설치하지 않습니다. 저장소 루트에서 아래 스크립트를 실행하면 각 도구의 설치 여부와 버전, WSL2, 가상화, 포트 점유를 표로 출력하고 빠진 항목의 설치 명령을 출력만 합니다.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/windows/check_prereqs.ps1
```

종료 코드는 모두 준비되면 `0`, 빠진 항목이 있으면 `1` 입니다. 포트 점유는 참고 정보이며 종료 코드에 영향을 주지 않습니다.

| 점검 항목 | 요구 사항 | 근거 |
| --- | --- | --- |
| Git | 최신 안정판 | 저장소 클론, `.gitattributes` 줄바꿈 규칙 |
| Docker Desktop | Linux 컨테이너 모드, Compose v2 | `docker-compose.yml` 의 `app`, `worker`, `db`, `redis`, `meilisearch` |
| WSL2 | Docker Desktop 백엔드로 사용 | `docker-compose.yml` Linux 이미지 |
| 가상화 | BIOS/UEFI 가상화 활성 | WSL2 요구 사항 |
| uv | 최신 안정판 | `pyproject.toml`, `uv.lock` |
| Python | 3.11 이상 3.13 미만 | `pyproject.toml` 의 `requires-python` |
| Node.js | 20 LTS 이상, npm 포함 | `package.json` 의 Tailwind CSS 4.3.3 도구 |
| GNU Make | 3.81 이상 | `Makefile` 대상. 없으면 5장의 대체 명령을 사용합니다. |

## 2. 설치

1장의 점검 결과에서 빠진 항목만 골라 아래 명령 목록을 사용자에게 보여 주고 승인을 받습니다. 승인 뒤에도 한 명령씩 실행하고 결과를 확인합니다.

| 항목 | 설치 명령 | 비고 |
| --- | --- | --- |
| Git | `winget install --id Git.Git -e --source winget` | 설치 후 새 터미널에서 `git --version` 확인 |
| Docker Desktop | `winget install --id Docker.DockerDesktop -e --source winget` | 관리자 권한, 첫 실행과 WSL2 백엔드 선택은 사람이 수행 |
| WSL2 | `wsl --install` | 관리자 권한과 재부팅 필요. 이미 설치되어 있으면 `wsl --update` |
| uv | `winget install --id astral-sh.uv -e --source winget` | 설치 후 `uv --version` 확인 |
| Python 3.13 | `winget install --id Python.Python.3.13 -e --source winget` | uv 로 관리하려면 `uv python install 3.13` 사용 |
| Node.js LTS | `winget install --id OpenJS.NodeJS.LTS -e --source winget` | npm 포함. `node --version`, `npm --version` 확인 |
| GNU Make | `winget install --id GnuWin32.Make -e --source winget` | 3.81 버전. PATH 에 없으면 새 터미널에서 `make --version` 확인 |

- `winget` 이 없으면 Microsoft Store 의 App Installer 를 먼저 설치합니다. 이 단계도 사용자 승인 뒤에 진행합니다.
- Docker Desktop 은 설치 후 Linux 컨테이너 모드인지 확인합니다. `docker version` 과 `docker compose version` 이 성공해야 합니다.
- 설치 직후에는 PATH 가 갱신되지 않으므로 새 PowerShell 또는 Git Bash 창에서 버전을 확인합니다.

## 3. 저장소 준비

1. 저장소를 경로가 짧은 위치에 클론합니다. 예: `C:\dev\refac_bid_box`. 경로가 길면 빌드와 자산 복사가 실패할 수 있습니다.
2. `.env` 를 만듭니다.

```powershell
Copy-Item .env.example .env
```

Git Bash 에서는 `cp .env.example .env` 를 사용합니다.

3. 사용자에게 아래 값을 받아 `.env` 에 입력합니다. 값은 에이전트가 만들지 않습니다.

| 변수 | 조건 |
| --- | --- |
| `SECRET_KEY` | 32자 이상. 비어 있거나 짧으면 애플리케이션이 기동하지 않습니다. |
| `MEILI_MASTER_KEY` | 비어 있으면 Compose 구성 단계에서 실패합니다. |
| `MYSQL_ROOT_PASSWORD` | 로컬 개발용 값. `.env.example` 기본값을 그대로 써도 되지만 사용자에게 확인합니다. |
| `G2B_SERVICE_KEY` | 4장 B 경로의 첫 수집에 필요합니다. |
| `G2B_USRINFO_SERVICE_KEY` | 수요기관 수집을 함께 할 때만 필요합니다. |

4. Python 의존성을 동기화합니다.

```powershell
uv sync --all-groups --python 3.13
```

uv 가 관리하는 3.13 인터프리터를 사용하므로 시스템 Python 설치가 없어도 됩니다.

5. 루트의 Tailwind CSS 도구 의존성을 설치합니다.

```powershell
npm ci
```

6. 줄바꿈이 LF 로 체크아웃되었는지 확인합니다. `.gitattributes` 가 `* text=auto eol=lf` 로 고정하므로 정상 클론이면 아래 결과가 `i/lf` 와 `w/lf` 입니다.

```powershell
git ls-files --eol Makefile docker-compose.yml
```

## 4. 데이터 확보

Git 으로 받지 않는 자산은 DB 행, `data/model_files/*/model.bin`, `chroma_db/` 입니다. 아래 A 를 먼저 시도하고, 코디네이터 묶음이 없을 때만 B 로 진행합니다.

### A. 코디네이터 묶음 복원

코디네이터가 전달한 스냅샷 디렉터리를 `<snapshot-dir>` 로 표기합니다. 실제 경로는 코디네이터가 알려 주며, 에이전트가 경로를 지어내지 않습니다.

1. DB 컨테이너를 먼저 띄웁니다.

```powershell
make db-up
```

2. 스냅샷 무결성을 확인합니다.

```powershell
uv run python scripts/backup_recovery.py verify --snapshot-dir <snapshot-dir>
```

3. 복원 계획만 확인합니다. 이 단계는 아무것도 덮어쓰지 않습니다.

```powershell
uv run python scripts/backup_recovery.py restore --snapshot-dir <snapshot-dir>
```

4. 사용자 승인 뒤 실제로 복원합니다.

```powershell
uv run python scripts/backup_recovery.py restore --snapshot-dir <snapshot-dir> --execute --confirm
```

- 스냅샷을 `data/backups/snapshots/snapshot_*` 아래에 두면 `make restore-dry-run`, `make backup-verify` 로 최신 스냅샷을 대상으로 같은 확인을 할 수 있습니다.
- 복원 후 스키마 상태를 읽기 전용으로 확인합니다.

```powershell
make migrate-current
make migrate-check
```

복원된 DB 에는 `make migrate-up` 을 실행하지 않습니다. `migrate-up` 은 빈 신규 DB 전용입니다.

### B. 빈 DB 로 시작하고 첫 수집 실행

코디네이터 묶음이 없을 때의 경로입니다. 모델 가중치는 이 경로로 생기지 않으므로 예측 기능과 `/api/v1/health/ready` 의 `model_registry` 검사는 제한된 상태로 남습니다.

1. 사용자가 `.env` 에 `G2B_SERVICE_KEY` 를 입력했는지 확인합니다.
2. DB 와 Redis 를 띄웁니다.

```powershell
make db-up
```

3. 빈 DB 에 스키마를 적용합니다. 기존 Django DB 에는 절대 실행하지 않습니다.

```powershell
make migrate-up
```

4. 전체 스택을 띄웁니다.

```powershell
make up
```

5. 첫 수집을 실행합니다. 수집 구간만 먼저 확인하려면 `--dry-run` 을 붙입니다.

```powershell
uv run python scripts/backfill_from_g2b.py --since <YYYYMMDD> --sync-downstream
```

- `--since` 를 생략하면 빈 DB 에서는 최근 30일 구간을 수집합니다.
- `--sync-downstream` 은 파생 집계, ChromaDB KB 색인, Meilisearch 색인, 정합성 검사를 이어서 실행합니다.
- KB 색인은 `EMBEDDING_PROVIDER=ollama` 설정을 사용하므로 Ollama 와 임베딩 모델이 없으면 이 단계가 실패할 수 있습니다. 이때는 `--sync-downstream` 없이 적재만 하고, Ollama 준비 후 아래 명령으로 하류 동기화를 다시 실행합니다.

```powershell
uv run python scripts/run_data_reconciliation.py --since <YYYYMMDD>
```

## 5. 실행

Docker Desktop 이 실행 중이고 Linux 컨테이너 모드인지 먼저 확인합니다. 그다음 저장소 루트에서 아래 순서로 진행합니다.

| 순서 | 명령 | 확인 |
| --- | --- | --- |
| 1 | `make up` | `docker compose up --build -d` 와 같습니다. 이미지 빌드에 시간이 걸립니다. |
| 2 | `docker compose ps` | `app`, `worker`, `db`, `redis`, `meilisearch` 상태 확인 |
| 3 | `make logs` | 기동 오류 확인. 종료는 `Ctrl+C` |
| 4 | `make migrate-current` | Alembic 적용 상태 확인 |
| 5 | `make migrate-check` | 모델과 실제 스키마 차이 확인 |

접속 주소는 아래와 같습니다.

| 대상 | 주소 |
| --- | --- |
| 웹 화면 | `http://localhost:8000` |
| API 문서 | `http://localhost:8000/docs` |
| 헬스체크 | `http://localhost:8000/api/v1/health` |
| 준비 상태 | `http://localhost:8000/api/v1/health/ready` |

준비 상태는 `mysql`, `redis`, `model_registry` 가 핵심 검사입니다. 4장 A 로 자산을 복원했다면 `ready` 를 기대할 수 있습니다. 4장 B 로만 진행해 모델 가중치가 없으면 `model_registry` 가 실패해 `503` 과 `not_ready` 가 반환되고 `app` 컨테이너가 `unhealthy` 로 표시됩니다. 이 상태에서도 웹 화면과 수집은 동작하지만 예측 기능은 제한됩니다.

중지와 정리는 아래 명령을 사용합니다.

```powershell
make down
```

GNU Make 가 없을 때는 같은 동작을 아래 명령으로 대체합니다.

| Make 대상 | 대체 명령 |
| --- | --- |
| `make up` | `docker compose up --build -d` |
| `make down` | `docker compose down` |
| `make logs` | `docker compose logs -f` |
| `make db-up` | `docker compose up -d db redis` |
| `make setup` | `uv sync --all-groups` |
| `make migrate-up` | `uv run python -m alembic upgrade head` |
| `make migrate-current` | `uv run python -m alembic current` |
| `make migrate-check` | `uv run python scripts/check_schema_drift.py` |
| `make migrate-verify` | `uv run python scripts/verify_migration.py` |
| `make model-verify` | `uv run python scripts/verify_model_compatibility.py` |
| `make test` | `uv run pytest tests/ -m "not data_assets"` |
| `make backup` | `uv run python scripts/backup_recovery.py backup --execute` |
| `make restore-dry-run` | `uv run python scripts/backup_recovery.py restore --snapshot-dir <snapshot-dir>` |

챗봇까지 확인하려면 Ollama 가 필요합니다. Compose 는 `OLLAMA_BASE_URL=http://host.docker.internal:11434` 로 호스트의 Ollama 를 사용하므로, 호스트에서 Ollama 를 실행해야 합니다. 설치 파일은 `https://ollama.com/download` 에서 받습니다. 이 항목은 웹 플랫폼 기동 자체에는 필수가 아닙니다.

## 6. 문제 해결

| 증상 | 확인 | 조치 |
| --- | --- | --- |
| `wsl --install` 또는 WSL2 커널 오류 | `wsl --status` | 관리자 PowerShell 에서 `wsl --install`, 이미 설치되어 있으면 `wsl --update`. 재부팅은 사람이 수행합니다. |
| Docker Desktop 이 기동하지 않음 | `docker version` 실패 | Docker Desktop 앱을 실행하고 WSL2 백엔드와 Linux 컨테이너 모드를 확인합니다. |
| 가상화 비활성 | `(Get-CimInstance Win32_Processor).VirtualizationFirmwareEnabled` 가 `False` | BIOS/UEFI 에서 가상화를 켭니다. 사람이 직접 수행합니다. |
| 포트 충돌 | `netstat -ano | findstr :3306` 처럼 `3306`, `6379`, `7700`, `8000` 을 확인합니다. | `make down` 으로 기존 스택을 내리고 다시 기동합니다. 다른 프로그램이 점유하면 해당 프로그램을 종료한 뒤 재시도합니다. |
| `make: command not found` | `make --version` 실패 | 5장의 대체 명령 표를 사용하거나 GNU Make 를 설치합니다. |
| 셸 스크립트가 `\r` 오류로 실패 | `git ls-files --eol <파일>` 결과가 `w/crlf` | `git config core.autocrlf false` 로 바꾸고, 로컬 수정이 없는 파일을 삭제한 뒤 `git checkout -- <파일>` 로 다시 받습니다. |
| 경로 길이 초과 | 빌드 중 경로 길이 오류 | 저장소를 `C:\dev` 처럼 짧은 경로에 두고, 필요하면 관리자 권한으로 `git config --system core.longpaths true` 를 설정합니다. |
| Compose 구성 단계 실패 | `SECRET_KEY`, `MEILI_MASTER_KEY` 누락 오류 | `.env` 에 두 값을 채웁니다. 값은 사용자에게 받습니다. |
| `/api/v1/health/ready` 가 `503` | 응답의 `checks` 에서 실패 항목 확인 | `mysql`, `redis`, `model_registry`, `chromadb`, `meilisearch` 중 실패 원인을 확인하고 `make logs` 로 앱 로그를 봅니다. 모델 가중치가 없으면 4장 A 복원이 필요합니다. |
| DB 테이블이 없음 | `make migrate-current` 가 비어 있음 | 빈 신규 DB 에서만 `make migrate-up` 을 실행합니다. 복원 대상 DB 에는 실행하지 않습니다. |

## 7. 실행 확인

본 스킬은 컨테이너 기동과 접속 확인까지만 다룹니다. 기동 후 기능 점검(로그인, 공고 목록, 예측, 챗봇, 검색)은 `platform-health-checklist` 스킬의 기능 점검 절차로 넘깁니다.

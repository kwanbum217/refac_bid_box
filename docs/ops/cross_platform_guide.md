# 크로스 플랫폼 호환 가이드 (macOS / Windows)

> **작성일**: 2026-07-31
> **갱신일**: 2026-08-06
> **상태**: macOS 검증 완료 / Windows CI 통과 / Windows 호스트 전체 스택 검증 대기
> **관련**: [`docs/design/REFACTORING_DESIGN.md`](../design/REFACTORING_DESIGN.md) 6장

---

## 1. 목적

macOS와 Windows에서 **동일한 환경**으로 개발하고 실행하기 위한 가이드입니다. 기존 프로젝트의 플랫폼 종속 문제를 해결합니다.

---

## 2. 기존 플랫폼 종속 문제와 해결

| 문제 | 원인 | 해결 |
| --- | --- | --- |
| `mysqlclient` 빌드 실패 | macOS에서 C 확장 빌드 의존성 | Docker MySQL + PyMySQL(순수 파이썬) |
| `hc.exe` Windows 바이너리 | Harness CLI Windows 전용 | Git 제거, CI 다운로드 또는 REST API |
| `.ps1` 스케줄러 | Windows 작업 스케줄러 | Celery Beat (크로스플랫폼) |
| 환경 차이 | 로컬 직접 설치 | Docker + Makefile 표준화 |
| 경로 구분자 | `\` vs `/` | `pathlib.Path` 전면 사용 |
| 인코딩 | 시스템 기본 인코딩 차이 | UTF-8 강제 |
| 체크섬 매니페스트 키 | `str(Path)` 가 Windows 에서 `\` 를 냄 | `as_posix()` 고정 (2026-08-06) |
| 줄바꿈 | `core.autocrlf=true` 가 Makefile 을 CRLF 로 체크아웃 | `.gitattributes` 로 `eol=lf` 고정 (2026-08-06) |

---

## 3. 표준 실행 환경 (Docker)

### 3.1 전체 스택 (docker-compose)

정본은 루트의 `docker-compose.yml`입니다. 기본 서비스는 FastAPI `app`, MySQL
8 `db`, Redis 7 `redis`입니다. React 스캐폴드는 `legacy` 프로필에서만
기동합니다.

### 3.2 실행 명령

| 작업 | 명령 |
| --- | --- |
| 전체 스택 기동 | `make up` 또는 `docker compose up -d` |
| DB + Redis만 | `make db-up` |
| 개발 서버 | `make dev` |
| Alembic 상태 확인 | `make migrate-current` |
| 기존 DB 스키마 점검 | `make migrate-check` |
| 신규 빈 DB 스키마 생성 | `make migrate-up` |
| 테스트 | `make test` |
| 중지 | `make down` |

---

## 4. Makefile 진입점

macOS와 Windows(Git Bash) 모두에서 동작하는 단일 진입점입니다.

실제 타깃은 루트 `Makefile`을 사용합니다. Windows에서는 `.venv/Scripts/python.exe`,
macOS에서는 `.venv/bin/python`을 자동 선택합니다.

기존 Django 운영 DB에 `make migrate-up`을 실행하지 마십시오. 기존 DB는
`make migrate-current`와 `make migrate-check`로 읽기 전용 확인하며, 신규 빈
Docker DB에만 `make migrate-up`을 사용합니다.

Windows에서는 Docker Desktop을 Linux 컨테이너 모드로 실행하고 Git Bash의
`make` 또는 GNU Make를 설치합니다.

모델 가중치와 ChromaDB는 Git으로 관리하지 않습니다. 따라서 가중치 없는 새 체크아웃의 make test는 외부 자산 의존 G1 테스트를 제외하고 실행합니다. 자산을 복원한 환경에서는 make test-data-assets, make migrate-verify, make model-verify를 추가로 실행해 G1 무결성과 모델 호환성을 확인하십시오.

---

## 5. 인코딩 가드

- 모든 파일 입출력에 `encoding="utf-8"` 명시.
- CSV/parquet 로드 시 인코딩·구분자 자동 감지 로직 유지.
- DB 연결 charset `utf8mb4` 고정.

---

## 5.1 새 장비 셋업: 모델 가중치 배포

**저장소 클론만으로는 예측 API 가 뜨지 않습니다.** 가중치 바이너리는 Git 추적
대상이 아니어서(`.gitignore` 의 `*.bin`, `*.joblib`) 새 장비에는 `metadata.json`
만 도착합니다. `metadata.json` 이 있다고 모델이 있는 것으로 판단하지 마십시오.

기존 장비에서 번들을 만듭니다.

```bash
uv run python scripts/sync_model_files.py export
# dist/model_files_bundle.tar.gz 와 .sha256 사이드카가 생깁니다
```

번들과 사이드카를 함께 새 장비로 옮긴 뒤 들여옵니다.

```bash
uv run python scripts/sync_model_files.py verify   # 배치 없이 무결성만 확인
uv run python scripts/sync_model_files.py import   # 검증 통과 시에만 배치
```

`import` 는 배치 전에 검증을 먼저 수행하며, 실패하면 아무것도 쓰지 않습니다.
기존 가중치가 있는 경로에는 `--force` 없이 덮어쓰지 않습니다.

배치 후 반드시 확인합니다.

```bash
uv run python scripts/verify_migration.py     # 1/4 항목이 G1 무결성입니다
uv run python scripts/promote_model.py status
```

| 항목 | 내용 |
| --- | --- |
| 번들 구성 | `model_files/`, `model_backups/`, `model_metrics/` |
| 크기 | 82MB -> 압축 29.8MB (2026-08-06 실측) |
| 무결성 | 파일별 SHA256 + 번들 사이드카 |
| 제외 | `__pycache__` (장비마다 파이썬 버전이 다릅니다) |

`model_backups/` 를 빼면 안 됩니다. 승격된 모델은 서빙본이 원본과 달라지므로
`verify_migration.py` 가 원본 기준선을 백업 쪽에서 대조합니다. 백업 없이 실측한
결과 G1 검증이 체크섬 불일치로 실패했습니다.

경로를 외부 볼륨으로 옮기려면 `MODEL_FILES_DIR`, `MODEL_BACKUPS_DIR`,
`MODEL_METRICS_DIR` 을 함께 바꾸십시오. 셋은 함께 움직여야 합니다.

`scripts/import_data_assets.py` 는 원본 `bid_box` 저장소가 옆에 있을 때 쓰는
최초 이관용이며 새 장비에서는 동작하지 않습니다. 또한 그 스크립트는 체크섬
매니페스트를 재생성하므로, 승격이 일어난 뒤 실행하면 G1 기준선이 현재
서빙본으로 덮여 무손실 검증이 의미를 잃습니다.

---

## 6. Windows 전체 스택 검증

PowerShell에서 다음을 실행합니다.

```powershell
powershell -ExecutionPolicy Bypass -File scripts/validate_windows.ps1
```

스크립트는 `uv sync`, `make test`, `make dev` 진입점 확인, Docker Compose
빌드·기동, 신규 격리 DB의 Alembic 적용, 스키마 드리프트 검사, FastAPI
헬스체크를 수행합니다. 검증용 Compose 프로젝트만 중지하고 볼륨은 삭제하지
않습니다.

---

## 7. CI 크로스 플랫폼 검증

GitHub Actions에서 macOS/Windows의 Python 테스트를 수행합니다. GitHub 호스팅
Windows 러너는 Linux 컨테이너 기반 전체 Compose 스택 검증을 대신하지 않습니다.

```yaml
# .github/workflows/ci.yml (개념)
strategy:
  matrix:
    os: [ubuntu-latest, macos-latest, windows-latest]
runs-on: ${{ matrix.os }}
steps:
  - uses: actions/checkout@v4
  - uses: astral-sh/setup-uv@v3
  - run: uv sync
  - run: uv run pytest -q
```

---

## 8. 체크리스트

- [x] Dockerfile 작성 (파이썬 슬림 이미지)
- [x] docker-compose.yml 작성 (`app`, `db`, `redis`)
- [x] Makefile 작성
- [x] macOS에서 `make up` 실행 검증
- [x] Windows에서 `uv run pytest -q` 실행 검증 (GitHub Actions windows-latest)
- [x] CI Python 매트릭스 테스트 통과 (macOS/Windows) — 2026-08-06 실제 통과 확인
- [x] `.gitattributes` 줄바꿈 가드 (데이터 자산은 변환 제외)
- [ ] Windows Docker Desktop에서 `scripts/validate_windows.ps1` 전체 통과

### 2026-08-06 정적 감사 결과

Windows 장비가 없어 실행 검증 대신 정적 감사와 CI 로 확인했습니다.

| 점검 항목 | 결과 |
| --- | --- |
| `open()` 인코딩 누락 | 없음 (바이너리 모드 2건만) |
| 하드코딩 `/tmp`, `.exe`, `fcntl`/`pwd`/`os.fork` | 없음 |
| 문자열 `+ "/"` 경로 조합 | 없음 |
| `os.symlink`/`chmod`, 로케일 의존 | 없음 |
| 대소문자만 다른 동일 경로 | 없음 |
| 빌드 진입점 줄바꿈 | Dockerfile/Makefile/compose 모두 LF |
| **체크섬 매니페스트 경로** | **결함 발견 후 수정** (`as_posix`) |

CI 의 windows-latest 작업은 이 결함으로 실패하고 있었으며, 수정 후 3개 작업
(macOS / Windows / lint) 전량 통과를 확인했습니다.

남은 미검증 영역은 **Windows 호스트의 Docker Compose 전체 스택**입니다. GitHub
호스팅 Windows 러너는 Linux 컨테이너 스택을 대신하지 못하므로 실제 장비가
필요합니다.

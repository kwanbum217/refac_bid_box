# ORM Mapped 1차 완료 및 종료 인수인계 (2026-08-21)

> **작성일**: 2026-08-21 (Asia/Seoul)
> **작성자**: Codex 코디네이터
> **인수 대상**: 다음 코디네이터 세션
> **ORM 병합 기준 main**: `20e0966`
> **Orca Run**: `run_5e17d4052908`
> **종료 상태**: 작업 완료, 원격 반영 완료, Docker 스택 종료

---

## 1. 완료된 작업

`src/app/models/bids.py`의 5개 ORM 모델·50개 컬럼을 SQLAlchemy 2.0
`Mapped[]`와 `mapped_column()` 선언으로 전환했습니다. 테이블명, 컬럼명과 순서,
MySQL·SQLite 타입, nullable, PK, 기본값, onupdate, FK, unique 제약 및 인덱스는
변경하지 않았습니다.

| 항목 | 결과 |
| --- | --- |
| `main` 및 `origin/main` | `20e0966` 일치 |
| ORM 정규화 메타데이터 지문 | 전후 `1946466aa8bfcec12c724277931c6c2fb868cb3d544cce65bb926a1f7fbf149e` 일치 |
| 대상 테스트 | 160 passed |
| 전체 테스트 | 1676 passed, 2 skipped |
| mypy | 89개 소스 파일 통과 |
| 실제 MySQL 8 스키마 drift | 실질 차이 0건 |
| 데이터 보존 검증 | ML 가중치, ChromaDB, DB 스키마·행 수 통과 |
| 에이전트 규칙 | 12/12 통과 |
| 독립 검토 | Gemini 3.7 Flash High 승인, 파일 변경 0건 |

관련 파일은 다음과 같습니다.

- `src/app/models/bids.py`
- `tests/test_model_schema_parity.py`
- `pyproject.toml`
- `docs/context/CURRENT_STATE.md`

Orca Run의 구현, 회귀 테스트, 사전 감사, 통합 검증, 최종 독립 검토 Task 5건은
모두 `completed`입니다. 격리 워크트리와 작업 브랜치, 워커 터미널은 병합 후
정리했습니다.

---

## 2. 다음 작업 순서

### 2.1 ORM Mapped 2차

가장 먼저 `src/app/models/chatbot.py`를 전환합니다. 다음 두 JSON 컬럼이 아직
구식 `Column(JSON)` 선언이라 mypy `call-overload` 예외 2개가 남아 있습니다.

| 모델 | 컬럼 | 현재 영향 |
| --- | --- | --- |
| `AutomationRequest` | `result_payload` | `src.app.services.automation_responses` 예외 유지 |
| `PipelineExecution` | `raw_status_payload` | `src.app.services.automation_orchestrator` 예외 유지 |

전환 후 `pyproject.toml`의 위 두 모듈 예외를 제거하고 `uv run mypy src/`로
검증합니다. JSON 기본값 `default=dict`는 Python 기본값으로 유지하며
`server_default`로 바꾸지 않습니다.

### 2.2 ORM Mapped 잔여 모델

`src/app/models/chatbot.py` 다음에는 아래 파일을 독립 작업 단위로 전환합니다.

1. `src/app/models/accounts.py`
2. `src/app/models/predictions.py`

각 작업은 전환 전 결정론적 메타데이터 지문을 기록하고, 전환 후 동일 지문과
실제 MySQL `make migrate-check`를 모두 통과해야 합니다. Alembic 마이그레이션은
생성하지 않습니다.

### 2.3 CURRENT_STATE의 나머지 우선순위

| 순서 | 작업 | 시작 조건 |
| :---: | --- | --- |
| 1 | 블로킹 I/O 12건의 P95·태스크 처리량 실측 | Docker 독점 점유와 실측 시간 확보 |
| 2 | Ollama `OLLAMA_NUM_PARALLEL` 및 SSE c4 기준선 | 사용자 동석, 호스트 Ollama 재기동 승인 |
| 3 | Windows Docker Desktop 실기 검증 | Windows 실기 환경 확보 |
| 4 | 수집 2·3회차 관찰 | Docker 스택 기동 |

성능 개선은 실측 전까지 주장하지 않습니다. Ollama 실험은 규약상 중간 결과를
판정 근거로 쓸 수 없으므로 완주 시간을 확보한 세션에서만 시작합니다.

---

## 3. 다음 세션 재개 절차

다음 세션은 `AGENTS.md`와 `docs/context/CURRENT_STATE.md`를 먼저 읽고 아래를
확인합니다.

```bash
git status --short
git branch --show-current
git rev-parse HEAD
git rev-parse origin/main
docker compose ps
```

Docker 스택이 필요하면 다음 순서로 재개합니다.

```bash
make up
docker compose ps
make migrate-check
```

종료 시점의 Docker 컨테이너는 모두 내려가 있지만 데이터 볼륨과 이미지는
삭제하지 않았습니다. `docker compose down -v` 또는 볼륨 삭제 명령은 실행하지
마십시오.

---

## 4. 종료 전 확인 상태

| 항목 | 상태 |
| --- | --- |
| Git 브랜치 | `main` |
| Git 원격 동기화 | ORM 병합 기준 `HEAD == origin/main == 20e0966`, 본 문서도 별도 병합·푸시 |
| 미커밋 변경 | 없음 |
| 활성 ORM 워크트리 | 없음 |
| 활성 ORM 워커 터미널 | 없음 |
| Docker 컨테이너 | 정상 종료 |
| Docker 볼륨·이미지 | 보존 |

실제 macOS 종료 명령은 실행하지 않았습니다. 이 문서의 커밋과 원격 반영,
Docker 종료 확인 이후 사용자가 운영체제를 종료하면 됩니다.

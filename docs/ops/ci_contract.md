# CI 운영 계약 및 워크플로우 명세 (CI Contract)

> **작성일**: 2026-09-02
> **버전**: v1.0.0
> **관련 워크플로우**: `.github/workflows/ci.yml`
> **단일 진실 원천**: `AGENTS.md` 및 `docs/context/CURRENT_STATE.md`

---

## 1. 개요 및 기본 원칙

본 문서는 `refac_bid_box` 저장소의 지속적 통합(Continuous Integration, CI) 파이프라인 구성과 운영 계약을 정의합니다.

본 저장소는 1인 개발 체계로 Pull Request(PR)를 생성하지 않고 작업 브랜치에서 직접 검증 후 `main`에 `git merge --no-ff`로 병합하는 방식을 따릅니다. 따라서 CI는 병합 전 모든 작업 브랜치에서의 푸시 이벤트를 완벽히 감지하여 회귀 및 결함을 사전 차단해야 합니다.

### 3대 핵심 원칙

1. **사각지대 없는 브랜치 검증**: 작업 브랜치 명명 규칙(`kwanbum217/**`, `feature/**`, `fix/**`, `docs/**` 등)에 관계없이 모든 브랜치 푸시에 대해 CI가 자동으로 실행됩니다.
2. **확인 전용 린트 및 게이트 불변**: CI 및 로컬 전체 검증(`make check-all`)은 파일을 수정하지 않는 확인 전용 명령을 일관되게 사용하며, 실패를 묵인하는 `continue-on-error`는 절대 허용하지 않습니다.
3. **실측 기반 커버리지 게이트**: 실측 테스트 커버리지(85.17%)를 기준으로 현실적이고 안전한 회귀 방지 하한선(80%)을 적용하여 품질 저하를 방지합니다.

---

## 2. 트리거 계약 (Trigger Contract)

### 2.1 Push 트리거

```yaml
on:
  push:
    branches: [ '**' ]
    tags-ignore: [ '**' ]
  pull_request:
    branches: [ main ]
```

- **모든 브랜치 수용 (`branches: ['**']`)**: 작업자가 생성하는 모든 접두사 및 브랜치에서의 변경 사항에 대해 CI가 트리거됩니다.
- **태그 중복 실행 방지 (`tags-ignore: ['**']`)**: 릴리스 태그 푸시 시 동일 커밋에 대한 불필요한 중복 실행을 차단합니다.
- **PR 보조 트리거**: 외부 기여 또는 PR 생성 상황에 대비한 보조 트리거로 유지됩니다.

---

## 3. Job 구성 및 게이트 명세

CI는 4개의 핵심 병렬/독립 Job으로 구성되며, 전 Job이 통과해야만 정상 상태로 판정됩니다.

| Job 이름 | 실행 환경 | 주요 검증 항목 | 통과 조건 및 게이트 |
| --- | --- | --- | --- |
| `lint-and-validate` | Ubuntu 22.04 / Python 3.11 / Node 22 | Ruff 린트, Ruff 포맷 검사, Bandit 보안 스캔, Mypy 타입 검사, 다중 에이전트 규칙 정합성, 문서 링크 유효성, Actionlint, 프론트엔드 테스트 및 빌드, Tailwind CSS 재현성 | 전 단계 종료 코드 0 (확인 전용) |
| `cross-platform-test` | Ubuntu (3.11, 3.12, 3.13), macOS (3.11), Windows (3.11) | SQLite 인메모리 기반 단위/통합/E2E 테스트, Pytest 커버리지 측정 | `not data_assets` 전량 통과, 커버리지 하한 80% 이상 |
| `docker-build` | Ubuntu 22.04 | 운영 Dockerfile 빌드 및 앱 엔트리포인트 스모크 임포트 | 이미지 빌드 성공 및 `import src.app.main` 통과 |
| `mysql-ngram-integration` | Ubuntu 22.04 / MySQL 8.0 컨테이너 | 격리 MySQL 인스턴스 기반 ngram, 방언 차이, 동시성 검증 | `tests/test_ngram_prefilter_equivalence.py`, `tests/test_mysql_integration_queries.py`, `tests/test_mysql_concurrency.py` 통과, 0건 skip, 1건 이상 pass |

---

## 4. 커버리지 게이트 계약 (Coverage Gate Contract)

### 4.1 실측치 및 하한선 기준

- **실측 커버리지 (2026-09-02 기준)**: **85.17%** (전체 9,967 구문 중 8,489 구문 실행, 1,478 누락)
- **CI 게이트 하한선 (`fail_under`)**: **80.00%**

### 4.2 하한선 설정 근거

1. **상시 Red 방지**: 실측치(85.17%)보다 임의로 높은 기준(예: 90%)을 부여할 경우 정상적인 리팩토링 및 기능 추가 시 CI가 상시 실패하여 게이트의 신뢰성이 상실됩니다.
2. **회귀 차단**: 실측치보다 약 5%p 낮은 80%를 하한선으로 두어, 테스트가 누락된 대규모 코드 추가나 기존 테스트 삭제 시 즉시 CI가 차단되도록 방어선을 구축합니다.
3. **환경 설정 통일**: `pyproject.toml`의 `[tool.coverage.report]`에 `fail_under = 80`을 명시하고, CI 실행 명령에 `--cov=src --cov-report=term-missing --cov-fail-under=80`을 결박하여 로컬과 CI가 동일하게 하한선을 강제합니다.

---

## 5. 로컬 검증(`make`)과 CI의 1:1 계약

로컬 개발 환경에서의 사전 검증 도구와 CI 워크플로우 명령은 1:1로 일치해야 합니다.

| 검증 단계 | 로컬 Makefile 타깃 | CI 실행 명령 | 비고 |
| --- | --- | --- | --- |
| Ruff 린트 | `make lint` | `uv run ruff check .` && `uv run ruff format --check .` | 파일 무수정 확인 전용 |
| 코드 포맷팅 | `make format` | (CI에서는 실행하지 않음) | 로컬 전용 자동 수정 |
| 보안 스캔 | `make security` | `uv run bandit -c pyproject.toml -r src/ scripts/` | 동일 설정 |
| 정적 타입 검사 | `make typecheck` | `uv run mypy src/` | Python 3.12 스텁 기준 동일 |
| 규칙 정합성 | `make check-rules` | `python3 scripts/validate_agent_rules.py --quiet` | 정본 규칙 일치 |
| 워크플로우 린트 | `make lint-workflows` | `uv run actionlint` | 동일 도구 |
| 전체 품질 검증 | `make check-all` | `lint-and-validate` Job 전반 | 단일 진입점 통일 |
| 백엔드 테스트 | `make test` | `uv run pytest -q -m "not data_assets" --cov=src ...` | 커버리지 측정 포함 |

---

## 6. 후속 과업 (Future Work)

### 6.1 MySQL 8 통합 테스트 범위 확대

- **현황**: CI의 MySQL 전용 Job은 `tests/test_ngram_prefilter_equivalence.py`, `tests/test_mysql_integration_queries.py`, `tests/test_mysql_concurrency.py`를 `mysql_integration` 마커로 실행합니다.
- **선정 기준**: SQLite와 MySQL에서 결과 또는 실행 가능성이 달라지는 콜레이션, 숫자 나눗셈, `ONLY_FULL_GROUP_BY`, 날짜 버킷 함수, JSON 스칼라 추출만 대상으로 삼습니다. 단순 CRUD와 양쪽 엔진에서 동일한 SQLAlchemy 컴파일 검사는 제외합니다.
- **범위**: 새 파일에는 방언 차이 통합 테스트를 최대 5개 추가하고, 기존 SQLite 테스트는 그대로 유지합니다. 테스트는 `tests/fixtures/ngram_mysql_init.sql`로 주입한 격리 스키마에서 읽기 전용으로 실행합니다.
- **과업 목표**: SQLite 인메모리와 실제 MySQL 8 간의 주요 방언 차이를 CI에서 조기에 확인합니다.
- **선행 요건**:
  1. 테스트 스위트 실행 시간 증가(CI latency budget) 영향도 분석
  2. MySQL 인스턴스 셋업 및 병렬 실행 시 테이블 격리/클린업 전략 수립
  3. 방언 차이가 유의미한 쿼리 목록 도출

### 6.2 동시성 및 세션 복구 통합 테스트

- **현황**: 2026-09-02 Capsule `task_g2_mysql_concurrency` 결과로 `tests/test_mysql_concurrency.py` 가 추가되었습니다. 이 파일은 SQLite 인메모리로는 드러나지 않는 MySQL InnoDB 의 트랜잭션/세션 상태 동작 5종을 검증합니다.
- **선정 기준**: 명시적 트랜잭션의 rollback 복구, `SELECT ... FOR UPDATE` 행 잠금 대기(`innodb_lock_wait_timeout`), 데드락 자동 감지(`OperationalError 1213`), UNIQUE 위반 commit 실패 후 복구, 동시 INSERT 후 멱등 결론 회복만 포함합니다.
- **격리 스키마**: `concurrency_test` 라는 전용 스키마를 모듈 시작 시 생성·종료 시 DROP 합니다. 운영 스키마 `procurement` 및 운영 테이블(`bid_announcements`, `bid_results`, `automation_requests` 등)에는 어떤 영향도 주지 않습니다.
- **벽시계 단언 정책**: 잠금 대기는 항상 예외 종류/원본 에러 코드로 판정합니다. 2026-09-02 의 0.1초 vs 0.08초 단언 회귀처럼, `time.sleep(N)` + 정해진 시간 내 완료 단언은 사용하지 않습니다.
- **CI 합류**: `mysql-ngram-integration` Job의 pytest 명령에 `tests/test_mysql_concurrency.py`를 합류했습니다. 0건 skip / 1건 이상 pass 게이트가 동일하게 적용됩니다.
- **skip 의 의미**: MySQL 부재 환경에서 5건 모두 skip 됩니다. skip 은 통과가 아니며, 보고서(`docs/analysis/task_bedb4b8bf44b.md`) 에 실행 여부가 정확히 기록됩니다.
- **실측 결과 (2026-09-02)**: `MYSQL_TEST_URL`로 MySQL 8 인스턴스에 연결한 지정 명령에서 5건 모두 통과했으며 skip은 0건이었습니다. 상세 결과와 전체 회귀 검증 결과는 `docs/analysis/task_bedb4b8bf44b.md`에 기록합니다.

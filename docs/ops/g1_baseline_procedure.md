# G1 기준선 생성 및 검증 절차

> G1 기준선은 데이터 무손실 검증의 출발점입니다.
> 검증 명령은 기준선을 자동으로 만들거나 갱신하지 않으며, 기준선이 없으면 실패합니다.

---

## 1. 기준선 생성

운영 DB에 연결할 수 있고 데이터 상태를 별도로 확인한 뒤에만 다음 명령을 실행합니다.

```bash
uv run python scripts/verify_migration.py --generate-schema-baseline
uv run python scripts/verify_migration.py --generate-reconciliation-baseline
```

스키마 기준선은 `data/backups/schema_signature_baseline.json`에, reconciliation 기준선은
`data/backups/row_count_reconciliation_baseline.json`에 기록됩니다. 두 명령은 검증을
수행하지 않고 기준선 생성 결과만 반환하므로, 생성 전에 DB가 손상되지 않았는지 담당자가
확인해야 합니다.

각 기준선에는 다음 출처 메타데이터가 포함됩니다.

| 항목 | 내용 |
| --- | --- |
| `generated_at` | 기준선 생성 시각(UTC) |
| `database_identifier` | 비밀번호를 숨긴 DB URL 식별자 |
| `generated_by` | 기준선 생성 운영 사용자 |
| `tool_version` | 검증 도구 버전 |
| `git_head` | 기준선 생성 당시 Git HEAD |

## 2. 기준선 검증

기준선을 생성한 뒤 다음 명령으로 검증합니다.

```bash
uv run python scripts/verify_migration.py
```

검증 경로에서는 기준선 파일을 생성하거나 수정하지 않습니다. 스키마 기준선 또는
reconciliation 기준선이 없거나, 출처 메타데이터가 없거나 불완전하면 즉시 실패합니다.

스키마 테이블 집합은 하드코딩 목록을 사용하지 않고 SQLAlchemy `Base.metadata`에 등록된
ORM 전체 테이블로 계산합니다. `src/app/models/__init__.py` 가 평가 모델을 포함해
등록된 ORM 을 모두 가져와야 합니다. DB에만 있는 테이블과 ORM에만 있는 테이블을 모두
보고하며, `APPROVED_EXTERNAL_TABLES` 에 없는 DB 테이블은 경고와 함께 실패 처리합니다.
Django 잔여 테이블, `alembic_version`, `servc_inst_verify` 는 승인된 외부 테이블입니다.

## 3. 테스트

DB 접속 없이 다음 단위 테스트로 fail-closed 동작과 테이블 집합 검증을 확인할 수 있습니다.

```bash
uv run pytest tests/test_g1_schema_signature.py tests/test_verify_migration_fail_closed.py -q
```

## 4. 로컬 실행 증적 보관 절차

G1 검증을 로컬에서 실행할 때는 언제, 어느 커밋에서, 무엇을 통과했는지 증적을 남깁니다. 증적이 없으면 같은 판정을 재현하기 위해 처음부터 다시 실행해야 합니다.

1. 검증 전에 `git rev-parse HEAD` 로 대상 커밋 SHA 를 기록합니다.
2. Makefile 에 실재하는 대상만 실행합니다: `make migrate-verify`, `make model-verify`, `make test-data-assets`.
3. 실행 결과(표준출력·종료 코드)를 `data/benchmarks/g1_runs/<날짜>/` 에 결과 파일로 남깁니다. 이 디렉터리는 증적을 만들 때만 생성하며, 본 절차 문서가 미리 만들지 않습니다.
4. 결과 파일에는 실행 일시(UTC), 대상 커밋 SHA, 실행한 make 대상, 종료 코드를 함께 적습니다.

`data/benchmarks/g1_runs/` 는 증적 보관 위치 제안이며, 보존 정책이 바뀌면 함께 재검토합니다.

## 5. 기준선 드리프트 정적 게이트

기준선이 ORM(`src.app.models` 의 `Base.metadata`)과 Alembic 마이그레이션(`migrations/versions/*.py`)보다 뒤처지면 CI 가 실패합니다. 이 게이트는 `tests/test_g1_baseline_drift_gate.py` 이며 DB 에 접속하지 않고 동작합니다. 마이그레이션 파일은 import 하지 않고 ast 로 `upgrade()` 본문만 읽으므로 alembic 런타임도 필요하지 않습니다.

막는 조건은 다음과 같습니다.

- 기준선 `tables` 에 없는 ORM 테이블 또는 컬럼
- 기준선 `orm_tables` 와 실제 ORM 테이블 집합의 불일치
- `upgrade()` 가 만들지만 기준선 `tables` 또는 해당 테이블 `indexes` 에 없는 테이블·인덱스. `op.execute` 원문 SQL 의 `CREATE [UNIQUE] INDEX`, `ADD [UNIQUE] INDEX` 도 포함하며, `downgrade()` 의 drop 은 세지 않습니다.
- 이름을 모듈 상수·f-string·for 루프로 정적으로 정할 수 없는 create 호출은 조용히 건너뛰지 않고 실패로 보고합니다.

스키마를 바꾸는 마이그레이션을 병합하기 전에 DB 에 적용한 뒤 기준선을 갱신합니다.

```bash
uv run python scripts/verify_migration.py --generate-schema-baseline
uv run pytest tests/test_g1_baseline_drift_gate.py -q
```

갱신 후 기존 테이블 정의 변경이 0건인지 `git diff data/backups/schema_signature_baseline.json` 으로 대조합니다. 새 테이블·인덱스 항목만 늘고 기존 항목의 컬럼·타입·제약조건은 변하지 않아야 합니다.

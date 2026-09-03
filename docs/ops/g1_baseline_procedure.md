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
ORM 전체 테이블로 계산합니다. DB에만 있는 테이블과 ORM에만 있는 테이블을 모두 보고하며,
승인 목록에 없는 DB 테이블은 경고와 함께 실패 처리합니다.

## 3. 테스트

DB 접속 없이 다음 단위 테스트로 fail-closed 동작과 테이블 집합 검증을 확인할 수 있습니다.

```bash
uv run pytest tests/test_g1_schema_signature.py tests/test_verify_migration_fail_closed.py -q
```

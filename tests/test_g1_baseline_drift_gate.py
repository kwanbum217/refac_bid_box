"""G1 스키마 서명 기준선 드리프트 정적 게이트.

DB 에 접속하지 않고 두 출처를 기준선(data/backups/schema_signature_baseline.json)과
대조합니다.

1. ORM: ``src.app.models`` 의 ``Base.metadata.tables`` 테이블 집합과 컬럼 이름 집합.
2. Alembic: ``migrations/versions/*.py`` 의 ``upgrade()`` 본문을 ast 로 파싱해 얻은
   ``op.create_table``, ``op.create_index``, ``op.execute`` 의 CREATE·ADD INDEX 이름.

스키마를 바꾸는 커밋이 기준선 갱신 없이 병합되면 이 테스트가 실패합니다.
판정 로직은 기준선 dict 를 인자로 받는 순수 함수라 기준선 사본으로 음성 대조할 수 있습니다.

마이그레이션 모듈은 import 하지 않습니다. ast 로만 읽으므로 DB 나 alembic 런타임이
없어도 동작합니다.
"""

from __future__ import annotations

import ast
import copy
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BASELINE_PATH = PROJECT_ROOT / "data" / "backups" / "schema_signature_baseline.json"
MIGRATIONS_DIR = PROJECT_ROOT / "migrations" / "versions"

BASELINE_REMEDY = (
    "기준선이 ORM/마이그레이션보다 뒤처졌습니다. 마이그레이션을 DB 에 적용한 뒤 "
    "`uv run python scripts/verify_migration.py --generate-schema-baseline` 로 "
    "data/backups/schema_signature_baseline.json 을 갱신하고, 기존 테이블 정의 변경이 "
    "0건인지 docs/ops/g1_baseline_procedure.md 절차로 대조하십시오."
)

_UNRESOLVED = object()

_ALTER_TABLE_RE = re.compile(r"ALTER\s+TABLE\s+[`\"]?([A-Za-z_][\w$]*)[`\"]?", re.IGNORECASE)
_CREATE_INDEX_RE = re.compile(
    r"CREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:IF\s+NOT\s+EXISTS\s+)?[`\"]?([A-Za-z_][\w$]*)[`\"]?",
    re.IGNORECASE,
)
_ON_TABLE_RE = re.compile(r"\bON\s+[`\"]?([A-Za-z_][\w$]*)[`\"]?", re.IGNORECASE)
_ADD_INDEX_RE = re.compile(
    r"\bADD\s+(?:UNIQUE\s+)?INDEX\s+[`\"]?([A-Za-z_][\w$]*)[`\"]?",
    re.IGNORECASE,
)


@dataclass
class MigrationCreates:
    """upgrade() 본문이 만드는 테이블·인덱스와 정적으로 정할 수 없는 이름."""

    created_tables: dict[str, str] = field(default_factory=dict)
    created_indexes: dict[tuple[str, str], str] = field(default_factory=dict)
    unresolved: dict[str, str] = field(default_factory=dict)


def _static_eval(node: ast.expr | None, constants: dict[str, object], env: dict[str, object]):
    """리터럴·모듈 상수·f-string 정도만 정적으로 평가합니다."""
    if node is None:
        return _UNRESOLVED
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        if node.id in env:
            return env[node.id]
        if node.id in constants:
            return constants[node.id]
        return _UNRESOLVED
    if isinstance(node, ast.Tuple):
        return tuple(_static_eval(element, constants, env) for element in node.elts)
    if isinstance(node, ast.List):
        return [_static_eval(element, constants, env) for element in node.elts]
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
                continue
            if isinstance(value, ast.FormattedValue):
                resolved = _static_eval(value.value, constants, env)
                parts.append(resolved if isinstance(resolved, str) else "\x00")
                continue
            parts.append("\x00")
        return "".join(parts)
    return _UNRESOLVED


def _resolve_str(node: ast.expr | None, constants: dict[str, object], env: dict[str, object]):
    value = _static_eval(node, constants, env)
    return value if isinstance(value, str) else _UNRESOLVED


def _module_constants(tree: ast.Module) -> dict[str, object]:
    """모듈 수준 ``NAME = <리터럴>`` 대입을 이름 해석용으로 모읍니다."""
    constants: dict[str, object] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name):
            continue
        value = _static_eval(node.value, constants, {})
        if value is not _UNRESOLVED:
            constants[target.id] = value
    return constants


def _bind_target(target: ast.expr, value: object, env: dict[str, object]) -> None:
    if isinstance(target, ast.Name):
        env[target.id] = value
        return
    if isinstance(target, ast.Tuple | ast.List):
        if isinstance(value, (list, tuple)) and len(value) == len(target.elts):
            for element, element_value in zip(target.elts, value, strict=True):
                _bind_target(element, element_value, env)
            return
        for element in target.elts:
            _bind_target(element, _UNRESOLVED, env)


def _target_names(target: ast.expr) -> list[str]:
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, ast.Tuple | ast.List):
        names: list[str] = []
        for element in target.elts:
            names.extend(_target_names(element))
        return names
    return []


def _iter_calls(body, constants, env):
    """문장 목록을 훑어 (Call, 해석 환경) 쌍을 냅니다. for 루프 변수를 바인딩합니다."""
    for node in body:
        if isinstance(node, ast.For):
            iterable = _static_eval(node.iter, constants, env)
            if isinstance(iterable, (list, tuple)):
                for element in iterable:
                    child_env = dict(env)
                    _bind_target(node.target, element, child_env)
                    yield from _iter_calls(node.body, constants, child_env)
            else:
                child_env = dict(env)
                for name in _target_names(node.target):
                    child_env[name] = _UNRESOLVED
                yield from _iter_calls(node.body, constants, child_env)
            yield from _iter_calls(node.orelse, constants, env)
        elif isinstance(node, ast.If | ast.With):
            yield from _iter_calls(node.body, constants, env)
            if isinstance(node, ast.If):
                yield from _iter_calls(node.orelse, constants, env)
        elif isinstance(node, ast.Try):
            yield from _iter_calls(node.body, constants, env)
            for handler in node.handlers:
                yield from _iter_calls(handler.body, constants, env)
            yield from _iter_calls(node.orelse, constants, env)
            yield from _iter_calls(node.finalbody, constants, env)
        elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            yield node.value, env


def _indexes_in_sql(text: str) -> list[tuple[str | None, str]]:
    """SQL 원문에서 (테이블, 인덱스) 쌍을 뽑습니다."""
    alter_match = _ALTER_TABLE_RE.search(text)
    alter_table = alter_match.group(1) if alter_match else None
    found: list[tuple[str | None, str]] = []
    for match in _CREATE_INDEX_RE.finditer(text):
        on_match = _ON_TABLE_RE.search(text, match.end())
        found.append((on_match.group(1) if on_match else None, match.group(1)))
    for match in _ADD_INDEX_RE.finditer(text):
        found.append((alter_table, match.group(1)))
    return found


def _classify_call(call: ast.Call, env, constants, location, creates, drops) -> None:
    func = call.func
    if not (
        isinstance(func, ast.Attribute)
        and isinstance(func.value, ast.Name)
        and func.value.id == "op"
    ):
        return

    args = call.args
    if func.attr == "create_table":
        name = _resolve_str(args[0] if args else None, constants, env)
        if isinstance(name, str):
            creates.created_tables.setdefault(name, location)
        else:
            creates.unresolved[location] = "op.create_table 이름을 정적으로 정할 수 없습니다"
    elif func.attr == "create_index":
        name = _resolve_str(args[0] if args else None, constants, env)
        table = _resolve_str(args[1] if len(args) > 1 else None, constants, env)
        if isinstance(name, str):
            key = (table if isinstance(table, str) else "", name)
            creates.created_indexes.setdefault(key, location)
        else:
            creates.unresolved[location] = "op.create_index 이름을 정적으로 정할 수 없습니다"
    elif func.attr == "execute":
        for arg in args:
            text = _resolve_str(arg, constants, env)
            if not isinstance(text, str):
                creates.unresolved[location] = "op.execute SQL 문자열을 정적으로 정할 수 없습니다"
                continue
            for table, name in _indexes_in_sql(text):
                creates.created_indexes.setdefault((table or "", name), location)
    elif func.attr in {"drop_table", "drop_index"}:
        name = _resolve_str(args[0] if args else None, constants, env)
        if isinstance(name, str):
            drops.add(name)


def _display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _parse_migration_file(path: Path) -> tuple[MigrationCreates, set[str]]:
    """upgrade() 본문만 봅니다. downgrade() 의 drop 은 무시합니다."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    constants = _module_constants(tree)
    creates = MigrationCreates()
    drops: set[str] = set()
    location_root = _display_path(path)
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef) or node.name != "upgrade":
            continue
        for call, env in _iter_calls(node.body, constants, {}):
            _classify_call(
                call,
                env,
                constants,
                f"{location_root}:{call.lineno}",
                creates,
                drops,
            )
    return creates, drops


def collect_migration_creates(directory: Path = MIGRATIONS_DIR) -> MigrationCreates:
    """모든 마이그레이션을 파싱하고 다른 파일의 upgrade() 가 drop 한 이름을 제외합니다."""
    per_file: list[tuple[MigrationCreates, set[str]]] = [
        _parse_migration_file(path) for path in sorted(directory.glob("*.py"))
    ]
    result = MigrationCreates()
    for index, (creates, _drops) in enumerate(per_file):
        other_drops: set[str] = set()
        for other_index, (_other_creates, other_file_drops) in enumerate(per_file):
            if other_index != index:
                other_drops |= other_file_drops
        for name, location in creates.created_tables.items():
            if name not in other_drops:
                result.created_tables.setdefault(name, location)
        for key, location in creates.created_indexes.items():
            if key[1] not in other_drops:
                result.created_indexes.setdefault(key, location)
        result.unresolved.update(creates.unresolved)
    return result


def _baseline_tables(baseline: dict) -> dict:
    tables = baseline.get("tables")
    return tables if isinstance(tables, dict) else {}


def orm_table_problems(baseline: dict, orm_tables: set[str]) -> list[str]:
    problems: list[str] = []
    baseline_orm = baseline.get("orm_tables")
    if not isinstance(baseline_orm, list):
        problems.append("기준선에 orm_tables 목록이 없습니다")
        baseline_orm = []
    baseline_orm_set = set(baseline_orm)
    missing = sorted(orm_tables - baseline_orm_set)
    extra = sorted(baseline_orm_set - orm_tables)
    if missing:
        problems.append(f"기준선 orm_tables 에 없는 ORM 테이블: {', '.join(missing)}")
    if extra:
        problems.append(f"ORM 에 없는 기준선 orm_tables 항목: {', '.join(extra)}")
    tables = _baseline_tables(baseline)
    absent = sorted(table for table in orm_tables if table not in tables)
    if absent:
        problems.append(f"기준선 tables 에 없는 ORM 테이블: {', '.join(absent)}")
    return problems


def orm_column_problems(baseline: dict, orm_columns: dict[str, set[str]]) -> list[str]:
    problems: list[str] = []
    tables = _baseline_tables(baseline)
    for table in sorted(orm_columns):
        entry = tables.get(table)
        if not isinstance(entry, dict):
            continue
        baseline_columns = {
            column.get("name") for column in entry.get("columns", []) if isinstance(column, dict)
        }
        orm_table_columns = set(orm_columns[table])
        added = sorted(orm_table_columns - baseline_columns)
        removed = sorted(baseline_columns - orm_table_columns)
        if added:
            problems.append(f"{table}: 기준선에 없는 ORM 컬럼 {', '.join(added)}")
        if removed:
            problems.append(f"{table}: ORM 에 없는 기준선 컬럼 {', '.join(removed)}")
    return problems


def migration_problems(baseline: dict, creates: MigrationCreates) -> list[str]:
    problems: list[str] = []
    tables = _baseline_tables(baseline)
    for name, location in sorted(creates.created_tables.items()):
        if name not in tables:
            problems.append(
                f"마이그레이션 upgrade() 가 만드는데 기준선 tables 에 없는 테이블: {name} ({location})"
            )
    for (table, index), location in sorted(creates.created_indexes.items()):
        if not table:
            if index in tables:
                continue
            if any(
                index in _index_names(entry) for entry in tables.values() if isinstance(entry, dict)
            ):
                continue
            problems.append(
                f"마이그레이션 upgrade() 가 만드는데 기준선에서 찾을 수 없는 인덱스: "
                f"{index} ({location})"
            )
            continue
        entry = tables.get(table)
        if not isinstance(entry, dict):
            problems.append(
                f"마이그레이션 upgrade() 인덱스 {index} 의 테이블 {table} 이 "
                f"기준선 tables 에 없습니다 ({location})"
            )
        elif index not in _index_names(entry):
            problems.append(
                f"마이그레이션 upgrade() 가 만드는데 {table} 의 기준선 indexes 에 없는 인덱스: "
                f"{index} ({location})"
            )
    for location, description in sorted(creates.unresolved.items()):
        problems.append(
            f"마이그레이션 이름을 정적으로 정할 수 없어 건너뛸 수 없습니다: {location} - {description}"
        )
    return problems


def _index_names(table_entry: dict) -> set[str]:
    return {
        index.get("name") for index in table_entry.get("indexes", []) if isinstance(index, dict)
    }


def find_baseline_drift(
    baseline: dict,
    orm_tables: set[str],
    orm_columns: dict[str, set[str]],
    creates: MigrationCreates,
) -> list[str]:
    """기준선 dict 를 받아 ORM·마이그레이션 두 출처와의 드리프트를 모두 모읍니다."""
    return (
        orm_table_problems(baseline, orm_tables)
        + orm_column_problems(baseline, orm_columns)
        + migration_problems(baseline, creates)
    )


def _load_baseline() -> dict:
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))


def _orm_snapshot() -> tuple[set[str], dict[str, set[str]]]:
    import src.app.models  # noqa: F401  (모델 등록을 위해 필요)
    from src.app.core.db import Base

    tables = set(Base.metadata.tables)
    columns = {
        name: {column.name for column in table.columns}
        for name, table in Base.metadata.tables.items()
    }
    return tables, columns


def _format(problems: list[str]) -> str:
    return BASELINE_REMEDY + "\n" + "\n".join(f"- {problem}" for problem in problems)


def test_gate_finds_no_drift_on_current_main():
    baseline = _load_baseline()
    orm_tables, orm_columns = _orm_snapshot()
    problems = find_baseline_drift(baseline, orm_tables, orm_columns, collect_migration_creates())
    assert problems == [], _format(problems)


def test_gate_orm_tables_are_in_baseline():
    baseline = _load_baseline()
    orm_tables, _orm_columns = _orm_snapshot()
    problems = orm_table_problems(baseline, orm_tables)
    assert problems == [], _format(problems)


def test_gate_orm_columns_are_in_baseline():
    baseline = _load_baseline()
    _orm_tables, orm_columns = _orm_snapshot()
    problems = orm_column_problems(baseline, orm_columns)
    assert problems == [], _format(problems)


def test_gate_migrations_are_in_baseline():
    baseline = _load_baseline()
    problems = migration_problems(baseline, collect_migration_creates())
    assert problems == [], _format(problems)


def test_gate_detects_baseline_missing_new_table():
    """음성 대조: 기준선에서 테이블 하나를 지우면 게이트가 실패를 보고해야 합니다."""
    baseline = copy.deepcopy(_load_baseline())
    assert "bid_announcement_license_limits" in baseline["tables"]
    del baseline["tables"]["bid_announcement_license_limits"]

    orm_tables, orm_columns = _orm_snapshot()
    problems = find_baseline_drift(baseline, orm_tables, orm_columns, collect_migration_creates())

    assert problems, "테이블 하나를 뺀 기준선 사본에서 게이트가 통과하면 안 됩니다"
    assert any("bid_announcement_license_limits" in problem for problem in problems)


def test_gate_detects_baseline_missing_index():
    """음성 대조: 원문 SQL 로 만든 인덱스 하나를 지우면 게이트가 실패를 보고해야 합니다."""
    baseline = copy.deepcopy(_load_baseline())
    bid_results = baseline["tables"]["bid_results"]
    names = {index["name"] for index in bid_results["indexes"]}
    assert "ix_bid_results_inst_cat_stats" in names
    bid_results["indexes"] = [
        index
        for index in bid_results["indexes"]
        if index["name"] != "ix_bid_results_inst_cat_stats"
    ]

    orm_tables, orm_columns = _orm_snapshot()
    problems = find_baseline_drift(baseline, orm_tables, orm_columns, collect_migration_creates())

    assert problems, "인덱스 하나를 뺀 기준선 사본에서 게이트가 통과하면 안 됩니다"
    assert any("ix_bid_results_inst_cat_stats" in problem for problem in problems)


def test_gate_collects_raw_sql_indexes_from_migrations():
    """op.execute 원문 SQL 의 ADD INDEX 도 수집되고, 원문 파싱도 UNIQUE 를 다룹니다."""
    creates = collect_migration_creates()
    assert ("bid_results", "ix_bid_results_inst_cat_stats") in creates.created_indexes
    assert ("bid_announcements", "ix_bid_ann_inst_cat_ntce") in creates.created_indexes

    assert _indexes_in_sql(
        "ALTER TABLE bid_results ADD INDEX ix_result_stats (a, b), ALGORITHM=INPLACE"
    ) == [("bid_results", "ix_result_stats")]
    assert _indexes_in_sql("CREATE UNIQUE INDEX uq_bid_slot ON bid_results (a, b)") == [
        ("bid_results", "uq_bid_slot")
    ]


def test_gate_rejects_unresolvable_migration_name(tmp_path):
    """정적으로 정할 수 없는 create 이름은 조용히 건너뛰지 않고 실패로 보고합니다."""
    migration = tmp_path / "abcd1234_add_dynamic_index.py"
    migration.write_text(
        "from alembic import op\n"
        "\n"
        "\n"
        "def upgrade():\n"
        "    op.create_index(dynamic_name, 'bid_results', ['category'], unique=False)\n",
        encoding="utf-8",
    )

    creates = collect_migration_creates(tmp_path)
    assert creates.unresolved, "정적으로 정할 수 없는 이름은 건너뛰지 않고 모아야 합니다"
    problems = migration_problems(_load_baseline(), creates)
    assert problems, "정적으로 정할 수 없는 이름이 있으면 게이트가 실패해야 합니다"


def test_gate_resolves_module_constants_and_loop_bindings(tmp_path):
    """모듈 상수, f-string 치환, for 루프 변수 이름을 정적으로 해석합니다."""
    migration = tmp_path / "abcd5678_add_constant_indexes.py"
    migration.write_text(
        "from alembic import op\n"
        "\n"
        "TABLE_NAME = 'bid_results'\n"
        "INDEX_NAME = 'ix_bid_results_cat_dt_stats'\n"
        "INDEXES = (('ix_bid_ann_collected_dt', ['collected_at']),)\n"
        "\n"
        "\n"
        "def upgrade():\n"
        "    op.execute(\n"
        "        f'ALTER TABLE {TABLE_NAME} ADD INDEX {INDEX_NAME} (category, rl_openg_dt), '\n"
        "        'ALGORITHM=INPLACE, LOCK=NONE'\n"
        "    )\n"
        "    for name, columns in INDEXES:\n"
        "        op.create_index(name, 'bid_announcements', columns, unique=False)\n",
        encoding="utf-8",
    )

    creates = collect_migration_creates(tmp_path)

    assert not creates.unresolved
    assert ("bid_results", "ix_bid_results_cat_dt_stats") in creates.created_indexes
    assert ("bid_announcements", "ix_bid_ann_collected_dt") in creates.created_indexes

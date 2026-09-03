"""tests/test_session_thread_ownership.py

SQLAlchemy Session 스레드 소유권 AST 정적 검사 테스트.

asyncio.to_thread 호출 시 Session 객체(db, session, db_session 등)가
스레드 경계를 넘어 전달되는 패턴을 정적 분석으로 차단합니다.
"""

from __future__ import annotations

import ast
from pathlib import Path

TARGET_FILES = (
    "src/app/api/ui.py",
    "src/app/api/v1/chatbot.py",
    "src/app/services/collector_service.py",
    "src/tasks/automation_tasks.py",
    "src/tasks/scheduled_tasks.py",
    "src/tasks/retrain_task.py",
)

FORBIDDEN_SESSION_NAMES = frozenset(
    {
        "db",
        "session",
        "db_session",
        "session_local",
        "scoped_session",
        "caller_db",
    }
)


def _is_to_thread_call(node: ast.Call) -> bool:
    """ast.Call 노드가 asyncio.to_thread 호출인지 확인합니다."""
    if (
        isinstance(node.func, ast.Attribute)
        and node.func.attr == "to_thread"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "asyncio"
    ):
        return True
    return isinstance(node.func, ast.Name) and node.func.id == "to_thread"


def _check_name_violation(name_id: str) -> bool:
    """식별자 이름이 금지된 세션 이름 패턴에 해당하는지 검사합니다."""
    lower_name = name_id.lower()
    return (
        lower_name in FORBIDDEN_SESSION_NAMES
        or lower_name.startswith("db_")
        or lower_name.endswith("_session")
    )


def find_session_thread_violations(source_code: str, filename: str = "<string>") -> list[str]:
    """소스 코드 AST 를 탐색하여 asyncio.to_thread 에 Session 인자가 전달되는 위반을 검출합니다."""
    tree = ast.parse(source_code, filename=filename)
    violations: list[str] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not _is_to_thread_call(node):
            continue

        # to_thread 의 첫 번째 인자는 실행 대상 함수이며, 2번째 인자부터 전달되는 매개변수입니다.
        func_args = node.args[1:]
        for arg in func_args:
            if isinstance(arg, ast.Name) and _check_name_violation(arg.id):
                violations.append(
                    f"{filename}:{arg.lineno} - to_thread 위치 인자로 세션 추정 변수 '{arg.id}' 전달됨"
                )

        for kw in node.keywords:
            if isinstance(kw.value, ast.Name) and _check_name_violation(kw.value.id):
                violations.append(
                    f"{filename}:{kw.lineno} - to_thread 키워드 인자 '{kw.arg}={kw.value.id}' 로 세션 추정 변수 전달됨"
                )

    return violations


def test_target_files_have_no_session_passed_to_thread():
    """모든 대상 파일에서 asyncio.to_thread 에 Session 객체를 넘기는 패턴이 없음을 검증."""
    repo_root = Path(__file__).resolve().parent.parent
    all_violations: list[str] = []

    for rel_path in TARGET_FILES:
        target_path = repo_root / rel_path
        assert target_path.exists(), f"검사 대상 파일이 존재하지 않습니다: {target_path}"
        source = target_path.read_text(encoding="utf-8")
        file_violations = find_session_thread_violations(source, filename=rel_path)
        all_violations.extend(file_violations)

    assert not all_violations, (
        f"SQLAlchemy Session 스레드 경계 위반 {len(all_violations)}건 발견:\n"
        + "\n".join(f"  - {v}" for v in all_violations)
    )


def test_checker_catches_intentional_positional_violation():
    """의도적 위치 인자 위반 코드 조각을 검사기가 올바르게 검출하는지 검증 (False Negative 방지)."""
    bad_code = """
import asyncio

async def bad_handler(db):
    result = await asyncio.to_thread(sync_worker, db, "some_arg")
    return result
"""
    violations = find_session_thread_violations(bad_code, filename="bad_pos.py")
    assert len(violations) == 1
    assert "to_thread 위치 인자로 세션 추정 변수 'db' 전달됨" in violations[0]


def test_checker_catches_intentional_keyword_violation():
    """의도적 키워드 인자 위반 코드 조각을 검사기가 올바르게 검출하는지 검증."""
    bad_code = """
import asyncio

async def bad_handler(session):
    result = await asyncio.to_thread(sync_worker, payload="test", db_session=session)
    return result
"""
    violations = find_session_thread_violations(bad_code, filename="bad_kw.py")
    assert len(violations) == 1
    assert "db_session=session" in violations[0]


def test_checker_allows_valid_to_thread_calls():
    """순수 데이터(식별자, 스칼라, dict)만 전달하는 정상 코드는 위반 없이 통과함을 검증."""
    good_code = """
import asyncio

async def good_handler(user_id: int, payload: dict):
    result = await asyncio.to_thread(sync_worker, user_id, payload, timeout=10)
    return result
"""
    violations = find_session_thread_violations(good_code, filename="good.py")
    assert violations == []

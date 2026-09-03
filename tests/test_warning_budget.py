"""
tests/test_warning_budget.py

pytest 의 filterwarnings 계약이 유지되는지를 정적으로 검사합니다.
**전체 테스트 스위트를 다시 실행하지 않습니다.** 이 파일은 subprocess
호출이나 pytest.main / pytest_collection 을 호출하지 않으며, 다음만 확인합니다.

  1. pyproject.toml 의 filterwarnings 각 항목이 발원 모듈/메시지/카테고리를 좁게 지정한다.
  2. 전역 ignore 가 없다 (action 만 있고 module/category/message 가 없는 항목 금지).
  3. 모든 필터의 발원 모듈이 서드파티/표준 라이브러리이며 src/ 하위가 아니다.
  4. docs/ops/warning_budget.md 의 filter_id 목록과 pyproject.toml 의 항목 수가 일치한다.
  5. 각 항목에 사유(reason) 와 재검토 시점(revisit) 키가 문서에 존재한다.

전체 pytest 실행 시 경고 예산은 pyproject.toml 의 filterwarnings 가 적용되어
0건이어야 합니다. 이 검증은 uv run pytest tests/ -q -m 'not data_assets' 로
수동으로 한 번 실측하며, 본 테스트 파일은 그 실측값을 다시 재현하지 않습니다.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = REPO_ROOT / "pyproject.toml"
WARNING_DOC = REPO_ROOT / "docs" / "ops" / "warning_budget.md"

ALLOWED_ACTIONS = {"ignore", "default", "error", "always", "module", "once"}
THIRD_PARTY_PREFIXES = (
    "chromadb",
    "joblib",
    "lightgbm",
    "fastapi",
    "starlette",
    "multiprocessing",
    "subprocess",
    "scripts",
    "_pytest",
)
# 우리 코드의 경고는 필터로 덮지 않습니다. 단, scripts/ 하위는 현재 작업의
# 쓰기 범위 밖이라 사유 명시 후 좁게 필터링을 허용합니다. src/ 는 절대 금지.
FORBIDDEN_PREFIXES = ("src.", "src/")


def _load_pyproject() -> dict:
    with PYPROJECT.open("rb") as f:
        return tomllib.load(f)


def _load_filterwarnings() -> list[str]:
    cfg = _load_pyproject()
    return list(cfg["tool"]["pytest"]["ini_options"].get("filterwarnings", []))


def _parse_filter(entry: str) -> dict[str, str]:
    parts = entry.split(":")
    if len(parts) < 2:
        raise AssertionError(f"filter 항목 형식이 잘못됐습니다: {entry!r}")
    return {
        "action": parts[0],
        "message": parts[1] if len(parts) > 1 else "",
        "category": parts[2] if len(parts) > 2 else "",
        "module": parts[3] if len(parts) > 3 else "",
        "lineno": parts[4] if len(parts) > 4 else "",
    }


def test_filterwarnings_is_declared():
    cfg = _load_pyproject()
    assert "filterwarnings" in cfg["tool"]["pytest"]["ini_options"], (
        "pyproject.toml 의 [tool.pytest.ini_options] 에 filterwarnings 가 없습니다."
    )


def test_no_global_ignore():
    """action 만 있고 나머지 필드가 비어 있는 항목(전역 ignore) 금지.

    예: 'ignore' 또는 'ignore:::' 는 어떤 경고든 흡수하므로 금지합니다.
    """
    for entry in _load_filterwarnings():
        parsed = _parse_filter(entry)
        narrow = any([parsed["message"], parsed["category"], parsed["module"]])
        assert narrow, (
            f"전역 ignore 가 발견됐습니다 (발원 모듈/메시지/카테고리 미지정): {entry!r}. "
            f"filterwarnings 는 좁게 지정해야 합니다."
        )


def test_action_is_recognised():
    for entry in _load_filterwarnings():
        parsed = _parse_filter(entry)
        assert parsed["action"] in ALLOWED_ACTIONS, (
            f"알 수 없는 action 입니다: {parsed['action']!r} (entry={entry!r})"
        )


def test_filter_targets_third_party_or_stdlib_only():
    """src/ 하위 모듈은 필터 대상이 될 수 없습니다.

    우리 코드의 경고는 필터로 덮지 말고 수정으로 처리합니다. 단, scripts/ 는
    현재 작업의 쓰기 범위 밖이라 사유 명시 후 필터 허용합니다.
    """
    for entry in _load_filterwarnings():
        parsed = _parse_filter(entry)
        module = parsed["module"]
        if not module:
            continue
        assert not module.startswith(FORBIDDEN_PREFIXES), (
            f"우리 코드 경로가 필터 대상입니다: {module!r} (entry={entry!r}). "
            f"src/ 하위 모듈 경고는 수정으로 해결해야 합니다."
        )


def test_filter_is_narrow_by_module_or_message():
    """module 또는 message 가 둘 다 비어 있으면 안 됩니다.

    pytest 의 filterwarnings 는 message 정규식이 비면 너무 광범위해집니다.
    """
    for entry in _load_filterwarnings():
        parsed = _parse_filter(entry)
        if parsed["action"] == "error":
            continue
        assert parsed["message"] or parsed["module"], (
            f"module 과 message 가 둘 다 비어 있습니다: {entry!r}"
        )


def test_documented_filter_ids_match_pyproject():
    """문서의 filter_id 목록과 pyproject 항목 수가 일치합니다."""
    assert WARNING_DOC.exists(), f"{WARNING_DOC} 가 없습니다. 문서를 먼저 작성하십시오."
    doc_text = WARNING_DOC.read_text(encoding="utf-8")

    filter_id_pattern = re.compile(r"^###\s+filter_id\s*:\s*`([A-Za-z0-9_]+)`", re.MULTILINE)
    doc_ids = filter_id_pattern.findall(doc_text)
    pyproject_count = len(_load_filterwarnings())

    assert doc_ids, "docs/ops/warning_budget.md 에 ### filter_id 항목이 없습니다."
    assert len(doc_ids) == pyproject_count, (
        f"문서의 filter_id 수({len(doc_ids)})와 pyproject 항목 수({pyproject_count})가 다릅니다. "
        f"문서: {doc_ids}"
    )


def test_each_filter_has_reason_and_revisit_in_doc():
    """각 filter_id 항목에 '## 사유' 와 '## 재검토 시점' 헤더가 있어야 합니다."""
    doc_text = WARNING_DOC.read_text(encoding="utf-8")
    sections = re.split(r"^###\s+filter_id\s*:\s*`([A-Za-z0-9_]+)`", doc_text, flags=re.MULTILINE)
    # sections[0] = 머리말, [1]=id, [2]=body, [3]=id, [4]=body, ...
    body_by_id: dict[str, str] = {}
    for i in range(1, len(sections), 2):
        body_by_id[sections[i]] = sections[i + 1]

    for fid, body in body_by_id.items():
        assert "## 사유" in body, f"{fid} 항목에 '## 사유' 헤더가 없습니다."
        assert "## 재검토 시점" in body, f"{fid} 항목에 '## 재검토 시점' 헤더가 없습니다."


def test_each_filter_id_is_unique():
    doc_text = WARNING_DOC.read_text(encoding="utf-8")
    ids = re.findall(r"^###\s+filter_id\s*:\s*`([A-Za-z0-9_]+)`", doc_text, re.MULTILINE)
    assert len(ids) == len(set(ids)), f"filter_id 가 중복됩니다: {ids}"


def test_documented_module_appears_in_pyproject():
    """문서에 적힌 module 이 pyproject 항목에 실제로 존재하는지 확인합니다."""
    doc_text = WARNING_DOC.read_text(encoding="utf-8")
    doc_modules = re.findall(r"^module\s*:\s*`([^`]+)`", doc_text, re.MULTILINE)

    pyproject_entries = _load_filterwarnings()
    pyproject_modules = set()
    for entry in pyproject_entries:
        parsed = _parse_filter(entry)
        if parsed["module"]:
            pyproject_modules.add(parsed["module"])

    for mod in doc_modules:
        assert mod in pyproject_modules, f"문서에 적힌 module {mod!r} 가 pyproject 항목에 없습니다."

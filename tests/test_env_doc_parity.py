"""docs/ops/environment_variables.md 와 Settings 필드·기본값의 정합성을 검증합니다.

문서가 스스로 "모든 환경변수의 단일 명세" 라고 선언하므로, Settings 에 필드가
추가되면 같은 커밋에서 문서 표도 함께 늘어나야 합니다. 컨테이너 인프라 전용
키는 애플리케이션 설정 모델에 없으므로 기존 예외 목록을 그대로 재사용합니다.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from src.app.core.config import Settings
from tests.test_logging_config import INFRA_ONLY_KEYS

PROJECT_ROOT = Path(__file__).parents[1]
DOC_PATH = PROJECT_ROOT / "docs" / "ops" / "environment_variables.md"

TABLE_ROW_PATTERN = re.compile(r"^\|\s*`([A-Z0-9_]+)`\s*\|([^\n]*)$", re.MULTILINE)


def _documented_rows() -> dict[str, list[str]]:
    """문서 표에서 키별 셀 목록을 뽑습니다. 첫 셀은 필수, 둘째 셀은 기본값입니다."""
    text = DOC_PATH.read_text(encoding="utf-8")
    rows: dict[str, list[str]] = {}
    for match in TABLE_ROW_PATTERN.finditer(text):
        rows[match.group(1)] = [cell.strip() for cell in match.group(2).split("|")]
    return rows


def test_env_document_exists() -> None:
    assert DOC_PATH.exists(), "docs/ops/environment_variables.md 가 있어야 합니다."


def test_settings_fields_are_documented() -> None:
    missing = set(Settings.model_fields) - set(_documented_rows()) - INFRA_ONLY_KEYS
    assert not missing, (
        "Settings 에 정의되었으나 docs/ops/environment_variables.md 표에 없는 키가 있습니다: "
        f"{sorted(missing)}"
    )


@pytest.mark.parametrize(
    "key",
    [
        "CORS_DEV_ALLOW_ALL",
        "AUTOMATION_DATA_REFRESH_SCHEDULE_ENABLED",
        "AUTOMATION_NIGHTLY_SCHEDULE_ENABLED",
        "OLLAMA_MODEL",
    ],
)
def test_documented_default_matches_settings(key: str) -> None:
    """문서의 기본값 열이 코드 기본값과 어긋나면 실패합니다."""
    rows = _documented_rows()
    assert key in rows, f"{key} 가 문서 표에 없습니다."
    cells = rows[key]
    assert len(cells) >= 2, f"{key} 행에서 기본값 열을 찾지 못했습니다: {cells}"
    documented_default = cells[1].strip("`").strip()

    default = Settings.model_fields[key].default
    expected = ("true" if default else "false") if isinstance(default, bool) else str(default)

    assert documented_default == expected, (
        f"{key} 의 문서 기본값 '{documented_default}' 이 코드 기본값 '{expected}' 과 다릅니다."
    )

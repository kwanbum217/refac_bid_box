"""tests/test_constraints_sync.py

constraints.txt 가 uv.lock 기반 uv export 결과와 어긋나면 실패하는 동기 검증 테스트.
- uv 가 없으면 skip 한다.
- 주석·헤더 줄은 제외하고 패키지==버전 줄 집합만 대조한다.
- 어긋나면 재생성 명령과 차이 목록을 메시지로 남긴다.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
CONSTRAINTS_PATH = REPO_ROOT / "constraints.txt"

EXPORT_ARGS = [
    "export",
    "--frozen",
    "--format",
    "requirements.txt",
    "--no-emit-project",
    "--no-dev",
    "--no-hashes",
]
REGENERATE_COMMAND = (
    "uv export --frozen --format requirements.txt --no-emit-project --no-dev --no-hashes "
    "-o constraints.txt"
)
ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*m")
PINNED_LINE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*==\S+")


def _pinned_requirements(text: str) -> set[str]:
    pinned: set[str] = set()
    for raw_line in ANSI_ESCAPE.sub("", text).splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if PINNED_LINE.match(line):
            pinned.add(line)
    return pinned


def test_constraints_matches_uv_lock():
    uv_executable = shutil.which("uv")
    if uv_executable is None:
        pytest.skip("uv 가 없어 constraints.txt 동기 검증을 건너뜁니다.")

    assert CONSTRAINTS_PATH.exists(), f"{CONSTRAINTS_PATH} 가 존재해야 합니다."

    result = subprocess.run(  # noqa: S603
        [uv_executable, *EXPORT_ARGS],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0, (
        f"uv export 가 실패했습니다(returncode={result.returncode}). uv.lock 과 "
        f"pyproject.toml 이 어긋났을 수 있습니다.\n{result.stderr}"
    )

    expected = _pinned_requirements(result.stdout)
    actual = _pinned_requirements(CONSTRAINTS_PATH.read_text(encoding="utf-8"))

    assert expected, "uv export 결과에서 패키지==버전 줄을 찾지 못했습니다."

    missing = sorted(expected - actual)
    stale = sorted(actual - expected)

    assert not missing, (
        "constraints.txt 에 uv.lock 기준 누락된 패키지가 있습니다. 다음 명령으로 "
        f"재생성하십시오:\n  {REGENERATE_COMMAND}\n누락(uv.lock 에만 있음): {missing}"
    )
    assert not stale, (
        "constraints.txt 에 uv.lock 에 없는 패키지가 있습니다. 다음 명령으로 "
        f"재생성하십시오:\n  {REGENERATE_COMMAND}\n잔존(constraints.txt 에만 있음): {stale}"
    )

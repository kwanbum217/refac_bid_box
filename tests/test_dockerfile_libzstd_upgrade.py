"""Dockerfile 런타임 스테이지의 libzstd1 보안 업그레이드 회귀 시험."""

import re
from pathlib import Path

DOCKERFILE = Path(__file__).resolve().parents[1] / "Dockerfile"


def _runtime_stage(text: str) -> str:
    lines = text.splitlines(keepends=True)
    start = None
    for index, line in enumerate(lines):
        if re.match(r"FROM\s.*\sAS\s+runtime\s*$", line.strip()) and start is None:
            start = index + 1
        elif start is not None and line.startswith("FROM "):
            return "".join(lines[start:index])
    assert start is not None, "Dockerfile 에 AS runtime 스테이지가 없습니다"
    return "".join(lines[start:])


def _only_upgrade_packages(stage: str) -> set[str]:
    match = re.search(r"--only-upgrade(.*?)(?:&&|\Z)", stage, re.S)
    assert match is not None, "런타임 스테이지에 --only-upgrade 설치가 없습니다"
    tokens = re.split(r"[\s\\]+", match.group(1))
    return {token for token in tokens if token and not token.startswith("-")}


def test_runtime_stage_upgrades_libzstd1() -> None:
    packages = _only_upgrade_packages(_runtime_stage(DOCKERFILE.read_text(encoding="utf-8")))
    assert "libzstd1" in packages, (
        f"런타임 스테이지 --only-upgrade 목록에 libzstd1 이 없습니다. 현재 목록: {sorted(packages)}"
    )

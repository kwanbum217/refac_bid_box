"""tests/test_sync_skill_mirrors.py

스킬 정본 복제 도구(scripts/sync_skill_mirrors.py)의 동작을 검증합니다.

검증 항목:
1. 정본과 미러가 같으면 --check 가 종료 코드 0 을 돌려준다
2. 내용 상이, 누락, 잔여 파일을 각각 어긋남으로 잡고 --check 가 1 을 돌려준다
3. 동기화가 세 경우를 모두 해소하고 잔여 파일과 빈 디렉터리를 제거한다
4. --check 는 파일을 고치지 않는다
5. 저장소의 실제 세 트리가 현재 일치한다
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import sync_skill_mirrors as sync


def build_repo(root: Path, mirror_content: dict[str, str] | None = None) -> None:
    """정본 하나와 미러 두 개를 가진 최소 저장소를 만듭니다."""
    canonical = root / sync.CANONICAL
    (canonical / "demo-skill").mkdir(parents=True)
    (canonical / "demo-skill" / "SKILL.md").write_text("정본 내용\n", encoding="utf-8")

    for mirror_rel in sync.MIRRORS:
        mirror = root / mirror_rel
        (mirror / "demo-skill").mkdir(parents=True)
        body = (
            "정본 내용\n"
            if mirror_content is None
            else mirror_content.get(str(mirror_rel), "정본 내용\n")
        )
        (mirror / "demo-skill" / "SKILL.md").write_text(body, encoding="utf-8")


def test_check_passes_when_mirrors_match(tmp_path: Path):
    """정본과 미러가 같으면 어긋남이 없고 종료 코드는 0 입니다."""
    build_repo(tmp_path)
    exit_code, report = sync.run(tmp_path, check_only=True)
    assert exit_code == 0
    assert all(entry["in_sync"] for entry in report["mirrors"].values())


def test_check_detects_changed_file(tmp_path: Path):
    """미러 내용이 다르면 changed 로 잡고 종료 코드 1 을 돌려줍니다."""
    build_repo(tmp_path, mirror_content={".claude/skills": "어긋난 내용\n"})
    exit_code, report = sync.run(tmp_path, check_only=True)
    assert exit_code == 1
    assert report["mirrors"][".claude/skills"]["changed"] == ["demo-skill/SKILL.md"]
    assert report["mirrors"][".opencode/skills"]["in_sync"] is True


def test_check_detects_missing_and_extra(tmp_path: Path):
    """정본에만 있는 파일은 missing, 미러에만 있는 파일은 extra 로 잡습니다."""
    build_repo(tmp_path)
    (tmp_path / sync.CANONICAL / "demo-skill" / "REFERENCE.md").write_text(
        "참고\n", encoding="utf-8"
    )
    (tmp_path / ".claude/skills" / "stray.md").write_text("잔여\n", encoding="utf-8")

    exit_code, report = sync.run(tmp_path, check_only=True)
    assert exit_code == 1
    claude = report["mirrors"][".claude/skills"]
    assert claude["missing"] == ["demo-skill/REFERENCE.md"]
    assert claude["extra"] == ["stray.md"]


def test_check_does_not_modify_files(tmp_path: Path):
    """--check 는 보고만 하고 미러를 고치지 않습니다."""
    build_repo(tmp_path, mirror_content={".claude/skills": "어긋난 내용\n"})
    target = tmp_path / ".claude/skills" / "demo-skill" / "SKILL.md"
    sync.run(tmp_path, check_only=True)
    assert target.read_text(encoding="utf-8") == "어긋난 내용\n"


def test_sync_resolves_all_drift(tmp_path: Path):
    """동기화가 내용 상이, 누락, 잔여를 모두 해소합니다."""
    build_repo(tmp_path, mirror_content={".claude/skills": "어긋난 내용\n"})
    (tmp_path / sync.CANONICAL / "demo-skill" / "REFERENCE.md").write_text(
        "참고\n", encoding="utf-8"
    )
    stray_dir = tmp_path / ".claude/skills" / "obsolete"
    stray_dir.mkdir(parents=True)
    (stray_dir / "old.md").write_text("옛 파일\n", encoding="utf-8")

    exit_code, _ = sync.run(tmp_path, check_only=False)
    assert exit_code == 0

    mirror = tmp_path / ".claude/skills"
    assert (mirror / "demo-skill" / "SKILL.md").read_text(encoding="utf-8") == "정본 내용\n"
    assert (mirror / "demo-skill" / "REFERENCE.md").read_text(encoding="utf-8") == "참고\n"
    assert not (mirror / "obsolete" / "old.md").exists()
    assert not stray_dir.exists(), "잔여 파일을 지운 뒤 빈 디렉터리도 제거해야 합니다."

    recheck_code, _ = sync.run(tmp_path, check_only=True)
    assert recheck_code == 0


def test_missing_canonical_is_tool_error(tmp_path: Path):
    """정본 디렉터리가 없으면 종료 코드 2 로 도구 오류를 알립니다."""
    exit_code, report = sync.run(tmp_path, check_only=True)
    assert exit_code == 2
    assert "error" in report


@pytest.mark.parametrize("mirror_rel", [str(m) for m in sync.MIRRORS])
def test_repository_mirrors_are_in_sync(mirror_rel: str):
    """저장소의 실제 미러가 정본과 일치합니다."""
    _, report = sync.run(PROJECT_ROOT, check_only=True)
    assert report["mirrors"][mirror_rel]["in_sync"] is True, (
        f"{mirror_rel} 가 정본과 다릅니다. python3 scripts/sync_skill_mirrors.py 를 실행하십시오."
    )

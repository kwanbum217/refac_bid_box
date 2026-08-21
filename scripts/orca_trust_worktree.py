"""
scripts/orca_trust_worktree.py

Antigravity CLI 워커를 띄우기 전에 워크트리 경로를 신뢰 목록에 등록합니다.

Antigravity 는 폴더 신뢰를 절대경로 단위로 저장합니다. 그래서 워크트리를 새로
만들 때마다 이전 승인이 따라오지 않고 기동 직후 신뢰 다이얼로그가 뜹니다.
다이얼로그가 뜬 상태에서는 Task 주입이 대화창에 먹혀 사라지고, 사람이 직접
승인해야 워커가 시작합니다. terminal create 앞에 이 스크립트를 넣으면
다이얼로그 자체가 뜨지 않습니다.

이 스크립트는 사용자 홈의 CLI 설정을 고칩니다. 쓰기 전에 항상 백업을 남기고,
이미 등록된 경로는 건너뜁니다. 등록 외의 키는 손대지 않습니다.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any

CLI_SETTINGS = Path.home() / ".gemini" / "antigravity-cli" / "settings.json"
TRUSTED_FOLDERS = Path.home() / ".gemini" / "trustedFolders.json"
TRUST_VALUE = "TRUST_FOLDER"


def _load(path: Path) -> Any:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"오류: 설정을 읽을 수 없습니다: {path} ({exc})") from exc


def _write(path: Path, payload: Any) -> None:
    shutil.copy2(path, path.with_suffix(path.suffix + ".orca-bak"))
    temporary = path.with_name(f".{path.name}.orca.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def register(paths: list[Path], dry_run: bool) -> int:
    resolved = [p.resolve() for p in paths]
    missing = [p for p in resolved if not p.is_dir()]
    if missing:
        for p in missing:
            print(f"오류: 디렉터리가 없습니다: {p}", file=sys.stderr)
        return 2

    settings = _load(CLI_SETTINGS)
    if not isinstance(settings, dict):
        print(f"오류: CLI 설정을 찾을 수 없습니다: {CLI_SETTINGS}", file=sys.stderr)
        return 2

    workspaces = settings.get("trustedWorkspaces")
    if not isinstance(workspaces, list):
        workspaces = []
    known = {str(item) for item in workspaces}
    added = [str(p) for p in resolved if str(p) not in known]

    folders = _load(TRUSTED_FOLDERS)
    if not isinstance(folders, dict):
        folders = {}
    # 이 파일은 소문자 경로를 키로 씁니다. 대소문자를 섞으면 조회가 빗나갑니다.
    folder_added = [str(p).lower() for p in resolved if str(p).lower() not in folders]

    for p in resolved:
        state = "등록" if str(p) in {*added} else "이미 신뢰됨"
        print(f"{state}: {p}")

    if dry_run or (not added and not folder_added):
        return 0

    if added:
        settings["trustedWorkspaces"] = [*workspaces, *added]
        _write(CLI_SETTINGS, settings)
    if folder_added:
        for key in folder_added:
            folders[key] = TRUST_VALUE
        _write(TRUSTED_FOLDERS, folders)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Antigravity 워크트리 신뢰 사전 등록")
    parser.add_argument("paths", nargs="+", help="신뢰할 워크트리 경로")
    parser.add_argument("--dry-run", action="store_true", help="쓰지 않고 판정만 출력합니다")
    args = parser.parse_args()
    return register([Path(p) for p in args.paths], args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())

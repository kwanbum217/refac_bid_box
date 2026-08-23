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
import os
import shutil
import sys
import time
import uuid
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import IO, Any

try:
    import fcntl as _fcntl

    def _acquire_platform_lock(fobj: IO[Any]) -> bool:
        try:
            _fcntl.flock(fobj.fileno(), _fcntl.LOCK_EX | _fcntl.LOCK_NB)
            return True
        except (BlockingIOError, OSError):
            return False

    def _release_platform_lock(fobj: IO[Any]) -> None:
        with suppress(OSError):
            _fcntl.flock(fobj.fileno(), _fcntl.LOCK_UN)

    _LOCK_AVAILABLE = True
except ImportError:
    try:
        import msvcrt as _msvcrt

        _LOCK_CHUNK = 1

        def _acquire_platform_lock(fobj: IO[Any]) -> bool:
            try:
                fobj.seek(0)
                _msvcrt.locking(fobj.fileno(), _msvcrt.LK_NBLCK, _LOCK_CHUNK)
                return True
            except (BlockingIOError, OSError):
                return False

        def _release_platform_lock(fobj: IO[Any]) -> None:
            with suppress(OSError):
                fobj.seek(0)
                _msvcrt.locking(fobj.fileno(), _msvcrt.LK_UNLCK, _LOCK_CHUNK)

        _LOCK_AVAILABLE = True
    except ImportError:
        _LOCK_AVAILABLE = False

CLI_SETTINGS = Path.home() / ".gemini" / "antigravity-cli" / "settings.json"
TRUSTED_FOLDERS = Path.home() / ".gemini" / "trustedFolders.json"
TRUST_VALUE = "TRUST_FOLDER"
LOCK_FILE = TRUSTED_FOLDERS.parent / ".orca-trust-worktree.lock"
LOCK_TIMEOUT_SECONDS = 10.0


def _load(path: Path) -> Any:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"오류: 설정을 읽을 수 없습니다: {path} ({exc})") from exc


@contextmanager
def _settings_lock():
    """두 신뢰 설정 파일의 RMW 구간을 프로세스 간에 직렬화합니다.

    OS advisory lock(POSIX fcntl.flock, Windows msvcrt.locking)을 사용하여
    프로세스 비정상 종료 시 커널에 의해 락이 즉시 자동 해제되도록 합니다.
    기존 ad-hoc 락 파일의 TOCTOU 경쟁 조건(stat/unlink 사이의 타 프로세스 락 삭제 및
    미포착 FileNotFoundError)을 근본적으로 제거합니다.
    """
    if not _LOCK_AVAILABLE:
        sys.stderr.write(
            f"[trust] 파일 잠금을 지원하는 모듈이 없습니다 (fcntl/msvcrt). "
            f"동시 쓰기 안전성이 보장되지 않습니다: {LOCK_FILE}\n"
        )
        yield
        return

    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + LOCK_TIMEOUT_SECONDS
    token = f"{uuid.uuid4().hex}:{os.getpid()}"
    fobj: IO[str] | None = None
    while True:
        try:
            fobj = LOCK_FILE.open("a+", encoding="utf-8")
            if _acquire_platform_lock(fobj):
                with suppress(OSError):
                    fobj.seek(0)
                    fobj.truncate(0)
                    fobj.write(f"{token}\n")
                    fobj.flush()
                break
            fobj.close()
            fobj = None
        except OSError:
            if fobj is not None:
                with suppress(OSError):
                    fobj.close()
                fobj = None

        if time.monotonic() >= deadline:
            raise RuntimeError(f"신뢰 설정 잠금을 획득하지 못했습니다: {LOCK_FILE}") from None
        time.sleep(0.05)

    try:
        yield
    finally:
        if fobj is not None:
            try:
                _release_platform_lock(fobj)
            finally:
                with suppress(OSError):
                    fobj.close()


def _serialize(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.orca.tmp")
    try:
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(path)
    finally:
        with suppress(FileNotFoundError):
            temporary.unlink()


def _atomic_write(path: Path, payload: Any) -> None:
    _atomic_write_text(path, _serialize(payload))


def _backup(path: Path) -> None:
    if path.is_file():
        shutil.copy2(path, path.with_suffix(path.suffix + ".orca-bak"))


def _restore(path: Path, original: str | None, existed: bool) -> None:
    if existed:
        assert original is not None
        _atomic_write_text(path, original)
    else:
        with suppress(FileNotFoundError):
            path.unlink()


def register(paths: list[Path], dry_run: bool) -> int:
    resolved = [p.resolve() for p in paths]
    missing = [p for p in resolved if not p.is_dir()]
    if missing:
        for p in missing:
            print(f"오류: 디렉터리가 없습니다: {p}", file=sys.stderr)
        return 2

    try:
        with _settings_lock():
            settings_existed = CLI_SETTINGS.is_file()
            folders_existed = TRUSTED_FOLDERS.is_file()
            settings_original = (
                CLI_SETTINGS.read_text(encoding="utf-8") if settings_existed else None
            )
            folders_original = (
                TRUSTED_FOLDERS.read_text(encoding="utf-8") if folders_existed else None
            )
            settings = _load(CLI_SETTINGS)
            if not isinstance(settings, dict):
                print(f"오류: CLI 설정을 찾을 수 없습니다: {CLI_SETTINGS}", file=sys.stderr)
                return 2
            folders = _load(TRUSTED_FOLDERS)
            if folders is None:
                folders = {}
            if not isinstance(folders, dict):
                print(
                    f"오류: 신뢰 폴더 설정이 올바른 JSON 객체가 아닙니다: {TRUSTED_FOLDERS}",
                    file=sys.stderr,
                )
                return 2

            workspaces = settings.get("trustedWorkspaces")
            if not isinstance(workspaces, list):
                workspaces = []
            known = {str(item) for item in workspaces}
            added = [str(p) for p in resolved if str(p) not in known]
            folder_added = [str(p).lower() for p in resolved if str(p).lower() not in folders]

            for p in resolved:
                state = "등록" if str(p) in {*added} else "이미 신뢰됨"
                print(f"{state}: {p}")

            if dry_run or (not added and not folder_added):
                return 0

            updated_settings = {**settings, "trustedWorkspaces": [*workspaces, *added]}
            updated_folders = {**folders, **dict.fromkeys(folder_added, TRUST_VALUE)}
            _backup(CLI_SETTINGS)
            _backup(TRUSTED_FOLDERS)
            try:
                _atomic_write(CLI_SETTINGS, updated_settings)
                _atomic_write(TRUSTED_FOLDERS, updated_folders)
            except OSError:
                _restore(CLI_SETTINGS, settings_original, settings_existed)
                _restore(TRUSTED_FOLDERS, folders_original, folders_existed)
                raise
    except (OSError, RuntimeError) as exc:
        print(f"오류: 신뢰 설정을 원자적으로 저장하지 못했습니다: {exc}", file=sys.stderr)
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Antigravity 워크트리 신뢰 사전 등록")
    parser.add_argument("paths", nargs="+", help="신뢰할 워크트리 경로")
    parser.add_argument("--dry-run", action="store_true", help="쓰지 않고 판정만 출력합니다")
    args = parser.parse_args()
    return register([Path(p) for p in args.paths], args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python
"""등록된 모델이 제공자 쪽에 실제로 존재하는지 대조합니다.

2026-08-20 에 무료 풀 1순위 `opencode/deepseek-v4-flash-free` 가 제공자에서
사라졌는데 라우터는 그대로 들고 있었습니다. 소멸은 오류를 내지 않고 조용히
일어나며, 그 모델이 선택되는 순간에야 `Model not found` 로 드러납니다.

기본 실행은 read-only 관측으로 상태 파일을 수정하지 않습니다.
--commit-observation 옵션을 지정할 때만 상태 파일에 연속 absent 관측 이력을 영구 반영합니다.

관측 이력 기반 반복 확인: 조회 실패(unavailable)가 아닌 'absent'가
연속 3회 확인될 때만 소멸로 판정합니다.

종료 코드:
    0: 모든 배정 대상 모델 확인됨 또는 의심(1~2회 absent)
    1: 소멸 발견(3회 연속 absent)
    2: 도구 오류(손상된 상태 파일, 잠금 실패 등)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess  # nosec B404 - 고정 인자 목록으로만 호출합니다
import sys
import time
import uuid
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import IO, Any, Protocol, cast

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

        class _MsvcrtLockModule(Protocol):
            def locking(self, fd: int, mode: int, nbytes: int) -> None: ...

            LK_NBLCK: int
            LK_UNLCK: int

        _msvcrt_lock = cast(_MsvcrtLockModule, _msvcrt)
        _LOCK_CHUNK = 1

        def _acquire_platform_lock(fobj: IO[Any]) -> bool:
            try:
                fobj.seek(0)
                _msvcrt_lock.locking(fobj.fileno(), _msvcrt_lock.LK_NBLCK, _LOCK_CHUNK)
                return True
            except (BlockingIOError, OSError):
                return False

        def _release_platform_lock(fobj: IO[Any]) -> None:
            with suppress(OSError):
                fobj.seek(0)
                _msvcrt_lock.locking(fobj.fileno(), _msvcrt_lock.LK_UNLCK, _LOCK_CHUNK)

        _LOCK_AVAILABLE = True
    except ImportError:
        _LOCK_AVAILABLE = False

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.orca_model_router import MODEL_POOL

LISTING_TIMEOUT = 120
LOCK_TIMEOUT_SECONDS = 10.0

# 상태 파일 경로
STATUS_PATH = Path(__file__).resolve().parent.parent / "data" / "model_inventory_history.json"

CODEX_CACHE = Path.home() / ".codex" / "models_cache.json"
KIMI_CONFIG = Path.home() / ".kimi-openrouter-free" / "config.toml"

# provider 별 목록 조회 방법. 값이 None 이면 이 도구로는 확인할 수 없습니다.
LISTING_COMMANDS: dict[str, list[str] | None] = {
    "opencode": ["opencode", "models"],
    "cerebras": ["opencode", "models"],
    "codex": None,
    "cursor": None,
    "kimi-openrouter": None,
}

# `agy models` 는 비대화형 실행에서 응답이 늦어 기본 경로에서 뺐습니다.
# --with-agy 로 명시할 때만 조회합니다.
AGY_LISTING = ["agy", "models"]
AGY_PROVIDERS = frozenset({"gemini", "claude"})


class CorruptHistoryError(Exception):
    """상태 파일이 손상되었거나 읽을 수 없을 때 발생하는 예외."""


@contextmanager
def _history_lock(state_path: Path):
    """상태 파일 갱신 구간(RMW)을 프로세스 간에 직렬화합니다."""
    if not _LOCK_AVAILABLE:
        raise RuntimeError(f"파일 잠금을 지원하는 모듈이 없습니다 (fcntl/msvcrt): {state_path}")

    lock_file = state_path.with_name(f".{state_path.name}.lock")
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + LOCK_TIMEOUT_SECONDS
    token = f"{uuid.uuid4().hex}:{os.getpid()}"
    fobj: IO[str] | None = None
    while True:
        try:
            fobj = lock_file.open("a+", encoding="utf-8")
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
            raise RuntimeError(f"상태 파일 잠금을 획득하지 못했습니다: {lock_file}") from None
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


def _atomic_save_history(
    history: dict[str, dict[str, int | str]],
    state_path: Path,
) -> None:
    """임시 파일 작성 후 os.replace/Path.replace 를 통해 원자적으로 상태 파일을 갱신합니다."""
    state_path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(history, ensure_ascii=False, indent=2) + "\n"
    temporary = state_path.with_name(f".{state_path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(state_path)
    finally:
        with suppress(FileNotFoundError):
            temporary.unlink()


def _run_listing(cmd: list[str]) -> set[str]:
    proc = subprocess.run(  # nosec B603 - shell 없이 고정 인자 목록으로 호출합니다
        cmd,
        capture_output=True,
        text=True,
        timeout=LISTING_TIMEOUT,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd)} 실패 (종료 코드 {proc.returncode})")
    entries: set[str] = set()
    for line in proc.stdout.splitlines():
        token = line.strip().split("\t")[0].strip()
        if token:
            entries.add(token)
    return entries


def _codex_ids() -> set[str]:
    """models_cache.json 에서 모델 ID 를 뽑습니다. 키 값은 읽지 않습니다."""
    data = json.loads(CODEX_CACHE.read_text(encoding="utf-8"))
    found: set[str] = set()

    def walk(node: object) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key in ("id", "slug", "model") and isinstance(value, str):
                    found.add(value)
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(data)
    return found


def _kimi_aliases() -> set[str]:
    """config.toml 의 [models."<별칭>"] 헤더만 읽습니다. api_key 는 읽지 않습니다."""
    text = KIMI_CONFIG.read_text(encoding="utf-8")
    return set(re.findall(r'^\[models\."([^"]+)"\]', text, flags=re.MULTILINE))


def _load_history(state_path: Path | None = None) -> dict[str, dict[str, int | str]]:
    """상태 파일을 로드합니다. 파일이 없으면 빈 dict를 반환하고, 손상 시 예외를 발생시킵니다."""
    path = state_path if state_path is not None else STATUS_PATH
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise CorruptHistoryError(f"상태 파일 손상 또는 읽기 실패: {path} ({exc})") from exc
    if not isinstance(data, dict):
        raise CorruptHistoryError(f"상태 파일이 JSON 객체(dict)가 아닙니다: {path}")
    return data


def audit_with_state(
    with_agy: bool = False,
    state_path: Path | None = None,
    commit: bool = False,
) -> tuple[int, list[str], dict[str, dict[str, str | int]]]:
    """실제 감사 로직.

    commit=False(기본) 이면 기존 상태 파일(있을 경우)을 읽어 streak 를 계산만 하고
    파일을 쓰지 않는 read-only 관측을 수행합니다.
    commit=True 이면 감사 1회당 단일 파일 잠금 구간 내에서 모든 풀의 결과를 원자적으로 일괄 반영합니다.
    """
    resolved_path = state_path if state_path is not None else STATUS_PATH

    lines: list[str] = []
    listings: dict[str, set[str]] = {}
    missing = 0
    pools_json: dict[str, dict[str, str | int]] = {}
    observed_statuses: dict[str, tuple[str, str]] = {}

    # 1. 관측 수행
    for pool_name, info in sorted(MODEL_POOL.items()):
        if not info["suitable_for"]:
            observed_statuses[pool_name] = ("skipped", "배정 대상 아님 (suitable_for 비어 있음)")
            continue

        provider = info["provider"]
        model_id = info["id"]

        try:
            if provider == "codex":
                known = listings.setdefault("codex", _codex_ids())
                present = model_id in known or model_id == "codex"
            elif provider == "kimi-openrouter":
                known = listings.setdefault("kimi", _kimi_aliases())
                present = model_id in known
            elif provider in AGY_PROVIDERS:
                if not with_agy:
                    observed_statuses[pool_name] = (
                        "unknown",
                        "agy 조회 생략 (--with-agy 로 활성화)",
                    )
                    continue
                known = listings.setdefault("agy", _run_listing(AGY_LISTING))
                present = model_id in known
            else:
                cmd = LISTING_COMMANDS.get(provider)
                if cmd is None:
                    observed_statuses[pool_name] = ("unknown", f"{provider} 목록 조회 경로 없음")
                    continue
                known = listings.setdefault(provider, _run_listing(cmd))
                present = model_id in known
        except Exception as exc:
            observed_statuses[pool_name] = ("unknown", str(exc))
            continue

        if present:
            observed_statuses[pool_name] = ("present", model_id)
        else:
            observed_statuses[pool_name] = ("absent", model_id)

    # 2. 상태 계산 및 (선택적) 커밋
    def _compute_and_update(history: dict[str, dict[str, int | str]]) -> None:
        nonlocal missing
        missing = 0
        lines.clear()
        pools_json.clear()

        for pool_name, (status, detail) in observed_statuses.items():
            if status == "skipped":
                pools_json[pool_name] = {"status": "skipped", "streak": 0}
                lines.append(f"  건너뜀   {pool_name:26} {detail}")
                continue

            prev_record = history.get(pool_name, {})
            prev_counter_raw = prev_record.get("counter", 0) if isinstance(prev_record, dict) else 0
            prev_counter = prev_counter_raw if isinstance(prev_counter_raw, int) else 0

            if status == "unknown":
                streak = prev_counter
                pools_json[pool_name] = {"status": "unknown", "streak": streak}
                lines.append(f"  확인불가 {pool_name:26} {detail}")
                history[pool_name] = {"status": "unknown", "counter": streak}
            elif status == "present":
                streak = 0
                pools_json[pool_name] = {"status": "present", "streak": 0}
                lines.append(f"  존재     {pool_name:26} {detail}")
                history[pool_name] = {"status": "present", "counter": 0}
            elif status == "absent":
                streak = prev_counter + 1
                pools_json[pool_name] = {"status": "absent", "streak": streak}
                history[pool_name] = {"status": "absent", "counter": streak}
                if streak >= 3:
                    missing += 1
                    lines.append(f"  소멸     {pool_name:26} {detail}  <- 제공자 목록에 없음")
                else:
                    lines.append(f"  의심     {pool_name:26} {detail}  <- 의심 {streak}/3")

    if commit:
        with _history_lock(resolved_path):
            history = _load_history(resolved_path)
            _compute_and_update(history)
            _atomic_save_history(history, resolved_path)
    else:
        history = _load_history(resolved_path)
        scratch_history = dict(history)
        _compute_and_update(scratch_history)

    return missing, lines, pools_json


def audit(
    with_agy: bool = False,
    state_path: Path | None = None,
    commit: bool = False,
) -> tuple[int, list[str]]:
    """모델 존재 여부를 확인합니다.

    commit=True 일 때만 관측 이력을 상태 파일에 영구 기록합니다. 기본값(False)은 read-only 입니다.

    종료 코드:
        0: 모든 배정 대상 모델 확인됨 또는 의심(1~2회 absent)
        1: 소멸 발견(3회 연속 absent)
        2: 도구 오류(손상된 상태 파일, 잠금 오류 등)
    """
    missing, lines, _ = audit_with_state(with_agy=with_agy, state_path=state_path, commit=commit)
    return missing, lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="등록 모델 실재 대조")
    parser.add_argument("--quiet", action="store_true", help="소멸 항목만 출력")
    parser.add_argument(
        "--json",
        action="store_true",
        help="기계 판독용 JSON 만 출력합니다 (--quiet 무시)",
    )
    parser.add_argument(
        "--with-agy",
        action="store_true",
        help="Antigravity 목록도 조회합니다 (느립니다)",
    )
    parser.add_argument(
        "--state",
        type=str,
        default=None,
        help="상태 파일 경로를 지정합니다 (기본: data/model_inventory_history.json)",
    )
    parser.add_argument(
        "--commit-observation",
        action="store_true",
        help="관측 결과를 상태 파일에 영구 기록합니다 (기본: read-only)",
    )
    parser.add_argument(
        "--reset-state",
        action="store_true",
        help="상태 파일을 비웁니다",
    )
    args = parser.parse_args(argv)

    state_path = Path(args.state) if args.state else None
    resolved_path = state_path if state_path is not None else STATUS_PATH
    mode_str = "committed" if args.commit_observation else "read_only"

    # 상태 파일 리셋
    if args.reset_state:
        if resolved_path.exists():
            resolved_path.unlink()
        if not args.json:
            print("상태 파일을 비활화했습니다.")
        return 0

    try:
        missing, lines, pools_json = audit_with_state(
            with_agy=args.with_agy,
            state_path=state_path,
            commit=args.commit_observation,
        )
    except Exception as exc:
        if args.json:
            print(json.dumps({"mode": mode_str, "extinct": 0, "pools": {}}))
        else:
            print(f"도구 오류: {exc}")
        return 2

    if args.json:
        result = {"mode": mode_str, "extinct": missing, "pools": pools_json}
        print(json.dumps(result, ensure_ascii=False))
        return 1 if missing else 0

    if not args.quiet:
        print(f"=== 모델 실재 감사 (관측 모드: {mode_str}) ===")

    for line in lines:
        if not args.quiet or "소멸" in line:
            print(line)

    if missing:
        print(
            f"\n[{mode_str}] 소멸 {missing}건. 라우터의 suitable_for 를 비우고 FREE_POOL_ORDER 에서 빼십시오."
        )
        return 1
    print(f"\n[{mode_str}] 배정 대상 모델 전부 확인됨.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

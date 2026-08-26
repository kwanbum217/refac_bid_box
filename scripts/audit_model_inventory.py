#!/usr/bin/env python
"""등록된 모델이 제공자 쪽에 실제로 존재하는지 대조합니다.

2026-08-20 에 무료 풀 1순위 `opencode/deepseek-v4-flash-free` 가 제공자에서
사라졌는데 라우터는 그대로 들고 있었습니다. 소멸은 오류를 내지 않고 조용히
일어나며, 그 모델이 선택되는 순간에야 `Model not found` 로 드러납니다.

관측 이력 기반 반복 확인: 조회 실패(unavailable)가 아닌 'absent'가
연속 3회 확인될 때만 소멸로 판정합니다. 종료 코드: 0 전부 확인/의심, 1 소멸
발견, 2 도구 오류(손상된 상태 파일 등).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess  # nosec B404 - 고정 인자 목록으로만 호출합니다
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.orca_model_router import MODEL_POOL

LISTING_TIMEOUT = 120

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
    """상태 파일을 로드합니다. 손상되지 않았으면 기존 이력을 반환합니다."""
    path = state_path if state_path is not None else STATUS_PATH
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
        return {}
    except (json.JSONDecodeError, OSError):
        return {}


def _save_history(
    history: dict[str, dict[str, int | str]],
    state_path: Path | None = None,
) -> None:
    """상태 파일에 이력을 저장합니다."""
    path = state_path if state_path is not None else STATUS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")


def _update_history(
    pool_name: str,
    status: str,  # "present" | "absent" | "unknown"
    counter: int,
    state_path: Path | None = None,
) -> int:
    """조회 결과를 기록하고 반환된 카운터를 업데이트합니다."""
    history = _load_history(state_path)
    current = history.get(pool_name, {"status": "present", "counter": 0})
    prev_counter_raw = current.get("counter", 0)
    prev_counter = prev_counter_raw if isinstance(prev_counter_raw, int) else 0

    if status == "present":
        # present 관측: 카운터 초기화
        history[pool_name] = {"status": "present", "counter": 0}
        _save_history(history, state_path)
        return 0
    elif status == "absent":
        # absent 관측: 카운터 증가
        new_counter = prev_counter + 1
        history[pool_name] = {"status": "absent", "counter": new_counter}
        _save_history(history, state_path)
        return new_counter
    else:  # unknown
        # unknown 관측: 카운터 보존, 기록만 남김
        history[pool_name] = {"status": "unknown", "counter": prev_counter}
        _save_history(history, state_path)
        return prev_counter


def audit(with_agy: bool = False, state_path: Path | None = None) -> tuple[int, list[str]]:
    """모델 존재 여부를 확인하고 관측 이력을 누적합니다.

    종료 코드:
        0: 모든 배정 대상 모델 확인됨 또는 의심(1~2회 absent)
        1: 소멸 발견(3회 연속 absent)
        2: 도구 오류(손상된 상태 파일 등)
    """
    lines: list[str] = []
    listings: dict[str, set[str]] = {}
    missing = 0

    for pool_name, info in sorted(MODEL_POOL.items()):
        if not info["suitable_for"]:
            lines.append(f"  건너뜀   {pool_name:26} 배정 대상 아님 (suitable_for 비어 있음)")
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
                    lines.append(f"  확인불가 {pool_name:26} agy 조회 생략 (--with-agy 로 활성화)")
                    _update_history(pool_name, "unknown", 0, state_path)
                    continue
                known = listings.setdefault("agy", _run_listing(AGY_LISTING))
                present = model_id in known
            else:
                cmd = LISTING_COMMANDS.get(provider)
                if cmd is None:
                    lines.append(f"  확인불가 {pool_name:26} {provider} 목록 조회 경로 없음")
                    _update_history(pool_name, "unknown", 0, state_path)
                    continue
                known = listings.setdefault(provider, _run_listing(cmd))
                present = model_id in known
        except Exception as exc:
            lines.append(f"  확인불가 {pool_name:26} {exc}")
            _update_history(pool_name, "unknown", 0, state_path)
            continue

        if present:
            lines.append(f"  존재     {pool_name:26} {model_id}")
            _update_history(pool_name, "present", 0, state_path)
        else:
            counter = _update_history(pool_name, "absent", 0, state_path)
            if counter >= 3:
                missing += 1
                lines.append(f"  소멸     {pool_name:26} {model_id}  <- 제공자 목록에 없음")
            else:
                lines.append(f"  의심     {pool_name:26} {model_id}  <- 의심 {counter}/3")

    return missing, lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="등록 모델 실재 대조")
    parser.add_argument("--quiet", action="store_true", help="소멸 항목만 출력")
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
        "--reset-state",
        action="store_true",
        help="상태 파일을 비웁니다",
    )
    args = parser.parse_args(argv)

    state_path = Path(args.state) if args.state else None

    # 상태 파일 리셋
    if args.reset_state:
        if state_path and state_path.exists():
            state_path.unlink()
        elif not state_path and STATUS_PATH.exists():
            STATUS_PATH.unlink()
        print("상태 파일을 비활화했습니다.")
        return 0

    try:
        missing, lines = audit(with_agy=args.with_agy, state_path=state_path)
    except Exception as exc:
        print(f"도구 오류: {exc}")
        return 2

    for line in lines:
        if not args.quiet or "소멸" in line:
            print(line)

    if missing:
        print(f"\n소멸 {missing}건. 라우터의 suitable_for 를 비우고 FREE_POOL_ORDER 에서 빼십시오.")
        return 1
    print("\n배정 대상 모델 전부 확인됨.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

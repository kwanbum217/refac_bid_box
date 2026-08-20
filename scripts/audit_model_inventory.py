#!/usr/bin/env python
"""등록된 모델이 제공자 쪽에 실제로 존재하는지 대조합니다.

2026-08-20 에 무료 풀 1순위 `opencode/deepseek-v4-flash-free` 가 제공자에서
사라졌는데 라우터는 그대로 들고 있었습니다. 소멸은 오류를 내지 않고 조용히
일어나며, 그 모델이 선택되는 순간에야 `Model not found` 로 드러납니다.

배정 대상(`suitable_for` 가 비어 있지 않은 항목)만 검사합니다. 코디네이터
전용이나 이력 보존 항목은 애초에 배정되지 않으므로 소멸해도 해가 없습니다.

종료 코드: 0 전부 확인, 1 소멸 발견, 2 도구 오류
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


def audit(with_agy: bool = False) -> tuple[int, list[str]]:
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
                    continue
                known = listings.setdefault("agy", _run_listing(AGY_LISTING))
                present = model_id in known
            else:
                cmd = LISTING_COMMANDS.get(provider)
                if cmd is None:
                    lines.append(f"  확인불가 {pool_name:26} {provider} 목록 조회 경로 없음")
                    continue
                known = listings.setdefault(provider, _run_listing(cmd))
                present = model_id in known
        except Exception as exc:
            lines.append(f"  확인불가 {pool_name:26} {exc}")
            continue

        if present:
            lines.append(f"  존재     {pool_name:26} {model_id}")
        else:
            missing += 1
            lines.append(f"  소멸     {pool_name:26} {model_id}  <- 제공자 목록에 없음")

    return missing, lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="등록 모델 실재 대조")
    parser.add_argument("--quiet", action="store_true", help="소멸 항목만 출력")
    parser.add_argument(
        "--with-agy",
        action="store_true",
        help="Antigravity 목록도 조회합니다 (느립니다)",
    )
    args = parser.parse_args(argv)

    try:
        missing, lines = audit(with_agy=args.with_agy)
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

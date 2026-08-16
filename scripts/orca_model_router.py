#!/usr/bin/env python3
"""
scripts/orca_model_router.py

Orca 워커 모델 라우터. Task 의 위험도와 유형에 따라 적절한 모델을 선택하고,
Dispatch 전에 모델 가용성을 probe 합니다.

주요 기능:
  1. classify  -- Task Intent 또는 Capsule 을 분석해 위험도와 권장 모델 풀을 반환합니다.
  2. probe     -- 모델 ID 가 실제로 호출 가능한지 검증합니다 (preflight).
  3. route     -- classify + probe 를 한 번에 수행하고 최종 모델을 결정합니다.
  4. list      -- 등록된 모델 풀과 정책을 출력합니다.

모델 풀 정책 (정본: .agents/skills/orca-section-coordination/SKILL.md 3.1절):
  - Claude 구독     : 코디네이터 전용. 워커로 사용하지 않습니다.
  - Gemini Flash    : 주력 워커. 분석·감사·측정·절차적 구현.
  - Claude 계열     : 별도 풀. 판정 품질이 필요한 작업.
  - Codex           : 주간 잔량이 넉넉할 때만.
  - OpenCode 무료   : 실패해도 손실 없는 병렬 조사. 임계 경로 금지.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    from scripts.orca_contract import char_len, load_capsule, parse_capsule_scalar
except (ModuleNotFoundError, ImportError):
    _repo_root = Path(__file__).resolve().parent.parent
    if str(_repo_root) not in sys.path:
        sys.path.insert(0, str(_repo_root))
    from scripts.orca_contract import char_len, load_capsule, parse_capsule_scalar

# ---------------------------------------------------------------------------
# 모델 풀 정의
# ---------------------------------------------------------------------------

# 프로바이더별 probe 명령과 타임아웃
PROBE_CONFIG: dict[str, dict[str, Any]] = {
    "gemini": {
        "probe_cmd": ["agy", "--model", "{model}", "--print", "ping", "--print-timeout", "15s"],
        "timeout": 20,
    },
    "claude": {
        "probe_cmd": ["agy", "--model", "{model}", "--print", "ping", "--print-timeout", "15s"],
        "timeout": 20,
    },
    "opencode": {
        "probe_cmd": ["opencode", "ask", "--model", "{model}", "--prompt", "ping"],
        "timeout": 15,
    },
}

# 등록된 모델 풀
MODEL_POOL: dict[str, dict[str, Any]] = {
    "gemini-flash-high": {
        "id": "gemini-3.7-flash-high",
        "provider": "gemini",
        "tier": "primary",
        "max_tokens": 1_000_000,
        "suitable_for": [
            "builder",
            "reviewer",
            "investigator",
            "benchmarker",
            "documenter",
        ],
        "notes": "주력 워커. 분석·감사·측정·절차적 구현.",
    },
    "gemini-flash-medium": {
        "id": "gemini-3.7-flash-medium",
        "provider": "gemini",
        "tier": "primary",
        "max_tokens": 1_000_000,
        "suitable_for": [
            "investigator",
            "documenter",
        ],
        "notes": "읽기 전용 조사 및 문서화.",
    },
    "claude-sonnet": {
        "id": "claude-sonnet-4-6",
        "provider": "claude",
        "tier": "secondary",
        "max_tokens": 200_000,
        "suitable_for": [
            "reviewer",
            "builder",
        ],
        "notes": "별도 풀. 판정 품질이 필요한 작업에만 사용.",
    },
    "claude-opus": {
        "id": "claude-opus-5",
        "provider": "claude",
        "tier": "coordinator",
        "max_tokens": 200_000,
        "suitable_for": [],
        "notes": "코디네이터 전용. 워커로 사용하지 않습니다.",
    },
    "codex": {
        "id": "codex",
        "provider": "opencode",
        "tier": "secondary",
        "max_tokens": None,
        "suitable_for": [
            "investigator",
            "documenter",
        ],
        "notes": "주간 잔량이 넉넉할 때만 사용.",
    },
    "opencode-free": {
        "id": "opencode-free",
        "provider": "opencode",
        "tier": "free",
        "max_tokens": None,
        "suitable_for": [
            "investigator",
        ],
        "notes": "실패해도 손실 없는 병렬 조사. 임계 경로 금지.",
    },
}

# 위험도 분류 기준
RISK_KEYWORDS = {
    "high": [
        r"\bmerge\b", r"\b병합\b", r"\bdeploy\b", r"\b배포\b",
        r"\bDB\b", r"\bdatabase\b", r"\bschema\b", r"\b스키마\b",
        r"\bmigration\b", r"\b마이그레이션\b", r"\bDROP\b", r"\bDELETE\b",
        r"\bpromotion\b", r"\b승격\b", r"\bcutover\b", r"\b컷오버\b",
        r"\bproduction\b", r"\b운영\b", r"\bretrain\b", r"\b재학습\b",
        r"\bsecurity\b", r"\b보안\b", r"\bsecret\b", r"\b시크릿\b",
    ],
    "medium": [
        r"\brefactor\b", r"\b리팩토링\b", r"\boptimize\b", r"\b최적화\b",
        r"\bperformance\b", r"\b성능\b", r"\bmodel\b", r"\b모델\b",
        r"\bAPI\b", r"\bendpoint\b", r"\b엔드포인트\b",
        r"\bconfig\b", r"\b설정\b", r"\bcache\b", r"\b캐시\b",
    ],
    "low": [
        r"\bdoc\b", r"\b문서\b", r"\btest\b", r"\b테스트\b",
        r"\blint\b", r"\bformat\b", r"\b포맷\b", r"\btypo\b",
        r"\bcomment\b", r"\b주석\b", r"\brename\b", r"\bchore\b",
    ],
}


# ---------------------------------------------------------------------------
# 데이터 클래스
# ---------------------------------------------------------------------------


@dataclass
class RouteResult:
    """모델 라우팅 결과."""

    risk: str  # low | medium | high
    role: str
    primary_model: str
    fallback_model: str | None
    primary_available: bool
    fallback_available: bool | None
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# 위험도 분류
# ---------------------------------------------------------------------------


def classify_risk(text: str) -> str:
    """텍스트에서 키워드 기반 위험도를 분류합니다.

    high 키워드가 하나라도 있으면 high,
    medium 키워드가 하나라도 있으면 medium,
    그 외에는 low 를 반환합니다.
    """
    text_lower = text.lower()
    for pattern in RISK_KEYWORDS["high"]:
        if re.search(pattern, text_lower):
            return "high"
    for pattern in RISK_KEYWORDS["medium"]:
        if re.search(pattern, text_lower):
            return "medium"
    return "low"


def classify_from_capsule(capsule_path: str | Path) -> dict[str, str]:
    """Capsule 파일에서 objective, why_now, role 등을 읽어 위험도를 분류합니다."""
    capsule_text = load_capsule(capsule_path)
    objective = parse_capsule_scalar(capsule_text, "objective") or ""
    why_now = parse_capsule_scalar(capsule_text, "why_now") or ""
    role = parse_capsule_scalar(capsule_text, "role") or "builder"

    combined = f"{objective}\n{why_now}"
    risk = classify_risk(combined)
    return {"risk": risk, "role": role, "objective": objective[:100]}


# ---------------------------------------------------------------------------
# 모델 선택
# ---------------------------------------------------------------------------


def select_model(role: str, risk: str, exclude: list[str] | None = None) -> dict[str, Any]:
    """역할과 위험도에 따라 최적 모델을 선택합니다.

    우선순위:
      1. high risk + reviewer → claude-sonnet
      2. builder / reviewer → gemini-flash-high
      3. investigator / benchmarker → gemini-flash-high
      4. documenter / low risk → gemini-flash-medium
      5. coordinator 전용 → claude-opus (워커로 사용 불가)

    이미 실패한 모델은 exclude 로 제외하고 다음 후보를 반환합니다.
    """
    exclude = exclude or []

    # 위험도 기반 우선순위 큐
    if risk == "high" and role == "reviewer":
        candidates = ["claude-sonnet", "gemini-flash-high"]
    elif risk == "high":
        candidates = ["gemini-flash-high", "claude-sonnet"]
    elif role == "reviewer":
        candidates = ["gemini-flash-high", "claude-sonnet"]
    elif role == "builder":
        candidates = ["gemini-flash-high"]
    elif role in ("investigator", "benchmarker"):
        candidates = ["gemini-flash-high", "gemini-flash-medium"]
    elif role == "documenter":
        candidates = ["gemini-flash-medium", "gemini-flash-high"]
    else:
        candidates = ["gemini-flash-high"]

    # 제외 목록 필터링
    primary = None
    fallback = None
    for c in candidates:
        if c not in exclude:
            if primary is None:
                primary = c
            elif fallback is None:
                fallback = c
                break

    if primary is None:
        primary = "gemini-flash-high"

    primary_model = MODEL_POOL.get(primary, {}).get("id", primary)
    fallback_model = MODEL_POOL.get(fallback, {}).get("id", fallback) if fallback else None

    return {
        "primary_pool": primary,
        "primary_model": primary_model,
        "fallback_pool": fallback,
        "fallback_model": fallback_model,
        "risk": risk,
        "role": role,
    }


# ---------------------------------------------------------------------------
# 모델 가용성 probe
# ---------------------------------------------------------------------------


def probe_model(model_id: str, timeout: int = 30) -> tuple[bool, str]:
    """모델이 실제로 호출 가능한지 확인합니다.

    반환값: (available: bool, detail: str)
    """
    # 모델 ID 를 풀에서 찾아 provider 확인
    provider = None
    for pool_name, pool_info in MODEL_POOL.items():
        if pool_info["id"] == model_id:
            provider = pool_info["provider"]
            break

    if provider is None:
        # 알 수 없는 모델이면 provider 추측
        if "gemini" in model_id.lower():
            provider = "gemini"
        elif "claude" in model_id.lower():
            provider = "claude"
        else:
            provider = "opencode"

    probe_info = PROBE_CONFIG.get(provider)
    if probe_info is None:
        return False, f"알 수 없는 provider: {provider}"

    cmd_template = probe_info["probe_cmd"]
    cmd = [arg.format(model=model_id) for arg in cmd_template]
    probe_timeout = probe_info.get("timeout", timeout)

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=probe_timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return False, f"probe 타임아웃 ({probe_timeout}초)"
    except FileNotFoundError:
        return False, f"실행 파일 없음: {cmd[0]}"

    # probe 성공 판정: 종료 코드 0 이고 stderr 에 치명적 오류가 없음
    if proc.returncode == 0:
        stderr_lower = proc.stderr.lower()
        fatal_keywords = ["error", "unauthorized", "forbidden", "not found", "quota"]
        for kw in fatal_keywords:
            if kw in stderr_lower:
                return False, f"probe 실패: {proc.stderr.strip()[:200]}"
        return True, f"OK (종료 코드 0, {len(proc.stdout)}자)"
    else:
        return False, f"probe 실패 (종료 코드 {proc.returncode}): {proc.stderr.strip()[:200]}"


def preflight(model_id: str, timeout: int = 30) -> tuple[bool, list[str]]:
    """Dispatch 전 전체 preflight 검사를 수행합니다.

    확인 항목:
      1. 모델 ID 가 등록된 풀에 있는가
      2. 모델 probe 가 성공하는가

    반환값: (passed: bool, warnings: list[str])
    """
    warnings: list[str] = []

    # 등록 확인
    registered = False
    for pool_name, pool_info in MODEL_POOL.items():
        if pool_info["id"] == model_id:
            registered = True
            if pool_info["tier"] == "coordinator":
                warnings.append(f"경고: {model_id} 는 코디네이터 전용입니다. 워커로 사용하지 마십시오.")
            if pool_info["tier"] == "free":
                warnings.append(
                    f"경고: {model_id} 는 무료 풀입니다. 임계 경로에 사용하지 마십시오."
                )
            break
    if not registered:
        warnings.append(f"경고: {model_id} 는 등록된 모델 풀에 없습니다.")

    # probe
    available, detail = probe_model(model_id, timeout)
    if not available:
        warnings.append(f"probe 실패: {detail}")

    return available and not any("경고" not in w for w in warnings), warnings


# ---------------------------------------------------------------------------
# 통합 라우팅
# ---------------------------------------------------------------------------


def route(
    capsule_path: str | Path | None = None,
    role: str | None = None,
    risk: str | None = None,
    objective: str | None = None,
    why_now: str | None = None,
    probe: bool = True,
    probe_timeout: int = 30,
) -> RouteResult:
    """전체 라우팅 파이프라인을 실행합니다.

    Capsule 이 제공되면 Capsule 에서 role, risk 를 추출합니다.
    그렇지 않으면 명시적 인자를 사용합니다.
    """
    warnings: list[str] = []

    # Capsule 기반 분류
    if capsule_path:
        info = classify_from_capsule(capsule_path)
        if role is None:
            role = info["role"]
        if risk is None:
            risk = info["risk"]
    elif objective or why_now:
        combined = f"{objective or ''}\n{why_now or ''}"
        if risk is None:
            risk = classify_risk(combined)
    else:
        if risk is None:
            risk = "medium"
        if role is None:
            role = "builder"

    # 모델 선택
    selection = select_model(role, risk)
    primary_id = selection["primary_model"]
    fallback_id = selection.get("fallback_model")

    primary_available = True
    fallback_available: bool | None = None

    if probe:
        available, detail = probe_model(primary_id, probe_timeout)
        primary_available = available
        if not available:
            warnings.append(f"주 모델 {primary_id} 사용 불가: {detail}")
            if fallback_id:
                available_fb, detail_fb = probe_model(fallback_id, probe_timeout)
                fallback_available = available_fb
                if not available_fb:
                    warnings.append(f"대체 모델 {fallback_id} 도 사용 불가: {detail_fb}")
                else:
                    warnings.append(f"대체 모델 {fallback_id} 로 전환합니다.")

    # 모델 풀 제약 검사
    for pool_name, pool_info in MODEL_POOL.items():
        if pool_info["id"] == primary_id:
            if pool_info["tier"] == "coordinator":
                warnings.append("경고: 코디네이터 전용 모델이 워커로 선택되었습니다.")
            elif pool_info["tier"] == "free" and risk != "low":
                warnings.append("경고: 무료 모델이 임계 경로에 사용됩니다.")

    return RouteResult(
        risk=risk,
        role=role,
        primary_model=primary_id,
        fallback_model=fallback_id,
        primary_available=primary_available,
        fallback_available=fallback_available,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="orca_model_router",
        description="Orca 워커 모델 라우터",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # classify
    cls = sub.add_parser("classify", help="Task 의 위험도와 권장 모델을 분류합니다.")
    cls.add_argument("--capsule", help="Task Capsule YAML 경로")
    cls.add_argument("--role", choices=["builder", "reviewer", "investigator", "benchmarker", "documenter"])
    cls.add_argument("--objective", help="작업 목표 텍스트")
    cls.add_argument("--why-now", help="작업 배경 텍스트")
    cls.add_argument("--json", action="store_true", help="JSON 출력")

    # probe
    prb = sub.add_parser("probe", help="모델 가용성을 확인합니다.")
    prb.add_argument("--model", required=True, help="모델 ID")
    prb.add_argument("--timeout", type=int, default=30, help="probe 타임아웃 (초)")
    prb.add_argument("--json", action="store_true", help="JSON 출력")

    # route
    rt = sub.add_parser("route", help="분류 + probe 통합 라우팅.")
    rt.add_argument("--capsule", help="Task Capsule YAML 경로")
    rt.add_argument("--role", choices=["builder", "reviewer", "investigator", "benchmarker", "documenter"])
    rt.add_argument("--risk", choices=["low", "medium", "high"])
    rt.add_argument("--objective", help="작업 목표 텍스트")
    rt.add_argument("--why-now", help="작업 배경 텍스트")
    rt.add_argument("--no-probe", action="store_true", help="probe 생략")
    rt.add_argument("--probe-timeout", type=int, default=30, help="probe 타임아웃 (초)")
    rt.add_argument("--json", action="store_true", help="JSON 출력")

    # list
    sub.add_parser("list", help="등록된 모델 풀을 출력합니다.")

    return parser


def cmd_classify(args: argparse.Namespace) -> int:
    if args.capsule:
        info = classify_from_capsule(args.capsule)
        risk = info["risk"]
        role = info["role"]
        objective = info["objective"]
    else:
        objective = args.objective or ""
        why_now = args.why_now or ""
        role = args.role or "builder"
        combined = f"{objective}\n{why_now}"
        risk = classify_risk(combined)

    selection = select_model(role, risk)

    if args.json:
        print(json.dumps({
            "risk": risk,
            "role": role,
            "primary_model": selection["primary_model"],
            "primary_pool": selection["primary_pool"],
            "fallback_model": selection.get("fallback_model"),
            "fallback_pool": selection.get("fallback_pool"),
        }, ensure_ascii=False, indent=2))
    else:
        print(f"위험도:       {risk}")
        print(f"역할:         {role}")
        print(f"주 모델:      {selection['primary_model']} ({selection['primary_pool']})")
        if selection.get("fallback_model"):
            print(f"대체 모델:    {selection['fallback_model']} ({selection['fallback_pool']})")
        if objective:
            print(f"작업 요약:    {objective}")
    return 0


def cmd_probe(args: argparse.Namespace) -> int:
    available, detail = probe_model(args.model, args.timeout)
    if args.json:
        print(json.dumps({"model": args.model, "available": available, "detail": detail}, ensure_ascii=False, indent=2))
    else:
        status = "사용 가능" if available else "사용 불가"
        print(f"모델:    {args.model}")
        print(f"상태:    {status}")
        print(f"상세:    {detail}")
    return 0 if available else 1


def cmd_route(args: argparse.Namespace) -> int:
    result = route(
        capsule_path=args.capsule,
        role=args.role,
        risk=args.risk,
        objective=args.objective,
        why_now=args.why_now,
        probe=not args.no_probe,
        probe_timeout=args.probe_timeout,
    )

    if args.json:
        print(json.dumps({
            "risk": result.risk,
            "role": result.role,
            "primary_model": result.primary_model,
            "primary_available": result.primary_available,
            "fallback_model": result.fallback_model,
            "fallback_available": result.fallback_available,
            "warnings": result.warnings,
            "recommended": (
                result.fallback_model
                if not result.primary_available and result.fallback_available
                else result.primary_model
            ),
        }, ensure_ascii=False, indent=2))
    else:
        print(f"위험도:        {result.risk}")
        print(f"역할:          {result.role}")
        print(f"주 모델:       {result.primary_model} {'(사용 가능)' if result.primary_available else '(사용 불가)'}")
        if result.fallback_model:
            fb_status = "(사용 가능)" if result.fallback_available else "(사용 불가)" if result.fallback_available is not None else "(미확인)"
            print(f"대체 모델:     {result.fallback_model} {fb_status}")
        if result.warnings:
            print()
            for w in result.warnings:
                print(f"  {w}")
        print()
        if not result.primary_available and result.fallback_available:
            print(f"권장: 대체 모델 {result.fallback_model} 사용")
        elif result.primary_available:
            print(f"권장: {result.primary_model} 사용")
        else:
            print("경고: 사용 가능한 모델이 없습니다!")

    has_warnings = bool(result.warnings)
    has_available = result.primary_available or result.fallback_available
    return 0 if has_available and not any("경고: 코디네이터" in w for w in result.warnings) else 1


def cmd_list(args: argparse.Namespace) -> int:  # noqa: ARG001
    print("등록된 모델 풀:")
    print("-" * 80)
    for pool_name, info in MODEL_POOL.items():
        tier_label = {"primary": "주력", "secondary": "보조", "coordinator": "코디네이터", "free": "무료"}.get(
            info["tier"], info["tier"]
        )
        print(f"  {pool_name} ({tier_label})")
        print(f"    ID:       {info['id']}")
        print(f"    Provider: {info['provider']}")
        print(f"    용도:     {', '.join(info['suitable_for']) or '워커 사용 불가'}")
        print(f"    비고:     {info['notes']}")
        print()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "classify":
        return cmd_classify(args)
    if args.command == "probe":
        return cmd_probe(args)
    if args.command == "route":
        return cmd_route(args)
    if args.command == "list":
        return cmd_list(args)
    return 1


if __name__ == "__main__":
    sys.exit(main())
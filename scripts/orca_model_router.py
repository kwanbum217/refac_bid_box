#!/usr/bin/env python3
"""
scripts/orca_model_router.py

Orca 워커 모델 라우터. Task 의 위험도와 유형에 따라 적절한 모델을 선택하고,
Dispatch 전에 모델 가용성을 probe 합니다.

주요 기능:
  1. classify  -- Task Intent 또는 Capsule 을 분석해 위험도와 권장 모델 풀을 반환합니다.
  2. probe     -- 모델 ID 가 실제로 호출 가능한지 검증합니다.
  3. route     -- classify + probe 를 한 번에 수행하고 최종 모델을 결정합니다.
  4. list      -- 등록된 모델 풀과 자동 선택 여부 정책을 출력합니다.

모델 풀 정책 (정본: .agents/skills/orca-section-coordination/SKILL.md 3.1절):
  - Claude 구독     : 코디네이터 전용 (claude-opus-5). 워커 사용 절대 금지.
  - Gemini Flash    : 주력 워커 (gemini-3.7-flash-high). 분석·감사·측정·절차적 구현.
  - Claude 계열     : 별도 풀 (claude-sonnet-4-6). 판정 품질이 필요한 작업.
  - Codex           : 주간 잔량이 넉넉할 때만 수동 지정.
  - OpenCode 무료   : 실패해도 손실 없는 병렬 조사. 임계 경로 금지.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    from scripts.orca_contract import load_capsule, parse_capsule_list, parse_capsule_scalar
except (ModuleNotFoundError, ImportError):
    _repo_root = Path(__file__).resolve().parent.parent
    if str(_repo_root) not in sys.path:
        sys.path.insert(0, str(_repo_root))
    from scripts.orca_contract import load_capsule, parse_capsule_list, parse_capsule_scalar

# ---------------------------------------------------------------------------
# 프로바이더별 probe 설정
# ---------------------------------------------------------------------------

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
        "probe_cmd": ["opencode", "run", "--model", "{model}", "ping"],
        "timeout": 15,
    },
    "codex": {
        "probe_cmd": ["codex", "exec", "ping"],
        "timeout": 30,
    },
    "cerebras": {
        "probe_cmd": ["opencode", "run", "--model", "{model}", "ping"],
        "timeout": 20,
    },
}

# ---------------------------------------------------------------------------
# 등록된 모델 풀
# ---------------------------------------------------------------------------

MODEL_POOL: dict[str, dict[str, Any]] = {
    "gemini-flash-high": {
        "id": "gemini-3.7-flash-high",
        "provider": "gemini",
        "tier": "primary",
        "auto_selectable": True,
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
        "auto_selectable": True,
        "max_tokens": 1_000_000,
        "suitable_for": [
            "investigator",
            "documenter",
        ],
        "notes": "읽기 전용 조사 및 문서화.",
    },
    "gemini-flash-low": {
        "id": "gemini-3.7-flash-low",
        "provider": "gemini",
        "tier": "primary",
        "auto_selectable": False,
        "max_tokens": 1_000_000,
        "suitable_for": [
            "documenter",
        ],
        "notes": "추론 단계가 가장 얕다. 2026-08-17 에 호출 가능만 확인했고 산출 품질은 미측정이라 자동 선택 대상이 아니다. 판단이 없는 기계적 치환에 수동 지정한다.",
    },
    "claude-sonnet": {
        "id": "claude-sonnet-4-6",
        "provider": "claude",
        "tier": "secondary",
        "auto_selectable": True,
        "max_tokens": 200_000,
        "suitable_for": [
            "reviewer",
            "builder",
        ],
        "notes": "별도 풀. 판정 품질이 필요한 작업에만 사용.",
    },
    "claude-opus-thinking": {
        "id": "claude-opus-4-6-thinking",
        "provider": "claude",
        "tier": "secondary",
        "auto_selectable": False,
        "max_tokens": 200_000,
        "suitable_for": [
            "reviewer",
        ],
        "notes": "Antigravity 별도 풀. 2026-08-17 감사 1건 실측: 보고 11,773자로 최다, 줄 수 기준을 기계적으로 적용하지 않고 분할 불필요를 논증. 수동 지정 전용.",
    },
    "claude-opus": {
        "id": "claude-opus-5",
        "provider": "claude",
        "tier": "coordinator",
        "auto_selectable": False,
        "max_tokens": 200_000,
        "suitable_for": [],
        "notes": "코디네이터 전용. 워커로 사용하지 않습니다.",
    },
    "codex": {
        "id": "codex",
        "provider": "codex",
        "tier": "secondary",
        "auto_selectable": False,
        "max_tokens": None,
        "suitable_for": [
            "investigator",
            "documenter",
        ],
        "notes": "주간 잔량이 넉넉할 때만 수동 지정.",
    },
    "opencode-free": {
        "id": "opencode/nemotron-3.5-lightning-free",
        "provider": "opencode",
        "tier": "free",
        "auto_selectable": False,
        "max_tokens": None,
        "suitable_for": [
            "investigator",
        ],
        "notes": "실패해도 손실 없는 병렬 조사. 임계 경로 금지 (allow_free 조건부 개방). fallback 후보: opencode/deepseek-v4-flash-free.",
    },
    "cerebras-oss": {
        "id": "cerebras/gpt-oss-120b",
        "provider": "cerebras",
        "tier": "free",
        "auto_selectable": False,
        "max_tokens": 65536,
        "suitable_for": [
            "investigator",
        ],
        "notes": "컨텍스트 65536 출력 8192 제한. Capsule 범위 작업 전용.",
    },
    "cerebras-gemma": {
        "id": "cerebras/gemma-4-31b",
        "provider": "cerebras",
        "tier": "free",
        "auto_selectable": False,
        "max_tokens": 65536,
        "suitable_for": [
            "investigator",
        ],
        "notes": (
            "실제 제약은 컨텍스트가 아니라 분당 토큰(TPM)이다. 2026-08-17 실측: "
            "파일 2개(1,081줄) 통독 실패, 파일 1개(522줄) 통독도 실패, 사실 주입 "
            "원샷(도구 호출 0회)은 성공. 에이전트 루프가 매 턴 컨텍스트를 재전송해 "
            "분당 유입이 누적되므로 파일 수 축소로는 해소되지 않는다. "
            "ground_truth 주입형 단발 판정에만 쓴다."
        ),
    },
}

# ---------------------------------------------------------------------------
# 무료/저가 풀 개방 정책 상수
# ---------------------------------------------------------------------------

FREE_POOL_ELIGIBLE_ROLES: frozenset[str] = frozenset({"investigator"})
FREE_POOL_MAX_RISK: str = "low"
FREE_POOL_ORDER: list[str] = ["opencode-free", "cerebras-oss"]

# ---------------------------------------------------------------------------
# 위험도 분류 기준
# ---------------------------------------------------------------------------

RISK_KEYWORDS: dict[str, list[str]] = {
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
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# 위험도 분류
# ---------------------------------------------------------------------------


def classify_risk_with_reasons(text: str) -> tuple[str, list[str]]:
    """텍스트에서 키워드 기반 위험도와 매칭된 근거를 분류합니다.

    대소문자를 무시하고(re.IGNORECASE) 원문을 검사합니다.
    high 키워드가 하나라도 매칭되면 high,
    medium 키워드가 하나라도 매칭되면 medium,
    그 외에는 low 를 반환합니다.
    """
    matched_high: list[str] = []
    for pattern in RISK_KEYWORDS["high"]:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            matched_high.append(match.group(0))

    if matched_high:
        keywords_str = ", ".join(sorted(set(matched_high)))
        return "high", [f"high 키워드 매칭: {keywords_str}"]

    matched_medium: list[str] = []
    for pattern in RISK_KEYWORDS["medium"]:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            matched_medium.append(match.group(0))

    if matched_medium:
        keywords_str = ", ".join(sorted(set(matched_medium)))
        return "medium", [f"medium 키워드 매칭: {keywords_str}"]

    matched_low: list[str] = []
    for pattern in RISK_KEYWORDS["low"]:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            matched_low.append(match.group(0))

    if matched_low:
        keywords_str = ", ".join(sorted(set(matched_low)))
        return "low", [f"low 키워드 매칭: {keywords_str}"]

    return "low", ["기본 위험도: low (매칭된 키워드 없음)"]


def classify_risk(text: str) -> str:
    """텍스트에서 위험도 등급(high | medium | low)만 반환합니다."""
    risk, _reasons = classify_risk_with_reasons(text)
    return risk


def capsule_has_write_scope(capsule_path: str | Path | None) -> bool:
    """Capsule 파일에서 allowed_write_files 를 검사하여 쓰기 권한 유무를 반환합니다.

    allowed_write_files 가 비어 있으면 False, 하나 이상이면 True 를 반환합니다.
    파일 경로가 None 이거나 읽기/파싱에 실패하면 안전(fail-closed)을 위해 True 를 반환합니다.
    """
    if capsule_path is None:
        return True
    try:
        text = load_capsule(capsule_path)
        write_files = parse_capsule_list(text, "allowed_write_files")
        return len(write_files) > 0
    except Exception:
        return True


def free_pool_eligibility(
    role: str,
    risk: str,
    has_write_scope: bool,
) -> tuple[bool, str]:
    """무료 모델 풀 개방 조건을 검사합니다.

    개방 조건:
      1. 역할이 FREE_POOL_ELIGIBLE_ROLES 에 속함 (investigator)
      2. 위험도가 FREE_POOL_MAX_RISK 이하 (low)
      3. 쓰기 범위가 없음 (not has_write_scope)

    반환값: (eligible: bool, reason: str)
    모든 조건을 만족하면 (True, "무료 풀 개방 조건 충족") 을 반환하고,
    그렇지 않으면 (False, 거부 사유) 를 반환합니다.
    """
    if role not in FREE_POOL_ELIGIBLE_ROLES:
        eligible_roles_str = ", ".join(sorted(FREE_POOL_ELIGIBLE_ROLES))
        return False, f"무료 풀 개방 불가: 역할({role})이 무료 풀 개방 대상({eligible_roles_str})이 아닙니다."

    if risk != FREE_POOL_MAX_RISK:
        return False, f"무료 풀 개방 불가: 위험도({risk})가 허용 기준({FREE_POOL_MAX_RISK})을 초과합니다."

    if has_write_scope:
        return False, "무료 풀 개방 불가: 쓰기 권한(allowed_write_files)이 존재합니다."

    return True, "무료 풀 개방 조건 충족"


def classify_from_capsule(capsule_path: str | Path) -> dict[str, Any]:
    """Capsule 파일에서 objective, why_now, role 등을 읽어 위험도를 분류합니다."""
    capsule_text = load_capsule(capsule_path)
    objective = parse_capsule_scalar(capsule_text, "objective") or ""
    why_now = parse_capsule_scalar(capsule_text, "why_now") or ""
    role = parse_capsule_scalar(capsule_text, "role") or "builder"

    combined = f"{objective}\n{why_now}"
    risk, reasons = classify_risk_with_reasons(combined)
    return {
        "risk": risk,
        "role": role,
        "objective": objective[:100],
        "reasons": reasons,
    }


# ---------------------------------------------------------------------------
# 모델 선택 및 검증
# ---------------------------------------------------------------------------


def is_coordinator_model(model_or_pool: str) -> bool:
    """주어진 모델 ID 또는 풀 이름이 코디네이터 전용인지 확인합니다."""
    if model_or_pool in ("claude-opus-5", "claude-opus"):
        return True
    for pool_info in MODEL_POOL.values():
        if pool_info["id"] == model_or_pool and pool_info["tier"] == "coordinator":
            return True
    return False


def select_model(
    role: str,
    risk: str,
    exclude: list[str] | None = None,
    allow_free: bool = False,
    has_write_scope: bool = True,
) -> dict[str, Any]:
    """역할과 위험도에 따라 최적 모델을 선택합니다.

    자동 선택 대상 풀(auto_selectable=True) 중에서만 선택하며,
    allow_free 가 True 이고 무료 풀 개방 조건을 충족하는 경우에만
    FREE_POOL_ORDER 의 모델이 후보 맨 앞에 추가됩니다.
    코디네이터 전용 모델(claude-opus-5)은 절대 선택되지 않습니다.
    """
    exclude = exclude or []

    # 추론 등급은 위험도에 따라 내립니다. 예전에는 리뷰어와 빌더가 위험도를
    # 무시하고 항상 high 로 갔습니다. 2026-08-17 에 읽기 전용 low 위험도 감사
    # 4건이 전부 high 로 배정되어 주간 한도를 불필요하게 썼습니다.
    if role == "reviewer":
        if risk == "high":
            base_candidates = ["claude-sonnet", "gemini-flash-high"]
        elif risk == "medium":
            base_candidates = ["gemini-flash-high", "claude-sonnet"]
        else:
            base_candidates = ["gemini-flash-medium", "gemini-flash-high"]
    elif risk == "high":
        base_candidates = ["gemini-flash-high", "claude-sonnet"]
    elif role == "builder":
        # 코드를 쓰는 역할은 등급을 내리지 않습니다. 기계적 이동이라도 재수출
        # 위치와 순환 참조 판단이 들어가고, 틀린 코드를 되돌리는 비용이
        # 읽기 작업과 비교되지 않습니다. 내리려면 측정이 먼저입니다.
        base_candidates = ["gemini-flash-high", "claude-sonnet"]
    elif role in ("investigator", "benchmarker"):
        if risk == "low":
            base_candidates = ["gemini-flash-medium", "gemini-flash-high"]
        else:
            base_candidates = ["gemini-flash-high", "gemini-flash-medium"]
    elif role == "documenter":
        base_candidates = ["gemini-flash-medium", "gemini-flash-high"]
    else:
        base_candidates = ["gemini-flash-high", "gemini-flash-medium"]

    eligible, _reason = free_pool_eligibility(role, risk, has_write_scope)
    if allow_free and eligible:
        candidates = [c for c in FREE_POOL_ORDER if c in MODEL_POOL] + base_candidates
    else:
        candidates = base_candidates

    primary: str | None = None
    fallback: str | None = None
    for c in candidates:
        if c not in exclude:
            if primary is None:
                primary = c
            elif fallback is None:
                fallback = c
                break

    if primary is None:
        primary = "gemini-flash-high"

    primary_model = MODEL_POOL[primary]["id"]
    fallback_model = MODEL_POOL[fallback]["id"] if fallback and fallback in MODEL_POOL else None

    return {
        "primary_pool": primary,
        "primary_model": primary_model,
        "fallback_pool": fallback,
        "fallback_model": fallback_model,
        "risk": risk,
        "role": role,
    }


# ---------------------------------------------------------------------------
# 모델 가용성 probe 및 preflight
# ---------------------------------------------------------------------------


def load_repo_env(repo_root: Path | str | None = None) -> dict[str, str]:
    """저장소 루트의 .env 파일에서 환경변수를 표준 라이브러리로 파싱합니다.

    보안 규칙: 파싱된 키 값은 로그, 예외 메시지, 주석, 문서에 노출하지 않습니다.
    """
    target_dir = Path(__file__).resolve().parent.parent if repo_root is None else Path(repo_root)

    env_path = target_dir / ".env"
    if not env_path.is_file():
        return {}

    env_vars: dict[str, str] = {}
    try:
        content = env_path.read_text(encoding="utf-8")
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, val = line.partition("=")
                key = key.strip()
                val = val.strip()
                if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                    val = val[1:-1]
                if key:
                    env_vars[key] = val
    except Exception:
        return {}

    return env_vars


def build_probe_env(repo_root: Path | str | None = None) -> tuple[dict[str, str], list[str]]:
    """probe 실행 시 주입할 환경변수 딕셔너리와 환경변수 상태 메시지를 반환합니다.

    보안 규칙: API 키 값은 로그, 예외 메시지, stdout, 주석, 문서 중 어디에도 출력하지 않습니다.
    키가 없을 때는 값 대신 'CEREBRAS_API_KEY 미설정'이라는 사실만 알립니다.
    """
    env = os.environ.copy()
    status_messages: list[str] = []

    repo_env = load_repo_env(repo_root)
    cerebras_key = repo_env.get("CEREBRAS_API_KEY") or env.get("CEREBRAS_API_KEY")

    if cerebras_key:
        env["CEREBRAS_API_KEY"] = cerebras_key
    else:
        status_messages.append("CEREBRAS_API_KEY 미설정")

    return env, status_messages


def probe_model(
    model_id: str,
    timeout: int = 30,
    repo_root: Path | str | None = None,
) -> tuple[bool, str]:
    """모델이 실제로 호출 가능한지 확인합니다.

    반환값: (available: bool, detail: str)
    종료 코드 0을 1차 가용 근거로 판정하며, stderr 경고/안내가 있더라도 가용으로 인정합니다.
    비정상 종료 시에만 할당량 초과, 인증 실패 등의 원인을 상세 분류합니다.
    """
    provider = None
    for pool_name, pool_info in MODEL_POOL.items():
        if pool_info["id"] == model_id or pool_name == model_id:
            provider = pool_info["provider"]
            break

    if provider is None:
        if "gemini" in model_id.lower():
            provider = "gemini"
        elif "claude" in model_id.lower():
            provider = "claude"
        elif "codex" in model_id.lower():
            provider = "codex"
        elif "cerebras" in model_id.lower():
            provider = "cerebras"
        else:
            provider = "opencode"

    probe_info = PROBE_CONFIG.get(provider)
    if probe_info is None:
        return False, f"알 수 없는 provider: {provider}"

    probe_env, env_status = build_probe_env(repo_root)
    if provider == "cerebras" and "CEREBRAS_API_KEY 미설정" in env_status:
        return False, "probe 실패: CEREBRAS_API_KEY 미설정"

    cmd_template = probe_info["probe_cmd"]
    cmd = [arg.format(model=model_id) for arg in cmd_template]
    probe_timeout = probe_info.get("timeout", timeout)

    try:
        proc = subprocess.run(
            cmd,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=probe_timeout,
            check=False,
            env=probe_env,
        )
    except subprocess.TimeoutExpired:
        return False, f"probe 타임아웃 ({probe_timeout}초)"
    except FileNotFoundError:
        return False, f"실행 파일 없음: {cmd[0]}"

    if proc.returncode == 0:
        stdout_clean = proc.stdout.strip() if proc.stdout else ""
        if not stdout_clean:
            stderr_clean = proc.stderr.strip()[:200] if proc.stderr else "없음"
            return False, f"probe 실패: 응답 본문(stdout)이 비어 있습니다. (stderr: {stderr_clean})"

        if proc.stderr and proc.stderr.strip():
            stderr_lower = proc.stderr.lower()
            if "error:" in stderr_lower or "failed to" in stderr_lower:
                return False, f"probe 실패: 종료 코드는 0이나 stderr 오류 발생: {proc.stderr.strip()[:200]}"
            stderr_short = proc.stderr.strip().splitlines()[0][:100]
            return True, f"OK (종료 코드 0, {len(stdout_clean)}자, stderr: {stderr_short})"
        return True, f"OK (종료 코드 0, {len(stdout_clean)}자)"

    # 비정상 종료 시 원인 분류
    stderr_lower = proc.stderr.lower()
    stdout_lower = proc.stdout.lower()
    combined = f"{stderr_lower} {stdout_lower}"

    if any(k in combined for k in ("quota", "resource_exhausted", "429", "usage limit", "upgrade to pro")):
        detail = f"할당량 초과 (quota exceeded): {proc.stderr.strip()[:200]}"
    elif any(k in combined for k in ("unauthorized", "unauthenticated", "forbidden", "auth", "api_key", "wrong api key", "401", "403")):
        detail = f"인증 실패 (auth failed): {proc.stderr.strip()[:200]}"
    elif "not found" in combined or "no such file" in combined:
        detail = f"모델 또는 명령어 없음: {proc.stderr.strip()[:200]}"
    else:
        detail = f"probe 실패 (종료 코드 {proc.returncode}): {proc.stderr.strip()[:200]}"

    return False, detail


def preflight(
    model_id: str,
    timeout: int = 30,
    repo_root: Path | str | None = None,
) -> tuple[bool, list[str]]:
    """Dispatch 전 모델의 가용성과 정책 적합성을 검사합니다.

    확인 항목:
      1. 코디네이터 전용 모델 거부
      2. 등록된 풀 여부 확인
      3. 컨텍스트 한도 경고 (200,000 미만 또는 None)
      4. 모델 probe 호출 검증

    반환값: (passed: bool, warnings: list[str])
    """
    warnings: list[str] = []

    # 1. 코디네이터 모델 거부
    if is_coordinator_model(model_id):
        warnings.append(f"거부: 코디네이터 전용 모델({model_id})은 워커로 사용할 수 없습니다.")
        return False, warnings

    # 2. 등록 풀 확인
    found_pool: dict[str, Any] | None = None
    for pool_name, pool_info in MODEL_POOL.items():
        if pool_info["id"] == model_id or pool_name == model_id:
            found_pool = pool_info
            break

    if found_pool is None:
        warnings.append(f"경고: 등록되지 않은 모델 ID입니다: {model_id}")
    else:
        if found_pool["tier"] == "free":
            warnings.append("주의: 무료 모델 풀입니다. 임계 경로 작업에는 사용하지 마십시오.")
            if found_pool.get("max_tokens") is None:
                warnings.append(
                    f"주의: 선택된 모델({found_pool['id']})의 컨텍스트 한도가 확인되지 않았습니다. "
                    "Capsule 과 diff 를 작게 유지해야 합니다."
                )
            elif found_pool["max_tokens"] < 200_000:
                warnings.append(
                    f"주의: 선택된 모델({found_pool['id']})의 최대 컨텍스트({found_pool['max_tokens']} 토큰)가 200,000 미만입니다. "
                    "Capsule 과 diff 를 그 한도 안에 유지해야 합니다."
                )
        elif (
            found_pool.get("tier") == "secondary"
            and found_pool.get("max_tokens") is not None
            and found_pool["max_tokens"] < 200_000
        ):
            warnings.append(
                f"주의: 선택된 모델({found_pool['id']})의 최대 컨텍스트({found_pool['max_tokens']} 토큰)가 200,000 미만입니다. "
                "Capsule 과 diff 를 그 한도 안에 유지해야 합니다."
            )

    # 3. probe 검증
    available, detail = probe_model(model_id, timeout, repo_root)
    if not available:
        warnings.append(f"주 모델 {model_id} 사용 불가: {detail}")
        return False, warnings

    return True, warnings


# ---------------------------------------------------------------------------
# 라우팅 통합
# ---------------------------------------------------------------------------


def route(
    capsule_path: str | Path | None = None,
    role: str | None = None,
    risk: str | None = None,
    objective: str | None = None,
    why_now: str | None = None,
    probe: bool = True,
    probe_timeout: int = 30,
    explicit_model: str | None = None,
    allow_free: bool = False,
    has_write_scope: bool | None = None,
) -> RouteResult:
    """분류와 probe 를 종합하여 최종 워커 모델을 라우팅합니다."""
    reasons: list[str] = []
    if capsule_path:
        info = classify_from_capsule(capsule_path)
        risk = risk or info["risk"]
        role = role or info["role"]
        reasons = info.get("reasons", [])
        if has_write_scope is None:
            has_write_scope = capsule_has_write_scope(capsule_path)
    else:
        role = role or "builder"
        if risk is None:
            combined = f"{objective or ''}\n{why_now or ''}"
            risk, reasons = classify_risk_with_reasons(combined)
        if has_write_scope is None:
            has_write_scope = True

    warnings: list[str] = []
    if allow_free:
        eligible, reason = free_pool_eligibility(role, risk, has_write_scope)
        if not eligible:
            warnings.append(reason)

    if explicit_model:
        if is_coordinator_model(explicit_model):
            raise ValueError(f"코디네이터 전용 모델은 워커로 지정할 수 없습니다: {explicit_model}")
        primary_id = explicit_model
        fallback_id = None
    else:
        selection = select_model(
            role=role,
            risk=risk,
            allow_free=allow_free,
            has_write_scope=has_write_scope,
        )
        primary_id = selection["primary_model"]
        fallback_id = selection.get("fallback_model")

    # 무료 풀이 실제로 주 모델로 선택된 경우 재검증 의무 경고 추가
    primary_pool_info = None
    for pool_info in MODEL_POOL.values():
        if pool_info["id"] == primary_id:
            primary_pool_info = pool_info
            break

    if primary_pool_info and primary_pool_info["tier"] == "free":
        warnings.append("주의: 무료 모델 풀이 주 모델로 선택되었습니다. 산출물 재검증 필수이며 임계 경로 금지입니다.")
        if primary_pool_info.get("max_tokens") is None:
            warnings.append(
                f"주의: 선택된 모델({primary_pool_info['id']})의 컨텍스트 한도가 확인되지 않았습니다. "
                "Capsule 과 diff 를 작게 유지해야 합니다."
            )
        elif primary_pool_info["max_tokens"] < 200_000:
            warnings.append(
                f"주의: 선택된 모델({primary_pool_info['id']})의 최대 컨텍스트({primary_pool_info['max_tokens']} 토큰)가 200,000 미만입니다. "
                "Capsule 과 diff 를 그 한도 안에 유지해야 합니다."
            )
    elif (
        primary_pool_info
        and primary_pool_info.get("tier") == "secondary"
        and primary_pool_info.get("max_tokens") is not None
        and primary_pool_info["max_tokens"] < 200_000
    ):
        warnings.append(
            f"주의: 선택된 모델({primary_pool_info['id']})의 최대 컨텍스트({primary_pool_info['max_tokens']} 토큰)가 200,000 미만입니다. "
            "Capsule 과 diff 를 그 한도 안에 유지해야 합니다."
        )

    primary_available = True
    fallback_available = None

    if probe:
        primary_ok, p_warnings = preflight(primary_id, timeout=probe_timeout)
        primary_available = primary_ok
        warnings.extend(p_warnings)

        if not primary_ok and fallback_id:
            fb_ok, fb_warnings = preflight(fallback_id, timeout=probe_timeout)
            fallback_available = fb_ok
            warnings.extend(fb_warnings)
            if fb_ok:
                warnings.append(f"대체 모델 {fallback_id} 로 전환합니다.")

    return RouteResult(
        risk=risk,
        role=role,
        primary_model=primary_id,
        fallback_model=fallback_id,
        primary_available=primary_available,
        fallback_available=fallback_available,
        reasons=reasons,
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
    cls.add_argument(
        "--allow-free",
        action="store_true",
        help="저가·무료 모델 풀 조건부 개방 (쓰기 권한 없는 investigator 및 low 위험도 전용)",
    )
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
    rt.add_argument("--model", help="명시적 모델 ID 지정")
    rt.add_argument(
        "--allow-free",
        action="store_true",
        help="저가·무료 모델 풀 조건부 개방 (쓰기 권한 없는 investigator 및 low 위험도 전용)",
    )
    rt.add_argument("--no-probe", action="store_true", help="probe 생략")
    rt.add_argument("--probe-timeout", type=int, default=30, help="probe 타임아웃 (초)")
    rt.add_argument("--json", action="store_true", help="JSON 출력")

    # list
    sub.add_parser("list", help="등록된 모델 풀을 출력합니다.")

    return parser


def cmd_classify(args: argparse.Namespace) -> int:
    reasons: list[str] = []
    allow_free = getattr(args, "allow_free", False)
    if args.capsule:
        info = classify_from_capsule(args.capsule)
        risk = info["risk"]
        role = info["role"]
        objective = info["objective"]
        reasons = info.get("reasons", [])
        has_write_scope = capsule_has_write_scope(args.capsule)
    else:
        objective = args.objective or ""
        why_now = args.why_now or ""
        role = args.role or "builder"
        combined = f"{objective}\n{why_now}"
        risk, reasons = classify_risk_with_reasons(combined)
        has_write_scope = True

    selection = select_model(
        role=role,
        risk=risk,
        allow_free=allow_free,
        has_write_scope=has_write_scope,
    )

    if args.json:
        print(json.dumps({
            "risk": risk,
            "role": role,
            "primary_model": selection["primary_model"],
            "primary_pool": selection["primary_pool"],
            "fallback_model": selection.get("fallback_model"),
            "fallback_pool": selection.get("fallback_pool"),
            "reasons": reasons,
        }, ensure_ascii=False, indent=2))
    else:
        print(f"위험도:       {risk}")
        print(f"역할:         {role}")
        print(f"주 모델:      {selection['primary_model']} ({selection['primary_pool']})")
        if selection.get("fallback_model"):
            print(f"대체 모델:    {selection['fallback_model']} ({selection['fallback_pool']})")
        if reasons:
            print(f"판정 근거:    {', '.join(reasons)}")
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
    try:
        result = route(
            capsule_path=args.capsule,
            role=args.role,
            risk=args.risk,
            objective=args.objective,
            why_now=args.why_now,
            probe=not args.no_probe,
            probe_timeout=args.probe_timeout,
            explicit_model=args.model,
            allow_free=getattr(args, "allow_free", False),
        )
    except ValueError as exc:
        if args.json:
            print(json.dumps({"error": str(exc)}, ensure_ascii=False, indent=2))
        else:
            print(f"오류: {exc}", file=sys.stderr)
        return 1

    recommended = (
        result.fallback_model
        if not result.primary_available and result.fallback_available
        else result.primary_model
    )

    if args.json:
        print(json.dumps({
            "risk": result.risk,
            "role": result.role,
            "primary_model": result.primary_model,
            "primary_available": result.primary_available,
            "fallback_model": result.fallback_model,
            "fallback_available": result.fallback_available,
            "reasons": result.reasons,
            "warnings": result.warnings,
            "recommended": recommended,
        }, ensure_ascii=False, indent=2))
    else:
        print(f"위험도:        {result.risk}")
        print(f"역할:          {result.role}")
        print(f"주 모델:       {result.primary_model} {'(사용 가능)' if result.primary_available else '(사용 불가)'}")
        if result.fallback_model:
            fb_status = "(사용 가능)" if result.fallback_available else "(사용 불가)" if result.fallback_available is not None else "(미확인)"
            print(f"대체 모델:     {result.fallback_model} {fb_status}")
        if result.reasons:
            print(f"판정 근거:     {', '.join(result.reasons)}")
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

    has_available = result.primary_available or bool(result.fallback_available)
    has_coordinator_warning = any("코디네이터 전용" in w for w in result.warnings)
    return 0 if has_available and not has_coordinator_warning else 1


def cmd_list(args: argparse.Namespace) -> int:
    print("등록된 모델 풀:")
    print("-" * 80)
    for pool_name, info in MODEL_POOL.items():
        tier_label = {
            "primary": "주력",
            "secondary": "보조",
            "coordinator": "코디네이터",
            "free": "무료",
        }.get(info["tier"], info["tier"])
        auto_status = "대상" if info.get("auto_selectable", False) else "비대상"
        if info["tier"] == "coordinator":
            auto_status += " (코디네이터 전용 - 워커 사용 불가)"
        elif not info.get("auto_selectable", False):
            auto_status += " (수동 지정 전용)"

        print(f"  {pool_name} ({tier_label})")
        print(f"    ID:        {info['id']}")
        print(f"    Provider:  {info['provider']}")
        print(f"    자동 선택: {auto_status}")
        print(f"    용도:      {', '.join(info['suitable_for']) or '워커 사용 불가'}")
        print(f"    비고:      {info['notes']}")
        print()
    print("안내: 무료 풀(opencode-free)은 --allow-free 지정 시 쓰기 권한 없는 low 위험도 조사(investigator) 역할에 한해 조건부로 개방됩니다.")
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

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
  - Codex           : 코디네이터 전용 (gpt-5.6-terra, effort medium). 기본값 변경 시
                      사용자에게 MODEL_CHANGE_NOTICE 를 먼저 보냅니다. 워커 사용 금지.
  - Claude 구독     : 예비 코디네이터. 워커 사용 금지.
  - Gemini Flash    : 주력 워커. 추론 등급은 공식 문서 기준으로 위험도에 따라 배정합니다.
                      medium 이 기본값이며 복잡한 코드와 에이전트 용도에 권장됩니다.
                      high 는 가장 어려운 작업 전용, low 는 초안과 빠른 분석용입니다.
  - Claude 계열     : 별도 풀 (claude-sonnet-5). 판정 품질이 필요한 작업 및 수동 보조 워커.
  - OpenCode 무료   : 실패해도 손실 없는 병렬 조사. 임계 경로 금지.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import shutil
import subprocess  # nosec B404 - 개발 스크립트가 고정 인자 목록으로만 외부 도구를 호출합니다
import sys
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Any, Protocol, cast

try:
    from scripts._strict_json import dump_strict_json
    from scripts.orca_contract import load_capsule, parse_capsule_list, parse_capsule_scalar
except (ModuleNotFoundError, ImportError):
    _repo_root = Path(__file__).resolve().parent.parent
    if str(_repo_root) not in sys.path:
        sys.path.insert(0, str(_repo_root))
    from scripts._strict_json import dump_strict_json
    from scripts.orca_contract import load_capsule, parse_capsule_list, parse_capsule_scalar

__all__ = [
    "FREE_BUILDER_ORDER",
    "FREE_INVESTIGATOR_ORDER",
    "FREE_ORDER_BY_ROLE",
    "FREE_POOL_ELIGIBLE_ROLES",
    "FREE_POOL_MAX_RISK",
    "FREE_POOL_ORDER",
    "INVENTORY_MISSING_THRESHOLD",
    "MODEL_POOL",
    "MODEL_PROVIDER_PREFIXES",
    "PROBE_CONFIG",
    "RELIABILITY_DEMOTE_RATE",
    "RELIABILITY_MIN_OBSERVATIONS",
    "RELIABILITY_SUSPEND_CONSECUTIVE",
    "RELIABILITY_WINDOW",
    "RISK_KEYWORDS",
    "TIER_POLICY",
    "ModelRoutingError",
    "RouteResult",
    "apply_inventory_history",
    "apply_reliability_history",
    "build_probe_env",
    "capsule_has_write_scope",
    "classify_from_capsule",
    "classify_risk",
    "classify_risk_with_reasons",
    "cmd_classify",
    "cmd_list",
    "cmd_probe",
    "cmd_route",
    "free_order_for_role",
    "free_pool_eligibility",
    "is_coordinator_model",
    "load_inventory_history",
    "load_reliability_history",
    "load_repo_env",
    "main",
    "pool_for_model",
    "preflight",
    "probe_model",
    "provider_for_model",
    "record_reliability_outcome",
    "resolve_kimi_bin",
    "route",
    "select_model",
]

# ---------------------------------------------------------------------------
# kimi 실행 파일 경로 해석
# ---------------------------------------------------------------------------


def resolve_kimi_bin() -> str:
    """kimi 실행 파일 경로를 해석합니다.

    우선순위: KIMI_BIN 환경변수 -> PATH 탐색(shutil.which) -> 홈 기준 기본 경로.
    어느 후보도 파일로 존재하지 않으면 마지막 후보 경로 문자열을 그대로 돌려줍니다.
    """
    env_bin = os.environ.get("KIMI_BIN", "").strip()
    if env_bin:
        return env_bin
    which_bin = shutil.which("kimi")
    if which_bin:
        return which_bin
    return str(Path.home() / ".kimi-code" / "bin" / "kimi")


# ---------------------------------------------------------------------------
# 프로바이더별 probe 설정
# ---------------------------------------------------------------------------

# 종료 코드 0 으로 끝내면서 본문에 오류를 적는 CLI 를 걸러내는 표지입니다.
# 이 목록에 걸리면 probe 는 fail-closed 로 사용 불가 판정합니다. 현재 등록된
# CLI 중 이 경로가 필요한 것은 없으며, 향후 등록을 대비한 보강입니다.
STDOUT_ERROR_MARKERS: tuple[str, ...] = (
    "[api error",
    "api error:",
    "incorrect api key",
    "invalid api key",
    "unauthorized",
    "model not found",
)


PROBE_CONFIG: dict[str, dict[str, Any]] = {
    "gemini": {
        "probe_cmd": ["agy", "--model", "{model}", "--print", "ping", "--print-timeout", "15s"],
        "timeout": 20,
    },
    "claude": {
        "probe_cmd": ["agy", "--model", "{model}", "--print", "ping", "--print-timeout", "15s"],
        "timeout": 20,
    },
    "claude-cli": {
        # 로컬 Claude Code CLI 전용 probe 설정.
        # claude -p ping --model {model} --effort medium --output-format json --tools "" --no-session-persistence --safe-mode
        "probe_cmd": [
            "claude",
            "-p",
            "ping",
            "--model",
            "{model}",
            "--effort",
            "medium",
            "--output-format",
            "json",
            "--tools",
            "",
            "--no-session-persistence",
            "--safe-mode",
        ],
        "timeout": 30,
    },
    "opencode": {
        # 15초는 콜드스타트에 짧아 살아 있는 모델도 사용 불가로 판정됐습니다.
        "probe_cmd": ["opencode", "run", "--model", "{model}", "ping"],
        "timeout": 60,
    },
    "codex": {
        "probe_cmd": ["codex", "exec", "ping"],
        "timeout": 30,
    },
    "cerebras": {
        "probe_cmd": ["opencode", "run", "--model", "{model}", "ping"],
        "timeout": 20,
    },
    "cursor": {
        # --mode plan 은 읽기 전용이라 probe 가 저장소를 건드리지 않습니다.
        "probe_cmd": ["cursor-agent", "-p", "--model", "auto", "--mode", "plan", "ping"],
        "timeout": 60,
    },
    "qwen": {
        # Qwen Code CLI 는 Alibaba Token Plan 자격증명으로 동작합니다. -p 는 단발
        # 실행이라 probe 가 대화형으로 남지 않습니다. Token Plan 은 대화형 코딩
        # 도구용이므로 probe 도 사람이 쓰는 것과 같은 CLI 경로를 씁니다.
        "probe_cmd": ["qwen", "-m", "{model}", "-p", "ping"],
        "timeout": 90,
    },
    "kimi-openrouter": {
        # resolve_kimi_bin() 으로 경로를 해석합니다. -p 는 단발 실행이라
        # probe 가 대화형으로 남지 않습니다. 무료 풀이라 콜드스타트가 깁니다.
        "probe_cmd": [
            resolve_kimi_bin(),
            "-m",
            "{model}",
            "-p",
            "ping",
        ],
        "timeout": 120,
    },
    "grok": {
        # SuperGrok 로컬 Grok CLI 전용 probe 설정.
        # grok -p ping --model {model} --output-format plain
        "probe_cmd": [
            "grok",
            "-p",
            "ping",
            "--model",
            "{model}",
            "--output-format",
            "plain",
        ],
        "timeout": 60,
    },
}

# ---------------------------------------------------------------------------
# 등록된 모델 풀
# ---------------------------------------------------------------------------

MODEL_POOL: dict[str, dict[str, Any]] = {
    "gemini-flash-high": {
        "id": "gemini-3.8-flash-high",
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
        "notes": "Gemini 3.8 Flash 공식 문서 기준 가장 어려운 추론·코딩 전용. high 위험도에만 배정한다. 토큰 소모가 크다.",
    },
    "gemini-flash-medium": {
        "id": "gemini-3.8-flash-medium",
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
        "notes": "Gemini 3.8 Flash 공식 문서 기준 기본값이며 복잡한 코드와 에이전트 용도에 권장되는 등급. medium 위험도 이하의 주력 워커.",
    },
    "gemini-flash-low": {
        "id": "gemini-3.8-flash-low",
        "provider": "gemini",
        "tier": "primary",
        "auto_selectable": True,
        "max_tokens": 1_000_000,
        "suitable_for": [
            "investigator",
            "benchmarker",
            "documenter",
        ],
        "notes": "Gemini 3.8 Flash 공식 문서 기준 용도는 지연이 중요한 작업, 초안 작성, 빠른 데이터 분석. low 위험도 문서화·조사·계측에만 자동 선택된다. 리뷰어와 빌더에는 배정하지 않는다.",
    },
    "gemini-3.7-flash-high": {
        "id": "gemini-3.7-flash-high",
        "provider": "gemini",
        "tier": "secondary",
        "auto_selectable": False,
        "max_tokens": 1_000_000,
        "suitable_for": [
            "builder",
            "reviewer",
            "investigator",
            "benchmarker",
            "documenter",
        ],
        "notes": "Gemini 3.7 Flash 수동 지정 전용. 3.8 롤백 및 비교 검증용.",
    },
    "gemini-3.7-flash-medium": {
        "id": "gemini-3.7-flash-medium",
        "provider": "gemini",
        "tier": "secondary",
        "auto_selectable": False,
        "max_tokens": 1_000_000,
        "suitable_for": [
            "builder",
            "reviewer",
            "investigator",
            "benchmarker",
            "documenter",
        ],
        "notes": "Gemini 3.7 Flash 수동 지정 전용. 3.8 롤백 및 비교 검증용.",
    },
    "gemini-3.7-flash-low": {
        "id": "gemini-3.7-flash-low",
        "provider": "gemini",
        "tier": "secondary",
        "auto_selectable": False,
        "max_tokens": 1_000_000,
        "suitable_for": [
            "investigator",
            "benchmarker",
            "documenter",
        ],
        "notes": "Gemini 3.7 Flash 수동 지정 전용. 3.8 롤백 및 비교 검증용.",
    },
    # ------------------------------------------------------------------
    # Alibaba Token Plan (Qwen Code CLI) 풀
    # ------------------------------------------------------------------
    # 2026-08-30 에 이 저장소의 Qwen Code v0.22.3 로 여섯 개 ID 를 직접 probe 했습니다.
    # 응답한 것은 qwen3.7-plus, deepseek-v4-pro, glm-5.2, qwen3.7-max,
    # qwen3.8-max-preview 입니다. qwen3.8-max 와 qwen3.8-flash 는 401 을 돌려주므로
    # 등록하지 않습니다. 공개 문서가 qwen3.8-max-preview 를 qwen3.8-max 로 라우팅한다고
    # 적고 있으나, 이 계정에서 실제로 동작하는 ID 는 preview 쪽입니다.
    "qwen-plus": {
        "id": "qwen3.7-plus",
        "provider": "qwen",
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
        "notes": "Alibaba Token Plan 에서 유일하게 자동 배정되는 모델. 리뷰어 주 모델이며, 빌더가 gemini 계열인 동안 다른 계열로 독립 검토를 맡는다. 빌더·조사·계측에는 gemini 할당량이 소진됐을 때 fallback 으로 들어간다.",
    },
    "deepseek-pro": {
        "id": "deepseek-v4-pro",
        "provider": "qwen",
        "tier": "primary",
        "auto_selectable": False,
        "max_tokens": 1_000_000,
        "suitable_for": [
            "builder",
            "investigator",
            "benchmarker",
        ],
        "notes": "복잡한 SQL·RAG·레이턴시 회귀 원인 분석 전문. Alibaba Token Plan 잔량이 크지 않아 자동 배정에서 제외한다. qwen-plus 가 두 번 실패했거나 원인 분석이 막혔을 때 --model 로 명시 지정하고 WORKER_MODEL_NOTICE 를 남긴다.",
    },
    "glm": {
        "id": "glm-5.2",
        "provider": "qwen",
        "tier": "primary",
        "auto_selectable": False,
        "max_tokens": 1_000_000,
        "suitable_for": [
            "reviewer",
            "investigator",
            "documenter",
        ],
        "notes": "독립 리뷰어. Alibaba Token Plan 잔량 보호를 위해 자동 배정에서 제외한다. 리뷰어 자동 배정은 별도 할당량인 gemini 계열이 맡으며, 빌더와 다른 계열이라는 조건은 그대로 지켜진다. 교차검토가 특별히 필요할 때만 명시 지정한다.",
    },
    "qwen-max": {
        "id": "qwen3.8-max-preview",
        "provider": "qwen",
        "tier": "secondary",
        "auto_selectable": False,
        "max_tokens": 1_000_000,
        "suitable_for": [
            "builder",
            "reviewer",
            "investigator",
        ],
        "notes": "escalation 전용이며 자동 배정하지 않는다. 다른 워커가 실패했거나 두 워커의 결론이 충돌할 때만 명시 지정한다. G1·G3·병합·컷오버 최종 판정은 코디네이터 몫이며 이 모델에 위임하지 않는다.",
    },
    "qwen-max-legacy": {
        "id": "qwen3.7-max",
        "provider": "qwen",
        "tier": "secondary",
        # 공급자가 legacy 로 옮기고 권장하지 않는다고 표시했으며, 상위 세대인
        # qwen3.8-max-preview 보다 단가가 높고 처리량 한도는 낮습니다. probe 는
        # 통과하지만 신규 자동 배정에서 제외합니다.
        "auto_selectable": False,
        "max_tokens": 256_000,
        "suitable_for": [],
        "notes": "legacy. 신규 자동 배정에서 제외한다. --model 로 명시 지정할 때만 쓰이며 그때도 경고가 남는다.",
    },
    "claude-sonnet": {
        "id": "claude-sonnet-5",
        "provider": "claude",
        "probe_provider": "claude-cli",
        "tier": "secondary",
        "auto_selectable": True,
        "max_tokens": 1_000_000,
        "suitable_for": [
            "reviewer",
            "builder",
        ],
        "notes": (
            "로컬 Claude Pro 전용 풀 (/opt/homebrew/bin/claude). "
            "canonical model claude-sonnet-5, context 1M, effort medium. "
            "WORKER_MODEL_NOTICE 후 명시 배정하는 수동 보조 워커."
        ),
    },
    "grok-4.6": {
        "id": "grok-4.6",
        "provider": "grok",
        "probe_provider": "grok",
        "tier": "secondary",
        "auto_selectable": False,
        "max_tokens": 1_000_000,
        "worker_efforts": ["medium", "low"],
        "coordinator_efforts": ["high"],
        "default_effort": "medium",
        "suitable_for": [
            "reviewer",
            "builder",
            "investigator",
        ],
        "notes": (
            "SuperGrok 구독 기반 로컬 Grok CLI (/opt/homebrew/bin/grok). "
            "effort high 는 코디네이터 등급으로 워커 자동 배정에서 제외한다. "
            "워커 등급은 medium 과 low 다. "
            "WORKER_MODEL_NOTICE 후 명시 배정으로만 사용한다."
        ),
    },
    "grok-4.5": {
        "id": "grok-4.5",
        "provider": "grok",
        "probe_provider": "grok",
        "tier": "secondary",
        "auto_selectable": False,
        "max_tokens": 1_000_000,
        "worker_efforts": ["medium", "low"],
        "coordinator_efforts": ["high"],
        "default_effort": "medium",
        "suitable_for": [
            "reviewer",
            "builder",
            "investigator",
        ],
        "notes": (
            "SuperGrok 구독 기반 로컬 Grok CLI (/opt/homebrew/bin/grok). "
            "grok-4.5 워커 모델. "
            "WORKER_MODEL_NOTICE 후 명시 배정으로만 사용한다."
        ),
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
        # 주 코디네이터의 예비 모델입니다. 구독 한도 여유가 있을 때만 수동으로
        # 전환하며 워커로는 사용하지 않습니다.
        "tier": "coordinator_reserve",
        "auto_selectable": False,
        "max_tokens": 200_000,
        "suitable_for": [],
        "notes": "예비 코디네이터. 한도 여유가 있을 때만 수동 지정. 워커로 사용하지 않습니다.",
    },
    "codex": {
        "id": "gpt-5.6-terra",
        "provider": "codex",
        # 기본 코디네이터는 Terra Medium입니다. Sol High는 데이터 무손실,
        # 컷오버 및 복잡한 병합 판정에 한해 수동으로 일시 승격합니다.
        "tier": "coordinator",
        "auto_selectable": False,
        "max_tokens": None,
        "default_effort": "medium",
        "notify_user_on_override": True,
        # 코디네이터는 워커 역할을 겸하지 않습니다. 자기 자신에게 배정하면
        # 위임으로 토큰이 줄지 않습니다.
        "suitable_for": [],
        "notes": (
            "코디네이터 전용 (gpt-5.6-terra, effort medium). 기본값 변경 전 "
            "MODEL_CHANGE_NOTICE가 필요합니다. Sol High는 사용자 승인 후 고위험 "
            "최종 판정에만 수동 사용합니다. 워커로 사용하지 않습니다."
        ),
    },
    "cursor-auto": {
        "id": "cursor-agent/auto",
        "provider": "cursor",
        "tier": "free",
        "auto_selectable": False,
        "max_tokens": None,
        "suitable_for": [
            "investigator",
            "builder",
        ],
        "notes": (
            "Cursor CLI 의 Auto 라우터. Hobby(무료) 등급에서 사용량 제한 하에 쓸 수 있다. "
            "요청마다 적합한 모델로 넘기므로 어느 모델이 처리했는지 사후 확정할 수 없어 "
            "reviewer 에는 배정하지 않는다. --mode plan 이 도구 차원에서 읽기 전용을 "
            "강제하는 것이 유일한 강점이다. 기동은 "
            "cursor-agent -p --model auto [--mode plan | --force] 형식이며 프롬프트는 "
            "stdin 으로 넣는다(인자로 주면 무시된다). "
            "2026-08-18 실측에서 5회 중 3회가 출력 없이 종료 코드 0 으로 끝났다. "
            "빈 출력을 결과 없음으로 읽지 말고 실패로 취급한다. 주력은 deepseek 이다."
        ),
    },
    "opencode-deepseek": {
        "id": "opencode/deepseek-v4-flash-free",
        "provider": "opencode",
        "tier": "free",
        "auto_selectable": False,
        "max_tokens": 1_000_000,
        "suitable_for": [
            "investigator",
            "builder",
        ],
        "notes": (
            "무료 풀에서 builder 를 받는 유일한 항목이다. 공식 발표 기준 "
            "컨텍스트 1M, 추론 모드 3단(Non-think / Think High / Think Max)이며 "
            "Think Max 는 384K 이상 권장. 벤더 자체 수치이므로 산출물은 반드시 "
            "재검증한다. reviewer 는 병합 판정에 직결되어 배정하지 않는다. "
            "2026-08-20 에 일시적으로 `Model not found` 가 나고 `opencode models` "
            "목록에서도 빠졌다가 같은 날 복구됐다. **목록 이탈과 삭제는 다르며, "
            "재시도 없이 제외 판정을 내리지 않는다.**"
        ),
    },
    "opencode-free": {
        "id": "opencode/nemotron-3.5-lightning-free",
        "provider": "opencode",
        "tier": "free",
        "auto_selectable": False,
        "max_tokens": None,
        # 2026-08-20 builder 경합에서 4.8KB Capsule 을 주자 다국어 토큰이
        # 무작위로 섞인 무의미 출력을 냈습니다. 도구 호출 0건, 파일 변경 0건.
        # 짧은 지시("OK 만 답하라", "2+2")에는 정상 응답하므로 probe 로는
        # 걸러지지 않습니다. 재시행도 2분 무응답이었습니다.
        #
        # 격리(quarantine)입니다. 영구 판정이 아니라 2회 관측에 근거한 배정
        # 중단이며, 재시험하려면 benchmarks/free_workers 를 다시 돌리십시오.
        # 이력을 남기려고 항목 자체는 지우지 않습니다.
        "suitable_for": [],
        "notes": (
            "배정 금지. 2026-08-20 실측에서 4.8KB 지시문에 무의미 출력. "
            "짧은 입력에는 정상 응답하므로 probe 통과. 장문 붕괴형."
        ),
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
            "2026-08-18 공식 문서 확인으로 정정. Cerebras 무료 등급 제약은 "
            "분당 요청 5회(RPM), 분당 30K 토큰, 시간·일 1M 토큰이다. 종전 기록은 "
            "이를 컨텍스트나 TPM 단일 원인으로 적어 '파일 수를 줄여도 해소되지 "
            "않는다' 는 틀린 결론을 남겼다. 실제 병목은 RPM 5 이며 도구 호출 하나에 "
            "12초가 걸리는 셈이라 에이전트 루프가 사실상 정지한다. "
            "모델 자체는 컨텍스트 256K, 도구 사용 지원, 코드 생성 중위권이다. "
            "따라서 도구 호출이 손에 꼽는 작업에만 배정한다."
        ),
    },
    "or-free-minimax-m3": {
        "id": "or-free/minimax-m3",
        "provider": "kimi-openrouter",
        "tier": "free",
        "auto_selectable": False,
        "max_tokens": 1_048_576,
        # 2026-09-02 읽기 전용 probe 통과. 쓰기 과제 실측 이력은 아직 없다.
        "suitable_for": [
            "investigator",
        ],
        "notes": (
            "OpenRouter minimax/minimax-m3:free. kimi 프로필에는 정의돼 있었으나 "
            "풀에 등록되지 않아 라우터가 보지 못했다. 2026-09-02 probe 로 가용성만 "
            "확인했고 컨텍스트 1,048,576 에 thinking 과 tool_use 를 선언한다. "
            "2026-08-20 쓰기 경합에 참여하지 않았으므로 builder 는 아직 열지 "
            "않는다. 쓰기 과제 실측 후 다른 무료 항목과 같은 기준으로 판정하라."
        ),
    },
    "or-free-nemotron-ultra": {
        "id": "or-free/nemotron-ultra",
        "provider": "kimi-openrouter",
        "tier": "free",
        "auto_selectable": False,
        "max_tokens": 1_000_000,
        # 2026-08-20 builder 경합 통과. 12분32초, 중립 시나리오 8/8, 테스트 10건.
        "suitable_for": [
            "investigator",
            "builder",
        ],
        "notes": (
            "OpenRouter nvidia/nemotron-3-ultra-550b-a55b:free. 무료 풀에서 문맥이 "
            "가장 크므로 장문 감사에 먼저 붙인다. 2026-08-20 게이트 도구 감사 "
            "6문항 6/6, 57초. reasoning_effort 를 받는 유일한 무료 항목이다."
        ),
    },
    "or-free-laguna-s": {
        "id": "or-free/laguna-s",
        "provider": "kimi-openrouter",
        "tier": "free",
        "auto_selectable": False,
        "max_tokens": 262_144,
        # 2026-08-20 builder 경합 격리(quarantine). 32분간 379KB 를 출력하는
        # 동안 도구 호출 0건, 파일 변경 0건. 사양 모순을 정확히 인지하고
        # escalation 을 결정한 뒤 매번 재검토로 되돌아갔습니다.
        #
        # 1회 관측이고, 그 회차의 Capsule 에는 만족 불가능한 acceptance 가
        # 하나 섞여 있었습니다(코디네이터 작성 오류). kimi -p 는 one-shot 이라
        # 코디네이터 회신을 받기도 어려웠습니다. 영구 판정으로 읽지 마십시오.
        # 재시험 전까지 배정만 중단합니다.
        "suitable_for": [],
        "notes": (
            "OpenRouter poolside/laguna-s-2.1:free. 2026-08-20 감사 6/6, 26초. "
            "읽기 전용 probe 에서 지시 형식을 정확히 지켰다."
        ),
    },
    "or-free-laguna-xs": {
        "id": "or-free/laguna-xs",
        "provider": "kimi-openrouter",
        "tier": "free",
        "auto_selectable": False,
        "max_tokens": 262_144,
        # 2026-08-20 builder 경합 통과. 11분03초, 중립 시나리오 8/8, 테스트 11건.
        # 핵심 불변식을 두 테스트로 쪼개 커버한 유일한 구현이라 산출물이 채택됐습니다.
        "suitable_for": [
            "investigator",
            "builder",
        ],
        "notes": (
            "OpenRouter poolside/laguna-xs-2.1:free. 2026-08-20 감사 6/6, 15초로 "
            "가장 빠르다. 다만 worker_done 의 --from 핸들을 한 번 틀렸다가 오류 "
            "메시지를 보고 자가 복구했다. 절차 실수를 감독으로 잡을 수 있는 "
            "작업에만 붙인다."
        ),
    },
    "opencode-nemotron3-ultra": {
        "id": "opencode/nemotron-3-ultra-free",
        "provider": "opencode",
        "tier": "free",
        "auto_selectable": False,
        "max_tokens": None,
        # 2026-09-02 배정 보류. E3 관측성 조사에서 컨텍스트 15% 를 쓰는 동안
        # 산출물이 0 이었고 codex 로 교체했다. 무료 풀 전반이 한 과제에
        # 9분에서 14분을 쓰는데, 코디네이터가 하나뿐인 조율에서는 그 대기가
        # 전체 웨이브를 늦춘다. 시간이 여유로운 병렬 조사에만 붙인다.
        # 2026-08-20 builder 경합 1위. 9분01초로 전체 최속, 중립 시나리오 8/8,
        # 테스트 9건. 그전까지 MODEL_POOL 에 등록조차 되어 있지 않았습니다.
        "suitable_for": [
            "investigator",
            "builder",
        ],
        "notes": (
            "무료 풀 1순위. 2026-08-20 쓰기 과제 실측 9분01초. "
            "컨텍스트 한도 미확인이므로 Capsule 과 diff 를 작게 유지하십시오."
        ),
    },
    "opencode-mimo": {
        "id": "opencode/mimo-v2.5-free",
        "provider": "opencode",
        "tier": "free",
        "auto_selectable": False,
        "max_tokens": None,
        # 2026-08-20 builder 경합 통과. 13분58초, 중립 시나리오 8/8, 테스트 9건.
        # 역시 미등록 상태였습니다.
        "suitable_for": [
            "investigator",
            "builder",
        ],
        "notes": (
            "2026-08-20 쓰기 과제 실측 13분58초 통과. "
            "컨텍스트 한도 미확인이므로 Capsule 과 diff 를 작게 유지하십시오."
        ),
    },
    "or-free-north-mini": {
        "id": "or-free/north-mini",
        "provider": "kimi-openrouter",
        "tier": "free",
        "auto_selectable": False,
        "max_tokens": 256_000,
        # 2026-08-20 builder 경합 격리(quarantine). 31분50초 시점에 스크립트
        # 70줄만 쓰고 테스트 미착수, 커밋 0건. 산출물 방향은 맞았습니다.
        #
        # 실격선 28분은 결과를 본 뒤 정한 사후 기준이라 능력 미달 근거로는
        # 약합니다. "이 벤치마크의 throughput 기준 부적합" 으로 읽으십시오.
        # 재시험 시에는 실격선을 시작 전에 정해 Capsule 에 적어야 합니다.
        "suitable_for": [],
        "notes": (
            "OpenRouter cohere/north-mini-code:free. 2026-08-20 감사 6/6 이나 "
            "86초로 가장 느리고, 출력 형식의 자리표시자를 그대로 남겼다. "
            "형식을 기계로 파싱하는 작업에는 붙이지 않는다."
        ),
    },
}

# ---------------------------------------------------------------------------
# 무료/저가 풀 개방 정책 상수
# ---------------------------------------------------------------------------

# reviewer 는 판정이 병합 결정에 직결되므로 개방하지 않습니다. builder 는
# 산출물이 Level 1 게이트와 테스트를 거쳐 코디네이터가 병합을 결정하므로
# 개방합니다. 무료 모델이 틀리면 손실은 시간이지 저장소가 아닙니다.
# ---------------------------------------------------------------------------
# OpenRouter 무료 풀 (Kimi Code 경유)
# ---------------------------------------------------------------------------
#
# 2026-08-20 Run run_a32b6b614996 에서 네 모델 모두 Orca 읽기 전용 worker 경로
# (dispatch --return-preamble -> kimi -p)를 완주했고, 이어서 1,111줄 게이트 도구
# 감사 6문항을 4종 동시 실행으로 물려 전부 6/6 정답이었습니다.
#
# **정확도로는 네 모델이 변별되지 않았습니다.** 갈린 축은 응답 시간과 지시 형식
# 준수뿐입니다. 따라서 아래 배정 차이는 능력 등급이 아니라 문맥 크기와 속도에
# 근거합니다. 더 어려운 과제로 재측정하기 전에는 등급 차이를 주장하지 않습니다.
#
# 네 모델 모두 kimi -p 단발 실행이라 대화형 재개와 다단계 감독이 불가능하고,
# 검증이 읽기 전용 범위에서만 이루어져 builder 는 부여하지 않습니다.

FREE_POOL_ELIGIBLE_ROLES: frozenset[str] = frozenset({"investigator", "builder"})
FREE_POOL_MAX_RISK: str = "low"
# 2026-08-20 재정렬. opencode-deepseek 은 같은 날 일시적으로 호출이 거부돼
# 뺐다가, 복구를 확인하고 원래 자리로 되돌렸습니다. 무료 풀에서 builder 를
# 받는 유일한 항목이라 1순위를 유지합니다. 앞의 세 자리는 같은 날 감사 6문항을 6/6 으로 통과한
# 모델이고, 그 뒤는 이 과제로 측정하지 않은 항목입니다.
#
# **정확도로 순위를 매긴 것이 아닙니다.** 측정된 네 모델이 전부 만점이라
# 변별되지 않았고, 순서는 문맥 크기와 응답 시간, 형식 준수에 따릅니다.
# 2026-08-20 builder 경합(run_d2fd971f7daa)으로 선별한 1차 합격군입니다.
# 무료 10종에 동일 Capsule 로 같은 쓰기 과제를 주고 격리 워크트리에서
# 수행시킨 뒤, 구현 내부에 의존하지 않는 행동 시나리오 8문항으로 채점했습니다.
#
#   opencode-nemotron3-ultra  8/8   9분01초  테스트 9건
#   or-free-laguna-xs         8/8  11분03초  테스트 11건
#   opencode-deepseek         8/8  11분31초  테스트 8건
#   or-free-nemotron-ultra    8/8  12분32초  테스트 10건
#   opencode-mimo             8/8  13분58초  테스트 9건
#
# 다섯은 **동등한 합격군이며 아래 순서는 능력 순위가 아닙니다.** 정확도가
# 전부 8/8 로 갈리지 않아 소요 시간으로 나열했을 뿐인데, 스택당 1회 실행이라
# 무료 엔드포인트의 큐·콜드스타트·429 편차를 분리하지 못했습니다. 9분과 11분의
# 차이를 능력 차이로 읽지 마십시오.
#
# 순위를 확정하려면 서로 다른 과제 여러 종을 스택당 최소 3회 반복해
# median 과 p95 로 재야 합니다. 절차는 benchmarks/free_workers/README.md 5 장.
#
# 또한 이것은 모델이 아니라 **모델 + 제공자 + CLI 하네스** 조합의 성능입니다.
# kimi -p 는 one-shot 이고 opencode run 은 대화 경로가 있어, 코디네이터 회신을
# 받을 수 있었던 스택과 아닌 스택이 섞여 있습니다.
#
# 역할은 잰 것만 부여합니다. 이번 경합이 측정한 것은 builder 하나이고,
# investigator 는 코드를 정확히 읽어야 완주할 수 있으므로 포섭됩니다.
# benchmarker(측정 설계)와 documenter(문서 작성)는 측정한 적이 없어
# 무료 풀 전체에서 회수했습니다. opencode-deepseek 과 cursor-auto 는
# 이번 경합 이전부터 근거 없이 넷을 갖고 있던 항목이라 같이 정리했습니다.
#
# 실격 4종은 suitable_for 를 비워 후보에서 빠집니다. 실격 사유는 각 항목의
# 주석에 있습니다. 능력 미달, 결정 불능, 속도 초과, 지역 차단으로 서로 다릅니다.
# 2026-08-20 2차 경합(builder_02)에서 스택당 3회 반복해 재정렬했습니다.
# 실격선과 채점기를 실행 전에 동결했고, 라운드로빈으로 순서 효과를 없앴습니다.
# 성공은 시한 내 종료 AND 커밋 1건 이상 AND 채점 만점 셋을 모두 만족한 회차입니다.
#
#   opencode-deepseek         3/3  median 253s  p95 279s
#   or-free-laguna-xs         3/3  median 458s  p95 507s
#   opencode-mimo             2/3  median 456s  p95 506s  (1회 승인 대기로 커밋 0)
#   or-free-nemotron-ultra    2/3  median 586s  p95 610s  (1회 채점 2/6)
#   opencode-nemotron3-ultra  1/3  median 594s  p95 594s  (오염. 아래 재측정 참조)
#
# 1차의 순서가 뒤집혔습니다. 1차 1위였던 opencode-nemotron3-ultra 는 매 회차
# audit() 시그니처를 바꿔 기존 테스트를 깨뜨리고 복구하느라 3회 중 2회가 시한을
# 넘겼습니다. 1차 3위였던 opencode-deepseek 이 3/3 에 median 이 다른 스택의
# 절반입니다. **n=1 로 매긴 순서는 재현되지 않습니다.**
#
# 2026-08-21 재측정(3차). 2차의 oc_nemo3ultra 오염분을 같은 base ref(8b0b400)
# 와 같은 동시 3대 조건으로 다시 쟀습니다. deepseek 은 opencode 목록에서
# 부재라 빠졌습니다.
#
#   opencode-mimo             3/3  median 512s  p95 620s
#   opencode-nemotron3-ultra  2/3  median 658s  p95 698s  (1회 미착수 조기 종료)
#   or-free-laguna-xs         0/3               p95 720s  (3회 전부 시한 초과)
#
# **n=3 으로 매긴 순서도 재현되지 않습니다.** or-free-laguna-xs 는 2차에서
# 3/3 에 median 458s 였는데 하루 뒤 0/3 이 됐습니다. 능력이 떨어진 것이
# 아닙니다. 3회 중 2회는 채점 6/6 만점 코드를 만들어 놓고 720초 안에 커밋에
# 도달하지 못했습니다. 무료 엔드포인트의 응답 지연입니다.
#
# 그래서 아래 순서는 속도 순위가 아니라 **가장 최근에 관측된 실패율** 순입니다.
# 지연으로 실패하는 스택을 앞에 두면 회차마다 시한을 통째로 버립니다.
# 속도로 줄을 세우려는 시도는 하지 마십시오. 다음 측정에서 또 뒤집힙니다.
#
# opencode-deepseek 은 순서를 유지합니다. 실재 관측 이력이 부재를 누적하고
# apply_inventory_history() 가 자동으로 강등·제외하므로 여기서 손대면 이중
# 처리가 됩니다.
FREE_BUILDER_ORDER: list[str] = [
    "opencode-deepseek",
    "opencode-mimo",
    "opencode-nemotron3-ultra",
    "or-free-nemotron-ultra",
    "or-free-laguna-xs",
    # 읽기 범위가 Capsule 로 좁혀진 조사 전용. 컨텍스트 65K.
    "cerebras-oss",
    # 2026-08-18 실측 5회 중 3회가 빈 출력에 종료 코드 0 이었습니다.
    "cursor-auto",
]

# investigator 전용 무료 후보 순서입니다. investigator 순서는 아직 벤치마크로
# 측정된 적이 없습니다. 아래 값은 2026-08-20 2차 경합 시점의 builder 순서를
# 물려받은 것이며, investigator 근거로 측정된 값이 아닙니다.
#
# 2026-08-21 재측정에서 builder 순서를 실패율 기준으로 바꿨지만 여기는 그대로
# 둡니다. 조사 능력은 큰 코드베이스 탐색, 원인 후보 생성과 반증, 근거 수집,
# 허위 지적 억제를 요구하며 쓰기 능력에 포섭되지 않으므로, builder 실측을
# investigator 재배열의 근거로 쓸 수 없습니다. 이 분리가 두 순서를 서로 다른
# 리스트 객체로 둔 이유이며, 2026-08-21 부터 값도 실제로 갈라졌습니다.
FREE_INVESTIGATOR_ORDER: list[str] = [
    "opencode-deepseek",
    "or-free-laguna-xs",
    "opencode-mimo",
    "or-free-nemotron-ultra",
    "opencode-nemotron3-ultra",
    "cerebras-oss",
    "cursor-auto",
]

# 역할별 무료 후보 순서입니다. 하나의 목록을 모든 역할에 쓰면 builder 실측이
# investigator 배정까지 바꿉니다. 두 순서는 같은 값을 가질 수 있으나
# 반드시 서로 다른 리스트 객체여야 합니다.
#
# 조사 능력은 큰 코드베이스 탐색, 원인 후보 생성과 반증, 근거 수집, 허위 지적
# 억제를 요구하며 쓰기 능력에 포섭되지 않습니다. 그래서 builder 실측을
# investigator 근거로 쓸 수 없습니다.
# 측정 절차는 benchmarks/free_workers/README.md 입니다.
FREE_ORDER_BY_ROLE: dict[str, list[str]] = {
    "builder": FREE_BUILDER_ORDER,
    "investigator": FREE_INVESTIGATOR_ORDER,
}

# 하위 호환 별칭입니다. 역할을 아는 자리에서는 free_order_for_role 을 쓰십시오.
FREE_POOL_ORDER: list[str] = FREE_BUILDER_ORDER


# ---------------------------------------------------------------------------
# 실행 신뢰도 이력 (rolling reliability)
# ---------------------------------------------------------------------------
#
# 실재 이력(apply_inventory_history)이 보는 것은 "모델이 존재하는가" 뿐입니다.
# 2026-08-21 3차 재측정의 or-free/laguna-xs 는 존재했고 코드도 채점 6/6 만점을
# 받았는데 720초 시한 안에 커밋에 도달하지 못해 3회 전부 실패했습니다.
# 존재 여부로는 이런 열화를 잡을 수 없습니다.
#
# 그래서 최근 실행 결과를 창(window) 단위로 누적해 배정에 반영합니다. 정기
# 경합을 대신하는 상시 관측 경로이며, 관측이 모자라면 아무것도 하지 않습니다.
# 표본이 적을 때 순위를 흔드는 것이 이번에 그만두기로 한 바로 그 실수입니다.
MODEL_RELIABILITY_HISTORY_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "model_reliability_history.json"
)
# 최근 몇 회까지 보는지. 오래된 실패가 영원히 따라다니지 않게 합니다.
RELIABILITY_WINDOW = 10
# 이 미만이면 판단하지 않습니다. n=1~2 로 순위를 바꾸지 않습니다.
RELIABILITY_MIN_OBSERVATIONS = 3
# 창 안 성공률이 이 값 미만이면 강등합니다.
RELIABILITY_DEMOTE_RATE = 0.5
# 연속 실패가 이만큼이면 후보에서 뺍니다. 강등으로는 부족한 상태입니다.
RELIABILITY_SUSPEND_CONSECUTIVE = 3


try:
    import fcntl as _fcntl

    def _platform_lock(fobj: IO[str]) -> None:
        _fcntl.flock(fobj.fileno(), _fcntl.LOCK_EX)

    def _platform_unlock(fobj: IO[str]) -> None:
        _fcntl.flock(fobj.fileno(), _fcntl.LOCK_UN)

    _LOCK_AVAILABLE = True
except ImportError:
    try:
        import msvcrt as _msvcrt

        class _MsvcrtLockModule(Protocol):
            def locking(self, fd: int, mode: int, nbytes: int) -> None: ...

            LK_LOCK: int
            LK_UNLCK: int

        _msvcrt_lock = cast(_MsvcrtLockModule, _msvcrt)

        _LOCK_CHUNK = 1

        # msvcrt 는 현재 파일 위치 기준으로 바이트 구간을 잠급니다. seek(0) 없이
        # 잠그면 프로세스마다 다른 구간을 잡아 상호 배제가 성립하지 않습니다.
        # LK_LOCK 은 차단 잠금입니다. LK_NBLCK 은 경쟁 시 대기하지 않고 즉시
        # OSError 를 내므로 직렬화가 아니라 실패가 됩니다.
        def _platform_lock(fobj: IO[str]) -> None:
            fobj.seek(0)
            _msvcrt_lock.locking(fobj.fileno(), _msvcrt_lock.LK_LOCK, _LOCK_CHUNK)

        def _platform_unlock(fobj: IO[str]) -> None:
            fobj.seek(0)
            _msvcrt_lock.locking(fobj.fileno(), _msvcrt_lock.LK_UNLCK, _LOCK_CHUNK)

        _LOCK_AVAILABLE = True
    except ImportError:
        _LOCK_AVAILABLE = False


@contextmanager
def _lock_file(lock_path: Path):
    """lock_path 에 대한 프로세스 간 배타 잠금을 획득합니다.

    잠금 파일은 이력 파일과 별도로 둡니다. replace() 로 이력 파일이 교체돼도
    잠금이 유효한 inode 를 가리키도록 하기 위해서입니다.
    잠금 모듈을 사용할 수 없는 플랫폼에서는 잠금 없이 진행하되 표준 오류에 경고를 냅니다.
    """
    if not _LOCK_AVAILABLE:
        sys.stderr.write(
            f"[reliability] 파일 잠금을 지원하는 모듈이 없습니다 (fcntl/msvcrt). "
            f"동시 쓰기 안전성이 보장되지 않습니다: {lock_path}\n"
        )
        yield
        return

    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fobj = lock_path.open("a", encoding="utf-8")
    try:
        _platform_lock(fobj)
        try:
            yield
        finally:
            _platform_unlock(fobj)
    finally:
        fobj.close()


def load_reliability_history(path: Path | str | None = None) -> dict[str, dict[str, Any]]:
    """실행 신뢰도 이력을 읽습니다.

    파일이 없거나 손상됐으면 빈 이력을 돌려줍니다. 이력을 읽지 못한 것을
    열화로 해석하면 안 됩니다. 관측이 없는 것과 나쁘게 관측된 것은 다릅니다.
    """
    target = Path(path) if path is not None else MODEL_RELIABILITY_HISTORY_PATH
    if not target.is_file():
        return {}
    try:
        loaded = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(loaded, dict):
        return {}
    return {k: v for k, v in loaded.items() if isinstance(v, dict)}


def _reliability_stats(record: dict[str, Any], role: str) -> tuple[int, float, int] | None:
    """(관측 수, 성공률, 연속 실패 수) 를 돌려줍니다. 판단 불가면 None 입니다."""
    role_record = record.get(role)
    if not isinstance(role_record, dict):
        return None
    recent = role_record.get("recent")
    if not isinstance(recent, list):
        return None
    outcomes = [bool(r.get("ok")) for r in recent if isinstance(r, dict) and "ok" in r]
    if not outcomes:
        return None
    outcomes = outcomes[-RELIABILITY_WINDOW:]
    consecutive = 0
    for ok in reversed(outcomes):
        if ok:
            break
        consecutive += 1
    return len(outcomes), sum(outcomes) / len(outcomes), consecutive


def apply_reliability_history(
    candidates: list[str],
    role: str,
    history: dict[str, dict[str, Any]] | None = None,
) -> tuple[list[str], list[str]]:
    """최근 실행 신뢰도로 후보 순서를 조정합니다.

    연속 실패가 임계에 닿은 후보는 빼고, 최근 성공률이 낮은 후보는 뒤로
    미룹니다. 상대 순서는 각 묶음 안에서 보존합니다. 관측이
    RELIABILITY_MIN_OBSERVATIONS 미만이면 손대지 않습니다.
    """
    if history is None:
        history = load_reliability_history()
    if not history:
        return list(candidates), []

    keep: list[str] = []
    demoted: list[str] = []
    notes: list[str] = []
    for name in candidates:
        record = history.get(name)
        stats = _reliability_stats(record, role) if isinstance(record, dict) else None
        if stats is None:
            keep.append(name)
            continue
        seen, rate, consecutive = stats
        if seen < RELIABILITY_MIN_OBSERVATIONS:
            keep.append(name)
            continue
        if consecutive >= RELIABILITY_SUSPEND_CONSECUTIVE:
            notes.append(
                f"{name}: 최근 {consecutive}회 연속 실패로 후보에서 제외 "
                f"(창 {seen}회 성공률 {rate:.0%})"
            )
            continue
        if rate < RELIABILITY_DEMOTE_RATE:
            demoted.append(name)
            notes.append(f"{name}: 최근 {seen}회 성공률 {rate:.0%} 로 후보 순위 강등")
            continue
        keep.append(name)
    return keep + demoted, notes


def record_reliability_outcome(
    pool_name: str,
    role: str,
    ok: bool,
    failure: str | None = None,
    elapsed_sec: int | None = None,
    observation_id: str | None = None,
    path: Path | str | None = None,
) -> dict[str, Any]:
    """실행 결과 한 건을 이력에 누적하고 갱신된 기록을 돌려줍니다.

    창 길이를 넘는 오래된 관측은 버립니다. 파일이 없으면 만듭니다.
    """
    target = Path(path) if path is not None else MODEL_RELIABILITY_HISTORY_PATH
    lock_path = target.with_name(target.name + ".lock")
    with _lock_file(lock_path):
        history = load_reliability_history(target)
        record = history.get(pool_name)
        role_record = record.get(role) if isinstance(record, dict) else None
        recent = role_record.get("recent") if isinstance(role_record, dict) else None
        if not isinstance(recent, list):
            recent = []
        if observation_id and any(
            isinstance(item, dict) and item.get("observation_id") == observation_id
            for item in recent
        ):
            return cast(dict[str, Any], role_record)
        recent.append(
            {
                "ok": bool(ok),
                "failure": None if ok else failure,
                "elapsed_sec": elapsed_sec,
                "observation_id": observation_id,
                "at": _dt.datetime.now(_dt.UTC).isoformat(timespec="seconds"),
            }
        )
        if not isinstance(record, dict):
            record = {}
        record[role] = {"recent": recent[-RELIABILITY_WINDOW:]}
        history[pool_name] = record
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
        try:
            temporary.write_text(
                dump_strict_json(history, indent=2) + "\n",
                encoding="utf-8",
            )
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
    return record[role]


def pool_for_model(model_or_pool: str) -> str | None:
    """풀 이름 또는 실제 모델 ID를 등록된 풀 이름으로 정규화합니다."""
    for pool_name, pool_info in MODEL_POOL.items():
        if model_or_pool in (pool_name, pool_info["id"]):
            return pool_name
    return None


# ---------------------------------------------------------------------------
# 모델 제공자(Provider) 판정
# ---------------------------------------------------------------------------
#
# 새 모델/제공자 추가 시:
#   1. MODEL_POOL 에 새 풀 등록 및 "provider" 필드 명시
#   2. MODEL_PROVIDER_PREFIXES 에 접두사-제공자 매핑 추가 (풀 미등록 임의 ID 판정용)
#
MODEL_PROVIDER_PREFIXES: tuple[tuple[str, str], ...] = (
    ("gemini", "gemini"),
    ("qwen", "qwen"),
    ("deepseek", "qwen"),
    ("glm", "qwen"),
    ("claude", "claude"),
    ("grok", "grok"),
    ("gpt-", "codex"),
    ("codex", "codex"),
    ("cursor", "cursor"),
    ("opencode", "opencode"),
    ("cerebras", "cerebras"),
    ("or-free", "kimi-openrouter"),
    ("kimi", "kimi-openrouter"),
)


def provider_for_model(model_or_pool: str, strict: bool = True) -> str:
    """모델 ID 또는 풀 이름에서 provider 계열을 판정합니다.

    1. MODEL_POOL 등록 항목 검사 (풀 이름 또는 id 일치)
    2. MODEL_PROVIDER_PREFIXES 접두사 매핑 검사
    3. 미상인 경우: strict=True 이면 ValueError 발생, False 이면 'unknown' 반환
    """
    if not model_or_pool or not isinstance(model_or_pool, str):
        if strict:
            raise ValueError(f"유효하지 않은 모델 이름입니다: {model_or_pool!r}")
        return "unknown"

    cleaned = model_or_pool.strip()

    # 1. MODEL_POOL 풀 이름 일치
    if cleaned in MODEL_POOL:
        return str(MODEL_POOL[cleaned].get("provider", "unknown"))

    # 2. MODEL_POOL ID 일치
    for pool_info in MODEL_POOL.values():
        if cleaned == pool_info.get("id"):
            return str(pool_info.get("provider", "unknown"))

    # 3. 접두사 매핑 검사 (소문자 기준)
    lowered = cleaned.lower()
    for prefix, provider in MODEL_PROVIDER_PREFIXES:
        if lowered.startswith(prefix):
            return provider

    if strict:
        raise ValueError(f"알 수 없는 모델 ID 또는 제공자입니다: {model_or_pool}")
    return "unknown"


def free_order_for_role(role: str) -> list[str]:
    """역할에 맞는 무료 후보 순서를 돌려줍니다.

    등록되지 않은 역할은 builder 순서를 씁니다. 무료 풀이 열리는 역할은
    FREE_POOL_ELIGIBLE_ROLES 로 이미 제한되어 있습니다.
    """
    return FREE_ORDER_BY_ROLE.get(role, FREE_BUILDER_ORDER)


# ---------------------------------------------------------------------------
# 실재 관측 이력 연동
# ---------------------------------------------------------------------------
#
# 무료 풀은 예고 없이 바뀝니다. 2026-08-20 에 opencode/deepseek-v4-flash-free 가
# 목록에서 빠졌다가 같은 날 복구됐고, 2026-08-21 에 다시 빠졌습니다. 한 번의
# 실패로 라우터에서 빼면 복구된 모델을 잃고, 그대로 두면 1순위가 호출 불가인
# 채로 배정됩니다. OpenCode TUI 는 -m 이 실패해도 조용히 다른 모델로 뜨므로
# 배정 실패가 드러나지도 않습니다.
#
# 그래서 제거가 아니라 강등으로 다룹니다. 소멸 판정(연속 3회)은
# scripts/audit_model_inventory.py 가 내리고, 라우터는 그 이력을 읽기만 합니다.
# 이력 파일은 Git 미추적이라 환경에 따라 없습니다. 없으면 강등도 없고 기존
# 동작 그대로입니다.
MODEL_INVENTORY_HISTORY_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "model_inventory_history.json"
)
INVENTORY_MISSING_THRESHOLD = 3


def load_inventory_history(path: Path | str | None = None) -> dict[str, dict[str, Any]]:
    """모델 실재 관측 이력을 읽습니다.

    파일이 없거나 손상됐으면 빈 이력을 돌려줍니다. 이력을 읽지 못한 것을
    소멸로 해석하면 안 됩니다. 관측이 없는 것과 없는 것으로 관측된 것은
    다릅니다.
    """
    target = Path(path) if path is not None else MODEL_INVENTORY_HISTORY_PATH
    if not target.is_file():
        return {}
    try:
        loaded = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(loaded, dict):
        return {}
    return {k: v for k, v in loaded.items() if isinstance(v, dict)}


def apply_inventory_history(
    candidates: list[str],
    history: dict[str, dict[str, Any]] | None = None,
) -> tuple[list[str], list[str]]:
    """관측 이력으로 후보 순서를 조정합니다.

    소멸로 판정된 후보는 빼고, 의심 상태 후보는 뒤로 미룹니다. 상대 순서는
    각 묶음 안에서 보존합니다. (조정된 후보, 사람이 읽을 사유) 를 돌려줍니다.
    """
    if history is None:
        history = load_inventory_history()
    if not history:
        return list(candidates), []

    keep: list[str] = []
    demoted: list[str] = []
    notes: list[str] = []
    for name in candidates:
        record = history.get(name)
        if not record or record.get("status") != "absent":
            keep.append(name)
            continue
        counter = record.get("counter", 0)
        if not isinstance(counter, int):
            keep.append(name)
            continue
        if counter >= INVENTORY_MISSING_THRESHOLD:
            notes.append(f"{name}: 소멸 판정({counter}회 연속 미관측)으로 후보에서 제외")
            continue
        demoted.append(name)
        notes.append(f"{name}: 미관측 {counter}/{INVENTORY_MISSING_THRESHOLD} 회로 후보 순위 강등")
    return keep + demoted, notes


# ---------------------------------------------------------------------------
# 역할별 추론 등급 정책
# ---------------------------------------------------------------------------
#
# 배정 근거는 Gemini 3.8 Flash 공식 문서입니다.
#   low    : 지연이 중요한 작업, 초안 작성, 빠른 데이터 분석
#   medium : 기본값. 대부분의 작업에서 최고 품질이며 "복잡한 코드와 에이전트
#            용도에 권장" 되고 첫 시도 정확도가 더 높음
#   high   : 복잡한 추론, 어려운 수학, "가장 어려운" 코딩·에이전트 작업.
#            토큰 소모가 큼
#
# 따라서 high 는 기본값이 아니라 high 위험도 전용입니다. 2026-08-17 까지
# 리뷰어와 빌더가 위험도와 무관하게 항상 high 로 갔고, 읽기 전용 low 위험도
# 감사 4건도 전부 high 로 배정되어 주간 한도를 불필요하게 썼습니다.
#
# 리뷰어는 판정이 병합 결정에 쓰이므로 주 모델을 low 등급으로 내리지 않습니다.

TIER_POLICY: dict[tuple[str, str], list[str]] = {
    # 예산 구조가 배정을 정합니다. Antigravity Gemini 는 5시간마다 리셋되는 별도
    # 할당량이고, Alibaba Token Plan 은 충전한 잔량을 깎아 씁니다. 그래서 건수가
    # 많은 빌더·조사·문서·계측은 Gemini 가 맡고, Alibaba 는 qwen-plus 하나만
    # 자동 배정 대상으로 남깁니다.
    #
    # 리뷰어만 qwen-plus 를 주 모델로 씁니다. 리뷰어와 빌더가 같은 계열이면 같은
    # 추론 편향이 검토를 그대로 통과시키므로, 빌더가 Gemini 인 동안 리뷰어는
    # 다른 계열이어야 합니다. 리뷰어 Task 는 빌더보다 건수가 적어 잔량 부담도
    # 작습니다.
    #
    # deepseek-pro, glm, qwen-max 는 auto_selectable=False 입니다. 자동으로는
    # 배정되지 않고 --model 명시 지정과 WORKER_MODEL_NOTICE 를 거쳐야 씁니다.
    ("reviewer", "high"): ["qwen-plus", "gemini-flash-high"],
    ("reviewer", "medium"): ["qwen-plus", "gemini-flash-medium"],
    # gemini-flash-low 는 메타데이터 notes 에서 "리뷰어와 빌더에는 배정하지
    # 않는다" 고 명시한 모델입니다. fallback 으로 넣어 두면 주 모델 장애 시
    # 금지한 등급이 코드 작성과 병합 판정으로 승격됩니다.
    ("reviewer", "low"): ["qwen-plus", "gemini-flash-medium"],
    ("builder", "high"): ["gemini-flash-high", "qwen-plus"],
    ("builder", "medium"): ["gemini-flash-medium", "qwen-plus"],
    ("builder", "low"): ["gemini-flash-medium", "qwen-plus"],
    ("investigator", "high"): ["gemini-flash-high", "qwen-plus"],
    ("investigator", "medium"): ["gemini-flash-medium", "qwen-plus"],
    ("investigator", "low"): ["gemini-flash-low", "gemini-flash-medium"],
    # 계측·벤치마크는 수치 해석 오류가 그대로 정본이 되므로 low 에도
    # 초안용 등급을 주 모델로 두지 않습니다.
    ("benchmarker", "high"): ["gemini-flash-high", "qwen-plus"],
    ("benchmarker", "medium"): ["gemini-flash-medium", "qwen-plus"],
    ("benchmarker", "low"): ["gemini-flash-medium", "gemini-flash-low"],
    ("documenter", "high"): ["gemini-flash-high", "qwen-plus"],
    ("documenter", "medium"): ["gemini-flash-medium", "qwen-plus"],
    ("documenter", "low"): ["gemini-flash-low", "gemini-flash-medium"],
    ("__default__", "high"): ["gemini-flash-high", "qwen-plus"],
    ("__default__", "medium"): ["gemini-flash-medium", "qwen-plus"],
    ("__default__", "low"): ["gemini-flash-medium", "qwen-plus"],
}

# ---------------------------------------------------------------------------
# 위험도 분류 기준
# ---------------------------------------------------------------------------

RISK_KEYWORDS: dict[str, list[str]] = {
    "high": [
        r"\bmerge\b",
        r"\b병합\b",
        r"\bdeploy\b",
        r"\b배포\b",
        r"\bDB\b",
        r"\bdatabase\b",
        r"\bschema\b",
        r"\b스키마\b",
        r"\bmigration\b",
        r"\b마이그레이션\b",
        r"\bDROP\b",
        r"\bDELETE\b",
        r"\bpromotion\b",
        r"\b승격\b",
        r"\bcutover\b",
        r"\b컷오버\b",
        r"\bproduction\b",
        r"\b운영\b",
        r"\bretrain\b",
        r"\b재학습\b",
        r"\bsecurity\b",
        r"\b보안\b",
        r"\bsecret\b",
        r"\b시크릿\b",
    ],
    "medium": [
        r"\brefactor\b",
        r"\b리팩토링\b",
        r"\boptimize\b",
        r"\b최적화\b",
        r"\bperformance\b",
        r"\b성능\b",
        r"\bmodel\b",
        r"\b모델\b",
        r"\bAPI\b",
        r"\bendpoint\b",
        r"\b엔드포인트\b",
        r"\bconfig\b",
        r"\b설정\b",
        r"\bcache\b",
        r"\b캐시\b",
    ],
    "low": [
        r"\bdoc\b",
        r"\b문서\b",
        r"\btest\b",
        r"\b테스트\b",
        r"\blint\b",
        r"\bformat\b",
        r"\b포맷\b",
        r"\btypo\b",
        r"\bcomment\b",
        r"\b주석\b",
        r"\brename\b",
        r"\bchore\b",
    ],
}

# ---------------------------------------------------------------------------
# 예외 클래스
# ---------------------------------------------------------------------------


class ModelRoutingError(RuntimeError):
    """후보 모델이 모두 제외되었거나 선택 가능한 모델이 없을 때 발생하는 예외."""

    def __init__(
        self,
        message: str,
        role: str | None = None,
        risk: str | None = None,
        exclude: list[str] | None = None,
        exclude_providers: list[str] | None = None,
    ) -> None:
        super().__init__(message)
        self.role = role
        self.risk = risk
        self.exclude = list(exclude) if exclude is not None else []
        self.exclude_providers = list(exclude_providers) if exclude_providers is not None else []


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
      1. 역할이 FREE_POOL_ELIGIBLE_ROLES 에 속함 (builder, investigator)
      2. 위험도가 FREE_POOL_MAX_RISK 와 같음 (low)

    반환값: (eligible: bool, reason: str)
    쓰기 범위가 있으면 병합 전 검증 의무를 사유에 포함하며,
    조건을 만족하면 (True, "무료 풀 개방 조건 충족") 을 반환하고,
    그렇지 않으면 (False, 거부 사유) 를 반환합니다.
    """
    if role not in FREE_POOL_ELIGIBLE_ROLES:
        eligible_roles_str = ", ".join(sorted(FREE_POOL_ELIGIBLE_ROLES))
        return (
            False,
            f"무료 풀 개방 불가: 역할({role})이 무료 풀 개방 대상({eligible_roles_str})이 아닙니다.",
        )

    if risk != FREE_POOL_MAX_RISK:
        return (
            False,
            f"무료 풀 개방 불가: 위험도({risk})가 허용 기준({FREE_POOL_MAX_RISK})을 초과합니다.",
        )

    # 쓰기 범위가 있어도 막지 않습니다. 종전에는 차단했으나, 산출물은 Level 1
    # 게이트와 테스트를 거쳐 코디네이터가 병합을 결정하므로 무료 모델의 오류가
    # 저장소에 그대로 들어가지 않습니다. 다만 검증 부담이 커지므로 호출부가
    # 인지하도록 사유에 남깁니다.
    if has_write_scope:
        return True, "무료 풀 개방 조건 충족 (쓰기 범위 있음: 병합 전 검증 필수)"

    return True, "무료 풀 개방 조건 충족"


def classify_from_capsule(capsule_path: str | Path) -> dict[str, Any]:
    """Capsule 파일에서 objective, why_now, role 등을 읽어 위험도를 분류합니다."""
    capsule_text = load_capsule(capsule_path)
    objective = parse_capsule_scalar(capsule_text, "objective") or ""
    why_now = parse_capsule_scalar(capsule_text, "why_now") or ""
    role = parse_capsule_scalar(capsule_text, "role") or "builder"
    builder_model = parse_capsule_scalar(capsule_text, "builder_model") or parse_capsule_scalar(
        capsule_text, "model"
    )
    builder_provider = parse_capsule_scalar(capsule_text, "builder_provider")
    if not builder_provider and builder_model:
        with suppress(Exception):
            b_prov = provider_for_model(builder_model, strict=False)
            if b_prov != "unknown":
                builder_provider = b_prov

    combined = f"{objective}\n{why_now}"
    risk, reasons = classify_risk_with_reasons(combined)
    return {
        "risk": risk,
        "role": role,
        "objective": objective[:100],
        "reasons": reasons,
        "builder_provider": builder_provider,
        "builder_model": builder_model,
    }


# ---------------------------------------------------------------------------
# 모델 선택 및 검증
# ---------------------------------------------------------------------------


def is_coordinator_model(model_or_pool: str) -> bool:
    """주어진 모델 ID 또는 풀 이름이 코디네이터 전용인지 확인합니다."""
    # 하드코딩된 예외를 두지 않습니다. 코디네이터가 바뀌면 여기도 같이
    # 고쳐야 하는데 잊기 쉽고, 잊으면 내려간 모델이 계속 코디네이터로 읽힙니다.
    for pool_name, pool_info in MODEL_POOL.items():
        if pool_info["tier"] not in {"coordinator", "coordinator_reserve"}:
            continue
        # 풀 이름과 모델 ID 둘 다 받습니다. 둘이 같은 풀도 있어 한쪽만 보면
        # 호출부에 따라 판정이 갈립니다.
        if model_or_pool in (pool_name, pool_info["id"]):
            return True
    return False


def select_model(
    role: str,
    risk: str,
    exclude: list[str] | None = None,
    allow_free: bool = False,
    has_write_scope: bool = True,
    exclude_providers: list[str] | str | None = None,
    builder_provider: str | None = None,
) -> dict[str, Any]:
    """역할과 위험도에 따라 최적 모델을 선택합니다.

    자동 선택 대상 풀(auto_selectable=True) 중에서만 선택하며,
    allow_free 가 True 이고 무료 풀 개방 조건을 충족하는 경우에만
    FREE_POOL_ORDER 의 모델이 후보 맨 앞에 추가됩니다.
    코디네이터 전용 모델은 절대 선택되지 않습니다.
    exclude_providers 로 지정된 provider 계열 모델은 주 모델 및 대체 모델에서 모두 제외됩니다.

    리뷰어 독립성 정책:
    role == "reviewer" 인 경우, 빌더 provider 가 알려져 있으면 해당 provider 계열을 제외합니다.
    빌더 provider 를 알 수 없는 경우(unknown / 미지정):
      - 위험도가 medium 이상이거나 쓰기 범위(has_write_scope=True)가 있으면 독립성을 증명할 수 없으므로 fail-closed 로 ModelRoutingError 를 발생시킵니다.
      - 위험도가 low 이고 읽기 전용(has_write_scope=False)인 경우에만 경고 후 진행을 허용합니다.
    """
    exclude = exclude or []
    if isinstance(exclude_providers, str):
        excluded_providers_set = {exclude_providers}
    elif exclude_providers:
        excluded_providers_set = set(exclude_providers)
    else:
        excluded_providers_set = set()

    # 빌더 provider 정규화: None, 빈 문자열, 공백/탭 등 공백 문자열, "unknown" 은 "unknown" 으로 통일
    builder_prov_norm: str = "unknown"
    if isinstance(builder_provider, str):
        stripped = builder_provider.strip()
        if stripped and stripped != "unknown":
            builder_prov_norm = stripped

    if builder_prov_norm != "unknown" and builder_prov_norm not in excluded_providers_set:
        excluded_providers_set.add(builder_prov_norm)

    inventory_notes: list[str] = []

    builder_prov_missing = builder_prov_norm == "unknown" and not excluded_providers_set
    if role == "reviewer" and builder_prov_missing:
        if risk in ("high", "medium") or has_write_scope:
            exclude_str = ", ".join(exclude) if exclude else "(없음)"
            exclude_prov_str = (
                ", ".join(sorted(excluded_providers_set)) if excluded_providers_set else "(없음)"
            )
            raise ModelRoutingError(
                f"리뷰어 모델 선택 실패: 빌더 provider 를 알 수 없어 독립성을 보장할 수 없습니다 "
                f"(role={role}, risk={risk}, has_write_scope={has_write_scope}). "
                "위험도가 medium 이상이거나 쓰기 범위가 있는 Task 에서는 빌더 provider 가 필수입니다.",
                role=role,
                risk=risk,
                exclude=exclude,
                exclude_providers=list(excluded_providers_set),
            )
        inventory_notes.append(
            "경고: 빌더 provider 를 알 수 없어 독립 provider 제외를 적용하지 못했습니다."
        )

    base_candidates = list(TIER_POLICY.get((role, risk), TIER_POLICY[("__default__", risk)]))

    eligible, _reason = free_pool_eligibility(role, risk, has_write_scope)
    if allow_free and eligible:
        # 무료 후보도 역할 적합성을 통과해야 합니다. 걸러 내지 않으면
        # investigator 전용 모델이 builder 로 배정됩니다. TIER_POLICY 경로는
        # 이미 불변식으로 묶여 있는데 무료 경로만 그 밖에 있었습니다.
        # 테스트로만 맞추면 후보를 추가할 때마다 다시 어긋나므로 실행 코드가
        # 계약을 지키게 합니다.
        free_candidates = [
            c
            for c in free_order_for_role(role)
            if c in MODEL_POOL and role in MODEL_POOL[c].get("suitable_for", [])
        ]
        # 무료 풀만 이력을 반영합니다. 예고 없이 바뀌는 것이 관측된 쪽이
        # 무료 풀이고, 범위를 넓히면 조회 불가가 많은 유료 풀까지 흔듭니다.
        free_candidates, inventory_notes = apply_inventory_history(free_candidates)
        # 실재 이력 다음에 신뢰도 이력을 적용합니다. 순서가 중요합니다.
        # 사라진 모델을 신뢰도로 강등해 봐야 의미가 없습니다.
        free_candidates, reliability_notes = apply_reliability_history(free_candidates, role)
        inventory_notes = inventory_notes + reliability_notes
        candidates = free_candidates + base_candidates
    else:
        candidates = base_candidates

    primary: str | None = None
    fallback: str | None = None
    for c in candidates:
        if c in exclude:
            continue
        c_provider = MODEL_POOL[c].get("provider")
        if c_provider in excluded_providers_set:
            continue
        if primary is None:
            primary = c
        elif fallback is None:
            fallback = c
            break

    if primary is None:
        exclude_str = ", ".join(exclude) if exclude else "(없음)"
        exclude_prov_str = (
            ", ".join(sorted(excluded_providers_set)) if excluded_providers_set else "(없음)"
        )
        raise ModelRoutingError(
            f"선택 가능한 모델 후보가 없습니다. (role={role}, risk={risk}, exclude=[{exclude_str}], exclude_providers=[{exclude_prov_str}])",
            role=role,
            risk=risk,
            exclude=exclude,
            exclude_providers=list(excluded_providers_set),
        )

    primary_model = MODEL_POOL[primary]["id"]
    fallback_model = MODEL_POOL[fallback]["id"] if fallback and fallback in MODEL_POOL else None

    return {
        "primary_pool": primary,
        "primary_model": primary_model,
        "fallback_pool": fallback,
        "fallback_model": fallback_model,
        "risk": risk,
        "role": role,
        "inventory_notes": inventory_notes,
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
                if (val.startswith('"') and val.endswith('"')) or (
                    val.startswith("'") and val.endswith("'")
                ):
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
    probe_key = None
    # 풀 키(gemini-flash-medium)와 실제 모델 ID(gemini-3.8-flash-medium)는
    # 다릅니다. 풀 키로 provider 만 찾고 명령에는 풀 키를 그대로 넘기면
    # CLI 가 "알 수 없는 모델" 로 거부해, 살아 있는 모델이 사용 불가로
    # 판정됩니다. 문서와 list 출력이 안내하는 이름이 풀 키이므로 이 경로가
    # 기본 사용법이었고, 2026-08-19 워커 배정에서 실제로 오판했습니다.
    resolved_id = model_id
    for pool_name, pool_info in MODEL_POOL.items():
        if pool_info["id"] == model_id or pool_name == model_id:
            provider = pool_info["provider"]
            resolved_id = pool_info["id"]
            probe_key = pool_info.get("probe_provider") or pool_info.get("probe_transport")
            break

    if provider is None:
        if "gemini" in model_id.lower():
            provider = "gemini"
        elif "claude-sonnet-5" in model_id.lower() or model_id.lower() == "claude-sonnet":
            provider = "claude"
            probe_key = "claude-cli"
            resolved_id = "claude-sonnet-5"
        elif "claude" in model_id.lower():
            provider = "claude"
        elif "codex" in model_id.lower():
            provider = "codex"
        elif "cerebras" in model_id.lower():
            provider = "cerebras"
        elif "grok" in model_id.lower():
            provider = "grok"
            probe_key = "grok"
        else:
            provider = "opencode"

    if probe_key is None:
        probe_key = provider

    probe_info = PROBE_CONFIG.get(probe_key)
    if probe_info is None:
        return False, f"알 수 없는 provider: {probe_key}"

    probe_env, env_status = build_probe_env(repo_root)
    if provider == "cerebras" and "CEREBRAS_API_KEY 미설정" in env_status:
        return False, "probe 실패: CEREBRAS_API_KEY 미설정"

    cmd_template = probe_info["probe_cmd"]
    cmd = [arg.format(model=resolved_id) for arg in cmd_template]
    if provider == "kimi-openrouter":
        cmd[0] = resolve_kimi_bin()
    probe_timeout = probe_info.get("timeout", timeout)

    try:
        proc = subprocess.run(  # nosec B603 - shell 없이 고정 인자 목록으로 호출합니다
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

        # 방어적 보강입니다. 현재 등록된 CLI 는 인증 실패에 0 이 아닌 종료 코드를
        # 돌려주므로 아래 분류 경로에서 이미 걸러집니다. 다만 종료 코드 0 으로
        # 끝내면서 오류를 응답 본문에만 적는 CLI 가 등록되면 종료 코드만으로는
        # 죽은 모델을 거를 수 없으므로, 본문의 오류 표지도 함께 봅니다.
        if any(marker in stdout_clean.lower() for marker in STDOUT_ERROR_MARKERS):
            return (
                False,
                f"probe 실패: 종료 코드는 0이나 응답 본문이 오류입니다: {stdout_clean[:200]}",
            )

        if proc.stderr and proc.stderr.strip():
            stderr_lower = proc.stderr.lower()
            if "error:" in stderr_lower or "failed to" in stderr_lower:
                return (
                    False,
                    f"probe 실패: 종료 코드는 0이나 stderr 오류 발생: {proc.stderr.strip()[:200]}",
                )
            stderr_short = proc.stderr.strip().splitlines()[0][:100]
            return True, f"OK (종료 코드 0, {len(stdout_clean)}자, stderr: {stderr_short})"
        return True, f"OK (종료 코드 0, {len(stdout_clean)}자)"

    # 비정상 종료 시 원인 분류
    stderr_lower = proc.stderr.lower()
    stdout_lower = proc.stdout.lower()
    combined = f"{stderr_lower} {stdout_lower}"

    if any(
        k in combined
        for k in ("quota", "resource_exhausted", "429", "usage limit", "upgrade to pro")
    ):
        detail = f"할당량 초과 (quota exceeded): {proc.stderr.strip()[:200]}"
    elif any(
        k in combined
        for k in (
            "unauthorized",
            "unauthenticated",
            "forbidden",
            "auth",
            "api_key",
            "wrong api key",
            "401",
            "403",
        )
    ):
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
    exclude_providers: list[str] | str | None = None,
    builder_provider: str | None = None,
    builder_model: str | None = None,
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
        if not builder_provider:
            builder_provider = info.get("builder_provider")
        if not builder_model:
            builder_model = info.get("builder_model")
    else:
        role = role or "builder"
        if risk is None:
            combined = f"{objective or ''}\n{why_now or ''}"
            risk, reasons = classify_risk_with_reasons(combined)
        if has_write_scope is None:
            has_write_scope = True

    if not builder_provider and builder_model:
        with suppress(Exception):
            b_prov = provider_for_model(builder_model, strict=False)
            if b_prov != "unknown":
                builder_provider = b_prov

    builder_prov_missing = (
        not builder_provider
        or builder_provider == "unknown"
        or (isinstance(builder_provider, str) and not builder_provider.strip())
    )
    if role == "reviewer" and builder_prov_missing and not exclude_providers:
        if risk in ("high", "medium") or has_write_scope:
            raise ModelRoutingError(
                f"리뷰어 모델 라우팅 실패: 빌더 provider 를 알 수 없어 독립성을 보장할 수 없습니다 "
                f"(role={role}, risk={risk}, has_write_scope={has_write_scope}). "
                "위험도가 medium 이상이거나 쓰기 범위가 있는 Task 에서는 빌더 provider 가 필수입니다.",
                role=role,
                risk=risk,
            )
        builder_provider = "unknown"

    warnings: list[str] = []
    if allow_free:
        eligible, reason = free_pool_eligibility(role, risk, has_write_scope)
        if not eligible:
            warnings.append(reason)

    if explicit_model:
        pool_name = pool_for_model(explicit_model)
        if not pool_name:
            raise ModelRoutingError(
                f"명시 지정 모델({explicit_model})이 MODEL_POOL 에 등록되어 있지 않습니다.",
                role=role,
                risk=risk,
            )
        if is_coordinator_model(explicit_model):
            raise ValueError(f"코디네이터 전용 모델은 워커로 지정할 수 없습니다: {explicit_model}")
        if role == "reviewer":
            explicit_prov = provider_for_model(explicit_model, strict=False)
            if builder_provider and builder_provider != "unknown":
                if explicit_prov == builder_provider:
                    raise ModelRoutingError(
                        f"리뷰어 명시 지정 모델({explicit_model}, provider={explicit_prov})이 "
                        f"빌더 provider({builder_provider})와 동일하여 독립 리뷰 정책을 위반합니다.",
                        role=role,
                        risk=risk,
                    )
            elif risk in ("medium", "high") or has_write_scope:
                raise ModelRoutingError(
                    f"리뷰어 명시 모델({explicit_model}) 지정 시 위험도 {risk} 에서는 "
                    "빌더 provider 가 확인되어야 합니다.",
                    role=role,
                    risk=risk,
                )
        primary_id = explicit_model
        fallback_id = None
    else:
        selection = select_model(
            role=role,
            risk=risk,
            allow_free=allow_free,
            has_write_scope=has_write_scope,
            exclude_providers=exclude_providers,
            builder_provider=builder_provider,
        )
        primary_id = selection["primary_model"]
        fallback_id = selection.get("fallback_model")
        if selection.get("inventory_notes"):
            warnings.extend(selection["inventory_notes"])

    # 무료 풀이 실제로 주 모델로 선택된 경우 재검증 의무 경고 추가
    primary_pool_info = None
    for pool_info in MODEL_POOL.values():
        if pool_info["id"] == primary_id:
            primary_pool_info = pool_info
            break

    if primary_pool_info and primary_pool_info["tier"] == "free":
        warnings.append(
            "주의: 무료 모델 풀이 주 모델로 선택되었습니다. 산출물 재검증 필수이며 임계 경로 금지입니다."
        )
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
    cls.add_argument(
        "--role", choices=["builder", "reviewer", "investigator", "benchmarker", "documenter"]
    )
    cls.add_argument("--objective", help="작업 목표 텍스트")
    cls.add_argument("--why-now", help="작업 배경 텍스트")
    cls.add_argument(
        "--allow-free",
        action="store_true",
        help="저가·무료 모델 풀 조건부 개방 (쓰기 권한 없는 investigator 및 low 위험도 전용)",
    )
    cls.add_argument(
        "--exclude-provider", action="append", help="제외할 provider 계열 (복수 지정 가능)"
    )
    cls.add_argument("--builder-provider", help="빌더 모델의 provider 계열")
    cls.add_argument("--builder-model", help="빌더 모델 ID")
    cls.add_argument("--json", action="store_true", help="JSON 출력")

    # probe
    prb = sub.add_parser("probe", help="모델 가용성을 확인합니다.")
    prb.add_argument("--model", required=True, help="모델 ID")
    prb.add_argument("--timeout", type=int, default=30, help="probe 타임아웃 (초)")
    prb.add_argument("--json", action="store_true", help="JSON 출력")

    # route
    rt = sub.add_parser("route", help="분류 + probe 통합 라우팅.")
    rt.add_argument("--capsule", help="Task Capsule YAML 경로")
    rt.add_argument(
        "--role", choices=["builder", "reviewer", "investigator", "benchmarker", "documenter"]
    )
    rt.add_argument("--risk", choices=["low", "medium", "high"])
    rt.add_argument("--objective", help="작업 목표 텍스트")
    rt.add_argument("--why-now", help="작업 배경 텍스트")
    rt.add_argument("--model", help="명시적 모델 ID 지정")
    rt.add_argument(
        "--allow-free",
        action="store_true",
        help="저가·무료 모델 풀 조건부 개방 (쓰기 권한 없는 investigator 및 low 위험도 전용)",
    )
    rt.add_argument(
        "--exclude-provider", action="append", help="제외할 provider 계열 (복수 지정 가능)"
    )
    rt.add_argument("--builder-provider", help="빌더 모델의 provider 계열")
    rt.add_argument("--builder-model", help="빌더 모델 ID")
    rt.add_argument("--no-probe", action="store_true", help="probe 생략")
    rt.add_argument("--probe-timeout", type=int, default=30, help="probe 타임아웃 (초)")
    rt.add_argument("--json", action="store_true", help="JSON 출력")

    # list
    sub.add_parser("list", help="등록된 모델 풀을 출력합니다.")

    reliability = sub.add_parser(
        "reliability-record",
        help="워커 실행 결과를 역할별 rolling reliability 이력에 기록합니다.",
    )
    reliability.add_argument("--pool", required=True, help="모델 풀 이름 또는 실제 모델 ID")
    reliability.add_argument(
        "--role",
        required=True,
        choices=["builder", "reviewer", "investigator", "benchmarker", "documenter"],
    )
    reliability.add_argument(
        "--status", required=True, choices=["succeeded", "failed"], help="실행 결과"
    )
    reliability.add_argument("--failure", help="실패 분류")
    reliability.add_argument("--elapsed-sec", type=int, help="실행 시간(초)")
    reliability.add_argument("--observation-id", help="중복 기록 방지용 실행 식별자")
    reliability.add_argument("--state", help="상태 파일 경로")
    reliability.add_argument("--json", action="store_true", help="JSON 출력")

    return parser


def cmd_classify(args: argparse.Namespace) -> int:
    reasons: list[str] = []
    allow_free = getattr(args, "allow_free", False)
    exclude_providers = getattr(args, "exclude_provider", None)
    builder_provider = getattr(args, "builder_provider", None)
    builder_model = getattr(args, "builder_model", None)
    if args.capsule:
        info = classify_from_capsule(args.capsule)
        risk = info["risk"]
        role = info["role"]
        objective = info["objective"]
        reasons = info.get("reasons", [])
        has_write_scope = capsule_has_write_scope(args.capsule)
        if not builder_provider:
            builder_provider = info.get("builder_provider")
        if not builder_model:
            builder_model = info.get("builder_model")
    else:
        objective = args.objective or ""
        why_now = args.why_now or ""
        role = args.role or "builder"
        combined = f"{objective}\n{why_now}"
        risk, reasons = classify_risk_with_reasons(combined)
        has_write_scope = True

    if not builder_provider and builder_model:
        with suppress(Exception):
            b_prov = provider_for_model(builder_model, strict=False)
            if b_prov != "unknown":
                builder_provider = b_prov

    try:
        selection = select_model(
            role=role,
            risk=risk,
            allow_free=allow_free,
            has_write_scope=has_write_scope,
            exclude_providers=exclude_providers,
            builder_provider=builder_provider,
        )
    except ModelRoutingError as exc:
        if args.json:
            print(dump_strict_json({"error": str(exc)}, indent=2))
        else:
            print(f"오류: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(
            dump_strict_json(
                {
                    "risk": risk,
                    "role": role,
                    "primary_model": selection["primary_model"],
                    "primary_pool": selection["primary_pool"],
                    "fallback_model": selection.get("fallback_model"),
                    "fallback_pool": selection.get("fallback_pool"),
                    "reasons": reasons,
                },
                indent=2,
            )
        )
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
        print(
            dump_strict_json(
                {"model": args.model, "available": available, "detail": detail},
                indent=2,
            )
        )
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
            exclude_providers=getattr(args, "exclude_provider", None),
            builder_provider=getattr(args, "builder_provider", None),
            builder_model=getattr(args, "builder_model", None),
        )
    except (ValueError, ModelRoutingError) as exc:
        if args.json:
            print(dump_strict_json({"error": str(exc)}, indent=2))
        else:
            print(f"오류: {exc}", file=sys.stderr)
        return 1

    recommended = (
        result.fallback_model
        if not result.primary_available and result.fallback_available
        else result.primary_model
    )

    if args.json:
        print(
            dump_strict_json(
                {
                    "risk": result.risk,
                    "role": result.role,
                    "primary_model": result.primary_model,
                    "primary_available": result.primary_available,
                    "fallback_model": result.fallback_model,
                    "fallback_available": result.fallback_available,
                    "reasons": result.reasons,
                    "warnings": result.warnings,
                    "recommended": recommended,
                },
                indent=2,
            )
        )
    else:
        print(f"위험도:        {result.risk}")
        print(f"역할:          {result.role}")
        print(
            f"주 모델:       {result.primary_model} {'(사용 가능)' if result.primary_available else '(사용 불가)'}"
        )
        if result.fallback_model:
            fb_status = (
                "(사용 가능)"
                if result.fallback_available
                else "(사용 불가)"
                if result.fallback_available is not None
                else "(미확인)"
            )
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
            "coordinator_reserve": "예비 코디네이터",
            "free": "무료",
        }.get(info["tier"], info["tier"])
        auto_status = "대상" if info.get("auto_selectable", False) else "비대상"
        if info["tier"] in {"coordinator", "coordinator_reserve"}:
            auto_status += " (코디네이터 전용 - 워커 사용 불가)"
        elif not info.get("auto_selectable", False):
            auto_status += " (수동 지정 전용)"

        print(f"  {pool_name} ({tier_label})")
        print(f"    ID:        {info['id']}")
        print(f"    Provider:  {info['provider']}")
        print(f"    자동 선택: {auto_status}")
        if info["tier"] == "coordinator":
            print(f"    기본 추론: {info['default_effort']}")
            print("    변경 알림: MODEL_CHANGE_NOTICE 사전 고지")
        print(f"    용도:      {', '.join(info['suitable_for']) or '워커 사용 불가'}")
        print(f"    비고:      {info['notes']}")
        print()
    print(
        "안내: 무료 풀(opencode-free)은 --allow-free 지정 시 쓰기 권한 없는 low 위험도 조사(investigator) 역할에 한해 조건부로 개방됩니다."
    )
    return 0


def cmd_reliability_record(args: argparse.Namespace) -> int:
    pool_name = pool_for_model(args.pool)
    if pool_name is None:
        print(f"오류: 등록되지 않은 모델 풀 또는 ID입니다: {args.pool}", file=sys.stderr)
        return 2
    if MODEL_POOL[pool_name]["tier"] != "free":
        print(
            f"오류: rolling reliability 기록 대상은 무료 풀뿐입니다: {pool_name}", file=sys.stderr
        )
        return 2

    record = record_reliability_outcome(
        pool_name,
        args.role,
        ok=args.status == "succeeded",
        failure=args.failure,
        elapsed_sec=args.elapsed_sec,
        observation_id=args.observation_id,
        path=args.state,
    )
    if args.json:
        print(
            dump_strict_json(
                {"pool": pool_name, "role": args.role, "record": record},
                indent=2,
            )
        )
    else:
        print(f"신뢰도 기록 완료: {pool_name}/{args.role} ({args.status})")
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
    if args.command == "reliability-record":
        return cmd_reliability_record(args)
    return 1


if __name__ == "__main__":
    sys.exit(main())

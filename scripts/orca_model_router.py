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
  - Gemini Flash    : 주력 워커. 추론 등급은 공식 문서 기준으로 위험도에 따라 배정합니다.
                      medium 이 기본값이며 복잡한 코드와 에이전트 용도에 권장됩니다.
                      high 는 가장 어려운 작업 전용, low 는 초안과 빠른 분석용입니다.
  - Claude 계열     : 별도 풀 (claude-sonnet-4-6). 판정 품질이 필요한 작업.
  - Codex           : 주간 잔량이 넉넉할 때만 수동 지정.
  - OpenCode 무료   : 실패해도 손실 없는 병렬 조사. 임계 경로 금지.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess  # nosec B404 - 개발 스크립트가 고정 인자 목록으로만 외부 도구를 호출합니다
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

__all__ = [
    "FREE_POOL_ELIGIBLE_ROLES",
    "FREE_POOL_MAX_RISK",
    "FREE_POOL_ORDER",
    "MODEL_POOL",
    "PROBE_CONFIG",
    "RISK_KEYWORDS",
    "TIER_POLICY",
    "ModelRoutingError",
    "RouteResult",
    "build_probe_env",
    "capsule_has_write_scope",
    "classify_from_capsule",
    "classify_risk",
    "classify_risk_with_reasons",
    "cmd_classify",
    "cmd_list",
    "cmd_probe",
    "cmd_route",
    "free_pool_eligibility",
    "is_coordinator_model",
    "load_repo_env",
    "main",
    "preflight",
    "probe_model",
    "route",
    "select_model",
]

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
    "kimi-openrouter": {
        # kimi 는 PATH 에 없어 전체 경로로 부릅니다. -p 는 단발 실행이라
        # probe 가 대화형으로 남지 않습니다. 무료 풀이라 콜드스타트가 깁니다.
        "probe_cmd": [
            "/Users/kwanbum/.kimi-code/bin/kimi",
            "-m",
            "{model}",
            "-p",
            "ping",
        ],
        "timeout": 120,
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
        "notes": "공식 문서 기준 가장 어려운 추론·코딩 전용. high 위험도에만 배정한다. 토큰 소모가 크다.",
    },
    "gemini-flash-medium": {
        "id": "gemini-3.7-flash-medium",
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
        "notes": "공식 문서 기준 기본값이며 복잡한 코드와 에이전트 용도에 권장되는 등급. medium 위험도 이하의 주력 워커.",
    },
    "gemini-flash-low": {
        "id": "gemini-3.7-flash-low",
        "provider": "gemini",
        "tier": "primary",
        "auto_selectable": True,
        "max_tokens": 1_000_000,
        "suitable_for": [
            "investigator",
            "benchmarker",
            "documenter",
        ],
        "notes": "공식 문서 기준 용도는 지연이 중요한 작업, 초안 작성, 빠른 데이터 분석. low 위험도 문서화·조사·계측에만 자동 선택된다. 리뷰어와 빌더에는 배정하지 않는다.",
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
    "cursor-auto": {
        "id": "cursor-agent/auto",
        "provider": "cursor",
        "tier": "free",
        "auto_selectable": False,
        "max_tokens": None,
        "suitable_for": [
            "investigator",
            "builder",
            "benchmarker",
            "documenter",
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
            "benchmarker",
            "documenter",
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
        # 배정 대상에서 뺍니다. 이력을 남기려고 항목 자체는 지우지 않습니다.
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
            "benchmarker",
            "documenter",
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
        # 2026-08-20 builder 경합 실격. 32분간 379KB 를 출력하는 동안 도구 호출
        # 0건, 파일 변경 0건. 사양 모순을 정확히 인지하고 escalation 을 결정한
        # 뒤 매번 재검토로 되돌아갔습니다. 같은 모순을 deepseek 은 3분 만에
        # ask 로 올려 해결했습니다. 읽기 전용 probe 에서는 드러나지 않습니다.
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
            "benchmarker",
            "documenter",
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
        # 2026-08-20 builder 경합 1위. 9분01초로 전체 최속, 중립 시나리오 8/8,
        # 테스트 9건. 그전까지 MODEL_POOL 에 등록조차 되어 있지 않았습니다.
        "suitable_for": [
            "investigator",
            "builder",
            "benchmarker",
            "documenter",
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
            "benchmarker",
            "documenter",
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
        # 2026-08-20 builder 경합 실격. 31분50초 시점에 스크립트 70줄만 쓰고
        # 테스트 미착수, 커밋 0건. 방향은 맞았으나 통과 5종 최장(13분58초)의
        # 2.3배로 실격선 28분을 넘겼습니다.
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
# 2026-08-20 builder 경합(run_d2fd971f7daa) 실측 순서입니다. 그 전까지는
# 문맥 크기와 probe 응답 시간으로 매긴 잠정 순서였고 능력 근거가 없었습니다.
#
# 무료 10종에 동일 Capsule 로 같은 쓰기 과제를 주고 격리 워크트리에서
# 수행시킨 뒤, 구현 내부에 의존하지 않는 행동 시나리오 8문항으로 채점했습니다.
# 통과 5종은 전부 8/8 이라 정확도로는 갈리지 않았고, 순서는 소요 시간입니다.
#
#   opencode-nemotron3-ultra  9분01초  8/8  테스트 9건
#   or-free-laguna-xs        11분03초  8/8  테스트 11건
#   opencode-deepseek        11분31초  8/8  테스트 8건
#   or-free-nemotron-ultra   12분32초  8/8  테스트 10건
#   opencode-mimo            13분58초  8/8  테스트 9건
#
# 실격 4종은 suitable_for 를 비워 후보에서 빠집니다. 실격 사유는 각 항목의
# 주석에 있습니다. 능력 미달, 결정 불능, 속도 초과, 지역 차단으로 서로 다릅니다.
FREE_POOL_ORDER: list[str] = [
    "opencode-nemotron3-ultra",
    "or-free-laguna-xs",
    "opencode-deepseek",
    "or-free-nemotron-ultra",
    "opencode-mimo",
    # 읽기 범위가 Capsule 로 좁혀진 조사 전용. 컨텍스트 65K.
    "cerebras-oss",
    # 2026-08-18 실측 5회 중 3회가 빈 출력에 종료 코드 0 이었습니다.
    "cursor-auto",
]

# ---------------------------------------------------------------------------
# 역할별 추론 등급 정책
# ---------------------------------------------------------------------------
#
# 배정 근거는 Gemini 3.7 Flash 공식 문서입니다.
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
    ("reviewer", "high"): ["claude-sonnet", "gemini-flash-high"],
    ("reviewer", "medium"): ["gemini-flash-medium", "gemini-flash-high"],
    # gemini-flash-low 는 메타데이터 notes 에서 "리뷰어와 빌더에는 배정하지
    # 않는다" 고 명시한 모델입니다. fallback 으로 넣어 두면 주 모델 장애 시
    # 금지한 등급이 코드 작성과 병합 판정으로 승격됩니다.
    ("reviewer", "low"): ["gemini-flash-medium", "gemini-flash-high"],
    ("builder", "high"): ["gemini-flash-high", "claude-sonnet"],
    ("builder", "medium"): ["gemini-flash-medium", "gemini-flash-high"],
    ("builder", "low"): ["gemini-flash-medium", "gemini-flash-high"],
    ("investigator", "high"): ["gemini-flash-high", "gemini-flash-medium"],
    ("investigator", "medium"): ["gemini-flash-medium", "gemini-flash-high"],
    ("investigator", "low"): ["gemini-flash-low", "gemini-flash-medium"],
    ("benchmarker", "high"): ["gemini-flash-high", "gemini-flash-medium"],
    ("benchmarker", "medium"): ["gemini-flash-medium", "gemini-flash-high"],
    ("benchmarker", "low"): ["gemini-flash-low", "gemini-flash-medium"],
    ("documenter", "high"): ["gemini-flash-high", "gemini-flash-medium"],
    ("documenter", "medium"): ["gemini-flash-medium", "gemini-flash-high"],
    ("documenter", "low"): ["gemini-flash-low", "gemini-flash-medium"],
    ("__default__", "high"): ["gemini-flash-high", "gemini-flash-medium"],
    ("__default__", "medium"): ["gemini-flash-medium", "gemini-flash-high"],
    ("__default__", "low"): ["gemini-flash-medium", "gemini-flash-high"],
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
    ) -> None:
        super().__init__(message)
        self.role = role
        self.risk = risk
        self.exclude = list(exclude) if exclude is not None else []


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
            for c in FREE_POOL_ORDER
            if c in MODEL_POOL and role in MODEL_POOL[c].get("suitable_for", [])
        ]
        candidates = free_candidates + base_candidates
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
        exclude_str = ", ".join(exclude) if exclude else "(없음)"
        raise ModelRoutingError(
            f"선택 가능한 모델 후보가 없습니다. (role={role}, risk={risk}, exclude=[{exclude_str}])",
            role=role,
            risk=risk,
            exclude=exclude,
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
    # 풀 키(gemini-flash-medium)와 실제 모델 ID(gemini-3.7-flash-medium)는
    # 다릅니다. 풀 키로 provider 만 찾고 명령에는 풀 키를 그대로 넘기면
    # CLI 가 "알 수 없는 모델" 로 거부해, 살아 있는 모델이 사용 불가로
    # 판정됩니다. 문서와 list 출력이 안내하는 이름이 풀 키이므로 이 경로가
    # 기본 사용법이었고, 2026-08-19 워커 배정에서 실제로 오판했습니다.
    resolved_id = model_id
    for pool_name, pool_info in MODEL_POOL.items():
        if pool_info["id"] == model_id or pool_name == model_id:
            provider = pool_info["provider"]
            resolved_id = pool_info["id"]
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
    cmd = [arg.format(model=resolved_id) for arg in cmd_template]
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

    try:
        selection = select_model(
            role=role,
            risk=risk,
            allow_free=allow_free,
            has_write_scope=has_write_scope,
        )
    except ModelRoutingError as exc:
        if args.json:
            print(json.dumps({"error": str(exc)}, ensure_ascii=False, indent=2))
        else:
            print(f"오류: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(
            json.dumps(
                {
                    "risk": risk,
                    "role": role,
                    "primary_model": selection["primary_model"],
                    "primary_pool": selection["primary_pool"],
                    "fallback_model": selection.get("fallback_model"),
                    "fallback_pool": selection.get("fallback_pool"),
                    "reasons": reasons,
                },
                ensure_ascii=False,
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
            json.dumps(
                {"model": args.model, "available": available, "detail": detail},
                ensure_ascii=False,
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
        )
    except (ValueError, ModelRoutingError) as exc:
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
        print(
            json.dumps(
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
                ensure_ascii=False,
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
    print(
        "안내: 무료 풀(opencode-free)은 --allow-free 지정 시 쓰기 권한 없는 low 위험도 조사(investigator) 역할에 한해 조건부로 개방됩니다."
    )
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

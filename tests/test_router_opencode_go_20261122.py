"""tests/test_router_opencode_go_20261122.py

2026-11-22 사용자 지정 OpenCode Go 워커 두 모델의 등록과 배정 정책을 검증합니다.
이 시험은 모델 하위 프로세스를 호출하지 않습니다(probe=False).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_scripts = Path(__file__).resolve().parent.parent / "scripts"
if str(_scripts) not in sys.path:
    sys.path.insert(0, str(_scripts))

from scripts.orca_model_router import (
    FREE_BUILDER_ORDER,
    FREE_INVESTIGATOR_ORDER,
    FREE_POOL_ORDER,
    MODEL_POOL,
    TIER_POLICY,
    ModelRoutingError,
    model_family,
    pool_for_model,
    provider_for_model,
    route,
    select_model,
)
from scripts.orca_taskctl import resolve_dispatch_model

BUILDER_POOL = "opencode-go-deepseek-v41"
BUILDER_ID = "opencode-go/deepseek-v4.1-flash"
REVIEWER_POOL = "opencode-go-glm-flash"
REVIEWER_ID = "opencode-go/glm-5.3-flash"


def test_opencode_go_models_are_registered_for_explicit_selection():
    """두 모델이 실행기 기준 provider opencode, 계열 deepseek/glm 으로 등록됩니다."""
    expected = {
        BUILDER_POOL: (BUILDER_ID, "deepseek", ["builder", "investigator"]),
        REVIEWER_POOL: (REVIEWER_ID, "glm", ["reviewer", "investigator", "builder"]),
    }
    for pool_name, (model_id, family, roles) in expected.items():
        info = MODEL_POOL[pool_name]
        assert info["id"] == model_id
        assert info["provider"] == "opencode"
        assert info["family"] == family
        assert info["tier"] == "primary"
        assert info["auto_selectable"] is False
        assert list(info["suitable_for"]) == roles
        assert model_family(pool_name) == family
        assert model_family(model_id) == family
        assert provider_for_model(pool_name) == "opencode"
        assert provider_for_model(model_id) == "opencode"
        # 실행기 라우팅은 provider 로 판정되므로 opencode 여야 런처가 잡힙니다.
        assert info["notes"]


def test_opencode_go_models_resolve_from_pool_name_and_model_id():
    """dispatch --model 이 풀 이름과 실제 ID 를 모두 찾아야 합니다."""
    assert pool_for_model(BUILDER_POOL) == BUILDER_POOL
    assert pool_for_model(BUILDER_ID) == BUILDER_POOL
    assert pool_for_model(REVIEWER_POOL) == REVIEWER_POOL
    assert pool_for_model(REVIEWER_ID) == REVIEWER_POOL


def test_opencode_go_models_stay_out_of_automatic_assignment():
    """자동 배정 후보(TIER_POLICY)와 무료 후보 순서에 끼지 않습니다."""
    tier_values = [model for models in TIER_POLICY.values() for model in models]
    for pool_name in (BUILDER_POOL, REVIEWER_POOL):
        assert pool_name not in tier_values

    free_orders = (FREE_POOL_ORDER, FREE_BUILDER_ORDER, FREE_INVESTIGATOR_ORDER)
    for order in free_orders:
        for pool_name in (BUILDER_POOL, REVIEWER_POOL):
            assert pool_name not in order

    roles = ("builder", "reviewer", "investigator", "benchmarker", "documenter")
    risks = ("high", "medium", "low")
    for role in roles:
        for risk in risks:
            kwargs = {"builder_provider": "gemini"} if role == "reviewer" else {}
            selection = select_model(role, risk, **kwargs)
            selected = {selection.get("primary_pool"), selection.get("fallback_pool")}
            assert BUILDER_POOL not in selected
            assert REVIEWER_POOL not in selected


def test_reviewer_independence_opencode_go_different_family_allowed():
    """같은 provider 라도 빌더 deepseek, 리뷰어 glm 은 독립 리뷰를 통과합니다."""
    result = route(
        role="reviewer",
        risk="high",
        explicit_model=REVIEWER_ID,
        builder_model=BUILDER_ID,
        builder_provider="opencode",
        probe=False,
    )
    assert result.primary_model == REVIEWER_ID


def test_reviewer_independence_opencode_go_same_family_rejected():
    """같은 계열(빌더·리뷰어 모두 deepseek)은 거부됩니다."""
    with pytest.raises(ModelRoutingError):
        route(
            role="reviewer",
            risk="high",
            explicit_model=BUILDER_ID,
            builder_model=BUILDER_ID,
            builder_provider="opencode",
            probe=False,
        )


@pytest.mark.parametrize("model", [BUILDER_ID, REVIEWER_ID])
def test_dispatch_explicit_model_resolves_without_routing_error(model: str):
    """dispatch --model 경로가 두 모델을 명시 지정으로 받아들입니다."""
    result = resolve_dispatch_model(
        args_model=model,
        capsule_text="role: builder\nrisk: medium\n",
    )
    assert result["model"] == model
    assert result["source"] == "explicit"

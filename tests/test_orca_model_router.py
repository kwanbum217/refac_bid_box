"""
tests/test_orca_model_router.py

orca_model_router.py 모델 라우터 유닛 테스트.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# scripts/ 디렉터리를 import 경로에 추가
_scripts = Path(__file__).resolve().parent.parent / "scripts"
if str(_scripts) not in sys.path:
    sys.path.insert(0, str(_scripts))

from orca_model_router import (
    MODEL_POOL,
    classify_risk,
    select_model,
    route,
    RouteResult,
)


class TestClassifyRisk:
    def test_high_risk_db_schema(self):
        assert classify_risk("DB schema migration for MySQL") == "high"

    def test_high_risk_merge(self):
        assert classify_risk("merge the feature branch to main") == "high"

    def test_high_risk_deploy(self):
        assert classify_risk("production 배포 및 컷오버") == "high"

    def test_high_risk_promotion(self):
        assert classify_risk("모델 승격 및 champion 교체") == "high"

    def test_high_risk_security(self):
        assert classify_risk("보안 취약점 수정 및 secret rotation") == "high"

    def test_medium_risk_refactor(self):
        assert classify_risk("prediction API 리팩토링") == "medium"

    def test_medium_risk_performance(self):
        assert classify_risk("cache 레이어 성능 최적화") == "medium"

    def test_medium_risk_config(self):
        assert classify_risk("환경 설정 파일 업데이트") == "medium"

    def test_low_risk_docs(self):
        assert classify_risk("README 문서 업데이트") == "low"

    def test_low_risk_tests(self):
        assert classify_risk("add more unit tests for predictor") == "low"

    def test_low_risk_lint(self):
        assert classify_risk("lint and format fixes") == "low"

    def test_default_low(self):
        assert classify_risk("일반적인 작업 내용") == "low"


class TestSelectModel:
    def test_builder_medium_risk(self):
        result = select_model("builder", "medium")
        assert result["primary_pool"] == "gemini-flash-high"
        assert result["primary_model"] == "gemini-3.7-flash-high"

    def test_builder_high_risk(self):
        result = select_model("builder", "high")
        assert result["primary_pool"] == "gemini-flash-high"
        assert result["fallback_pool"] == "claude-sonnet"

    def test_reviewer_high_risk(self):
        result = select_model("reviewer", "high")
        assert result["primary_pool"] == "claude-sonnet"
        assert result["fallback_pool"] == "gemini-flash-high"

    def test_reviewer_medium_risk(self):
        result = select_model("reviewer", "medium")
        assert result["primary_pool"] == "gemini-flash-high"

    def test_investigator(self):
        result = select_model("investigator", "low")
        assert result["primary_pool"] == "gemini-flash-high"

    def test_documenter_low_risk(self):
        result = select_model("documenter", "low")
        assert result["primary_pool"] == "gemini-flash-medium"

    def test_exclude_primary(self):
        result = select_model("builder", "high", exclude=["gemini-flash-high"])
        assert result["primary_pool"] == "claude-sonnet"
        assert result["fallback_pool"] is None

    def test_unknown_role(self):
        result = select_model("unknown", "low")
        assert result["primary_pool"] == "gemini-flash-high"


class TestRoute:
    def test_route_no_probe(self):
        result = route(role="builder", risk="medium", probe=False)
        assert isinstance(result, RouteResult)
        assert result.risk == "medium"
        assert result.role == "builder"
        assert result.primary_model == "gemini-3.7-flash-high"
        assert result.primary_available is True  # no probe = assume available

    def test_route_with_objective(self):
        result = route(
            objective="DB schema migration",
            why_now="운영 DB 마이그레이션 필요",
            probe=False,
        )
        assert result.risk == "high"
        assert result.primary_model == "gemini-3.7-flash-high"
        assert result.fallback_model == "claude-sonnet-4-6"

    def test_route_low_risk_documenter(self):
        result = route(role="documenter", risk="low", probe=False)
        assert result.primary_model == "gemini-3.7-flash-medium"


class TestModelPool:
    def test_all_pools_have_required_fields(self):
        for pool_name, info in MODEL_POOL.items():
            assert "id" in info, f"{pool_name}: id 누락"
            assert "provider" in info, f"{pool_name}: provider 누락"
            assert "tier" in info, f"{pool_name}: tier 누락"
            assert "suitable_for" in info, f"{pool_name}: suitable_for 누락"

    def test_coordinator_not_suitable_for_worker(self):
        claude_opus = MODEL_POOL["claude-opus"]
        assert claude_opus["tier"] == "coordinator"
        assert claude_opus["suitable_for"] == []

    def test_primary_models_cover_all_roles(self):
        """주력 모델은 모든 역할을 커버해야 합니다."""
        gemini_high = MODEL_POOL["gemini-flash-high"]
        all_roles = {"builder", "reviewer", "investigator", "benchmarker", "documenter"}
        assert set(gemini_high["suitable_for"]) == all_roles

    def test_no_provider_mismatch(self):
        valid_providers = {"gemini", "claude", "opencode"}
        for pool_name, info in MODEL_POOL.items():
            assert info["provider"] in valid_providers, f"{pool_name}: 알 수 없는 provider"


class TestCLI:
    def test_list_command(self):
        import subprocess
        result = subprocess.run(
            [sys.executable, str(_scripts / "orca_model_router.py"), "list"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0
        assert "gemini-flash-high" in result.stdout
        assert "claude-opus" in result.stdout

    def test_classify_json(self):
        import subprocess
        result = subprocess.run(
            [
                sys.executable, str(_scripts / "orca_model_router.py"),
                "classify", "--objective", "DB schema migration",
                "--role", "builder", "--json",
            ],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["risk"] == "high"
        assert data["primary_model"] == "gemini-3.7-flash-high"

    def test_route_json(self):
        import subprocess
        result = subprocess.run(
            [
                sys.executable, str(_scripts / "orca_model_router.py"),
                "route", "--role", "builder", "--risk", "medium",
                "--no-probe", "--json",
            ],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["risk"] == "medium"
        assert "recommended" in data
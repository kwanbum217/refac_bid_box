"""
tests/test_orca_model_router.py

orca_model_router.py 모델 라우터 유닛 테스트.
테스트 환경에서는 실제 모델 하위 프로세스 호출이 0회임을 monkeypatch 로 보장합니다.
"""

from __future__ import annotations

import argparse
import json
import multiprocessing
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_scripts = Path(__file__).resolve().parent.parent / "scripts"
if str(_scripts) not in sys.path:
    sys.path.insert(0, str(_scripts))

from scripts.orca_model_router import (
    FREE_BUILDER_ORDER,
    FREE_INVESTIGATOR_ORDER,
    FREE_POOL_ELIGIBLE_ROLES,
    FREE_POOL_MAX_RISK,
    FREE_POOL_ORDER,
    INVENTORY_MISSING_THRESHOLD,
    MODEL_POOL,
    PROBE_CONFIG,
    RELIABILITY_WINDOW,
    RISK_KEYWORDS,
    ModelRoutingError,
    RouteResult,
    apply_reliability_history,
    build_probe_env,
    capsule_has_write_scope,
    classify_from_capsule,
    classify_risk,
    classify_risk_with_reasons,
    cmd_classify,
    cmd_list,
    cmd_probe,
    cmd_route,
    free_pool_eligibility,
    is_coordinator_model,
    load_reliability_history,
    load_repo_env,
    main,
    preflight,
    probe_model,
    record_reliability_outcome,
    resolve_kimi_bin,
    route,
    select_model,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def guard_no_real_subprocess(monkeypatch):
    """모든 테스트에서 실제 외부 프로세스 실행이 일어나지 않도록 기본 차단합니다."""

    def _fail_on_unmocked_run(*args, **kwargs):
        raise RuntimeError(
            "테스트에서 실제 subprocess.run 이 호출되었습니다. monkeypatch 가 필요합니다."
        )

    monkeypatch.setattr(subprocess, "run", _fail_on_unmocked_run)


# ---------------------------------------------------------------------------
# 1. 위험도 분류 테스트 (대소문자 무관, 결함 회귀, 근거 기록)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolate_local_history(monkeypatch):
    """배정 테스트를 로컬 관측 이력에서 격리합니다.

    data/model_inventory_history.json 은 Git 미추적이라 환경마다 있고 없고가
    다릅니다. 격리하지 않으면 같은 테스트가 로컬에서는 실패하고 CI 에서는
    통과합니다. 이력 연동 자체는 이력을 명시로 주입해 검증합니다.
    """
    monkeypatch.setattr(
        "scripts.orca_model_router.load_inventory_history",
        lambda path=None: {},
    )
    original_reliability_loader = load_reliability_history
    monkeypatch.setattr(
        "scripts.orca_model_router.load_reliability_history",
        lambda path=None: {} if path is None else original_reliability_loader(path),
    )


def _coordinator_pool_and_id() -> tuple[str, str]:
    """코디네이터를 MODEL_POOL 에서 파생시킵니다.

    테스트에 모델 이름을 박으면 코디네이터를 교체할 때 계약이 아니라 이름
    때문에 깨집니다. 검증해야 하는 것은 "코디네이터로 등록된 것이 워커로
    선택되지 않는다" 이지 그것이 어느 모델인지가 아닙니다.
    """
    pools = [n for n, i in MODEL_POOL.items() if i["tier"] == "coordinator"]
    assert len(pools) == 1, f"코디네이터는 정확히 하나여야 합니다: {pools}"
    return pools[0], MODEL_POOL[pools[0]]["id"]


COORDINATOR_POOL, COORDINATOR_ID = _coordinator_pool_and_id()


class TestClassifyRisk:
    def test_regression_high_risk_drop_delete_db(self):
        """이전 판 결함 회귀 테스트: DROP, DELETE, DB 가 포함된 문장이 모두 high 로 분류됨을 단정합니다."""
        assert classify_risk("DROP unused index on bid table") == "high"
        assert classify_risk("DELETE stale rows from prediction log") == "high"
        assert classify_risk("Fix DB connection pool exhaustion") == "high"

    @pytest.mark.parametrize(
        ("keyword_upper", "keyword_lower"),
        [
            ("DROP", "drop"),
            ("DELETE", "delete"),
            ("DB", "db"),
            ("DATABASE", "database"),
            ("SCHEMA", "schema"),
            ("MIGRATION", "migration"),
            ("MERGE", "merge"),
            ("DEPLOY", "deploy"),
            ("REFACTOR", "refactor"),
            ("OPTIMIZE", "optimize"),
            ("DOC", "doc"),
            ("TEST", "test"),
            ("LINT", "lint"),
        ],
    )
    def test_case_insensitivity(self, keyword_upper, keyword_lower):
        """대소문자 무관 테스트: 동일 키워드의 대문자판과 소문자판이 같은 위험도 등급을 반환합니다."""
        text_upper = f"Task to handle {keyword_upper} operation on workspace"
        text_lower = f"Task to handle {keyword_lower} operation on workspace"
        assert classify_risk(text_upper) == classify_risk(text_lower)

    def test_korean_keywords_high(self):
        assert classify_risk("운영 DB 스키마 마이그레이션 및 배포") == "high"
        assert classify_risk("작업 브랜치 병합 진행") == "high"
        assert classify_risk("모델 승격 및 컷오버") == "high"
        assert classify_risk("재학습 파이프라인 보안 시크릿 점검") == "high"

    def test_korean_keywords_medium(self):
        assert classify_risk("FastAPI 엔드포인트 리팩토링 및 캐시 최적화") == "medium"
        assert classify_risk("환경 설정 파일 및 모델 성능 점검") == "medium"

    def test_korean_keywords_low(self):
        assert classify_risk("README 문서 및 함수 주석 업데이트") == "low"
        assert classify_risk("단위 테스트 작성 및 린트 포맷 수정") == "low"
        assert classify_risk("변수 이름 rename 및 chore 작업") == "low"

    def test_priority_high_over_medium_and_low(self):
        """high 키워드가 있으면 medium/low 키워드가 함께 있어도 high 로 판정합니다."""
        text = "Refactor and write unit test before DB migration and merge"
        risk, reasons = classify_risk_with_reasons(text)
        assert risk == "high"
        assert any("high 키워드 매칭" in r for r in reasons)
        assert "DB" in reasons[0] or "migration" in reasons[0] or "merge" in reasons[0]

    def test_priority_medium_over_low(self):
        """high 키워드가 없고 medium 키워드가 있으면 medium 으로 판정합니다."""
        text = "Update documentation and refactor API endpoint"
        risk, reasons = classify_risk_with_reasons(text)
        assert risk == "medium"
        assert any("medium 키워드 매칭" in r for r in reasons)

    def test_default_low_when_no_keywords(self):
        text = "일반적인 단순 작업"
        risk, reasons = classify_risk_with_reasons(text)
        assert risk == "low"
        assert "기본 위험도: low" in reasons[0]

    def test_all_risk_keywords_defined(self):
        assert "high" in RISK_KEYWORDS
        assert "medium" in RISK_KEYWORDS
        assert "low" in RISK_KEYWORDS
        assert len(RISK_KEYWORDS["high"]) > 0
        assert len(RISK_KEYWORDS["medium"]) > 0
        assert len(RISK_KEYWORDS["low"]) > 0


# ---------------------------------------------------------------------------
# 2. 모델 풀 및 선택 정책 테스트 (코디네이터 거부, 자동 선택 풀 구분)
# ---------------------------------------------------------------------------


class TestModelPoolAndSelection:
    def test_all_pools_have_required_fields(self):
        for pool_name, info in MODEL_POOL.items():
            assert "id" in info, f"{pool_name}: id 누락"
            assert "provider" in info, f"{pool_name}: provider 누락"
            assert "tier" in info, f"{pool_name}: tier 누락"
            assert "auto_selectable" in info, f"{pool_name}: auto_selectable 누락"
            assert "suitable_for" in info, f"{pool_name}: suitable_for 누락"
            assert "notes" in info, f"{pool_name}: notes 누락"

    def test_coordinator_model_rejection_properties(self):
        """코디네이터로 등록된 것은 어떤 경우에도 워커로 선택되어서는 안 됩니다."""
        assert is_coordinator_model(COORDINATOR_ID) is True
        assert is_coordinator_model(COORDINATOR_POOL) is True
        assert MODEL_POOL[COORDINATOR_POOL]["auto_selectable"] is False
        assert MODEL_POOL[COORDINATOR_POOL]["suitable_for"] == []
        assert MODEL_POOL["claude-opus"]["tier"] == "coordinator_reserve"
        assert is_coordinator_model("claude-opus") is True
        assert is_coordinator_model("claude-opus-5") is True

    def test_select_model_never_returns_coordinator(self):
        """모든 역할과 위험도 조합에서 select_model 은 코디네이터 모델을 반환하지 않습니다."""
        roles = ["builder", "reviewer", "investigator", "benchmarker", "documenter", "unknown"]
        risks = ["high", "medium", "low"]
        for r in roles:
            for k in risks:
                res = select_model(r, k)
                assert res["primary_model"] != COORDINATOR_ID
                assert res["primary_pool"] != COORDINATOR_POOL
                assert res["fallback_model"] != COORDINATOR_ID
                assert res["fallback_pool"] != COORDINATOR_POOL

    def test_select_model_high_risk_reviewer(self):
        res = select_model("reviewer", "high")
        assert res["primary_pool"] == "claude-sonnet"
        assert res["primary_model"] == "claude-sonnet-4-6"
        assert res["fallback_pool"] == "gemini-flash-high"
        assert res["fallback_model"] == "gemini-3.7-flash-high"

    def test_select_model_high_risk_builder(self):
        res = select_model("builder", "high")
        assert res["primary_pool"] == "gemini-flash-high"
        assert res["fallback_pool"] == "claude-sonnet"

    def test_select_model_documenter_low_risk(self):
        """공식 문서가 low 등급 용도로 초안 작성과 빠른 분석을 규정합니다."""
        res = select_model("documenter", "low")
        assert res["primary_pool"] == "gemini-flash-low"
        assert res["fallback_pool"] == "gemini-flash-medium"

    def test_select_model_investigator(self):
        """medium 이 문서상 기본값이므로 medium 위험도의 주 모델입니다."""
        res = select_model("investigator", "medium")
        assert res["primary_pool"] == "gemini-flash-medium"
        assert res["fallback_pool"] == "gemini-flash-high"

    def test_select_model_exclude_filtering(self):
        res = select_model("builder", "high", exclude=["gemini-flash-high"])
        assert res["primary_pool"] == "claude-sonnet"
        assert res["fallback_pool"] is None

    def test_select_model_all_candidates_excluded_raises_model_routing_error(self):
        """후보가 전부 제외되면 기본 모델로 부활하지 않고 ModelRoutingError 가 발생합니다."""
        with pytest.raises(ModelRoutingError) as exc_info:
            select_model(
                "builder",
                "high",
                exclude=["gemini-flash-high", "claude-sonnet"],
            )

        err = exc_info.value
        assert err.role == "builder"
        assert err.risk == "high"
        assert "gemini-flash-high" in err.exclude
        assert "claude-sonnet" in err.exclude
        assert "builder" in str(err)
        assert "high" in str(err)
        assert "gemini-flash-high" in str(err)

    def test_select_model_normal_path_regression_preserved(self):
        """제외하지 않은 정상 경로가 종전과 동일한 모델을 반환합니다."""
        res_builder_high = select_model("builder", "high")
        assert res_builder_high["primary_pool"] == "gemini-flash-high"
        assert res_builder_high["primary_model"] == "gemini-3.7-flash-high"
        assert res_builder_high["fallback_pool"] == "claude-sonnet"
        assert res_builder_high["fallback_model"] == "claude-sonnet-4-6"

        res_reviewer_high = select_model("reviewer", "high")
        assert res_reviewer_high["primary_pool"] == "claude-sonnet"
        assert res_reviewer_high["primary_model"] == "claude-sonnet-4-6"
        assert res_reviewer_high["fallback_pool"] == "gemini-flash-high"
        assert res_reviewer_high["fallback_model"] == "gemini-3.7-flash-high"

        res_investigator_low = select_model("investigator", "low")
        assert res_investigator_low["primary_pool"] == "gemini-flash-low"
        assert res_investigator_low["primary_model"] == "gemini-3.7-flash-low"
        assert res_investigator_low["fallback_pool"] == "gemini-flash-medium"
        assert res_investigator_low["fallback_model"] == "gemini-3.7-flash-medium"

    def test_auto_selectable_pools_distinction(self):
        """자동 선택 대상 풀과 비대상 풀이 명확히 구분됨을 검증합니다."""
        auto_pools = {name for name, info in MODEL_POOL.items() if info["auto_selectable"]}
        non_auto_pools = {name for name, info in MODEL_POOL.items() if not info["auto_selectable"]}

        assert auto_pools == {
            "gemini-flash-high",
            "gemini-flash-medium",
            "gemini-flash-low",
            "claude-sonnet",
        }
        assert non_auto_pools == {
            "claude-opus",
            "claude-opus-thinking",
            "codex",
            "opencode-deepseek",
            "cursor-auto",
            "opencode-free",
            "cerebras-oss",
            "cerebras-gemma",
            "or-free-nemotron-ultra",
            "or-free-laguna-s",
            "or-free-laguna-xs",
            "or-free-north-mini",
            "opencode-nemotron3-ultra",
            "opencode-mimo",
        }


# ---------------------------------------------------------------------------
# 3. Probe 및 Preflight 가용성 판정 테스트
# ---------------------------------------------------------------------------


class TestProbeAndPreflight:
    def test_probe_success_with_clean_stdout(self, monkeypatch):
        mock_proc = MagicMock(returncode=0, stdout="ping ok", stderr="")
        monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: mock_proc)

        available, detail = probe_model("gemini-3.7-flash-high")
        assert available is True
        assert detail.startswith("OK (종료 코드 0")

    def test_probe_success_with_warning_in_stderr(self, monkeypatch):
        """종료 코드 0이면서 stderr 에 warning 문구가 있는 경우 사용 가능으로 판정함을 단정합니다."""
        mock_proc = MagicMock(
            returncode=0,
            stdout="pong",
            stderr="UserWarning: deprecation notice\ninfo: update available",
        )
        monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: mock_proc)

        available, detail = probe_model("gemini-3.7-flash-high")
        assert available is True
        assert "OK (종료 코드 0" in detail
        assert "UserWarning" in detail

    def test_probe_failure_empty_stdout_with_zero_returncode(self, monkeypatch):
        """종료 코드가 0이어도 stdout 이 비어 있으면 근거 없는 성공이므로 사용 불가로 판정합니다."""
        mock_proc = MagicMock(returncode=0, stdout="", stderr="")
        monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: mock_proc)

        available, detail = probe_model("gemini-3.7-flash-high")
        assert available is False
        assert "응답 본문(stdout)이 비어 있습니다" in detail

    def test_probe_failure_zero_returncode_with_stderr_error(self, monkeypatch):
        """종료 코드가 0이어도 stderr 에 Error/Failed 가 있으면 거짓 양성을 방지하기 위해 사용 불가로 판정합니다."""
        mock_proc = MagicMock(
            returncode=0,
            stdout="some text",
            stderr="Error: Failed to change directory to /repo/ask",
        )
        monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: mock_proc)

        available, detail = probe_model("codex")
        assert available is False
        assert "stderr 오류 발생" in detail

    def test_probe_config_valid_signatures(self):
        """probe_cmd 가 실제 존재하는 서브커맨드와 플래그를 사용하는지 검증합니다."""
        opencode_cmd = PROBE_CONFIG["opencode"]["probe_cmd"]
        assert opencode_cmd[0] == "opencode"
        assert opencode_cmd[1] == "run"
        assert "--model" in opencode_cmd or "-m" in opencode_cmd
        assert "ask" not in opencode_cmd
        assert "--prompt" not in opencode_cmd
        assert opencode_cmd[-1] == "ping"
        assert PROBE_CONFIG["opencode"]["timeout"] == 60

        codex_cmd = PROBE_CONFIG["codex"]["probe_cmd"]
        assert codex_cmd == ["codex", "exec", "ping"]
        assert PROBE_CONFIG["codex"]["timeout"] == 30

        cerebras_cmd = PROBE_CONFIG["cerebras"]["probe_cmd"]
        assert cerebras_cmd[0] == "opencode"
        assert cerebras_cmd[1] == "run"
        assert "--model" in cerebras_cmd
        assert PROBE_CONFIG["cerebras"]["timeout"] == 20

        for provider in ("gemini", "claude"):
            agy_cmd = PROBE_CONFIG[provider]["probe_cmd"]
            assert agy_cmd[0] == "agy"
            assert "--model" in agy_cmd
            assert "--print" in agy_cmd
            assert "--print-timeout" in agy_cmd

    def test_probe_failure_quota_exceeded(self, monkeypatch):
        mock_proc = MagicMock(
            returncode=1, stdout="", stderr="Error: RESOURCE_EXHAUSTED: quota exceeded 429"
        )
        monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: mock_proc)

        available, detail = probe_model("gemini-3.7-flash-high")
        assert available is False
        assert "할당량 초과" in detail or "quota" in detail

    def test_probe_failure_codex_usage_limit(self, monkeypatch):
        """codex 의 'You've hit your usage limit. Upgrade to Pro' 에러가 할당량 초과로 정상 분류되는지 검증."""
        captured_kwargs = {}

        def _mock_run(*args, **kwargs):
            captured_kwargs.update(kwargs)
            return MagicMock(
                returncode=1,
                stdout="",
                stderr="ERROR: You've hit your usage limit. Upgrade to Pro at https://openai.com or try again at Aug 20th, 2026 12:52 PM.",
            )

        monkeypatch.setattr(subprocess, "run", _mock_run)

        available, detail = probe_model("codex")
        assert available is False
        assert "할당량 초과" in detail
        assert captured_kwargs.get("stdin") == subprocess.DEVNULL

    def test_probe_model_passes_stdin_devnull(self, monkeypatch):
        """probe_model 이 subprocess.run 호출 시 stdin=subprocess.DEVNULL 을 명시적으로 전달하는지 검증."""
        captured_kwargs = {}

        def _mock_run(*args, **kwargs):
            captured_kwargs.update(kwargs)
            return MagicMock(returncode=0, stdout="ping ok", stderr="")

        monkeypatch.setattr(subprocess, "run", _mock_run)

        available, _detail = probe_model("gemini-3.7-flash-high")
        assert available is True
        assert captured_kwargs.get("stdin") == subprocess.DEVNULL

    def test_probe_failure_unauthorized(self, monkeypatch):
        mock_proc = MagicMock(returncode=1, stdout="", stderr="401 Unauthorized: invalid api_key")
        monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: mock_proc)

        available, detail = probe_model("claude-sonnet-4-6")
        assert available is False
        assert "인증 실패" in detail or "auth" in detail

    def test_probe_failure_command_not_found(self, monkeypatch):
        mock_proc = MagicMock(returncode=127, stdout="", stderr="agy: command not found")
        monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: mock_proc)

        available, detail = probe_model("gemini-3.7-flash-high")
        assert available is False
        assert "모델 또는 명령어 없음" in detail or "not found" in detail

    def test_probe_failure_generic(self, monkeypatch):
        mock_proc = MagicMock(returncode=2, stdout="", stderr="Unexpected network glitch")
        monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: mock_proc)

        available, detail = probe_model("gemini-3.7-flash-high")
        assert available is False
        assert "probe 실패 (종료 코드 2)" in detail

    def test_probe_timeout(self, monkeypatch):
        def _raise_timeout(*args, **kwargs):
            raise subprocess.TimeoutExpired(cmd=["agy"], timeout=10)

        monkeypatch.setattr(subprocess, "run", _raise_timeout)
        available, detail = probe_model("gemini-3.7-flash-high", timeout=10)
        assert available is False
        assert "타임아웃" in detail

    def test_probe_file_not_found(self, monkeypatch):
        def _raise_fnf(*args, **kwargs):
            raise FileNotFoundError("No such file or directory: 'agy'")

        monkeypatch.setattr(subprocess, "run", _raise_fnf)
        available, detail = probe_model("gemini-3.7-flash-high")
        assert available is False
        assert "실행 파일 없음" in detail

    def test_preflight_coordinator_rejection(self):
        """preflight 에서 코디네이터 전용 모델은 즉시 거부되어야 합니다."""
        passed, warnings = preflight(COORDINATOR_ID)
        assert passed is False
        assert any("코디네이터 전용 모델" in w for w in warnings)

    def test_preflight_success(self, monkeypatch):
        mock_proc = MagicMock(returncode=0, stdout="pong", stderr="")
        monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: mock_proc)

        passed, warnings = preflight("gemini-3.7-flash-high")
        assert passed is True
        assert len(warnings) == 0

    def test_preflight_free_tier_warning(self, monkeypatch):
        mock_proc = MagicMock(returncode=0, stdout="pong", stderr="")
        monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: mock_proc)

        passed, warnings = preflight("opencode/nemotron-3.5-lightning-free")
        assert passed is True
        assert any("무료 모델" in w for w in warnings)

        passed_pool, warnings_pool = preflight("opencode-free")
        assert passed_pool is True
        assert any("무료 모델" in w for w in warnings_pool)

    def test_preflight_unregistered_model(self, monkeypatch):
        mock_proc = MagicMock(returncode=0, stdout="pong", stderr="")
        monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: mock_proc)

        passed, warnings = preflight("custom-unregistered-model")
        assert passed is True
        assert any("등록되지 않은 모델" in w for w in warnings)


# ---------------------------------------------------------------------------
# 4. Route 통합 테스트 (Capsule 파싱, Fallback 전환, 명시적 지정)
# ---------------------------------------------------------------------------


class TestRoute:
    def test_route_no_probe(self):
        res = route(role="builder", risk="medium", probe=False)
        assert isinstance(res, RouteResult)
        assert res.risk == "medium"
        assert res.role == "builder"
        assert res.primary_model == "gemini-3.7-flash-medium"
        assert res.primary_available is True
        assert res.fallback_available is None

    def test_route_with_objective_and_why_now(self):
        res = route(
            objective="DROP and DELETE unused stale rows from DB",
            why_now="마이그레이션 준비",
            probe=False,
        )
        assert res.risk == "high"
        assert res.primary_model == "gemini-3.7-flash-high"
        assert res.fallback_model == "claude-sonnet-4-6"
        assert len(res.reasons) > 0
        assert any("high 키워드 매칭" in r for r in res.reasons)

    def test_classify_from_capsule_helper(self, tmp_path):
        capsule_file = tmp_path / "test_capsule.yaml"
        capsule_file.write_text(
            "schema: ORCA_TASK_CAPSULE_V2\n"
            "role: investigator\n"
            "objective: >\n"
            "  Investigate performance bottleneck in cache layer.\n"
            "why_now: >\n"
            "  P95 레이턴시 최적화.\n",
            encoding="utf-8",
        )
        info = classify_from_capsule(capsule_file)
        assert info["risk"] == "medium"
        assert info["role"] == "investigator"
        assert "performance" in info["objective"]
        assert len(info["reasons"]) > 0

    def test_probe_config_providers(self):
        for provider in ("gemini", "claude", "opencode", "codex", "cerebras"):
            assert provider in PROBE_CONFIG
            assert "probe_cmd" in PROBE_CONFIG[provider]
            assert "timeout" in PROBE_CONFIG[provider]

    def test_route_with_capsule_file(self, tmp_path):
        capsule_file = tmp_path / "sample_capsule.yaml"
        capsule_file.write_text(
            "schema: ORCA_TASK_CAPSULE_V2\n"
            "role: reviewer\n"
            "objective: >\n"
            "  Review DB schema migration and merge readiness.\n"
            "why_now: >\n"
            "  배포 전 검증.\n",
            encoding="utf-8",
        )
        res = route(capsule_path=capsule_file, probe=False)
        assert res.risk == "high"
        assert res.role == "reviewer"
        assert res.primary_model == "claude-sonnet-4-6"
        assert res.fallback_model == "gemini-3.7-flash-high"

    def test_route_primary_fail_fallback_success(self, monkeypatch):
        """주 모델이 실패하고 대체 모델이 성공할 때 대체 모델로 전환됨을 확인합니다."""

        def _mock_run(cmd, *args, **kwargs):
            if "gemini-3.7-flash-high" in cmd:
                return MagicMock(returncode=1, stdout="", stderr="quota exhausted 429")
            return MagicMock(returncode=0, stdout="ok", stderr="")

        monkeypatch.setattr(subprocess, "run", _mock_run)

        res = route(role="builder", risk="high", probe=True)
        assert res.primary_available is False
        assert res.fallback_available is True
        assert any("대체 모델" in w and "전환" in w for w in res.warnings)

    def test_route_explicit_coordinator_model_rejected(self):
        """explicit_model 로 코디네이터가 주어지면 ValueError 로 거부합니다."""
        with pytest.raises(ValueError, match="코디네이터 전용 모델은 워커로 지정할 수 없습니다"):
            route(explicit_model=COORDINATOR_ID, probe=False)
        with pytest.raises(ValueError, match="코디네이터 전용 모델은 워커로 지정할 수 없습니다"):
            route(explicit_model="claude-opus-5", probe=False)


# ---------------------------------------------------------------------------
# 5. CLI 명령어 테스트 (list, classify, probe, route)
# ---------------------------------------------------------------------------


class TestCLI:
    def test_list_command_distinguishes_auto_select(self, capsys):
        parser = argparse.ArgumentParser()
        parser.add_argument("--json", action="store_true")
        args = parser.parse_args([])

        ret = cmd_list(args)
        assert ret == 0
        captured = capsys.readouterr().out

        # 자동 선택 대상 풀
        assert "gemini-flash-high" in captured
        assert "자동 선택: 대상" in captured

        # 자동 선택 비대상 풀 및 사유
        assert "claude-opus" in captured
        assert "자동 선택: 비대상 (코디네이터 전용 - 워커 사용 불가)" in captured
        assert "codex" in captured
        assert "자동 선택: 비대상 (수동 지정 전용)" in captured
        assert "opencode-free" in captured

    def test_classify_json(self, capsys):
        parser = argparse.ArgumentParser()
        parser.add_argument("--capsule", default=None)
        parser.add_argument("--role", default="builder")
        parser.add_argument("--objective", default="DB schema migration")
        parser.add_argument("--why-now", default="마이그레이션")
        parser.add_argument("--json", action="store_true", default=True)
        args = parser.parse_args([])

        ret = cmd_classify(args)
        assert ret == 0
        captured = capsys.readouterr().out
        data = json.loads(captured)
        assert data["risk"] == "high"
        assert data["primary_model"] == "gemini-3.7-flash-high"
        assert len(data["reasons"]) > 0

    def test_classify_text(self, capsys):
        parser = argparse.ArgumentParser()
        parser.add_argument("--capsule", default=None)
        parser.add_argument("--role", default="documenter")
        parser.add_argument("--objective", default="문서 작성")
        parser.add_argument("--why-now", default="가이드")
        parser.add_argument("--json", action="store_true", default=False)
        args = parser.parse_args([])

        ret = cmd_classify(args)
        assert ret == 0
        captured = capsys.readouterr().out
        assert "위험도:       low" in captured
        assert "주 모델:      gemini-3.7-flash-low" in captured

    def test_probe_cli_success(self, monkeypatch, capsys):
        mock_proc = MagicMock(returncode=0, stdout="ok", stderr="")
        monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: mock_proc)

        parser = argparse.ArgumentParser()
        parser.add_argument("--model", default="gemini-3.7-flash-high")
        parser.add_argument("--timeout", type=int, default=30)
        parser.add_argument("--json", action="store_true", default=True)
        args = parser.parse_args([])

        ret = cmd_probe(args)
        assert ret == 0
        data = json.loads(capsys.readouterr().out)
        assert data["available"] is True

    def test_route_cli_json(self, capsys):
        parser = argparse.ArgumentParser()
        parser.add_argument("--capsule", default=None)
        parser.add_argument("--role", default="builder")
        parser.add_argument("--risk", default="medium")
        parser.add_argument("--objective", default=None)
        parser.add_argument("--why-now", default=None)
        parser.add_argument("--model", default=None)
        parser.add_argument("--no-probe", action="store_true", default=True)
        parser.add_argument("--probe-timeout", type=int, default=30)
        parser.add_argument("--json", action="store_true", default=True)
        args = parser.parse_args([])

        ret = cmd_route(args)
        assert ret == 0
        data = json.loads(capsys.readouterr().out)
        assert data["risk"] == "medium"
        assert data["recommended"] == "gemini-3.7-flash-medium"

    def test_route_cli_coordinator_model_rejected(self, capsys):
        parser = argparse.ArgumentParser()
        parser.add_argument("--capsule", default=None)
        parser.add_argument("--role", default="builder")
        parser.add_argument("--risk", default="medium")
        parser.add_argument("--objective", default=None)
        parser.add_argument("--why-now", default=None)
        parser.add_argument("--model", default=COORDINATOR_ID)
        parser.add_argument("--no-probe", action="store_true", default=True)
        parser.add_argument("--probe-timeout", type=int, default=30)
        parser.add_argument("--json", action="store_true", default=True)
        args = parser.parse_args([])

        ret = cmd_route(args)
        assert ret == 1
        data = json.loads(capsys.readouterr().out)
        assert "error" in data
        assert "코디네이터 전용 모델" in data["error"]

    def test_route_cli_model_routing_error_json(self, monkeypatch, capsys):
        def _raise_error(*args, **kwargs):
            raise ModelRoutingError("후보 없음", role="builder", risk="high", exclude=["a"])

        monkeypatch.setattr("scripts.orca_model_router.select_model", _raise_error)

        parser = argparse.ArgumentParser()
        parser.add_argument("--capsule", default=None)
        parser.add_argument("--role", default="builder")
        parser.add_argument("--risk", default="high")
        parser.add_argument("--objective", default=None)
        parser.add_argument("--why-now", default=None)
        parser.add_argument("--model", default=None)
        parser.add_argument("--no-probe", action="store_true", default=True)
        parser.add_argument("--probe-timeout", type=int, default=30)
        parser.add_argument("--json", action="store_true", default=True)
        args = parser.parse_args([])

        ret = cmd_route(args)
        assert ret == 1
        data = json.loads(capsys.readouterr().out)
        assert "error" in data
        assert "후보 없음" in data["error"]

    def test_classify_cli_model_routing_error_json(self, monkeypatch, capsys):
        def _raise_error(*args, **kwargs):
            raise ModelRoutingError("후보 없음", role="builder", risk="high", exclude=["a"])

        monkeypatch.setattr("scripts.orca_model_router.select_model", _raise_error)

        parser = argparse.ArgumentParser()
        parser.add_argument("--capsule", default=None)
        parser.add_argument("--role", default="builder")
        parser.add_argument("--objective", default="test")
        parser.add_argument("--why-now", default="test")
        parser.add_argument("--json", action="store_true", default=True)
        args = parser.parse_args([])

        ret = cmd_classify(args)
        assert ret == 1
        data = json.loads(capsys.readouterr().out)
        assert "error" in data
        assert "후보 없음" in data["error"]

    def test_main_cli_list_dispatch(self, capsys):
        ret = main(["list"])
        assert ret == 0
        captured = capsys.readouterr().out
        assert "등록된 모델 풀:" in captured

    def test_main_cli_classify_dispatch(self, capsys):
        ret = main(["classify", "--objective", "test", "--json"])
        assert ret == 0
        data = json.loads(capsys.readouterr().out)
        assert "risk" in data


# ---------------------------------------------------------------------------
# 6. 저가·무료 모델 풀 조건부 개방 (allow_free) 테스트
# ---------------------------------------------------------------------------


class TestFreePoolOptIn:
    def test_free_pool_constants(self):
        assert frozenset({"investigator", "builder"}) == FREE_POOL_ELIGIBLE_ROLES
        assert FREE_POOL_MAX_RISK == "low"
        # 2026-08-21 재측정(3차) 이후의 builder 순서입니다. 속도 순위가 아니라
        # 가장 최근에 관측된 실패율 순입니다. 근거는 orca_model_router.py 의
        # FREE_BUILDER_ORDER 주석과 benchmarks/free_workers/results/ 입니다.
        assert FREE_BUILDER_ORDER == [
            "opencode-deepseek",
            "opencode-mimo",
            "opencode-nemotron3-ultra",
            "or-free-nemotron-ultra",
            "or-free-laguna-xs",
            "cerebras-oss",
            "cursor-auto",
        ]
        # FREE_POOL_ORDER 는 builder 순서의 하위 호환 별칭입니다.
        assert FREE_POOL_ORDER == FREE_BUILDER_ORDER
        # investigator 순서는 builder 실측으로 바꾸지 않습니다. 2026-08-21
        # 재측정에서 builder 만 재정렬했으므로 두 순서는 값이 달라야 합니다.
        assert FREE_INVESTIGATOR_ORDER != FREE_BUILDER_ORDER
        # 실격 4종은 후보에서 빠져 있어야 합니다.
        for disqualified in (
            "or-free-laguna-s",
            "or-free-north-mini",
            "opencode-free",
        ):
            assert disqualified not in FREE_POOL_ORDER
        assert "codex" not in FREE_POOL_ORDER
        assert "reviewer" not in FREE_POOL_ELIGIBLE_ROLES

    def test_free_model_id_and_provider_properties(self):
        """무료 모델 ID 형식(provider/model) 및 codex 독립 프로바이더 검증."""
        deepseek_info = MODEL_POOL["opencode-deepseek"]
        assert "/" in deepseek_info["id"]
        assert deepseek_info["id"] == "opencode/deepseek-v4-flash-free"
        assert deepseek_info["provider"] == "opencode"
        assert deepseek_info["tier"] == "free"
        assert deepseek_info["auto_selectable"] is False
        assert deepseek_info["max_tokens"] == 1_000_000
        # 잰 역할만 부여합니다. 2026-08-20 경합이 측정한 것은 builder 이고,
        # investigator 는 코드를 정확히 읽어야 완주하므로 포섭됩니다.
        # benchmarker 와 documenter 는 무료 풀 전체에서 회수했습니다.
        assert set(deepseek_info["suitable_for"]) == {"investigator", "builder"}
        assert "reviewer" not in deepseek_info["suitable_for"]

        # 2026-08-20 builder 경합 결과입니다. 통과한 둘만 쓰기 역할을 받고,
        # 실격한 둘은 suitable_for 가 비어 배정되지 않습니다.
        for pool_name in (
            "or-free-nemotron-ultra",
            "or-free-laguna-s",
            "or-free-laguna-xs",
            "or-free-north-mini",
        ):
            info = MODEL_POOL[pool_name]
            assert info["provider"] == "kimi-openrouter"
            assert info["tier"] == "free"
            assert info["auto_selectable"] is False
            # reviewer 는 병합 판정에 쓰이는 임계 경로라 무료 풀에 열지 않습니다.
            assert "reviewer" not in info["suitable_for"]

        for passed in ("or-free-nemotron-ultra", "or-free-laguna-xs"):
            assert set(MODEL_POOL[passed]["suitable_for"]) == {"investigator", "builder"}

        # laguna-s 는 결정 불능(32분 도구 호출 0건), north-mini 는 속도 초과
        # (31분50초, 실격선 28분)로 배정 대상에서 빠졌습니다.
        for failed in ("or-free-laguna-s", "or-free-north-mini"):
            assert MODEL_POOL[failed]["suitable_for"] == []

        free_info = MODEL_POOL["opencode-free"]
        assert "/" in free_info["id"]
        assert free_info["id"] == "opencode/nemotron-3.5-lightning-free"
        assert free_info["provider"] == "opencode"
        assert free_info["tier"] == "free"
        assert free_info["auto_selectable"] is False
        # 2026-08-20 실측에서 4.8KB 지시문에 무의미 출력을 냈습니다. 짧은
        # 입력에는 정상 응답하므로 probe 로는 걸러지지 않아, 배정 대상에서
        # 명시적으로 빼야 합니다.
        assert free_info["suitable_for"] == []

        # 2026-08-20 경합을 통과해 새로 등록된 OpenCode 무료 2종입니다.
        for pool_name in ("opencode-nemotron3-ultra", "opencode-mimo"):
            info = MODEL_POOL[pool_name]
            assert info["provider"] == "opencode"
            assert info["tier"] == "free"
            assert info["auto_selectable"] is False
            assert set(info["suitable_for"]) == {"investigator", "builder"}
            assert "reviewer" not in info["suitable_for"]

        # 무료 풀 어느 항목도 측정하지 않은 역할을 가져서는 안 됩니다.
        for pool_name in FREE_POOL_ORDER:
            roles = set(MODEL_POOL[pool_name]["suitable_for"])
            assert roles <= {"investigator", "builder"}, (
                f"{pool_name} 이 측정되지 않은 역할 {roles - {'investigator', 'builder'}} 을 갖고 있습니다"
            )

        codex_info = MODEL_POOL["codex"]
        assert codex_info["provider"] == "codex"
        # Codex 는 Terra Medium 기본 코디네이터입니다. 코디네이터는 워커 역할을
        # 겸하지 않으므로 suitable_for 가 비어 있어야 합니다. 자기 자신에게
        # 배정하면 위임이 아니라서 코디네이터 토큰이 줄지 않습니다.
        assert codex_info["tier"] == "coordinator"
        assert codex_info["id"] == "gpt-5.6-terra"
        assert codex_info["suitable_for"] == []
        assert codex_info["auto_selectable"] is False

    def test_cerebras_pool_properties(self):
        """cerebras-oss 풀의 속성, ID 형식 및 메타데이터 검증."""
        c_info = MODEL_POOL["cerebras-oss"]
        assert "/" in c_info["id"]
        assert c_info["id"] == "cerebras/gpt-oss-120b"
        assert c_info["provider"] == "cerebras"
        assert c_info["tier"] == "free"
        assert c_info["auto_selectable"] is False
        assert c_info["max_tokens"] == 65536
        assert "65536" in c_info["notes"]
        assert "8192" in c_info["notes"]
        assert "Capsule" in c_info["notes"]

    def test_cerebras_gemma_notes_mention_rpm_5(self):
        """cerebras-gemma 의 notes 가 공식 문서 기준 무료 등급 제약(RPM 5)을 언급합니다."""
        g_info = MODEL_POOL["cerebras-gemma"]
        assert g_info["provider"] == "cerebras"
        assert g_info["tier"] == "free"
        assert "RPM" in g_info["notes"]
        assert "5회" in g_info["notes"]

    def test_env_injection_and_secret_redaction(self, tmp_path, monkeypatch):
        """환경변수 주입 시 키 값이 로그나 메시지에 노출되지 않고 미설정 사실만 안전하게 전달되는지 검증."""
        # 1. 가상 키가 설정된 경우 (.env 파싱 및 주입)
        fake_key = "test_cerebras_secret_key_abcdef123456"
        env_file = tmp_path / ".env"
        env_file.write_text(f'CEREBRAS_API_KEY="{fake_key}"\nOTHER_KEY="foo"\n', encoding="utf-8")

        repo_vars = load_repo_env(tmp_path)
        assert repo_vars["CEREBRAS_API_KEY"] == fake_key

        env, status = build_probe_env(tmp_path)
        assert env["CEREBRAS_API_KEY"] == fake_key
        assert fake_key not in str(status)

        # 2. 키가 미설정된 경우
        empty_dir = tmp_path / "empty_repo"
        empty_dir.mkdir()
        monkeypatch.delenv("CEREBRAS_API_KEY", raising=False)

        _env_empty, status_empty = build_probe_env(empty_dir)
        assert "CEREBRAS_API_KEY 미설정" in status_empty
        assert fake_key not in str(status_empty)

        # 3. 키 미설정 상태에서 cerebras probe 호출 시 미설정 에러 메시지 반환 검증
        ok, detail = probe_model("cerebras/gpt-oss-120b", repo_root=empty_dir)
        assert ok is False
        assert "CEREBRAS_API_KEY 미설정" in detail
        assert fake_key not in detail

    @pytest.fixture
    def cerebras_key_present(self, monkeypatch):
        """`.env` 유무와 무관하게 Cerebras 키가 있는 상태를 고정합니다.

        저장소 `.env` 를 읽는 경로를 대체하지 않으면 격리 워크트리처럼 `.env`
        가 없는 환경에서 probe 가 실패해 테스트가 환경에 좌우됩니다.
        """
        import scripts.orca_model_router as router

        monkeypatch.setattr(
            router, "load_repo_env", lambda repo_root=None: {"CEREBRAS_API_KEY": "test-key"}
        )

    def test_small_context_limit_warning(self, monkeypatch, cerebras_key_present):
        """max_tokens 가 있는 풀(숫자 포함)과 max_tokens 가 None 인 free 풀(한도 미확인) 모두 적절한 한도 경고가 발행되는지 검증."""
        mock_proc = MagicMock(returncode=0, stdout="ping ok", stderr="")
        monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: mock_proc)

        # 1. max_tokens 가 있는 풀 (cerebras: 65536) -> 숫자(65536) 포함
        passed_c, warnings_c = preflight("cerebras/gpt-oss-120b")
        assert passed_c is True
        assert any(
            "200,000 미만" in w and "Capsule 과 diff" in w and "65536" in w for w in warnings_c
        )

        res_c = route(explicit_model="cerebras/gpt-oss-120b", probe=False)
        assert any(
            "200,000 미만" in w and "Capsule 과 diff" in w and "65536" in w for w in res_c.warnings
        )

        # 2. max_tokens 가 None 인 free 풀 (opencode-free: None) -> 한도 미확인 경고
        passed_f, warnings_f = preflight("opencode/nemotron-3.5-lightning-free")
        assert passed_f is True
        assert any(
            "컨텍스트 한도가 확인되지 않았습니다" in w and "Capsule 과 diff" in w
            for w in warnings_f
        )

        # 기본 무료 주 모델 opencode-deepseek 는 max_tokens 1,000,000 이므로
        # 한도 경고 없이 재검증 필수 경고만 발행합니다.
        res_f = route(
            role="investigator", risk="low", allow_free=True, has_write_scope=False, probe=False
        )
        assert res_f.primary_model == "opencode/deepseek-v4-flash-free"
        assert any("산출물 재검증 필수" in w for w in res_f.warnings)

        res_none = route(explicit_model="opencode/nemotron-3.5-lightning-free", probe=False)
        assert any(
            "컨텍스트 한도가 확인되지 않았습니다" in w and "Capsule 과 diff" in w
            for w in res_none.warnings
        )

    def test_capsule_has_write_scope_scenarios(self, tmp_path):
        """allowed_write_files 여부에 따른 쓰기 범위 판정 및 fail-closed 검증."""
        # 1. 빈 allowed_write_files -> 쓰기 범위 없음 (False)
        empty_write_capsule = tmp_path / "capsule_readonly.yaml"
        empty_write_capsule.write_text(
            "schema: ORCA_TASK_CAPSULE_V2\n"
            "role: investigator\n"
            "objective: Readonly cache analysis\n"
            "allowed_write_files: []\n",
            encoding="utf-8",
        )
        assert capsule_has_write_scope(empty_write_capsule) is False

        # 2. 파일 목록이 있는 allowed_write_files -> 쓰기 범위 있음 (True)
        write_capsule = tmp_path / "capsule_write.yaml"
        write_capsule.write_text(
            "schema: ORCA_TASK_CAPSULE_V2\n"
            "role: investigator\n"
            "objective: Fix cache analysis\n"
            "allowed_write_files:\n"
            '  - "src/ml/..."\n',
            encoding="utf-8",
        )
        assert capsule_has_write_scope(write_capsule) is True

        # 3. 없는 파일 경로 -> fail-closed (True)
        non_existent = tmp_path / "missing_file.yaml"
        assert capsule_has_write_scope(non_existent) is True

        # 4. None 경로 -> fail-closed (True)
        assert capsule_has_write_scope(None) is True

    def test_free_pool_eligibility_unit(self):
        """free_pool_eligibility 헬퍼의 조건별 통과/거부 및 한국어 사유 검증."""
        # 통과 조건: investigator, low, has_write_scope=False
        eligible, reason = free_pool_eligibility("investigator", "low", False)
        assert eligible is True
        assert "조건 충족" in reason

        # 통과 2: builder 도 무료 풀 개방 대상입니다.
        eligible, reason = free_pool_eligibility("builder", "low", False)
        assert eligible is True
        assert "조건 충족" in reason

        # 통과 3: 쓰기 범위가 있어도 거부하지 않으며 사유에 병합 전 검증 필수를 남깁니다.
        eligible, reason = free_pool_eligibility("investigator", "low", True)
        assert eligible is True
        assert "병합 전 검증 필수" in reason

        # 거부 1: 역할 불일치 (reviewer)
        eligible, reason = free_pool_eligibility("reviewer", "low", False)
        assert eligible is False
        assert "역할(reviewer)" in reason
        assert "investigator" in reason
        assert "builder" in reason

        # 거부 2: 위험도 초과 (high)
        eligible, reason = free_pool_eligibility("investigator", "high", False)
        assert eligible is False
        assert "위험도(high)" in reason

        # 거부 3: 위험도 초과 (medium)
        eligible, reason = free_pool_eligibility("investigator", "medium", False)
        assert eligible is False
        assert "위험도(medium)" in reason

    def test_allow_free_false_never_selects_free_pool(self):
        """allow_free=False 인 경우 어떤 역할, 위험도, 쓰기 범위에서도 무료 풀이 선택되지 않습니다."""
        roles = ["investigator", "builder", "reviewer", "benchmarker", "documenter"]
        risks = ["low", "medium", "high"]
        scopes = [True, False]

        for r in roles:
            for k in risks:
                for s in scopes:
                    res = select_model(r, k, allow_free=False, has_write_scope=s)
                    assert res["primary_pool"] != "opencode-free"
                    assert res["primary_model"] != "opencode/nemotron-3.5-lightning-free"
                    assert res["fallback_pool"] != "opencode-free"
                    assert res["fallback_model"] != "opencode/nemotron-3.5-lightning-free"
                    assert res["primary_pool"] != "opencode-deepseek"
                    assert res["primary_model"] != "opencode/deepseek-v4-flash-free"
                    assert res["fallback_pool"] != "opencode-deepseek"
                    assert res["fallback_model"] != "opencode/deepseek-v4-flash-free"
                    assert res["primary_pool"] != "cerebras-oss"
                    assert res["fallback_pool"] != "cerebras-oss"

    def test_allow_free_true_investigator_low_risk_no_write_scope_selects_free_primary(self):
        """allow_free=True, investigator, low, 쓰기 없음 조합에서 FREE_INVESTIGATOR_ORDER 1순위와 2순위가 주/대체 모델로 지정됩니다."""
        res = select_model("investigator", "low", allow_free=True, has_write_scope=False)
        assert res["primary_pool"] == FREE_INVESTIGATOR_ORDER[0]
        assert res["primary_model"] == MODEL_POOL[FREE_INVESTIGATOR_ORDER[0]]["id"]
        assert res["fallback_pool"] == FREE_INVESTIGATOR_ORDER[1]
        assert res["fallback_model"] == MODEL_POOL[FREE_INVESTIGATOR_ORDER[1]]["id"]

    def test_allow_free_true_builder_low_risk_allowed(self):
        """allow_free=True, builder, low 는 무료 풀이 허용됩니다. 주 모델로 opencode/deepseek-v4-flash-free 가 선택되고 재검증 경고가 기록됩니다."""
        res = route(role="builder", risk="low", allow_free=True, probe=False)
        assert res.primary_model == "opencode/deepseek-v4-flash-free"
        assert res.primary_model != "opencode/nemotron-3.5-lightning-free"
        assert any("산출물 재검증 필수" in w for w in res.warnings)

    def test_allow_free_true_high_risk_rejected(self):
        """allow_free=True 여도 high/medium 위험도는 무료 풀이 거부됩니다."""
        res_high = route(
            role="investigator", risk="high", allow_free=True, has_write_scope=False, probe=False
        )
        assert res_high.primary_model != "opencode/nemotron-3.5-lightning-free"
        assert any("위험도(high)" in w for w in res_high.warnings)

        res_med = route(
            role="investigator", risk="medium", allow_free=True, has_write_scope=False, probe=False
        )
        assert res_med.primary_model != "opencode/nemotron-3.5-lightning-free"
        assert any("위험도(medium)" in w for w in res_med.warnings)

    def test_allow_free_true_with_write_scope_allowed(self):
        """allow_free=True 일 때 쓰기 범위가 있어도 무료 풀이 거부되지 않습니다. free_pool_eligibility 가 허용하며 사유에 병합 전 검증 필수를 남깁니다."""
        eligible, reason = free_pool_eligibility("investigator", "low", True)
        assert eligible is True
        assert "병합 전 검증 필수" in reason

        res = route(
            role="investigator", risk="low", allow_free=True, has_write_scope=True, probe=False
        )
        assert res.primary_model == "opencode/deepseek-v4-flash-free"
        assert any("산출물 재검증 필수" in w for w in res.warnings)

    def test_allow_free_true_reviewer_rejected(self):
        """reviewer 는 읽기 전용이어도 임계 경로이므로 allow_free=True 여도 무료 풀이 거부됩니다."""
        res = route(
            role="reviewer", risk="low", allow_free=True, has_write_scope=False, probe=False
        )
        assert res.primary_model != "opencode/nemotron-3.5-lightning-free"
        assert any("역할(reviewer)" in w for w in res.warnings)

    def test_free_pool_selected_includes_revalidation_mandatory_warning(self):
        """무료 풀이 주 모델로 선택되면 산출물 재검증 필수 및 임계 경로 금지 경고가 반드시 포함됩니다."""
        res = route(
            role="investigator", risk="low", allow_free=True, has_write_scope=False, probe=False
        )
        assert res.primary_model == "opencode/deepseek-v4-flash-free"
        assert any("산출물 재검증 필수" in w and "임계 경로 금지" in w for w in res.warnings)

    def test_allow_free_true_never_selects_coordinator_model(self):
        """allow_free=True 상태에서도 코디네이터는 절대 선택되지 않습니다."""
        res = select_model("investigator", "low", allow_free=True, has_write_scope=False)
        assert res["primary_model"] != COORDINATOR_ID
        assert res["fallback_model"] != COORDINATOR_ID

    def test_route_free_pool_primary_fail_fallback(self, monkeypatch, cerebras_key_present):
        """무료 1순위가 probe 실패하면 2순위로 fallback 전환됨을 검증합니다."""

        def _mock_run(cmd, *args, **kwargs):
            if "opencode/deepseek-v4-flash-free" in cmd:
                return MagicMock(returncode=1, stdout="", stderr="Error: model unavailable")
            return MagicMock(returncode=0, stdout="ping ok", stderr="")

        monkeypatch.setattr(subprocess, "run", _mock_run)

        res = route(
            role="investigator", risk="low", allow_free=True, has_write_scope=False, probe=True
        )
        assert res.primary_available is False
        assert res.fallback_available is True
        assert res.fallback_model == "or-free/laguna-xs"
        assert any("대체 모델 or-free/laguna-xs 로 전환" in w for w in res.warnings)

    def test_route_with_capsule_file_allow_free(self, tmp_path):
        """Capsule 파일을 통한 route 에서 allow_free 조건부 개방 검증."""
        # 쓰기 없는 읽기 전용 Capsule (low 위험도)
        ro_capsule = tmp_path / "investigator_ro.yaml"
        ro_capsule.write_text(
            "schema: ORCA_TASK_CAPSULE_V2\n"
            "role: investigator\n"
            "objective: >\n"
            "  Investigate doc and typo details without modifications.\n"
            "why_now: >\n"
            "  단순 문서 조사.\n"
            "allowed_write_files: []\n",
            encoding="utf-8",
        )
        res_ro = route(capsule_path=ro_capsule, allow_free=True, probe=False)
        assert res_ro.risk == "low"
        assert res_ro.role == "investigator"
        assert res_ro.primary_model == "opencode/deepseek-v4-flash-free"

        # 쓰기 있는 Capsule: 쓰기 범위가 있어도 무료 풀이 허용되며 재검증 경고가 기록됩니다.
        rw_capsule = tmp_path / "investigator_rw.yaml"
        rw_capsule.write_text(
            "schema: ORCA_TASK_CAPSULE_V2\n"
            "role: investigator\n"
            "objective: >\n"
            "  Investigate and modify test file.\n"
            "why_now: >\n"
            "  수정 포함 조사.\n"
            "allowed_write_files:\n"
            '  - "tests/test_foo.py"\n',
            encoding="utf-8",
        )
        res_rw = route(capsule_path=rw_capsule, allow_free=True, probe=False)
        assert res_rw.primary_model == "opencode/deepseek-v4-flash-free"
        assert any("산출물 재검증 필수" in w for w in res_rw.warnings)

    def test_cli_route_allow_free_json(self, tmp_path, capsys):
        """CLI route 서브커맨드에서 --allow-free 플래그 전달 시 JSON 출력 검증."""
        capsule_file = tmp_path / "capsule_cli.yaml"
        capsule_file.write_text(
            "schema: ORCA_TASK_CAPSULE_V2\n"
            "role: investigator\n"
            "objective: >\n"
            "  Simple doc check.\n"
            "why_now: >\n"
            "  문서 조사.\n"
            "allowed_write_files: []\n",
            encoding="utf-8",
        )

        parser = argparse.ArgumentParser()
        parser.add_argument("--capsule", default=str(capsule_file))
        parser.add_argument("--role", default="investigator")
        parser.add_argument("--risk", default="low")
        parser.add_argument("--objective", default=None)
        parser.add_argument("--why-now", default=None)
        parser.add_argument("--model", default=None)
        parser.add_argument("--allow-free", action="store_true", default=True)
        parser.add_argument("--no-probe", action="store_true", default=True)
        parser.add_argument("--probe-timeout", type=int, default=30)
        parser.add_argument("--json", action="store_true", default=True)
        args = parser.parse_args([])

        ret = cmd_route(args)
        assert ret == 0
        data = json.loads(capsys.readouterr().out)
        assert data["primary_model"] == "opencode/deepseek-v4-flash-free"
        assert data["recommended"] == "opencode/deepseek-v4-flash-free"
        assert any("산출물 재검증 필수" in w for w in data["warnings"])

    def test_cli_classify_allow_free_json(self, tmp_path, capsys):
        """CLI classify 서브커맨드에서 --allow-free 플래그 전달 시 JSON 출력 검증."""
        capsule_file = tmp_path / "capsule_cls.yaml"
        capsule_file.write_text(
            "schema: ORCA_TASK_CAPSULE_V2\n"
            "role: investigator\n"
            "objective: >\n"
            "  Simple test check.\n"
            "why_now: >\n"
            "  테스트 확인.\n"
            "allowed_write_files: []\n",
            encoding="utf-8",
        )

        parser = argparse.ArgumentParser()
        parser.add_argument("--capsule", default=str(capsule_file))
        parser.add_argument("--role", default="investigator")
        parser.add_argument("--objective", default=None)
        parser.add_argument("--why-now", default=None)
        parser.add_argument("--allow-free", action="store_true", default=True)
        parser.add_argument("--json", action="store_true", default=True)
        args = parser.parse_args([])

        ret = cmd_classify(args)
        assert ret == 0
        data = json.loads(capsys.readouterr().out)
        assert data["primary_model"] == "opencode/deepseek-v4-flash-free"

    def test_list_command_includes_free_pool_guide(self, capsys):
        """CLI list 서브커맨드에서 조건부 개방 안내 문구가 출력되는지 검증."""
        parser = argparse.ArgumentParser()
        args = parser.parse_args([])

        ret = cmd_list(args)
        assert ret == 0
        captured = capsys.readouterr().out
        assert "--allow-free" in captured
        assert "investigator" in captured
        assert "조건부로 개방" in captured


class TestRiskAwareTier:
    """추론 등급이 공식 문서 기준과 위험도를 반영하는지 검증합니다.

    Gemini 3.7 Flash 문서는 medium 을 기본값으로 두고 "복잡한 코드와 에이전트
    용도에 권장" 한다고 적습니다. high 는 "가장 어려운" 추론·코딩 전용이고
    low 는 초안 작성과 빠른 분석용입니다. 2026-08-17 까지 리뷰어와 빌더가
    위험도와 무관하게 항상 high 로 가서 주간 한도를 불필요하게 썼습니다.
    """

    def test_high_tier_is_reserved_for_high_risk(self):
        """high 는 기본값이 아니라 high 위험도 전용입니다."""
        for role in ("builder", "reviewer", "investigator", "documenter"):
            for risk in ("low", "medium"):
                assert select_model(role, risk)["primary_pool"] != "gemini-flash-high"

    def test_builder_medium_risk_uses_medium(self):
        """문서가 복잡한 코드에 권장하는 등급이 medium 입니다."""
        res = select_model("builder", "medium")
        assert res["primary_pool"] == "gemini-flash-medium"
        assert res["fallback_pool"] == "gemini-flash-high"

    def test_builder_high_risk_uses_high(self):
        res = select_model("builder", "high")
        assert res["primary_pool"] == "gemini-flash-high"
        assert res["fallback_pool"] == "claude-sonnet"

    def test_reviewer_never_gets_low_tier_as_primary(self):
        """판정이 병합 결정에 쓰이므로 리뷰어 주 모델은 low 등급이 아닙니다."""
        for risk in ("low", "medium", "high"):
            assert select_model("reviewer", risk)["primary_pool"] != "gemini-flash-low"

    def test_reviewer_high_risk_prefers_claude(self):
        assert select_model("reviewer", "high")["primary_pool"] == "claude-sonnet"

    def test_low_tier_only_for_low_risk_read_or_doc_roles(self):
        """low 등급은 low 위험도 조사와 문서화에만 주 모델이 됩니다."""
        assert select_model("investigator", "low")["primary_pool"] == "gemini-flash-low"
        assert select_model("documenter", "low")["primary_pool"] == "gemini-flash-low"
        assert select_model("builder", "low")["primary_pool"] == "gemini-flash-medium"


def test_flash_low_is_never_assigned_to_reviewer_or_builder():
    """메타데이터가 리뷰어와 빌더에 배정하지 않는다고 명시한 모델은 fallback 에도 없어야 합니다.

    fallback 으로 남겨 두면 주 모델 장애 시 금지한 등급이 코드 작성이나 병합
    판정으로 승격됩니다.
    """
    from scripts.orca_model_router import MODEL_POOL, TIER_POLICY, select_model

    assert "reviewer" not in MODEL_POOL["gemini-flash-low"]["suitable_for"]
    assert "builder" not in MODEL_POOL["gemini-flash-low"]["suitable_for"]

    for (role, risk), candidates in TIER_POLICY.items():
        if role in {"reviewer", "builder"}:
            assert "gemini-flash-low" not in candidates, (role, risk, candidates)

    for role in ("reviewer", "builder"):
        for risk in ("low", "medium", "high"):
            res = select_model(role, risk)
            assert res["primary_pool"] != "gemini-flash-low", res
            assert res["fallback_pool"] != "gemini-flash-low", res


def test_tier_policy_assignments_are_declared_suitable():
    """TIER_POLICY 가 배정하는 모든 (역할, 모델) 조합이 suitable_for 에 있어야 합니다.

    select_model 은 suitable_for 를 검사하지 않으므로 두 정의는 조용히 어긋납니다.
    2026-08-18 대조에서 배정 조합 36개 중 9개가 불일치했습니다. TIER_POLICY 를
    정본으로 삼고 이 테스트로 드리프트를 막습니다.
    """
    from scripts.orca_model_router import TIER_POLICY

    mismatched = [
        (role, effort, model)
        for (role, effort), models in TIER_POLICY.items()
        for model in models
        if role != "__default__" and role not in MODEL_POOL[model]["suitable_for"]
    ]
    assert mismatched == []


def test_tier_policy_models_exist_in_pool():
    """TIER_POLICY 가 가리키는 모델은 전부 MODEL_POOL 에 있어야 합니다."""
    from scripts.orca_model_router import TIER_POLICY

    unknown = [
        (key, model)
        for key, models in TIER_POLICY.items()
        for model in models
        if model not in MODEL_POOL
    ]
    assert unknown == []


def test_probe_resolves_pool_key_to_actual_model_id(monkeypatch):
    """풀 키로 probe 하면 실제 모델 ID 로 CLI 를 불러야 합니다.

    풀 키를 그대로 넘기면 CLI 가 알 수 없는 모델로 거부해, 살아 있는 모델이
    사용 불가로 판정됩니다. list 출력과 문서가 안내하는 이름이 풀 키이므로
    이 경로가 기본 사용법입니다.
    """
    import subprocess

    from scripts.orca_model_router import MODEL_POOL, probe_model

    seen: list[list[str]] = []

    class _Proc:
        returncode = 0
        stdout = "pong"
        stderr = ""

    def fake_run(cmd, **kwargs):
        seen.append(cmd)
        return _Proc()

    monkeypatch.setattr(subprocess, "run", fake_run)

    available, _detail = probe_model("gemini-flash-medium")
    assert available is True
    assert seen, "probe 명령이 실행되지 않았습니다"
    assert MODEL_POOL["gemini-flash-medium"]["id"] in seen[0]
    assert "gemini-flash-medium" not in seen[0]


def test_free_pool_candidates_must_match_role_suitable_for():
    """무료 후보도 역할 적합성을 통과해야 합니다.

    걸러 내지 않으면 investigator 전용 모델이 builder 로 배정됩니다.
    TIER_POLICY 경로는 이미 불변식으로 묶여 있는데 무료 경로만 밖에 있었습니다.
    """
    # builder 를 가진 무료 풀을 전부 빼면 남는 무료 후보는 investigator 전용
    # 뿐입니다. 그때 그 모델이 builder 로 선택되면 안 됩니다. 목록을 손으로
    # 적으면 풀이 바뀔 때마다 어긋나므로 MODEL_POOL 에서 유도합니다.
    from scripts.orca_model_router import FREE_POOL_ORDER, MODEL_POOL, select_model

    builder_capable = [
        name for name in FREE_POOL_ORDER if "builder" in MODEL_POOL[name]["suitable_for"]
    ]
    investigator_only = [
        name for name in FREE_POOL_ORDER if "builder" not in MODEL_POOL[name]["suitable_for"]
    ]
    assert investigator_only, "investigator 전용 무료 풀이 없으면 이 불변식을 검사할 수 없습니다"

    result = select_model(
        "builder",
        "low",
        exclude=builder_capable,
        allow_free=True,
        has_write_scope=True,
    )
    assert "builder" in MODEL_POOL[result["primary_pool"]]["suitable_for"]
    assert result["primary_pool"] not in investigator_only

    # 적합한 무료 모델이 있으면 여전히 우선합니다. 제외 없이 부르면
    # FREE_INVESTIGATOR_ORDER 1순위가 그대로 나와야 합니다.
    investigator = select_model("investigator", "low", allow_free=True, has_write_scope=False)
    assert investigator["primary_pool"] == FREE_INVESTIGATOR_ORDER[0]
    assert "investigator" in MODEL_POOL[investigator["primary_pool"]]["suitable_for"]


def test_every_free_pool_selection_is_role_suitable():
    """무료 풀 개방 대상 역할 전부에서 불변식이 유지되어야 합니다."""
    from scripts.orca_model_router import (
        FREE_POOL_ELIGIBLE_ROLES,
        MODEL_POOL,
        select_model,
    )

    for role in sorted(FREE_POOL_ELIGIBLE_ROLES):
        result = select_model(role, "low", allow_free=True, has_write_scope=False)
        assert role in MODEL_POOL[result["primary_pool"]]["suitable_for"], (
            f"{role} 에 부적합한 모델 {result['primary_pool']} 이 선택됐습니다"
        )
        fallback = result["fallback_pool"]
        if fallback:
            assert role in MODEL_POOL[fallback]["suitable_for"], (
                f"{role} 에 부적합한 fallback {fallback} 이 선택됐습니다"
            )


def test_free_order_by_role_objects_are_distinct():
    """FREE_ORDER_BY_ROLE 의 builder 와 investigator 키는 서로 다른 리스트 객체여야 합니다."""
    from scripts.orca_model_router import FREE_ORDER_BY_ROLE

    assert FREE_ORDER_BY_ROLE["builder"] is not FREE_ORDER_BY_ROLE["investigator"], (
        "builder 와 investigator 순서가 같은 리스트 객체를 가리킵니다"
    )


def test_select_model_responds_independently_to_role_order_changes(monkeypatch):
    """FREE_ORDER_BY_ROLE 의 두 순서를 서로 다르게 바꾸면 select_model 이
    역할별로 다른 주 모델을 골라야 합니다. builder 실측 갱신이 investigator 배정까지
    전파되지 않는다는 것을 증명하는 회귀 테스트입니다."""
    from scripts.orca_model_router import FREE_ORDER_BY_ROLE, select_model

    # builder 는 무료 풀 첫 번째, investigator 는 무료 풀 마지막으로 설정
    builder_order = list(FREE_ORDER_BY_ROLE["builder"])
    investigator_order = list(reversed(FREE_ORDER_BY_ROLE["investigator"]))

    monkeypatch.setattr(
        "scripts.orca_model_router.FREE_ORDER_BY_ROLE",
        {"builder": builder_order, "investigator": investigator_order},
    )

    b = select_model("builder", "low", allow_free=True, has_write_scope=False)
    i = select_model("investigator", "low", allow_free=True, has_write_scope=False)

    assert b["primary_pool"] != i["primary_pool"], (
        "서로 다른 순서를 monkeypatch 했는데도 builder 와 investigator 가 "
        f"같은 모델({b['primary_pool']})을 골랐습니다"
    )


def test_load_inventory_history_missing_file_is_empty(tmp_path):
    """이력 파일이 없으면 빈 이력입니다. 관측이 없는 것을 소멸로 보면 안 됩니다."""
    from scripts.orca_model_router import load_inventory_history

    assert load_inventory_history(tmp_path / "none.json") == {}


def test_load_inventory_history_corrupt_file_is_empty(tmp_path):
    """손상된 이력도 빈 이력입니다. 읽기 실패로 후보를 지우면 안 됩니다."""
    from scripts.orca_model_router import load_inventory_history

    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    assert load_inventory_history(broken) == {}


def test_apply_inventory_history_demotes_suspected_but_keeps_it():
    """의심 상태는 제외가 아니라 강등입니다. 복구되는 사례가 실제로 있었습니다."""
    from scripts.orca_model_router import apply_inventory_history

    candidates = ["a", "b", "c"]
    history = {"a": {"status": "absent", "counter": 1}}
    ranked, notes = apply_inventory_history(candidates, history)

    assert ranked == ["b", "c", "a"], "의심 후보는 뒤로 미루되 남아 있어야 합니다"
    assert any("강등" in n for n in notes)


def test_apply_inventory_history_drops_confirmed_missing():
    """연속 임계값을 넘긴 소멸은 후보에서 뺍니다."""
    from scripts.orca_model_router import apply_inventory_history

    history = {"a": {"status": "absent", "counter": INVENTORY_MISSING_THRESHOLD}}
    ranked, notes = apply_inventory_history(["a", "b"], history)

    assert ranked == ["b"]
    assert any("소멸 판정" in n for n in notes)


def test_apply_inventory_history_present_and_unknown_untouched():
    """present 와 unknown 은 순서를 바꾸지 않습니다."""
    from scripts.orca_model_router import apply_inventory_history

    history = {
        "a": {"status": "present", "counter": 0},
        "b": {"status": "unknown", "counter": 2},
    }
    ranked, notes = apply_inventory_history(["a", "b"], history)

    assert ranked == ["a", "b"]
    assert notes == []


def test_apply_inventory_history_empty_history_is_identity():
    """이력이 없으면 기존 동작 그대로여야 합니다."""
    from scripts.orca_model_router import apply_inventory_history

    ranked, notes = apply_inventory_history(["a", "b"], {})
    assert ranked == ["a", "b"]
    assert notes == []


def test_select_model_demotes_missing_free_candidate(monkeypatch):
    """미관측 무료 후보는 1순위에서 밀려나고 사유가 남습니다."""
    from scripts.orca_model_router import FREE_BUILDER_ORDER, select_model

    first = FREE_BUILDER_ORDER[0]
    monkeypatch.setattr(
        "scripts.orca_model_router.load_inventory_history",
        lambda path=None: {first: {"status": "absent", "counter": 1}},
    )
    res = select_model("builder", "low", allow_free=True, has_write_scope=True)

    assert res["primary_pool"] != first
    assert any(first in note for note in res["inventory_notes"])


def test_select_model_applies_reliability_only_to_matching_role(monkeypatch):
    first = FREE_BUILDER_ORDER[0]
    monkeypatch.setattr(
        "scripts.orca_model_router.load_reliability_history",
        lambda path=None: {first: {"builder": {"recent": [{"ok": False}] * 3}}},
    )

    builder = select_model("builder", "low", allow_free=True, has_write_scope=True)
    investigator = select_model("investigator", "low", allow_free=True, has_write_scope=False)

    assert builder["primary_pool"] != first
    assert investigator["primary_pool"] == first


# ---------------------------------------------------------------------------
# 실행 신뢰도 이력 (rolling reliability)
# ---------------------------------------------------------------------------


class TestReliabilityHistory:
    """실재 이력이 잡지 못하는 "존재하지만 실패한다" 유형을 다룹니다."""

    def _hist(self, tmp_path, payload):
        p = tmp_path / "reliability.json"
        p.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return p

    def test_missing_file_changes_nothing(self, tmp_path):
        """이력이 없는 것을 열화로 해석하면 안 됩니다."""
        got, notes = apply_reliability_history(
            ["a", "b"], "builder", load_reliability_history(tmp_path / "x")
        )
        assert got == ["a", "b"]
        assert notes == []

    def test_broken_json_changes_nothing(self, tmp_path):
        p = tmp_path / "reliability.json"
        p.write_text("{ not json", encoding="utf-8")
        assert load_reliability_history(p) == {}

    def test_too_few_observations_are_ignored(self, tmp_path):
        """n=1~2 로 순위를 흔들지 않습니다. 표본이 적을 때의 재정렬이 이번에 그만둔 실수입니다."""
        hist = {"a": {"builder": {"recent": [{"ok": False}, {"ok": False}]}}}
        got, notes = apply_reliability_history(["a", "b"], "builder", hist)
        assert got == ["a", "b"]
        assert notes == []

    def test_low_success_rate_demotes_but_keeps(self, tmp_path):
        hist = {
            "a": {
                "builder": {"recent": [{"ok": False}, {"ok": True}, {"ok": False}, {"ok": False}]}
            }
        }
        got, notes = apply_reliability_history(["a", "b"], "builder", hist)
        assert got == ["b", "a"], "성공률이 낮은 후보가 뒤로 가지 않았습니다"
        assert any("강등" in n for n in notes)

    def test_consecutive_failures_suspend(self, tmp_path):
        """laguna_xs 가 3회 연속 시한 초과한 형태입니다."""
        hist = {
            "a": {
                "builder": {
                    "recent": [
                        {"ok": True},
                        {"ok": False, "failure": "timeout"},
                        {"ok": False, "failure": "timeout"},
                        {"ok": False, "failure": "timeout"},
                    ]
                }
            }
        }
        got, notes = apply_reliability_history(["a", "b"], "builder", hist)
        assert got == ["b"], "연속 실패 후보가 제외되지 않았습니다"
        assert any("연속 실패" in n for n in notes)

    def test_healthy_stack_untouched(self):
        hist = {"a": {"builder": {"recent": [{"ok": True}] * 5}}}
        got, notes = apply_reliability_history(["a", "b"], "builder", hist)
        assert got == ["a", "b"]
        assert notes == []

    def test_window_drops_old_observations(self):
        """오래된 실패가 영원히 따라다니지 않습니다."""
        recent = [{"ok": False}] * 8 + [{"ok": True}] * RELIABILITY_WINDOW
        hist = {"a": {"builder": {"recent": recent}}}
        got, _notes = apply_reliability_history(["a", "b"], "builder", hist)
        assert got == ["a", "b"], "창 밖의 옛 실패가 아직 반영되고 있습니다"

    def test_record_outcome_accumulates_and_trims(self, tmp_path):
        p = tmp_path / "reliability.json"
        for _ in range(RELIABILITY_WINDOW + 5):
            record_reliability_outcome("a", "builder", ok=True, path=p)
        rec = record_reliability_outcome(
            "a", "builder", ok=False, failure="timeout", elapsed_sec=720, path=p
        )
        assert len(rec["recent"]) == RELIABILITY_WINDOW
        assert rec["recent"][-1]["failure"] == "timeout"
        assert rec["recent"][-1]["elapsed_sec"] == 720

    def test_record_outcome_deduplicates_observation_id(self, tmp_path):
        p = tmp_path / "reliability.json"
        first = record_reliability_outcome(
            "a", "builder", ok=False, observation_id="task:attempt", path=p
        )
        second = record_reliability_outcome(
            "a", "builder", ok=False, observation_id="task:attempt", path=p
        )

        assert first == second
        assert len(second["recent"]) == 1

    def test_relative_order_is_preserved_within_groups(self):
        degraded = [{"ok": False}, {"ok": True}, {"ok": False}, {"ok": False}]
        hist = {
            "b": {"builder": {"recent": degraded}},
            "d": {"builder": {"recent": degraded}},
        }
        got, _ = apply_reliability_history(["a", "b", "c", "d"], "builder", hist)
        assert got == ["a", "c", "b", "d"]

    def test_builder_failures_do_not_change_investigator_order(self):
        hist = {"a": {"builder": {"recent": [{"ok": False}] * 3}}}

        builder, _ = apply_reliability_history(["a", "b"], "builder", hist)
        investigator, notes = apply_reliability_history(["a", "b"], "investigator", hist)

        assert builder == ["b"]
        assert investigator == ["a", "b"]
        assert notes == []

    def test_cli_records_free_pool_outcome(self, tmp_path, capsys):
        state = tmp_path / "reliability.json"

        code = main(
            [
                "reliability-record",
                "--pool",
                "or-free-laguna-xs",
                "--role",
                "builder",
                "--status",
                "failed",
                "--failure",
                "timeout",
                "--elapsed-sec",
                "720",
                "--observation-id",
                "laguna_xs_r1",
                "--state",
                str(state),
                "--json",
            ]
        )

        assert code == 0
        assert json.loads(capsys.readouterr().out)["record"]["recent"][0]["failure"] == "timeout"


# ---------------------------------------------------------------------------
# 다중 프로세스 동시 기록 회귀 테스트 및 kimi resolver 테스트
# ---------------------------------------------------------------------------


def _worker_record(barrier, path_str, pool_name, role, obs_id):
    """모든 프로세스가 동시에 read-modify-write 에 진입하도록 맞춘 뒤 기록합니다.

    Barrier 없이 그냥 띄우면 프로세스가 순차로 소화되어 경쟁이 재현되지 않고,
    잠금을 빼도 테스트가 통과해 회귀를 잡지 못합니다.
    """
    from scripts.orca_model_router import record_reliability_outcome

    barrier.wait()
    record_reliability_outcome(
        pool_name,
        role,
        ok=True,
        observation_id=obs_id,
        path=Path(path_str),
    )


class TestConcurrentReliabilityRecord:
    """동시 다중 프로세스 기록 시 관측 유실이 없어야 합니다."""

    def test_no_lost_updates_under_concurrent_writes(self, tmp_path):
        """N 개 관측이 동시에 기록될 때 모두 최종 이력에 남아야 합니다.

        RELIABILITY_WINDOW(10) 보다 작은 N=8 을 사용해 창 자르기와 섞이지 않습니다.
        _lock_file 의 잠금을 제거하면 이 테스트는 관측 유실로 실패해야 합니다.
        """
        from scripts.orca_model_router import RELIABILITY_WINDOW, load_reliability_history

        n_writers = 8
        assert n_writers < RELIABILITY_WINDOW, "N 이 창 크기 이상이면 창 자르기와 간섭합니다"

        p = tmp_path / "reliability.json"
        pool_name = "test-pool"
        role = "builder"

        ctx = multiprocessing.get_context("fork" if os.name != "nt" else "spawn")
        barrier = ctx.Barrier(n_writers)
        procs = [
            ctx.Process(
                target=_worker_record,
                args=(barrier, str(p), pool_name, role, f"obs:{i}"),
            )
            for i in range(n_writers)
        ]
        for proc in procs:
            proc.start()
        for proc in procs:
            proc.join(timeout=60)
            assert proc.exitcode == 0, f"기록 프로세스가 비정상 종료했습니다: {proc.exitcode}"

        history = load_reliability_history(p)
        recent = history[pool_name][role]["recent"]
        recorded_ids = {item["observation_id"] for item in recent}
        expected_ids = {f"obs:{i}" for i in range(n_writers)}
        assert recorded_ids == expected_ids, f"유실된 관측: {expected_ids - recorded_ids}"


class TestResolveKimiBin:
    """resolve_kimi_bin 이 KIMI_BIN 환경변수와 기본 경로를 올바르게 처리합니다."""

    def test_kimi_bin_env_takes_priority(self, monkeypatch, tmp_path):
        """KIMI_BIN 이 지정되면 그 값이 반환됩니다."""
        fake_bin = str(tmp_path / "custom_kimi")
        monkeypatch.setenv("KIMI_BIN", fake_bin)
        result = resolve_kimi_bin()
        assert result == fake_bin

    def test_no_absolute_path_literal_without_kimi_bin(self, monkeypatch):
        """KIMI_BIN 이 없고 PATH 에도 kimi 가 없을 때 기본 경로가
        Path.home() 기반으로 조합되고 하드코딩 문자열 리터럴을 쓰지 않는지 검증합니다."""
        from pathlib import Path

        import scripts.orca_model_router as _router

        monkeypatch.delenv("KIMI_BIN", raising=False)
        monkeypatch.setattr(_router.shutil, "which", lambda name: None)

        fake_home = Path("/tmp/fakehome")
        monkeypatch.setattr(_router.Path, "home", staticmethod(lambda: fake_home))

        result = resolve_kimi_bin()
        assert result == str(fake_home / ".kimi-code" / "bin" / "kimi"), (
            f"예상 경로와 다릅니다: {result}"
        )

    def test_kimi_bin_reflected_in_probe_cmd(self, monkeypatch, tmp_path):
        """KIMI_BIN 이 지정되면 resolve_kimi_bin 이 그 값을 반환하고
        probe_model 이 kimi-openrouter provider 에서 그 경로를 첫 인자로 사용합니다."""
        import subprocess as _sp

        import scripts.orca_model_router as _router

        fake_bin = str(tmp_path / "my_kimi")
        monkeypatch.setenv("KIMI_BIN", fake_bin)

        # resolve_kimi_bin 이 KIMI_BIN 을 반환하는지 직접 검증합니다.
        assert resolve_kimi_bin() == fake_bin

        captured = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            m = MagicMock()
            m.returncode = 0
            m.stdout = "pong"
            m.stderr = ""
            return m

        monkeypatch.setattr(_sp, "run", fake_run)
        monkeypatch.setattr(_router, "build_probe_env", lambda root=None: ({}, "ok"))

        # PROBE_CONFIG 에 kimi-openrouter 가 직접 등록되어 있으므로
        # probe_info 를 통해 provider 를 지정해 호출합니다.
        probe_info = _router.PROBE_CONFIG["kimi-openrouter"]
        cmd_template = probe_info["probe_cmd"]
        cmd = [arg.format(model="kimi-k2-free") for arg in cmd_template]
        cmd[0] = _router.resolve_kimi_bin()
        assert cmd[0] == fake_bin, f"probe 첫 인자가 KIMI_BIN 값이 아닙니다: {cmd}"

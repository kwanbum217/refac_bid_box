"""
tests/test_orca_model_router.py

orca_model_router.py 모델 라우터 유닛 테스트.
테스트 환경에서는 실제 모델 하위 프로세스 호출이 0회임을 monkeypatch 로 보장합니다.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_scripts = Path(__file__).resolve().parent.parent / "scripts"
if str(_scripts) not in sys.path:
    sys.path.insert(0, str(_scripts))

from scripts.orca_model_router import (
    FREE_POOL_ELIGIBLE_ROLES,
    FREE_POOL_MAX_RISK,
    FREE_POOL_ORDER,
    MODEL_POOL,
    PROBE_CONFIG,
    RISK_KEYWORDS,
    ModelRoutingError,
    RouteResult,
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
    load_repo_env,
    main,
    preflight,
    probe_model,
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
        """코디네이터 전용 모델(claude-opus-5)은 어떤 경우에도 워커로 선택되어서는 안 됩니다."""
        assert is_coordinator_model("claude-opus-5") is True
        assert is_coordinator_model("claude-opus") is True
        assert MODEL_POOL["claude-opus"]["tier"] == "coordinator"
        assert MODEL_POOL["claude-opus"]["auto_selectable"] is False
        assert MODEL_POOL["claude-opus"]["suitable_for"] == []

    def test_select_model_never_returns_coordinator(self):
        """모든 역할과 위험도 조합에서 select_model 은 코디네이터 모델을 반환하지 않습니다."""
        roles = ["builder", "reviewer", "investigator", "benchmarker", "documenter", "unknown"]
        risks = ["high", "medium", "low"]
        for r in roles:
            for k in risks:
                res = select_model(r, k)
                assert res["primary_model"] != "claude-opus-5"
                assert res["primary_pool"] != "claude-opus"
                assert res["fallback_model"] != "claude-opus-5"
                assert res["fallback_pool"] != "claude-opus"

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
        passed, warnings = preflight("claude-opus-5")
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
        """explicit_model 로 claude-opus-5 가 주어지면 ValueError 로 거부합니다."""
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
        parser.add_argument("--model", default="claude-opus-5")
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
        assert FREE_POOL_ORDER == [
            "opencode-deepseek",
            "or-free-nemotron-ultra",
            "or-free-laguna-s",
            "or-free-laguna-xs",
            "opencode-free",
            "cerebras-oss",
            "or-free-north-mini",
            "cursor-auto",
        ]
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
        assert set(deepseek_info["suitable_for"]) == {
            "investigator",
            "builder",
            "benchmarker",
            "documenter",
        }
        assert "reviewer" not in deepseek_info["suitable_for"]

        # OpenRouter 무료 4종은 읽기 전용으로만 검증되어 investigator 만 받습니다.
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
            assert info["suitable_for"] == ["investigator"]
            assert "builder" not in info["suitable_for"]
            assert "reviewer" not in info["suitable_for"]

        free_info = MODEL_POOL["opencode-free"]
        assert "/" in free_info["id"]
        assert free_info["id"] == "opencode/nemotron-3.5-lightning-free"
        assert free_info["provider"] == "opencode"
        assert free_info["tier"] == "free"
        assert free_info["auto_selectable"] is False

        codex_info = MODEL_POOL["codex"]
        assert codex_info["provider"] == "codex"
        assert codex_info["tier"] == "secondary"
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

    def test_allow_free_true_investigator_low_risk_no_write_scope_selects_deepseek(self):
        """allow_free=True, investigator, low, 쓰기 없음 조합에서 주 모델로 opencode/deepseek-v4-flash-free 가 선택되고 fallback 으로 opencode/nemotron-3.5-lightning-free 가 지정됩니다."""
        res = select_model("investigator", "low", allow_free=True, has_write_scope=False)
        assert res["primary_pool"] == "opencode-deepseek"
        assert res["primary_model"] == "opencode/deepseek-v4-flash-free"
        assert res["fallback_pool"] == "or-free-nemotron-ultra"
        assert res["fallback_model"] == "or-free/nemotron-ultra"

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
        """allow_free=True 상태에서도 코디네이터 전용 모델(claude-opus-5)은 절대 선택되지 않습니다."""
        res = select_model("investigator", "low", allow_free=True, has_write_scope=False)
        assert res["primary_model"] != "claude-opus-5"
        assert res["fallback_model"] != "claude-opus-5"

    def test_route_free_pool_primary_fail_fallback(self, monkeypatch, cerebras_key_present):
        """opencode-deepseek 가 probe 실패하면 cursor-auto 로 fallback 전환됨을 검증합니다."""

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
        assert res.fallback_model == "or-free/nemotron-ultra"
        assert any("대체 모델 or-free/nemotron-ultra 로 전환" in w for w in res.warnings)

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
    from scripts.orca_model_router import MODEL_POOL, select_model

    # deepseek 과 cursor 를 빼면 남는 무료 모델은 investigator 전용입니다.
    result = select_model(
        "builder",
        "low",
        exclude=["opencode-deepseek", "cursor-auto"],
        allow_free=True,
        has_write_scope=True,
    )
    assert "builder" in MODEL_POOL[result["primary_pool"]]["suitable_for"]

    # 적합한 무료 모델이 있으면 여전히 우선합니다.
    investigator = select_model("investigator", "low", allow_free=True, has_write_scope=False)
    assert investigator["primary_pool"] == "opencode-deepseek"


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

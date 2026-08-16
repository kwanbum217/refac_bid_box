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
    MODEL_POOL,
    PROBE_CONFIG,
    RISK_KEYWORDS,
    RouteResult,
    classify_from_capsule,
    classify_risk,
    classify_risk_with_reasons,
    cmd_classify,
    cmd_list,
    cmd_probe,
    cmd_route,
    is_coordinator_model,
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
        raise RuntimeError("테스트에서 실제 subprocess.run 이 호출되었습니다. monkeypatch 가 필요합니다.")

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
        res = select_model("documenter", "low")
        assert res["primary_pool"] == "gemini-flash-medium"
        assert res["fallback_pool"] == "gemini-flash-high"

    def test_select_model_investigator(self):
        res = select_model("investigator", "medium")
        assert res["primary_pool"] == "gemini-flash-high"
        assert res["fallback_pool"] == "gemini-flash-medium"

    def test_select_model_exclude_filtering(self):
        res = select_model("builder", "high", exclude=["gemini-flash-high"])
        assert res["primary_pool"] == "claude-sonnet"
        assert res["fallback_pool"] is None

    def test_auto_selectable_pools_distinction(self):
        """자동 선택 대상 풀과 비대상 풀이 명확히 구분됨을 검증합니다."""
        auto_pools = {name for name, info in MODEL_POOL.items() if info["auto_selectable"]}
        non_auto_pools = {name for name, info in MODEL_POOL.items() if not info["auto_selectable"]}

        assert auto_pools == {"gemini-flash-high", "gemini-flash-medium", "claude-sonnet"}
        assert non_auto_pools == {"claude-opus", "codex", "opencode-free"}


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
        mock_proc = MagicMock(returncode=0, stdout="pong", stderr="UserWarning: deprecation notice\ninfo: update available")
        monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: mock_proc)

        available, detail = probe_model("gemini-3.7-flash-high")
        assert available is True
        assert "OK (종료 코드 0" in detail
        assert "UserWarning" in detail

    def test_probe_failure_quota_exceeded(self, monkeypatch):
        mock_proc = MagicMock(returncode=1, stdout="", stderr="Error: RESOURCE_EXHAUSTED: quota exceeded 429")
        monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: mock_proc)

        available, detail = probe_model("gemini-3.7-flash-high")
        assert available is False
        assert "할당량 초과" in detail or "quota" in detail

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

        passed, warnings = preflight("opencode-free")
        assert passed is True
        assert any("무료 모델" in w for w in warnings)

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
        assert res.primary_model == "gemini-3.7-flash-high"
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
        for provider in ("gemini", "claude", "opencode"):
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
        assert "주 모델:      gemini-3.7-flash-medium" in captured

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
        assert data["recommended"] == "gemini-3.7-flash-high"

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

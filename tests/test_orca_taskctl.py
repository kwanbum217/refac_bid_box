"""
tests/test_orca_taskctl.py

orca_taskctl.py Control Plane 자동화 도구 유닛 테스트.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pytest

# scripts/ 디렉터리를 import 경로에 추가
_scripts = Path(__file__).resolve().parent.parent / "scripts"
if str(_scripts) not in sys.path:
    sys.path.insert(0, str(_scripts))

from orca_taskctl import (
    parse_intent,
    expand_intent_to_capsule,
    _format_list,
    CAPSULE_BUDGET,
    COMPLEX_CAPSULE_BUDGET,
)


SAMPLE_INTENT = """\
schema: ORCA_TASK_INTENT_V1
role: builder
objective: >
  prediction API latency regression 수정.
  c10 P95 56.45ms를 유지해야 합니다.
scope:
  - "src/ml/predictor.py"
  - "tests/test_prediction.py"
acceptance:
  - "targeted tests pass"
  - "c10 P95 regression 없음"
risk: medium
"""

SIMPLE_INTENT = """\
schema: ORCA_TASK_INTENT_V1
role: investigator
objective: >
  코드베이스에서 모든 캐시 사용 패턴을 조사합니다.
scope:
  - "src/app/core/cache.py"
acceptance:
  - "보고서 작성"
risk: low
"""


class TestParseIntent:
    def test_parse_basic_fields(self):
        intent = parse_intent(SAMPLE_INTENT)
        assert intent["schema"] == "ORCA_TASK_INTENT_V1"
        assert intent["role"] == "builder"
        assert "prediction API" in intent["objective"]
        assert intent["risk"] == "medium"

    def test_parse_scope(self):
        intent = parse_intent(SAMPLE_INTENT)
        assert intent["scope"] == ["src/ml/predictor.py", "tests/test_prediction.py"]

    def test_parse_acceptance(self):
        intent = parse_intent(SAMPLE_INTENT)
        assert intent["acceptance"] == ["targeted tests pass", "c10 P95 regression 없음"]

    def test_parse_investigator(self):
        intent = parse_intent(SIMPLE_INTENT)
        assert intent["role"] == "investigator"
        assert intent["risk"] == "low"
        assert "캐시" in intent["objective"]

    def test_parse_empty_scope(self):
        text = """\
schema: ORCA_TASK_INTENT_V1
role: builder
objective: test
scope: []
acceptance: []
risk: low
"""
        intent = parse_intent(text)
        assert intent["scope"] == []

    def test_parse_defaults(self):
        text = """\
schema: ORCA_TASK_INTENT_V1
objective: minimal task
"""
        intent = parse_intent(text)
        assert intent["role"] == "builder"
        assert intent["risk"] == "medium"
        assert intent["scope"] == []

    def test_parse_with_context(self):
        text = """\
schema: ORCA_TASK_INTENT_V1
role: builder
objective: fix bug
context: >
  이전 PR에서 발생한 회귀 버그입니다.
  핫픽스가 필요합니다.
risk: high
"""
        intent = parse_intent(text)
        assert "회귀 버그" in intent["context"]
        assert "핫픽스" in intent["context"]


class TestFormatList:
    def test_simple_items(self):
        result = _format_list(["item1", "item2"])
        assert "item1" in result
        assert "item2" in result

    def test_items_with_spaces(self):
        result = _format_list(["item with spaces"])
        assert '"item with spaces"' in result

    def test_items_with_slashes(self):
        result = _format_list(["src/ml/predictor.py"])
        assert '"src/ml/predictor.py"' in result

    def test_empty_list(self):
        result = _format_list([])
        assert "[]" in result


class TestExpandIntentToCapsule:
    def test_expand_generates_valid_capsule(self):
        intent = parse_intent(SAMPLE_INTENT)
        capsule = expand_intent_to_capsule(intent, task_id="test_task_001")

        assert "ORCA_TASK_CAPSULE_V2" in capsule
        assert "test_task_001" in capsule
        assert "prediction API" in capsule
        assert "allowed_read_files" in capsule
        assert "allowed_write_files" in capsule
        assert "src/ml/predictor.py" in capsule
        assert "tests/test_prediction.py" in capsule

    def test_expand_includes_forbidden_list(self):
        intent = parse_intent(SAMPLE_INTENT)
        capsule = expand_intent_to_capsule(intent, task_id="test_task_001")

        assert "README.md 전체 재독 금지" in capsule
        assert "DB 스키마 및 원본 데이터 변경 금지" in capsule
        assert "main 브랜치 직접 수정" in capsule
        assert "이모지 사용 금지" in capsule

    def test_expand_includes_ground_truth(self):
        intent = parse_intent(SAMPLE_INTENT)
        capsule = expand_intent_to_capsule(intent, task_id="test_task_001")

        assert "G1 데이터 무손실" in capsule
        assert "Train/Serve 특징 단일화" in capsule
        assert "1인 작업" in capsule

    def test_expand_includes_verification_commands(self):
        intent = parse_intent(SAMPLE_INTENT)
        capsule = expand_intent_to_capsule(intent, task_id="test_task_001")

        assert "pytest" in capsule
        assert "validate_agent_rules" in capsule

    def test_expand_with_context_as_why_now(self):
        text = """\
schema: ORCA_TASK_INTENT_V1
role: builder
objective: fix bug
context: >
  이전 PR에서 발생한 회귀 버그입니다.
risk: high
"""
        intent = parse_intent(text)
        capsule = expand_intent_to_capsule(intent, task_id="test_task_002")
        assert "회귀 버그" in capsule

    def test_expand_without_scope_uses_default(self):
        text = """\
schema: ORCA_TASK_INTENT_V1
role: builder
objective: minimal task
risk: low
"""
        intent = parse_intent(text)
        capsule = expand_intent_to_capsule(intent, task_id="test_task_003")
        assert "src/..." in capsule
        assert "tests/..." in capsule

    def test_expand_high_risk_uses_complex_budget(self):
        intent = parse_intent(SAMPLE_INTENT)
        intent["risk"] = "high"
        capsule = expand_intent_to_capsule(intent, task_id="test_task_004")
        # 복잡 예산 내에 있어야 함
        assert len(capsule) <= COMPLEX_CAPSULE_BUDGET

    def test_expand_medium_risk_under_budget(self):
        intent = parse_intent(SAMPLE_INTENT)
        capsule = expand_intent_to_capsule(intent, task_id="test_task_005")
        assert len(capsule) <= CAPSULE_BUDGET

    def test_expand_auto_generates_task_id(self):
        intent = parse_intent(SAMPLE_INTENT)
        capsule = expand_intent_to_capsule(intent)
        assert "task_" in capsule

    def test_expand_includes_escalate_when(self):
        intent = parse_intent(SAMPLE_INTENT)
        capsule = expand_intent_to_capsule(intent, task_id="test_task_006")
        assert "allowed_write_files 범위를 벗어난 파일 수정" in capsule
        assert "ground_truth와 실제 코드" in capsule
        assert "새로운 외부 패키지" in capsule


class TestCLI:
    def test_expand_command(self):
        import subprocess
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(SAMPLE_INTENT)
            intent_path = f.name

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            out_path = f.name

        try:
            result = subprocess.run(
                [
                    sys.executable, str(_scripts / "orca_taskctl.py"),
                    "expand", "--intent", intent_path, "--out", out_path, "--json",
                ],
                capture_output=True, text=True, timeout=10,
            )
            assert result.returncode == 0
            data = json.loads(result.stdout)
            assert "capsule_path" in data
            assert data["risk"] == "medium"
            assert data["role"] == "builder"

            # 출력 파일이 생성되었는지 확인
            capsule_text = Path(out_path).read_text()
            assert "ORCA_TASK_CAPSULE_V2" in capsule_text
        finally:
            Path(intent_path).unlink(missing_ok=True)
            Path(out_path).unlink(missing_ok=True)

    def test_expand_missing_intent(self):
        import subprocess
        result = subprocess.run(
            [
                sys.executable, str(_scripts / "orca_taskctl.py"),
                "expand", "--intent", "/nonexistent/path.yaml", "--out", "/tmp/out.yaml",
            ],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 2
        assert "없음" in result.stderr or "오류" in result.stderr

    def test_status_command(self):
        import subprocess
        result = subprocess.run(
            [
                sys.executable, str(_scripts / "orca_taskctl.py"),
                "status", "--json",
            ],
            capture_output=True, text=True, timeout=10,
        )
        # status 는 Orca CLI 가 없어도 실패하지 않아야 함
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert "run_id" in data
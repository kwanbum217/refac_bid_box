"""tests/test_prediction_feature_parity.py

공고 상세 API 와 챗봇 도구가 같은 특징을 쓰는지 고정합니다.

두 경로가 다른 특징을 만들면 같은 공고에 다른 투찰가를 답합니다. AGENTS.md 가
금지한 train/serve skew 이며, 2026-09-03 에 실제로 발생했습니다. 챗봇 도구가
announcement_feature_payload 병합을 빠뜨려 제도 특징이 기본값으로 떨어졌고,
용역 모델 기준 낙찰률이 6.6에서 11.5%p 높게 나왔습니다.

모델 파일 없이도 도는 검사입니다. 예측값이 아니라 특징 키 집합을 비교합니다.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
API_PATH = REPO_ROOT / "src/app/api/v1/predictions.py"
TOOL_PATH = REPO_ROOT / "src/app/services/tools/bid_prediction_tool.py"


def _has_payload_merge(source: str, func_name: str | None = None) -> bool:
    """announcement_feature_payload 를 펼쳐 병합하는 dict 표현이 있는지 봅니다."""
    tree = ast.parse(source)
    nodes = [tree]
    if func_name:
        nodes = [
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef) and n.name == func_name
        ]
        if not nodes:
            return False
    for node in nodes:
        for sub in ast.walk(node):
            if not isinstance(sub, ast.Dict):
                continue
            for key, value in zip(sub.keys, sub.values, strict=False):
                if key is not None:
                    continue
                # {**announcement_feature_payload(bid), ...} 형태
                if (
                    isinstance(value, ast.Call)
                    and isinstance(value.func, ast.Name)
                    and value.func.id == "announcement_feature_payload"
                ):
                    return True
    return False


def test_api_path_merges_announcement_payload():
    """공고 상세 API 는 제도 특징을 병합해야 합니다."""
    assert _has_payload_merge(API_PATH.read_text(encoding="utf-8"))


def test_chatbot_tool_merges_announcement_payload():
    """챗봇 도구도 같은 병합을 해야 합니다.

    빠뜨리면 학습이 쓰는 특징 30여 개가 기본값으로 떨어져 상세 화면과 다른
    답을 냅니다.
    """
    assert _has_payload_merge(
        TOOL_PATH.read_text(encoding="utf-8"), "_build_prediction_features"
    ), (
        "_build_prediction_features 가 announcement_feature_payload 를 병합하지 않습니다. "
        "제도 특징이 기본값으로 떨어져 공고 상세와 다른 투찰가를 답하게 됩니다."
    )


def test_both_paths_share_the_same_feature_source():
    """두 경로가 같은 함수에서 제도 특징을 얻어야 합니다."""
    api_src = API_PATH.read_text(encoding="utf-8")
    tool_src = TOOL_PATH.read_text(encoding="utf-8")
    for src, label in ((api_src, "predictions.py"), (tool_src, "bid_prediction_tool.py")):
        assert "announcement_feature_payload" in src, f"{label} 이 공통 특징 공급원을 쓰지 않습니다"

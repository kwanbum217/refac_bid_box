"""공고 기준 분석 배지가 공고별 계산 지원 여부를 보여 주는지 실제 실행으로 검증합니다."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

TEMPLATE_PATH = Path("src/app/templates/bids/detail.html")


def _function_source(template: str, name: str) -> str:
    start = template.index(f"function {name}(")
    depth = 0
    for index in range(template.index("{", start), len(template)):
        if template[index] == "{":
            depth += 1
        elif template[index] == "}":
            depth -= 1
            if depth == 0:
                return template[start : index + 1]
    raise AssertionError(f"{name} 의 끝을 찾지 못했습니다")


def _badge_source(template: str) -> str:
    start = template.index("const scopeBadgeInputCodes")
    end = template.index("function renderNegotiation", start)
    helpers = [
        _function_source(template, name)
        for name in ("blockedCodeOf", "getBlockedReasonText", "hasMemberQuantData")
    ]
    return "\n".join(helpers) + "\n" + template[start:end]


CASES = {
    "general_supported": (
        {"blocked": False, "rule_id": "SERVC_GENERAL_X", "rule_name": "조달청 일반용역"},
        "green",
        "계산 지원",
    ),
    "tech_supported": (
        {"blocked": False, "rule_id": "SERVC_TECH_QUAL_ANNOUNCEMENT_LWLT_A"},
        "green",
        "계산 지원 · 기술용역 공고 하한율",
    ),
    "negotiation": (
        {"blocked": False, "negotiation_variant": "일반"},
        "blue",
        "협상에의한계약 · 평가비율 제공",
    ),
    "manual": (
        {"blocked": True, "blocked_reason": "MANUAL_EVALUATION: 자체 심사"},
        "red",
        "계산 미지원 · 수기심사",
    ),
    "non_pred": (
        {"blocked": True, "blocked_reason": "NON_PRED_PRICE: 비예가"},
        "red",
        "계산 미지원 · 비예가",
    ),
    "score_table": (
        {"blocked": True, "blocked_reason": "MISSING_SCORE_TABLE: 배점표 필요"},
        "amber",
        "입력하면 계산 가능 · 배점표 입력",
    ),
    "local_type": (
        {"blocked": True, "blocked_reason": "LOCAL_SERVICE_TYPE_UNRESOLVED: 후보"},
        "amber",
        "입력하면 계산 가능 · 용역 세부유형 선택",
    ),
    "bounds_member_missing": (
        {"blocked": True, "blocked_reason": "PRICE_BOUNDS_UNRESOLVED: 정량", "non_price_score": 0},
        "amber",
        "입력하면 계산 가능 · 회원 정량정보",
    ),
    "bounds_with_member": (
        {
            "blocked": True,
            "blocked_reason": "PRICE_BOUNDS_UNRESOLVED: 하한율",
            "non_price_score": 12.5,
        },
        "red",
        "계산 미지원 · 투찰 범위 미확정",
    ),
    "unknown_code": (
        {"blocked": True, "blocked_reason": "SOMETHING_NEW: 새 사유"},
        "red",
        "계산 미지원",
    ),
    "no_data": (None, "gray", "지원 여부 확인 실패"),
}


@pytest.fixture(scope="module")
def rendered() -> dict[str, dict[str, str]]:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node 를 사용할 수 없습니다")
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    inputs = {key: value[0] for key, value in CASES.items()}
    script = f"""
const badge = {{ classes: new Set(['badge', 'badge-gray']), text: '', title: '' }};
const handle = {{
  removeClass(names) {{ names.split(' ').forEach(n => badge.classes.delete(n)); return handle; }},
  addClass(name) {{ badge.classes.add(name); return handle; }},
  text(value) {{ badge.text = value; return handle; }},
  attr(name, value) {{ badge[name] = value; return handle; }},
}};
const $ = () => handle;
{_badge_source(template)}
const out = {{}};
for (const [key, data] of Object.entries({json.dumps(inputs, ensure_ascii=False)})) {{
  setEvaluationScopeBadge(data);
  const tones = [...badge.classes].filter(n => n.startsWith('badge-'));
  out[key] = {{ tones: tones.join(' '), text: badge.text, title: badge.title }};
}}
process.stdout.write(JSON.stringify(out));
"""
    result = subprocess.run(  # noqa: S603 - node 경로와 인자를 이 테스트가 직접 고정합니다
        [node, "-e", script], capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@pytest.mark.parametrize("case", sorted(CASES))
def test_badge_reflects_notice_support(rendered, case):
    _, tone, text = CASES[case]
    assert rendered[case]["tones"] == f"badge-{tone}"
    assert rendered[case]["text"] == text


def test_blocked_badge_title_carries_full_reason(rendered):
    assert rendered["manual"]["title"] == "발주기관 자체 심사기준표를 적용하는 수기심사 공고"
    assert rendered["unknown_code"]["title"] == "새 사유"


def test_initial_badge_does_not_claim_coverage():
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    assert "지원 여부 확인 중" in template
    assert "계산 미지원 분야" in template
    assert ".badge-amber" in template

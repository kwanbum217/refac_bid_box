"""기술용역 적격심사 표시 계층의 회귀 검증."""

from pathlib import Path

TEMPLATE_PATH = Path("src/app/templates/bids/detail.html")


def test_tech_service_missing_lower_bound_reason_is_translated():
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    assert (
        "'TECH_SERVICE_MISSING_LWLT': '기술용역 공고에 낙찰하한율이 없어 계산할 수 없음'"
        in template
    )


def test_blocked_reason_code_prefix_is_stripped_without_losing_server_message():
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    start = template.index("function getBlockedReasonText")
    end = template.index("function setEvaluationScopeBadge", start)
    function = template[start:end]
    assert "rawReason.match(/^([A-Z][A-Z_]*)\\s*:/)" in function
    assert "reasons[reasonCode]" in function
    assert "rawReason.slice(codePrefix[0].length).trim()" in function


def test_scope_badge_is_reset_for_general_tech_and_negotiation_responses():
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    start = template.index("function setEvaluationScopeBadge")
    end = template.index("function renderNegotiation", start)
    setter = template[start:end]
    assert "일반용역 적격심사만 지원 (약 6%)" in setter
    assert "SERVC_TECH_QUAL_ANNOUNCEMENT_LWLT" in setter
    assert "기술용역 적격심사 공고 (공고 하한율 적용)" in setter
    assert "협상에의한계약 평가비율 제공" in setter
    assert "별표" not in setter
    assert "배점표" not in setter
    assert (
        "setEvaluationScopeBadge(data);" in template[template.index("function renderNegotiation") :]
    )

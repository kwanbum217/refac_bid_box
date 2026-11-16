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


def test_scope_badge_is_set_on_every_recommend_response():
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    assert "일반용역 적격심사만 지원 (약 6%)" not in template
    assert (
        "setEvaluationScopeBadge(data);" in template[template.index("function renderNegotiation") :]
    )
    error_start = template.index(
        "error: function(xhr)", template.index("function requestRecommend")
    )
    error_handler = template[error_start : template.index("complete: function()", error_start)]
    assert "applyEvaluationScopeBadge('gray', '로그인 후 확인')" in error_handler
    assert "setEvaluationScopeBadge(null)" in error_handler

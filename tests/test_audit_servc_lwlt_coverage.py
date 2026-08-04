from scripts.audit_servc_lwlt_coverage import requires_lower_limit


def test_requires_lower_limit_for_threshold_methods():
    assert requires_lower_limit("적격심사제-추정가격 2억원 미만인 용역")
    assert requires_lower_limit("제한적최저가(낙찰하한율)-제한적최저가(낙찰하한율)")
    assert requires_lower_limit("소액수의견적-소액수의견적(2인 이상 견적 제출)")


def test_does_not_require_lower_limit_for_non_threshold_methods():
    assert not requires_lower_limit("협상에의한계약-협상에 의한 낙찰자 결정")
    assert not requires_lower_limit("규격가격동시입찰-제안적격자 중 예가 내 최저가 투찰자")
    assert not requires_lower_limit("수의시담-수의시담")

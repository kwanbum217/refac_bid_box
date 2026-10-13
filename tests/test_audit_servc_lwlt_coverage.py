import pandas as pd
import pytest

from scripts.audit_servc_lwlt_coverage import requires_lower_limit, split_by_explainability


def test_requires_lower_limit_for_threshold_methods():
    assert requires_lower_limit("적격심사제-추정가격 2억원 미만인 용역")
    assert requires_lower_limit("제한적최저가(낙찰하한율)-제한적최저가(낙찰하한율)")
    assert requires_lower_limit("소액수의견적-소액수의견적(2인 이상 견적 제출)")


# 기관(공기업·공단) 자체 기준 공고의 실제 낙찰방법명. R2 로 기관 규칙이 코드에 들어왔으므로
# 커버리지 감사도 이 표기들을 하한율 필수 유형으로 세어야 한다.
INSTITUTION_QUALIFICATION_METHODS = (
    "적격심사제-기타용역 추정가격 고시금액 이상",
    "적격심사제-임대차 적격심사 추정가격 고시금액 이상",
    "적격심사제-수리ㆍ점검용역 적격심사 고시금액 미만",
    "적격심사제-소프트웨어용역(중소기업자간 경쟁제품 비대상) 적격심사 추정가격 고시금액 미만",
    "적격심사제-화물 육상운송용역 적격심사 추정가격 고시금액 미만",
)


@pytest.mark.parametrize("method", INSTITUTION_QUALIFICATION_METHODS)
def test_requires_lower_limit_for_institution_methods(method: str) -> None:
    assert requires_lower_limit(method)


def test_does_not_require_lower_limit_for_non_threshold_methods():
    assert not requires_lower_limit("협상에의한계약-협상에 의한 낙찰자 결정")
    assert not requires_lower_limit("규격가격동시입찰-제안적격자 중 예가 내 최저가 투찰자")
    assert not requires_lower_limit("수의시담-수의시담")


def _stats(rates: dict[str, float]) -> pd.DataFrame:
    return pd.DataFrame({"missing_rate": rates})


def test_all_or_nothing_groups_are_explained_by_method_name():
    explained, mixed = split_by_explainability(_stats({"수의시담": 1.0, "적격심사": 0.0}))
    assert list(explained.index) == ["수의시담", "적격심사"]
    assert mixed.empty


def test_group_with_both_present_and_missing_is_not_explained():
    """공고서참조가 정정의 근거입니다. 같은 방법 안에서 20.6%만 결측입니다."""
    explained, mixed = split_by_explainability(_stats({"공고서참조": 0.206}))
    assert explained.empty
    assert list(mixed.index) == ["공고서참조"]


def test_near_boundary_group_is_treated_as_explained():
    """2만 8천 건 중 2건처럼 사실상 한쪽에 붙은 그룹을 혼재로 세지 않습니다."""
    explained, mixed = split_by_explainability(_stats({"수의시담": 1.0 - 2 / 28764}))
    assert list(explained.index) == ["수의시담"]
    assert mixed.empty

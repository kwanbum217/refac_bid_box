from pathlib import Path

import pytest

from src.app.schemas.evaluations import ContractRegimeDescription, EvaluationResponse
from src.app.services.demand_institutions import describe_contract_regime


@pytest.mark.parametrize(
    ("raw", "method", "institution", "regime", "label", "basis", "rate"),
    [
        (
            {},
            None,
            {"jrsdctn_div_nm": "지방자치단체"},
            "LOCAL",
            "지방계약",
            "INSTITUTION",
            "±3%",
        ),
        ({}, "지방계약", None, "LOCAL", "지방계약", "METHOD_NAME", "±3%"),
        (
            {},
            None,
            {"jrsdctn_div_nm": "국가기관"},
            "NATIONAL",
            "국가계약",
            "INSTITUTION",
            "±2%",
        ),
        ({}, None, None, None, "계약 법령 미상", None, "±2% (기본값, 법령 미상)"),
        (
            {},
            None,
            {"jrsdctn_div_nm": "국가기관", "dminstt_nm": "부산지방국토관리청"},
            "NATIONAL",
            "국가계약",
            "INSTITUTION",
            "±2%",
        ),
    ],
)
def test_describe_contract_regime(raw, method, institution, regime, label, basis, rate):
    described = describe_contract_regime(raw, method, institution)

    assert described["regime"] == regime
    assert described["label"] == label
    assert described["basis"] == basis
    assert described["range_rate_label"] == rate
    if basis == "METHOD_NAME":
        assert described["basis_text"] == "계약방법명에 지방 표기"
    if regime == "LOCAL" and basis == "INSTITUTION":
        assert described["basis_text"] == "수요기관 소관구분: 지방자치단체"


def test_no_institution_row_and_response_schema_accept_description():
    described = describe_contract_regime({"dminsttCd": "missing"}, None, None)
    response = EvaluationResponse(contract_regime=ContractRegimeDescription(**described))

    assert response.contract_regime is not None
    assert response.contract_regime.label == "계약 법령 미상"
    assert response.contract_regime.range_rate_label == "±2% (기본값, 법령 미상)"


def test_detail_and_scenario_template_render_regime_and_hide_negotiation_scenario():
    template = Path("src/app/templates/bids/detail.html").read_text()

    assert "{{ contract_regime.label }} · {{ contract_regime.range_rate_label }}" in template
    assert 'title="{{ contract_regime.basis_text or' in template
    assert 'id="contract-regime-range"' in template
    assert "isNegotiation || $('#scenario-tbody').children().length === 0" in template
    assert "regime.range_rate_label" in template

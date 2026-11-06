"""
tests/test_band_regime_classifier.py

`classify_band_regime` 의 갈래 판별 계약 검증.

시험 입력은 설계 문서 `.orca/ref/band_2to1_attachment_classifier_design_20261106.md`
2.2절 오탐 사례 6행과 부록 B 공고별 결과 표의 인용 문구(80자 이내)입니다. 첨부
원문 파일은 저장소에 없으며 내려받지 않습니다. 2.2절 사례는 오탐 문구와 같은
공고의 부록 B 인용 문구를 함께 넣어, 판별기가 오탐 문구에 흔들리지 않는지
확인합니다.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import FrozenInstanceError
from typing import Any

import pytest

from src.app.services.band_regime_classifier import (
    LOCAL,
    MOIS4,
    MOIS_ACADEMIC,
    MOIS_OTHER,
    NO_ATTACH,
    PPS,
    UNSPECIFIED,
    BandRegimeResult,
    classify_band_regime,
)

REQUIRED_REGIMES = (MOIS_ACADEMIC, MOIS_OTHER, PPS, LOCAL, UNSPECIFIED, NO_ATTACH)

# (공고번호, 첨부 원문 텍스트들, 설계 문서의 사람 판정 갈래)
APPENDIX_CASES: list[tuple[str, list[str], str]] = [
    (
        "R25BK01224070",
        [
            "사 대상으로서 「지방자치단체 입찰시 낙찰자 결정기준」(입찰공고일 기준 적용)의 "
            "[별표 4] 학술연구용역의 적격심사 세부기준 중 추정가격 2억미만",
            "경기도일반용역적격심사세부기준 등 기타 입찰에 관한 서류 등을충분히 숙지하시고",
        ],
        MOIS_ACADEMIC,
    ),
    (
        "R26BK01333358",
        [
            "이상)으로 투찰한 자 순으로 지방자치단체 입찰시 낙찰자 결정기준 제2장의2 "
            "기술·학술연구 용역 적격심사 세부기준(행정안전부 예규) <별표4> 학",
            "라. 입찰자는 울산광역시 일반용역 적격심사 세부기준, 지방자치단체 입찰시 낙찰자 결정기준",
        ],
        MOIS_ACADEMIC,
    ),
    (
        "R25BK01154030",
        [
            ": 「지방자치단체를 당사자로 하는 계약에 관한 법률 시행령」 제42조 및 "
            "경기도 일반용역 적격심사 세부기준(경기도 예규 제739호) 별표<1-2",
            "경기도 일반용역 적격심사 세부기준(경기도 예규 제739호) 별표<1-2>",
        ],
        LOCAL,
    ),
    (
        "R25BK01255918",
        [
            "부기준에 의거 심사하여 적격 판정받은 자를 낙찰자로 결정합니다. 적격심사기준 : "
            "조달청 일반용역 적격심사 세부기준 [조달청공고 최신호, [별표1",
            "물품적격심사에 적용되는 세부기준은 행정안전부 예규 지방자치단체 입찰시 "
            "낙찰자 결정기준 제4장 물품 적격심사",
        ],
        PPS,
    ),
    (
        "R26BK01506722",
        [
            "용역으로 기준은 아래 표와 같습니다. 「지방자치단체 입찰 시 낙찰자 결정기준」 "
            "제2장의2 기술·학술연구 용역 적격심사 세부기준 적격심사 기준 적",
            "사업수행능력평가(P.Q)를 하지 않는 기술용역 4. 추정가격 2억원 미만 1억원 이상인 평가기준",
        ],
        MOIS_OTHER,
    ),
    (
        "R26BK01270299",
        [
            "용역은 적격심사 대상으로 「조달청 일반용역 적격심사 세부기준」제5조제1항제1호 "
            "[별표1] 학술연구용역 적격심사 세부기준(추정가격 5억미만, 고시",
            "조달청 일반용역 적격심사 세부기준」제5조제1항제1호 [별표1] 학술연구용역 적격심사 세부기준",
        ],
        PPS,
    ),
    (
        "R25BK01183253",
        [
            "사 대상으로서 「지방자치단체 입찰시 낙찰자 결정기준」(입찰공고일 기준 적용)의 "
            "[별표 4] 학술연구용역의 적격심사 세부기준 중 추정가격 2억미만",
        ],
        MOIS_ACADEMIC,
    ),
    (
        "R26BK01363389",
        [
            "시 낙찰자 결정기준(행안부 예규)」제2장의2 기술·학술연구용역 적격심사 세부기준"
            "[별표4] 학술연구용역(추정가격 2억미만 1억이상) 평가기준에 따",
        ],
        MOIS_ACADEMIC,
    ),
    (
        "R26BK01560778",
        [
            "추정가격 2억원 미만인 일반용역 평가기준”에 따라 예정가격 이하로 낙찰하한율"
            "(87.745%) 이상 최저가 가격으로 입찰한 자의 순으로 적격심사하",
        ],
        MOIS_OTHER,
    ),
    (
        "R26BK01705722",
        [
            ") 결정 가.「지방자치단체 입찰시 낙찰자 결정기준(행정안전부 예규 제373호)」 "
            "제2장의2 기술 용역적격심사세부기준에 의거 예정가격 이하로서 낙",
        ],
        MOIS_OTHER,
    ),
    (
        "R25BK01248793",
        [
            "사대상 용역으로「조달청 일반용역 적격심사 세부기준이 적용됩니다. - 세부기준: "
            "[별표 1] 학술연구용역 (추정가격 5억 원 미만) 평가 기준 적",
        ],
        PPS,
    ),
    (
        "R25BK01244020",
        [
            "가장 많이 선택된 4개의 예비가격을 산술평균한 가격으로 합니다. 다.「부산광역시 "
            "일반용역 적격심사 세부기준(부산광역시 공고 제2025-1981호",
        ],
        LOCAL,
    ),
    (
        "R25BK01139979",
        [
            "행정자치부 예규 제332호(2025.7) 지방자치단체 입찰시 낙찰자선정 세부기준에 의하며",
        ],
        UNSPECIFIED,
    ),
    (
        "R26BK01345876",
        [
            "입찰공고 시 적격심사 평가 기준(보유 기술인력 평가) 누락으로 적격심사를 진행할 수 없는",
        ],
        UNSPECIFIED,
    ),
]

FALSE_POSITIVE_IDS = frozenset(
    {
        "R25BK01224070",
        "R26BK01333358",
        "R25BK01154030",
        "R25BK01255918",
        "R26BK01506722",
        "R26BK01270299",
    }
)

NO_ATTACHMENT_INPUTS: list[list[str]] = [
    [],
    [""],
    ["", "   ", "\u200b"],
]


def _appendix_params() -> list[Any]:
    return [pytest.param(*case, id=case[0]) for case in APPENDIX_CASES]


@pytest.mark.parametrize(("case_id", "texts", "expected"), _appendix_params())
def test_appendix_quotes_match_documented_regime(
    case_id: str, texts: list[str], expected: str
) -> None:
    result = classify_band_regime(texts)

    assert result.regime == expected, f"{case_id}: {result}"


@pytest.mark.parametrize(
    ("case_id", "texts", "expected"),
    [pytest.param(*case, id=case[0]) for case in APPENDIX_CASES if case[0] in FALSE_POSITIVE_IDS],
)
def test_false_positive_quotes_do_not_flip_the_regime(
    case_id: str, texts: list[str], expected: str
) -> None:
    result = classify_band_regime(texts)

    assert result.regime == expected, f"{case_id}: {result}"


def test_false_positive_case_set_covers_design_table() -> None:
    assert len(FALSE_POSITIVE_IDS) == 6


def test_each_required_regime_has_at_least_two_cases() -> None:
    counts = Counter(expected for _, _, expected in APPENDIX_CASES)
    counts[NO_ATTACH] = len(NO_ATTACHMENT_INPUTS)

    for regime in REQUIRED_REGIMES:
        assert counts[regime] >= 2, f"{regime} 시험 건수 {counts[regime]}"


@pytest.mark.parametrize(
    ("case_id", "texts", "expected"),
    _appendix_params(),
)
def test_evidence_is_at_most_eighty_characters(
    case_id: str, texts: list[str], expected: str
) -> None:
    result = classify_band_regime(texts)

    if expected in {MOIS_ACADEMIC, MOIS_OTHER, PPS, LOCAL}:
        assert result.evidence is not None, case_id
        assert len(result.evidence) <= 80, case_id
    else:
        assert result.evidence is None, case_id


@pytest.mark.parametrize("texts", NO_ATTACHMENT_INPUTS)
def test_empty_attachment_texts_mean_no_attachment(texts: list[str]) -> None:
    assert classify_band_regime(texts) == BandRegimeResult(NO_ATTACH, None, ())


def test_notice_sentence_is_not_a_decision_sentence() -> None:
    result = classify_band_regime(
        ["경기도 일반용역 적격심사 세부기준 등 기타 입찰에 관한 서류를 충분히 숙지하시고"]
    )

    assert result.regime == UNSPECIFIED
    assert result.evidence is None
    assert result.matched_rules == ()


def test_whitespace_and_zero_width_characters_are_normalized() -> None:
    result = classify_band_regime(
        ["제\u00a02\u3000장\u200b의 2 기술·학술연구 용역 적격심사 세부기준을 적용합니다"]
    )

    assert result.regime == MOIS_ACADEMIC
    assert "R1" in result.matched_rules


def test_goods_chapter_is_reachable() -> None:
    result = classify_band_regime(
        ["지방자치단체 입찰시 낙찰자 결정기준 제4장 물품 적격심사 세부기준을 적용합니다"]
    )

    assert result.regime == MOIS4
    assert "R8" in result.matched_rules


def test_result_is_frozen_and_matched_rules_is_a_tuple() -> None:
    result = classify_band_regime(APPENDIX_CASES[0][1])

    assert isinstance(result.matched_rules, tuple)
    with pytest.raises(FrozenInstanceError):
        result.regime = PPS  # type: ignore[misc]

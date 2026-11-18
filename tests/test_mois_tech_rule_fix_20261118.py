"""행안부 예규 기술용역 가격 구간 정정 시험 (2026-11-18).

정본:
 - .orca/capsules/task_mois_tech_rule_fix_20261118/capsule.yaml
 - data/sources/qualification/files/mois/fbe9a0b783c6_mois373_body.txt
   (행정안전부 예규 제373호, 시행 2026-07-01)

결함: 공고의 sucsfbidMthdAppStd 가 행안부 예규 「지방자치단체 입찰시 낙찰자 결정기준」을
지목해도 경고 문구와 result.base_rate 만 88 이 되고, 평가 경로(evaluations.py)가 읽는
resolve_score_params 의 base_rate 와 예측 경로(predictions.py)가 읽는 rule.base_rate 는
조달청 현행 0.90, 가격 구간도 조달청 고시금액 4구간이 그대로였습니다.

시험 항목:
 (1) 행안부 지목 기술용역 공고의 평가·예측 두 경로가 0.88 과 예규 구간을 쓴다.
 (2) 행안부를 지목하지 않은 조달청 기술용역 공고는 0.90 과 조달청 4구간 그대로다.
 (3) 예규 별표1~3 의 B·k·기준비율·통과점수·평탄 구간이 원문 값과 같다.
 (4) 낙찰방법명에 P.Q 수행 여부 표기가 없는 공고는 예규 별표를 확정하지 않는다.
 (5) 예규 별표는 조달청 고시금액 경계를 쓰지 않는다.

DB·.env·운영 서버를 쓰지 않습니다.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from src.app.services.evaluation_flat_zones import servc_tech_flat_zone_for
from src.app.services.evaluation_rules import (
    MOIS_TECH_ANNEX_UNRESOLVED_WARNING,
    MOIS_TECH_BASE_RATE_WARNING,
    MOIS_TECH_LOCAL_ANNEX_01,
    MOIS_TECH_LOCAL_ANNEX_02,
    MOIS_TECH_LOCAL_ANNEX_03,
    MOIS_TECH_LOCAL_ANNEX_RULES,
    SERVC_TECH_QUAL_ANNOUNCEMENT_LWLT,
    SERVC_TECH_QUAL_RULE_IDS,
    resolve_evaluation_rule_from_raw_data,
    resolve_score_params,
    select_mois_tech_annex_rule,
)

MOIS_APP_STD = "지방자치단체 입찰시 낙찰자 결정기준"
PPS_APP_STD = "조달청 기술용역 적격심사 세부기준"
ANNOUNCED = "2026-07-01"

METHOD_PQ_10E_OVER = "적격심사제-추정가격이 10억원 이상인 P.Q대상 기술용역의 평가기준"
METHOD_PQ_5E_10E = "적격심사제-추정가격이 10억원 미만 5억원 이상인 P.Q 대상 기술용역의 평가기준"
METHOD_PQ_UNDER_5E = "적격심사제-추정가격이 5억원 미만인 P.Q 대상 기술용역의 평가기준"
METHOD_NON_PQ_1E_2E = "적격심사제-추정가격이 2억원 미만 1억원 이상인 P.Q비대상 기술용역의 평가기준"
METHOD_NON_PQ_UNDER_1E = "적격심사제-추정가격이 1억원 미만인 P.Q비대상 기술용역의 평가기준"
METHOD_NON_PQ_2E_5E = "적격심사제-추정가격이 5억원 미만 2억원 이상인 P.Q비대상 기술용역의 평가기준"
METHOD_DISASTER = "적격심사제-추정가격이 1억원 이상인 재난복구 기술용역의 평가기준"
METHOD_WITHOUT_PQ_MARK = (
    "적격심사제-추정가격이 10억원 이상인 건설사업관리 기술용역의 평가기준(기술인평가포함)"
)


def _resolve(
    method_name: str,
    *,
    app_std: str | None = MOIS_APP_STD,
    announced: str = ANNOUNCED,
    lwlt: str = "79.995",
    srvce_div: str = "기술용역",
    pq_eval: str | None = None,
):
    raw_data = {
        "srvceDivNm": srvce_div,
        "sucsfbidMthdNm": method_name,
        "sucsfbidLwltRate": lwlt,
        "bidNtceDt": announced,
    }
    if pq_eval is not None:
        raw_data["pqEvalYn"] = pq_eval
    if app_std is not None:
        raw_data["sucsfbidMthdAppStd"] = app_std
    return resolve_evaluation_rule_from_raw_data("Servc", raw_data)


def _resolution(result, estimated_price: str | int, method_name: str):
    """평가 경로(evaluations.py)와 같은 인자로 배점표를 해석합니다."""
    return resolve_score_params(
        result.rule,
        Decimal(str(estimated_price)),
        ANNOUNCED,
        method_name,
    )


# --------------------------------------------------------------------------- #
# (1) 행안부 지목 기술용역: 평가·예측 두 경로가 예규 값
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("method_name", "expected_rule"),
    [
        (METHOD_PQ_10E_OVER, MOIS_TECH_LOCAL_ANNEX_01),
        (METHOD_PQ_5E_10E, MOIS_TECH_LOCAL_ANNEX_01),
        (METHOD_PQ_UNDER_5E, MOIS_TECH_LOCAL_ANNEX_01),
        (METHOD_NON_PQ_1E_2E, MOIS_TECH_LOCAL_ANNEX_02),
        (METHOD_NON_PQ_UNDER_1E, MOIS_TECH_LOCAL_ANNEX_02),
        (METHOD_DISASTER, MOIS_TECH_LOCAL_ANNEX_03),
    ],
)
def test_mois_stated_tech_uses_mois_annex_rule(method_name: str, expected_rule) -> None:
    result = _resolve(method_name)

    assert result.is_blocked is False
    assert result.rule is not None
    assert result.rule.rule_id == expected_rule.rule_id
    # 예측 경로(predictions.py)는 rule.base_rate 를 읽습니다.
    assert result.rule.base_rate == Decimal("0.88")
    assert result.base_rate == Decimal("0.88")
    assert MOIS_TECH_BASE_RATE_WARNING in result.warnings


@pytest.mark.parametrize(
    ("method_name", "estimated_price", "b", "k", "t"),
    [
        (METHOD_PQ_10E_OVER, 2_005_454_545, "30", "1", "92"),
        (METHOD_PQ_5E_10E, 600_000_000, "50", "2", "95"),
        (METHOD_PQ_UNDER_5E, 300_000_000, "60", "4", "95"),
    ],
)
def test_mois_annex_01_evaluation_path_uses_annex_bands(
    method_name: str, estimated_price: int, b: str, k: str, t: str
) -> None:
    """청주 R26BK01610866 처럼 20억원대 P.Q 대상 공고의 실제 계산 경로를 봅니다."""
    result = _resolve(method_name)
    resolution = _resolution(result, estimated_price, method_name)

    assert resolution.base_rate == Decimal("0.88")
    assert resolution.max_price_score == Decimal(b)
    assert resolution.multiplier == Decimal(k)
    assert resolution.pass_threshold == Decimal(t)
    # 예규는 고시금액 경계를 쓰지 않으므로 조달청 90/20·70/4 구간이 나오지 않습니다.
    assert resolution.price_band_label is not None
    assert "고시금액" not in resolution.price_band_label


@pytest.mark.parametrize(
    ("method_name", "estimated_price", "b", "k", "t"),
    [
        (METHOD_NON_PQ_UNDER_1E, 90_000_000, "90", "20", "95"),
        (METHOD_NON_PQ_1E_2E, 150_000_000, "80", "20", "95"),
        (METHOD_NON_PQ_2E_5E, 300_000_000, "50", "4", "95"),
        (METHOD_DISASTER, 50_000_000, "90", "20", "95"),
    ],
)
def test_mois_annex_02_03_evaluation_path_uses_annex_bands(
    method_name: str, estimated_price: int, b: str, k: str, t: str
) -> None:
    result = _resolve(method_name)
    resolution = _resolution(result, estimated_price, method_name)

    assert resolution.base_rate == Decimal("0.88")
    assert resolution.max_price_score == Decimal(b)
    assert resolution.multiplier == Decimal(k)
    assert resolution.pass_threshold == Decimal(t)


# --------------------------------------------------------------------------- #
# (2) 조달청 기술용역 공고는 불변
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("app_std", [PPS_APP_STD, None])
def test_pps_tech_announcement_keeps_90_and_pps_bands(app_std: str | None) -> None:
    result = _resolve(METHOD_PQ_10E_OVER, app_std=app_std)

    assert result.is_blocked is False
    assert result.rule is not None
    assert result.rule.rule_id == SERVC_TECH_QUAL_ANNOUNCEMENT_LWLT.rule_id
    assert result.rule.base_rate == Decimal("0.90")
    assert result.base_rate is None
    assert MOIS_TECH_BASE_RATE_WARNING not in result.warnings

    # 추정가격 2억원이면 조달청 별표1 의 고시금액 미만 구간(B=90, k=20)입니다.
    resolution = _resolution(result, 200_000_000, METHOD_PQ_10E_OVER)
    assert resolution.base_rate == Decimal("0.90")
    assert resolution.max_price_score == Decimal("90")
    assert resolution.multiplier == Decimal("20")


def test_pps_tech_bands_keep_notice_amount_boundary() -> None:
    rule = SERVC_TECH_QUAL_ANNOUNCEMENT_LWLT

    assert len(rule.price_bands) == 4
    assert rule.price_bands[0].label == "추정가격이 고시금액 미만인 용역"
    assert {band.base_rate for band in rule.price_bands} == {Decimal("0.90")}


# --------------------------------------------------------------------------- #
# (3) 예규 별표 값 (원문 줄 인용 확정값)
# --------------------------------------------------------------------------- #


def test_mois_annex_01_band_values() -> None:
    rule = MOIS_TECH_LOCAL_ANNEX_01

    assert rule.base_rate == Decimal("0.88")
    assert [(b.upper_bound, b.max_price_score, b.multiplier) for b in rule.price_bands] == [
        (Decimal("500000000"), Decimal("60"), Decimal("4")),
        (Decimal("1000000000"), Decimal("50"), Decimal("2")),
        (None, Decimal("30"), Decimal("1")),
    ]
    assert [b.label for b in rule.price_bands] == [
        "추정가격이 5억원 미만인 용역",
        "추정가격이 10억원 미만 5억원 이상인 용역",
        "추정가격이 10억원 이상인 용역",
    ]
    assert [(t.upper_bound, t.pass_threshold) for t in rule.threshold_bands] == [
        (Decimal("1000000000"), Decimal("95")),
        (None, Decimal("92")),
    ]


def test_mois_annex_02_band_values() -> None:
    rule = MOIS_TECH_LOCAL_ANNEX_02

    assert rule.base_rate == Decimal("0.88")
    assert [(b.upper_bound, b.max_price_score, b.multiplier) for b in rule.price_bands] == [
        (Decimal("100000000"), Decimal("90"), Decimal("20")),
        (Decimal("200000000"), Decimal("80"), Decimal("20")),
        (Decimal("500000000"), Decimal("50"), Decimal("4")),
        (Decimal("1000000000"), Decimal("50"), Decimal("2")),
        (None, Decimal("30"), Decimal("1")),
    ]


def test_mois_annex_03_band_values() -> None:
    rule = MOIS_TECH_LOCAL_ANNEX_03

    assert rule.base_rate == Decimal("0.88")
    assert [(b.upper_bound, b.max_price_score, b.multiplier) for b in rule.price_bands] == [
        (None, Decimal("90"), Decimal("20")),
    ]
    assert [(t.upper_bound, t.pass_threshold) for t in rule.threshold_bands] == [
        (Decimal("1000000000"), Decimal("95")),
        (None, Decimal("92")),
    ]


@pytest.mark.parametrize(
    ("rule", "index", "ratio", "score"),
    [
        (MOIS_TECH_LOCAL_ANNEX_01, 0, "0.8925", "55"),
        (MOIS_TECH_LOCAL_ANNEX_01, 1, "0.905", "45"),
        (MOIS_TECH_LOCAL_ANNEX_01, 2, "0.96", "22"),
        (MOIS_TECH_LOCAL_ANNEX_02, 0, "0.8825", "85"),
        (MOIS_TECH_LOCAL_ANNEX_02, 1, "0.8825", "75"),
        (MOIS_TECH_LOCAL_ANNEX_02, 2, "0.8925", "45"),
        (MOIS_TECH_LOCAL_ANNEX_02, 3, "0.905", "45"),
        (MOIS_TECH_LOCAL_ANNEX_02, 4, "0.96", "22"),
        (MOIS_TECH_LOCAL_ANNEX_03, 0, "0.8825", "85"),
    ],
)
def test_mois_annex_flat_zones(rule, index: int, ratio: str, score: str) -> None:
    zone = servc_tech_flat_zone_for(rule.rule_id, index)

    assert zone is not None
    assert zone.flat_ratio == Decimal(ratio)
    assert zone.flat_score == Decimal(score)
    assert "fbe9a0b783c6_mois373_body.txt" in zone.source


def test_mois_annex_flat_zones_are_distinct_from_pps() -> None:
    """같은 rule_id 로 조달청 평탄을 돌려주지 않는다(예규 전용 키)."""
    pps_zone = servc_tech_flat_zone_for(SERVC_TECH_QUAL_ANNOUNCEMENT_LWLT.rule_id, 0)
    mois_zone = servc_tech_flat_zone_for(MOIS_TECH_LOCAL_ANNEX_01.rule_id, 2)

    assert pps_zone is not None
    assert pps_zone.flat_ratio == Decimal("0.9025")
    assert mois_zone is not None
    assert mois_zone.flat_ratio == Decimal("0.96")


def test_mois_annex_rules_are_registered_as_tech_rules() -> None:
    for rule in MOIS_TECH_LOCAL_ANNEX_RULES:
        assert rule.rule_id in SERVC_TECH_QUAL_RULE_IDS


# --------------------------------------------------------------------------- #
# (4) 낙찰방법명에 P.Q 표기가 없으면 별표를 확정하지 않는다
# --------------------------------------------------------------------------- #


def test_mois_stated_without_annex_token_uses_pq_eval_yn() -> None:
    """낙찰방법명에 P.Q 표기가 없으면 pqEvalYn 으로 별표 1/2 를 가릅니다.

    별표 1 제목은 '사업수행능력평가(P.Q)를 하는 기술용역 평가기준', 별표 2 제목은
    '사업수행능력 평가(P.Q)를 하지 않는 기술용역 평가기준'이라 나라장터의
    pqEvalYn 이 별표 선택 근거가 됩니다. 실제 분포에서 무토큰 공고는 전부 pqEvalYn=Y
    였습니다.
    """
    result = _resolve(METHOD_WITHOUT_PQ_MARK, pq_eval="Y")

    assert result.is_blocked is False
    assert result.rule is not None
    assert result.rule.rule_id == MOIS_TECH_LOCAL_ANNEX_01.rule_id
    assert result.rule.base_rate == Decimal("0.88")
    assert _resolution(result, 2_005_454_545, METHOD_WITHOUT_PQ_MARK).max_price_score == Decimal(
        "30"
    )


def test_mois_stated_without_annex_token_n_pq_uses_annex_02() -> None:
    result = _resolve(METHOD_WITHOUT_PQ_MARK, pq_eval="N")

    assert result.rule is not None
    assert result.rule.rule_id == MOIS_TECH_LOCAL_ANNEX_02.rule_id
    assert result.rule.base_rate == Decimal("0.88")


def test_mois_stated_without_any_token_keeps_pps_rule() -> None:
    """낙찰방법명 표기도 pqEvalYn 도 없으면 예규 별표를 확정하지 않습니다."""
    result = _resolve(METHOD_WITHOUT_PQ_MARK)

    assert result.is_blocked is False
    assert result.rule is not None
    assert result.rule.rule_id == SERVC_TECH_QUAL_ANNOUNCEMENT_LWLT.rule_id
    assert result.rule.base_rate == Decimal("0.90")
    assert result.base_rate == Decimal("0.88")
    assert MOIS_TECH_ANNEX_UNRESOLVED_WARNING in result.warnings


def test_select_mois_tech_annex_rule_returns_none_without_token() -> None:
    assert select_mois_tech_annex_rule(METHOD_WITHOUT_PQ_MARK) is None
    assert select_mois_tech_annex_rule(None) is None


@pytest.mark.parametrize(
    ("method_name", "expected_rule"),
    [
        (METHOD_PQ_10E_OVER, MOIS_TECH_LOCAL_ANNEX_01),
        (METHOD_NON_PQ_1E_2E, MOIS_TECH_LOCAL_ANNEX_02),
        (
            "적격심사제-추정가격이 10억원 미만 5억원 이상인 P.Q 비대상 기술용역의 평가기준",
            MOIS_TECH_LOCAL_ANNEX_02,
        ),
        (METHOD_DISASTER, MOIS_TECH_LOCAL_ANNEX_03),
    ],
)
def test_select_mois_tech_annex_rule_maps_tokens(method_name: str, expected_rule) -> None:
    assert select_mois_tech_annex_rule(method_name) is expected_rule


# --------------------------------------------------------------------------- #
# (5) 예규는 조달청 고시금액 경계를 쓰지 않는다
# --------------------------------------------------------------------------- #


def test_mois_annex_bands_ignore_notice_amount_boundary() -> None:
    """공고일 연도가 달라도 예규 구간의 상한은 금액 그대로여야 합니다."""
    result = _resolve(METHOD_PQ_UNDER_5E, announced="2027-03-02")

    assert result.rule is not None
    assert result.rule.rule_id == MOIS_TECH_LOCAL_ANNEX_01.rule_id
    assert result.rule.price_bands[0].upper_bound == Decimal("500000000")
    assert all(band.label != "추정가격이 고시금액 미만인 용역" for band in result.rule.price_bands)

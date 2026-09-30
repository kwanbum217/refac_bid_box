"""
tests/test_extract_score_params.py

scripts/extract_score_params.py 의 순수 파서를 실측 문서 문자열로 고정한다.

픽스처 문자열은 2026-09-30 코디네이터 워크트리에서 실제로 내려받은 문서에서 그대로
가져왔다. 출처:
  - [별표 9] 수요기관 지정형 적격심사(조달청 일반용역 적격심사 세부기준).hwpx
    (공고 R26BK01707844 첨부)
  - [ATT2]1-1. 입찰공고문.hwp (공고 R26BK01707844 첨부)
  - 조달청 일반용역 적격심사 세부기준(조달청공고 제2026-390호) 제10조
"""

from __future__ import annotations

import io
import zipfile
from decimal import Decimal

from scripts.extract_score_params import (
    BandValue,
    DocumentText,
    ScoreParams,
    band_matches,
    extract_document_text,
    parse_pass_threshold,
    parse_price_formula,
    parse_price_limit,
    select_band,
)

# ----------------------------------------------------------------------------
# 실측 픽스처
# ----------------------------------------------------------------------------

# R26BK01707844 (천수만(서산) 청정어장 재생사업 어장환경개선 용역, 추정가격 269,026,364)
ANNOUNCEMENT_METHOD = "적격심사제-수요기관 지정형 적격심사  추정가격 고시금액 이상"
ANNOUNCEMENT_ESTIMATED_PRICE = 269026364

# 별표 9 의 심사항목 배점한도 표 (입찰가격 행 + 구간 라벨 행)
BOPYO9_ROWS = (
    ("추정가격 5억원 이상", "추정가격 5억원 미만"),
    ("Ⅱ.입찰가격", "※ 입찰가격 평점 계산식 참조", "60", "70"),
    ("①입찰가격 평점 계산식 사업예산규모", "평점 계산식", "예외사항"),
    (
        "추정가격 고시금액 이상",
        "수식입니다.BIGCIRC  `평점(점)`=`배점한도-`2` TIMES  vert  ( {90} over {100} - "
        "{입찰가격} over {예정가격} ) TIMES  100 vert",
        "입찰가격이 예정가격 이하로서 예정가격의 97.5% 이상인 경우에는 입찰가격이 "
        "예정가격의 97.5%인 경우의 점수로 평가",
    ),
    (
        "추정가격 고시금액 미만",
        "수식입니다.BIGCIRC  `평점(점)=배점한도-4 TIMES  vert  ( {90} over {100} - "
        "{입찰가격} over {예정가격} ) TIMES  100 vert",
        "입찰가격이 예정가격 이하로서 예정가격의 93.75% 이상인 경우에는 입찰가격이 "
        "예정가격의 93.75%인 경우의 점수로 평가",
    ),
)

# R26BK01707844 입찰공고문 본문 (통과점수 문구가 "종합평점이 85점"으로 실린다)
ANNOUNCEMENT_TEXT = (
    "동일가격의 최저가 입찰자가 2인 이상으로서 적격심사를 하는 경우에는 종합평점이 "
    "85점 이상인 자 중에서 최고점수인 자를 낙찰자로 결정합니다."
)

# 조달청 일반용역 적격심사 세부기준 제10조 (예외 조항 포함)
CRITERIA_ARTICLE_10 = (
    "제10조(낙찰자 결정) ① 최저가 입찰자에 대한 심사결과 종합평점이 85점(다만, "
    "소프트웨어용역의 중소기업자간 경쟁제품, 여객 육상운송용역은 88점)이상이면 "
    "낙찰자로 결정한다."
)


# ----------------------------------------------------------------------------
# 통과점수 T
# ----------------------------------------------------------------------------


def test_parse_pass_threshold_from_announcement_text() -> None:
    value, evidence = parse_pass_threshold(ANNOUNCEMENT_TEXT)
    assert value == Decimal("85")
    assert evidence is not None
    assert "종합평점" in evidence


def test_parse_pass_threshold_from_criteria_article() -> None:
    value, evidence = parse_pass_threshold(CRITERIA_ARTICLE_10)
    assert value == Decimal("85")
    assert evidence is not None
    assert "제10조" in evidence


def test_parse_pass_threshold_absent() -> None:
    assert parse_pass_threshold("적격심사 기준은 별표에 따른다.") == (None, None)


# ----------------------------------------------------------------------------
# 가격 배점한도 B, 평점계수 k
# ----------------------------------------------------------------------------


def test_parse_price_formula_reads_both_bands_with_base_rate() -> None:
    formulas = parse_price_formula(BOPYO9_ROWS)
    assert len(formulas) == 2
    by_label = {formula.label: formula for formula in formulas}
    assert by_label["추정가격 고시금액 이상"].multiplier == Decimal("2")
    assert by_label["추정가격 고시금액 미만"].multiplier == Decimal("4")
    # 백틱이 낀 수식 개체도 같은 값으로 읽혀야 한다.
    assert by_label["추정가격 고시금액 이상"].base_rate == Decimal("0.9")
    assert by_label["추정가격 고시금액 미만"].base_rate == Decimal("0.9")


def test_parse_price_limit_reads_both_bands() -> None:
    limits = parse_price_limit(BOPYO9_ROWS)
    assert [(limit.label, limit.value) for limit in limits] == [
        ("추정가격 5억원 이상", Decimal("60")),
        ("추정가격 5억원 미만", Decimal("70")),
    ]


def test_band_matches_by_hint_text() -> None:
    assert band_matches("추정가격 고시금액 이상", ANNOUNCEMENT_METHOD, ANNOUNCEMENT_ESTIMATED_PRICE)
    assert not band_matches(
        "추정가격 고시금액 미만", ANNOUNCEMENT_METHOD, ANNOUNCEMENT_ESTIMATED_PRICE
    )


def test_band_matches_by_estimated_price_threshold() -> None:
    label = "추정가격 5억원 미만"
    assert band_matches(label, ANNOUNCEMENT_METHOD, 269_026_364)
    assert not band_matches("추정가격 5억원 이상", ANNOUNCEMENT_METHOD, 269_026_364)


def test_select_band_picks_k_and_b_for_announcement() -> None:
    formulas = parse_price_formula(BOPYO9_ROWS)
    selected_k = select_band(
        [BandValue(label=f.label, value=f.multiplier, evidence=f.evidence) for f in formulas],
        ANNOUNCEMENT_METHOD,
        ANNOUNCEMENT_ESTIMATED_PRICE,
    )
    assert selected_k is not None
    assert selected_k.value == Decimal("2")

    selected_b = select_band(
        parse_price_limit(BOPYO9_ROWS), ANNOUNCEMENT_METHOD, ANNOUNCEMENT_ESTIMATED_PRICE
    )
    assert selected_b is not None
    assert selected_b.value == Decimal("70")


def test_select_band_returns_none_when_ambiguous() -> None:
    candidates = [
        BandValue(label="구간 A", value=Decimal("1"), evidence=""),
        BandValue(label="구간 B", value=Decimal("2"), evidence=""),
    ]
    assert select_band(candidates, ANNOUNCEMENT_METHOD, ANNOUNCEMENT_ESTIMATED_PRICE) is None


# ----------------------------------------------------------------------------
# 첨부 텍스트 추출
# ----------------------------------------------------------------------------


def _minimal_hwpx(cells: list[str]) -> bytes:
    cell_xml = "".join(f"<hp:tc><hp:p><hp:t>{cell}</hp:t></hp:p></hp:tc>" for cell in cells)
    section = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<hs:sec xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph">'
        f"<hp:tbl><hp:tr>{cell_xml}</hp:tr></hp:tbl>"
        "<hp:p><hp:t>종합평점이 85점 이상인 자</hp:t></hp:p>"
        "</hs:sec>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("mimetype", "application/hwp+zip")
        archive.writestr("Contents/section0.xml", section)
    return buffer.getvalue()


def test_extract_document_text_reads_hwpx_rows_and_flat() -> None:
    document = extract_document_text(_minimal_hwpx(["Ⅱ.입찰가격", "20"]))
    assert document.ok
    assert ("Ⅱ.입찰가격", "20") in document.rows
    assert parse_pass_threshold(document.flat)[0] == Decimal("85")


def test_extract_document_text_reports_pdf_reason() -> None:
    document = extract_document_text(b"%PDF-1.7\n%...")
    assert not document.ok
    assert document.reason is not None
    assert "PDF" in document.reason


def test_extract_document_text_reports_unknown_format() -> None:
    document = extract_document_text(b"\x00\x01\x02\x03")
    assert not document.ok
    assert document.reason is not None


# ----------------------------------------------------------------------------
# 결과 정규화
# ----------------------------------------------------------------------------


def test_score_params_as_dict_normalizes_decimals() -> None:
    params = ScoreParams(
        bid_no="R26BK01707844",
        category="Servc",
        max_price_score=Decimal("70.0"),
        multiplier=Decimal("2"),
        pass_threshold=Decimal("85.00"),
        base_rate=Decimal("0.9"),
    )
    payload = params.as_dict()
    assert payload["B_max_price_score"] == "70"
    assert payload["k_multiplier"] == "2"
    assert payload["T_pass_threshold"] == "85"  # noqa: S105 - 임계값 라벨이 pass 를 포함한다
    assert payload["base_rate"] == "0.9"


def test_document_text_ok_flag() -> None:
    assert not DocumentText().ok
    assert DocumentText(flat="x").ok

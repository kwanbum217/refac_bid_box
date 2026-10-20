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
    _HWP_KEEP_RE,
    _WHITESPACE_RE,
    BandValue,
    DocumentText,
    ScoreParams,
    _hwp_formula_rows,
    _hwp_record_text,
    _hwp_records,
    _hwp_section_flat,
    _hwp_table_rows,
    band_matches,
    extract_document_text,
    parse_band_terms,
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
# 추정가격 구간 해석 및 선택 (합성 구간 표)
# ----------------------------------------------------------------------------

# 추정가격 구간이 3개(5억 미만 / 5억 이상 10억 미만 / 10억 이상)인 합성 별표.
# 배점한도 표 행과 구간별 평점 계산식 행을 함께 둔다.
THREE_BAND_ROWS = (
    ("추정가격 5억원 미만", "추정가격 5억원 이상 10억원 미만", "추정가격 10억원 이상"),
    ("Ⅱ.입찰가격", "※ 입찰가격 평점 계산식 참조", "70", "65", "60"),
    (
        "추정가격 5억원 미만",
        "수식입니다.BIGCIRC  `평점(점)=배점한도-4 TIMES  vert  ( {90} over {100} - "
        "{입찰가격} over {예정가격} ) TIMES  100 vert",
        "입찰가격이 예정가격 이하로서 예정가격의 93.75% 이상인 경우의 점수로 평가",
    ),
    (
        "추정가격 5억원 이상 10억원 미만",
        "수식입니다.BIGCIRC  `평점(점)=배점한도-2 TIMES  vert  ( {90} over {100} - "
        "{입찰가격} over {예정가격} ) TIMES  100 vert",
        "입찰가격이 예정가격 이하로서 예정가격의 97.5% 이상인 경우의 점수로 평가",
    ),
    (
        "추정가격 10억원 이상",
        "수식입니다.BIGCIRC  `평점(점)=배점한도-1 TIMES  vert  ( {90} over {100} - "
        "{입찰가격} over {예정가격} ) TIMES  100 vert",
        "입찰가격이 예정가격 이하인 경우의 점수로 평가",
    ),
)

BAND_500_000_000 = 500_000_000
BAND_700_000_000 = 700_000_000
BAND_1_500_000_000 = 1_500_000_000


def test_parse_band_terms_reads_both_ends() -> None:
    terms = parse_band_terms("추정가격 5억원 이상 10억원 미만")
    assert terms == (
        (Decimal("500000000"), "이상"),
        (Decimal("1000000000"), "미만"),
    )


def test_parse_band_terms_reads_single_bound_and_absence() -> None:
    assert parse_band_terms("추정가격 5억원 미만") == ((Decimal("500000000"), "미만"),)
    # 부등호 없는 금액과 고시금액 라벨은 구간 경계로 확정하지 않는다.
    assert parse_band_terms("추정가격 5억원") == ()
    assert parse_band_terms("추정가격 고시금액 이상") == ()


def test_band_matches_two_sided_range() -> None:
    label = "추정가격 5억원 이상 10억원 미만"
    assert band_matches(label, "", BAND_700_000_000)
    assert not band_matches(label, "", BAND_500_000_000 - 1)
    assert not band_matches(label, "", BAND_1_500_000_000)


def test_band_matches_boundary_operators() -> None:
    assert band_matches("추정가격 5억원 이상", "", BAND_500_000_000)
    assert not band_matches("추정가격 5억원 초과", "", BAND_500_000_000)
    assert band_matches("추정가격 5억원 이하", "", BAND_500_000_000)
    assert not band_matches("추정가격 5억원 미만", "", BAND_500_000_000)


def test_select_band_picks_b_from_synthetic_three_band_table() -> None:
    limits = parse_price_limit(THREE_BAND_ROWS)
    assert [(limit.label, limit.value) for limit in limits] == [
        ("추정가격 5억원 미만", Decimal("70")),
        ("추정가격 5억원 이상 10억원 미만", Decimal("65")),
        ("추정가격 10억원 이상", Decimal("60")),
    ]
    selected = select_band(limits, "", BAND_700_000_000)
    assert selected is not None
    assert selected.label == "추정가격 5억원 이상 10억원 미만"
    assert selected.value == Decimal("65")


def test_select_band_picks_k_from_synthetic_three_band_table() -> None:
    formulas = parse_price_formula(THREE_BAND_ROWS)
    candidates = [
        BandValue(label=formula.label, value=formula.multiplier, evidence=formula.evidence)
        for formula in formulas
    ]
    selected = select_band(candidates, "", BAND_1_500_000_000)
    assert selected is not None
    assert selected.label == "추정가격 10억원 이상"
    assert selected.value == Decimal("1")


def test_select_band_rejects_contradicting_single_candidate() -> None:
    candidate = [BandValue(label="추정가격 5억원 이상", value=Decimal("70"), evidence="")]
    # 추정가격이 라벨 구간 밖이면 후보가 하나뿐이어도 고르지 않는다.
    assert select_band(candidate, "", ANNOUNCEMENT_ESTIMATED_PRICE) is None
    assert select_band(candidate, "", BAND_700_000_000) == candidate[0]


def test_select_band_keeps_uninterpretable_single_candidate() -> None:
    candidate = [BandValue(label="", value=Decimal("70"), evidence="")]
    assert select_band(candidate, "", BAND_700_000_000) == candidate[0]


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


# ----------------------------------------------------------------------------
# 바이너리 HWP 표 복원 (합성 레코드)
# ----------------------------------------------------------------------------

_HWP_TAG_PARA_HEADER = 0x42
_HWP_TAG_PARA_TEXT = 0x43
_HWP_TAG_CTRL_HEADER = 0x47
_HWP_TAG_LIST_HEADER = 0x48
_HWP_TAG_TABLE = 0x4D


def _record(tag: int, level: int, payload: bytes) -> bytes:
    header = tag | (level << 10) | (len(payload) << 20)
    return header.to_bytes(4, "little") + payload


def _cell_record(col: int, row: int, row_span: int, col_span: int, text: str, level: int) -> bytes:
    """셀 하나를 LIST_HEADER + 문단(PARA_HEADER·PARA_TEXT)으로 조립한다."""
    header = (
        (1).to_bytes(4, "little")
        + (0x20).to_bytes(4, "little")
        + col.to_bytes(2, "little")
        + row.to_bytes(2, "little")
        + col_span.to_bytes(2, "little")
        + row_span.to_bytes(2, "little")
        + b"\x00" * 8
    )
    return (
        _record(_HWP_TAG_LIST_HEADER, level, header)
        + _record(_HWP_TAG_PARA_HEADER, level, b"\x00" * 22)
        + _record(_HWP_TAG_PARA_TEXT, level + 1, text.encode("utf-16le"))
    )


def _synthetic_section(cells: list[tuple[int, int, int, int, str]], rows: int, cols: int) -> bytes:
    """표 1개(셀 N개)를 담은 합성 BodyText 섹션 바이트를 만든다.

    실제 HWP 5.x 와 같이 CTRL_HEADER(ctrl id 'tbl ') 바로 뒤에 TABLE 레코드가 오고,
    셀은 같은 레벨의 LIST_HEADER 로 이어진다. cells 항목은 (col, row, rowspan, colspan, text).
    """
    level = 2
    data = _record(_HWP_TAG_CTRL_HEADER, level - 1, b"tbl "[::-1] + b"\x00" * 42)
    data += _record(
        _HWP_TAG_TABLE,
        level,
        (0).to_bytes(4, "little") + rows.to_bytes(2, "little") + cols.to_bytes(2, "little"),
    )
    for col, row, row_span, col_span, text in cells:
        data += _cell_record(col, row, row_span, col_span, text, level)
    return data


def test_binary_hwp_table_rows_restored() -> None:
    cells = [
        (0, 0, 1, 1, "심사항목"),
        (1, 0, 1, 1, "심사분야"),
        (2, 0, 1, 1, "입찰가격"),
        (3, 0, 1, 1, "배점한도"),
    ]
    section = _synthetic_section(cells, rows=1, cols=4)
    rows = _hwp_table_rows(_hwp_records(section))
    assert rows == [("심사항목", "심사분야", "입찰가격", "배점한도")]


def test_binary_hwp_table_fills_merged_rowspan_cells() -> None:
    cells = [
        (0, 0, 3, 1, "머리"),
        (1, 0, 1, 1, "가"),
        (1, 1, 1, 1, "나"),
        (1, 2, 1, 1, "다"),
    ]
    section = _synthetic_section(cells, rows=3, cols=2)
    rows = _hwp_table_rows(_hwp_records(section))
    assert rows == [("머리", "가"), ("머리", "나"), ("머리", "다")]


def test_hwp_records_stop_at_truncated_record() -> None:
    section = _synthetic_section([(0, 0, 1, 1, "값")], rows=1, cols=1)
    records = _hwp_records(section + b"\x42\x00\x00")
    assert records
    assert all(isinstance(payload, bytes) for _, _, payload in records)


# ----------------------------------------------------------------------------
# 바이너리 HWP 수식 개체 서식
# ----------------------------------------------------------------------------

HWP_PRICE_FORMULA_ROWS = (
    (
        "2. 입찰가격",
        "o 다음 산식에 의해 산출된 평점 적용 88 입찰가격 "
        "*평점=50-2\u00d7\uff5c( - )\u00d7100\uff5c 100 예정가격",
        "50점",
    ),
    (
        "2. 입찰가격",
        "o 다음 산식에 의해 산출된 평점 적용 88 입찰가격 "
        "* 평점=30 -\uff5c( - )\u00d7100\uff5c 100 예정가격",
        "30점",
    ),
)


def test_parse_price_formula_reads_binary_renderings() -> None:
    formulas = parse_price_formula(HWP_PRICE_FORMULA_ROWS)
    assert [formula.multiplier for formula in formulas] == [Decimal("2"), Decimal("1")]


def test_parse_price_limit_reads_point_suffixed_b_values() -> None:
    limits = parse_price_limit(HWP_PRICE_FORMULA_ROWS)
    assert [(limit.label, limit.value) for limit in limits] == [("", Decimal("50"))]


# ----------------------------------------------------------------------------
# 계산식 서식 확장 (실측 바이너리 HWP 렌더링)
# ----------------------------------------------------------------------------


def test_parse_price_formula_reads_placeholder_with_soft_hyphen() -> None:
    rows = (("입찰가격 평점산식", "ㅇ평점(점) = 배점한도\u00ad4\u00d7"),)
    formulas = parse_price_formula(rows)
    assert [formula.multiplier for formula in formulas] == [Decimal("4")]


def test_parse_price_formula_reads_numeric_style_with_point_suffix() -> None:
    rows = (
        ("입찰가격 평점산식", "평점(점) = 60 - 2 \u00d7 ( 100 - 예정가격 ) \u00d7 100"),
        ("입찰가격 평점산식", "평점 = 90 - 20 \u00d7 ( 100 - 예정가격 ) \u00d7 100"),
    )
    assert [formula.multiplier for formula in parse_price_formula(rows)] == [
        Decimal("2"),
        Decimal("20"),
    ]


def test_parse_price_formula_reads_numeric_style_without_multiplier() -> None:
    rows = (("입찰가격 평점산식", "평점 = 30 - ( 100 - 예정가격 ) \u00d7 100"),)
    assert [formula.multiplier for formula in parse_price_formula(rows)] == [Decimal("1")]


def test_parse_price_formula_reads_bare_limit_style() -> None:
    rows = (("입찰가격 평점산식", "배점한도-60\u00d7 예정가격"),)
    assert [formula.multiplier for formula in parse_price_formula(rows)] == [Decimal("60")]


def test_parse_price_formula_requires_price_context() -> None:
    # 실적계수 계산식은 입찰가격·예정가격 문맥이 없으므로 입찰가격 계산식이 아니다.
    assert parse_price_formula((("▪평점 = 11 \u00d7 실적계수 (실적계수의 상한은 1)",),)) == []
    assert parse_price_formula((("▪평점 = 11 \u00d7 예정가격 (실적계수의 상한은 1)",),))


def test_parse_price_formula_reads_text_base_rate() -> None:
    rows = (
        (
            "입찰가격 평점산식 88 입찰가격 평점(점) = 60 - 2 \u00d7( --- - -------- ) \u00d7 100 "
            "단, 투찰율이 95.5% 초과시 45점 평점 100 예정가격",
        ),
    )
    formulas = parse_price_formula(rows)
    assert [formula.multiplier for formula in formulas] == [Decimal("2")]
    assert formulas[0].base_rate == Decimal("0.88")


def test_extract_document_text_promotes_formula_paragraph_to_row() -> None:
    text = (
        '<?xml version="1.0"?><HWPML><BODY><P>입찰가격 평점산식</P>'
        "<P>ㅇ평점(점) = 배점한도\u00ad4\u00d7 100 예정가격</P></BODY></HWPML>"
    ).encode("utf-8")
    document = extract_document_text(text)
    assert document.ok
    assert [formula.multiplier for formula in parse_price_formula(document.rows)] == [Decimal("4")]


# ----------------------------------------------------------------------------
# 수식 개체(EQEDIT) 및 레코드 텍스트 판독 (합성 레코드)
# ----------------------------------------------------------------------------

_HWP_TAG_EQEDIT = 0x58

# 실측 바이너리 HWP 수식 개체 스크립트. 실제 payload 처럼 앞에 이진 속성 필드가 있고
# 그 뒤에 스크립트 문자열이 UTF-16LE 로 온다.
_EQEDIT_SCRIPT = (
    "평점(점)=배점한도-2 TIMES |( {88} over {100} - {입찰가격} over {예정가격} ) TIMES 100|"
)
_EQUATION_PARAGRAPH = "3) 입찰가격(90점) : 평점 = 90-20\u00d788/100-입찰가격/예정가격)\u00d7100"


def _eqedit_record(script: str, level: int = 2) -> bytes:
    payload = (0).to_bytes(2, "little") + script.encode("utf-16le") + b"\x00\x00"
    return _record(_HWP_TAG_EQEDIT, level, payload)


def test_hwp_record_text_reads_eqedit_script() -> None:
    records = _hwp_records(_eqedit_record(_EQEDIT_SCRIPT))
    text = _hwp_record_text(records)
    assert "배점한도-2 TIMES" in text
    assert "입찰가격" in text
    assert "예정가격" in text


def test_hwp_formula_rows_recovers_eqedit_price_formula() -> None:
    rows = _hwp_formula_rows(_hwp_records(_eqedit_record(_EQEDIT_SCRIPT)))
    assert [formula.multiplier for formula in parse_price_formula(rows)] == [Decimal("2")]


def test_hwp_formula_rows_reads_backticked_eqedit_script() -> None:
    # 실측 수식 개체는 조판에 따라 백틱이 낀다("평점(점)`=`배점한도-`2`").
    script = (
        "평점(점)`=`배점한도-`2` TIMES |( {88} over {100} - {입찰가격} over {예정가격} ) TIMES 100|"
    )
    rows = _hwp_formula_rows(_hwp_records(_eqedit_record(script)))
    assert [formula.multiplier for formula in parse_price_formula(rows)] == [Decimal("2")]


def test_hwp_formula_rows_recovers_paragraph_lost_by_flat_decode() -> None:
    """홀수 크기 레코드 뒤 문단은 전체 스트림 디코딩에서 정렬이 어긋나 유실된다.

    레코드 단위 판독은 이를 회수한다(실측 공고 20220626311 의 유실 유형).
    """
    odd = _record(_HWP_TAG_PARA_HEADER, 1, b"\x00" * 21)  # payload 길이 21(홀수)
    paragraph = _record(_HWP_TAG_PARA_TEXT, 1, _EQUATION_PARAGRAPH.encode("utf-16le"))
    section = odd + paragraph

    whole = _WHITESPACE_RE.sub("", _HWP_KEEP_RE.sub("", section.decode("utf-16le", "ignore")))
    assert "평점=90-20" not in whole  # 전체 스트림 디코딩에서는 유실

    rows = _hwp_formula_rows(_hwp_records(section))
    assert [formula.multiplier for formula in parse_price_formula(rows)] == [Decimal("20")]


# ----------------------------------------------------------------------------
# 바이너리 HWP 평문(레코드 단위 문단 텍스트)
# ----------------------------------------------------------------------------

# 실측 원문: 한국농어촌공사 일반용역 적격심사 세부기준(20251001판) 제10조.
# 이 문단은 PARA_TEXT 레코드에 있지만, 본문 스트림 전체 디코딩으로는 유실되어
# 평문(flat)에서 '85점' 이 0회였다.
_HWP_ARTICLE_10 = (
    "제10조(낙찰자 결정) ① 최저가 입찰자에 대한 심사결과 종합평점이 85점(다만, "
    "소프트웨어용역의 중소기업자간 경쟁제품, 여객 육상운송용역은 88점)이상이면 "
    "낙찰자로 결정한다."
)


def _section_with_odd_sized_record() -> bytes:
    """홀수 크기 레코드 뒤에 PARA_TEXT 문단이 오는 본문 스트림 섹션을 만든다."""
    odd = _record(_HWP_TAG_PARA_HEADER, 1, b"\x00" * 21)  # payload 길이 21(홀수)
    paragraph = _record(_HWP_TAG_PARA_TEXT, 1, _HWP_ARTICLE_10.encode("utf-16le"))
    return odd + paragraph


def test_hwp_section_flat_recovers_paragraph_after_odd_sized_record() -> None:
    """홀수 크기 레코드 뒤 문단은 평문(flat)에서 유실되지 않아야 한다."""
    section = _section_with_odd_sized_record()

    # 고치기 전 방식(본문 스트림 전체 디코딩)에서는 정렬이 어긋나 문단이 사라진다.
    whole_stream = section.decode("utf-16le", "ignore")
    assert "85점" not in whole_stream
    assert "낙찰자로 결정" not in whole_stream

    flat = _hwp_section_flat(section)
    assert "85점" in flat
    assert "낙찰자로 결정" in flat
    assert parse_pass_threshold(flat)[0] == Decimal("85")


def test_hwp_section_flat_falls_back_to_stream_decode_when_records_unusable() -> None:
    """레코드 파싱이 비어 있으면 기존 스트림 전체 디코딩으로 대체한다."""
    section = b"\x00\x00" + "평문이 그대로 남아야 한다".encode("utf-16le")
    assert _hwp_records(section) == []

    flat = _hwp_section_flat(section)
    assert flat == _HWP_KEEP_RE.sub("", section.decode("utf-16le", "ignore"))
    assert "평문이 그대로 남아야 한다" in flat


def test_hwp_section_flat_reads_paragraph_text_when_records_available() -> None:
    """레코드가 있으면 레코드 단위 문단 텍스트를 평문으로 쓴다."""
    section = _record(_HWP_TAG_PARA_TEXT, 1, _HWP_ARTICLE_10.encode("utf-16le"))
    flat = _hwp_section_flat(section)
    assert flat == _hwp_record_text(_hwp_records(section))
    assert "종합평점이 85점" in flat

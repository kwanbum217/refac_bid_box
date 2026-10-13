"""`src/app/services/evaluation_rules_history.py` 이력 레지스트리 시험.

생성물 정합(명세 YAML == 커밋된 모듈), 개정판 구간 라우팅, B·k·기준비율·통과점수·하한율의
YAML 대조, `고시금액` 경계 처리, 생성 스크립트의 `--check` 계약을 네트워크·DB 없이 검증합니다.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from scripts.build_pps_history_rules import (
    DEFAULT_OUTPUT,
    DEFAULT_YAML,
    _attachment_code,
    _boundary_literal,
    _decimal_literal,
    main,
    render_module,
)
from src.app.services import evaluation_rules_history as erhist

# ----------------------------------------------------------------------------
# 생성물 정합
# ----------------------------------------------------------------------------


def test_committed_module_matches_yaml_render() -> None:
    """커밋된 모듈이 명세 YAML 에서 방금 생성한 결과와 같은지 봅니다(`--check` 와 같은 계약)."""
    assert DEFAULT_OUTPUT.read_text(encoding="utf-8") == render_module(DEFAULT_YAML)


def test_build_check_mode_passes(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--check"]) == 0
    assert "일치" in capsys.readouterr().out


def test_build_check_mode_detects_drift(tmp_path: Path) -> None:
    drifted = tmp_path / "drifted.py"
    drifted.write_text("HISTORY_REVISIONS = ()\n", encoding="utf-8")
    assert main(["--check", "--out", str(drifted)]) == 1

    missing = tmp_path / "missing.py"
    assert main(["--check", "--out", str(missing)]) == 1


def test_build_writes_module(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "generated.py"
    assert main(["--out", str(out)]) == 0
    assert out.read_text(encoding="utf-8") == render_module(DEFAULT_YAML)
    assert "생성" in capsys.readouterr().out


def test_build_rejects_unknown_service_type(tmp_path: Path) -> None:
    spec = yaml.safe_load(DEFAULT_YAML.read_text(encoding="utf-8"))
    spec["revisions"] = [spec["revisions"][0]]
    spec["revisions"][0]["attachments"] = [spec["revisions"][0]["attachments"][0]]
    spec["revisions"][0]["attachments"][0]["service_type"] = "미확인용역"
    broken = tmp_path / "broken.yaml"
    broken.write_text(yaml.safe_dump(spec, allow_unicode=True), encoding="utf-8")
    with pytest.raises(ValueError, match="용역 유형 코드"):
        render_module(broken)


def test_build_rejects_empty_revisions(tmp_path: Path) -> None:
    broken = tmp_path / "empty.yaml"
    broken.write_text(yaml.safe_dump({"revisions": []}, allow_unicode=True), encoding="utf-8")
    with pytest.raises(ValueError, match="revisions"):
        render_module(broken)


def test_build_rejects_overlong_generated_line(tmp_path: Path) -> None:
    """생성 행이 100 자를 넘으면 서식을 깨뜨리므로 생성을 거부합니다."""
    spec = yaml.safe_load(DEFAULT_YAML.read_text(encoding="utf-8"))
    spec["revisions"] = [spec["revisions"][0]]
    attachment = spec["revisions"][0]["attachments"][0]
    attachment["title"] = "가" * 120
    spec["revisions"][0]["attachments"] = [attachment]
    broken = tmp_path / "long.yaml"
    broken.write_text(yaml.safe_dump(spec, allow_unicode=True), encoding="utf-8")
    with pytest.raises(ValueError, match="100 자"):
        render_module(broken)


def test_generator_helpers() -> None:
    assert _attachment_code("별표 1") == "ATTACH_01"
    assert _attachment_code("별표 3의2") == "ATTACH_03_2"
    assert _attachment_code("별표 12") == "ATTACH_12"
    with pytest.raises(ValueError, match="별표 표기"):
        _attachment_code("부속 1")
    assert _decimal_literal(None) == "None"
    assert _decimal_literal(2.0) == 'Decimal("2")'
    assert _decimal_literal("95.5") == 'Decimal("95.5")'
    assert _boundary_literal(None) == "None"
    assert _boundary_literal(500000000) == 'Decimal("500000000")'
    assert _boundary_literal("고시금액") == "NOTICE_AMOUNT_BOUNDARY"
    with pytest.raises(ValueError, match="경계 표기"):
        _boundary_literal("기준금액")


# ----------------------------------------------------------------------------
# 고시금액 상수
# ----------------------------------------------------------------------------


def test_notice_amount_only_evidenced_years() -> None:
    # 2023 년만 저장소에 근거가 있다(src/ml/notice_amount.py, 기획재정부 고시 제2022-32호).
    assert erhist.history_notice_amount_for_year(2023) == 220_000_000
    # 2019~2022 년 값은 저장소에 근거가 없어 값을 만들지 않는다.
    for year in (2015, 2016, 2017, 2018, 2019, 2020, 2021, 2022, 2024):
        assert erhist.history_notice_amount_for_year(year) is None


# ----------------------------------------------------------------------------
# 개정판 구간 라우팅
# ----------------------------------------------------------------------------


def test_dates_before_and_after_history_window_are_not_routed() -> None:
    miss, reason = erhist.resolve_history_band("2015-04-30", "ACADEMIC", 300_000_000, None)
    assert miss is None
    assert "개정판이 없습니다" in str(reason)
    miss, reason = erhist.resolve_history_band("2023-05-01", "ACADEMIC", 300_000_000, None)
    assert miss is None
    assert "개정판이 없습니다" in str(reason)


def test_revision_windows_are_half_open_on_the_ends() -> None:
    """각 판의 시행일과 종료일 당일이 그 판으로 라우팅되는지 봅니다."""
    for revision in erhist.HISTORY_REVISIONS:
        if not revision.routable:
            continue
        for day in (revision.effective_from, revision.effective_to):
            for attachment in revision.attachments:
                resolution, reason = erhist.resolve_history_band(
                    day, attachment.service_type, 600_000_000, 220_000_000
                )
                if resolution is None:
                    # 경계가 고시금액이고 값을 주지 않은 호출은 미확정이 정상이다.
                    assert "고시금액" in str(reason)
                    continue
                assert resolution.revision_key == revision.notice_key


def test_2016_48_is_excluded_and_2016_51_covers_the_window() -> None:
    excluded = [item for item in erhist.HISTORY_REVISIONS if item.notice_key == "2016-48"]
    assert len(excluded) == 1
    assert excluded[0].routable is False
    assert excluded[0].exclusion_reason

    resolution, reason = erhist.resolve_history_band("2016-06-01", "FACILITY", 300_000_000, None)
    assert reason is None
    assert resolution is not None
    assert resolution.revision_key == "2016-51"
    assert resolution.revision_notice_no == "조달청공고 제2016-51호"


# ----------------------------------------------------------------------------
# 구간 경계와 값
# ----------------------------------------------------------------------------


def _resolve(day: str, service_type: str, price: object, notice_amount: object = None):
    resolution, reason = erhist.resolve_history_band(
        day,
        service_type,
        price,
        notice_amount,  # type: ignore[arg-type]
    )
    assert reason is None, reason
    assert resolution is not None
    return resolution


def test_price_band_boundary_is_inclusive_on_the_upper_side() -> None:
    # 시설분야 별표는 추정가격 5억원 경계이며 5억원은 상위 구간(이상)에 든다.
    over = _resolve("2015-08-01", "FACILITY", Decimal("500000000"))
    assert over.max_price_score == Decimal("60")
    under = _resolve("2015-08-01", "FACILITY", Decimal("499999999"))
    assert under.max_price_score == Decimal("70")


def test_academic_boundary_moves_with_the_revision() -> None:
    # 2015-41 은 2억원, 2018-36 은 2.1억원 경계다.
    assert _resolve("2015-08-01", "ACADEMIC", Decimal("200000000")).max_price_score == Decimal("40")
    assert _resolve("2015-08-01", "ACADEMIC", Decimal("199999999")).max_price_score == Decimal("70")
    assert _resolve("2018-05-01", "ACADEMIC", Decimal("210000000")).max_price_score == Decimal("40")
    assert _resolve("2018-05-01", "ACADEMIC", Decimal("209999999")).max_price_score == Decimal("70")


def test_formula_axis_can_differ_from_the_price_axis() -> None:
    """정보통신(비대상)은 B 는 5억원, 평점산식은 2.1억원 경계를 씁니다."""
    mid = _resolve("2018-05-01", "SW_NON_SME", Decimal("250000000"))
    assert mid.max_price_score == Decimal("70")
    assert mid.multiplier == Decimal("2")
    assert mid.lwlt_rate == Decimal("80.495")

    low = _resolve("2018-05-01", "SW_NON_SME", Decimal("100000000"))
    assert low.max_price_score == Decimal("70")
    assert low.multiplier == Decimal("4")
    assert low.flat_ratio == Decimal("91.75")
    assert low.lwlt_rate == Decimal("84.245")

    high = _resolve("2018-05-01", "SW_NON_SME", Decimal("600000000"))
    assert high.max_price_score == Decimal("60")
    assert high.multiplier == Decimal("2")


def test_insurance_has_no_flat_ratio() -> None:
    resolution = _resolve("2021-06-01", "INSURANCE", Decimal("600000000"))
    assert resolution.max_price_score == Decimal("60")
    assert resolution.multiplier == Decimal("0.375")
    assert resolution.base_ratio == Decimal("88")
    assert resolution.flat_ratio is None
    assert resolution.pass_score == Decimal("85")
    assert resolution.lwlt_rate == Decimal("47.995")


def test_known_notice_amount_resolves_token_boundary() -> None:
    """2022-42 학술연구는 고시금액 경계를 쓰며, 2023 년 값이 있으면 풀린다."""
    over = _resolve("2023-02-01", "ACADEMIC", Decimal("220000000"), 220_000_000)
    assert over.revision_key == "2022-42"
    assert over.max_price_score == Decimal("40")
    assert over.multiplier == Decimal("2")
    assert over.lwlt_rate == Decimal("80.495")

    under = _resolve("2023-02-01", "ACADEMIC", Decimal("219999999"), 220_000_000)
    assert under.max_price_score == Decimal("70")
    assert under.multiplier == Decimal("4")
    assert under.lwlt_rate == Decimal("84.245")


def test_unknown_notice_amount_returns_reason_without_guessing() -> None:
    resolution, reason = erhist.resolve_history_band("2019-06-01", "ACADEMIC", 90_000_000, None)
    assert resolution is None
    assert "고시금액" in str(reason)
    # 값을 넘겨주면 같은 호출이 풀린다(추정이 아니라 입력 부재가 원인임을 확인).
    resolution, reason = erhist.resolve_history_band(
        "2019-06-01", "ACADEMIC", 90_000_000, 220_000_000
    )
    assert reason is None
    assert resolution is not None
    assert resolution.multiplier == Decimal("4")


def test_missing_service_type_and_missing_price_return_reasons() -> None:
    resolution, reason = erhist.resolve_history_band("2018-05-01", "TECH", 300_000_000, None)
    assert resolution is None
    assert "TECH" in str(reason)

    resolution, reason = erhist.resolve_history_band("2018-05-01", "ACADEMIC", None, None)
    assert resolution is None
    assert "추정가격" in str(reason)

    resolution, reason = erhist.resolve_history_band(None, "ACADEMIC", 300_000_000, None)
    assert resolution is None
    assert "공고일" in str(reason)

    resolution, reason = erhist.resolve_history_band("2018-05-01", "SW", 300_000_000, None)
    assert resolution is None
    assert "SW 별표가 없습니다" in str(reason)


def test_price_outside_every_band_returns_reason() -> None:
    # 폐기물 별표는 5억원 경계이고 경계 밖은 없다. 0 이하는 추정가격 미상으로 본다.
    resolution, reason = erhist.resolve_history_band("2018-05-01", "WASTE", 0, None)
    assert resolution is None
    assert "추정가격" in str(reason)


def test_resolution_carries_source_metadata() -> None:
    resolution = _resolve("2022-06-01", "PASSENGER_TRANSPORT", Decimal("300000000"))
    assert resolution.rule_id == "SERVC_QUAL_HIST_2022_42_ATTACH_05"
    assert resolution.attachment == "별표 5"
    assert resolution.service_type == "PASSENGER_TRANSPORT"
    assert resolution.source_service_type == "여객 육상운송용역"
    assert resolution.pass_score == Decimal("88")
    assert "pps_servc_qual_history_2015_2022.yaml" in resolution.source


# ----------------------------------------------------------------------------
# YAML 대조 (개정판 3개)
# ----------------------------------------------------------------------------

_REVISION_SAMPLES = (
    ("2015-41", "시설분야용역", Decimal("400000000"), None),
    ("2015-41", "시설분야용역", Decimal("600000000"), None),
    ("2017-95", "정보통신용역(중소기업자간 경쟁제품 비대상)", Decimal("250000000"), None),
    ("2017-95", "정보통신용역(중소기업자간 경쟁제품 비대상)", Decimal("100000000"), None),
    ("2022-42", "학술연구용역", Decimal("100000000"), 220_000_000),
    ("2022-42", "학술연구용역", Decimal("300000000"), 220_000_000),
)


def test_three_revisions_match_the_yaml_spec() -> None:
    """개정판 3개의 임의 지점을 YAML 원문과 직접 대조합니다."""
    spec = yaml.safe_load(DEFAULT_YAML.read_text(encoding="utf-8"))
    revisions = {item["notice_key"]: item for item in spec["revisions"]}
    dates = {"2015-41": "2015-08-01", "2017-95": "2017-12-05", "2022-42": "2022-06-01"}
    for notice_key, raw_type, price, notice_amount in _REVISION_SAMPLES:
        revision = revisions[notice_key]
        attachment = next(
            item for item in revision["attachments"] if item["service_type"] == raw_type
        )
        expected = _expected_tier(attachment, price, notice_amount)
        resolution = _resolve(dates[notice_key], erhist_code(raw_type), price, notice_amount)
        assert resolution.revision_key == notice_key
        assert resolution.max_price_score == Decimal(str(expected["B"]))
        assert resolution.multiplier == Decimal(str(expected["k"]))
        assert resolution.base_ratio == Decimal(str(expected["base_ratio"]))
        assert resolution.pass_score == Decimal(str(expected["pass_score"]))
        assert resolution.lwlt_rate == Decimal(str(expected["lwlt_rate"]))
        if expected["flat_ratio"] is None:
            assert resolution.flat_ratio is None
        else:
            assert resolution.flat_ratio == Decimal(str(expected["flat_ratio"]))


def erhist_code(raw_type: str) -> str:
    """시험용 지역 대조기를 쓰지 않고 명세 표기를 코드로 옮깁니다."""
    from scripts.build_pps_history_rules import YAML_SERVICE_TYPE_CODES

    return YAML_SERVICE_TYPE_CODES[raw_type]


def _expected_tier(attachment: dict, price: Decimal, notice_amount: object) -> dict:
    def side(value: object) -> Decimal | None:
        if value is None:
            return None
        if isinstance(value, str):
            assert value == "고시금액"
            assert notice_amount is not None
            return Decimal(str(notice_amount))
        return Decimal(str(value))

    for band in attachment["bands"]:
        low, high = side(band["price_lower"]), side(band["price_upper"])
        if low is not None and price < low:
            continue
        if high is not None and price >= high:
            continue
        for tier in band["score_tiers"]:
            t_low, t_high = side(tier["formula_lower"]), side(tier["formula_upper"])
            if t_low is not None and price < t_low:
                continue
            if t_high is not None and price >= t_high:
                continue
            return {
                "B": band["B"],
                "k": tier["k"],
                "base_ratio": tier["base_ratio"],
                "flat_ratio": tier["flat_ratio"],
                "pass_score": tier["pass_score"],
                "lwlt_rate": tier["lwlt_rate"],
            }
    raise AssertionError("명세에서 대응 구간을 찾지 못했습니다.")


def test_module_table_shape_is_intact() -> None:
    keys = [revision.notice_key for revision in erhist.HISTORY_REVISIONS]
    assert keys == [
        "2015-41",
        "2016-48",
        "2016-51",
        "2017-35",
        "2017-82",
        "2017-95",
        "2018-36",
        "2019-31",
        "2020-10",
        "2020-30",
        "2021-2",
        "2022-42",
    ]
    revisions_without_insurance = {
        "2015-41",
        "2016-48",
        "2016-51",
        "2017-35",
        "2017-82",
        "2017-95",
        "2018-36",
        "2019-31",
        "2020-10",
        "2020-30",
    }
    for revision in erhist.HISTORY_REVISIONS:
        codes = [item.service_type for item in revision.attachments]
        assert len(codes) == len(set(codes))
        has_insurance = "INSURANCE" in codes
        assert has_insurance is (revision.notice_key not in revisions_without_insurance)

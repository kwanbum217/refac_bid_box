"""
tests/test_price_score_verification.py

입찰가격 평점 검증기와 통과 가능 낙찰가 구간 역산 단위 테스트.

가이드 원본 규칙 회귀(56.98점), 반올림 경계, k=0, B-N 음수, Q 누락, 하한율 미달을
각각 하나씩 덮고, 역산 구간 경계/내부/외부 표본을 calculate_price_score 로 직접
대조합니다. DB, HTTP, 파일 I/O, 시스템 시각에 의존하지 않는 순수 함수 테스트입니다.
"""

from decimal import Decimal
from typing import ClassVar

import pytest

from src.app.services import price_score_verification as psv
from src.app.services.evaluation_scoring import (
    calculate_min_bid_amount,
    calculate_price_score,
    compute_price_ratio,
)
from src.app.services.price_score_verification import (
    invert_pass_bid_range,
    round_price_ratio,
    verify_price_score,
)


class TestRoundPriceRatio:
    """입찰가격 비율 반올림 (소수점 다섯째 자리 반올림, 넷째 자리 확정)."""

    def test_guide_raw_ratio_rounds_to_four_decimals(self) -> None:
        # 참고 자료 예시: 407,448,800 / 500,000,000 = 0.8148976 -> 0.8149
        assert round_price_ratio(Decimal("0.8148976")) == Decimal("0.8149")

    def test_half_up_boundary_rounds_up(self) -> None:
        assert round_price_ratio(Decimal("0.81485")) == Decimal("0.8149")

    def test_just_below_half_rounds_down(self) -> None:
        assert round_price_ratio(Decimal("0.814849")) == Decimal("0.8148")

    def test_matches_canonical_compute_price_ratio(self) -> None:
        bid = Decimal("407448800")
        pred = Decimal("500000000")
        assert round_price_ratio(bid / pred) == compute_price_ratio(bid, pred)


class TestGuideRegression:
    """가이드 실전 예시(예정가격 5억, 입찰가 407,448,800, B=70, k=2, 기준 88%) 고정."""

    def test_guide_example_is_exactly_56_98(self) -> None:
        res = verify_price_score(
            bid_price=Decimal("407448800"),
            pred_price=Decimal("500000000"),
            base_rate=Decimal("88"),
            max_price_score=Decimal("70"),
            multiplier=Decimal("2"),
        )
        assert res.status == "verified"
        assert res.is_verifiable is True
        assert res.price_ratio == Decimal("0.8149")
        assert res.base_rate_ratio == Decimal("0.88")
        assert res.deviation == Decimal("6.51")
        assert res.deduction == Decimal("13.02")
        assert res.score == Decimal("56.98")

    def test_guide_example_matches_canonical_calculator(self) -> None:
        canonical = calculate_price_score(
            bid_price=Decimal("407448800"),
            pred_price=Decimal("500000000"),
            base_rate=Decimal("88"),
            max_price_score=Decimal("70"),
            multiplier=Decimal("2"),
        )
        assert canonical.score == Decimal("56.98")


class TestVerifyPriceScoreUnverifiable:
    """입력 누락/형식 오류는 예외 없이 확인 불가 결과로 반환한다."""

    def test_missing_pred_price_is_unverifiable(self) -> None:
        res = verify_price_score(
            bid_price=Decimal("407448800"),
            pred_price=None,
            base_rate=Decimal("88"),
            max_price_score=Decimal("70"),
            multiplier=Decimal("2"),
        )
        assert res.status == "unverifiable"
        assert res.is_verifiable is False
        assert res.score is None
        assert any("예정가격" in reason for reason in res.reasons)

    def test_zero_pred_price_is_unverifiable(self) -> None:
        res = verify_price_score(
            bid_price=Decimal("100"),
            pred_price=Decimal("0"),
            base_rate=Decimal("90"),
            max_price_score=Decimal("30"),
            multiplier=Decimal("2"),
        )
        assert res.is_verifiable is False
        assert res.score is None

    def test_negative_bid_price_is_unverifiable(self) -> None:
        res = verify_price_score(
            bid_price=Decimal("-1"),
            pred_price=Decimal("500000000"),
            base_rate=Decimal("88"),
            max_price_score=Decimal("70"),
            multiplier=Decimal("2"),
        )
        assert res.is_verifiable is False
        assert res.score is None

    def test_verify_delegates_to_canonical_scorer(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # 평점 산식을 재구현하지 않고 evaluation_scoring.calculate_price_score 를 호출하는지 확인
        calls: list[tuple[tuple[object, ...], dict[str, object]]] = []
        original = psv.calculate_price_score

        def spy(*args: object, **kwargs: object) -> object:
            calls.append((args, kwargs))
            return original(*args, **kwargs)

        monkeypatch.setattr(psv, "calculate_price_score", spy)
        res = verify_price_score(
            bid_price=Decimal("407448800"),
            pred_price=Decimal("500000000"),
            base_rate=Decimal("88"),
            max_price_score=Decimal("70"),
            multiplier=Decimal("2"),
        )
        assert len(calls) == 1
        assert res.score == Decimal("56.98")


class TestInvertPassBidRange:
    """통과 가능 낙찰가 구간 역산의 정확성과 방어적 분기 검증."""

    BASE_ARGS: ClassVar[dict[str, Decimal]] = {
        "pass_threshold": Decimal("95"),  # T
        "non_price_score": Decimal("70"),  # Q
        "base_rate": Decimal("0.90"),
        "max_price_score": Decimal("30"),  # B
        "multiplier": Decimal("2"),  # k
        "pred_price": Decimal("100000000"),
    }

    def test_interval_bounds_pass_and_outside_amounts_fail(self) -> None:
        # N = 95 - 70 = 25, 허용차 = (30 - 25) / 200 = 0.025
        # 비율 구간 = [0.875, 0.925]
        res = invert_pass_bid_range(**self.BASE_ARGS)
        assert res.status == "feasible"
        assert res.is_feasible is True
        assert res.required_price_score == Decimal("25")
        assert res.tolerance == Decimal("0.025")
        assert res.ratio_low == Decimal("0.875")
        assert res.ratio_high == Decimal("0.925")
        assert res.ratio_grid_low == Decimal("0.8750")
        assert res.ratio_grid_high == Decimal("0.9250")
        assert res.amount_low == Decimal("87495000")
        assert res.amount_high == Decimal("92504999")

        n = res.required_price_score
        for amount in (
            res.amount_low,
            Decimal("90000000"),
            res.amount_high,
        ):
            assert amount is not None
            score = calculate_price_score(
                amount, self.BASE_ARGS["pred_price"], Decimal("0.90"), Decimal("30"), Decimal("2")
            ).score
            assert score >= n

        for amount in (res.amount_low - 1, res.amount_high + 1):
            score = calculate_price_score(
                amount, self.BASE_ARGS["pred_price"], Decimal("0.90"), Decimal("30"), Decimal("2")
            ).score
            assert score < n

    def test_non_grid_tolerance_snaps_to_four_decimal_grid(self) -> None:
        # N = 95 - 69.998 = 25.002, 허용차 = 4.998 / 200 = 0.02499
        # 연속 구간 = [0.87501, 0.92499], 격자 구간 = [0.8751, 0.9249]
        res = invert_pass_bid_range(
            pass_threshold=Decimal("95"),
            non_price_score=Decimal("69.998"),
            base_rate=Decimal("0.90"),
            max_price_score=Decimal("30"),
            multiplier=Decimal("2"),
            pred_price=Decimal("100000000"),
        )
        assert res.status == "feasible"
        assert res.ratio_low == Decimal("0.87501")
        assert res.ratio_high == Decimal("0.92499")
        assert res.ratio_grid_low == Decimal("0.8751")
        assert res.ratio_grid_high == Decimal("0.9249")
        assert res.amount_low == Decimal("87505000")
        assert res.amount_high == Decimal("92494999")

        n = res.required_price_score
        for amount in (res.amount_low, res.amount_high):
            score = calculate_price_score(
                amount, Decimal("100000000"), Decimal("0.90"), Decimal("30"), Decimal("2")
            ).score
            assert score >= n
        for amount in (res.amount_low - 1, res.amount_high + 1):
            score = calculate_price_score(
                amount, Decimal("100000000"), Decimal("0.90"), Decimal("30"), Decimal("2")
            ).score
            assert score < n

    def test_lwlt_within_range_trims_effective_low(self) -> None:
        res = invert_pass_bid_range(
            **self.BASE_ARGS,
            announcement_lwlt_rate=Decimal("90.005"),
        )
        assert res.status == "feasible"
        assert res.lwlt_status == "within_range"
        assert res.lwlt_rate_ratio == Decimal("0.90005")
        assert (
            res.lwlt_amount
            == calculate_min_bid_amount(Decimal("100000000"), Decimal("90.005")).min_bid_amount
        )
        assert res.amount_low == Decimal("87495000")
        assert res.effective_amount_low == Decimal("90005000")
        assert res.effective_amount_high == res.amount_high
        assert res.effective_ratio_low == Decimal("0.90005")

    def test_lwlt_excludes_all_passing_amounts(self) -> None:
        # 하한율 95% 의 최저금액 95,000,000원이 평점 통과 상한 92,504,999원보다 높다.
        res = invert_pass_bid_range(
            **self.BASE_ARGS,
            announcement_lwlt_rate=Decimal("95"),
        )
        assert res.status == "impossible"
        assert res.is_feasible is False
        assert res.lwlt_status == "excludes_all"
        assert res.effective_amount_low is None
        assert res.effective_amount_high is None
        assert any("낙찰하한율" in reason for reason in res.reasons)

    def test_k_zero_makes_full_ratio_range_feasible(self) -> None:
        # k=0 이면 P = B 로 고정. N = 25 <= B = 30 이므로 모든 비율이 통과한다.
        res = invert_pass_bid_range(
            pass_threshold=Decimal("95"),
            non_price_score=Decimal("70"),
            base_rate=Decimal("0.90"),
            max_price_score=Decimal("30"),
            multiplier=Decimal("0"),
            pred_price=Decimal("100000000"),
        )
        assert res.status == "feasible"
        assert res.tolerance is None
        assert res.ratio_low == Decimal("0")
        assert res.ratio_high == Decimal("1")
        assert res.amount_low == Decimal("0")
        assert res.amount_high == Decimal("100000000")
        mid = calculate_price_score(
            Decimal("50000000"), Decimal("100000000"), Decimal("0.90"), Decimal("30"), Decimal("0")
        )
        assert mid.score == Decimal("30") >= res.required_price_score

    def test_k_zero_is_impossible_when_below_required_score(self) -> None:
        res = invert_pass_bid_range(
            pass_threshold=Decimal("95"),
            non_price_score=Decimal("60"),
            base_rate=Decimal("0.90"),
            max_price_score=Decimal("30"),
            multiplier=Decimal("0"),
            pred_price=Decimal("100000000"),
        )
        assert res.status == "impossible"
        assert res.is_feasible is False
        assert res.ratio_low is None

    def test_impossible_when_required_exceeds_max_price_score(self) -> None:
        # B - N = 20 - 23 = -3 < 0
        res = invert_pass_bid_range(
            pass_threshold=Decimal("95"),
            non_price_score=Decimal("72"),
            base_rate=Decimal("0.90"),
            max_price_score=Decimal("20"),
            multiplier=Decimal("2"),
            pred_price=Decimal("100000000"),
        )
        assert res.status == "impossible"
        assert res.is_feasible is False
        assert res.required_price_score == Decimal("23")
        assert any("배점한도" in reason for reason in res.reasons)

    def test_impossible_when_won_unit_has_no_amount_in_window(self) -> None:
        # 예정가격 3원에서는 허용 구간에 정수 금액이 존재하지 않는다.
        res = invert_pass_bid_range(
            pass_threshold=Decimal("95"),
            non_price_score=Decimal("70"),
            base_rate=Decimal("0.90"),
            max_price_score=Decimal("30"),
            multiplier=Decimal("2"),
            pred_price=Decimal("3"),
        )
        assert res.status == "impossible"
        assert res.amount_low is None
        assert res.amount_high is None

    def test_missing_non_price_score_is_unverifiable(self) -> None:
        res = invert_pass_bid_range(
            pass_threshold=Decimal("95"),
            non_price_score=None,
            base_rate=Decimal("0.90"),
            max_price_score=Decimal("30"),
            multiplier=Decimal("2"),
            pred_price=Decimal("100000000"),
        )
        assert res.status == "unverifiable"
        assert res.is_feasible is False
        assert any("비가격 정량점수" in reason for reason in res.reasons)

    def test_missing_multiplier_does_not_divide_by_zero(self) -> None:
        res = invert_pass_bid_range(
            pass_threshold=Decimal("95"),
            non_price_score=Decimal("70"),
            base_rate=Decimal("0.90"),
            max_price_score=Decimal("30"),
            multiplier=None,
            pred_price=Decimal("100000000"),
        )
        assert res.status == "unverifiable"
        assert res.tolerance is None

    def test_missing_pred_price_is_unverifiable(self) -> None:
        res = invert_pass_bid_range(
            pass_threshold=Decimal("95"),
            non_price_score=Decimal("70"),
            base_rate=Decimal("0.90"),
            max_price_score=Decimal("30"),
            multiplier=Decimal("2"),
            pred_price=None,
        )
        assert res.status == "unverifiable"
        assert res.amount_low is None

    def test_lwlt_not_provided_leaves_effective_equal_to_window(self) -> None:
        res = invert_pass_bid_range(**self.BASE_ARGS)
        assert res.lwlt_status == "not_provided"
        assert res.lwlt_amount is None
        assert res.effective_amount_low == res.amount_low
        assert res.effective_amount_high == res.amount_high

"""재발주 이력 특징 테스트.

핵심은 두 가지입니다. 정규화가 같은 사업의 서로 다른 해 공고를 한 키로 묶는가,
그리고 이력이 미래를 보지 않는가입니다.
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.ml.repeat_history import (
    DEFAULT_REPEAT_RATE,
    NO_HISTORY_DAYS,
    attach_repeat_history,
    normalize_title,
    repeat_key,
)


@pytest.mark.parametrize(
    ("left", "right"),
    [
        (
            "2026학년도 창남초등학교 통학버스 임차 용역 입찰 공고",
            "2025학년도 창남초등학교 통학버스 임차 용역 재공고",
        ),
        ("2024년 A청사 청소용역", "2023년 A청사 청소용역(긴급)"),
        ("[재공고] 도서관 시설관리 용역", "도서관 시설관리 용역 제2차"),
    ],
)
def test_normalize_title_groups_same_business_across_years(left: str, right: str) -> None:
    assert normalize_title(left) == normalize_title(right)


def test_normalize_title_keeps_different_business_apart() -> None:
    assert normalize_title("2024년 청사 청소용역") != normalize_title("2024년 청사 경비용역")


def test_repeat_key_rejects_too_short_title() -> None:
    # 정규화 후 남는 글자가 없으면 기관명만으로 키가 만들어져 서로 다른 사업이
    # 한 덩어리가 됩니다. 그런 행은 이력을 붙이지 않습니다.
    assert repeat_key("A기관", "2024") == ""
    assert repeat_key("A기관", "청소용역") != ""


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "dminstt_nm": ["A기관", "A기관", "A기관", "B기관"],
            "bid_ntce_nm": [
                "2023년 청사 청소용역",
                "2024년 청사 청소용역",
                "2025년 청사 청소용역",
                "2024년 청사 청소용역",
            ],
            "winning_rate": [88.0, 90.0, 95.0, 70.0],
            "openg_dt": pd.to_datetime(["2023-03-01", "2024-03-01", "2025-03-01", "2024-06-01"]),
        }
    )


def test_attach_repeat_history_uses_only_past_rows() -> None:
    out = attach_repeat_history(_frame())

    # 첫 회차는 이력이 없습니다.
    assert out.loc[0, "is_repeat"] == 0.0
    assert out.loc[0, "repeat_cnt"] == 0.0
    assert out.loc[0, "repeat_hist_rate"] == pytest.approx(DEFAULT_REPEAT_RATE)
    assert out.loc[0, "repeat_days_since"] == NO_HISTORY_DAYS

    # 두 번째 회차는 첫 회차만 봅니다. 세 번째(95.0)를 보면 누수입니다.
    assert out.loc[1, "is_repeat"] == 1.0
    assert out.loc[1, "repeat_cnt"] == 1.0
    assert out.loc[1, "repeat_prev_rate"] == pytest.approx(0.88)
    assert out.loc[1, "repeat_hist_rate"] == pytest.approx(0.88)

    # 세 번째 회차는 앞의 둘 평균입니다.
    assert out.loc[2, "repeat_cnt"] == 2.0
    assert out.loc[2, "repeat_hist_rate"] == pytest.approx(0.89)
    assert out.loc[2, "repeat_prev_rate"] == pytest.approx(0.90)


def test_attach_repeat_history_separates_institutions() -> None:
    out = attach_repeat_history(_frame())
    # 같은 사업명이라도 발주처가 다르면 남의 이력을 가져오면 안 됩니다.
    assert out.loc[3, "is_repeat"] == 0.0
    assert out.loc[3, "repeat_hist_rate"] == pytest.approx(DEFAULT_REPEAT_RATE)


def test_attach_repeat_history_measures_interval_in_days() -> None:
    out = attach_repeat_history(_frame())
    assert out.loc[1, "repeat_days_since"] == pytest.approx(366.0)


def test_attach_repeat_history_survives_missing_columns() -> None:
    out = attach_repeat_history(pd.DataFrame({"winning_rate": [88.0]}))
    assert out.loc[0, "is_repeat"] == 0.0
    assert out.loc[0, "repeat_hist_rate"] == pytest.approx(DEFAULT_REPEAT_RATE)


def test_attach_repeat_history_ignores_out_of_range_rates() -> None:
    df = _frame()
    df.loc[0, "winning_rate"] = 999.0
    out = attach_repeat_history(df)
    # 이상치는 이력에서 빠지므로 두 번째 회차는 이력이 없는 것과 같습니다.
    assert out.loc[1, "repeat_cnt"] == 0.0


def test_build_default_feature_map_exposes_repeat_features() -> None:
    from src.ml.features import build_default_feature_map

    feature_map = build_default_feature_map(
        {
            "presmpt_prce": 100_000_000,
            "is_repeat": 1.0,
            "repeat_cnt": 3.0,
            "repeat_hist_rate": 0.91,
            "repeat_prev_rate": 0.92,
            "repeat_hist_std": 0.01,
            "repeat_days_since": 358.0,
        }
    )
    assert feature_map["is_repeat"] == pytest.approx(1.0)
    assert feature_map["repeat_prev_rate"] == pytest.approx(0.92)
    assert feature_map["repeat_days_since"] == pytest.approx(358.0)


def test_build_default_feature_map_defaults_without_history() -> None:
    from src.ml.features import build_default_feature_map

    feature_map = build_default_feature_map({"presmpt_prce": 100_000_000})
    assert feature_map["is_repeat"] == pytest.approx(0.0)
    assert feature_map["repeat_hist_rate"] == pytest.approx(DEFAULT_REPEAT_RATE)

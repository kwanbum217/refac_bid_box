"""eval_servc_freshness 의 인자화·JSON 출력 시험.

실제 parquet 을 읽거나 LightGBM 을 학습하지 않도록 build_frame 과 fit_operational 을
작은 가짜 프레임·상수 예측 모델로 바꿉니다.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from scripts import eval_servc_freshness as freshness
from src.ml.trainer import TRAINING_FEATURES


class ConstantModel:
    def __init__(self, value: float) -> None:
        self.value = value

    def predict(self, frame: pd.DataFrame) -> np.ndarray:
        return np.full(len(frame), self.value, dtype=float)


@pytest.fixture
def fakes(monkeypatch: pytest.MonkeyPatch) -> dict[str, list]:
    dates = pd.date_range("2024-01-01", "2026-10-01", freq="6h")
    frame = pd.DataFrame(
        np.zeros((len(dates), len(TRAINING_FEATURES))), columns=list(TRAINING_FEATURES)
    )
    frame["openg_dt"] = dates
    frame["winning_rate"] = np.linspace(0.0, 1.0, len(dates))
    frame["raw_lwlt"] = np.where(np.arange(len(dates)) % 2 == 0, np.nan, 1.0)

    calls: dict[str, list] = {"parquet": [], "fits": []}

    def build_frame(path: object) -> pd.DataFrame:
        calls["parquet"].append(path)
        return frame

    def fit_operational(train: pd.DataFrame, features: list[str]) -> ConstantModel:
        calls["fits"].append(train["openg_dt"].max())
        return ConstantModel(0.5)

    monkeypatch.setattr(freshness, "build_frame", build_frame)
    monkeypatch.setattr(freshness, "fit_operational", fit_operational)
    return calls


def test_default_args_keep_existing_parquet_and_splits(
    fakes: dict[str, list], capsys: pytest.CaptureFixture[str]
) -> None:
    assert freshness.main([]) == 0

    assert [path.as_posix() for path in fakes["parquet"]] == [freshness.PARQUET.as_posix()]
    assert len(fakes["fits"]) == len(freshness.SPLITS) * 2
    printed = capsys.readouterr().out
    for title, *_ in freshness.SPLITS:
        assert title in printed


def test_split_argument_replaces_defaults(
    fakes: dict[str, list], capsys: pytest.CaptureFixture[str]
) -> None:
    assert freshness.main(["--split", "사용자 분할|2026-03-01|2026-04-01|2026-05-01"]) == 0

    assert len(fakes["fits"]) == 2
    printed = capsys.readouterr().out
    assert "사용자 분할" in printed
    assert freshness.SPLITS[0][0] not in printed


@pytest.mark.parametrize(
    "raw",
    [
        "제목|2026-03-01|2026-04-01",
        "제목|2026-05-01|2026-04-01|2026-06-01",
        "제목|2026-03-01|2026-06-01|2026-05-01",
        "제목|2026-04-01|2026-04-01|2026-05-01",
        "제목|날짜아님|2026-04-01|2026-05-01",
    ],
)
def test_malformed_split_is_rejected(fakes: dict[str, list], raw: str) -> None:
    with pytest.raises(SystemExit):
        freshness.main(["--split", raw])

    assert fakes["parquet"] == []
    assert fakes["fits"] == []


def test_output_writes_rows_per_split_and_group(fakes: dict[str, list], tmp_path) -> None:
    output = tmp_path / "freshness.json"
    assert (
        freshness.main(
            [
                "--split",
                "첫 분할|2026-03-01|2026-04-01|2026-05-01",
                "--split",
                "둘째 분할|2026-04-01|2026-05-01|2026-06-01",
                "--output",
                str(output),
            ]
        )
        == 0
    )

    records = json.loads(output.read_text(encoding="utf-8"))
    assert len(records) == 6
    assert [record["split"] for record in records] == ["첫 분할"] * 3 + ["둘째 분할"] * 3
    assert [record["group"] for record in records] == ["전체", "하한율 보유", "하한율 결측"] * 2
    assert set(records[0]) == {
        "split",
        "group",
        "n",
        "mae_stale",
        "mae_fresh",
        "diff",
        "t",
        "hit_stale",
        "hit_fresh",
        "bias_stale",
        "bias_fresh",
    }
    assert records[0]["n"] == records[1]["n"] + records[2]["n"]

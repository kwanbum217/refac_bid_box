import numpy as np
import pandas as pd

from scripts.eval_servc_candidates_unbiased import attach_ewm_history, paired


def test_attach_ewm_history_uses_ratio_and_excludes_same_timestamp():
    frame = pd.DataFrame(
        {
            "dminstt_nm": ["기관A", "기관A", "기관A", "기관A"],
            "openg_dt": pd.to_datetime(["2024-01-01", "2024-01-01", "2024-02-01", "2024-02-01"]),
            "winning_rate": [80.0, 82.0, 90.0, 95.0],
            "inst_hist_rate": [0.925, 0.925, 0.810, 0.810],
        }
    )

    column = attach_ewm_history(frame, halflife=20)

    assert frame.loc[0, column] == 0.925
    assert frame.loc[1, column] == 0.925
    assert frame.loc[2, column] == frame.loc[3, column]
    assert 0.80 <= frame.loc[2, column] <= 0.82
    assert frame[column].between(0.0, 1.0).all()


def test_paired_reports_candidate_advantage_and_detection_limit():
    result = paired(np.array([-0.1, -0.2, -0.15, -0.05]), "절대오차")

    assert result["평균 차이"] < 0
    assert result["최소 감지 차이"] > 0
    assert result["판정"] == "후보 우세"

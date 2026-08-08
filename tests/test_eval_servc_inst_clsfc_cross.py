import numpy as np
import pandas as pd

from scripts.eval_servc_inst_clsfc_cross import (
    apply_offsets,
    offsets,
    oracle_table,
    set_cell,
)


def _frame(cells: list[str], errors: list[float]) -> pd.DataFrame:
    frame = pd.DataFrame(
        {
            "dminstt_nm": ["기관A"] * len(cells),
            "clsfc_nm": cells,
            "err": errors,
        }
    )
    frame["abs_err"] = frame["err"].abs()
    return set_cell(frame, ["dminstt_nm", "clsfc_nm"])


def test_offsets_skips_cells_below_min_rows():
    frame = _frame(["큰셀"] * 12 + ["작은셀"] * 3, [1.0] * 12 + [5.0] * 3)

    table = offsets(frame, min_rows=10, stat="median")

    assert list(table.index) == ["기관A | 큰셀"]
    assert table.iloc[0] == 1.0


def test_offsets_median_resists_skew_that_moves_the_mean():
    errors = [0.1] * 11 + [20.0]
    frame = _frame(["셀"] * 12, errors)

    median = offsets(frame, min_rows=10, stat="median").iloc[0]
    mean = offsets(frame, min_rows=10, stat="mean").iloc[0]

    assert median == 0.1
    assert mean > 1.0


def test_apply_offsets_leaves_uncovered_cells_untouched():
    frame = _frame(["보정"] * 10 + ["미보정"] * 2, [2.0] * 10 + [3.0] * 2)
    table = offsets(frame, min_rows=10, stat="median")

    result = apply_offsets(frame, table)

    assert np.allclose(result[:10], 0.0)
    assert np.allclose(result[10:], 3.0)


def test_oracle_gains_on_cell_bias_and_median_beats_mean_under_skew():
    """셀마다 일정한 편향이 있으면 오라클은 그것을 걷어냅니다.

    한쪽 꼬리가 긴 셀에서는 평균 오프셋이 중앙값 오프셋보다 불리합니다. 소분류
    단독 오프셋이 평균으로 기각된 배경이 이 성질입니다.
    """
    rng = np.random.default_rng(42)
    skewed = list(rng.normal(1.0, 0.1, 30)) + list(rng.normal(9.0, 0.1, 6))
    balanced = list(rng.normal(-1.0, 0.1, 36))
    frame = _frame(["왜도셀"] * 36 + ["대칭셀"] * 36, skewed + balanced)

    table = oracle_table({2025: frame})
    picked = table[table["최소 표본"] == 10].set_index("오프셋")["개선"]

    assert picked["median"] > 0
    assert picked["median"] > picked["mean"]

import pandas as pd

from scripts.compare_servc_models_paired import (
    evaluate_paired_samples,
    print_paired_evaluation,
)


def _paired_frame(actual: list[float], chal_err: list[float]) -> pd.DataFrame:
    size = len(actual)
    return pd.DataFrame(
        {
            "actual": actual,
            "base_err": [1.0] * size,
            "chal_err": chal_err,
            "base_width": [2.0] * size,
            "chal_width": [1.8] * size,
            "base_covered": [True] * size,
            "chal_covered": [True] * size,
            "missing_provenance": [False] * size,
            "base_fallback": [False] * size,
            "challenger_fallback": [False] * size,
            "same_actual_model": [False] * size,
        }
    )


def test_evaluation_excludes_outside_rows_only_from_decision_scope():
    frame = _paired_frame([70.0, 90.0, 110.0, 50.0], [0.9, 1.0, 1.1, 0.0])

    evaluation = evaluate_paired_samples(frame)

    assert evaluation["outside_count"] == 1
    assert evaluation["outside_ratio"] == 0.25
    assert evaluation["reporting"]["n"] == 4
    assert evaluation["decision"]["n"] == 3


def test_evaluation_warns_when_reporting_and_decision_verdicts_differ(capsys):
    frame = _paired_frame(
        [80.0, 90.0, 100.0, 105.0, 50.0, 50.0, 50.0, 50.0],
        [0.9, 1.1, 0.9, 1.1, 0.0, 0.1, 0.2, 0.3],
    )

    evaluation = evaluate_paired_samples(frame)
    print_paired_evaluation(evaluation)
    output = capsys.readouterr().out

    assert evaluation["reporting"]["verdict"] == "challenger 우세"
    assert evaluation["decision"]["verdict"] == "판별 불가"
    assert evaluation["verdict_mismatch"] is True
    assert "주의: 판정이 어긋납니다" in output
    assert "전량 'challenger 우세' -> 범위 내 '판별 불가'" in output


def test_collect_since_adds_opening_date_lower_bound():
    from sqlalchemy.dialects import mysql

    from scripts.eval_servc_api_path import collect

    captured = {}

    class _Session:
        def execute(self, stmt):
            captured["sql"] = str(
                stmt.compile(dialect=mysql.dialect(), compile_kwargs={"literal_binds": True})
            )

            class _Result:
                def all(self):
                    return []

            return _Result()

    collect(_Session(), 2026, 10, 42, "Servc", since="2026-10-15")
    assert "rl_openg_dt >= '2026-10-15'" in captured["sql"]

    collect(_Session(), 2026, 10, 42, "Servc")
    assert ">= '2026-10-15'" not in captured["sql"]

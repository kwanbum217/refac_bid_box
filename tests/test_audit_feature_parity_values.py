import pandas as pd

from scripts.audit_feature_parity_values import (
    AUDITED_FEATURES,
    compare,
    split_differences,
    summarize,
)


def test_audit_uses_servc_feature_contract():
    assert "inst_ewm_rate" in AUDITED_FEATURES


def test_audit_compares_and_summarizes_ewm_value():
    records = []
    for train_value, serve_value in ((0.88, 0.89), (0.90, 0.91)):
        pairs = compare(
            pd.Series({"inst_ewm_rate": train_value}),
            {"inst_ewm_rate": serve_value},
        )
        records.append(
            {
                "inst_ewm_rate__t": pairs["inst_ewm_rate"][0],
                "inst_ewm_rate__s": pairs["inst_ewm_rate"][1],
            }
        )

    table = summarize(records)

    row = table[table["특징"] == "inst_ewm_rate"].iloc[0]
    assert row["평균절대차"] == 0.01


def test_audit_separates_known_timing_and_unexpected_differences():
    table = pd.DataFrame(
        [
            {
                "특징": "inst_ewm_rate",
                "종류": "수치",
                "일치율": 0.1,
                "상관": 0.89,
                "평균절대차": 0.01,
            },
            {
                "특징": "log_price",
                "종류": "수치",
                "일치율": 0.1,
                "상관": 0.5,
                "평균절대차": 1.0,
            },
        ]
    )

    known, unexpected = split_differences(table)

    assert known["특징"].tolist() == ["inst_ewm_rate"]
    assert unexpected["특징"].tolist() == ["log_price"]


def test_audit_escalates_known_feature_outside_measured_guard():
    table = pd.DataFrame(
        [
            {
                "특징": "inst_ewm_rate",
                "종류": "수치",
                "일치율": 0.0,
                "상관": 0.1,
                "평균절대차": 0.5,
            }
        ]
    )

    known, unexpected = split_differences(table)

    assert known.empty
    assert unexpected["특징"].tolist() == ["inst_ewm_rate"]

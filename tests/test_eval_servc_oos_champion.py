"""
tests/test_eval_servc_oos_champion.py

Servc 현 Champion 유효 OOS 고정 평가 하네스 단위 테스트.

DB 또는 모델 파일 없이 순수 Python 로직만 검증합니다.
- OOS 표본 집합 정의 상수 검증
- 행 키 SHA-256 결박 재현성 및 순서 독립성
- 평가 지표 계산 정확성 (MAE, RMSE, 편향, 밴드, 구간 피복률)
- 집단별 지표 분기 (하한율 보유/결측)
- run_servc_oos_evaluation dry-run 스키마 무결성
- 표본 수 불일치 시 canonical=False 표기
"""

from __future__ import annotations

import hashlib

import numpy as np
import pandas as pd
import pytest

from scripts.eval_servc_oos_champion import (
    EXPECTED_OOS_SAMPLE_COUNT,
    OOS_CUTOFF_TIMESTAMP,
    OOS_EVAL_SCHEMA,
    OOS_EVAL_SCHEMA_VERSION,
    compute_frame_keys_sha256,
    compute_group_metrics,
    compute_oos_metrics,
    compute_sample_keys_sha256,
    run_servc_oos_evaluation,
)

# ---------------------------------------------------------------------------
# 섹션 1: OOS 표본 집합 정의 상수 검증
# ---------------------------------------------------------------------------


class TestOosSampleConstants:
    def test_expected_sample_count_is_canonical(self):
        assert EXPECTED_OOS_SAMPLE_COUNT == 3589

    def test_cutoff_timestamp_format(self):
        # 'YYYY-MM-DD HH:MM:SS' 형식 검증
        parts = OOS_CUTOFF_TIMESTAMP.split(" ")
        assert len(parts) == 2, "cutoff 타임스탬프는 날짜+시간 두 부분이어야 합니다."
        date_part, time_part = parts
        assert date_part == "2026-08-03"
        assert time_part == "11:00:00"

    def test_cutoff_timestamp_post_feature_store_freeze(self):
        # 컷오프는 feature store parquet 2026-08-03 이후여야 합니다.
        assert OOS_CUTOFF_TIMESTAMP >= "2026-08-03 11:00:00"

    def test_schema_name_and_version(self):
        assert OOS_EVAL_SCHEMA == "ORCA_SERVC_OOS_EVAL_V1"
        assert OOS_EVAL_SCHEMA_VERSION == "1.0.0"


# ---------------------------------------------------------------------------
# 섹션 2: 행 키 SHA-256 결박 재현성 및 순서 독립성
# ---------------------------------------------------------------------------


class TestKeysSha256:
    def test_order_independent_same_hash(self):
        keys = ["001:001:Servc", "002:002:Servc", "003:003:Servc"]
        h1 = compute_sample_keys_sha256(keys)
        h2 = compute_sample_keys_sha256(list(reversed(keys)))
        assert h1 == h2, "키 목록 순서가 달라도 동일한 해시여야 합니다."

    def test_deterministic_across_calls(self):
        keys = ["bid001:001:Servc", "bid002:002:Servc"]
        assert compute_sample_keys_sha256(keys) == compute_sample_keys_sha256(keys)

    def test_different_keys_produce_different_hash(self):
        h1 = compute_sample_keys_sha256(["key_a:001:Servc"])
        h2 = compute_sample_keys_sha256(["key_b:001:Servc"])
        assert h1 != h2

    def test_empty_keys_returns_sha256_of_empty(self):
        result = compute_sample_keys_sha256([])
        expected = hashlib.sha256(b"").hexdigest()
        assert result == expected

    def test_sha256_length_is_64_hex(self):
        h = compute_sample_keys_sha256(["test:001:Servc"])
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_compute_frame_keys_sha256_empty_df(self):
        result = compute_frame_keys_sha256(pd.DataFrame())
        assert result == hashlib.sha256(b"").hexdigest()

    def test_compute_frame_keys_sha256_matches_manual(self):
        df = pd.DataFrame(
            {
                "bid_ntce_no": ["2026001", "2026002"],
                "bid_ntce_ord": ["001", "001"],
                "category": ["Servc", "Servc"],
            }
        )
        # bid_ntce_ord.zfill(3) 을 거치므로 이미 3자리
        expected_keys = ["2026001:001:Servc", "2026002:001:Servc"]
        expected_hash = compute_sample_keys_sha256(expected_keys)
        assert compute_frame_keys_sha256(df) == expected_hash


# ---------------------------------------------------------------------------
# 섹션 3: 평가 지표 계산 정확성
# ---------------------------------------------------------------------------


class TestComputeOosMetrics:
    def _make_df(self, actual, pred, low=None, high=None):
        data = {"actual": actual, "pred": pred}
        if low is not None:
            data["low"] = low
            data["high"] = high
        return pd.DataFrame(data)

    def test_mae_calculation(self):
        df = self._make_df([85.0, 90.0, 95.0], [84.0, 91.0, 96.0])
        m = compute_oos_metrics(df)
        # |85-84| + |90-91| + |95-96| = 1+1+1 = 3, mean = 1.0
        assert abs(m["mae"] - 1.0) < 1e-6

    def test_rmse_calculation(self):
        df = self._make_df([85.0, 90.0], [83.0, 92.0])
        m = compute_oos_metrics(df)
        # errors: -2, 2 -> squared: 4, 4 -> mean: 4 -> sqrt: 2.0
        assert abs(m["rmse"] - 2.0) < 1e-6

    def test_bias_positive_overestimate(self):
        df = self._make_df([80.0, 80.0], [82.0, 82.0])
        m = compute_oos_metrics(df)
        assert m["bias"] == pytest.approx(2.0, abs=1e-4)

    def test_bias_negative_underestimate(self):
        df = self._make_df([90.0, 90.0], [88.0, 88.0])
        m = compute_oos_metrics(df)
        assert m["bias"] == pytest.approx(-2.0, abs=1e-4)

    def test_hit_rate_05_all_within(self):
        df = self._make_df([85.0, 90.0], [85.3, 89.8])
        m = compute_oos_metrics(df)
        assert m["hit_rate_05"] == pytest.approx(1.0)

    def test_hit_rate_05_none_within(self):
        df = self._make_df([85.0, 90.0], [86.0, 91.0])
        m = compute_oos_metrics(df)
        assert m["hit_rate_05"] == pytest.approx(0.0)

    def test_accuracy_bands_all_present(self):
        df = self._make_df([85.0], [85.0])
        m = compute_oos_metrics(df)
        for band in [0.5, 1.0, 2.0, 3.0, 5.0]:
            key = f"within_{band}_pct"
            assert key in m["accuracy_bands"], f"밴드 '{key}'가 결과에 없습니다."

    def test_accuracy_bands_counts_correct(self):
        # 오차 0.3: within_0.5=1, within_1.0=1, 오차 0.7: within_0.5=0, within_1.0=1
        df = self._make_df([85.0, 90.0], [85.3, 90.7])
        m = compute_oos_metrics(df)
        assert m["accuracy_bands"]["within_0.5_pct"]["count"] == 1
        assert m["accuracy_bands"]["within_0.5_pct"]["ratio"] == pytest.approx(0.5)
        assert m["accuracy_bands"]["within_1.0_pct"]["count"] == 2

    def test_coverage_perfect_interval(self):
        df = self._make_df(
            [85.0, 90.0, 95.0],
            [85.0, 90.0, 95.0],
            low=[84.0, 89.0, 94.0],
            high=[86.0, 91.0, 96.0],
        )
        m = compute_oos_metrics(df)
        assert m["coverage"] == pytest.approx(1.0)
        assert m["coverage_gap"] == pytest.approx(0.1, abs=1e-4)

    def test_coverage_none_without_interval_columns(self):
        df = self._make_df([85.0, 90.0], [84.0, 91.0])
        m = compute_oos_metrics(df)
        assert m["coverage"] is None
        assert m["coverage_gap"] is None
        assert m["median_interval_width"] is None

    def test_median_interval_width(self):
        df = self._make_df(
            [85.0, 90.0],
            [85.0, 90.0],
            low=[83.0, 88.0],
            high=[87.0, 94.0],
        )
        m = compute_oos_metrics(df)
        # widths: 4.0, 6.0 -> median = 5.0
        assert m["median_interval_width"] == pytest.approx(5.0, abs=1e-4)

    def test_empty_df_returns_none_metrics(self):
        m = compute_oos_metrics(pd.DataFrame())
        assert m["sample_count"] == 0
        assert m["mae"] is None
        assert m["rmse"] is None
        assert m["bias"] is None

    def test_sample_count_matches_input(self):
        n = 100
        rng = np.random.default_rng(seed=42)
        df = pd.DataFrame(
            {
                "actual": rng.uniform(80, 100, n),
                "pred": rng.uniform(80, 100, n),
            }
        )
        m = compute_oos_metrics(df)
        assert m["sample_count"] == n


# ---------------------------------------------------------------------------
# 섹션 4: 집단별 지표 분기 (하한율 보유/결측)
# ---------------------------------------------------------------------------


class TestComputeGroupMetrics:
    def _make_scored_df(self):
        return pd.DataFrame(
            {
                "actual": [85.0, 86.0, 92.0, 93.0],
                "pred": [84.5, 85.5, 91.5, 92.5],
                "is_lwlt_missing": [False, False, True, True],
            }
        )

    def test_group_keys_present(self):
        result = compute_group_metrics(self._make_scored_df())
        assert "with_lwlt" in result
        assert "missing_lwlt" in result

    def test_group_counts(self):
        result = compute_group_metrics(self._make_scored_df())
        assert result["with_lwlt"]["sample_count"] == 2
        assert result["missing_lwlt"]["sample_count"] == 2

    def test_empty_df_returns_empty(self):
        result = compute_group_metrics(pd.DataFrame())
        assert result == {}

    def test_missing_column_returns_empty(self):
        df = pd.DataFrame({"actual": [85.0], "pred": [84.0]})
        result = compute_group_metrics(df)
        assert result == {}

    def test_group_mae_differs_between_groups(self):
        # with_lwlt: 오차 0.5, missing_lwlt: 오차 1.5
        df = pd.DataFrame(
            {
                "actual": [85.0, 90.0],
                "pred": [84.5, 88.5],
                "is_lwlt_missing": [False, True],
            }
        )
        result = compute_group_metrics(df)
        assert result["with_lwlt"]["mae"] == pytest.approx(0.5)
        assert result["missing_lwlt"]["mae"] == pytest.approx(1.5)


# ---------------------------------------------------------------------------
# 섹션 5: run_servc_oos_evaluation dry-run 스키마 무결성
# ---------------------------------------------------------------------------


class TestRunServcOosEvaluationDryRun:
    def _make_samples_df(self, n=3589):
        return pd.DataFrame(
            {
                "bid_id": range(1, n + 1),
                "bid_ntce_no": [f"2026{i:06d}" for i in range(1, n + 1)],
                "bid_ntce_ord": ["001"] * n,
                "category": ["Servc"] * n,
                "openg_dt": ["2026-08-10 10:00:00"] * n,
                "sucsf_bid_amt": [1_000_000] * n,
                "actual_rate": [85.0] * n,
                "presmpt_prce": [1_000_000] * n,
                "base_amount": [None] * n,
            }
        )

    def test_dry_run_returns_required_schema_keys(self):
        df = self._make_samples_df()
        result = run_servc_oos_evaluation(samples_df=df, dry_run=True)
        required_keys = [
            "schema",
            "version",
            "evaluated_at",
            "dry_run",
            "canonical",
            "expected_sample_count",
            "actual_sample_count",
            "sample_count_diff",
            "sample_keys_sha256",
            "model_provenance",
            "overall_metrics",
            "group_metrics",
            "skipped_count",
            "sample_definition",
        ]
        for key in required_keys:
            assert key in result, f"결과에 필수 키 '{key}'가 없습니다."

    def test_dry_run_schema_name_matches_constant(self):
        df = self._make_samples_df()
        result = run_servc_oos_evaluation(samples_df=df, dry_run=True)
        assert result["schema"] == OOS_EVAL_SCHEMA
        assert result["version"] == OOS_EVAL_SCHEMA_VERSION

    def test_dry_run_flag_is_true(self):
        df = self._make_samples_df()
        result = run_servc_oos_evaluation(samples_df=df, dry_run=True)
        assert result["dry_run"] is True

    def test_canonical_true_when_count_matches(self):
        df = self._make_samples_df(n=EXPECTED_OOS_SAMPLE_COUNT)
        result = run_servc_oos_evaluation(samples_df=df, dry_run=True)
        assert result["canonical"] is True
        assert result["sample_count_diff"] == 0

    def test_canonical_false_when_count_differs(self):
        df = self._make_samples_df(n=EXPECTED_OOS_SAMPLE_COUNT - 10)
        result = run_servc_oos_evaluation(samples_df=df, dry_run=True)
        assert result["canonical"] is False
        assert result["sample_count_diff"] == -10

    def test_sample_keys_sha256_is_hex64(self):
        df = self._make_samples_df(n=5)
        result = run_servc_oos_evaluation(samples_df=df, dry_run=True)
        sha = result["sample_keys_sha256"]
        assert len(sha) == 64
        assert all(c in "0123456789abcdef" for c in sha)

    def test_sample_keys_sha256_deterministic(self):
        df = self._make_samples_df(n=10)
        r1 = run_servc_oos_evaluation(samples_df=df, dry_run=True)
        r2 = run_servc_oos_evaluation(samples_df=df, dry_run=True)
        assert r1["sample_keys_sha256"] == r2["sample_keys_sha256"]

    def test_expected_sample_count_is_3589(self):
        df = self._make_samples_df()
        result = run_servc_oos_evaluation(samples_df=df, dry_run=True)
        assert result["expected_sample_count"] == 3589

    def test_model_provenance_keys_present(self):
        df = self._make_samples_df()
        result = run_servc_oos_evaluation(samples_df=df, dry_run=True)
        prov = result["model_provenance"]
        for key in ["model_id", "weights_sha256", "weights_exist", "model_version"]:
            assert key in prov, f"model_provenance에 '{key}' 키가 없습니다."

    def test_sample_definition_mentions_cutoff(self):
        df = self._make_samples_df()
        result = run_servc_oos_evaluation(samples_df=df, dry_run=True)
        assert OOS_CUTOFF_TIMESTAMP in result["sample_definition"]

    def test_empty_samples_returns_schema(self):
        df = pd.DataFrame()
        result = run_servc_oos_evaluation(samples_df=df, dry_run=False)
        assert result["schema"] == OOS_EVAL_SCHEMA
        assert result["actual_sample_count"] == 0

    def test_no_session_and_no_samples_raises(self):
        with pytest.raises(ValueError, match="session 또는 samples_df"):
            run_servc_oos_evaluation(session=None, samples_df=None)

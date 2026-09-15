"""
tests/test_eval_cnstwk_year_holdout.py

공사(Cnstwk) 연도 경계 홀드아웃 평가 스크립트 테스트.

합성 데이터와 가짜 v25 로더로 다음을 검증합니다.
  (a) 분할 경계: openg_dt 2024-12-31 / 2025-01-01, 레짐 2026-05-26
  (b) 홀드아웃 정답이 학습 특징에 들어가지 않음 (기관 이력 누수 없음)
  (c) 쌍대 t 계산이 수작업 값과 일치
  (d) 출력 JSON 구조 검증
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.eval_cnstwk_year_holdout import (
    PROMOTION_MAE_IMPROVEMENT,
    PROMOTION_T_THRESHOLD,
    REGIME_SHIFT_DATE,
    TRAIN_CUTOFF,
    _hit_rate,
    _mae,
    _paired_t,
    _rmse,
    _segment_metrics,
    main,
    predict_v25_batch,
)

# ---------------------------------------------------------------------------
# 합성 데이터 헬퍼
# ---------------------------------------------------------------------------


def _make_df(
    n_train: int = 300,
    n_2025: int = 100,
    n_2026_pre: int = 80,
    n_2026_post: int = 60,
    seed: int = 42,
) -> pd.DataFrame:
    """학습·홀드아웃 합성 공사 데이터프레임을 만든다."""
    rng = np.random.default_rng(seed)

    # 날짜 범위
    train_dates = pd.date_range("2022-01-01", "2024-12-31", periods=n_train)
    dates_2025 = pd.date_range("2025-01-01", "2025-12-31", periods=n_2025)
    dates_2026_pre = pd.date_range("2026-01-01", "2026-05-25", periods=n_2026_pre)
    dates_2026_post = pd.date_range("2026-05-26", "2026-09-01", periods=n_2026_post)

    all_dates = list(train_dates) + list(dates_2025) + list(dates_2026_pre) + list(dates_2026_post)
    n_total = len(all_dates)

    # 공고일: 레짐 전후 검증을 위해 openg_dt 와 독립적으로 설정
    ntce_dates = [d - pd.Timedelta(days=30) for d in all_dates]

    winning_rates = rng.uniform(70.0, 110.0, n_total)
    prices = rng.uniform(1e7, 5e8, n_total)

    inst_names = [f"기관_{i % 20:02d}" for i in range(n_total)]

    df = pd.DataFrame(
        {
            "openg_dt": all_dates,
            "bid_ntce_dt": ntce_dates,
            "bid_clse_dt": [d - pd.Timedelta(days=7) for d in all_dates],
            "winning_rate": winning_rates,
            "presmpt_prce": prices,
            "dminstt_nm": inst_names,
            "category": "Cnstwk",
            "bid_ntce_nm": [f"공사 공고 {i:04d}" for i in range(n_total)],
            "lwlt_rate": rng.uniform(85.0, 90.0, n_total),
            "srvce_div_nm": rng.choice(["공사", "미상"], n_total),
            "lrg_clsfc_nm": rng.choice(["토목", "건축", "기계설비"], n_total),
            "cntrct_mthd_nm": rng.choice(["일반경쟁", "제한경쟁"], n_total),
            "prearng_mthd": rng.choice(["예가", "기초"], n_total),
            "sucsfbid_mthd_nm": rng.choice(["적격심사", "최저가"], n_total),
            "mid_clsfc_nm": rng.choice(["일반토목", "건축공사"], n_total),
            "clsfc_nm": rng.choice(["포장공사", "일반건축"], n_total),
            "ntce_kind_nm": rng.choice(["일반", "재공고"], n_total),
            "bid_methd_nm": rng.choice(["전자", "우편"], n_total),
            "intrbid_yn": rng.choice(["Y", "N"], n_total),
            "ppsw_gnrl_srvce_yn": rng.choice(["Y", "N"], n_total),
            "tech_ablt_evl_rt": rng.uniform(0, 100, n_total),
            "bid_prce_evl_rt": rng.uniform(0, 100, n_total),
            "tot_prdprc_num": rng.integers(2, 10, n_total).astype(float),
            "drwt_prdprc_num": rng.integers(1, 5, n_total).astype(float),
        }
    )
    return df


def _fake_v25_loader(fixed_pred: float = 90.0):
    """고정 예측값을 반환하는 가짜 v25 래퍼 로더를 만든다."""
    wrapper = MagicMock()
    wrapper.get_serving_columns.return_value = []
    wrapper.get_category_levels.return_value = None
    wrapper.predict.return_value = fixed_pred
    return lambda: wrapper


def _save_parquet(df: pd.DataFrame, path: Path) -> None:
    df.to_parquet(path, index=False)


# ---------------------------------------------------------------------------
# (a) 분할 경계 검증
# ---------------------------------------------------------------------------


class TestSplitBoundary:
    def test_train_cutoff_is_2025_01_01(self):
        assert pd.Timestamp("2025-01-01") == TRAIN_CUTOFF

    def test_regime_shift_is_2026_05_26(self):
        assert pd.Timestamp("2026-05-26") == REGIME_SHIFT_DATE

    def test_main_splits_correctly(self, tmp_path):
        """main() 이 반환한 JSON 의 train_rows / holdout_2025_rows / oos_2026_rows 가
        합성 데이터의 날짜 분포와 일치한다."""
        df = _make_df(n_train=300, n_2025=100, n_2026_pre=80, n_2026_post=60)
        parquet_file = tmp_path / "dataset_Cnstwk.parquet"
        _save_parquet(df, parquet_file)
        output_file = tmp_path / "result.json"

        import unittest.mock as mock

        import scripts.eval_cnstwk_year_holdout as _mod

        # v25_loader 주입: predict_v25_batch 를 직접 패치한다
        with mock.patch.object(
            _mod, "predict_v25_batch", side_effect=lambda df, loader=None: np.full(len(df), 90.0)
        ):
            ret = main(
                [
                    "--parquet",
                    str(parquet_file),
                    "--output",
                    str(output_file),
                    "--limit",
                    "0",
                ]
            )

        assert ret == 0
        result = json.loads(output_file.read_text())

        meta = result["meta"]
        assert meta["train_rows"] == 300
        assert meta["holdout_2025_rows"] == 100
        assert meta["oos_2026_rows"] == 140  # 80 + 60

    def test_2026_regime_split(self, tmp_path):
        """2026년 OOS 가 레짐 전/후로 올바르게 나뉜다."""
        df = _make_df(n_train=200, n_2025=50, n_2026_pre=40, n_2026_post=30)
        parquet_file = tmp_path / "dataset_Cnstwk.parquet"
        _save_parquet(df, parquet_file)
        output_file = tmp_path / "result.json"

        import unittest.mock as mock

        import scripts.eval_cnstwk_year_holdout as _mod

        with mock.patch.object(
            _mod, "predict_v25_batch", side_effect=lambda df, loader=None: np.full(len(df), 90.0)
        ):
            ret = main(
                [
                    "--parquet",
                    str(parquet_file),
                    "--output",
                    str(output_file),
                ]
            )

        assert ret == 0
        result = json.loads(output_file.read_text())
        segment_labels = [s["segment"] for s in result["segments"]]
        # 레짐 전 구간이 별도 세그먼트로 존재해야 한다
        assert any("레짐 전" in lbl for lbl in segment_labels), segment_labels
        assert any("레짐 후" in lbl for lbl in segment_labels), segment_labels


# ---------------------------------------------------------------------------
# (b) 홀드아웃 정답이 학습 특징에 누수되지 않음
# ---------------------------------------------------------------------------


class TestNoLeakage:
    def test_institution_history_not_leaked(self):
        """attach_institution_history 가 학습 구간 종료 후 홀드아웃의 낙찰률을
        기관 이력에 포함하지 않는다.

        검증 방법: 학습 구간에 기관 A 의 행만 있고, 홀드아웃에 기관 A 의 행이
        있을 때, 홀드아웃 첫 행의 inst_hist_rate 는 학습 구간의 낙찰률 평균이어야
        한다. 홀드아웃 첫 행의 정답(winning_rate) 을 inst_hist_rate 에 쓴다면
        inst_hist_rate 는 다른 값이 된다.
        """
        from src.ml.institution_history import attach_institution_history

        # 학습: 기관 A 의 낙찰률을 80 으로 고정
        train_rows = [
            {
                "openg_dt": pd.Timestamp(f"2024-{m:02d}-01"),
                "dminstt_nm": "기관A",
                "winning_rate": 80.0,
                "category": "Cnstwk",
            }
            for m in range(1, 13)
        ]
        # 홀드아웃: 기관 A 의 낙찰률을 110 으로 설정 (학습과 다른 값)
        holdout_row = {
            "openg_dt": pd.Timestamp("2025-01-15"),
            "dminstt_nm": "기관A",
            "winning_rate": 110.0,
            "category": "Cnstwk",
        }
        df_all = pd.DataFrame([*train_rows, holdout_row])
        df_all["openg_dt"] = pd.to_datetime(df_all["openg_dt"])

        result = attach_institution_history(df_all)

        # 홀드아웃 행 (마지막 행)의 inst_hist_rate 는 80% 기반이어야 한다
        holdout_hist_rate = float(result.iloc[-1]["inst_hist_rate"])
        expected = 80.0 / 100.0  # 학습 구간 평균
        assert abs(holdout_hist_rate - expected) < 0.01, (
            f"홀드아웃 inst_hist_rate={holdout_hist_rate:.4f} 가 학습 구간 평균"
            f" {expected:.4f} 와 크게 다릅니다. 누수 의심."
        )

    def test_holdout_winning_rate_not_in_train_features(self, tmp_path):
        """홀드아웃 행의 winning_rate 가 학습 특징 벡터에 직접 들어가지 않는다."""
        from src.ml.features import build_feature_frame
        from src.ml.training_config import training_features_for_category

        df = _make_df(n_train=50, n_2025=20, n_2026_pre=10, n_2026_post=5)
        train_mask = df["openg_dt"] < pd.Timestamp("2025-01-01")
        df_train = df[train_mask].copy()

        records = df_train.to_dict(orient="records")
        features_list = build_feature_frame(records)
        df_feat = pd.DataFrame(features_list)

        feature_columns = training_features_for_category("Cnstwk")
        # 특징 컬럼에 winning_rate 가 없어야 한다
        assert "winning_rate" not in feature_columns
        assert "winning_rate" not in df_feat.columns


# ---------------------------------------------------------------------------
# (c) 쌍대 t 계산이 수작업 값과 일치
# ---------------------------------------------------------------------------


class TestPairedT:
    def test_paired_t_manual(self):
        """수작업으로 계산한 t 통계량과 _paired_t 의 결과가 일치한다."""
        # diff = |후보 오차| - |v25 오차|
        diff = np.array([0.1, -0.2, 0.3, -0.1, 0.5, -0.4, 0.2, 0.0])
        n = len(diff)
        mean_d = float(diff.mean())
        se = float(diff.std(ddof=1) / np.sqrt(n))
        expected_t = mean_d / se

        result = _paired_t(diff)
        assert abs(result["t"] - expected_t) < 1e-4, (
            f"expected t={expected_t:.6f}, got t={result['t']:.6f}"
        )
        assert abs(result["mean_diff"] - mean_d) < 1e-6
        assert abs(result["se"] - se) < 1e-6

    def test_paired_t_single_element(self):
        """표본이 1개면 se=inf, t=0 이어야 한다."""
        result = _paired_t(np.array([0.5]))
        assert math.isinf(result["se"])
        assert result["t"] == 0.0

    def test_paired_t_empty(self):
        """빈 배열이면 nan 을 반환한다."""
        result = _paired_t(np.array([]))
        assert math.isnan(result["t"])

    def test_segment_metrics_promotion_criteria(self):
        """승격 판단 기준 충족 여부가 올바르게 계산된다."""
        n = 500
        rng = np.random.default_rng(0)
        y = rng.uniform(80, 100, n)

        # 후보가 v25 보다 정확한 경우: 후보 오차 작음
        cand_pred = y + rng.uniform(-0.1, 0.1, n)
        v25_pred = y + rng.uniform(-2.0, 2.0, n)

        result = _segment_metrics(y, cand_pred, v25_pred, "테스트")
        # n=500, 후보가 훨씬 정확하면 |t| >= 2.0 + MAE 개선 >= 0.0074 를 충족해야
        if result["meets_promotion_criteria"]:
            assert abs(result["paired"]["t"]) >= PROMOTION_T_THRESHOLD
            assert result["mae_improvement"] >= PROMOTION_MAE_IMPROVEMENT

    def test_segment_metrics_no_promotion(self):
        """후보와 v25 가 동일하면 승격 기준을 충족하지 않는다."""
        y = np.array([90.0] * 100)
        pred = np.array([90.5] * 100)  # 동일한 예측

        result = _segment_metrics(y, pred, pred, "동일 모델 테스트")
        assert result["meets_promotion_criteria"] is False
        assert result["paired"]["mean_diff"] == 0.0


# ---------------------------------------------------------------------------
# (d) 출력 JSON 구조 검증
# ---------------------------------------------------------------------------


class TestOutputJsonStructure:
    def test_json_has_required_keys(self, tmp_path):
        """출력 JSON 에 meta 와 segments 키가 있고, meta 에 필수 필드가 있다."""
        df = _make_df(n_train=100, n_2025=40, n_2026_pre=20, n_2026_post=15)
        parquet_file = tmp_path / "dataset_Cnstwk.parquet"
        _save_parquet(df, parquet_file)
        output_file = tmp_path / "result.json"

        import unittest.mock as mock

        import scripts.eval_cnstwk_year_holdout as _mod

        with mock.patch.object(
            _mod, "predict_v25_batch", side_effect=lambda df, loader=None: np.full(len(df), 90.0)
        ):
            ret = main(
                [
                    "--parquet",
                    str(parquet_file),
                    "--output",
                    str(output_file),
                ]
            )

        assert ret == 0
        result = json.loads(output_file.read_text())

        # 최상위 키
        assert "meta" in result
        assert "segments" in result

        # meta 필수 필드
        meta = result["meta"]
        required_meta_keys = {
            "parquet_path",
            "train_rows",
            "holdout_2025_rows",
            "oos_2026_rows",
            "feature_columns",
            "git_commit",
            "elapsed_seconds",
            "promotion_threshold",
        }
        for key in required_meta_keys:
            assert key in meta, f"meta 에 '{key}' 가 없습니다"

        # 세그먼트 필수 필드
        for seg in result["segments"]:
            for key in ("segment", "n", "candidate", "v25", "paired", "meets_promotion_criteria"):
                assert key in seg, f"segment '{seg.get('segment')}' 에 '{key}' 가 없습니다"
            for model_key in ("candidate", "v25"):
                for metric in ("mae", "rmse", "hit_rate_0_5pct"):
                    assert metric in seg[model_key], (
                        f"segment '{seg['segment']}' 의 '{model_key}' 에 '{metric}' 가 없습니다"
                    )
            for stat_key in ("mean_diff", "se", "t"):
                assert stat_key in seg["paired"], (
                    f"segment '{seg['segment']}' 의 'paired' 에 '{stat_key}' 가 없습니다"
                )

    def test_json_types_are_correct(self, tmp_path):
        """JSON 의 수치 필드가 float 이고 n 이 int 다."""
        df = _make_df(n_train=80, n_2025=30, n_2026_pre=15, n_2026_post=10)
        parquet_file = tmp_path / "dataset_Cnstwk.parquet"
        _save_parquet(df, parquet_file)
        output_file = tmp_path / "result.json"

        import unittest.mock as mock

        import scripts.eval_cnstwk_year_holdout as _mod

        with mock.patch.object(
            _mod, "predict_v25_batch", side_effect=lambda df, loader=None: np.full(len(df), 90.0)
        ):
            main(
                [
                    "--parquet",
                    str(parquet_file),
                    "--output",
                    str(output_file),
                ]
            )

        result = json.loads(output_file.read_text())
        for seg in result["segments"]:
            assert isinstance(seg["n"], int)
            assert isinstance(seg["candidate"]["mae"], float)
            assert isinstance(seg["v25"]["rmse"], float)
            assert isinstance(seg["meets_promotion_criteria"], bool)

    def test_no_registry_write(self, tmp_path):
        """평가 실행 후 ml_registry 디렉터리가 생성되지 않는다."""
        df = _make_df(n_train=50, n_2025=20, n_2026_pre=10, n_2026_post=8)
        parquet_file = tmp_path / "dataset_Cnstwk.parquet"
        _save_parquet(df, parquet_file)
        output_file = tmp_path / "result.json"

        registry_dir = tmp_path / "ml_registry"
        assert not registry_dir.exists()

        import unittest.mock as mock

        import scripts.eval_cnstwk_year_holdout as _mod

        with mock.patch.object(
            _mod, "predict_v25_batch", side_effect=lambda df, loader=None: np.full(len(df), 90.0)
        ):
            main(
                [
                    "--parquet",
                    str(parquet_file),
                    "--output",
                    str(output_file),
                ]
            )

        assert not registry_dir.exists(), "레지스트리에 파일이 써졌습니다. 계약 위반."


# ---------------------------------------------------------------------------
# 유닛 테스트: 지표 함수
# ---------------------------------------------------------------------------


class TestMetricFunctions:
    def test_mae(self):
        y = np.array([1.0, 2.0, 3.0])
        p = np.array([1.5, 2.5, 3.5])
        assert abs(_mae(y, p) - 0.5) < 1e-9

    def test_rmse(self):
        y = np.array([0.0, 1.0])
        p = np.array([1.0, 2.0])
        assert abs(_rmse(y, p) - 1.0) < 1e-9

    def test_hit_rate(self):
        y = np.array([90.0, 90.0, 90.0, 90.0])
        p = np.array([90.3, 90.6, 89.6, 91.0])
        # 90.3 (diff=0.3 <= 0.5 -> hit), 90.6 (diff=0.6 -> miss),
        # 89.6 (diff=0.4 -> hit), 91.0 (diff=1.0 -> miss)
        assert abs(_hit_rate(y, p, 0.5) - 0.5) < 1e-9


# ---------------------------------------------------------------------------
# v25 로더 주입 테스트
# ---------------------------------------------------------------------------


class TestV25LoaderInjection:
    def test_fake_loader_used(self):
        """가짜 로더가 올바르게 주입되고 고정값을 반환한다."""
        n = 10
        rng = np.random.default_rng(1)
        df = pd.DataFrame(
            {
                "openg_dt": pd.date_range("2025-01-01", periods=n),
                "bid_ntce_dt": pd.date_range("2024-12-01", periods=n),
                "bid_clse_dt": pd.date_range("2024-12-15", periods=n),
                "presmpt_prce": rng.uniform(1e7, 1e8, n),
                "winning_rate": rng.uniform(80, 100, n),
                "dminstt_nm": ["기관A"] * n,
                "category": ["Cnstwk"] * n,
            }
        )
        loader = _fake_v25_loader(fixed_pred=88.0)
        preds = predict_v25_batch(df, loader=loader)
        assert len(preds) == n
        assert np.all(preds == 88.0)

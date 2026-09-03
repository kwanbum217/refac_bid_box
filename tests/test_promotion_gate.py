"""
tests/test_promotion_gate.py

운영 쌍대검정 판정 게이트와 원자적 교체 검증.

capsule task_t3_promotion 사양:
- paired_verdict.json 이 없거나 verdict 가 approved 가 아니면 승격 거부
- verdict == "rejected" 는 force 로도 뚫리지 않음
- paired_verdict.json 이 없는 미판정은 force 로 뚫을 수 있음
- 교체 도중 실패 시 서빙 디렉터리가 부재/부분 복사 상태로 남지 않음
"""

import json
from pathlib import Path

import joblib
import pytest
from sklearn.linear_model import LinearRegression

from scripts.promote_model import main as cli_main
from src.ml.promotion import (
    PromotionRejected,
    check_promotion_criteria,
    compute_artifact_checksum,
    promote,
    read_paired_verdict,
)

MODEL_NAME = "test_model"
SERVABLE_FEATURES = ["log_price", "month", "inst_hist_rate"]


def _training_metadata(version: str) -> dict:
    return {
        "model_name": MODEL_NAME,
        "version": version,
        "model_type": "lightgbm",
        "features": SERVABLE_FEATURES,
        "samples_count": 1000,
        "metrics": {"r2": 0.68, "rmse": 2.7, "mape": 1.46},
        "time_sorted_split": True,
        "holdout_is_overfit": False,
        "cv_metrics": {"folds": [{"r2": 0.67}, {"r2": 0.69}]},
    }


def _make_model():
    return LinearRegression().fit([[0.0, 1.0, 0.9], [1.0, 2.0, 0.8]], [1.0, 2.0])


@pytest.fixture
def registry(tmp_path):
    root = tmp_path / "ml_registry"
    version_dir = root / MODEL_NAME / "v_20260801_000000_000"
    version_dir.mkdir(parents=True)
    joblib.dump(_make_model(), version_dir / "model.bin")
    (version_dir / "metadata.json").write_text(
        json.dumps(_training_metadata("v_20260801_000000_000")), encoding="utf-8"
    )
    champion_dir = root / MODEL_NAME / "base"
    champion_dir.mkdir()
    joblib.dump(_make_model(), champion_dir / "model.bin")
    (champion_dir / "metadata.json").write_text(
        json.dumps(_training_metadata("base")), encoding="utf-8"
    )
    return root


@pytest.fixture
def dirs(tmp_path, registry):
    return {
        "registry_dir": registry,
        "serving_dir": tmp_path / "model_files",
        "backup_dir": tmp_path / "model_backups",
    }


def _write_verdict(registry_dir, version, verdict, **extra):
    path = Path(registry_dir) / MODEL_NAME / version / "paired_verdict.json"
    challenger_dir = path.parent
    champion_dir = Path(registry_dir) / MODEL_NAME / "base"
    payload = {
        "verdict": verdict,
        "champion_version": "base",
        "challenger_version": version,
        "champion_checksum": compute_artifact_checksum(champion_dir),
        "challenger_checksum": compute_artifact_checksum(challenger_dir),
        "sample_hash": "sample-sha256",
        "code_commit": "deadbeef",
        "decided_at": "2026-08-07",
        "evidence": extra.get("evidence", "test evidence"),
    }
    payload.update(extra)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


# --------------------------------------------------------------------------- #
# 쌍대검정 판정 게이트
# --------------------------------------------------------------------------- #


def test_missing_verdict_blocks_promotion(dirs):
    """paired_verdict.json 이 없으면 승격 조건에 미판정 사유가 붙습니다."""
    meta = _training_metadata("v_20260801_000000_000")
    reasons = check_promotion_criteria(meta, registry_dir=dirs["registry_dir"])
    assert any("미판정" in r for r in reasons)


def test_missing_verdict_bypassable_with_force(dirs):
    """미판정은 force 로 뚫을 수 있습니다."""
    promote(
        MODEL_NAME,
        "v_20260801_000000_000",
        registry_dir=dirs["registry_dir"],
        serving_dir=dirs["serving_dir"],
        backup_dir=dirs["backup_dir"],
        force=True,
    )
    assert (dirs["serving_dir"] / MODEL_NAME / "model.bin").exists()


def test_rejected_verdict_blocks_promotion(dirs):
    """verdict == rejected 이면 승격이 거부됩니다."""
    _write_verdict(dirs["registry_dir"], "v_20260801_000000_000", "rejected")
    meta = _training_metadata("v_20260801_000000_000")
    reasons = check_promotion_criteria(meta, registry_dir=dirs["registry_dir"])
    assert any("기각" in r for r in reasons)


def test_rejected_verdict_not_bypassable_with_force(dirs):
    """verdict == rejected 는 force 로도 뚫리지 않습니다."""
    _write_verdict(dirs["registry_dir"], "v_20260801_000000_000", "rejected")
    with pytest.raises(PromotionRejected, match="기각"):
        promote(
            MODEL_NAME,
            "v_20260801_000000_000",
            registry_dir=dirs["registry_dir"],
            serving_dir=dirs["serving_dir"],
            backup_dir=dirs["backup_dir"],
            force=True,
        )


def test_approved_verdict_passes(dirs):
    """verdict == approved 이면 쌍대검정 사유가 붙지 않습니다."""
    _write_verdict(dirs["registry_dir"], "v_20260801_000000_000", "approved")
    meta = _training_metadata("v_20260801_000000_000")
    reasons = check_promotion_criteria(meta, registry_dir=dirs["registry_dir"])
    assert not any("쌍대검정" in r for r in reasons)


def test_unknown_verdict_value_blocks(dirs):
    """verdict 가 approved/rejected 외의 값이면 판정 불가로 거부됩니다."""
    _write_verdict(dirs["registry_dir"], "v_20260801_000000_000", "pending")
    meta = _training_metadata("v_20260801_000000_000")
    reasons = check_promotion_criteria(meta, registry_dir=dirs["registry_dir"])
    assert any("판정 불가" in r for r in reasons)


def test_read_paired_verdict_returns_none_when_missing(dirs):
    assert read_paired_verdict(MODEL_NAME, "v_20260801_000000_000", dirs["registry_dir"]) is None


def test_read_paired_verdict_returns_data(dirs):
    _write_verdict(dirs["registry_dir"], "v_20260801_000000_000", "rejected", evidence="t=5.14")
    data = read_paired_verdict(MODEL_NAME, "v_20260801_000000_000", dirs["registry_dir"])
    assert data is not None
    assert data["verdict"] == "rejected"
    assert "t=5.14" in data["evidence"]


# --------------------------------------------------------------------------- #
# 원자적 교체
# --------------------------------------------------------------------------- #


def test_staging_failure_leaves_serving_untouched(dirs):
    """staging 검증 실패 시 기존 서빙 디렉터리가 그대로 남습니다."""
    _write_verdict(dirs["registry_dir"], "v_20260801_000000_000", "approved")

    # 먼저 정상적으로 승격해 서빙 디렉터리를 만듭니다.
    promote(
        MODEL_NAME,
        "v_20260801_000000_000",
        registry_dir=dirs["registry_dir"],
        serving_dir=dirs["serving_dir"],
        backup_dir=dirs["backup_dir"],
    )
    serving = dirs["serving_dir"] / MODEL_NAME
    assert serving.exists()
    original_model = (serving / "model.bin").read_bytes()

    # source 의 model.bin 을 깨뜨려 staging 검증을 실패시킵니다.
    source = dirs["registry_dir"] / MODEL_NAME / "v_20260801_000000_000"
    (source / "model.bin").write_bytes(b"corrupted")

    with pytest.raises(Exception):  # noqa: B017 -- staging 실패 경로는 어떤 예외든 동일하게 검증
        promote(
            MODEL_NAME,
            "v_20260801_000000_000",
            registry_dir=dirs["registry_dir"],
            serving_dir=dirs["serving_dir"],
            backup_dir=dirs["backup_dir"],
        )

    # 서빙 디렉터리가 원본 그대로 남아 있어야 합니다.
    assert serving.exists()
    assert (serving / "model.bin").read_bytes() == original_model
    assert (serving / "metadata.json").exists()

    # staging 임시 디렉터리가 남아있지 않아야 합니다.
    staging_dirs = list(dirs["serving_dir"].glob(".promote_staging_*"))
    assert not staging_dirs


def test_promote_atomic_no_partial_serving(dirs):
    """교체 도중 실패해도 서빙 디렉터리가 부분 복사 상태가 되지 않습니다."""
    _write_verdict(dirs["registry_dir"], "v_20260801_000000_000", "approved")

    serving = dirs["serving_dir"] / MODEL_NAME
    assert not serving.exists()

    # source model.bin 을 깨뜨려 staging 복사는 되지만 검증에서 실패하게 합니다.
    source = dirs["registry_dir"] / MODEL_NAME / "v_20260801_000000_000"
    (source / "model.bin").write_bytes(b"bad")

    with pytest.raises(Exception):  # noqa: B017 -- staging 실패 경로는 어떤 예외든 동일하게 검증
        promote(
            MODEL_NAME,
            "v_20260801_000000_000",
            registry_dir=dirs["registry_dir"],
            serving_dir=dirs["serving_dir"],
            backup_dir=dirs["backup_dir"],
        )

    # 서빙 디렉터리가 아예 만들어지지 않았어야 합니다.
    assert not serving.exists()


# --------------------------------------------------------------------------- #
# CLI status 에서 쌍대 기각 표시
# --------------------------------------------------------------------------- #


def test_status_shows_rejected_verdict(dirs, capsys):
    """status 명령이 기각 버전을 승격 불가로 표시하고 쌍대 기각 사유를 출력합니다."""
    _write_verdict(
        dirs["registry_dir"],
        "v_20260801_000000_000",
        "rejected",
        evidence="t=5.14, MAE 1.4050 -> 1.4188",
    )
    exit_code = cli_main(
        [
            "--registry-dir",
            str(dirs["registry_dir"]),
            "--serving-dir",
            str(dirs["serving_dir"]),
            "--backup-dir",
            str(dirs["backup_dir"]),
            "status",
            "--model",
            MODEL_NAME,
        ]
    )
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "승격 불가" in out
    assert "기각" in out
    assert "t=5.14" in out
    assert "force" in out


def test_latest_version_ignores_baseline_directory(tmp_path):
    """baseline 만 있는 모델 디렉터리에서 latest_version 이 baseline 을 버전으로 반환하지 않고 FileNotFoundError 를 발생시킵니다."""
    from src.ml.promotion import latest_version

    model_dir = tmp_path / "ml_registry" / "only_baseline_model"
    baseline_dir = model_dir / "baseline"
    baseline_dir.mkdir(parents=True)
    (baseline_dir / "feature_distributions_v1.json").write_text("{}", encoding="utf-8")
    (baseline_dir / "metadata.json").write_text("{}", encoding="utf-8")

    with pytest.raises(FileNotFoundError, match="학습 아티팩트가 없습니다"):
        latest_version("only_baseline_model", registry_dir=tmp_path / "ml_registry")

    # v_ 버전이 추가되면 정상 반환
    v1_dir = model_dir / "v_20260901_120000_000"
    v1_dir.mkdir()
    assert (
        latest_version("only_baseline_model", registry_dir=tmp_path / "ml_registry")
        == "v_20260901_120000_000"
    )

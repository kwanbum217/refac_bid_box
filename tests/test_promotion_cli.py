"""
tests/test_promotion_cli.py

승격·롤백 도구 검증.

AGENTS.md 의 비협상 원칙은 "신규 모델은 champion 을 성능으로 압도할 때만
승격, **즉시 롤백 가능**" 입니다. 롤백이 백업 디렉터리를 사람이 옮기는
절차로만 존재하면 그 원칙이 손에 걸려 있는 셈이므로, 왕복이 실제로 되는지를
고정합니다.

승격은 되돌리기 어려운 변경이라 `--apply` 없이는 아무것도 바꾸지 않아야
합니다. 그것도 함께 고정합니다.
"""

import json

import joblib
import pytest
from sklearn.linear_model import LinearRegression

from scripts.promote_model import main
from src.ml.promotion import RollbackUnavailable, promote, rollback

MODEL_NAME = "test_model"
CHAMPION_VERSION = "v_20260731_000000_000"

# features.py 가 만들어 줄 수 있는 특징이어야 승격 검사를 통과합니다.
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
        "cv_folds": [{"r2": 0.67}, {"r2": 0.69}],
    }


@pytest.fixture
def registry(tmp_path):
    """학습 아티팩트와 유효한 증거 판정 두 버전을 만듭니다."""
    root = tmp_path / "ml_registry"
    versions = (CHAMPION_VERSION, "v_20260801_000000_000", "v_20260802_000000_000")
    for version in versions:
        version_dir = root / MODEL_NAME / version
        version_dir.mkdir(parents=True)
        model = LinearRegression().fit([[0.0, 1.0, 0.9], [1.0, 2.0, 0.8]], [1.0, 2.0])
        joblib.dump(model, version_dir / "model.bin")
        (version_dir / "metadata.json").write_text(
            json.dumps(_training_metadata(version)), encoding="utf-8"
        )
    for version in versions[1:]:
        _create_verdict(root, version, CHAMPION_VERSION)
    return root


@pytest.fixture
def dirs(tmp_path, registry):
    return {
        "registry_dir": registry,
        "serving_dir": tmp_path / "model_files",
        "backup_dir": tmp_path / "model_backups",
    }


def _serving_version(dirs) -> str:
    meta = dirs["serving_dir"] / MODEL_NAME / "metadata.json"
    return json.loads(meta.read_text(encoding="utf-8"))["version"]


def _cli_args(dirs, *rest) -> list[str]:
    return [
        "--registry-dir",
        str(dirs["registry_dir"]),
        "--serving-dir",
        str(dirs["serving_dir"]),
        "--backup-dir",
        str(dirs["backup_dir"]),
        *rest,
    ]


def _create_verdict(registry_dir, version, champion_version):
    """운영 경로와 동일한 CLI 생성 경로로 증거를 채웁니다."""
    assert (
        main(
            [
                "--registry-dir",
                str(registry_dir),
                "create-verdict",
                "--model",
                MODEL_NAME,
                "--version",
                version,
                "--champion-version",
                champion_version,
                "--verdict",
                "approved",
                "--sample-hash",
                "sample-sha256",
                "--code-commit",
                "deadbeef",
            ]
        )
        == 0
    )


# --------------------------------------------------------------------------- #
# 예행이 기본
# --------------------------------------------------------------------------- #


def test_promote_without_apply_changes_nothing(dirs):
    """오타 한 번으로 서빙이 바뀌면 안 됩니다."""
    exit_code = main(_cli_args(dirs, "promote", "--model", MODEL_NAME))
    assert exit_code == 0
    assert not (dirs["serving_dir"] / MODEL_NAME).exists()


def test_promote_dry_run_reports_rejection(dirs, capsys):
    """승격 조건 위반은 예행에서 사유와 함께 드러나야 합니다."""
    version_dir = dirs["registry_dir"] / MODEL_NAME / "v_20260802_000000_000"
    meta = json.loads((version_dir / "metadata.json").read_text(encoding="utf-8"))
    meta["time_sorted_split"] = False
    (version_dir / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")

    exit_code = main(_cli_args(dirs, "promote", "--model", MODEL_NAME))
    assert exit_code == 1
    assert "시계열 분할" in capsys.readouterr().out


def test_approved_empty_evidence_is_rejected(dirs, capsys):
    """approved 문자열만 남긴 위조 판정은 승격되지 않습니다."""
    version_dir = dirs["registry_dir"] / MODEL_NAME / "v_20260802_000000_000"
    verdict_path = version_dir / "paired_verdict.json"
    verdict = json.loads(verdict_path.read_text(encoding="utf-8"))
    for field in (
        "champion_checksum",
        "challenger_checksum",
        "sample_hash",
        "code_commit",
        "decided_at",
    ):
        verdict[field] = ""
    verdict_path.write_text(json.dumps(verdict), encoding="utf-8")

    exit_code = main(_cli_args(dirs, "promote", "--model", MODEL_NAME, "--apply"))

    assert exit_code == 1
    assert not (dirs["serving_dir"] / MODEL_NAME).exists()
    assert "증거 필드" in capsys.readouterr().out


def test_status_reports_serving_and_challenger(dirs, capsys):
    promote(
        MODEL_NAME,
        "v_20260801_000000_000",
        registry_dir=dirs["registry_dir"],
        serving_dir=dirs["serving_dir"],
        backup_dir=dirs["backup_dir"],
    )
    main(_cli_args(dirs, "status"))

    out = capsys.readouterr().out
    assert "v_20260801_000000_000" in out
    assert "v_20260802_000000_000" in out
    # 쌍대 비교 없이 승격을 권하면 안 됩니다.
    assert "compare_servc_models_paired.py" in out


# --------------------------------------------------------------------------- #
# 승격과 롤백 왕복
# --------------------------------------------------------------------------- #


def test_promote_then_rollback_restores_previous_version(dirs):
    promote(
        MODEL_NAME,
        "v_20260801_000000_000",
        registry_dir=dirs["registry_dir"],
        serving_dir=dirs["serving_dir"],
        backup_dir=dirs["backup_dir"],
    )
    exit_code = main(_cli_args(dirs, "promote", "--model", MODEL_NAME, "--apply"))
    assert exit_code == 0
    assert _serving_version(dirs) == "v_20260802_000000_000"

    exit_code = main(_cli_args(dirs, "rollback", "--model", MODEL_NAME))
    assert exit_code == 0
    assert _serving_version(dirs) == "v_20260801_000000_000"


def test_rollback_is_reversible(dirs):
    """잘못 되돌렸을 때 한 번 더 되돌릴 수 있어야 합니다."""
    for version in ("v_20260801_000000_000", "v_20260802_000000_000"):
        promote(
            MODEL_NAME,
            version,
            registry_dir=dirs["registry_dir"],
            serving_dir=dirs["serving_dir"],
            backup_dir=dirs["backup_dir"],
        )

    rollback(MODEL_NAME, serving_dir=dirs["serving_dir"], backup_dir=dirs["backup_dir"])
    assert _serving_version(dirs) == "v_20260801_000000_000"

    rollback(MODEL_NAME, serving_dir=dirs["serving_dir"], backup_dir=dirs["backup_dir"])
    assert _serving_version(dirs) == "v_20260802_000000_000"


def test_rollback_without_backup_fails_clearly(dirs):
    with pytest.raises(RollbackUnavailable):
        rollback(MODEL_NAME, serving_dir=dirs["serving_dir"], backup_dir=dirs["backup_dir"])


def test_rollback_cli_reports_missing_backup(dirs, capsys):
    exit_code = main(_cli_args(dirs, "rollback", "--model", MODEL_NAME))
    assert exit_code == 1
    assert "백업본이 없습니다" in capsys.readouterr().out


def test_promotion_keeps_quantile_artifacts(dirs):
    """분위 아티팩트를 빠뜨리면 서빙에서 예측 구간이 조용히 사라집니다."""
    version_dir = dirs["registry_dir"] / MODEL_NAME / "v_20260802_000000_000"
    model = joblib.load(version_dir / "model.bin")
    for quantile in ("q05", "q95"):
        joblib.dump(model, version_dir / f"model_{quantile}.bin")

    main(_cli_args(dirs, "promote", "--model", MODEL_NAME, "--apply"))

    served = dirs["serving_dir"] / MODEL_NAME
    assert (served / "model_q05.bin").exists()
    assert (served / "model_q95.bin").exists()

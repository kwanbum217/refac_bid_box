"""승격 판정과 실제 모델 아티팩트의 증거 결속 검증입니다."""

import json
from pathlib import Path

import joblib
import pytest
from sklearn.linear_model import LinearRegression

from scripts.promote_model import main as cli_main
from src.ml.promotion import (
    PromotionRejected,
    compute_artifact_checksum,
    promote,
)

MODEL_NAME = "evidence_model"
CHALLENGER_VERSION = "v_20260903_000000_000"
CHAMPION_VERSION = "v_20260902_000000_000"
FEATURES = ["log_price", "month", "inst_hist_rate"]


def _metadata(version: str) -> dict:
    return {
        "model_name": MODEL_NAME,
        "version": version,
        "model_type": "lightgbm",
        "features": FEATURES,
        "samples_count": 100,
        "metrics": {"r2": 0.7, "rmse": 2.0, "mape": 1.0},
        "time_sorted_split": True,
        "holdout_is_overfit": False,
        "cv_metrics": {"folds": [{"r2": 0.7}]},
    }


@pytest.fixture
def registry(tmp_path: Path) -> tuple[Path, Path, Path]:
    root = tmp_path / "ml_registry"
    for version in (CHAMPION_VERSION, CHALLENGER_VERSION):
        model_dir = root / MODEL_NAME / version
        model_dir.mkdir(parents=True)
        joblib.dump(
            LinearRegression().fit([[0.0, 1.0, 0.9], [1.0, 2.0, 0.8]], [1.0, 2.0]),
            model_dir / "model.bin",
        )
        (model_dir / "metadata.json").write_text(
            json.dumps(_metadata(version), ensure_ascii=False), encoding="utf-8"
        )
    challenger = root / MODEL_NAME / CHALLENGER_VERSION
    champion = root / MODEL_NAME / CHAMPION_VERSION
    verdict = {
        "verdict": "approved",
        "champion_version": CHAMPION_VERSION,
        "challenger_version": CHALLENGER_VERSION,
        "champion_checksum": compute_artifact_checksum(champion),
        "challenger_checksum": compute_artifact_checksum(challenger),
        "sample_hash": "sample-sha256",
        "code_commit": "deadbeef",
        "decided_at": "2026-09-03T00:00:00+00:00",
        "evidence": "paired test",
    }
    (challenger / "paired_verdict.json").write_text(
        json.dumps(verdict, ensure_ascii=False), encoding="utf-8"
    )
    return root, challenger, champion


def _promotion_args(registry: Path, tmp_path: Path, *extra: str) -> list[str]:
    return [
        "--registry-dir",
        str(registry),
        "--serving-dir",
        str(tmp_path / "model_files"),
        "--backup-dir",
        str(tmp_path / "model_backups"),
        "--audit-log",
        str(tmp_path / "promotion_audit.log"),
        *extra,
    ]


def test_approved_verdict_with_empty_evidence_is_rejected(registry, tmp_path):
    root, challenger, _ = registry
    payload = json.loads((challenger / "paired_verdict.json").read_text())
    for field in (
        "champion_checksum",
        "challenger_checksum",
        "sample_hash",
        "code_commit",
        "decided_at",
    ):
        payload[field] = ""
    (challenger / "paired_verdict.json").write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(PromotionRejected, match="증거 필드"):
        promote(
            MODEL_NAME,
            CHALLENGER_VERSION,
            registry_dir=root,
            serving_dir=tmp_path / "model_files",
            backup_dir=tmp_path / "model_backups",
            force=True,
            audit_log_path=tmp_path / "promotion_audit.log",
        )


def test_challenger_checksum_mismatch_is_rejected(registry, tmp_path):
    root, challenger, _ = registry
    payload = json.loads((challenger / "paired_verdict.json").read_text())
    payload["challenger_checksum"] = "0" * 64
    (challenger / "paired_verdict.json").write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(PromotionRejected, match="challenger 아티팩트 체크섬"):
        promote(
            MODEL_NAME,
            CHALLENGER_VERSION,
            registry_dir=root,
            serving_dir=tmp_path / "model_files",
            backup_dir=tmp_path / "model_backups",
            audit_log_path=tmp_path / "promotion_audit.log",
        )


def test_missing_champion_and_mismatched_champion_are_rejected(registry, tmp_path):
    root, challenger, _ = registry
    payload = json.loads((challenger / "paired_verdict.json").read_text())
    payload["champion_checksum"] = "1" * 64
    (challenger / "paired_verdict.json").write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(PromotionRejected, match="champion 아티팩트 체크섬"):
        promote(
            MODEL_NAME,
            CHALLENGER_VERSION,
            registry_dir=root,
            serving_dir=tmp_path / "model_files",
            backup_dir=tmp_path / "model_backups",
            audit_log_path=tmp_path / "promotion_audit.log",
        )

    payload["champion_version"] = "v_missing"
    (challenger / "paired_verdict.json").write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(PromotionRejected, match="champion 아티팩트 디렉터리"):
        promote(
            MODEL_NAME,
            CHALLENGER_VERSION,
            registry_dir=root,
            serving_dir=tmp_path / "model_files",
            backup_dir=tmp_path / "model_backups",
            audit_log_path=tmp_path / "promotion_audit.log",
        )


def test_rejected_verdict_remains_blocked_with_empty_evidence(registry, tmp_path):
    root, challenger, _ = registry
    payload = json.loads((challenger / "paired_verdict.json").read_text())
    payload.update(
        {
            "verdict": "rejected",
            "champion_checksum": "",
            "challenger_checksum": "",
            "sample_hash": "",
            "code_commit": "",
            "decided_at": "",
        }
    )
    (challenger / "paired_verdict.json").write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(PromotionRejected, match="기각"):
        promote(
            MODEL_NAME,
            CHALLENGER_VERSION,
            registry_dir=root,
            serving_dir=tmp_path / "model_files",
            backup_dir=tmp_path / "model_backups",
            force=True,
            audit_log_path=tmp_path / "promotion_audit.log",
        )


def test_promotion_audit_is_append_only_for_success_and_rejection(registry, tmp_path):
    root, challenger, _ = registry
    audit = tmp_path / "promotion_audit.log"
    promote(
        MODEL_NAME,
        CHALLENGER_VERSION,
        registry_dir=root,
        serving_dir=tmp_path / "model_files",
        backup_dir=tmp_path / "model_backups",
        audit_log_path=audit,
    )
    original_lines = audit.read_text(encoding="utf-8").splitlines()
    assert len(original_lines) == 1
    assert json.loads(original_lines[0])["result"] == "promoted"

    payload = json.loads((challenger / "paired_verdict.json").read_text())
    payload["challenger_checksum"] = "0" * 64
    (challenger / "paired_verdict.json").write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(PromotionRejected):
        promote(
            MODEL_NAME,
            CHALLENGER_VERSION,
            registry_dir=root,
            serving_dir=tmp_path / "model_files",
            backup_dir=tmp_path / "model_backups",
            audit_log_path=audit,
        )
    lines = audit.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[1])["result"] == "rejected"
    assert lines[0] == original_lines[0]


def test_cli_create_verdict_binds_both_artifacts(registry, tmp_path):
    root, challenger, champion = registry
    verdict_path = challenger / "paired_verdict.json"
    verdict_path.unlink()
    exit_code = cli_main(
        _promotion_args(
            root,
            tmp_path,
            "create-verdict",
            "--model",
            MODEL_NAME,
            "--version",
            CHALLENGER_VERSION,
            "--champion-version",
            CHAMPION_VERSION,
            "--verdict",
            "approved",
            "--sample-hash",
            "sample-sha256",
            "--code-commit",
            "deadbeef",
        )
    )
    assert exit_code == 0
    payload = json.loads(verdict_path.read_text(encoding="utf-8"))
    assert payload["challenger_checksum"] == compute_artifact_checksum(challenger)
    assert payload["champion_checksum"] == compute_artifact_checksum(champion)
    assert payload["decided_at"]

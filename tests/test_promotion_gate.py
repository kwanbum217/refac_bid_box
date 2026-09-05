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
import shutil
from pathlib import Path

import joblib
import pytest
from sklearn.linear_model import LinearRegression

from scripts.promote_model import main as cli_main
from src.ml import promotion as promotion_mod
from src.ml.model_registry import LIVE_FILENAME, resolve_serving_tree
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
    tree = resolve_serving_tree(dirs["serving_dir"] / MODEL_NAME)
    assert (tree / "model.bin").exists()


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
    tree = resolve_serving_tree(serving)
    original_model = (tree / "model.bin").read_bytes()

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
    cur_tree = resolve_serving_tree(serving)
    assert (cur_tree / "model.bin").read_bytes() == original_model
    assert (cur_tree / "metadata.json").exists()

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


def test_promote_keeps_serving_path_present_during_swap(dirs, monkeypatch):
    """기존 서빙본을 교체하는 동안 서빙 디렉터리가 한 번도 사라지지 않습니다."""
    _write_verdict(dirs["registry_dir"], "v_20260801_000000_000", "approved")
    promote(
        MODEL_NAME,
        "v_20260801_000000_000",
        registry_dir=dirs["registry_dir"],
        serving_dir=dirs["serving_dir"],
        backup_dir=dirs["backup_dir"],
    )
    serving = dirs["serving_dir"] / MODEL_NAME
    seen: list[bool] = []

    def _watch(fn):
        def wrapped(*args, **kwargs):
            seen.append(serving.exists())
            try:
                return fn(*args, **kwargs)
            finally:
                seen.append(serving.exists())

        return wrapped

    monkeypatch.setattr(promotion_mod, "_replace_path", _watch(promotion_mod._replace_path))
    monkeypatch.setattr(promotion_mod.shutil, "rmtree", _watch(shutil.rmtree))
    monkeypatch.setattr(promotion_mod.shutil, "copytree", _watch(shutil.copytree))

    promote(
        MODEL_NAME,
        "v_20260801_000000_000",
        registry_dir=dirs["registry_dir"],
        serving_dir=dirs["serving_dir"],
        backup_dir=dirs["backup_dir"],
    )

    assert seen
    assert all(seen), "승격 교체 중 서빙 경로가 부재한 순간이 있습니다"
    assert serving.exists()
    tree = resolve_serving_tree(serving)
    assert (tree / "model.bin").exists()
    assert (tree / "metadata.json").exists()


def test_promote_injected_replace_failure_leaves_valid_serving(dirs, monkeypatch):
    """LIVE 교체 중 실패해도 서빙 경로는 직전 유효 세트 트리로 남습니다."""
    _write_verdict(dirs["registry_dir"], "v_20260801_000000_000", "approved")
    promote(
        MODEL_NAME,
        "v_20260801_000000_000",
        registry_dir=dirs["registry_dir"],
        serving_dir=dirs["serving_dir"],
        backup_dir=dirs["backup_dir"],
    )
    serving = dirs["serving_dir"] / MODEL_NAME
    orig_tree = resolve_serving_tree(serving)
    original_model = (orig_tree / "model.bin").read_bytes()
    original_meta = (orig_tree / "metadata.json").read_text(encoding="utf-8")

    real_replace = promotion_mod._replace_path

    def fail_on_live_replace(src, dst):
        dst_path = Path(dst)
        if dst_path.name == LIVE_FILENAME and dst_path.parent == serving:
            raise OSError("injected live replace failure")
        return real_replace(src, dst)

    monkeypatch.setattr(promotion_mod, "_replace_path", fail_on_live_replace)

    # v2 준비 및 승격 시도
    v2 = "v_20260802_000000_000"
    v2_dir = dirs["registry_dir"] / MODEL_NAME / v2
    v2_dir.mkdir(parents=True, exist_ok=True)
    joblib.dump(_make_model(), v2_dir / "model.bin")
    (v2_dir / "metadata.json").write_text(json.dumps(_training_metadata(v2)), encoding="utf-8")
    _write_verdict(dirs["registry_dir"], v2, "approved")

    with pytest.raises(OSError, match="injected live replace failure"):
        promote(
            MODEL_NAME,
            v2,
            registry_dir=dirs["registry_dir"],
            serving_dir=dirs["serving_dir"],
            backup_dir=dirs["backup_dir"],
        )

    assert serving.exists()
    current_tree = resolve_serving_tree(serving)
    assert (current_tree / "model.bin").read_bytes() == original_model
    assert (current_tree / "metadata.json").read_text(encoding="utf-8") == original_meta
    assert (dirs["backup_dir"] / MODEL_NAME / "model.bin").exists()


def test_kill_window_simulation_before_live_publish(dirs, monkeypatch):
    """설계 7.1절 1: 세대 디렉터리 생성 후 LIVE 발행 전 중단(SIGKILL) 시 이전 세트가 보존됩니다."""
    _write_verdict(dirs["registry_dir"], "v_20260801_000000_000", "approved")
    promote(
        MODEL_NAME,
        "v_20260801_000000_000",
        registry_dir=dirs["registry_dir"],
        serving_dir=dirs["serving_dir"],
        backup_dir=dirs["backup_dir"],
    )
    serving = dirs["serving_dir"] / MODEL_NAME
    v1_tree = resolve_serving_tree(serving)
    v1_model_bytes = (v1_tree / "model.bin").read_bytes()
    v1_meta = json.loads((v1_tree / "metadata.json").read_text(encoding="utf-8"))

    # publish_live 직전 프로세스 킬 시뮬레이션
    def simulated_kill(slot, version):
        raise KeyboardInterrupt("Simulated SIGKILL / process termination")

    monkeypatch.setattr(promotion_mod, "publish_live", simulated_kill)

    v2 = "v_20260802_000000_000"
    v2_dir = dirs["registry_dir"] / MODEL_NAME / v2
    v2_dir.mkdir(parents=True, exist_ok=True)
    joblib.dump(_make_model(), v2_dir / "model.bin")
    (v2_dir / "metadata.json").write_text(json.dumps(_training_metadata(v2)), encoding="utf-8")
    _write_verdict(dirs["registry_dir"], v2, "approved")

    with pytest.raises(KeyboardInterrupt, match="Simulated SIGKILL"):
        promote(
            MODEL_NAME,
            v2,
            registry_dir=dirs["registry_dir"],
            serving_dir=dirs["serving_dir"],
            backup_dir=dirs["backup_dir"],
        )

    # 단언: 서빙 해석 결과는 완전히 v1 세트여야 하며, v2 와 섞이지 않습니다.
    resolved = resolve_serving_tree(serving)
    assert resolved == v1_tree
    assert (resolved / "model.bin").read_bytes() == v1_model_bytes
    resolved_meta = json.loads((resolved / "metadata.json").read_text(encoding="utf-8"))
    assert resolved_meta["version"] == v1_meta["version"]


def test_successful_promotion_consistent_set(dirs):
    """설계 7.1절 3: v1 승격 후 v2 승격 성공 시 새 세트 전체가 일치합니다."""
    for version in ("v_20260801_000000_000", "v_20260802_000000_000"):
        v_dir = dirs["registry_dir"] / MODEL_NAME / version
        v_dir.mkdir(parents=True, exist_ok=True)
        joblib.dump(_make_model(), v_dir / "model.bin")
        (v_dir / "metadata.json").write_text(
            json.dumps(_training_metadata(version)), encoding="utf-8"
        )
        _write_verdict(dirs["registry_dir"], version, "approved")
        promote(
            MODEL_NAME,
            version,
            registry_dir=dirs["registry_dir"],
            serving_dir=dirs["serving_dir"],
            backup_dir=dirs["backup_dir"],
        )

    serving = dirs["serving_dir"] / MODEL_NAME
    resolved = resolve_serving_tree(serving)
    assert resolved.name == "v_20260802_000000_000"
    meta = json.loads((resolved / "metadata.json").read_text(encoding="utf-8"))
    assert meta["version"] == "v_20260802_000000_000"
    assert (resolved / "model.bin").exists()


def test_multi_file_bundle_atomicity(dirs, monkeypatch):
    """설계 7.1절 5: 다중 분위 아티팩트 세트도 LIVE 전환 직전 중단 시 일체 섞이지 않습니다."""
    v1 = "v_20260801_000000_000"
    v1_dir = dirs["registry_dir"] / MODEL_NAME / v1
    for q in ("q05", "q95"):
        joblib.dump(_make_model(), v1_dir / f"model_{q}.bin")
    _write_verdict(dirs["registry_dir"], v1, "approved")
    promote(
        MODEL_NAME,
        v1,
        registry_dir=dirs["registry_dir"],
        serving_dir=dirs["serving_dir"],
        backup_dir=dirs["backup_dir"],
    )

    serving = dirs["serving_dir"] / MODEL_NAME
    v1_tree = resolve_serving_tree(serving)
    v1_q05 = (v1_tree / "model_q05.bin").read_bytes()

    # v2 에 다른 q05 준비
    v2 = "v_20260802_000000_000"
    v2_dir = dirs["registry_dir"] / MODEL_NAME / v2
    v2_dir.mkdir(parents=True, exist_ok=True)
    joblib.dump(_make_model(), v2_dir / "model.bin")
    (v2_dir / "metadata.json").write_text(json.dumps(_training_metadata(v2)), encoding="utf-8")
    (v2_dir / "model_q05.bin").write_bytes(b"v2_q05_bytes")
    _write_verdict(dirs["registry_dir"], v2, "approved")

    # publish_live 직전 실패 주입
    monkeypatch.setattr(
        promotion_mod,
        "publish_live",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("kill before live")),
    )

    with pytest.raises(RuntimeError, match="kill before live"):
        promote(
            MODEL_NAME,
            v2,
            registry_dir=dirs["registry_dir"],
            serving_dir=dirs["serving_dir"],
            backup_dir=dirs["backup_dir"],
        )

    # v1 세트 파일들이 온전히 보존되며 v2 의 q05 가 섞이지 않음
    current = resolve_serving_tree(serving)
    assert current == v1_tree
    assert (current / "model_q05.bin").read_bytes() == v1_q05
    meta = json.loads((current / "metadata.json").read_text(encoding="utf-8"))
    assert meta["version"] == v1


def test_legacy_slot_root_fallback(dirs):
    """설계 7.1절 7: LIVE 포인터가 없는 레거시 슬롯 루트는 슬롯 루트 자체로 해석됩니다."""
    legacy_slot = dirs["serving_dir"] / "legacy_model"
    legacy_slot.mkdir(parents=True, exist_ok=True)
    (legacy_slot / "model.bin").write_bytes(b"legacy_weights")
    (legacy_slot / "metadata.json").write_text(
        json.dumps({"version": "legacy_v1", "name": "legacy_model"}), encoding="utf-8"
    )

    resolved = resolve_serving_tree(legacy_slot)
    assert resolved == legacy_slot
    assert (resolved / "model.bin").read_bytes() == b"legacy_weights"
    meta = json.loads((resolved / "metadata.json").read_text(encoding="utf-8"))
    assert meta["version"] == "legacy_v1"


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

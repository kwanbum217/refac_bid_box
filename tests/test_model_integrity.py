"""서빙 모델 무결성 manifest 계약 시험.

src/ml/model_integrity.py 의 manifest 기록·검증과, 래퍼 로드 경로·승격·롤백
경로·생성 스크립트가 그 계약을 실제로 강제하는지 임시 디렉터리 가짜 모델로
확인합니다. 격리 워크트리에는 data/model_files/*/model.bin 이 없으므로
운영 가중치를 쓰지 않습니다.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

import joblib
import numpy as np
import pytest

# model_registry 가 로드 시점에 model_wrappers 에 런타임 종속성을 주입하므로 먼저 임포트
import src.ml.model_registry  # noqa: F401
from scripts.write_model_manifests import main as write_manifests_main
from src.app.core.config import settings
from src.ml.model_integrity import (
    MANIFEST_FILENAME,
    ModelIntegrityError,
    verify_file,
    write_manifest,
)
from src.ml.model_registry import resolve_serving_tree
from src.ml.model_wrappers import JoblibModelWrapper
from src.ml.promotion import promote, rollback

MODEL_NAME = "manifest_model"
PREPROCESS_MARKER = "preprocess_executed.marker"

_PREPROCESS_SCRIPT = (
    "from pathlib import Path\n"
    "\n"
    f"Path(__file__).with_name({PREPROCESS_MARKER!r}).write_text('ran', encoding='utf-8')\n"
    "\n"
    "def preprocess(features_dict):\n"
    "    return features_dict\n"
)


class ManifestDummyModel:
    """joblib 로 직렬화 가능한 최소 모델."""

    def __init__(self, value: float = 88.0) -> None:
        self.value = value

    def predict(self, frame):
        return np.full((len(frame),), self.value, dtype=float)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_model_dir(root: Path, *, preprocess: bool = False) -> Path:
    model_dir = root / "dummy_model"
    model_dir.mkdir(parents=True, exist_ok=True)
    joblib.dump(ManifestDummyModel(), model_dir / "model.bin")
    (model_dir / "metadata.json").write_text(
        json.dumps(
            {
                "name": "dummy_model",
                "version": "v1",
                "model_file": "model.bin",
                "features": [],
            }
        ),
        encoding="utf-8",
    )
    if preprocess:
        (model_dir / "preprocess.py").write_text(_PREPROCESS_SCRIPT, encoding="utf-8")
    return model_dir


def _load_wrapper(model_dir: Path) -> JoblibModelWrapper:
    return JoblibModelWrapper(str(model_dir), {"model_file": "model.bin"})


def test_manifest_match_allows_load_and_preprocess(tmp_path):
    """manifest 와 일치하는 model.bin·preprocess.py 는 로드·실행된다."""
    model_dir = _write_model_dir(tmp_path, preprocess=True)
    payload = write_manifest(model_dir)

    assert set(payload["files"]) == {"model.bin", "metadata.json", "preprocess.py"}
    assert payload["files"]["model.bin"]["sha256"] == _sha256(model_dir / "model.bin")

    wrapper = _load_wrapper(model_dir)

    assert wrapper.model is not None
    assert wrapper.preprocessor is not None
    assert (model_dir / PREPROCESS_MARKER).is_file()
    verify_file(model_dir, "model.bin")


def test_tampered_model_bin_is_rejected(tmp_path):
    """model.bin 1바이트 변조는 로드 전에 거부된다."""
    model_dir = _write_model_dir(tmp_path)
    write_manifest(model_dir)
    data = bytearray((model_dir / "model.bin").read_bytes())
    data[len(data) // 2] ^= 0x01
    (model_dir / "model.bin").write_bytes(bytes(data))

    with pytest.raises(ModelIntegrityError, match="체크섬 불일치"):
        _load_wrapper(model_dir)


def test_tampered_preprocess_is_not_executed(tmp_path):
    """preprocess.py 변조 시 exec 되지 않아 부작용 파일이 생기지 않는다."""
    model_dir = _write_model_dir(tmp_path, preprocess=True)
    write_manifest(model_dir)

    baseline = _load_wrapper(model_dir)
    assert baseline.preprocessor is not None
    marker = model_dir / PREPROCESS_MARKER
    assert marker.is_file()
    marker.unlink()

    (model_dir / "preprocess.py").write_text(
        _PREPROCESS_SCRIPT + "TAMPERED = True\n", encoding="utf-8"
    )

    with pytest.raises(ModelIntegrityError, match="체크섬 불일치"):
        _load_wrapper(model_dir)
    assert not marker.exists(), "변조된 preprocess.py 가 실행되었습니다"


@pytest.mark.parametrize("environment", ["production", "staging"])
def test_missing_manifest_is_refused_in_protected_environments(tmp_path, monkeypatch, environment):
    """manifest 가 없으면 production·staging 은 로드를 거부한다."""
    model_dir = _write_model_dir(tmp_path)
    monkeypatch.setattr(settings, "ENVIRONMENT", environment)

    with pytest.raises(ModelIntegrityError, match="manifest 가 없어"):
        _load_wrapper(model_dir)


def test_missing_manifest_warns_and_loads_in_development(tmp_path, monkeypatch, caplog):
    """manifest 가 없어도 development 는 경고 후 로드한다."""
    model_dir = _write_model_dir(tmp_path)
    monkeypatch.setattr(settings, "ENVIRONMENT", "development")

    with caplog.at_level(logging.WARNING, logger="src.ml.model_integrity"):
        wrapper = _load_wrapper(model_dir)

    assert wrapper.model is not None
    assert any("manifest" in record.getMessage() for record in caplog.records)


def test_corrupt_manifest_refuses_load(tmp_path):
    """읽을 수 없는 manifest 는 로드를 거부한다."""
    model_dir = _write_model_dir(tmp_path)
    (model_dir / MANIFEST_FILENAME).write_text("{not json", encoding="utf-8")

    with pytest.raises(ModelIntegrityError, match="manifest 를 읽을 수 없습니다"):
        _load_wrapper(model_dir)


def test_file_missing_from_manifest_refuses_load(tmp_path):
    """manifest 에 없는 아티팩트는 로드를 거부한다."""
    model_dir = _write_model_dir(tmp_path)
    payload = write_manifest(model_dir)
    del payload["files"]["model.bin"]
    (model_dir / MANIFEST_FILENAME).write_text(
        json.dumps(payload, sort_keys=True), encoding="utf-8"
    )

    with pytest.raises(ModelIntegrityError, match="manifest 에 아티팩트가 없습니다"):
        _load_wrapper(model_dir)


def test_write_manifest_is_reproducible(tmp_path):
    """같은 파일 세트를 두 번 봉인하면 같은 바이트가 나온다."""
    model_dir = _write_model_dir(tmp_path, preprocess=True)
    (model_dir / "notes.txt").write_text("추적 대상 아님", encoding="utf-8")

    first = write_manifest(model_dir)
    first_bytes = (model_dir / MANIFEST_FILENAME).read_bytes()
    second = write_manifest(model_dir)

    assert first == second
    assert (model_dir / MANIFEST_FILENAME).read_bytes() == first_bytes
    assert "notes.txt" not in first["files"]
    assert first["files"]["preprocess.py"]["bytes"] == (model_dir / "preprocess.py").stat().st_size
    assert first["files"]["preprocess.py"]["sha256"] == _sha256(model_dir / "preprocess.py")


def test_promotion_seals_manifest(tmp_path):
    """승격 경로가 서빙 세대에 manifest 를 쓰고, 이후 변조는 거부된다."""
    version = "v_20261011_000000_000"
    registry = tmp_path / "ml_registry"
    source = registry / MODEL_NAME / version
    source.mkdir(parents=True)
    joblib.dump(ManifestDummyModel(), source / "model.bin")
    (source / "metadata.json").write_text(
        json.dumps(
            {
                "model_name": MODEL_NAME,
                "version": version,
                "model_type": "lightgbm",
                "features": [],
            }
        ),
        encoding="utf-8",
    )

    result = promote(
        MODEL_NAME,
        version,
        registry_dir=registry,
        serving_dir=tmp_path / "model_files",
        backup_dir=tmp_path / "model_backups",
        force=True,
        audit_log_path=tmp_path / "promotion_audit.log",
    )

    tree = resolve_serving_tree(Path(result["promoted_to"]))
    manifest = json.loads((tree / MANIFEST_FILENAME).read_text(encoding="utf-8"))
    assert manifest["files"]["model.bin"]["sha256"] == _sha256(tree / "model.bin")
    assert manifest["files"]["metadata.json"]["sha256"] == _sha256(tree / "metadata.json")
    verify_file(tree, "model.bin")

    data = bytearray((tree / "model.bin").read_bytes())
    data[-1] ^= 0x01
    (tree / "model.bin").write_bytes(bytes(data))
    with pytest.raises(ModelIntegrityError, match="체크섬 불일치"):
        verify_file(tree, "model.bin")


def test_rollback_seals_manifest_for_legacy_backup(tmp_path):
    """manifest 가 없던 레거시 백업을 되돌려도 복원 세트에 manifest 가 봉인된다."""
    serving_dir = tmp_path / "model_files"
    (serving_dir / "legacy_model").mkdir(parents=True)
    backup_dir = tmp_path / "model_backups"
    backup = backup_dir / "legacy_model"
    backup.mkdir(parents=True)
    joblib.dump(ManifestDummyModel(), backup / "model.bin")
    (backup / "metadata.json").write_text(
        json.dumps({"name": "legacy_model", "version": "legacy_v1"}), encoding="utf-8"
    )

    rollback("legacy_model", serving_dir=serving_dir, backup_dir=backup_dir)

    tree = resolve_serving_tree(serving_dir / "legacy_model")
    assert (tree / MANIFEST_FILENAME).is_file()
    verify_file(tree, "model.bin")


def test_write_model_manifests_cli_covers_slots_and_generations(tmp_path, capsys):
    """생성 스크립트가 레거시 슬롯과 LIVE 세대 트리에 manifest 를 쓴다."""
    root = tmp_path / "model_files"
    legacy = root / "legacy_model"
    legacy.mkdir(parents=True)
    joblib.dump(ManifestDummyModel(), legacy / "model.bin")
    (legacy / "metadata.json").write_text(
        json.dumps({"name": "legacy_model", "version": "legacy_v1"}), encoding="utf-8"
    )

    generation = root / "generation_model" / "generations" / "v1_20261011_000000_abcdef"
    generation.mkdir(parents=True)
    joblib.dump(ManifestDummyModel(), generation / "model.bin")
    (generation / "metadata.json").write_text(
        json.dumps({"name": "generation_model", "version": "v1"}), encoding="utf-8"
    )
    (root / "generation_model" / "LIVE").write_text("v1_20261011_000000_abcdef\n", encoding="utf-8")

    (root / ".promote_staging_leftover").mkdir()
    (root / "empty_slot").mkdir()

    exit_code = write_manifests_main(["--model-files-dir", str(root)])
    out = capsys.readouterr().out

    assert exit_code == 0
    assert (legacy / MANIFEST_FILENAME).is_file()
    assert (generation / MANIFEST_FILENAME).is_file()
    assert not (root / ".promote_staging_leftover" / MANIFEST_FILENAME).exists()
    assert "건너뜀" in out
    verify_file(generation, "model.bin")
    verify_file(legacy, "model.bin")

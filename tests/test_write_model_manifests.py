"""서빙 모델 manifest 생성 재사용 함수와 두 배치 경로 시험.

`write_manifests_under` 는 배치 직후 manifest 를 다시 쓰는 두 경로
(`import_data_assets.py`, `sync_model_files.py import`)가 공유하는 함수입니다.
반환값과 봉인 결과를 임시 디렉터리 가짜 슬롯(model.bin, metadata.json)으로만
고정합니다. 운영 가중치는 건드리지 않습니다.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import joblib
import numpy as np

import scripts.import_data_assets as import_data_assets
from scripts.write_model_manifests import main as write_manifests_main
from scripts.write_model_manifests import write_manifests_under
from src.ml.model_integrity import MANIFEST_FILENAME, verify_file

WRONG_MANIFEST = json.dumps(
    {
        "schema": "model_artifact_manifest_v1",
        "files": {"model.bin": {"sha256": "0" * 64, "bytes": 1}},
    }
)


class _DummyModel:
    """joblib 로 직렬화 가능한 최소 모델."""

    def __init__(self, value: float = 88.0) -> None:
        self.value = value

    def predict(self, frame):
        return np.full((len(frame),), self.value, dtype=float)


def _write_slot(slot: Path, *, generation: str | None = None) -> Path:
    tree = slot if generation is None else slot / "generations" / generation
    tree.mkdir(parents=True, exist_ok=True)
    joblib.dump(_DummyModel(), tree / "model.bin")
    (tree / "metadata.json").write_text(
        json.dumps({"name": slot.name, "version": "v1"}), encoding="utf-8"
    )
    if generation is not None:
        (slot / "LIVE").write_text(f"{generation}\n", encoding="utf-8")
    return tree


def test_write_manifests_under_seals_legacy_and_generation_slots(tmp_path):
    """레거시 슬롯과 LIVE 세대 트리를 모두 봉인하고 건너뜀을 센다."""
    root = tmp_path / "model_files"
    legacy_tree = _write_slot(root / "legacy_model")
    generation_tree = _write_slot(root / "generation_model", generation="v1_20261011_000000_abcdef")
    (root / ".promote_staging_leftover").mkdir(parents=True)
    (root / "empty_slot").mkdir(parents=True)

    written, total_files, skipped = write_manifests_under(root)

    assert (written, total_files, skipped) == (2, 4, 1)
    assert (legacy_tree / MANIFEST_FILENAME).is_file()
    assert (generation_tree / MANIFEST_FILENAME).is_file()
    assert not (root / ".promote_staging_leftover" / MANIFEST_FILENAME).exists()
    verify_file(legacy_tree, "model.bin")
    verify_file(generation_tree, "model.bin")


def test_write_manifests_under_overwrites_wrong_manifest(tmp_path):
    """이미 있던 틀린 manifest 는 배치된 파일 기준으로 덮인다."""
    root = tmp_path / "model_files"
    tree = _write_slot(root / "stale_model")
    (tree / MANIFEST_FILENAME).write_text(WRONG_MANIFEST, encoding="utf-8")

    write_manifests_under(root)

    manifest = json.loads((tree / MANIFEST_FILENAME).read_text(encoding="utf-8"))
    assert manifest["files"]["model.bin"]["sha256"] != "0" * 64
    verify_file(tree, "model.bin")


def test_write_manifests_under_missing_root_is_noop(tmp_path):
    """없는 루트는 아무것도 쓰지 않고 0 을 돌려준다."""
    assert write_manifests_under(tmp_path / "nope") == (0, 0, 0)


def test_cli_reports_written_and_skipped(tmp_path, capsys):
    """main() 의 출력 문구와 종료 코드가 유지된다."""
    root = tmp_path / "model_files"
    _write_slot(root / "model_a")
    (root / "empty_slot").mkdir(parents=True)

    assert write_manifests_main(["--model-files-dir", str(root)]) == 0
    out = capsys.readouterr().out
    assert "완료: 모델 1개 / 파일 2개, 건너뜀 1개" in out
    assert "[건너뜀]" in out


def test_import_data_assets_reseals_serving_manifest(tmp_path, monkeypatch):
    """원본 이관 경로가 복사 직후 서빙 슬롯 manifest 를 다시 봉인한다."""
    source_root = tmp_path / "bid_box"
    model_src = source_root / "apps" / "predictions" / "model_files" / "demo_model"
    model_src.mkdir(parents=True)
    joblib.dump(_DummyModel(), model_src / "model.bin")
    (model_src / "metadata.json").write_text(
        json.dumps({"name": "demo_model", "version": "v1"}), encoding="utf-8"
    )
    (model_src / MANIFEST_FILENAME).write_text(WRONG_MANIFEST, encoding="utf-8")

    chroma_src = source_root / "chroma_db"
    chroma_src.mkdir()
    connection = sqlite3.connect(chroma_src / "chroma.sqlite3")
    connection.execute("CREATE TABLE collections (name TEXT)")
    connection.execute("CREATE TABLE embeddings (id INTEGER)")
    connection.commit()
    connection.close()

    project_root = tmp_path / "project"
    project_root.mkdir()
    monkeypatch.setattr(import_data_assets, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(sys, "argv", ["import_data_assets.py", "--source", str(source_root)])

    assert import_data_assets.main() == 0

    tree = project_root / "data" / "model_files" / "demo_model"
    manifest = json.loads((tree / MANIFEST_FILENAME).read_text(encoding="utf-8"))
    assert manifest["files"]["model.bin"]["sha256"] != "0" * 64
    verify_file(tree, "model.bin")

"""G1 무결성 보고의 서빙 세대 체크섬 대조 시험.

원본 4종 대조와 별도로, LIVE 포인터가 가리키는 승격 세대의 artifact manifest
sha256 과 실제 파일 해시를 대조하는지 확인합니다. 해시 일치/불일치/manifest
없음 세 경우의 보고 항목과, 이 항목이 G1 판정을 바꾸지 않는지 단언합니다.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts import verify_migration

MODEL = "servc_institution_v1"
GENERATION = "gen-20261101"


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _write_generation(
    root: Path,
    *,
    manifest: bool = True,
    weights: bytes = b"serving-weights",
) -> Path:
    """LIVE 포인터·metadata·가중치·manifest 를 갖춘 가짜 서빙 세대를 만듭니다."""
    slot = root / MODEL
    generation = slot / "generations" / GENERATION
    generation.mkdir(parents=True)
    (generation / "metadata.json").write_text('{"version": "test"}', encoding="utf-8")
    (generation / "model.bin").write_bytes(weights)
    (slot / "LIVE").write_text(GENERATION, encoding="utf-8")
    if manifest:
        (generation / "artifact_manifest.json").write_text(
            json.dumps(
                {
                    "schema": "model_artifact_manifest_v1",
                    "files": {
                        "model.bin": {
                            "sha256": _sha256(weights),
                            "bytes": len(weights),
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
    return generation


def test_matching_generation_reports_pass(tmp_path):
    _write_generation(tmp_path)

    entries = verify_migration.collect_serving_generations(tmp_path, models=(MODEL,))

    assert entries is not None
    assert len(entries) == 1
    entry = entries[0]
    assert entry["model"] == MODEL
    assert entry["generation"] == GENERATION
    assert entry["manifest"] == "present"
    assert entry["files_checked"] == 1
    assert entry["mismatches"] == []
    assert entry["status"] == "PASS"


def test_tampered_generation_reports_mismatch(tmp_path):
    generation = _write_generation(tmp_path)
    (generation / "model.bin").write_bytes(b"tampered-weights")

    entries = verify_migration.collect_serving_generations(tmp_path, models=(MODEL,))

    assert entries is not None
    entry = entries[0]
    assert entry["status"] == "MISMATCH"
    assert entry["manifest"] == "present"
    assert entry["files_checked"] == 1
    assert entry["mismatches"][0]["file"] == "model.bin"
    assert entry["mismatches"][0]["reason"] == "체크섬 불일치"


def test_missing_manifest_reports_warn_not_fail(tmp_path):
    _write_generation(tmp_path, manifest=False)

    entries = verify_migration.collect_serving_generations(tmp_path, models=(MODEL,))

    assert entries is not None
    entry = entries[0]
    assert entry["status"] == "WARN"
    assert entry["manifest"] == "missing"
    assert entry["files_checked"] == 0
    assert "artifact manifest 없음" in entry["detail"]


def test_legacy_slot_without_live_is_not_reported(tmp_path):
    """LIVE 이전 레거시 슬롯은 비교할 세대가 없어 보고 키를 만들지 않습니다."""
    (tmp_path / MODEL).mkdir(parents=True)
    (tmp_path / MODEL / "model.bin").write_bytes(b"legacy")

    assert verify_migration.collect_serving_generations(tmp_path, models=(MODEL,)) is None


def test_report_adds_serving_generations_without_changing_verdict(tmp_path):
    _write_generation(tmp_path)
    entries = verify_migration.collect_serving_generations(tmp_path, models=(MODEL,))
    assert entries is not None

    report = verify_migration.generate_verification_report(
        [("ML 가중치 4종 무결성", True, "체크섬 일치")],
        output_path=tmp_path / "report.json",
        serving_generations=entries,
    )

    assert report["overall_verdict"] == "PASS"
    assert report["passed_count"] == 1
    assert report["total_count"] == 1
    assert report["serving_generations"] == entries
    saved = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert saved["serving_generations"] == entries


def test_warn_entry_does_not_change_verdict(tmp_path):
    _write_generation(tmp_path, manifest=False)
    entries = verify_migration.collect_serving_generations(tmp_path, models=(MODEL,))
    assert entries is not None
    assert entries[0]["status"] == "WARN"

    report = verify_migration.generate_verification_report(
        [("ML 가중치 4종 무결성", True, "체크섬 일치")],
        output_path=tmp_path / "report.json",
        serving_generations=entries,
    )

    assert report["overall_verdict"] == "PASS"


def test_report_omits_key_when_no_generation(tmp_path):
    report = verify_migration.generate_verification_report(
        [("ML 가중치 4종 무결성", True, "체크섬 일치")],
        output_path=tmp_path / "report.json",
        serving_generations=None,
    )

    assert "serving_generations" not in report


def test_main_includes_serving_generation_and_keeps_exit_code(monkeypatch, tmp_path):
    """원본 대조가 통과하면 서빙 세대 대조가 붙어도 종료 코드는 0 입니다."""
    monkeypatch.delenv("MODEL_FILES_DIR", raising=False)
    monkeypatch.delenv("MODEL_BACKUPS_DIR", raising=False)
    weights = b"original-weights"
    _write_generation(tmp_path / "data" / "model_files", weights=weights)
    slot = tmp_path / "data" / "model_files" / MODEL
    (slot / "model.bin").write_bytes(weights)

    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "models": {
                    MODEL: {"model.bin": {"sha256": _sha256(weights)}},
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(verify_migration, "ASSET_ROOT", tmp_path)
    monkeypatch.setattr(verify_migration, "MANIFEST_PATH", manifest)
    monkeypatch.setattr(verify_migration, "EXPECTED_MODELS", (MODEL,))
    report_path = tmp_path / "report.json"
    monkeypatch.setattr(
        "sys.argv",
        [
            "verify_migration.py",
            "--only-steps",
            "weights",
            "--report-path",
            str(report_path),
        ],
    )

    assert verify_migration.main() == 0
    saved = json.loads(report_path.read_text(encoding="utf-8"))
    assert saved["overall_verdict"] == "PASS"
    assert saved["serving_generations"][0]["status"] == "PASS"
    assert saved["serving_generations"][0]["generation"] == GENERATION

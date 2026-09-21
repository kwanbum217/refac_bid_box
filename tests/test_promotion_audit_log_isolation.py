"""승격 감사 로그가 테스트 중 임시 디렉터리에만 기록되는지 고정합니다.

배경: 승격 테스트가 audit_log_path 를 넘기지 않아 src.ml.promotion 의 기본 경로인
data/promotion_audit.log 로 기록이 쌓였습니다. 2026-09-21 확인 결과 그 파일
9,245줄 중 9,244줄이 테스트의 test_model 기록이었고, 실제 승격 기록은 1건뿐입니다.

기본 경로에 쓰는 호출 경로는 두 가지입니다.
  - audit_log_path 없이 src.ml.promotion.promote() 를 부르는 테스트
    (tests/test_promotion_gate.py, tests/test_promotion_cli.py 의 test_model 승격)
  - scripts/promote_model CLI 를 --audit-log 없이 부르는 테스트
    (CLI 가 임포트 시점에 기본 경로를 str 로 굳혀 argparse 기본값으로 씁니다)

tests/conftest.py 의 _isolate_promotion_audit_log autouse fixture 가 두 기본 경로를
모두 tmp_path 아래로 돌립니다. 이 파일이 그 계약을 회귀 테스트로 단언합니다.
운영 코드의 기본 경로와 동작은 바뀌지 않았습니다.
"""

import json
import tempfile
from pathlib import Path
from typing import Any

import joblib
import pytest
from sklearn.linear_model import LinearRegression

from src.ml import promotion as promotion_mod
from src.ml.promotion import (
    PromotionRejected,
    _append_promotion_audit,
    compute_artifact_checksum,
    promote,
)

MODEL_NAME = "test_model"
VERSION = "v_20260801_000000_000"
CHAMPION_VERSION = "base"
FEATURES = ["log_price", "month", "inst_hist_rate"]


def _production_audit_log() -> Path:
    """운영 기본 감사 로그 경로.

    monkeypatch 가 건드리지 않는 PROJECT_ROOT 로 다시 조립합니다. 그래야 격리
    fixture 가 기본 경로를 바꿔도 단언이 운영 경로를 잃지 않습니다.
    """
    return promotion_mod.PROJECT_ROOT / "data" / "promotion_audit.log"


def _repo_data_dir() -> Path:
    return promotion_mod.PROJECT_ROOT / "data"


def _stat_signature(path: Path) -> tuple[int, int] | None:
    """(크기, 수정 시각 ns). 파일이 없으면 None. 감사 로그 기록 여부를 비교합니다."""
    if not path.exists():
        return None
    stat = path.stat()
    return (stat.st_size, stat.st_mtime_ns)


def _training_metadata(version: str) -> dict:
    return {
        "model_name": MODEL_NAME,
        "version": version,
        "model_type": "lightgbm",
        "features": FEATURES,
        "samples_count": 1000,
        "metrics": {"r2": 0.68, "rmse": 2.7, "mape": 1.46},
        "time_sorted_split": True,
        "holdout_is_overfit": False,
        "cv_metrics": {"folds": [{"r2": 0.67}, {"r2": 0.69}]},
    }


def _model() -> LinearRegression:
    return LinearRegression().fit([[0.0, 1.0, 0.9], [1.0, 2.0, 0.8]], [1.0, 2.0])


@pytest.fixture
def registry(tmp_path: Path) -> Path:
    """champion(base) 과 challenger 를 만들고 쌍대검정 approved 판정을 채웁니다."""
    root = tmp_path / "ml_registry"
    for version in (CHAMPION_VERSION, VERSION):
        version_dir = root / MODEL_NAME / version
        version_dir.mkdir(parents=True)
        joblib.dump(_model(), version_dir / "model.bin")
        (version_dir / "metadata.json").write_text(
            json.dumps(_training_metadata(version), ensure_ascii=False), encoding="utf-8"
        )

    challenger = root / MODEL_NAME / VERSION
    champion = root / MODEL_NAME / CHAMPION_VERSION
    verdict: dict[str, Any] = {
        "verdict": "approved",
        "champion_version": CHAMPION_VERSION,
        "challenger_version": VERSION,
        "champion_checksum": compute_artifact_checksum(champion),
        "challenger_checksum": compute_artifact_checksum(challenger),
        "sample_hash": "sample-sha256",
        "code_commit": "deadbeef",
        "decided_at": "2026-08-07",
        "evidence": "test evidence",
    }
    (challenger / "paired_verdict.json").write_text(
        json.dumps(verdict, ensure_ascii=False), encoding="utf-8"
    )
    return root


def test_default_audit_log_path_is_not_in_repo_data():
    """(1) 테스트 중 기본 감사 로그 경로가 저장소의 data/ 아래가 아닙니다."""
    default = Path(promotion_mod.AUDIT_LOG_PATH).resolve()
    assert not default.is_relative_to(_repo_data_dir().resolve())
    assert not default.is_relative_to(promotion_mod.PROJECT_ROOT.resolve())

    temp_root = Path(tempfile.gettempdir()).resolve()
    assert default.is_relative_to(temp_root)


def test_cli_module_level_audit_log_path_is_isolated():
    """scripts/promote_model 이 임포트 시점에 복사한 기본 경로도 저장소 밖이어야 합니다."""
    from scripts import promote_model

    cli_default = Path(promote_model.AUDIT_LOG_PATH).resolve()
    assert cli_default == Path(promotion_mod.AUDIT_LOG_PATH).resolve()
    assert not cli_default.is_relative_to(_repo_data_dir().resolve())


def test_append_promotion_audit_without_path_keeps_production_log_untouched():
    """(2) audit_log_path 없이 _append_promotion_audit 을 불러도 운영 로그 크기·수정 시각이 그대로입니다."""
    production = _production_audit_log()
    before = _stat_signature(production)

    _append_promotion_audit(
        model_name=MODEL_NAME,
        version=VERSION,
        verdict_file_hash="deadbeef",
        artifact_hashes={"challenger": "c", "champion": "b"},
        result="promoted",
        rejection_reasons=[],
    )

    assert _stat_signature(production) == before

    isolated = Path(promotion_mod.AUDIT_LOG_PATH)
    assert isolated.exists()
    entries = [json.loads(line) for line in isolated.read_text(encoding="utf-8").splitlines()]
    assert entries[-1]["model_name"] == MODEL_NAME


def test_promote_without_audit_log_keeps_production_log_untouched(registry, tmp_path):
    """audit_log_path 없이 승격해도 운영 로그는 그대로이고 격리 경로에만 기록됩니다."""
    production = _production_audit_log()
    before = _stat_signature(production)

    promote(
        MODEL_NAME,
        VERSION,
        registry_dir=registry,
        serving_dir=tmp_path / "model_files",
        backup_dir=tmp_path / "model_backups",
    )

    assert _stat_signature(production) == before

    isolated = Path(promotion_mod.AUDIT_LOG_PATH)
    assert isolated.exists()
    entries = [json.loads(line) for line in isolated.read_text(encoding="utf-8").splitlines()]
    assert entries[-1]["result"] == "promoted"


def test_leak_call_path_after_monkeypatch_undo_keeps_production_log_untouched(
    registry, tmp_path, monkeypatch
):
    """(3) 누출 테스트와 같은 호출 경로로 불러도 (2) 가 성립합니다.

    tests/test_promotion_gate.py::test_same_version_repromotion_kill_preserves_serving_set
    이 monkeypatch.undo() 로 공유 monkeypatch 인스턴스를 되돌린 뒤 audit_log_path 없이
    promote() 를 부릅니다. 당시에는 격리 패치까지 함께 풀려 운영 로그로 샜습니다.
    격리 패치가 별도 MonkeyPatch 인스턴스에 살아남는지 같은 순서로 재현해 고정합니다.
    """
    monkeypatch.setenv("PROMOTION_AUDIT_ISOLATION_PROBE", "1")
    monkeypatch.undo()

    production = _production_audit_log()
    before = _stat_signature(production)

    promote(
        MODEL_NAME,
        VERSION,
        registry_dir=registry,
        serving_dir=tmp_path / "model_files",
        backup_dir=tmp_path / "model_backups",
    )

    assert _stat_signature(production) == before
    assert Path(promotion_mod.AUDIT_LOG_PATH).exists()


def test_rejected_promotion_without_audit_log_keeps_production_log_untouched(registry, tmp_path):
    """거부된 승격도 운영 로그가 아니라 격리 경로에만 기록됩니다."""
    (registry / MODEL_NAME / VERSION / "paired_verdict.json").unlink()
    production = _production_audit_log()
    before = _stat_signature(production)

    with pytest.raises(PromotionRejected):
        promote(
            MODEL_NAME,
            VERSION,
            registry_dir=registry,
            serving_dir=tmp_path / "model_files",
            backup_dir=tmp_path / "model_backups",
        )

    assert _stat_signature(production) == before

    isolated = Path(promotion_mod.AUDIT_LOG_PATH)
    assert isolated.exists()
    entries = [json.loads(line) for line in isolated.read_text(encoding="utf-8").splitlines()]
    assert entries[-1]["result"] == "rejected"

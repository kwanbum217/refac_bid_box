"""
src/ml/promotion.py

학습 레지스트리(ml_registry/)의 챌린저를 서빙 경로(data/model_files/)로 승격합니다.

두 경로는 메타데이터 규격이 다릅니다. 학습기는 features/model_type 을 쓰고
ModelRegistry 는 required_features/type 을 읽습니다. 번역 없이 복사하면
required_features 가 비어 모델이 어떤 특징도 요구하지 않는 것처럼 보입니다.

승격은 되돌리기 어려운 변경이므로 자동으로 일어나지 않습니다. 호출부가
명시적으로 부르고, 직전 서빙본을 백업한 뒤 교체합니다.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import joblib

from src.app.core.config import settings
from src.app.core.timeutil import utcnow
from src.ml.features import unservable_features

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
# 경로 정본은 settings 입니다 (src/app/core/config.py).
SERVING_ROOT = Path(settings.MODEL_FILES_DIR)
REGISTRY_ROOT = PROJECT_ROOT / "ml_registry"
# 백업은 서빙 루트 밖에 둡니다. 안에 두면 ModelRegistry 가 디렉터리를 모두
# 모델로 훑으므로 백업본까지 로드해 같은 모델이 두 번 등록됩니다.
BACKUP_ROOT = Path(settings.MODEL_BACKUPS_DIR)

# 서빙 모델 실측 지표를 담는 사이드카.
#
# 원본에서 이식한 4개 모델(v25, quantum_leap_v25_pro, ssh_hist_premium,
# v13_hybrid)의 metadata.json 은 **체크섬 매니페스트에 포함돼 있습니다.**
# 거기에 지표를 써넣으면 G1 무손실 검증이 깨지므로 별도 파일에 둡니다.
METRICS_ROOT = Path(settings.MODEL_METRICS_DIR)

# 승격 필수 조건. 설계서 7장을 코드로 옮긴 것입니다.
# 필수 4(어느 폴드도 R2 > 0.99 아닐 것)는 ssh_hist_premium 타깃 누수 사고의
# 재발 방지 장치입니다. 그 모델은 5폴드 중 3개가 R2 0.9999999999999998 이었습니다.
LEAK_R2_THRESHOLD = 0.99


class PromotionRejected(RuntimeError):
    """승격 조건을 통과하지 못했습니다."""


def latest_version(model_name: str, registry_dir: Path | str = REGISTRY_ROOT) -> str:
    versions = sorted(p.name for p in Path(registry_dir, model_name).iterdir() if p.is_dir())
    if not versions:
        raise FileNotFoundError(f"학습 아티팩트가 없습니다: {model_name}")
    return versions[-1]


def check_promotion_criteria(metadata: dict[str, Any]) -> list[str]:
    """승격을 막아야 하는 사유를 돌려줍니다. 빈 목록이면 통과입니다."""
    reasons: list[str] = []

    if metadata.get("holdout_is_overfit"):
        reasons.append("홀드아웃 분리 실패. 지표가 학습 구간 자기 점수입니다")
    if not metadata.get("time_sorted_split"):
        reasons.append("시계열 분할이 아닙니다. 미래 정보가 학습에 샜을 수 있습니다")

    fold_r2 = [
        float(fold["r2"])
        for fold in (metadata.get("cv_metrics", {}).get("folds") or [])
        if fold.get("r2") is not None
    ]
    leaking = [r2 for r2 in fold_r2 if r2 > LEAK_R2_THRESHOLD]
    if leaking:
        reasons.append(
            f"타깃 누수 의심. R2 가 {LEAK_R2_THRESHOLD} 를 넘는 폴드 {len(leaking)}개: {leaking}"
        )

    features = list(metadata.get("features") or [])
    if not features:
        reasons.append("특징 목록이 비었습니다")
    else:
        missing = unservable_features(features)
        if missing:
            reasons.append(f"추론에서 만들 수 없는 특징: {missing}")

    return reasons


def build_serving_metadata(metadata: dict[str, Any], category_code: str | None) -> dict[str, Any]:
    """학습 메타데이터를 ModelRegistry 가 읽는 규격으로 번역합니다."""
    return {
        "name": metadata["model_name"],
        "version": metadata["version"],
        "type": "joblib",
        "model_file": "model.bin",
        "description": f"{metadata['model_name']} 재학습 승격본",
        "specialization": metadata.get("model_type", ""),
        "specialized_categories": [category_code] if category_code else [],
        "required_features": list(metadata.get("features") or []),
        "category_levels": metadata.get("category_levels") or {},
        "training_rows": metadata.get("samples_count"),
        "interval": metadata.get("interval") or {"available": False},
        "promoted_at": utcnow().isoformat(),
        "source_metrics": metadata.get("metrics") or {},
        # source_metrics 는 앞 80% 로 학습한 모델의 홀드아웃 값이고, 가중치는
        # 전량으로 재적합한 것입니다. 두 학습 범위가 다르다는 표시를 서빙본에도
        # 남겨야 나중에 지표와 모델을 짝지어 읽을 때 오해가 없습니다.
        "refit_on_full": bool(metadata.get("refit_on_full")),
    }


def promote(
    model_name: str,
    version: str | None = None,
    *,
    category_code: str | None = None,
    registry_dir: Path | str = REGISTRY_ROOT,
    serving_dir: Path | str = SERVING_ROOT,
    backup_dir: Path | str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """챌린저를 서빙 경로로 승격합니다.

    force 는 승격 조건 위반을 무시합니다. 되돌리기 어려운 선택이므로 호출부가
    담당자 확인을 거친 경우에만 씁니다.
    """
    registry_dir = Path(registry_dir)
    serving_dir = Path(serving_dir)
    version = version or latest_version(model_name, registry_dir)
    source = registry_dir / model_name / version
    metadata = json.loads((source / "metadata.json").read_text(encoding="utf-8"))

    reasons = check_promotion_criteria(metadata)
    if reasons and not force:
        raise PromotionRejected(f"{model_name}/{version} 승격 거부:\n- " + "\n- ".join(reasons))

    # 모델이 실제로 로드되고 특징 이름이 맞는지 확인합니다. 메타데이터만 믿으면
    # 가중치가 깨져 있어도 승격이 성공한 것처럼 보입니다.
    model = joblib.load(source / "model.bin")
    served_columns = list(getattr(model, "feature_name_", []) or metadata.get("features") or [])
    blocked = unservable_features(served_columns)
    if blocked and not force:
        raise PromotionRejected(f"{model_name}/{version} 가중치가 요구하는 미지원 특징: {blocked}")

    target = serving_dir / model_name
    backup = None
    if target.exists():
        backup_root = Path(backup_dir) if backup_dir else BACKUP_ROOT
        backup_root.mkdir(parents=True, exist_ok=True)
        backup = backup_root / model_name
        if backup.exists():
            shutil.rmtree(backup)
        shutil.move(str(target), str(backup))

    try:
        target.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / "model.bin", target / "model.bin")
        # 분위 아티팩트를 빠뜨리면 서빙에서 구간이 조용히 사라집니다.
        for artifact in sorted(source.glob("model_q*.bin")):
            shutil.copy2(artifact, target / artifact.name)
        serving_metadata = build_serving_metadata(metadata, category_code)
        (target / "metadata.json").write_text(
            json.dumps(serving_metadata, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    except Exception:
        # 교체 도중 실패하면 직전 서빙본을 되돌립니다. 반쯤 쓰인 디렉터리를
        # 남기면 다음 기동에서 모델 로드가 깨집니다.
        if backup is not None:
            if target.exists():
                shutil.rmtree(target)
            shutil.move(str(backup), str(target))
        raise

    return {
        "model_name": model_name,
        "version": version,
        "promoted_to": str(target),
        "backup": str(backup) if backup else None,
        "required_features": serving_metadata["required_features"],
        "category_levels": len(serving_metadata["category_levels"]),
    }


def load_serving_metrics(
    model_name: str,
    *,
    serving_dir: Path | str | None = None,
    metrics_dir: Path | str | None = None,
) -> tuple[str, dict]:
    """서빙 중인 모델의 버전과 지표를 돌려줍니다.

    지표는 두 곳에서 찾습니다.

    1. 서빙 metadata.json 의 `source_metrics` — 승격이 기록합니다
    2. 사이드카 `data/model_metrics/<모델>.json` — 실측이 기록합니다

    사이드카는 **버전이 일치할 때만** 씁니다. 모델이 교체됐는데 옛 측정값을
    물려주면 없는 근거로 승격을 판단하게 됩니다.
    """
    # 기본값을 인자 자리에 두면 정의 시점에 고정되어 테스트가 경로를 갈아끼울
    # 수 없습니다. 호출 시점에 모듈 전역을 다시 읽습니다.
    serving_dir = SERVING_ROOT if serving_dir is None else serving_dir
    metrics_dir = METRICS_ROOT if metrics_dir is None else metrics_dir

    meta_path = Path(serving_dir) / model_name / "metadata.json"
    if not meta_path.exists():
        return "", {}
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return "", {}

    version = str(meta.get("version") or "")
    metrics = meta.get("source_metrics") or meta.get("metrics") or {}
    if metrics:
        return version, dict(metrics)

    sidecar = Path(metrics_dir) / f"{model_name}.json"
    if not sidecar.exists():
        return version, {}
    try:
        measured = json.loads(sidecar.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return version, {}

    if str(measured.get("version") or "") != version:
        return version, {}
    return version, dict(measured.get("metrics") or {})


def save_serving_metrics(
    model_name: str,
    version: str,
    metrics: dict,
    *,
    detail: dict | None = None,
    metrics_dir: Path | str | None = None,
) -> Path:
    """실측 지표를 사이드카에 기록합니다."""
    root = Path(METRICS_ROOT if metrics_dir is None else metrics_dir)
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{model_name}.json"
    payload = {
        "model_name": model_name,
        "version": version,
        "metrics": metrics,
        "measured_at": utcnow().isoformat(),
        **(detail or {}),
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


class RollbackUnavailable(RuntimeError):
    """되돌릴 백업본이 없습니다."""


def rollback(
    model_name: str,
    *,
    serving_dir: Path | str = SERVING_ROOT,
    backup_dir: Path | str | None = None,
) -> dict[str, Any]:
    """직전 서빙본으로 되돌립니다. `promote` 의 짝입니다.

    "즉시 롤백 가능" 은 AGENTS.md 의 비협상 원칙인데, 백업 디렉터리를 사람이
    직접 옮기는 것이 유일한 수단이면 그 원칙이 손 절차에 걸려 있는 셈입니다.

    현재 서빙본은 버리지 않고 백업 자리로 넣습니다. 그래야 잘못 되돌렸을 때
    한 번 더 되돌릴 수 있습니다.
    """
    serving_dir = Path(serving_dir)
    backup_root = Path(backup_dir) if backup_dir else BACKUP_ROOT
    backup = backup_root / model_name
    if not backup.exists():
        raise RollbackUnavailable(
            f"{model_name} 의 백업본이 없습니다: {backup}. 승격 이력이 없거나 이미 되돌렸습니다."
        )

    target = serving_dir / model_name
    restored_version = _metadata_version(backup)
    replaced_version = _metadata_version(target)

    # 교체 순서가 중요합니다. 백업을 먼저 옮기면 현재 서빙본을 둘 자리가 없습니다.
    holding = backup_root / f"{model_name}.rollback_tmp"
    if holding.exists():
        shutil.rmtree(holding)
    if target.exists():
        shutil.move(str(target), str(holding))
    try:
        shutil.move(str(backup), str(target))
    except Exception:
        if holding.exists():
            shutil.move(str(holding), str(target))
        raise
    if holding.exists():
        shutil.move(str(holding), str(backup))

    return {
        "model_name": model_name,
        "restored_version": restored_version,
        "replaced_version": replaced_version,
        "serving_path": str(target),
        "backup": str(backup) if backup.exists() else None,
    }


def _metadata_version(model_dir: Path) -> str:
    meta_path = model_dir / "metadata.json"
    if not meta_path.exists():
        return ""
    try:
        return str(json.loads(meta_path.read_text(encoding="utf-8")).get("version") or "")
    except (json.JSONDecodeError, OSError):
        return ""

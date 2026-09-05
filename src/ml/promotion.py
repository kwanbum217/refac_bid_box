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

import hashlib
import json
import os
import shutil
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import Any

import joblib

from src.app.core.config import settings
from src.app.core.timeutil import utcnow
from src.ml.features import unservable_features
from src.ml.model_registry import (
    GENERATIONS_DIRNAME,
    LIVE_FILENAME,
    resolve_serving_tree,
)

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
# 승격 시도는 append-only 런타임 로그에 남깁니다. .gitignore 의 *.log 대상입니다.
AUDIT_LOG_PATH = PROJECT_ROOT / "data" / "promotion_audit.log"

# 판정 파일에 결속할 아티팩트. 순서와 framing 을 고정해야 판정 생성·검증이
# 동일한 바이트 규칙을 사용하고 파일 경계가 모호해지지 않습니다.
PROMOTION_ARTIFACTS = ("model.bin", "metadata.json")
PROMOTION_EVIDENCE_FIELDS = (
    "champion_checksum",
    "challenger_checksum",
    "sample_hash",
    "code_commit",
    "decided_at",
)

# 승격 필수 조건. 설계서 7장을 코드로 옮긴 것입니다.
# 필수 4(어느 폴드도 R2 > 0.99 아닐 것)는 ssh_hist_premium 타깃 누수 사고의
# 재발 방지 장치입니다. 그 모델은 5폴드 중 3개가 R2 0.9999999999999998 이었습니다.
LEAK_R2_THRESHOLD = 0.99


class PromotionRejected(RuntimeError):
    """승격 조건을 통과하지 못했습니다."""


def compute_artifact_checksum(model_dir: Path | str) -> str:
    """모델 승격 아티팩트의 SHA-256 매니페스트 해시를 계산합니다.

    판정 생성과 승격 검증이 반드시 이 함수를 함께 사용하도록 합니다. 모델
    가중치와 학습 메타데이터가 같은 버전 디렉터리에 있어야만 해시를 만들 수
    있습니다.
    """
    model_dir = Path(model_dir)
    digest = hashlib.sha256()
    for name in PROMOTION_ARTIFACTS:
        path = model_dir / name
        data = path.read_bytes()
        name_bytes = name.encode("utf-8")
        digest.update(len(name_bytes).to_bytes(4, "big"))
        digest.update(name_bytes)
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return digest.hexdigest()


def _safe_artifact_checksum(model_dir: Path | str) -> str:
    try:
        return compute_artifact_checksum(model_dir)
    except (OSError, OverflowError):
        return ""


def _paired_verdict_path(
    model_name: str, version: str, registry_dir: Path | str = REGISTRY_ROOT
) -> Path:
    return Path(registry_dir) / model_name / version / "paired_verdict.json"


def _safe_registry_version(version: str) -> bool:
    value = Path(version)
    return (
        bool(version)
        and not value.is_absolute()
        and len(value.parts) == 1
        and version not in {".", ".."}
    )


def _paired_verdict_checksum(model_name: str, version: str, registry_dir: Path | str) -> str:
    path = _paired_verdict_path(model_name, version, registry_dir)
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""


def _promotion_evidence_reasons(
    model_name: str,
    version: str,
    verdict_data: dict[str, Any],
    registry_dir: Path | str,
) -> tuple[list[str], dict[str, str]]:
    """approved 판정과 양쪽 실제 아티팩트의 결속 상태를 검증합니다."""
    reasons: list[str] = []
    registry_dir = Path(registry_dir)
    challenger_dir = registry_dir / model_name / version
    actual_challenger = _safe_artifact_checksum(challenger_dir)
    champion_version = str(verdict_data.get("champion_version") or "")
    champion_dir = registry_dir / model_name / champion_version
    actual_champion = _safe_artifact_checksum(champion_dir) if champion_version else ""
    actual = {"challenger": actual_challenger, "champion": actual_champion}

    for field in PROMOTION_EVIDENCE_FIELDS:
        if not str(verdict_data.get(field) or "").strip():
            reasons.append(f"승격 증거 필드가 비었습니다: {field}")

    if str(verdict_data.get("challenger_version") or "") != version:
        reasons.append("판정 파일의 challenger_version 이 승격 대상 버전과 다릅니다")
    if not champion_version:
        reasons.append("판정 파일의 champion_version 이 비었습니다")
    elif not champion_dir.is_dir():
        reasons.append(f"champion 아티팩트 디렉터리가 없습니다: {champion_dir}")

    if not actual_challenger:
        reasons.append("challenger 아티팩트(model.bin, metadata.json)를 읽을 수 없습니다")
    elif verdict_data.get("challenger_checksum") != actual_challenger:
        reasons.append("challenger 아티팩트 체크섬이 판정 파일과 다릅니다")

    if not actual_champion:
        reasons.append("champion 아티팩트(model.bin, metadata.json)를 읽을 수 없습니다")
    elif verdict_data.get("champion_checksum") != actual_champion:
        reasons.append("champion 아티팩트 체크섬이 판정 파일과 다릅니다")
    return reasons, actual


def check_promotion_evidence(
    metadata: dict[str, Any],
    *,
    registry_dir: Path | str = REGISTRY_ROOT,
) -> list[str]:
    """approved 판정의 증거 결속 사유만 돌려줍니다.

    구조적 게이트의 `force` 처리와 분리해 호출부가 증거 실패를 우회하지
    않도록 하는 공개 검사 함수입니다.
    """
    model_name = str(metadata.get("model_name") or "")
    version = str(metadata.get("version") or "")
    if not model_name or not version:
        return []
    verdict_data = read_paired_verdict(model_name, version, registry_dir)
    if verdict_data is None or verdict_data.get("verdict") != "approved":
        return []
    reasons, _ = _promotion_evidence_reasons(model_name, version, verdict_data, registry_dir)
    return reasons


def _append_promotion_audit(
    *,
    model_name: str,
    version: str,
    verdict_file_hash: str,
    artifact_hashes: dict[str, str],
    result: str,
    rejection_reasons: list[str],
    audit_log_path: Path | str | None = None,
) -> None:
    """승격 결과를 기존 로그를 보존하는 JSON Lines 형식으로 기록합니다."""
    path = Path(audit_log_path) if audit_log_path is not None else AUDIT_LOG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": utcnow().isoformat(),
        "model_name": model_name,
        "version": version,
        "verdict_file_hash": verdict_file_hash,
        "artifact_hashes": artifact_hashes,
        "result": result,
        "rejection_reasons": rejection_reasons,
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")


def read_paired_verdict(
    model_name: str,
    version: str,
    registry_dir: Path | str = REGISTRY_ROOT,
) -> dict[str, Any] | None:
    """쌍대검정 판정 파일을 읽습니다. 없으면 None 입니다."""
    path = _paired_verdict_path(model_name, version, registry_dir)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def latest_version(model_name: str, registry_dir: Path | str = REGISTRY_ROOT) -> str:
    model_path = Path(registry_dir, model_name)
    if not model_path.exists():
        raise FileNotFoundError(f"학습 아티팩트가 없습니다: {model_name}")
    versions = sorted(
        p.name for p in model_path.iterdir() if p.is_dir() and p.name.startswith("v_")
    )
    if not versions:
        raise FileNotFoundError(f"학습 아티팩트가 없습니다: {model_name}")
    return versions[-1]


def check_promotion_criteria(
    metadata: dict[str, Any],
    *,
    registry_dir: Path | str = REGISTRY_ROOT,
) -> list[str]:
    """승격을 막아야 하는 사유를 돌려줍니다. 빈 목록이면 통과입니다."""
    reasons: list[str] = []

    model_name = metadata.get("model_name", "")
    version = metadata.get("version", "")
    if model_name and version:
        verdict_data = read_paired_verdict(model_name, version, registry_dir)
        if verdict_data is None:
            reasons.append("운영 쌍대검정 미판정. paired_verdict.json 이 없습니다")
        elif verdict_data.get("verdict") == "rejected":
            evidence = verdict_data.get("evidence", "")
            reasons.append(f"운영 쌍대검정 기각: {evidence}")
        elif verdict_data.get("verdict") != "approved":
            reasons.append(f"운영 쌍대검정 판정 불가. verdict={verdict_data.get('verdict')!r}")
        else:
            reasons.extend(check_promotion_evidence(metadata, registry_dir=registry_dir))

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


def _is_paired_rejected(metadata: dict[str, Any], registry_dir: Path) -> tuple[bool, str]:
    """쌍대검정 기각 여부를 확인합니다.

    (거부 여부, 증거 요약) 튜플을 돌려줍니다. 기각이 아니면 (False, "") 입니다.
    """
    model_name = metadata.get("model_name", "")
    version = metadata.get("version", "")
    if not model_name or not version:
        return False, ""
    verdict_data = read_paired_verdict(model_name, version, registry_dir)
    if verdict_data is not None and verdict_data.get("verdict") == "rejected":
        return True, verdict_data.get("evidence", "")
    return False, ""


def promote(
    model_name: str,
    version: str | None = None,
    *,
    category_code: str | None = None,
    registry_dir: Path | str = REGISTRY_ROOT,
    serving_dir: Path | str = SERVING_ROOT,
    backup_dir: Path | str | None = None,
    force: bool = False,
    audit_log_path: Path | str | None = None,
) -> dict[str, Any]:
    """승격을 시도하고 성공·거부 결과를 append-only 감사 로그에 남깁니다."""
    registry_dir = Path(registry_dir)
    resolved_version = version
    if not resolved_version:
        try:
            resolved_version = latest_version(model_name, registry_dir)
        except Exception as exc:
            _append_promotion_audit(
                model_name=model_name,
                version="",
                verdict_file_hash="",
                artifact_hashes={"challenger": "", "champion": ""},
                result="rejected",
                rejection_reasons=[str(exc)],
                audit_log_path=audit_log_path,
            )
            raise

    source = registry_dir / model_name / resolved_version
    verdict_data = read_paired_verdict(model_name, resolved_version, registry_dir)
    champion_version = str((verdict_data or {}).get("champion_version") or "")
    artifact_hashes = {
        "challenger": _safe_artifact_checksum(source),
        "champion": _safe_artifact_checksum(registry_dir / model_name / champion_version)
        if champion_version
        else "",
    }
    verdict_file_hash = _paired_verdict_checksum(model_name, resolved_version, registry_dir)

    try:
        if not _safe_registry_version(resolved_version):
            raise PromotionRejected("승격 버전 경로가 안전하지 않습니다")
        result = _promote_unlogged(
            model_name,
            resolved_version,
            category_code=category_code,
            registry_dir=registry_dir,
            serving_dir=serving_dir,
            backup_dir=backup_dir,
            force=force,
        )
    except Exception as exc:
        _append_promotion_audit(
            model_name=model_name,
            version=resolved_version,
            verdict_file_hash=verdict_file_hash,
            artifact_hashes=artifact_hashes,
            result="rejected",
            rejection_reasons=[str(exc)],
            audit_log_path=audit_log_path,
        )
        raise

    _append_promotion_audit(
        model_name=model_name,
        version=resolved_version,
        verdict_file_hash=verdict_file_hash,
        artifact_hashes=artifact_hashes,
        result="promoted",
        rejection_reasons=[],
        audit_log_path=audit_log_path,
    )
    return result


def _promote_unlogged(
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

    force 는 구조적 승격 조건 위반을 무시합니다. 그러나 운영 쌍대검정에서
    기각(rejected)된 버전은 force 로도 승격할 수 없습니다.
    """
    registry_dir = Path(registry_dir)
    serving_dir = Path(serving_dir)
    version = version or latest_version(model_name, registry_dir)
    source = registry_dir / model_name / version
    metadata = json.loads((source / "metadata.json").read_text(encoding="utf-8"))

    if metadata.get("model_name") != model_name or metadata.get("version") != version:
        raise PromotionRejected("메타데이터의 모델명 또는 버전이 승격 대상과 다릅니다")

    # 쌍대검정 기각은 force 로도 뚫리지 않습니다.
    rejected, evidence = _is_paired_rejected(metadata, registry_dir)
    if rejected:
        raise PromotionRejected(
            f"{model_name}/{version} 승격 불가 (운영 쌍대검정 기각): {evidence}"
        )

    evidence_reasons = check_promotion_evidence(metadata, registry_dir=registry_dir)
    if evidence_reasons:
        raise PromotionRejected(
            f"{model_name}/{version} 승격 거부:\n- " + "\n- ".join(evidence_reasons)
        )

    reasons = check_promotion_criteria(metadata, registry_dir=registry_dir)
    if reasons and not force:
        raise PromotionRejected(f"{model_name}/{version} 승격 거부:\n- " + "\n- ".join(reasons))

    # 모델이 실제로 로드되고 특징 이름이 맞는지 확인합니다. 메타데이터만 믿으면
    # 가중치가 깨져 있어도 승격이 성공한 것처럼 보입니다.
    model = joblib.load(source / "model.bin")
    served_columns = list(getattr(model, "feature_name_", []) or metadata.get("features") or [])
    blocked = unservable_features(served_columns)
    if blocked and not force:
        raise PromotionRejected(f"{model_name}/{version} 가중치가 요구하는 미지원 특징: {blocked}")

    # 원자적 교체: staging 에서 검증까지 마친 뒤 서빙 디렉터리를 바꿉니다.
    # staging 실패 시 서빙 디렉터리는 손대지지 않은 채로 남습니다.
    target = serving_dir / model_name
    serving_dir.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(dir=str(serving_dir), prefix=".promote_staging_"))

    try:
        shutil.copy2(source / "model.bin", staging / "model.bin")
        for artifact in sorted(source.glob("model_q*.bin")):
            shutil.copy2(artifact, staging / artifact.name)
        serving_metadata = build_serving_metadata(metadata, category_code)
        (staging / "metadata.json").write_text(
            json.dumps(serving_metadata, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        # staging 에서 모델 무결성을 한 번 더 확인합니다.
        staging_model = joblib.load(staging / "model.bin")
        staging_columns = list(
            getattr(staging_model, "feature_name_", []) or metadata.get("features") or []
        )
        staging_blocked = unservable_features(staging_columns)
        if staging_blocked and not force:
            raise PromotionRejected(
                f"{model_name}/{version} staging 가중치가 요구하는 미지원 특징: {staging_blocked}"
            )
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    # 검증 완료. 서빙 슬롯 디렉터리는 유지한 채 불변 세대 디렉터리와 LIVE 포인터로 원자 공개합니다.
    # 1. 현재 해석된 트리를 백업으로 스냅샷 (기존 원본 바이트 보존 계약)
    # 2. staging 디렉터리를 slot/generations/<version> 으로 원자적 rename
    # 3. LIVE 포인터를 version 으로 원자적 교체
    # 4. 직전 세대와 현재 세대만 남기고 오래된 세대 정리
    backup = None
    dest_generation = None
    try:
        target.mkdir(parents=True, exist_ok=True)
        current_tree = resolve_serving_tree(target)
        if (current_tree / "metadata.json").is_file() or (current_tree / "model.bin").is_file():
            backup_root = Path(backup_dir) if backup_dir else BACKUP_ROOT
            backup_root.mkdir(parents=True, exist_ok=True)
            backup = backup_root / model_name
            _snapshot_directory(current_tree, backup)

        generations_dir = target / GENERATIONS_DIRNAME
        generations_dir.mkdir(parents=True, exist_ok=True)
        dest_generation = generations_dir / version
        if dest_generation.exists():
            shutil.rmtree(dest_generation, ignore_errors=True)
        _replace_path(staging, dest_generation)

        publish_live(target, version)

        keep_versions = {version}
        if backup is not None and backup.exists():
            backup_ver = _metadata_version(backup)
            if backup_ver and _safe_registry_version(backup_ver):
                keep_versions.add(backup_ver)
        _prune_generations(target, keep_versions)
    except Exception:
        if dest_generation is not None and dest_generation.exists():
            live_path = target / LIVE_FILENAME
            current_live = ""
            if live_path.is_file():
                with suppress(OSError):
                    current_live = live_path.read_text(encoding="utf-8").strip()
            if current_live != version:
                shutil.rmtree(dest_generation, ignore_errors=True)
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
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

    slot = Path(serving_dir) / model_name
    serving_tree = resolve_serving_tree(slot)
    meta_path = serving_tree / "metadata.json"
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


def _replace_path(src: Path | str, dst: Path | str) -> None:
    """같은 볼륨에서 경로를 원자적으로 교체합니다.

    파일에 대해 POSIX rename(2) 과 Windows ReplaceFile 과 같이 목적지가
    이미 있어도 한 연산으로 바뀝니다. 디렉터리 전체를 비어 있지 않은
    디렉터리 위에 올리는 용도로는 쓰지 않습니다. 그 연산은 POSIX 에서도
    Windows 에서도 실패합니다.
    """
    os.replace(src, dst)


def _tree_files(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*") if path.is_file())


def _snapshot_directory(source: Path, dest: Path) -> None:
    """source 트리를 dest 로 복사합니다. source 자체는 지우지 않습니다."""
    tmp = dest.with_name(f"{dest.name}.snapshot_tmp")
    if tmp.exists():
        shutil.rmtree(tmp)
    shutil.copytree(source, tmp)
    if dest.exists():
        shutil.rmtree(dest)
    _replace_path(tmp, dest)


def publish_live(slot: Path, version: str) -> None:
    """세대 디렉터리를 LIVE 파일의 원자적 os.replace 로 공개합니다."""
    if not _safe_registry_version(version):
        raise ValueError(f"안전하지 않은 세대 이름입니다: {version}")
    gen_dir = slot / GENERATIONS_DIRNAME / version
    if not (gen_dir / "metadata.json").is_file():
        raise FileNotFoundError(f"유효한 세대 트리가 아닙니다: {gen_dir}")
    tmp_live = slot / f".LIVE_{os.getpid()}_{id(version)}.tmp"
    tmp_live.write_text(f"{version}\n", encoding="utf-8")
    _replace_path(tmp_live, slot / LIVE_FILENAME)


def _prune_generations(slot: Path, keep_versions: set[str]) -> None:
    """직전 세대와 현재 세대만 남기고 나머지 오래된 세대 디렉터리를 정리합니다."""
    generations_dir = slot / GENERATIONS_DIRNAME
    if not generations_dir.is_dir():
        return
    for child in generations_dir.iterdir():
        if child.is_dir() and child.name not in keep_versions and not child.name.startswith("."):
            shutil.rmtree(child, ignore_errors=True)


class RollbackUnavailable(RuntimeError):
    """되돌릴 백업본이 없습니다."""


def rollback(
    model_name: str,
    *,
    serving_dir: Path | str = SERVING_ROOT,
    backup_dir: Path | str | None = None,
) -> dict[str, Any]:
    """직전 서빙본으로 되돌립니다. `promote` 의 짝입니다.

    설계 5.4절: 파일 단위 재설치를 제거하고 불변 세대 디렉터리와 LIVE 포인터 교체로 완결합니다.
    1. 백업 스냅샷이 있으면 그것을 새 세대 디렉터리로 올리고 LIVE 를 그 이름으로 돌리거나,
    2. 직전 세대가 generations/ 에 남아 있으면 LIVE 만 직전 이름으로 교체합니다.
    현재 서빙본은 holding 에 보관했다가 백업으로 이동하여 왕복 롤백 계약을 유지합니다.
    """
    serving_dir = Path(serving_dir)
    backup_root = Path(backup_dir) if backup_dir else BACKUP_ROOT
    backup = backup_root / model_name
    if not backup.exists():
        raise RollbackUnavailable(
            f"{model_name} 의 백업본이 없습니다: {backup}. 승격 이력이 없거나 이미 되돌렸습니다."
        )

    target = serving_dir / model_name
    current_tree = resolve_serving_tree(target)
    restored_version = _metadata_version(backup)
    replaced_version = _metadata_version(current_tree)
    if not restored_version or not _safe_registry_version(restored_version):
        raise RollbackUnavailable(
            f"{model_name} 의 백업본({backup})에 안전한 버전 정보가 없습니다: {restored_version}"
        )

    holding = backup_root / f"{model_name}.rollback_tmp"
    if holding.exists():
        shutil.rmtree(holding)
    if current_tree.exists():
        _snapshot_directory(current_tree, holding)

    generations_dir = target / GENERATIONS_DIRNAME
    generations_dir.mkdir(parents=True, exist_ok=True)
    restored_generation = generations_dir / restored_version

    staging_created = False
    restore_staging = target / f".rollback_staging_{model_name}_{os.getpid()}"
    try:
        if not (restored_generation / "metadata.json").is_file():
            if restore_staging.exists():
                shutil.rmtree(restore_staging)
            shutil.copytree(backup, restore_staging)
            staging_created = True
            if restored_generation.exists():
                shutil.rmtree(restored_generation)
            _replace_path(restore_staging, restored_generation)

        publish_live(target, restored_version)
    except Exception:
        if staging_created and restore_staging.exists():
            shutil.rmtree(restore_staging, ignore_errors=True)
        if holding.exists():
            shutil.rmtree(holding, ignore_errors=True)
        raise

    if backup.exists():
        shutil.rmtree(backup)
    if holding.exists():
        _replace_path(holding, backup)

    return {
        "model_name": model_name,
        "restored_version": restored_version,
        "replaced_version": replaced_version,
        "serving_path": str(target),
        "backup": str(backup) if backup.exists() else None,
    }


def _metadata_version(model_dir: Path) -> str:
    serving_tree = resolve_serving_tree(model_dir)
    meta_path = serving_tree / "metadata.json"
    if not meta_path.exists():
        return ""
    try:
        return str(json.loads(meta_path.read_text(encoding="utf-8")).get("version") or "")
    except (json.JSONDecodeError, OSError):
        return ""

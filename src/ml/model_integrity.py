"""서빙 모델 아티팩트의 sha256 manifest 기록·검증.

서빙 디렉터리(`data/model_files/<모델>/`)의 로드 대상 파일은 Git 추적 대상이
아닙니다(`.gitignore` 의 `*.bin`, `*.joblib`). 저장소만 클론한 장비에는
메타데이터만 오고 가중치는 배포·승격 경로로 들어옵니다. 그 과정에서 파일이
잘리거나 바뀌어도 지금까지는 로드 시점에 알아챌 방법이 없었습니다.

이 모듈이 그 기준선을 만듭니다. 승격과 생성 스크립트가
`artifact_manifest.json` 에 로드 대상 파일의 sha256 을 봉인하고, 모델 래퍼가
파일을 열기 전에 `verify_file` 로 대조합니다. 래퍼 로드 1회당 파일당 1회만
해시를 계산하므로 요청 경로에는 추가 비용이 없습니다.

manifest 가 없을 때의 정책은 환경을 따릅니다. production·staging 은 로드를
거부하고, development 는 경고 후 진행합니다(가중치를 아직 배포하지 않은
개발 볼륨 호환). 판정은 기존 `settings.ENVIRONMENT` 하나만 읽습니다.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

from src.app.core.config import settings

logger = logging.getLogger(__name__)

MANIFEST_FILENAME = "artifact_manifest.json"
MANIFEST_SCHEMA = "model_artifact_manifest_v1"

# manifest 에 봉인할 로드 대상입니다. 래퍼가 실제로 여는 파일 형식과
# 일치해야 합니다. model.bin·분위기 모델·v25 보조 번들(*.bin),
# v25 lgbm 보조 번들(*.joblib), 커스텀 전처리, 서빙 메타데이터입니다.
MANIFEST_TRACKED_GLOBS = ("*.bin", "*.joblib")
MANIFEST_TRACKED_FILES = ("preprocess.py", "metadata.json")

# manifest 부재를 허용하지 않는 환경입니다. 하나로 묶어 두어 staging 만
# 완화되는 일이 없게 합니다.
MANIFEST_REQUIRED_ENVIRONMENTS = frozenset({"production", "staging"})

_HASH_CHUNK_SIZE = 1024 * 1024


class ModelIntegrityError(RuntimeError):
    """서빙 아티팩트가 manifest 와 일치하지 않습니다."""


def sha256_file(path: Path | str) -> str:
    """파일의 SHA-256 을 청크 단위로 계산합니다."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(_HASH_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def iter_manifest_targets(model_dir: Path | str) -> list[Path]:
    """manifest 에 기록할 로드 대상 파일을 경로순으로 돌려줍니다."""
    directory = Path(model_dir)
    targets = {path for pattern in MANIFEST_TRACKED_GLOBS for path in directory.glob(pattern)}
    for name in MANIFEST_TRACKED_FILES:
        path = directory / name
        if path.is_file():
            targets.add(path)
    return sorted(targets)


def write_manifest(model_dir: Path | str) -> dict[str, Any]:
    """디렉터리의 로드 대상 파일을 sha256 manifest 로 봉인합니다.

    타임스탬프를 담지 않습니다. 같은 파일 세트를 두 번 봉인하면 같은 바이트가
    나와야 승격·생성 스크립트의 결과를 재현·대조할 수 있습니다.
    """
    directory = Path(model_dir)
    if not directory.is_dir():
        raise FileNotFoundError(f"모델 디렉터리를 찾을 수 없습니다: {directory}")

    files = {
        path.name: {"sha256": sha256_file(path), "bytes": path.stat().st_size}
        for path in iter_manifest_targets(directory)
    }
    payload = {"schema": MANIFEST_SCHEMA, "files": files}
    manifest_path = directory / MANIFEST_FILENAME
    manifest_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return payload


def load_manifest(model_dir: Path | str) -> dict[str, Any] | None:
    """manifest 를 읽습니다. 없으면 None, 읽을 수 없으면 예외입니다."""
    manifest_path = Path(model_dir) / MANIFEST_FILENAME
    if not manifest_path.is_file():
        return None
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ModelIntegrityError(f"manifest 를 읽을 수 없습니다: {manifest_path}: {exc}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("files"), dict):
        raise ModelIntegrityError(f"manifest 형식이 올바르지 않습니다: {manifest_path}")
    return payload


def verify_file(model_dir: Path | str, filename: str) -> None:
    """파일이 manifest 와 일치하는지 확인하고, 아니면 로드를 거부합니다.

    manifest 가 없으면 production·staging 은 거부하고 development 는 경고 후
    진행합니다. manifest 가 있는데 파일이 없거나 해시가 다르면 환경과 무관하게
    거부합니다(변조는 개발 볼륨에서도 조용히 넘기지 않습니다).
    """
    directory = Path(model_dir)
    manifest = load_manifest(directory)
    if manifest is None:
        if settings.ENVIRONMENT in MANIFEST_REQUIRED_ENVIRONMENTS:
            raise ModelIntegrityError(
                f"manifest 가 없어 로드를 거부합니다({settings.ENVIRONMENT}): {directory}"
            )
        logger.warning("manifest 가 없어 무결성 검증 없이 로드합니다(development): %s", directory)
        return

    entry = manifest["files"].get(filename)
    if not isinstance(entry, dict) or not entry.get("sha256"):
        raise ModelIntegrityError(f"manifest 에 아티팩트가 없습니다: {directory / filename}")
    path = directory / filename
    try:
        actual = sha256_file(path)
    except OSError as exc:
        raise ModelIntegrityError(f"아티팩트를 읽을 수 없습니다: {path}: {exc}") from exc
    expected = str(entry["sha256"])
    if actual != expected:
        raise ModelIntegrityError(
            f"체크섬 불일치: {path} (manifest {expected[:16]}..., 실제 {actual[:16]}...)"
        )

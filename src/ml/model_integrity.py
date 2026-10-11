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

해시만으로는 막지 못하는 경우가 하나 남습니다. 모델 디렉터리에 쓸 수 있는
공격자가 가중치와 manifest 를 함께 바꾸고 해시까지 다시 계산하면 대조가
맞습니다. 그래서 manifest 에 HMAC-SHA256 서명을 더합니다. 키는
`settings.MODEL_MANIFEST_SIGNING_KEY` 이고, 서명 대상은 `signature` 필드를 뺀
`{schema, files}` 의 정규 JSON(키 정렬, 최소 구분자, UTF-8)입니다. 키가 없으면
서명 없이 기록합니다. production·staging 은 키가 없거나 서명이 없으면 거부하고,
development 는 경고 후 해시 검증만 합니다. 서명이 있는데 틀리면 환경과 무관하게
거부합니다.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from pathlib import Path
from typing import Any

from src.app.core.config import settings

logger = logging.getLogger(__name__)

MANIFEST_FILENAME = "artifact_manifest.json"
MANIFEST_SCHEMA = "model_artifact_manifest_v1"

# manifest 서명 필드와 유일하게 지원하는 알고리즘입니다. 서명 대상은 이 필드를
# 뺀 나머지 payload 이므로, 서명을 계산할 때와 검증할 때 같은 필드 이름을 써야 합니다.
SIGNATURE_FIELD = "signature"
SIGNATURE_ALGORITHM = "hmac-sha256"

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


def _is_single_path_component(filename: object) -> bool:
    """이름이 디렉터리 안 단일 경로 성분인지 판정합니다.

    경로 구분자, 상위 참조(`..`), 절대 경로, 빈 문자열을 모두 거부합니다.
    POSIX 에서 백슬래시는 구분자가 아니지만 Windows 배포를 함께 막기 위해
    `/` 와 `\\` 를 모두 금지합니다.
    """
    if not isinstance(filename, str) or not filename:
        return False
    if filename in {".", ".."}:
        return False
    if "/" in filename or "\\" in filename:
        return False
    return not Path(filename).is_absolute()


def _assert_single_path_component(filename: object, *, label: str) -> str:
    if not _is_single_path_component(filename):
        raise ModelIntegrityError(f"{label} 이 디렉터리 밖을 가리킵니다: {filename!r}")
    return str(filename)


def resolve_artifact_path(model_dir: Path | str, candidate: Path | str) -> Path:
    """로드 대상 경로를 model_dir 안의 단일 파일로 확정합니다.

    `..`, 절대 경로, 심볼릭 링크로 디렉터리 밖을 가리키면
    ModelIntegrityError 를 냅니다. 래퍼가 여는 경로와 manifest 로 검증하는
    경로를 같은 resolved 경로로 묶기 위한 함수입니다.
    """
    directory = Path(model_dir).resolve()
    raw = Path(str(candidate))
    if raw.is_absolute():
        raise ModelIntegrityError(f"절대 경로 아티팩트는 열지 않습니다: {candidate}")
    resolved = (directory / raw).resolve()
    try:
        relative = resolved.relative_to(directory)
    except ValueError as exc:
        raise ModelIntegrityError(
            f"모델 디렉터리 밖의 아티팩트는 열지 않습니다: {candidate}"
        ) from exc
    if len(relative.parts) != 1 or not _is_single_path_component(relative.name):
        raise ModelIntegrityError(f"모델 디렉터리 밖의 아티팩트는 열지 않습니다: {candidate}")
    return resolved


def sha256_file(path: Path | str) -> str:
    """파일의 SHA-256 을 청크 단위로 계산합니다."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(_HASH_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_manifest_bytes(payload: dict[str, Any]) -> bytes:
    """서명 대상 바이트를 만듭니다.

    `signature` 필드를 뺀 payload 를 키 정렬·최소 구분자 JSON 으로 직렬화합니다.
    같은 값이면 실행 환경과 무관하게 같은 바이트가 나와야 기록과 검증이
    일치하므로, 들여쓰기나 필드 순서 같은 표현 차이를 배제합니다.
    """
    body = {key: value for key, value in payload.items() if key != SIGNATURE_FIELD}
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def compute_manifest_signature(payload: dict[str, Any], key: str) -> str:
    """`signature` 필드를 뺀 payload 의 HMAC-SHA256 16진 문자열을 계산합니다."""
    return hmac.new(
        key.encode("utf-8"), _canonical_manifest_bytes(payload), hashlib.sha256
    ).hexdigest()


def _build_manifest_signature(payload: dict[str, Any]) -> dict[str, str] | None:
    """서명 키가 있으면 manifest 에 넣을 서명 블록을 만듭니다."""
    key = settings.MODEL_MANIFEST_SIGNING_KEY
    if not key:
        return None
    return {"alg": SIGNATURE_ALGORITHM, "value": compute_manifest_signature(payload, key)}


def _verify_manifest_signature(payload: dict[str, Any]) -> None:
    """manifest 서명을 검증하고, 규칙에 어긋나면 로드를 거부합니다.

    (a) production·staging 에서 키가 비어 있으면 거부
    (b) production·staging 에서 manifest 에 서명이 없거나 틀리면 거부
    (c) development 에서 키가 있고 서명이 있는데 틀리면 거부
    (d) development 에서 키가 없거나 서명이 없으면 경고 후 해시 검증만

    키 값과 서명 값은 예외 메시지와 로그에 넣지 않습니다.
    """
    key = settings.MODEL_MANIFEST_SIGNING_KEY
    required = settings.ENVIRONMENT in MANIFEST_REQUIRED_ENVIRONMENTS
    if not key:
        if required:
            raise ModelIntegrityError(
                f"manifest 서명 키가 없어 로드를 거부합니다({settings.ENVIRONMENT})"
            )
        logger.warning("manifest 서명 키가 없어 서명 검증 없이 진행합니다(development)")
        return

    signature = payload.get(SIGNATURE_FIELD)
    if signature is None:
        if required:
            raise ModelIntegrityError(
                f"manifest 에 서명이 없어 로드를 거부합니다({settings.ENVIRONMENT})"
            )
        logger.warning("manifest 에 서명이 없어 서명 검증 없이 진행합니다(development)")
        return
    if (
        not isinstance(signature, dict)
        or signature.get("alg") != SIGNATURE_ALGORITHM
        or not isinstance(signature.get("value"), str)
    ):
        raise ModelIntegrityError("manifest 서명 형식이 올바르지 않습니다")

    expected = compute_manifest_signature(payload, key)
    try:
        matches = hmac.compare_digest(expected, signature["value"])
    except TypeError as exc:
        raise ModelIntegrityError("manifest 서명 형식이 올바르지 않습니다") from exc
    if not matches:
        raise ModelIntegrityError("manifest 서명이 일치하지 않습니다")


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

    서명 키(`settings.MODEL_MANIFEST_SIGNING_KEY`)가 있으면 `signature` 블록을
    함께 넣습니다. 키가 없으면 지금까지처럼 서명 없이 씁니다.

    타임스탬프를 담지 않습니다. 같은 파일 세트를 두 번 봉인하면 같은 바이트가
    나와야 승격·생성 스크립트의 결과를 재현·대조할 수 있습니다. HMAC 은
    결정론적이라 서명을 붙여도 이 성질은 유지됩니다.
    """
    directory = Path(model_dir)
    if not directory.is_dir():
        raise FileNotFoundError(f"모델 디렉터리를 찾을 수 없습니다: {directory}")

    files = {}
    for path in iter_manifest_targets(directory):
        name = _assert_single_path_component(path.name, label="manifest 키")
        files[name] = {"sha256": sha256_file(path), "bytes": path.stat().st_size}
    payload: dict[str, Any] = {"schema": MANIFEST_SCHEMA, "files": files}
    signature = _build_manifest_signature(payload)
    if signature is not None:
        payload[SIGNATURE_FIELD] = signature
    manifest_path = directory / MANIFEST_FILENAME
    manifest_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return payload


def load_manifest(model_dir: Path | str) -> dict[str, Any] | None:
    """manifest 를 읽고 서명을 검증합니다. 없으면 None, 잘못됐으면 예외입니다.

    서명 규칙은 `_verify_manifest_signature` 를 따릅니다. 해시 검증 전에
    manifest 한 번만 읽어 서명을 대조하므로 파일마다 반복 비용이 없습니다.
    """
    manifest_path = Path(model_dir) / MANIFEST_FILENAME
    if not manifest_path.is_file():
        return None
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ModelIntegrityError(f"manifest 를 읽을 수 없습니다: {manifest_path}: {exc}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("files"), dict):
        raise ModelIntegrityError(f"manifest 형식이 올바르지 않습니다: {manifest_path}")
    for name in payload["files"]:
        _assert_single_path_component(name, label="manifest 키")
    _verify_manifest_signature(payload)
    return payload


def verify_file(model_dir: Path | str, filename: str) -> None:
    """파일이 manifest 와 일치하는지 확인하고, 아니면 로드를 거부합니다.

    manifest 가 없으면 production·staging 은 거부하고 development 는 경고 후
    진행합니다. manifest 의 서명은 load_manifest 가 검증하며, 틀리면 환경과
    무관하게 거부합니다. manifest 가 있는데 파일이 없거나 해시가 다르면 환경과
    무관하게 거부합니다(변조는 개발 볼륨에서도 조용히 넘기지 않습니다).

    filename 은 디렉터리 안 단일 경로 성분이어야 합니다. `..` 나 구분자가 섞이면
    검증 대상과 실제로 여는 파일이 갈라지므로 먼저 거부합니다.
    """
    _assert_single_path_component(filename, label="아티팩트 이름")
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

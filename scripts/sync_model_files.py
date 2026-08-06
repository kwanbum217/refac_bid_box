#!/usr/bin/env python3
"""
모델 가중치 번들 내보내기·들여오기.

가중치 바이너리는 Git 추적 대상이 아닙니다(`.gitignore` 의 `*.bin`, `*.joblib`).
저장소만 클론한 장비에는 `metadata.json` 만 오고 `model.bin` 은 오지 않으므로,
그대로는 예측 API 가 뜨지 않고 `verify_migration.py` 도 통과하지 못합니다.
이 스크립트가 그 사이를 잇습니다.

`import_data_assets.py` 는 원본 `bid_box` 저장소가 옆에 있을 때만 동작하므로
새 장비에서는 쓸 수 없습니다. 그쪽은 최초 이관용, 이쪽은 장비 간 배포용입니다.

**체크섬 매니페스트(`data/backups/data_assets_checksums.json`)는 건드리지
않습니다.** 그 파일은 원본 4종의 G1 기준선이며, 현재 서빙본으로 다시 만들면
승격된 모델이 기준선을 덮어써 무손실 검증이 의미를 잃습니다.

사용:
  python scripts/sync_model_files.py export
  python scripts/sync_model_files.py export --output dist/models.tar.gz
  python scripts/sync_model_files.py import --input dist/models.tar.gz
  python scripts/sync_model_files.py verify --input dist/models.tar.gz
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import shutil
import sys
import tarfile
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.app.core.config import settings  # noqa: E402

DEFAULT_BUNDLE = PROJECT_ROOT / "dist" / "model_files_bundle.tar.gz"

# 번들에 담는 것들입니다.
#
# model_backups 를 빼면 안 됩니다. 승격된 모델은 서빙본이 원본과 달라지므로
# verify_migration.py 가 원본 기준선을 백업 쪽에서 대조합니다(그 파일 134행).
# 백업이 없는 장비에서는 G1 검증이 "체크섬 불일치" 로 떨어집니다.
#
# model_metrics 는 승격 게이트가 champion 지표를 읽는 사이드카입니다. 없으면
# 재학습이 비교 대상을 찾지 못해 판정 불가로 빠집니다.
BUNDLE_MEMBERS = (
    ("model_files", lambda: Path(settings.MODEL_FILES_DIR)),
    ("model_backups", lambda: Path(settings.MODEL_BACKUPS_DIR)),
    ("model_metrics", lambda: Path(settings.MODEL_METRICS_DIR)),
)

# 재생성되는 캐시는 담지 않습니다. 장비마다 파이썬 버전이 달라 오히려 해롭습니다.
EXCLUDE_DIRS = {"__pycache__"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def iter_files(base: Path):
    for path in sorted(base.rglob("*")):
        if not path.is_file():
            continue
        if EXCLUDE_DIRS & set(path.parts):
            continue
        yield path


def build_inventory() -> tuple[dict, int]:
    """번들에 담길 파일 목록과 체크섬을 만듭니다."""
    inventory: dict[str, dict] = {}
    total_bytes = 0
    for member, resolve in BUNDLE_MEMBERS:
        base = resolve()
        if not base.exists():
            continue
        for path in iter_files(base):
            # 키는 as_posix 로 고정합니다. str() 은 Windows 에서 역슬래시를
            # 내므로 한 플랫폼에서 만든 번들을 다른 곳에서 대조할 수 없습니다.
            rel = (Path(member) / path.relative_to(base)).as_posix()
            size = path.stat().st_size
            inventory[rel] = {"sha256": sha256_file(path), "bytes": size}
            total_bytes += size
    return inventory, total_bytes


def cmd_export(args: argparse.Namespace) -> int:
    output: Path = args.output
    inventory, total_bytes = build_inventory()
    if not inventory:
        print("[실패] 담을 파일이 없습니다. 가중치 경로를 확인하십시오.")
        for member, resolve in BUNDLE_MEMBERS:
            print(f"       {member}: {resolve()}")
        return 1

    manifest = {
        "generated_at": datetime.now(UTC).isoformat(),
        "file_count": len(inventory),
        "total_bytes": total_bytes,
        "files": inventory,
    }

    output.parent.mkdir(parents=True, exist_ok=True)
    print(f"[1/2] 번들 생성: {output}")
    with tarfile.open(output, "w:gz") as tar:
        for member, resolve in BUNDLE_MEMBERS:
            base = resolve()
            if not base.exists():
                print(f"      건너뜀(없음): {member} -> {base}")
                continue
            for path in iter_files(base):
                arcname = (Path(member) / path.relative_to(base)).as_posix()
                tar.add(path, arcname=arcname)
        payload = json.dumps(manifest, indent=2, ensure_ascii=False).encode("utf-8")
        info = tarfile.TarInfo("bundle_manifest.json")
        info.size = len(payload)
        # 재현 가능한 번들이 되도록 시각을 고정합니다. 같은 가중치를 두 번
        # 내보내면 같은 내용이 나와야 배포본을 대조할 수 있습니다.
        info.mtime = 0
        tar.addfile(info, io.BytesIO(payload))

    bundle_sha = sha256_file(output)
    sidecar = output.with_suffix(output.suffix + ".sha256")
    sidecar.write_text(f"{bundle_sha}  {output.name}\n", encoding="utf-8")

    print(f"[2/2] 파일 {len(inventory)}개 / {total_bytes / 1024 / 1024:.1f}MB")
    print(f"      번들 크기: {output.stat().st_size / 1024 / 1024:.1f}MB")
    print(f"      SHA256: {bundle_sha}")
    print(f"      사이드카: {sidecar}")
    return 0


def read_bundle_manifest(bundle: Path) -> dict:
    with tarfile.open(bundle, "r:gz") as tar:
        handle = tar.extractfile("bundle_manifest.json")
        if handle is None:
            raise ValueError("번들에 bundle_manifest.json 이 없습니다")
        return json.loads(handle.read().decode("utf-8"))


def verify_sidecar(bundle: Path) -> list[str]:
    sidecar = bundle.with_suffix(bundle.suffix + ".sha256")
    if not sidecar.exists():
        return [f"사이드카 없음: {sidecar} (전송 중 손상을 확인할 수 없습니다)"]
    expected = sidecar.read_text(encoding="utf-8").split()[0]
    actual = sha256_file(bundle)
    if expected != actual:
        return [f"번들 체크섬 불일치: 기대 {expected[:16]}... 실제 {actual[:16]}..."]
    return []


def cmd_verify(args: argparse.Namespace) -> int:
    bundle: Path = args.input
    if not bundle.exists():
        print(f"[실패] 번들 없음: {bundle}")
        return 1

    failures = verify_sidecar(bundle)

    # 전송 중 잘린 번들은 압축 해제 자체가 실패합니다. 예외를 그대로 두면
    # 검증이 크래시로 끝나 import 쪽 방어가 동작하지 않습니다.
    try:
        manifest = read_bundle_manifest(bundle)
        files = manifest.get("files", {})

        with tarfile.open(bundle, "r:gz") as tar:
            names = {n for n in tar.getnames() if n != "bundle_manifest.json"}
            missing = set(files) - names
            extra = names - set(files)
            for name in sorted(missing):
                failures.append(f"목록에 있으나 번들에 없음: {name}")
            for name in sorted(extra):
                failures.append(f"번들에 있으나 목록에 없음: {name}")

            for name, meta in sorted(files.items()):
                if name in missing:
                    continue
                handle = tar.extractfile(name)
                if handle is None:
                    failures.append(f"읽을 수 없음: {name}")
                    continue
                digest = hashlib.sha256()
                while chunk := handle.read(1024 * 1024):
                    digest.update(chunk)
                if digest.hexdigest() != meta["sha256"]:
                    failures.append(f"체크섬 불일치: {name}")
    except (tarfile.TarError, EOFError, OSError, ValueError, json.JSONDecodeError) as exc:
        failures.append(f"번들을 읽을 수 없음: {type(exc).__name__}: {exc}")

    if failures:
        print(f"[실패] {len(failures)}건")
        for line in failures[:10]:
            print(f"       {line}")
        return 1

    print(f"[통과] 파일 {len(files)}개 체크섬 일치")
    print(f"       생성 시각: {manifest.get('generated_at')}")
    return 0


def cmd_import(args: argparse.Namespace) -> int:
    bundle: Path = args.input
    if not bundle.exists():
        print(f"[실패] 번들 없음: {bundle}")
        return 1

    # 배치 전에 먼저 검증합니다. 손상된 번들을 풀어 놓고 나서 알아차리면
    # 기존 서빙본이 이미 덮여 있습니다.
    print("[1/3] 번들 무결성 검증")
    if cmd_verify(args) != 0:
        print("       검증에 실패해 배치하지 않았습니다. 기존 가중치는 그대로입니다.")
        return 1

    manifest = read_bundle_manifest(bundle)
    targets = {member: resolve() for member, resolve in BUNDLE_MEMBERS}

    existing = [str(path) for path in targets.values() if path.exists()]
    if existing and not args.force:
        print("[중단] 다음 경로에 이미 파일이 있습니다.")
        for path in existing:
            print(f"       {path}")
        print("       덮어쓰려면 --force 를 붙이십시오.")
        return 1

    print("[2/3] 배치")
    with tarfile.open(bundle, "r:gz") as tar:
        for name in manifest.get("files", {}):
            member = name.split("/", 1)[0]
            base = targets.get(member)
            if base is None:
                print(f"       건너뜀(대상 불명): {name}")
                continue
            dest = base / Path(name).relative_to(member)
            dest.parent.mkdir(parents=True, exist_ok=True)
            handle = tar.extractfile(name)
            if handle is None:
                continue
            with dest.open("wb") as out:
                shutil.copyfileobj(handle, out)
    for member, base in targets.items():
        if base.exists():
            print(f"       {member} -> {base}")

    print("[3/3] 배치 후 확인")
    print("       uv run python scripts/verify_migration.py")
    print("       uv run python scripts/promote_model.py status")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="모델 가중치 번들 내보내기·들여오기")
    sub = parser.add_subparsers(dest="command", required=True)

    p_export = sub.add_parser("export", help="현재 가중치를 번들로 묶습니다")
    p_export.add_argument("--output", type=Path, default=DEFAULT_BUNDLE)
    p_export.set_defaults(func=cmd_export)

    p_import = sub.add_parser("import", help="번들을 검증한 뒤 배치합니다")
    p_import.add_argument("--input", type=Path, default=DEFAULT_BUNDLE)
    p_import.add_argument("--force", action="store_true", help="기존 가중치를 덮어씁니다")
    p_import.set_defaults(func=cmd_import)

    p_verify = sub.add_parser("verify", help="번들 무결성만 확인합니다")
    p_verify.add_argument("--input", type=Path, default=DEFAULT_BUNDLE)
    p_verify.set_defaults(func=cmd_verify)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

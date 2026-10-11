#!/usr/bin/env python3
"""
서빙 모델 디렉터리용 무결성 manifest 생성.

`data/model_files/<모델>/` 의 로드 대상 파일(model.bin, 보조 `*.bin`/`*.joblib`,
preprocess.py, metadata.json)에 sha256 manifest(`artifact_manifest.json`)를
씁니다. 모델 래퍼는 manifest 와 대조가 맞아야 파일을 열므로
(src/ml/model_integrity.py), 승격 이력을 거치지 않고 들어온 기존
디렉터리에는 이 스크립트로 기준선을 만들어야 합니다.

LIVE 포인터가 있는 슬롯은 공개된 세대 트리에 씁니다. 로더가 실제로 여는
트리와 같은 곳이어야 검증이 의미를 가집니다.

manifest 는 model.bin 과 한 세트로 생성·배포되는 머신별 산출물이라 Git 추적
대상이 아닙니다(.gitignore). metadata.json 은 계속 추적합니다.

사용:
  uv run python scripts/write_model_manifests.py
  uv run python scripts/write_model_manifests.py --model-files-dir data/model_files
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.app.core.config import settings  # noqa: E402
from src.ml.model_integrity import iter_manifest_targets, write_manifest  # noqa: E402
from src.ml.model_registry import resolve_serving_tree  # noqa: E402


def iter_model_slots(root: Path) -> list[Path]:
    """모델 슬롯 디렉터리를 경로순으로 돌려줍니다. 승격 임시 디렉터리는 뺍니다."""
    if not root.is_dir():
        return []
    return sorted(
        path for path in root.iterdir() if path.is_dir() and not path.name.startswith(".")
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="서빙 모델 무결성 manifest 생성")
    parser.add_argument(
        "--model-files-dir",
        type=Path,
        default=Path(settings.MODEL_FILES_DIR),
        help="서빙 모델 루트 (기본: settings.MODEL_FILES_DIR)",
    )
    args = parser.parse_args(argv)

    root: Path = args.model_files_dir
    if not root.is_dir():
        print(f"[실패] 모델 디렉터리를 찾을 수 없습니다: {root}")
        return 1

    written = 0
    total_files = 0
    skipped = 0
    for slot in iter_model_slots(root):
        tree = resolve_serving_tree(slot)
        targets = iter_manifest_targets(tree)
        if not targets:
            print(f"[건너뜀] {slot.name}: 로드 대상 파일이 없습니다 ({tree})")
            skipped += 1
            continue
        write_manifest(tree)
        written += 1
        total_files += len(targets)
        print(f"[갱신] {slot.name}: 파일 {len(targets)}개 ({tree})")

    print(f"완료: 모델 {written}개 / 파일 {total_files}개, 건너뜀 {skipped}개")
    return 0


if __name__ == "__main__":
    sys.exit(main())

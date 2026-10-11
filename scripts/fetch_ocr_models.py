#!/usr/bin/env python3
"""
OCR 인식 모델 고정 다운로드.

스캔본 등급확인서를 읽는 rapidocr 인식 모델(korean_PP-OCRv5_rec_mobile.onnx)을
고정 URL 에서 내려받아 sha256 을 대조한 뒤 저장합니다. 값이 다르면 임시 파일을
지우고 실패하므로, 검증되지 않은 모델이 실행 경로에 남지 않습니다.

실행 중에 인터넷에서 모델을 내려받지 않도록 Dockerfile 빌드 단계에서 이 스크립트를
실행해 이미지에 모델을 넣습니다. 저장 위치 기본값은 설정 DOCUMENT_OCR_MODEL_DIR 의
기본값과 같으며(data/ocr_models), 모델 파일은 Git 추적 대상이 아닙니다.

사용:
  uv run python scripts/fetch_ocr_models.py
  uv run python scripts/fetch_ocr_models.py --dest data/ocr_models
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DEST_DIR = PROJECT_ROOT / "data" / "ocr_models"

# (파일명, 고정 URL, sha256). src/app/services/document_extraction/ocr.py 의
# MODEL_FILES 와 값이 같아야 하며, tests/test_fetch_ocr_models.py 가 대조합니다.
MODEL_SOURCES: tuple[tuple[str, str, str], ...] = (
    (
        "korean_PP-OCRv5_rec_mobile.onnx",
        "https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.10.0/onnx/PP-OCRv5/rec/"
        "korean_PP-OCRv5_rec_mobile.onnx",
        "cd6e2ea50f6943ca7271eb8c56a877a5a90720b7047fe9c41a2e541a25773c9b",
    ),
)
REQUEST_TIMEOUT_SECONDS = 60
USER_AGENT = "refac-bid-box-ocr-fetch/1.0"
CHUNK_BYTES = 1024 * 1024

Opener = Callable[..., Any]


class FetchError(RuntimeError):
    """모델 내려받기나 해시 대조에 실패했습니다."""


def sha256_of(path: Path) -> str:
    """파일 전체의 sha256 16진 문자열을 돌려줍니다."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fetch_model(
    filename: str,
    url: str,
    sha256: str,
    dest_dir: Path,
    opener: Opener = urllib.request.urlopen,
) -> Path:
    """모델 하나를 내려받아 해시를 확인하고 저장합니다.

    이미 같은 해시의 파일이 있으면 내려받지 않습니다. 저장은 임시 파일에 받은 뒤
    교체하므로, 중간에 끊겨도 반쪽짜리 파일이 남지 않습니다.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / filename
    if target.is_file() and sha256_of(target) == sha256:
        print(f"[건너뜀] {target} (해시 일치)")
        return target

    temp_path = dest_dir / f".{filename}.part"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with (
            opener(request, timeout=REQUEST_TIMEOUT_SECONDS) as response,
            temp_path.open("wb") as handle,
        ):
            for chunk in iter(lambda: response.read(CHUNK_BYTES), b""):
                handle.write(chunk)
        actual = sha256_of(temp_path)
        if actual != sha256:
            raise FetchError(f"{filename} 해시가 다릅니다: 기대 {sha256}, 실제 {actual}")
        os.replace(temp_path, target)
    finally:
        temp_path.unlink(missing_ok=True)

    print(f"[완료] {target}")
    return target


def fetch_all(dest_dir: Path, opener: Opener = urllib.request.urlopen) -> list[Path]:
    """MODEL_SOURCES 를 전부 내려받아 저장 경로 목록을 돌려줍니다."""
    return [
        fetch_model(filename, url, sha256, dest_dir, opener)
        for filename, url, sha256 in MODEL_SOURCES
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="OCR 인식 모델을 고정 URL 에서 받아 해시를 대조합니다."
    )
    parser.add_argument(
        "--dest",
        type=Path,
        default=DEFAULT_DEST_DIR,
        help="모델 저장 디렉터리 (기본 data/ocr_models)",
    )
    args = parser.parse_args(argv)
    try:
        fetch_all(args.dest)
    except (FetchError, OSError, urllib.error.URLError) as exc:
        print(f"[실패] {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

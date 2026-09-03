#!/usr/bin/env python3
"""
scripts/backup_snapshots.py

scripts/backup_recovery.py 에서 분할된 스냅샷 검증/목록/정리 함수 모음입니다.
저장된 백업 스냅샷의 무결성 검증과 목록 조회, 개수 기준 정리를 담당합니다.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from scripts.backup_recovery_core import (
    DEFAULT_SNAPSHOTS_DIR,
    MANIFEST_FILENAME,
    sha256_file,
)


def verify_snapshot(snapshot_dir: Path) -> tuple[bool, list[str], dict[str, Any]]:
    """스냅샷 디렉토리의 매니페스트 및 체크섬 무결성을 검증합니다."""
    manifest_file = snapshot_dir / MANIFEST_FILENAME
    if not manifest_file.exists():
        return False, [f"매니페스트 파일 없음: {manifest_file}"], {}

    try:
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    except Exception as exc:
        return False, [f"매니페스트 파싱 실패: {exc}"], {}

    errors: list[str] = []
    components = manifest.get("components", {})

    for comp_name, comp_info in components.items():
        rel_path = comp_info.get("path")
        if not rel_path:
            errors.append(f"{comp_name}: 매니페스트 내 파일 경로 정의 누락")
            continue

        file_path = snapshot_dir / rel_path
        if not file_path.exists():
            errors.append(f"{comp_name}: 아카이브 파일 누락 ({file_path.name})")
            continue

        expected_size = comp_info.get("size_bytes")
        if expected_size is not None and file_path.stat().st_size != expected_size:
            errors.append(
                f"{comp_name}: 파일 크기 불일치 (기대 {expected_size:,} vs 실제 {file_path.stat().st_size:,})"
            )

        expected_sha = comp_info.get("sha256")
        if expected_sha:
            actual_sha = sha256_file(file_path)
            if actual_sha != expected_sha:
                errors.append(
                    f"{comp_name}: SHA256 체크섬 불일치 ({actual_sha[:12]} vs {expected_sha[:12]})"
                )

    is_valid = len(errors) == 0
    return is_valid, errors, manifest


def list_snapshots(snapshots_dir: Path | None = None) -> list[dict[str, Any]]:
    """생성된 백업 스냅샷 목록을 조회하여 출력합니다."""
    dir_path = snapshots_dir or DEFAULT_SNAPSHOTS_DIR
    print("=" * 60)
    print(f"refac_bid_box 백업 스냅샷 목록 ({dir_path})")
    print("=" * 60)

    if not dir_path.exists():
        print("  등록된 백업 스냅샷이 없습니다.")
        return []

    snapshots = []
    for item in sorted(dir_path.iterdir(), reverse=True):
        if item.is_dir():
            manifest_file = item / MANIFEST_FILENAME
            if manifest_file.exists():
                is_valid, _, manifest = verify_snapshot(item)
                snapshots.append(
                    {
                        "dir": str(item),
                        "name": item.name,
                        "created_at": manifest.get("created_at", "unknown"),
                        "head_commit": manifest.get("head_commit", "unknown"),
                        "valid": is_valid,
                    }
                )

    if not snapshots:
        print("  유효한 백업 스냅샷이 없습니다.")
        return []

    for s in snapshots:
        valid_tag = "[정상]" if s["valid"] else "[무결성 오류]"
        print(f"  - {s['name']} {valid_tag}")
        print(f"      생성 시각: {s['created_at']}")
        print(f"      HEAD 커밋: {s['head_commit']}")
        print(f"      경로: {s['dir']}")

    return snapshots


def prune_snapshots(
    snapshots_dir: Path | None = None,
    retain_count: int = 7,
    delete: bool = False,
) -> dict[str, Any]:
    """개수 기준으로 오래된 스냅샷을 열거합니다. 삭제는 명시적으로만 수행합니다."""
    if retain_count < 1:
        raise ValueError("retain_count는 1 이상이어야 합니다.")
    directory = snapshots_dir or DEFAULT_SNAPSHOTS_DIR
    candidates = [item for item in directory.glob("snapshot_*") if item.is_dir()]
    candidates.sort(key=lambda item: item.name, reverse=True)
    stale = candidates[retain_count:]
    print(f"보존 개수: {retain_count}, 삭제 대상: {len(stale)}개")
    for item in stale:
        print(f"  - {item}")
    if delete:
        for item in stale:
            shutil.rmtree(item)
        print("명시적 삭제 플래그가 지정되어 삭제를 완료했습니다.")
    return {
        "retain_count": retain_count,
        "candidates": [str(item) for item in candidates],
        "stale": [str(item) for item in stale],
        "deleted": delete,
    }

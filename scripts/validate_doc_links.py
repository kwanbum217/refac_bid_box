#!/usr/bin/env python3
"""저장소 내부 마크다운 상대 경로 링크 검증 스크립트 (CI / pre-commit).

외부 URL(http://, https://, mailto: 등)은 네트워크 의존성으로 인해 CI를 불안정하게
만들 수 있으므로 검사 대상에서 제외하고, 저장소 내부 파일 및 디렉터리를 가리키는
상대 경로 링크의 유효성만 검증합니다.

검증 규칙:
  1. 저장소 내부 마크다운(.md) 파일 내의 링크/이미지/참조 경로를 추출합니다.
  2. 코드 블록(fenced code block) 내부의 텍스트는 검사에서 제외합니다.
  3. 외부 스킴(http, https, mailto, ftp, tel, conversation 등) 및 순수 앵커(#fragment)는 제외합니다.
  4. 파일 앵커(path/to/file.md#section) 및 줄 번호 접미사(:123, :L10-L20)는 파일 존재 여부만 검증합니다.
  5. 링크 대상 파일 또는 디렉터리가 실제로 존재하는지 확인합니다.

사용:
  python3 scripts/validate_doc_links.py          # 전체 검증
  python3 scripts/validate_doc_links.py --quiet   # 요약만 출력
  python3 scripts/validate_doc_links.py path/to/doc.md
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import urllib.parse
from pathlib import Path
from typing import NamedTuple

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# 제외할 외부 URL 스킴 목록 (네트워크 독립적 CI를 위해 외부 URL 검사 제외)
EXTERNAL_SCHEMES = (
    "http://",
    "https://",
    "mailto:",
    "ftp://",
    "ftps://",
    "tel:",
    "data:",
    "javascript:",
    "irc:",
    "urn:",
    "conversation:",  # AGY 에이전트 대화 URI 스킴
)

# 기본 무시 디렉터리 및 파일 패턴
DEFAULT_EXCLUDE_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    "chroma_db",
    "data",
    "dist",
    "build",
    "coverage",
    ".coverage",
}


class BrokenLink(NamedTuple):
    source_file: Path
    line_number: int
    raw_target: str
    resolved_path: Path
    reason: str


def is_external_link(target: str) -> bool:
    """외부 링크 여부를 판별합니다. 외부 URL은 네트워크 의존성을 배제하기 위해 검사하지 않습니다."""
    target_clean = target.strip()
    if target_clean.startswith("//"):
        return True
    lower = target_clean.lower()
    return any(lower.startswith(scheme) for scheme in EXTERNAL_SCHEMES)


def strip_code_blocks(content: str) -> list[tuple[int, str]]:
    """마크다운 내용에서 코드 블록(fenced code block)을 빈 줄로 치환하여 행 번호를 보존합니다."""
    lines = content.splitlines()
    result: list[tuple[int, str]] = []
    in_code_block = False
    fence_char = ""

    for line_idx, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not in_code_block:
            if stripped.startswith("```") or stripped.startswith("~~~"):
                in_code_block = True
                fence_char = stripped[:3]
                result.append((line_idx, ""))
            else:
                result.append((line_idx, line))
        else:
            if stripped.startswith(fence_char):
                in_code_block = False
                fence_char = ""
            result.append((line_idx, ""))

    return result


def extract_links_from_line(line: str) -> list[str]:
    """한 줄에서 마크다운 링크 대상 경로를 추출합니다."""
    targets: list[str] = []

    # 1. 인라인 링크 및 이미지: [text](target "title") or ![alt](target)
    # 괄호 안의 중첩이나 타이틀 처리를 위해 정규식 적용
    inline_pattern = re.compile(r"!?\[.*?\]\(<([^>]+)>|!?\[.*?\]\(([^)]+)\)")
    for match in inline_pattern.finditer(line):
        target = match.group(1) if match.group(1) is not None else match.group(2)
        if target:
            # 타이틀 제거 (예: "path/to/file.md 'title'" 또는 'path/to/file.md "title"')
            target_parts = target.strip().split()
            if target_parts:
                targets.append(target_parts[0])

    # 2. 참조형 링크 정의: [ref]: target "title"
    ref_pattern = re.compile(r"^\s*\[[^\]]+\]:\s*(\S+)")
    ref_match = ref_pattern.match(line)
    if ref_match:
        targets.append(ref_match.group(1))

    # 3. HTML a href 및 img src 태그
    html_href_pattern = re.compile(r"""<a\s+[^>]*href=["']([^"']+)["']""", re.IGNORECASE)
    for match in html_href_pattern.finditer(line):
        targets.append(match.group(1))

    html_src_pattern = re.compile(r"""<img\s+[^>]*src=["']([^"']+)["']""", re.IGNORECASE)
    for match in html_src_pattern.finditer(line):
        targets.append(match.group(1))

    return targets


def resolve_link_target(
    source_file: Path, raw_target: str, root_dir: Path
) -> tuple[Path | None, str]:
    """링크 타겟 경로를 로컬 파일시스템 경로로 해석합니다.

    반환값: (해석된 Path 객체, 무시 사유 또는 빈 문자열)
    """
    clean_target = raw_target.strip()

    # file:// 로 시작하는 로컬 URI 스킴 처리
    if clean_target.startswith("file://"):
        clean_target = clean_target[len("file://") :]

    # 1. 외부 URL 스킴 검사 -> 제외
    if is_external_link(clean_target):
        return None, "external_url"

    # 2. 순수 앵커 (#fragment) -> 동일 문서 내 앵커이므로 제외
    if clean_target.startswith("#"):
        return None, "anchor_only"

    # 3. 앵커 및 쿼리 파라미터 분리
    target_path, _, _ = clean_target.partition("#")
    target_path, _, _ = target_path.partition("?")
    target_path = target_path.strip()

    # 4. 파일 뒤에 붙은 줄 번호 표기(:123, :123-145, :L10-L20) 제거
    target_path = re.sub(r":(?:L?\d+(?:-L?\d+)?)$", "", target_path)

    if not target_path:
        return None, "empty_target"

    # 5. URL 디코딩 (%20 -> 공백 등)
    target_path = urllib.parse.unquote(target_path)

    target_as_path = Path(target_path)

    # 6. 절대 경로 처리
    #
    # 저장소 루트 기준 절대 표기(예: /docs/context/CURRENT_STATE.md)만 허용한다.
    # 작성자 머신의 실제 절대 경로(/Users/..., C:\\...)를 존재한다는 이유로
    # 통과시키면 그 머신에서만 green 이 된다. 2026-08-25 에 이 fail-open 때문에
    # 로컬은 통과하고 CI 3플랫폼이 33건으로 실패했다.
    if target_as_path.is_absolute():
        rel_to_root = (root_dir / target_path.lstrip("/")).resolve()
        return rel_to_root, ""

    # 7. 현재 마크다운 파일 위치 기준 상대 경로
    resolved = (source_file.parent / target_path).resolve()
    return resolved, ""


def validate_markdown_file(md_file: Path, root_dir: Path = PROJECT_ROOT) -> list[BrokenLink]:
    """단일 마크다운 파일의 링크를 검증하고 깨진 링크 목록을 반환합니다."""
    broken_links: list[BrokenLink] = []

    try:
        content = md_file.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError) as e:
        return [
            BrokenLink(
                source_file=md_file,
                line_number=1,
                raw_target="",
                resolved_path=md_file,
                reason=f"파일 읽기 오류: {e}",
            )
        ]

    lines_without_code = strip_code_blocks(content)

    for line_num, line in lines_without_code:
        if not line:
            continue
        targets = extract_links_from_line(line)
        for raw_target in targets:
            resolved_path, skip_reason = resolve_link_target(md_file, raw_target, root_dir)
            if skip_reason:
                continue

            if resolved_path is None:
                continue

            # 파일 또는 디렉터리 존재 여부 확인
            if not resolved_path.exists():
                broken_links.append(
                    BrokenLink(
                        source_file=md_file,
                        line_number=line_num,
                        raw_target=raw_target,
                        resolved_path=resolved_path,
                        reason="대상 파일 또는 디렉터리가 존재하지 않음",
                    )
                )

    return broken_links


def find_markdown_files(
    target_path: Path,
    exclude_dirs: set[str] = DEFAULT_EXCLUDE_DIRS,
) -> list[Path]:
    """대상 경로 내의 모든 마크다운 파일을 수집합니다."""
    if target_path.is_file():
        if target_path.suffix.lower() == ".md":
            return [target_path]
        return []

    md_files: list[Path] = []
    for root, dirs, files in os.walk(target_path):
        # 무시 디렉터리 제외
        dirs[:] = [
            d
            for d in dirs
            if d not in exclude_dirs
            and not (
                d.startswith(".")
                and d
                not in {".agents", ".github", ".antigravity", ".cursor", ".claude", ".opencode"}
            )
        ]
        for file in files:
            if file.endswith(".md"):
                md_files.append(Path(root) / file)

    return sorted(md_files)


def validate_doc_links(
    target_paths: list[Path] | None = None,
    root_dir: Path = PROJECT_ROOT,
    quiet: bool = False,
) -> int:
    """마크다운 문서 링크들을 검증합니다."""
    if not target_paths:
        target_paths = [root_dir]

    all_md_files: list[Path] = []
    for p in target_paths:
        all_md_files.extend(find_markdown_files(p))

    # 중복 제거 및 정렬
    unique_files = sorted(set(all_md_files))

    if not quiet:
        print("=" * 60)
        print("저장소 내부 마크다운 문서 링크 정합성 검증")
        print(f"검사 대상 파일 수: {len(unique_files)}개")
        print("=" * 60)

    total_broken: list[BrokenLink] = []
    checked_count = 0

    for md_file in unique_files:
        broken = validate_markdown_file(md_file, root_dir=root_dir)
        checked_count += 1
        if broken:
            total_broken.extend(broken)
            if not quiet:
                for b in broken:
                    rel_src = (
                        b.source_file.relative_to(root_dir)
                        if b.source_file.is_relative_to(root_dir)
                        else b.source_file
                    )
                    print(
                        f"[FAIL] {rel_src}:{b.line_number} -> {b.raw_target}\n"
                        f"       원인: {b.reason} (해석 경로: {b.resolved_path})"
                    )

    if not quiet:
        print("-" * 60)

    if total_broken:
        print(
            f"검증 실패: 총 {len(total_broken)}개의 깨진 링크 발견 "
            f"({checked_count}개 마크다운 파일 검사)."
        )
        return 1

    if not quiet:
        print(f"검증 통과: 모든 내부 마크다운 링크가 유효합니다 ({checked_count}개 파일).")
    else:
        print(f"[PASS] 문서 링크 검증 통과 ({checked_count}개 파일)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "저장소 내부 마크다운 상대 경로 링크 정합성 검증 스크립트.\n"
            "외부 URL(http://, https:// 등)은 CI 네트워크 독립성을 위해 검사에서 제외합니다."
        )
    )
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help="검사할 파일 또는 디렉터리 경로 (생략 시 저장소 전체)",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="요약 결과만 출력 (성공 시 한 줄 출력)",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=PROJECT_ROOT,
        help="프로젝트 루트 디렉터리 경로",
    )

    args = parser.parse_args()
    return validate_doc_links(
        target_paths=args.paths if args.paths else None,
        root_dir=args.root.resolve(),
        quiet=args.quiet,
    )


if __name__ == "__main__":
    sys.exit(main())

"""scripts/validate_doc_links.py 단위 테스트.

저장소 내부 마크다운 문서 상대 경로 링크 검증기의 기능을 테스트합니다.
- 정상 상대 링크 검증 통과
- 깨진 상대 링크 검출 및 실패 반환
- 파일 앵커(file.md#section) 및 순수 앵커(#section) 처리
- 외부 URL(http://, https://, mailto: 등) 제외 검증
- 코드 블록 내 예시 링크 무시 검증
- --quiet 플래그 및 CLI 실행 종료 코드 검증
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from scripts.validate_doc_links import (
    extract_links_from_line,
    find_markdown_files,
    is_external_link,
    resolve_link_target,
    strip_code_blocks,
    validate_doc_links,
    validate_markdown_file,
)


def test_is_external_link():
    """외부 URL 스킴 판별 기능을 검증합니다."""
    assert is_external_link("https://example.com")
    assert is_external_link("http://localhost:8000")
    assert is_external_link("mailto:test@example.com")
    assert is_external_link("ftp://files.example.com")
    assert is_external_link("//cdn.example.com/asset.js")
    assert is_external_link("conversation://e9e7b872")

    # 로컬 경로는 외부 링크가 아님
    assert not is_external_link("docs/README.md")
    assert not is_external_link("../ops/guide.md")
    assert not is_external_link("./relative/path.md")
    assert not is_external_link("#internal-anchor")


def test_strip_code_blocks():
    """마크다운 코드 블록(fenced code block) 내부가 제거되고 행 번호가 보존되는지 검증합니다."""
    content = """# Title
[Normal Link](docs/guide.md)
```python
# Code block
[Fake Link in Code](invalid/path.md)
```
[Another Normal Link](docs/api.md)
"""
    lines = strip_code_blocks(content)
    assert len(lines) == 7
    # 2번째 줄(정상 링크)은 유지
    assert lines[1] == (2, "[Normal Link](docs/guide.md)")
    # 4번째 줄(코드 블록 내부)은 빈 줄로 치환
    assert lines[3] == (4, "")
    # 7번째 줄(정상 링크)은 유지
    assert lines[6] == (7, "[Another Normal Link](docs/api.md)")


def test_extract_links_from_line():
    """다양한 형식의 마크다운 링크 추출을 검증합니다."""
    line = (
        'Check [Guide](docs/guide.md "Title") and ![Img](images/arch.png) or <a href="docs/api.md">'
    )
    links = extract_links_from_line(line)
    assert "docs/guide.md" in links
    assert "images/arch.png" in links
    assert "docs/api.md" in links

    # 참조형 링크 정의
    ref_line = "  [ref1]: docs/reference.md 'Ref Title'"
    ref_links = extract_links_from_line(ref_line)
    assert ref_links == ["docs/reference.md"]


def test_resolve_link_target(tmp_path: Path):
    """링크 타겟 경로 해석 및 앵커/쿼리 분리를 검증합니다."""
    root_dir = tmp_path
    doc_dir = root_dir / "docs" / "sub"
    doc_dir.mkdir(parents=True)
    source_file = doc_dir / "index.md"
    source_file.write_text("content", encoding="utf-8")

    target_file = root_dir / "docs" / "target.md"
    target_file.write_text("target", encoding="utf-8")

    # 1. 상대 경로 + 앵커
    resolved, skip = resolve_link_target(source_file, "../target.md#section-1", root_dir)
    assert skip == ""
    assert resolved == target_file

    # 2. 줄 번호 접미사 (:123, :L10-L20)
    resolved, skip = resolve_link_target(source_file, "../target.md:15", root_dir)
    assert skip == ""
    assert resolved == target_file

    resolved, skip = resolve_link_target(source_file, "../target.md:L10-L20", root_dir)
    assert skip == ""
    assert resolved == target_file

    # 3. 순수 앵커
    resolved, skip = resolve_link_target(source_file, "#section-only", root_dir)
    assert skip == "anchor_only"
    assert resolved is None

    # 4. 외부 URL
    resolved, skip = resolve_link_target(source_file, "https://google.com", root_dir)
    assert skip == "external_url"
    assert resolved is None


def test_validate_markdown_file_valid_and_broken(tmp_path: Path):
    """마크다운 파일의 정상 링크 및 깨진 링크 검출을 검증합니다."""
    root_dir = tmp_path
    docs_dir = root_dir / "docs"
    docs_dir.mkdir()

    valid_target = docs_dir / "valid.md"
    valid_target.write_text("# Valid target", encoding="utf-8")

    test_md = docs_dir / "test.md"
    test_md.write_text(
        """# Test Document
- [Valid Link](valid.md)
- [Valid with Anchor](valid.md#overview)
- [Valid with Line](valid.md:10)
- [External Link](https://example.com/docs)
- [Anchor Only](#self-anchor)
- [Broken Link](nonexistent.md)
- [Broken with Anchor](missing_file.md#part1)
""",
        encoding="utf-8",
    )

    broken = validate_markdown_file(test_md, root_dir=root_dir)

    assert len(broken) == 2
    raw_targets = [b.raw_target for b in broken]
    assert "nonexistent.md" in raw_targets
    assert "missing_file.md#part1" in raw_targets

    # 깨진 링크 행 번호 확인 (6번째 줄과 7번째 줄)
    line_nums = [b.line_number for b in broken]
    assert 7 in line_nums
    assert 8 in line_nums


def test_validate_doc_links_function(tmp_path: Path):
    """validate_doc_links 함수가 유효/비유효 시 각각 0과 1을 반환하는지 검증합니다."""
    root_dir = tmp_path
    doc = root_dir / "doc.md"
    target = root_dir / "target.md"
    target.write_text("hello", encoding="utf-8")

    doc.write_text("[Link](target.md)", encoding="utf-8")
    assert validate_doc_links(target_paths=[doc], root_dir=root_dir, quiet=True) == 0

    doc.write_text("[Broken Link](missing.md)", encoding="utf-8")
    assert validate_doc_links(target_paths=[doc], root_dir=root_dir, quiet=True) == 1


def test_find_markdown_files(tmp_path: Path):
    """find_markdown_files가 제외 디렉터리를 올바르게 건너뛰는지 검증합니다."""
    (tmp_path / "valid.md").write_text("content", encoding="utf-8")

    venv_dir = tmp_path / ".venv"
    venv_dir.mkdir()
    (venv_dir / "ignored.md").write_text("content", encoding="utf-8")

    sub_dir = tmp_path / "subdir"
    sub_dir.mkdir()
    (sub_dir / "sub.md").write_text("content", encoding="utf-8")

    files = find_markdown_files(tmp_path)
    file_names = [f.name for f in files]
    assert "valid.md" in file_names
    assert "sub.md" in file_names
    assert "ignored.md" not in file_names


def test_host_absolute_path_is_broken_even_if_it_exists(tmp_path):
    """작성자 머신에 실재하는 절대 경로도 깨진 링크로 잡아야 합니다.

    존재한다는 이유로 통과시키면 그 머신에서만 green 이 됩니다. 2026-08-25 에
    이 fail-open 으로 로컬은 통과하고 CI 3플랫폼이 33건으로 실패했습니다.
    """
    existing_abs = tmp_path / "outside.txt"
    existing_abs.write_text("x", encoding="utf-8")
    assert existing_abs.is_absolute()
    assert existing_abs.exists()

    repo = tmp_path / "repo"
    (repo / "docs").mkdir(parents=True)
    md = repo / "docs" / "doc.md"
    md.write_text(f"[바깥]({existing_abs})\n", encoding="utf-8")

    broken = validate_markdown_file(md, root_dir=repo)
    assert len(broken) == 1
    assert str(existing_abs) in broken[0].raw_target


def test_file_uri_to_host_path_is_broken(tmp_path):
    """file:// 로 감싼 머신 절대 경로도 같은 이유로 잡아야 합니다."""
    existing_abs = tmp_path / "outside2.txt"
    existing_abs.write_text("x", encoding="utf-8")

    repo = tmp_path / "repo2"
    (repo / "docs").mkdir(parents=True)
    md = repo / "docs" / "doc.md"
    md.write_text(f"[바깥](file://{existing_abs})\n", encoding="utf-8")

    assert len(validate_markdown_file(md, root_dir=repo)) == 1


def test_windows_drive_absolute_path_is_broken(tmp_path):
    """드라이브 문자가 붙은 절대 경로도 저장소 밖이면 깨진 링크여야 합니다.

    Windows 에서 Path 조인은 드라이브 절대 경로를 만나면 root_dir 를 통째로
    버리므로, anchor 를 떼지 않으면 작성자 머신 경로가 그대로 통과합니다.
    """
    repo = tmp_path / "repo_win"
    (repo / "docs").mkdir(parents=True)
    md = repo / "docs" / "doc.md"
    md.write_text("[바깥](C:/Users/kwanbum/outside.txt)\n", encoding="utf-8")

    assert len(validate_markdown_file(md, root_dir=repo)) == 1


def test_cli_execution():
    """CLI 형태로 스크립트를 호출했을 때 정상 종료(exit code 0)하는지 검증합니다."""
    proc = subprocess.run(
        [sys.executable, "scripts/validate_doc_links.py", "--quiet"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    assert "[PASS]" in proc.stdout

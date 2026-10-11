"""vendor 정적 자산의 출처 기록과 SHA-256 고정을 검증한다 (보안 검토 L16).

vendor 아래 모든 파일은 디렉터리 단위 SOURCE.txt 에 기록되어야 하며,
기록된 SHA-256 은 현재 파일 해시와 일치해야 한다. 또한 템플릿이 참조하는
vendor 경로가 모두 기록되어 있는지 확인한다. vendor 파일 자체는 검증만 하고 수정하지 않는다.
"""

import hashlib
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
VENDOR_DIR = PROJECT_ROOT / "src" / "app" / "static" / "vendor"
TEMPLATES_DIR = PROJECT_ROOT / "src" / "app" / "templates"
SOURCE_NAME = "SOURCE.txt"
VENDOR_PREFIX = "vendor/"

LIBRARY_DIRS = (
    "bootstrap",
    "chartjs",
    "daisyui",
    "fontawesome",
    "fonts",
    "jquery",
    "marked",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def parse_source_file(source_path: Path) -> list[dict]:
    """SOURCE.txt 를 빈 줄로 구분된 레코드 목록으로 파싱한다."""
    records = []
    text = source_path.read_text(encoding="utf-8")
    for raw_block in re.split(r"\n\s*\n", text):
        if not raw_block.strip():
            continue
        lines = [line.strip() for line in raw_block.splitlines() if line.strip()]
        record = {"header": lines[0], "source": None, "sha256": None, "file": None}
        for line in lines[1:]:
            key, _, value = line.partition(":")
            if key.strip() == "Source":
                record["source"] = value.strip()
            elif key.strip() == "SHA-256":
                record["sha256"] = value.strip()
            elif key.strip() == "File":
                record["file"] = value.strip()
        records.append(record)
    return records


def load_records() -> dict[str, str]:
    """vendor 기준 상대 경로 -> 기록된 SHA-256 매핑을 만든다."""
    records: dict[str, str] = {}
    for source in sorted(VENDOR_DIR.rglob(SOURCE_NAME)):
        for record in parse_source_file(source):
            if record["file"]:
                rel = record["file"]
            else:
                siblings = [
                    path
                    for path in sorted(source.parent.iterdir())
                    if path.is_file() and path.name != SOURCE_NAME
                ]
                assert len(siblings) == 1, (
                    f"{source} 에 File 줄이 없고 디렉터리 파일 수가 1이 아니다: {len(siblings)}"
                )
                rel = siblings[0].relative_to(VENDOR_DIR).as_posix()
            assert record["sha256"], f"{source} 의 '{rel}' 레코드에 SHA-256 이 없다"
            assert rel not in records, f"{rel} 이 SOURCE.txt 에 중복 기록됐다"
            records[rel] = record["sha256"]
    return records


def vendor_files() -> set[str]:
    return {
        path.relative_to(VENDOR_DIR).as_posix()
        for path in VENDOR_DIR.rglob("*")
        if path.is_file() and path.name != SOURCE_NAME
    }


def template_vendor_references() -> set[str]:
    references: set[str] = set()
    for template in sorted(TEMPLATES_DIR.rglob("*.html")):
        content = template.read_text(encoding="utf-8")
        references.update(re.findall(r"vendor/[A-Za-z0-9._/-]+", content))
    return references


def test_each_library_directory_has_source_file():
    missing = [name for name in LIBRARY_DIRS if not any((VENDOR_DIR / name).rglob(SOURCE_NAME))]
    assert missing == [], f"SOURCE.txt 가 없는 vendor 라이브러리 디렉터리: {missing}"


def test_every_vendor_file_is_recorded():
    recorded = set(load_records())
    actual = vendor_files()
    unrecorded = actual - recorded
    stale = recorded - actual
    assert unrecorded == set(), f"SOURCE.txt 에 기록되지 않은 vendor 파일: {sorted(unrecorded)}"
    assert stale == set(), f"실제로 존재하지 않는 파일이 기록됨: {sorted(stale)}"


def test_recorded_hashes_match_files():
    mismatched = []
    for rel, expected in load_records().items():
        actual = sha256_file(VENDOR_DIR / rel)
        if actual != expected:
            mismatched.append((rel, expected, actual))
    assert mismatched == [], f"기록 해시와 실제 파일 해시가 다름: {mismatched}"


def test_template_referenced_vendor_files_are_recorded():
    recorded = set(load_records())
    missing = [
        reference
        for reference in sorted(template_vendor_references())
        if (VENDOR_DIR / reference[len(VENDOR_PREFIX) :]).is_file()
        and reference[len(VENDOR_PREFIX) :] not in recorded
    ]
    assert missing == [], f"템플릿이 참조하지만 기록되지 않은 vendor 파일: {missing}"

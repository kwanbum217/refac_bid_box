#!/usr/bin/env python3
"""적격심사 근거 원문 수집·중복 제거·manifest 생성·보고서 인용 갱신 스크립트.

EXT_SRC 아래에 흩어진 HWP·PDF·추출 텍스트·표를 sha256 기준으로 중복 제거해
data/sources/qualification/files/<기관 slug>/<sha256 앞 12자>_<정리된 파일명>
으로 모으고, 파일별 출처 메타데이터를 담은 manifest.json 을 만든다.
docs/analysis 의 'EXT/...' 와 '.orca/capsules/task_*/external/...' 인용을 새 경로로
바꾸고, 어떤 보고서가 어떤 파일을 인용하는지(cited_by)를 manifest 에 남긴다.

결정적이다. 같은 입력에 대해 두 번 돌려도 manifest.json 이 바이트 단위로 같다.
타임스탬프나 절대 경로를 결과에 넣지 않는다.

사용:
  uv run python scripts/build_qualification_sources_manifest.py
  uv run python scripts/build_qualification_sources_manifest.py --source-dir EXT_SRC
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_SOURCE_DIR = PROJECT_ROOT / "EXT_SRC"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "sources" / "qualification"
DEFAULT_DOCS_DIR = PROJECT_ROOT / "docs" / "analysis"

MANIFEST_SCHEMA = "QUALIFICATION_SOURCES_MANIFEST_V1"
MANIFEST_FILENAME = "manifest.json"
README_FILENAME = "README.md"
FILES_SUBDIR = "files"
NEW_CITATION_PREFIX = "data/sources/qualification/files/"

ENTRY_KEYS = (
    "sha256",
    "path",
    "original_filename",
    "institution",
    "doc_title",
    "doc_number",
    "effective_date",
    "source_url",
    "source_kind",
    "derived_from",
    "cited_by",
    "first_seen",
)

# 원문이 아닌 실행 산출물, 로그, 오류 덤프, OS 잡파일은 수집하지 않는다.
EXCLUDED_DIR_PARTS = frozenset({"__pycache__", ".git"})
EXCLUDED_BASENAMES = frozenset({".DS_Store", "Thumbs.db", "desktop.ini"})
EXCLUDED_SUFFIXES = frozenset(
    {".py", ".pyc", ".js", ".css", ".err", ".log", ".sh", ".sql", ".sqlite3", ".rdb", ".pdf.err"}
)

# 기관 slug -> 실제 기관명. slug 는 EXT_SRC 하위 폴더명(캡슐 task 디렉터리 바로 아래)과 맞춘다.
SLUG_INSTITUTIONS: dict[str, str] = {
    "busan": "부산광역시",
    "cb": "충청북도",
    "chungnam": "충청남도",
    "daegu": "대구광역시",
    "daejeon": "대전광역시",
    "dapa": "방위사업청",
    "ekr": "한국농어촌공사",
    "gb": "경상북도",
    "gg": "경기도",
    "gn": "경상남도",
    "gwd": "강원특별자치도",
    "iia": "인천국제공항공사",
    "iiac": "인천국제공항공사",
    "inan": "인천광역시",
    "jeju": "제주특별자치도",
    "jeonbuk": "전북특별자치도",
    "jn_gj": "전남광주통합특별시",
    "kdhc": "한국지역난방공사",
    "kepcoec": "한국전력기술",
    "kepri": "한국전력공사 전력연구원",
    "khnp": "한국수력원자력",
    "khs": "국가유산청",
    "knoc": "한국석유공사",
    "kogas": "한국가스공사",
    "korail": "한국철도공사",
    "koex": "한국도로공사",
    "kps": "한전KPS",
    "krc": "한국농어촌공사",
    "kwater": "한국수자원공사",
    "lh": "한국토지주택공사",
    "me": "환경부",
    "mois": "행정안전부",
    "mois_exec": "행정안전부",
    "molit": "국토교통부",
    "pps": "조달청",
    "sejong": "세종특별자치시",
    "seoul": "서울특별시",
    "ulsan": "울산광역시",
}

# 지방자치단체(나라장터/elis 수집) slug. source_kind 판정에 쓴다.
LOCAL_GOVT_SLUGS = frozenset(
    {
        "busan",
        "cb",
        "chungnam",
        "daegu",
        "daejeon",
        "gb",
        "gg",
        "gn",
        "gwd",
        "inan",
        "jeju",
        "jeonbuk",
        "jn_gj",
        "sejong",
        "seoul",
        "ulsan",
    }
)

# 파일명만으로는 실제 기관을 알 수 없는 두 건을 내용 기준으로 정정한다.
# 원래 파일명은 original_filename 으로 보존한다.
FILE_OVERRIDES: dict[str, dict[str, Any]] = {
    "한국도로공사 589792_0_한국도로공사)일반용역 적격심사 세부기준(23.07.31 시행).hwp": {
        "institution": "한국공항공사",
        "slug": "kac",
        "doc_title": "한국공항공사 일반용역 적격심사 세부기준",
        "doc_number": "지침 제653호",
        "effective_date": "2023-07-20",
    },
    "한전KPS 2.(예고)한전 일반용역 적격심사 세부기준 전문(제2차).hwp": {
        "institution": "한국전력공사",
        "slug": "kepco",
        "doc_title": "한국전력공사 일반용역 적격심사 세부기준 개정 예고안(제2차)",
        "doc_number": None,
        "effective_date": None,
    },
}

# 파일명·경로에서 기관명을 추론할 때 쓰는 키워드. 긴 키워드를 먼저 본다.
INSTITUTION_KEYWORDS: tuple[tuple[str, str, str], ...] = (
    ("한국지역난방공사", "kdhc", "한국지역난방공사"),
    ("인천국제공항공사", "iiac", "인천국제공항공사"),
    ("인천공항시설관리", "iiac_facility", "인천공항시설관리"),
    ("한국수력원자력", "khnp", "한국수력원자력"),
    ("한국농어촌공사", "ekr", "한국농어촌공사"),
    ("한국수자원공사", "kwater", "한국수자원공사"),
    ("한국토지주택공사", "lh", "한국토지주택공사"),
    ("한국전력공사", "kepco", "한국전력공사"),
    ("한국도로공사", "koex", "한국도로공사"),
    ("한국가스공사", "kogas", "한국가스공사"),
    ("한국철도공사", "korail", "한국철도공사"),
    ("한국석유공사", "knoc", "한국석유공사"),
    ("강원특별자치도", "gwd", "강원특별자치도"),
    ("전남광주통합특별시", "jn_gj", "전남광주통합특별시"),
    ("제주특별자치도", "jeju", "제주특별자치도"),
    ("세종특별자치시", "sejong", "세종특별자치시"),
    ("충청남도", "chungnam", "충청남도"),
    ("충청북도", "cb", "충청북도"),
    ("경상남도", "gn", "경상남도"),
    ("경상북도", "gb", "경상북도"),
    ("대구광역시", "daegu", "대구광역시"),
    ("인천광역시", "inan", "인천광역시"),
    ("국가유산청", "khs", "국가유산청"),
    ("방위사업청", "dapa", "방위사업청"),
    ("경기도", "gg", "경기도"),
    ("조달청", "pps", "조달청"),
    ("한전KPS", "kps", "한전KPS"),
)

# 영문 slug 접두어로 기관을 추론한다(추출 폴더의 ekr_full.txt, iia_17529_full.txt 등).
ENGLISH_SLUG_PREFIXES: tuple[tuple[str, str, str], ...] = (
    ("kepcoec", "kepcoec", "한국전력기술"),
    ("kepri", "kepri", "한국전력공사 전력연구원"),
    ("kwater", "kwater", "한국수자원공사"),
    ("korail", "korail", "한국철도공사"),
    ("khnp", "khnp", "한국수력원자력"),
    ("kdhc", "kdhc", "한국지역난방공사"),
    ("knoc", "knoc", "한국석유공사"),
    ("jngj", "jn_gj", "전남광주통합특별시"),
    ("ulsan", "ulsan", "울산광역시"),
    ("busan", "busan", "부산광역시"),
    ("daejeon", "daejeon", "대전광역시"),
    ("jeonbuk", "jeonbuk", "전북특별자치도"),
    ("chungnam", "chungnam", "충청남도"),
    ("mois", "mois", "행정안전부"),
    ("ekr", "ekr", "한국농어촌공사"),
    ("iia", "iia", "인천국제공항공사"),
    ("kogas", "kogas", "한국가스공사"),
    ("kps", "kps", "한전KPS"),
    ("lh", "lh", "한국토지주택공사"),
    ("gn", "gn", "경상남도"),
    ("gb", "gb", "경상북도"),
    ("gg", "gg", "경기도"),
    ("cb", "cb", "충청북도"),
    ("me", "me", "환경부"),
)

DOC_NUMBER_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"제\s*(\d{4})\s*[-\u2013]\s*(\d{1,5})\s*호"),
    re.compile(r"([가-힣]{2,10})\s*-\s*(\d{1,5})\s*호"),
    re.compile(r"제\s*(\d{1,5})\s*호"),
)

DATE_DOTTED = re.compile(r"(\d{4})\s*[.\-]\s*(\d{1,2})\s*[.\-]\s*(\d{1,2})")
DATE_SHORT = re.compile(r"(?:^|[^\d])(\d{2})\s*[.\-]\s*(\d{1,2})\s*[.\-]\s*(\d{1,2})")
DATE_COMPACT = re.compile(r"(\d{4})(\d{2})(\d{2})\s*시행")

URL_RE = re.compile(r"https?://[^\s`\"'<>)\]}]+")
FILENAME_TOKEN_RE = re.compile(r"[0-9A-Za-z가-힣][0-9A-Za-z가-힣_\-]*(?:\.[0-9A-Za-z가-힣_\-]+)+")
CODE_SPAN_RE = re.compile(r"`([^`\n]*)`")
NEW_PATH_RE = re.compile(r"^([a-z0-9_]+)/([0-9a-f]{12})_(.+)$")

UNSAFE_FILENAME = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def nfc(value: str) -> str:
    return unicodedata.normalize("NFC", value)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def clean_filename(name: str) -> str:
    cleaned = UNSAFE_FILENAME.sub("_", nfc(name)).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned or "unnamed"


def is_candidate(path: Path) -> bool:
    if any(part in EXCLUDED_DIR_PARTS for part in path.parts):
        return False
    if path.name in EXCLUDED_BASENAMES:
        return False
    suffix = path.suffix.lower()
    if suffix in EXCLUDED_SUFFIXES:
        return False
    return bool(suffix)


def detect_institution_keyword(text: str) -> tuple[str, str] | None:
    for keyword, slug, institution in INSTITUTION_KEYWORDS:
        if keyword in text:
            return slug, institution
    return None


def detect_english_prefix(filename: str) -> tuple[str, str] | None:
    lowered = filename.lower()
    for prefix, slug, institution in ENGLISH_SLUG_PREFIXES:
        if re.match(rf"^{re.escape(prefix)}(?:[_\-.]|$)", lowered):
            return slug, institution
    return None


def parse_doc_number(name: str) -> str | None:
    for pattern in DOC_NUMBER_PATTERNS:
        match = pattern.search(name)
        if match:
            groups = match.groups()
            if len(groups) == 2:
                head, tail = groups
                if head.isdigit():
                    return f"제{head}-{tail}호"
                return f"{head}-{tail}호"
            return f"제{groups[0]}호"
    return None


def _iso_date(year: int, month: int, day: int) -> str | None:
    if not (1900 <= year <= 2100 and 1 <= month <= 12 and 1 <= day <= 31):
        return None
    return f"{year:04d}-{month:02d}-{day:02d}"


def parse_effective_date(name: str) -> str | None:
    compact = DATE_COMPACT.search(name)
    if compact:
        return _iso_date(int(compact.group(1)), int(compact.group(2)), int(compact.group(3)))
    dotted = DATE_DOTTED.search(name)
    if dotted:
        return _iso_date(int(dotted.group(1)), int(dotted.group(2)), int(dotted.group(3)))
    short = DATE_SHORT.search(name)
    if short:
        return _iso_date(2000 + int(short.group(1)), int(short.group(2)), int(short.group(3)))
    return None


MAX_INFER_SOURCE_LEN = 120


def resolve_identity(
    rel_parts: tuple[str, ...], filename: str
) -> tuple[str, str | None, dict[str, Any]]:
    """(slug, institution, override_fields) 를 돌려준다."""
    override = FILE_OVERRIDES.get(nfc(filename))
    if override:
        return override["slug"], override["institution"], override

    if rel_parts and rel_parts[0] == "capsules" and len(rel_parts) >= 4:
        slug_token = nfc(rel_parts[2])
        if slug_token in SLUG_INSTITUTIONS:
            return slug_token, SLUG_INSTITUTIONS[slug_token], {}
        inferred = (
            detect_institution_keyword(nfc(filename))
            or detect_english_prefix(filename)
            or detect_institution_keyword(nfc("/".join(rel_parts[:3])))
        )
        if inferred:
            return inferred[0], inferred[1], {}
        return slug_token, None, {}

    if rel_parts and rel_parts[0] == "downloads":
        inferred = detect_institution_keyword(nfc("/".join(rel_parts))) or detect_english_prefix(
            filename
        )
        if inferred:
            return inferred[0], inferred[1], {}
        return "downloads", None, {}

    if rel_parts and rel_parts[0] == "session_20261006":
        if len(rel_parts) >= 2 and rel_parts[1] == "info21c":
            return "info21c", None, {}
        return "session_20261006", None, {}

    inferred = detect_institution_keyword(nfc("/".join(rel_parts))) or detect_english_prefix(
        filename
    )
    if inferred:
        return inferred[0], inferred[1], {}
    if len(rel_parts) >= 2 and rel_parts[0] == "capsules":
        return "misc", None, {}
    return (nfc(rel_parts[0]) if rel_parts else "misc"), None, {}


def source_kind_for(
    rel_parts: tuple[str, ...], filename: str, slug: str, is_extracted: bool
) -> str:
    if "info21c" in rel_parts:
        return "info21c"
    if rel_parts and rel_parts[0] == "downloads":
        return "user_download"
    if slug == "pps":
        return "law.go.kr"
    if slug == "supplement":
        return "g2b_attachment"
    if is_extracted:
        return "extracted_text"
    if slug in LOCAL_GOVT_SLUGS:
        return "elis"
    return "institution_site"


DOC_EXTENSIONS = ("hwp", "hwpx", "pdf", "odt", "docx", "xlsx", "bin")
EXTRACT_MARKERS = (".txt", ".html", ".xhtml", ".xml", ".tbl.txt")


def is_extracted_name(filename: str) -> bool:
    lowered = nfc(filename).lower()
    return lowered.endswith(EXTRACT_MARKERS)


def candidate_group(
    source_dir: Path,
) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for path in sorted(source_dir.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        if not is_candidate(path):
            continue
        rel = path.relative_to(source_dir)
        filename = nfc(path.name)
        sha = sha256_file(path)
        groups[sha].append(
            {
                "abs": path,
                "rel_parts": tuple(nfc(p) for p in rel.parts),
                "rel": "/".join(nfc(p) for p in rel.parts),
                "filename": filename,
                "dir": (nfc(str(rel.parent)) if str(rel.parent) != "." else ""),
            }
        )
    return groups


def representative_sort_key(candidate: dict[str, Any]) -> tuple[str, str, str]:
    return (candidate["rel_parts"][0], candidate["filename"], candidate["rel"])


def choose_representative(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    return sorted(candidates, key=representative_sort_key)[0]


def derived_from_sha(
    entry_candidate: dict[str, Any],
    siblings: list[dict[str, Any]],
    sha_by_rel: dict[str, str],
) -> str | None:
    if not is_extracted_name(entry_candidate["filename"]):
        return None
    base = entry_candidate["filename"]
    best: tuple[int, str] | None = None
    for sibling in siblings:
        if sibling["rel"] == entry_candidate["rel"]:
            continue
        name = sibling["filename"]
        if name.lower().endswith(tuple(f".{ext}" for ext in DOC_EXTENSIONS)) and base.startswith(
            name
        ):
            length = len(name)
            if best is None or length > best[0]:
                best = (length, sha_by_rel[sibling["rel"]])
    return best[1] if best else None


def scan_report_urls(docs_dir: Path, stems: set[str]) -> dict[str, str]:
    """보고서 표에서 파일 stem 과 같은 줄에 있는 단일 URL 을 출처로 채운다."""
    if not docs_dir.exists():
        return {}
    url_by_stem: dict[str, str] = {}
    for md in sorted(docs_dir.rglob("*.md")):
        try:
            text = md.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for line in text.splitlines():
            urls = URL_RE.findall(line)
            if len(urls) != 1:
                continue
            url = urls[0].rstrip(").,")
            for token in FILENAME_TOKEN_RE.findall(line):
                candidates = _stem_candidates(token)
                for stem in candidates:
                    if stem in stems and stem not in url_by_stem:
                        url_by_stem[stem] = url
                        break
    return url_by_stem


def _stem_candidates(token: str) -> list[str]:
    parts = token.split(".")
    out: list[str] = []
    for end in range(len(parts), 0, -1):
        out.append(".".join(parts[:end]))
    return out


def _split_line_ref(content: str) -> tuple[str, str]:
    match = re.search(r":\d+(?:[-,]\d+)*$", content)
    if match:
        return content[: match.start()], content[match.start() :]
    return content, ""


def rewrite_citations(
    docs_dir: Path,
    alias_index: dict[str, set[str]],
    name_index: dict[str, set[str]],
    slug_paths: dict[str, list[str]],
    sha_to_path: dict[str, str],
) -> tuple[dict[str, list[str]], list[dict[str, str]], list[dict[str, str]], list[dict[str, str]]]:
    """보고서 인용을 새 경로로 바꾸고 cited_by 를 모은다.

    반환: (cited_by, rewritten, skipped_ambiguous, unmatched)
    """
    cited_by: dict[str, set[str]] = defaultdict(set)
    rewritten: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []
    unmatched: list[dict[str, str]] = []
    if not docs_dir.exists():
        return {}, [], [], []

    for md in sorted(docs_dir.rglob("*.md")):
        try:
            text = md.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        try:
            report = str(md.relative_to(PROJECT_ROOT))
        except ValueError:
            report = str(md.relative_to(docs_dir))

        def replace(match: re.Match[str], report: str = report) -> str:
            content = match.group(1)
            prefix, rest = _citation_prefix(content)
            if prefix is None:
                return match.group(0)
            if prefix == NEW_CITATION_PREFIX:
                new_rel = rest
                parsed = NEW_PATH_RE.match(new_rel)
                if parsed and parsed.group(3):
                    sha = _sha_for_new_path(sha_to_path, parsed.group(1), parsed.group(2))
                    if sha:
                        cited_by[sha].add(report)
                return match.group(0)
            path_part, suffix = _split_line_ref(rest)
            if not path_part or "<" in path_part or "*" in path_part or "~" in path_part:
                unmatched.append(
                    {"report": report, "citation": content, "reason": "glob_or_placeholder"}
                )
                return match.group(0)
            if path_part.endswith("/") or "." not in path_part.rsplit("/", 1)[-1]:
                slug = path_part.strip("/").split("/")[0]
                if slug in slug_paths and path_part.strip("/") == slug:
                    new_path = NEW_CITATION_PREFIX + slug
                    for p in slug_paths[slug]:
                        sha = sha_to_path_reverse(sha_to_path, p)
                        if sha:
                            cited_by[sha].add(report)
                    rewritten.append({"report": report, "from": content, "to": new_path + suffix})
                    return f"`{new_path}{suffix}`"
                unmatched.append({"report": report, "citation": content, "reason": "directory"})
                return match.group(0)

            shas = alias_index.get(path_part)
            if shas is not None and len(shas) == 1:
                sha = next(iter(shas))
            elif shas is not None and len(shas) > 1:
                skipped.append({"report": report, "citation": content, "reason": "alias_ambiguous"})
                return match.group(0)
            else:
                basename = path_part.rsplit("/", 1)[-1]
                name_shas = name_index.get(basename)
                if name_shas is not None and len(name_shas) == 1:
                    sha = next(iter(name_shas))
                elif name_shas is not None and len(name_shas) > 1:
                    skipped.append(
                        {"report": report, "citation": content, "reason": "name_ambiguous"}
                    )
                    return match.group(0)
                else:
                    unmatched.append({"report": report, "citation": content, "reason": "not_found"})
                    return match.group(0)
            cited_by[sha].add(report)
            new_path = NEW_CITATION_PREFIX + sha_to_path[sha]
            rewritten.append({"report": report, "from": content, "to": new_path + suffix})
            return f"`{new_path}{suffix}`"

        new_text = CODE_SPAN_RE.sub(replace, text)
        if new_text != text:
            md.write_text(new_text, encoding="utf-8")

    return (
        {sha: sorted(reports) for sha, reports in cited_by.items()},
        rewritten,
        skipped,
        unmatched,
    )


def sha_to_path_reverse(sha_to_path: dict[str, str], path: str) -> str | None:
    for sha, p in sha_to_path.items():
        if p == path:
            return sha
    return None


def _sha_for_new_path(sha_to_path: dict[str, str], slug: str, sha12: str) -> str | None:
    for sha, path in sha_to_path.items():
        if sha.startswith(sha12) and path.startswith(f"{slug}/"):
            return sha
    return None


def _citation_prefix(content: str) -> tuple[str | None, str]:
    for prefix in (NEW_CITATION_PREFIX, "EXT/"):
        if content.startswith(prefix):
            return prefix, content[len(prefix) :]
    match = re.match(r"^\.orca/capsules/task_[0-9a-f]+/external/", content)
    if match:
        return match.group(0), content[match.end() :]
    return None, ""


def build_manifest(
    source_dir: Path, docs_dir: Path, output_dir: Path, copy_files: bool, rewrite_docs: bool
) -> dict[str, Any]:
    groups = candidate_group(source_dir)
    sha_by_rel: dict[str, str] = {}
    siblings_by_dir: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for sha, candidates in groups.items():
        for candidate in candidates:
            sha_by_rel[candidate["rel"]] = sha
            siblings_by_dir[candidate["dir"]].append(candidate)

    files_dir = output_dir / FILES_SUBDIR
    if copy_files and files_dir.exists():
        shutil.rmtree(files_dir)

    stems = {
        candidate["filename"].rsplit(".", 1)[0] for cands in groups.values() for candidate in cands
    }
    url_by_stem = scan_report_urls(docs_dir, stems)

    entries: list[dict[str, Any]] = []
    alias_index: dict[str, set[str]] = defaultdict(set)
    name_index: dict[str, set[str]] = defaultdict(set)
    slug_paths: dict[str, list[str]] = defaultdict(list)
    sha_to_path: dict[str, str] = {}

    for sha in sorted(groups):
        candidates = groups[sha]
        representative = choose_representative(candidates)
        slug, institution, override = resolve_identity(
            representative["rel_parts"], representative["filename"]
        )
        cleaned = clean_filename(representative["filename"])
        rel_new = f"{slug}/{sha[:12]}_{cleaned}"
        sha_to_path[sha] = rel_new
        slug_paths[slug].append(rel_new)

        stem = representative["filename"].rsplit(".", 1)[0]
        doc_number = override.get("doc_number") or parse_doc_number(representative["filename"])
        effective_date = override.get("effective_date") or parse_effective_date(
            representative["filename"]
        )
        doc_title = override.get("doc_title")
        source_url = url_by_stem.get(stem)
        is_extracted = is_extracted_name(representative["filename"])
        derived = derived_from_sha(
            representative, siblings_by_dir[representative["dir"]], sha_by_rel
        )

        if copy_files:
            dest = files_dir / rel_new
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(representative["abs"], dest)

        aliases = _aliases(representative, candidates)
        for alias in aliases:
            alias_index[alias].add(sha)
        name_index[representative["filename"]].add(sha)
        for candidate in candidates:
            name_index[candidate["filename"]].add(sha)

        entries.append(
            {
                "sha256": sha,
                "path": f"{FILES_SUBDIR}/{rel_new}",
                "original_filename": representative["filename"],
                "institution": institution,
                "doc_title": doc_title,
                "doc_number": doc_number,
                "effective_date": effective_date,
                "source_url": source_url,
                "source_kind": source_kind_for(
                    representative["rel_parts"], representative["filename"], slug, is_extracted
                ),
                "derived_from": derived,
                "cited_by": [],
                "first_seen": representative["rel"],
            }
        )

    entries.sort(key=lambda entry: entry["path"])

    cited_by: dict[str, list[str]] = {}
    citations_section: dict[str, Any] = {
        "rewritten": [],
        "skipped_ambiguous": [],
        "unmatched": [],
    }
    if rewrite_docs:
        cited_by, rewritten, skipped, unmatched = rewrite_citations(
            docs_dir, alias_index, name_index, slug_paths, sha_to_path
        )
        citations_section = {
            "rewritten": rewritten,
            "skipped_ambiguous": skipped,
            "unmatched": unmatched,
        }

    if cited_by:
        for entry in entries:
            entry["cited_by"] = cited_by.get(entry["sha256"], [])

    institutions = dict(sorted(SLUG_INSTITUTIONS.items()))
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "source_root": str(source_dir.relative_to(PROJECT_ROOT))
        if source_dir.is_relative_to(PROJECT_ROOT)
        else source_dir.name,
        "file_count": len(entries),
        "candidate_count": sum(len(c) for c in groups.values()),
        "institutions": institutions,
        "files": entries,
        "citations": citations_section,
    }
    return manifest


def _aliases(representative: dict[str, Any], candidates: list[dict[str, Any]]) -> set[str]:
    aliases: set[str] = set()
    for candidate in [representative, *candidates]:
        parts = candidate["rel_parts"]
        if parts and parts[0] == "capsules" and len(parts) >= 4:
            aliases.add("/".join(parts[3:]))
        if parts and parts[0] in {"downloads", "session_20261006"} and len(parts) >= 2:
            aliases.add("/".join(parts[1:]))
    return aliases


def write_readme(output_dir: Path, manifest: dict[str, Any]) -> None:
    files = manifest["files"]
    institutions = sorted({entry["institution"] for entry in files if entry["institution"]})
    lines = [
        "# 적격심사 근거 원문 수집 저장소",
        "",
        "> **경로**: `data/sources/qualification/`",
        "> **관리 스크립트**: `scripts/build_qualification_sources_manifest.py`",
        f"> **스키마**: `{MANIFEST_SCHEMA}`",
        "",
        "---",
        "",
        "## 1. 목적",
        "",
        "여러 Orca 태스크와 사용자 내려받기에 흩어져 있던 적격심사 근거 원문(HWP·HWPX·PDF),",
        "추출 텍스트·표를 sha256 기준으로 중복 제거해 한 곳에 모으고, 파일별 출처를 manifest 로 고정합니다.",
        "docs/analysis 보고서의 원문 인용은 이 저장소 경로를 가리킵니다.",
        "",
        "## 2. 구조",
        "",
        "| 경로 | 커밋 | 설명 |",
        "| --- | --- | --- |",
        "| `manifest.json` | 예 | 파일별 sha256·경로·출처·인용 보고서 목록 |",
        "| `README.md` | 예 | 이 문서 |",
        f"| `{FILES_SUBDIR}/<기관 slug>/<sha256 앞 12자>_<파일명>` | 아니오 | 원문·추출물 사본(gitignore) |",
        "",
        "원문 사본은 용량과 재배포 문제 때문에 커밋하지 않습니다. manifest 만 커밋하면",
        "어떤 파일이 있어야 하는지, 각 파일의 sha256 이 무엇인지 검증할 수 있습니다.",
        "",
        "## 3. 기관 slug",
        "",
        "| slug | 기관 |",
        "| --- | --- |",
    ]
    for slug, name in manifest["institutions"].items():
        lines.append(f"| `{slug}` | {name} |")
    lines += [
        "",
        "## 4. manifest 항목 필드",
        "",
        "| 필드 | 의미 |",
        "| --- | --- |",
        "| `sha256` | 파일 내용 해시. 중복 제거 기준이며 항목 간 유일합니다. |",
        "| `path` | `files/` 이하 상대 경로 |",
        "| `original_filename` | 수집 당시 파일명(오기 정정 전 이름도 보존) |",
        "| `institution` | 실제 내용 기준 기관명. 모르면 null |",
        "| `doc_title` | 문서 제목. 모르면 null |",
        "| `doc_number` | 예규·지침·공고 번호. 모르면 null |",
        "| `effective_date` | 시행일(YYYY-MM-DD). 모르면 null |",
        "| `source_url` | 출처 URL. 모르면 null |",
        "| `source_kind` | elis, law.go.kr, g2b_attachment, institution_site, user_download, info21c, extracted_text |",
        "| `derived_from` | 추출물이면 원본 sha256, 아니면 null |",
        "| `cited_by` | 이 파일을 인용하는 docs/analysis 보고서 경로 목록 |",
        "| `first_seen` | 이 내용이 처음 확인된 EXT_SRC 하위 상대 경로 |",
        "",
        "값을 알 수 없으면 추측하지 않고 null 로 둡니다.",
        "",
        "## 5. 기관명 정정 2건",
        "",
        "파일명과 실제 내용이 다른 두 건은 내용 기준으로 기관을 정정하고 원래 이름을 `original_filename` 에 보존했습니다.",
        "",
        "| original_filename | 정정 기관 | 근거 |",
        "| --- | --- | --- |",
        "| `한국도로공사 589792_0_한국도로공사)일반용역 적격심사 세부기준(23.07.31 시행).hwp` | 한국공항공사 | 지침 제653호, 2023-07-20 개정 |",
        "| `한전KPS 2.(예고)한전 일반용역 적격심사 세부기준 전문(제2차).hwp` | 한국전력공사 | 개정 예고안(제2차) |",
        "",
        "## 6. 재생성",
        "",
        "```sh",
        "uv run python scripts/build_qualification_sources_manifest.py",
        "```",
        "",
        "`EXT_SRC/` 를 입력으로 원문 배치, manifest 생성, 보고서 인용 갱신을 한 번에 수행합니다.",
        "같은 입력에 대해 결정적으로 같은 결과를 냅니다(타임스탬프·절대 경로 미포함).",
        "",
        "## 7. 현황",
        "",
        f"- 고유 파일 수: {manifest['file_count']}",
        f"- 수집 후보 파일 수(중복 포함): {manifest['candidate_count']}",
        f"- 기관 수: {len(institutions)}",
        "",
    ]
    (output_dir / README_FILENAME).write_text("\n".join(lines), encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="적격심사 근거 원문 manifest 생성 도구")
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--docs-dir", type=Path, default=DEFAULT_DOCS_DIR)
    parser.add_argument("--no-copy", action="store_true", help="원문 사본 배치를 건너뜁니다")
    parser.add_argument(
        "--no-rewrite-docs", action="store_true", help="보고서 인용 갱신을 건너뜁니다"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    source_dir = args.source_dir.resolve()
    output_dir = args.output_dir.resolve()
    docs_dir = args.docs_dir.resolve()
    if not source_dir.exists():
        print(f"[오류] 원문 소스 디렉터리가 없습니다: {source_dir}")
        return 1

    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = build_manifest(
        source_dir,
        docs_dir,
        output_dir,
        copy_files=not args.no_copy,
        rewrite_docs=not args.no_rewrite_docs,
    )
    manifest_file = output_dir / MANIFEST_FILENAME
    manifest_file.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    write_readme(output_dir, manifest)

    citations = manifest["citations"]
    print(
        f"적격심사 원문 수집 완료: 고유 {manifest['file_count']}개 "
        f"(후보 {manifest['candidate_count']}개) -> {output_dir}"
    )
    print(
        f"인용 갱신 {len(citations.get('rewritten', []))}건, "
        f"모호 {len(citations.get('skipped_ambiguous', []))}건, "
        f"미대응 {len(citations.get('unmatched', []))}건"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

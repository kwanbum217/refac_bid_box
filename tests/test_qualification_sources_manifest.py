"""적격심사 근거 원문 manifest 생성·배치·인용 갱신 계약 시험.

scripts/build_qualification_sources_manifest.py 를 작은 픽스처에 두 번 돌려
manifest 스키마, sha256 중복 제거, 경로 규칙, 기관명 정정 2건, 보고서 인용 갱신,
gitignore 규칙, 결정성을 확인합니다. 운영 DB 나 실제 EXT_SRC 를 건드리지 않습니다.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = PROJECT_ROOT / "scripts" / "build_qualification_sources_manifest.py"
MANIFEST_REL = Path("data") / "sources" / "qualification" / "manifest.json"

CORRECTION_ROAD = "한국도로공사 589792_0_한국도로공사)일반용역 적격심사 세부기준(23.07.31 시행).hwp"
CORRECTION_KPS = "한전KPS 2.(예고)한전 일반용역 적격심사 세부기준 전문(제2차).hwp"

REQUIRED_ENTRY_KEYS = {
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
}

PATH_RULE = re.compile(r"^files/[a-z0-9_]+/[0-9a-f]{12}_.+$")


def _write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _make_sources(source_dir: Path) -> None:
    # 같은 내용의 서로 다른 위치 사본 -> sha256 중복 제거 대상
    _write(source_dir / "capsules" / "task_aaaa00000001" / "seoul" / "seoul_general.hwp", b"HWP-A")
    _write(source_dir / "capsules" / "task_aaaa00000002" / "seoul" / "seoul_general.hwp", b"HWP-A")
    # 추출 텍스트(원본과 같은 폴더, 이름 접두 일치) -> derived_from
    _write(
        source_dir / "capsules" / "task_aaaa00000001" / "seoul" / "seoul_general.hwp.tbl.txt",
        b"TABLE-A",
    )
    # 인용 대상
    _write(source_dir / "capsules" / "task_aaaa00000001" / "pps" / "pps_2025_257.txt", b"PPS-TEXT")
    # 기관명 정정 2건
    downloads = source_dir / "downloads" / "적격심사_미수집_항목원문들"
    _write(downloads / CORRECTION_ROAD, b"KAC-CONTENT")
    _write(downloads / CORRECTION_KPS, b"KEPCO-CONTENT")
    # 제외 대상(실행 산출물)
    _write(source_dir / "capsules" / "task_aaaa00000001" / "dump.py", b"print(1)")
    _write(source_dir / "capsules" / "task_aaaa00000001" / ".DS_Store", b"junk")


def _make_docs(docs_dir: Path) -> None:
    docs_dir.mkdir(parents=True, exist_ok=True)
    (docs_dir / "sample.md").write_text(
        "\n".join(
            [
                "# 샘플 보고서",
                "",
                "- 원본: `EXT/seoul/seoul_general.hwp`",
                "- 표: `EXT/seoul/seoul_general.hwp.tbl.txt:31`",
                "- 조달청: `EXT/pps/pps_2025_257.txt:7`",
                "- 미대응: `.orca/capsules/task_aaaa00000001/external/nope/missing.hwp`",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _run(source_dir: Path, output_dir: Path, docs_dir: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        [
            sys.executable,
            str(SCRIPT),
            "--source-dir",
            str(source_dir),
            "--output-dir",
            str(output_dir),
            "--docs-dir",
            str(docs_dir),
        ],
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture
def built(tmp_path: Path) -> dict:
    workspace = tmp_path / "ws"
    source_dir = workspace / "src"
    docs_dir = workspace / "docs"
    output_dir = workspace / "out"
    _make_sources(source_dir)
    _make_docs(docs_dir)
    result = _run(source_dir, output_dir, docs_dir)
    assert result.returncode == 0, result.stderr
    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    return {
        "workspace": workspace,
        "source_dir": source_dir,
        "docs_dir": docs_dir,
        "output_dir": output_dir,
        "manifest": manifest,
    }


def test_manifest_schema_and_entry_keys(built: dict) -> None:
    manifest = built["manifest"]
    assert manifest["schema"] == "QUALIFICATION_SOURCES_MANIFEST_V1"
    assert isinstance(manifest["files"], list)
    assert manifest["files"]
    for entry in manifest["files"]:
        assert set(entry) == REQUIRED_ENTRY_KEYS
    paths = [entry["path"] for entry in manifest["files"]]
    assert paths == sorted(paths)


def test_sha256_unique_and_dedup(built: dict) -> None:
    files = built["manifest"]["files"]
    shas = [entry["sha256"] for entry in files]
    assert len(shas) == len(set(shas))
    # 같은 내용 사본 두 개는 한 항목으로 합쳐진다.
    seoul_hwp = [e for e in files if e["original_filename"] == "seoul_general.hwp"]
    assert len(seoul_hwp) == 1
    assert built["manifest"]["candidate_count"] > built["manifest"]["file_count"]


def test_path_rule(built: dict) -> None:
    for entry in built["manifest"]["files"]:
        assert PATH_RULE.match(entry["path"]), entry["path"]
        assert (built["output_dir"] / entry["path"]).is_file()


def test_institution_corrections(built: dict) -> None:
    by_name = {entry["original_filename"]: entry for entry in built["manifest"]["files"]}
    road = by_name[CORRECTION_ROAD]
    kps = by_name[CORRECTION_KPS]
    assert road["institution"] == "한국공항공사"
    assert road["doc_number"] == "지침 제653호"
    assert road["effective_date"] == "2023-07-20"
    assert road["path"].startswith("files/kac/")
    assert road["original_filename"] == CORRECTION_ROAD
    assert kps["institution"] == "한국전력공사"
    assert kps["path"].startswith("files/kepco/")
    # 파일명 오기(한국도로공사·한전KPS)를 기관명으로 쓰지 않는다.
    assert road["institution"] != "한국도로공사"
    assert kps["institution"] != "한전KPS"


def test_derived_from_links_extracted(built: dict) -> None:
    by_name = {entry["original_filename"]: entry for entry in built["manifest"]["files"]}
    source = by_name["seoul_general.hwp"]
    extracted = by_name["seoul_general.hwp.tbl.txt"]
    assert extracted["derived_from"] == source["sha256"]
    assert source["derived_from"] is None


def test_citations_rewritten_and_line_refs_preserved(built: dict) -> None:
    text = (built["docs_dir"] / "sample.md").read_text(encoding="utf-8")
    files = built["manifest"]["files"]
    by_name = {entry["original_filename"]: entry["path"] for entry in files}
    assert "EXT/seoul/" not in text
    assert "EXT/pps/" not in text
    assert f"data/sources/qualification/{by_name['seoul_general.hwp']}" in text
    assert ":31`" in text  # 행 번호 보존
    assert ":7`" in text
    # 미대응 인용은 그대로 남고 보고서 목록에 남는다.
    assert "external/nope/missing.hwp" in text
    unmatched = built["manifest"]["citations"]["unmatched"]
    assert any("missing.hwp" in item["citation"] for item in unmatched)


def test_cited_by_recorded(built: dict) -> None:
    by_name = {entry["original_filename"]: entry for entry in built["manifest"]["files"]}
    assert "sample.md" in by_name["seoul_general.hwp"]["cited_by"]


def test_gitignore_rule_files_ignored_manifest_tracked() -> None:
    files_cmd = [
        "git",
        "-C",
        str(PROJECT_ROOT),
        "check-ignore",
        "-q",
        "data/sources/qualification/files/inan/000000000000_x.hwp",
    ]
    manifest_cmd = [
        "git",
        "-C",
        str(PROJECT_ROOT),
        "check-ignore",
        "-q",
        "data/sources/qualification/manifest.json",
    ]
    on_files = subprocess.run(files_cmd, check=False)  # noqa: S603
    on_manifest = subprocess.run(manifest_cmd, check=False)  # noqa: S603
    if on_files.returncode not in (0, 1):
        pytest.skip("git 저장소가 아니라 check-ignore 를 쓸 수 없습니다.")
    assert on_files.returncode == 0, "files/ 하위가 무시되지 않습니다."
    assert on_manifest.returncode == 1, "manifest.json 이 무시되면 안 됩니다."


def test_script_is_deterministic(tmp_path: Path) -> None:
    manifests = []
    for tag in ("a", "b"):
        workspace = tmp_path / tag
        source_dir = workspace / "src"
        docs_dir = workspace / "docs"
        output_dir = workspace / "out"
        _make_sources(source_dir)
        _make_docs(docs_dir)
        result = _run(source_dir, output_dir, docs_dir)
        assert result.returncode == 0, result.stderr
        manifests.append((output_dir / "manifest.json").read_bytes())
    assert manifests[0] == manifests[1]

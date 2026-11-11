"""tests/test_fixture_manifest_split_20261111.py

fixture 별 evidence manifest 경로 분리 규칙을 검증합니다.

검증 항목:
1. v2 fixture 는 v2 manifest 경로, v1 은 기존 manifest 경로를 기본으로 쓴다
2. --output / --manifest-path 명시가 fixture 기본 경로보다 우선한다
3. v2 fixture 를 v2 manifest 로 검증하면 근거 ID 누락이 0건이다
4. 생성기 기본 출력이 fixture 에 맞는 경로다
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from scripts import build_llm_fixture_manifest, validate_llm_quality_fixture
from scripts.build_llm_fixture_manifest import (
    DEFAULT_MANIFEST_PATH,
    V2_MANIFEST_PATH,
    build_manifest_file,
    manifest_path_for_fixture,
)
from scripts.validate_llm_quality_fixture import validate_file

V2_FIXTURE_NAME = "llm_quality_fixture_v2.json"
V1_FIXTURE_NAME = "llm_quality_fixture_v1.json"
EV_ID = "bid_10015927"


def _write_fixture(path: Path) -> None:
    item = {
        "id": "q01",
        "question": "질문",
        "context_sufficient": True,
        "expected_evidence_ids": [EV_ID],
        "expected_facts": ["사실"],
        "forbidden_literals": ["Servc", "Thng", "Cnstwk", "Frgcpt"],
        "semantic_forbidden_claims": ["자기모순된 비교를 하지 않는다"],
        "citation_required": True,
        "refusal_expected": False,
        "numeric_tolerance": None,
        "scoring_rubric": "정답 기준",
    }
    path.write_text(json.dumps({"items": [item]}, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_manifest(path: Path, evidence_ids: list[str]) -> None:
    entries = []
    for ev_id in evidence_ids:
        doc = f"문서 {ev_id}"
        digest = hashlib.sha256(doc.encode("utf-8")).hexdigest()
        entries.append(
            {
                "evidence_id": ev_id,
                "content_hash": f"sha256:{digest}",
                "doc_length": len(doc),
            }
        )
    payload = {
        "schema_version": "1.0.0",
        "created_at": "2026-11-11T00:00:00Z",
        "collection_name": "bidding_kb",
        "total_collection_documents": len(entries),
        "item_count": len(entries),
        "entries": entries,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _create_mock_chroma(db_path: Path, records: list[tuple[str, str]]) -> None:
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute("CREATE TABLE collections (id TEXT PRIMARY KEY, name TEXT)")
    cur.execute("INSERT INTO collections (id, name) VALUES ('col_001', 'bidding_kb')")
    cur.execute(
        "CREATE TABLE segments (id TEXT PRIMARY KEY, type TEXT, scope TEXT, collection TEXT)"
    )
    cur.execute(
        "INSERT INTO segments (id, type, scope, collection) VALUES ('seg_001', 'vector', 'VECTOR', 'col_001')"
    )
    cur.execute(
        "CREATE TABLE embeddings (id TEXT PRIMARY KEY, segment_id TEXT, embedding_id TEXT, seq_id INTEGER, created_at TEXT)"
    )
    cur.execute(
        "CREATE TABLE embedding_metadata (id TEXT, key TEXT, string_value TEXT, int_value INTEGER, float_value REAL, bool_value INTEGER)"
    )
    for idx, (ev_id, doc) in enumerate(records, start=1):
        emb_uuid = f"emb_uuid_{idx:04d}"
        cur.execute(
            "INSERT INTO embeddings (id, segment_id, embedding_id, seq_id, created_at) VALUES (?, 'seg_001', ?, ?, '2026-11-11T00:00:00Z')",
            (emb_uuid, ev_id, idx),
        )
        cur.execute(
            "INSERT INTO embedding_metadata (id, key, string_value, int_value, float_value, bool_value) VALUES (?, 'chroma:document', ?, NULL, NULL, NULL)",
            (emb_uuid, doc),
        )
    conn.commit()
    conn.close()


@pytest.fixture(autouse=True)
def mock_kb_existence(monkeypatch):
    monkeypatch.setattr(
        validate_llm_quality_fixture,
        "verify_evidence_ids_in_kb",
        lambda *a, **kw: (True, [], "로컬 ChromaDB 대조 완료"),
    )


def test_manifest_path_follows_fixture():
    """v2 fixture 는 v2 manifest, v1 과 그 밖은 기존 manifest 경로를 쓴다."""
    assert manifest_path_for_fixture(Path("data/eval") / V2_FIXTURE_NAME) == V2_MANIFEST_PATH
    assert manifest_path_for_fixture(Path("data/eval") / V1_FIXTURE_NAME) == DEFAULT_MANIFEST_PATH
    assert manifest_path_for_fixture(Path("tmp") / "fixture.json") == DEFAULT_MANIFEST_PATH


def test_v2_fixture_validates_against_v2_manifest_without_missing_ids(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """v2 fixture 를 기본 v2 manifest 로 검증하면 근거 ID 누락이 0건이다."""
    data_dir = tmp_path / "data" / "eval"
    data_dir.mkdir(parents=True)
    fixture_path = data_dir / V2_FIXTURE_NAME
    _write_fixture(fixture_path)
    _write_manifest(data_dir / V2_MANIFEST_PATH.name, [EV_ID])
    monkeypatch.chdir(tmp_path)

    relative_fixture = Path("data/eval") / V2_FIXTURE_NAME
    assert validate_file(relative_fixture, min_context_sufficient=1, quiet=True) == 0

    is_valid, errors, stats = validate_llm_quality_fixture.validate_fixture_data(
        json.loads(relative_fixture.read_text(encoding="utf-8")),
        min_context_sufficient=1,
        manifest_path=manifest_path_for_fixture(relative_fixture),
        check_kb_existence=True,
    )
    assert is_valid is True, f"검증 오류: {errors}"
    assert "대조 완료" in stats["manifest_verification_status"]
    assert "누락" not in stats["manifest_verification_status"]


def test_explicit_manifest_path_overrides_fixture_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """--manifest-path 를 명시하면 fixture 기본 manifest 경로보다 우선한다."""
    data_dir = tmp_path / "data" / "eval"
    data_dir.mkdir(parents=True)
    _write_fixture(data_dir / V2_FIXTURE_NAME)
    explicit_manifest = tmp_path / "explicit_manifest.json"
    _write_manifest(explicit_manifest, [EV_ID])
    monkeypatch.chdir(tmp_path)

    assert not (data_dir / V2_MANIFEST_PATH.name).exists()
    ret = validate_llm_quality_fixture.main(
        [
            str(Path("data/eval") / V2_FIXTURE_NAME),
            "--manifest-path",
            str(explicit_manifest),
            "--min-context-sufficient",
            "1",
            "--quiet",
        ]
    )
    assert ret == 0


def test_explicit_output_overrides_fixture_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """생성기의 --output 명시가 fixture 기본 출력 경로보다 우선한다."""
    mock_db = tmp_path / "chroma.sqlite3"
    _create_mock_chroma(mock_db, [(EV_ID, "문서 본문")])
    data_dir = tmp_path / "data" / "eval"
    data_dir.mkdir(parents=True)
    _write_fixture(data_dir / V2_FIXTURE_NAME)
    explicit_output = tmp_path / "explicit_manifest.json"
    monkeypatch.chdir(tmp_path)

    code = build_manifest_file(
        fixture_path=Path("data/eval") / V2_FIXTURE_NAME,
        output_path=explicit_output,
        chroma_db_path=mock_db,
        quiet=True,
    )
    assert code == 0
    assert explicit_output.is_file()
    assert not (data_dir / V2_MANIFEST_PATH.name).exists()


def test_build_default_output_follows_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """생성기 기본 출력이 fixture 파일명에 맞는 manifest 경로다."""
    mock_db = tmp_path / "chroma.sqlite3"
    _create_mock_chroma(mock_db, [(EV_ID, "문서 본문")])
    data_dir = tmp_path / "data" / "eval"
    data_dir.mkdir(parents=True)
    _write_fixture(data_dir / V2_FIXTURE_NAME)
    _write_fixture(data_dir / V1_FIXTURE_NAME)
    monkeypatch.chdir(tmp_path)

    v2_code = build_manifest_file(
        fixture_path=Path("data/eval") / V2_FIXTURE_NAME,
        chroma_db_path=mock_db,
        quiet=True,
    )
    assert v2_code == 0
    assert (data_dir / V2_MANIFEST_PATH.name).is_file()
    assert not (data_dir / DEFAULT_MANIFEST_PATH.name).exists()

    v1_code = build_manifest_file(
        fixture_path=Path("data/eval") / V1_FIXTURE_NAME,
        chroma_db_path=mock_db,
        quiet=True,
    )
    assert v1_code == 0
    assert (data_dir / DEFAULT_MANIFEST_PATH.name).is_file()


def test_validator_reuses_generator_rule():
    """경로 규칙은 생성기 모듈 한 곳에만 정의되고 검증기가 그것을 재사용한다."""
    assert (
        validate_llm_quality_fixture.manifest_path_for_fixture
        is build_llm_fixture_manifest.manifest_path_for_fixture
    )

"""
scripts/build_llm_fixture_manifest.py

LLM 품질 평가 fixture (data/eval/llm_quality_fixture_v1.json) 가 참조하는
지식베이스 근거 ID 들의 경량 evidence manifest 생성기.

표준 라이브러리만을 사용하여 ChromaDB SQLite 데이터베이스로부터 fixture 의
expected_evidence_ids 에 해당하는 문서의 해시(SHA-256)와 컬렉션 메타데이터를 추출하고,
data/eval/llm_quality_evidence_manifest.json 파일을 생성합니다.

ChromaDB 스키마:
- collections(id, name)
- segments(id, type, scope, collection)
- embeddings(id, segment_id, embedding_id, seq_id, created_at)
- embedding_metadata(id, key, string_value, int_value, float_value, bool_value)
  (문서 본문은 key = 'chroma:document' 인 행의 string_value)

규약:
- 종료 코드 0: manifest 생성 성공
- 종료 코드 1: ChromaDB 미존재 / 필수 근거 ID 누락 / 부분 생성 방지 실패
- 종료 코드 2: fixture 파일 미존재 또는 JSON 파싱 오류
- ChromaDB 가 없거나 ID 가 누락된 경우 빈 파일이나 부분 manifest 를 일절 생성하지 않습니다 (fail-closed).
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_FIXTURE_PATH = Path("data/eval/llm_quality_fixture_v1.json")
DEFAULT_MANIFEST_PATH = Path("data/eval/llm_quality_evidence_manifest.json")
DEFAULT_COLLECTION_NAME = "bidding_kb"
MANIFEST_SCHEMA_VERSION = "1.0.0"
CHROMA_DOCUMENT_KEY = "chroma:document"


def find_chroma_sqlite_path(custom_path: str | Path | None = None) -> Path | None:
    """ChromaDB sqlite 파일 경로를 탐색합니다 (표준 라이브러리 전용)."""
    if custom_path:
        cand = Path(custom_path)
        if cand.is_dir():
            cand = cand / "chroma.sqlite3"
        if cand.exists() and cand.is_file() and cand.stat().st_size > 0:
            return cand
        return None

    # 1. .env 파일 파싱
    env_path = Path(".env")
    if env_path.exists():
        try:
            for line in env_path.read_text(encoding="utf-8").splitlines():
                if line.startswith("CHROMA_DB_PATH="):
                    val = line.split("=", 1)[1].strip().strip('"').strip("'")
                    cand = Path(val) / "chroma.sqlite3"
                    if cand.exists() and cand.stat().st_size > 1000:
                        return cand
        except OSError:
            pass

    # 2. 환경변수 확인
    env_var = os.environ.get("CHROMA_DB_PATH")
    if env_var:
        cand = Path(env_var) / "chroma.sqlite3"
        if cand.exists() and cand.stat().st_size > 1000:
            return cand

    # 3. 로컬 및 알려진 상대 경로 탐색
    repo_root = Path(__file__).resolve().parent.parent
    for rel_cand in [
        Path("chroma_db/chroma.sqlite3"),
        Path("../chroma_db/chroma.sqlite3"),
        repo_root / "chroma_db" / "chroma.sqlite3",
    ]:
        if rel_cand.exists() and rel_cand.stat().st_size > 1000:
            return rel_cand

    return None


def extract_required_evidence_ids(fixture_data: Any) -> set[str]:
    """fixture 데이터로부터 고유한 expected_evidence_ids 집합을 추출합니다."""
    if isinstance(fixture_data, dict):
        items = fixture_data.get("items", [])
    elif isinstance(fixture_data, list):
        items = fixture_data
    else:
        items = []

    evidence_ids: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        for ev_id in item.get("expected_evidence_ids") or []:
            if isinstance(ev_id, str) and ev_id.strip():
                evidence_ids.add(ev_id.strip())

    return evidence_ids


def query_evidence_manifest_from_sqlite(
    db_path: Path,
    collection_name: str,
    required_ids: set[str],
) -> tuple[bool, dict[str, Any] | None, str]:
    """ChromaDB SQLite 에서 required_ids 를 배치 조회하여 manifest 딕셔너리를 생성합니다.

    Returns:
        (success, manifest_dict_or_none, message)
    """
    if not db_path.exists() or not db_path.is_file():
        return False, None, f"ChromaDB SQLite 파일이 존재하지 않습니다: {db_path}"

    try:
        conn = sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True)
    except Exception:
        try:
            conn = sqlite3.connect(str(db_path))
        except Exception as exc:
            return False, None, f"ChromaDB SQLite 연결 실패: {exc}"

    try:
        cur = conn.cursor()

        # 1. 컬렉션 존재 여부 확인
        cur.execute("SELECT id FROM collections WHERE name = ? LIMIT 1", (collection_name,))
        row = cur.fetchone()
        if not row:
            conn.close()
            return False, None, f"ChromaDB 컬렉션 '{collection_name}' 을(를) 찾을 수 없습니다."

        # 2. 컬렉션 내 총 문서 수 집계 (조인 기반 정밀 집계)
        cur.execute(
            """
            SELECT count(DISTINCT e.id)
            FROM embeddings e
            JOIN segments s ON s.id = e.segment_id
            JOIN collections col ON col.id = s.collection
            JOIN embedding_metadata em ON em.id = e.id AND em.key = ?
            WHERE col.name = ?
            """,
            (CHROMA_DOCUMENT_KEY, collection_name),
        )
        count_row = cur.fetchone()
        total_docs = count_row[0] if count_row else 0

        # 3. 필요한 evidence ID 목록을 일괄(batch) IN 절로 조회
        required_ids_list = sorted(required_ids)
        placeholders = ", ".join("?" for _ in required_ids_list)
        batch_query = (
            f"SELECT e.embedding_id, em.string_value "  # noqa: S608
            f"FROM embeddings e "
            f"JOIN segments s ON s.id = e.segment_id "
            f"JOIN collections col ON col.id = s.collection "
            f"JOIN embedding_metadata em ON em.id = e.id AND em.key = ? "
            f"WHERE col.name = ? AND e.embedding_id IN ({placeholders})"  # nosec B608
        )
        query_params = [CHROMA_DOCUMENT_KEY, collection_name, *required_ids_list]
        cur.execute(batch_query, query_params)
        rows = cur.fetchall()
        conn.close()

        found_docs: dict[str, str] = {}
        for row in rows:
            emb_id = str(row[0])
            doc_str = str(row[1]) if row[1] is not None else ""
            found_docs[emb_id] = doc_str

        missing_ids = [ev_id for ev_id in required_ids_list if ev_id not in found_docs]
        if missing_ids:
            return (
                False,
                None,
                f"ChromaDB 컬렉션('{collection_name}')에 다음 expected_evidence_ids 가 누락되었습니다: {missing_ids}",
            )

        entries = []
        for ev_id in required_ids_list:
            doc_str = found_docs[ev_id]
            digest = hashlib.sha256(doc_str.encode("utf-8")).hexdigest()
            entries.append(
                {
                    "evidence_id": ev_id,
                    "content_hash": f"sha256:{digest}",
                    "doc_length": len(doc_str),
                }
            )

        manifest = {
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "created_at": datetime.now(UTC).isoformat(),
            "collection_name": collection_name,
            "total_collection_documents": total_docs,
            "item_count": len(entries),
            "entries": entries,
        }
        return True, manifest, f"성공 ({len(entries)}건의 근거 ID 추출 완료)"

    except Exception as exc:
        with contextlib.suppress(Exception):
            conn.close()
        return False, None, f"ChromaDB SQLite 조회 중 오류 발생: {exc}"


def build_manifest_file(
    fixture_path: Path | str = DEFAULT_FIXTURE_PATH,
    output_path: Path | str = DEFAULT_MANIFEST_PATH,
    chroma_db_path: Path | str | None = None,
    collection_name: str = DEFAULT_COLLECTION_NAME,
    quiet: bool = False,
) -> int:
    """fixture 로부터 근거 ID 목록을 읽고 ChromaDB 에서 manifest 를 생성하여 저장합니다."""
    fpath = Path(fixture_path)
    if not fpath.exists() or not fpath.is_file():
        if not quiet:
            print(f"오류: fixture 파일 '{fpath}' 을(를) 찾을 수 없습니다.", file=sys.stderr)
        return 2

    try:
        fixture_data = json.loads(fpath.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        if not quiet:
            print(f"오류: fixture 파일 '{fpath}' 파싱 실패 ({exc})", file=sys.stderr)
        return 2

    required_ids = extract_required_evidence_ids(fixture_data)
    if not required_ids:
        if not quiet:
            print(
                f"오류: fixture 파일 '{fpath}' 에 expected_evidence_ids 가 정의되어 있지 않습니다.",
                file=sys.stderr,
            )
        return 1

    db_path = find_chroma_sqlite_path(chroma_db_path)
    if not db_path:
        if not quiet:
            print(
                "오류: ChromaDB SQLite 데이터베이스를 찾을 수 없습니다. (manifest 생성 불가, fail-closed)",
                file=sys.stderr,
            )
        return 1

    success, manifest_dict, message = query_evidence_manifest_from_sqlite(
        db_path=db_path,
        collection_name=collection_name,
        required_ids=required_ids,
    )

    if not success or manifest_dict is None:
        if not quiet:
            print(
                f"오류: manifest 생성 실패 ({message}). 부분 manifest 를 쓰지 않습니다.",
                file=sys.stderr,
            )
        return 1

    out_path = Path(output_path)
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        # 임시 파일 작성 후 원자적 교체
        temp_out = out_path.with_name(f".tmp_{out_path.name}")
        content = json.dumps(manifest_dict, ensure_ascii=False, indent=2) + "\n"
        temp_out.write_text(content, encoding="utf-8")
        temp_out.replace(out_path)
    except OSError as exc:
        if not quiet:
            print(f"오류: manifest 파일 '{out_path}' 쓰기 실패 ({exc})", file=sys.stderr)
        return 1

    if not quiet:
        print(f"[PASS] LLM 품질 fixture evidence manifest 생성 완료: {out_path}")
        print(f"  - 컬렉션: {manifest_dict['collection_name']}")
        print(f"  - 전체 문서 수: {manifest_dict['total_collection_documents']}")
        print(f"  - 추출 근거 ID 수: {manifest_dict['item_count']}")

    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="LLM 품질 평가 fixture 근거 ID 경량 evidence manifest 생성기"
    )
    parser.add_argument(
        "--fixture",
        default=str(DEFAULT_FIXTURE_PATH),
        help=f"입력 fixture JSON 파일 경로 (기본값: {DEFAULT_FIXTURE_PATH})",
    )
    parser.add_argument(
        "--output",
        default=str(DEFAULT_MANIFEST_PATH),
        help=f"출력 manifest JSON 파일 경로 (기본값: {DEFAULT_MANIFEST_PATH})",
    )
    parser.add_argument(
        "--chroma-db-path",
        default=None,
        help="ChromaDB 디렉터리 또는 chroma.sqlite3 파일 경로 (미지정 시 자동 탐색)",
    )
    parser.add_argument(
        "--collection",
        default=DEFAULT_COLLECTION_NAME,
        help=f"조회할 ChromaDB 컬렉션 이름 (기본값: {DEFAULT_COLLECTION_NAME})",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="정상 생성 시 출력을 억제합니다 (종료 코드 0 유지).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    return build_manifest_file(
        fixture_path=args.fixture,
        output_path=args.output,
        chroma_db_path=args.chroma_db_path,
        collection_name=args.collection,
        quiet=args.quiet,
    )


if __name__ == "__main__":
    sys.exit(main())

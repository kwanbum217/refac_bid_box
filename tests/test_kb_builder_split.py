"""
tests/test_kb_builder_split.py

src/app/services/kb_builder.py 분할 및 심볼 재수출 검증 테스트.
kb_builder.py 에서 재수출하는 심볼들이 누락되거나 분할된 모듈과 어긋나면 깨지도록 구성합니다.
"""

from __future__ import annotations

import ast
from pathlib import Path


def test_reexported_symbols_from_kb_builder():
    """kb_builder.py 에서 이동된 6개 심볼이 올바르게 재수출되는지 검증합니다.

    kb_builder.py 에서 재수출을 제거하면 이 테스트가 즉시 깨집니다.
    """
    import src.app.services.kb_builder as kb_builder_module
    import src.app.services.kb_document_builder as kb_doc_module

    moved_symbols = [
        "_max_documents",
        "_resolve_announcements",
        "_resolve_delta_announcements",
        "_join_key",
        "_build_announcement_document",
        "_build_result_document",
    ]

    for sym in moved_symbols:
        assert hasattr(kb_builder_module, sym), f"kb_builder.py 에 {sym} 재수출 누락"
        assert hasattr(kb_doc_module, sym), f"kb_document_builder.py 에 {sym} 정의 누락"
        assert getattr(kb_builder_module, sym) is getattr(kb_doc_module, sym)


def test_retained_symbols_in_kb_builder():
    """kb_builder.py 에 필수 유지 심볼 및 상수가 그대로 남아 있는지 검증합니다."""
    import src.app.services.kb_builder as kb_builder_module

    retained_symbols = [
        "_flush",
        "_load_existing_index",
        "_document_hash",
        "_read_existing_index_value",
        "_diff_index",
        "_upsert_kb_status",
        "rebuild_knowledge_base",
        "_sync",
        "get_kb_document_count",
        "DOC_FORMAT_VERSION",
        "INDEX_LOOKUP_BATCH_SIZE",
        "INDEX_LOOKUP_RETRY_DELAY_SECONDS",
        "DEFAULT_MAX_DOCUMENTS",
        "COLLECTION_NAME",
        "INDEX_BATCH_SIZE",
        "INDEX_LOOKUP_MAX_ATTEMPTS",
        "MAX_REMOVAL_RATIO",
    ]

    for sym in retained_symbols:
        assert hasattr(kb_builder_module, sym), f"kb_builder.py 에 {sym} 유지 누락"


def test_no_circular_dependency():
    """kb_document_builder.py 가 kb_builder 를 import 하지 않는지 AST 로 검증합니다."""
    doc_builder_path = Path("src/app/services/kb_document_builder.py")
    tree = ast.parse(doc_builder_path.read_text(encoding="utf-8"))

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert "kb_builder" not in alias.name, (
                    "kb_document_builder 가 kb_builder 를 import 하면 안 됩니다"
                )
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert "kb_builder" not in node.module, (
                "kb_document_builder 가 kb_builder 를 import 하면 안 됩니다"
            )


def test_line_counts():
    """kb_builder.py 와 kb_document_builder.py 가 각각 500줄 미만인지 검증합니다."""
    services_dir = Path("src/app/services")
    for filename in ["kb_builder.py", "kb_document_builder.py"]:
        file_path = services_dir / filename
        assert file_path.exists(), f"{filename} 파일이 존재하지 않습니다"
        line_count = len(file_path.read_text(encoding="utf-8").splitlines())
        assert line_count < 500, f"{filename} 은 500줄 미만이어야 합니다 (현재: {line_count}줄)"


def test_document_builder_functions():
    """kb_document_builder 모듈의 기능이 정상 동작하는지 기본 검증합니다."""
    from src.app.models.bids import BidAnnouncement, BidResult
    from src.app.services.kb_document_builder import (
        _build_announcement_document,
        _build_result_document,
        _join_key,
        _max_documents,
    )

    # _max_documents
    assert _max_documents() >= 500_000

    # _join_key
    ann = BidAnnouncement(
        id=1,
        bid_ntce_no="20260101001",
        bid_ntce_ord="00",
        bid_ntce_nm="테스트 공고",
        category="Servc",
    )
    result = BidResult(
        id=1,
        bid_ntce_no="20260101001",
        bid_ntce_ord="000",
        category="Servc",
        bidwinnr_nm="낙찰업체",
        sucsf_bid_amt=1000000,
        sucsf_bid_rate=88.5,
    )
    assert _join_key(ann) == _join_key(result)

    # _build_announcement_document
    doc = _build_announcement_document(ann, result)
    assert "[공고명] 테스트 공고" in doc
    assert "[낙찰업체] 낙찰업체" in doc

    # _build_result_document
    res_doc = _build_result_document(result)
    assert "[낙찰공고번호] 20260101001-000" in res_doc
    assert "[낙찰업체] 낙찰업체" in res_doc

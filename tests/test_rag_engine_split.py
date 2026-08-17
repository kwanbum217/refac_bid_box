"""
tests/test_rag_engine_split.py

src/rag/engine.py 분할 후 재수출 심볼 동일성(object identity) 검증 테스트.
신규 모듈(query_planning, snapshots, answer_format)의 심볼과
engine.py에서 재수출된 심볼이 동일한 객체인지 단정합니다.
"""

import inspect

import src.rag.answer_format as answer_format
import src.rag.engine as engine
import src.rag.query_planning as query_planning
import src.rag.snapshots as snapshots


def test_query_planning_symbol_identity():
    symbols = [
        "is_result_list_query",
        "extract_result_limit",
        "_month_end",
        "_parse_year_month_window",
        "_parse_time_window",
        "build_retrieval_plan",
        "STATISTICS_KEYWORDS",
        "SEMANTIC_KEYWORDS",
        "KB_KEYWORDS",
        "CATEGORY_KEYWORDS",
        "REGION_KEYWORDS",
        "TREND_KEYWORDS",
        "RESULT_QUERY_MARKERS",
        "RESULT_LIST_MARKERS",
        "_normalize_text",
        "_category_label",
        "_query_lower",
    ]
    for symbol in symbols:
        engine_obj = getattr(engine, symbol)
        module_obj = getattr(query_planning, symbol)
        assert engine_obj is module_obj, (
            f"심볼 {symbol}의 객체 동일성 검증 실패 (engine vs query_planning)"
        )


def test_snapshots_symbol_identity():
    symbols = [
        "_extract_statistical_snapshot",
        "_extract_semantic_snapshot",
        "_extract_kb_snapshot",
        "_extract_trend_snapshot",
    ]
    for symbol in symbols:
        engine_obj = getattr(engine, symbol)
        module_obj = getattr(snapshots, symbol)
        assert engine_obj is module_obj, (
            f"심볼 {symbol}의 객체 동일성 검증 실패 (engine vs snapshots)"
        )


def test_answer_format_symbol_identity():
    symbols = [
        "_markdown_result_cell",
        "_format_result_amount",
        "_format_result_rate",
        "_build_result_list_answer",
        "_compose_context_text",
        "_build_source_citation_from_context",
        "_fallback_answer",
        "_build_evidence_items",
        "_format_filters_for_prompt",
        "_normalize_category_wording",
    ]
    for symbol in symbols:
        engine_obj = getattr(engine, symbol)
        module_obj = getattr(answer_format, symbol)
        assert engine_obj is module_obj, (
            f"심볼 {symbol}의 객체 동일성 검증 실패 (engine vs answer_format)"
        )


def test_no_circular_imports_in_new_modules():
    """신규 3개 모듈이 engine.py를 역참조(순환 import)하지 않는지 검증합니다."""
    for mod in (query_planning, snapshots, answer_format):
        source = inspect.getsource(mod)
        assert "from src.rag.engine" not in source
        assert "import src.rag.engine" not in source
        assert "from .engine" not in source

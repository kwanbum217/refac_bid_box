"""
tests/test_planner_split.py

planner.py 기계적 분할(planner_intent_signals.py, planner_llm_draft.py) 정합성 검증 테스트.
- 모듈별 심볼 위치 및 재수출 검증
- 순환 참조 부재 검증
- 신규 모듈의 독립 실행 검증
"""

import sys


def test_planner_reexports_all_symbols():
    import src.app.services.planner as planner
    import src.app.services.planner_intent_signals as signals
    import src.app.services.planner_llm_draft as llm_draft

    moved_signals = [
        "_extract_bid_query_params",
        "_extract_followup_region",
        "_extract_followup_category",
        "_has_prediction_action_intent",
        "_has_collection_command",
        "_has_collection_context_only",
        "_is_model_validation_request",
        "_is_bid_price_prediction_request",
        "_extract_prediction_model_id",
        "_extract_prediction_limit",
        "_select_action",
        "_has_kb_refresh_intent",
    ]
    for sym in moved_signals:
        assert hasattr(signals, sym), f"signals missing {sym}"
        assert hasattr(planner, sym), f"planner re-export missing {sym}"

    moved_llm = [
        "LLM_PLAN_DRAFT_ENV",
        "_attempt_llm_plan_draft",
        "_llm_plan_draft_enabled",
        "_should_try_llm_plan_draft",
        "_llm_system_instruction",
        "_request_llm_plan_draft",
        "_validate_llm_plan_draft",
    ]
    for sym in moved_llm:
        assert hasattr(llm_draft, sym), f"llm_draft missing {sym}"
        assert hasattr(planner, sym), f"planner re-export missing {sym}"


def test_no_circular_imports():
    # 신규 모듈이 planner 를 직접 import 하지 않는지 확인
    import src.app.services.planner_intent_signals as signals
    import src.app.services.planner_llm_draft as llm_draft

    assert "src.app.services.planner" not in sys.modules or not hasattr(signals, "plan_chat_request")
    assert not hasattr(signals, "plan_chat_request")
    assert not hasattr(signals, "interpret_request")
    assert not hasattr(llm_draft, "plan_chat_request")
    assert not hasattr(llm_draft, "interpret_request")


def test_line_count_limits():
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    planner_lines = len((root / "src/app/services/planner.py").read_text().splitlines())
    signals_lines = len(
        (root / "src/app/services/planner_intent_signals.py").read_text().splitlines()
    )
    llm_lines = len((root / "src/app/services/planner_llm_draft.py").read_text().splitlines())

    assert planner_lines <= 700, f"planner.py line count ({planner_lines}) exceeds 700"
    assert signals_lines <= 350, f"planner_intent_signals.py line count ({signals_lines}) exceeds 350"
    assert llm_lines <= 350, f"planner_llm_draft.py line count ({llm_lines}) exceeds 350"

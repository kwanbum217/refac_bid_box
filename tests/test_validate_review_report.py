from __future__ import annotations

import json
from pathlib import Path

from scripts.validate_review_report import evaluate, main, parse_checklist

CAPSULE = """schema: ORCA_TASK_CAPSULE_V2
review_checklist:
  - id: "C1"
    question: "모든 subprocess.run 호출에 timeout 인자가 있는가"
    how: "호출 수와 timeout 출현 수를 비교"
    defect_when: "no"
  - id: "C2"
    question: "정규식이 여러 줄을 넘어 매칭될 수 있는가"
    how: "반례 입력으로 재현"
    defect_when: "yes"

allowed_read_files:
  - "x.py"
"""


def _report(**over: object) -> dict:
    base = {
        "schema": "ORCA_REVIEW_DONE_V2",
        "verdict": "fail",
        "checklist_results": [
            {"id": "C1", "answer": "no", "evidence": "x.py:10 timeout 0회"},
            {"id": "C2", "answer": "no", "evidence": "x.py:14 줄바꿈 미포함"},
        ],
        "blocking_issues": [{"id": "C1", "file": "x.py:10", "description": "timeout 누락"}],
    }
    base.update(over)
    return base


def test_parse_checklist_reads_id_and_polarity():
    items = parse_checklist(CAPSULE)
    assert [i["id"] for i in items] == ["C1", "C2"]
    assert items[0]["defect_when"] == "no"
    assert items[1]["defect_when"] == "yes"


def test_parse_checklist_absent_returns_empty():
    assert parse_checklist("schema: X\nallowed_read_files: []\n") == []


def test_contract_satisfied():
    """결함 1건이 blocking_issues 에 id 와 함께 있으면 만족입니다."""
    res = evaluate(parse_checklist(CAPSULE), _report())
    assert res["ok"], res["violations"]
    assert res["defect_ids"] == ["C1"]
    assert res["effective_verdict"] == "fail"


def test_condition1_missing_result():
    rep = _report(checklist_results=[{"id": "C1", "answer": "no", "evidence": "x"}])
    res = evaluate(parse_checklist(CAPSULE), rep)
    assert not res["ok"]
    assert any("조건1" in v and "C2" in v for v in res["violations"])


def test_condition2_missing_evidence():
    rep = _report(
        checklist_results=[
            {"id": "C1", "answer": "no", "evidence": ""},
            {"id": "C2", "answer": "no", "evidence": "ok"},
        ]
    )
    res = evaluate(parse_checklist(CAPSULE), rep)
    assert not res["ok"]
    assert any("조건2" in v and "evidence" in v for v in res["violations"])


def test_condition2_unreadable_answer():
    rep = _report(
        checklist_results=[
            {"id": "C1", "answer": "아마도", "evidence": "x"},
            {"id": "C2", "answer": "no", "evidence": "y"},
        ]
    )
    res = evaluate(parse_checklist(CAPSULE), rep)
    assert not res["ok"]
    assert any("조건2" in v and "yes/no" in v for v in res["violations"])


def test_condition3_defect_not_in_blocking():
    """감도 시험에서 실제로 발생한 위반입니다."""
    res = evaluate(parse_checklist(CAPSULE), _report(blocking_issues=[]))
    assert not res["ok"]
    assert any("조건3 위반" in v and "C1" in v for v in res["violations"])


def test_condition3_needs_polarity():
    """defect_when 이 없으면 조용히 통과하지 않고 판정 불가로 막습니다."""
    capsule = CAPSULE.replace('    defect_when: "no"\n', "")
    res = evaluate(parse_checklist(capsule), _report())
    assert not res["ok"]
    assert any("판정 불가" in v and "C1" in v for v in res["violations"])


def test_condition4_pass_with_empty_results_is_degraded():
    rep = _report(verdict="pass", checklist_results=[], blocking_issues=[])
    res = evaluate(parse_checklist(CAPSULE), rep)
    assert res["effective_verdict"] == "insufficient_context"
    assert not res["ok"]


def test_condition4_pass_with_defect_is_corrected_to_fail():
    """결함을 확인했는데 pass 를 선언하면 실효 판정을 fail 로 정정합니다."""
    res = evaluate(parse_checklist(CAPSULE), _report(verdict="pass"))
    assert res["effective_verdict"] == "fail"
    assert not res["ok"]


def test_main_exit_codes(tmp_path: Path):
    cap = tmp_path / "capsule.yaml"
    cap.write_text(CAPSULE, encoding="utf-8")
    rep = tmp_path / "report.json"

    rep.write_text(json.dumps(_report(), ensure_ascii=False), encoding="utf-8")
    assert main(["--capsule", str(cap), "--report", str(rep)]) == 0

    rep.write_text(json.dumps(_report(blocking_issues=[]), ensure_ascii=False), encoding="utf-8")
    assert main(["--capsule", str(cap), "--report", str(rep)]) == 1

    assert main(["--capsule", str(cap), "--report", str(tmp_path / "nope.json")]) == 2

    rep.write_text("{invalid", encoding="utf-8")
    assert main(["--capsule", str(cap), "--report", str(rep)]) == 2


def test_evaluate_rejects_prefix_id_matching():
    """결함 5: C10 이 blocking_issues 에 있어도 C1 요구가 충족되지 않습니다."""
    checklist = [{"id": "C1", "defect_when": "yes"}]
    report = {
        "checklist_results": [{"id": "C1", "answer": "yes", "evidence": "e"}],
        "blocking_issues": ["C10"],
        "verdict": "fail",
    }
    res = evaluate(checklist, report)
    assert not res["ok"]
    assert any("조건3 위반" in v and "C1" in v for v in res["violations"])


def test_parse_checklist_folded_scalar():
    """결함 6: YAML folded scalar (>)로 작성된 question 을 문장으로 파싱합니다."""
    capsule = (
        'review_checklist:\n  - id: "C1"\n    question: >\n      abc def\n    defect_when: "yes"\n'
    )
    items = parse_checklist(capsule)
    assert len(items) == 1
    assert items[0]["id"] == "C1"
    assert items[0]["question"] == "abc def"
    assert items[0]["defect_when"] == "yes"

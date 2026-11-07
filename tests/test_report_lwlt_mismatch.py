"""낙찰하한율 불일치 진단 지표 시험 (DB 없이).

(1) 순수 계산 함수: 소수 3자리 비교, 비교 불가 처리, 규칙 ID별 최소 불일치 필터와
    차이값 상위 3개 분포를 고정합니다.
(2) 지표 정합: 커밋된 data/reference/lwlt_mismatch_metrics.yaml 의 schema·합계와
    by_rule 항목 조건을 확인합니다.
(3) argparse 옵션과 --check 종료 코드(같으면 0, 다르면 1)를 확인합니다.

DB·.env 를 쓰지 않습니다. 전량 시험은 -m 'not data_assets' 로 돌립니다.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml

from scripts import report_lwlt_mismatch as metric_script

METRICS_PATH = Path(metric_script.DEFAULT_OUTPUT)


def _sample(
    rule_id: str = "R",
    edition: str = "2026-01-01",
    scope: str = metric_script.SCOPE_ALL,
    notice: str | None = None,
    rule: str | None = None,
    declared: str | None = None,
) -> metric_script.RateSample:
    return metric_script.RateSample(
        rule_id=rule_id,
        edition=edition,
        scope=scope,
        notice_rate=Decimal(notice) if notice is not None else None,
        rule_rate=Decimal(rule) if rule is not None else None,
        declared_rate=Decimal(declared if declared is not None else rule)
        if (declared is not None or rule is not None)
        else None,
    )


# --------------------------------------------------------------------------- #
# (1) 소수 3자리 비교
# --------------------------------------------------------------------------- #


def test_compare_uses_three_decimal_places() -> None:
    assert metric_script.classify(_sample(notice="80.4954", rule="80.495")) == metric_script.MATCH
    assert (
        metric_script.classify(_sample(notice="80.4964", rule="80.495")) == metric_script.MISMATCH
    )
    assert metric_script.rate_diff(_sample(notice="82.495", rule="80.495")) == Decimal("2.000")
    assert metric_script.rate_diff(_sample(notice="80.4949", rule="80.495")) == Decimal("0.000")


def test_compare_excludes_missing_or_nonpositive_notice() -> None:
    assert metric_script.classify(_sample(notice=None, rule="80.495")) == (
        metric_script.NOT_COMPARABLE
    )
    assert metric_script.classify(_sample(notice="0", rule="80.495")) == (
        metric_script.NOT_COMPARABLE
    )
    assert metric_script.classify(_sample(notice="-1", rule="80.495")) == (
        metric_script.NOT_COMPARABLE
    )
    assert metric_script.classify(_sample(notice="80.495", rule=None)) == (
        metric_script.NOT_COMPARABLE
    )


def test_rule_rate_prefers_printed_band_and_falls_back_to_declared() -> None:
    banded = SimpleNamespace(
        price_bands=(
            SimpleNamespace(
                upper_bound=Decimal("500000000"), lwlt_rate=Decimal("82.495"), label="5억원 미만"
            ),
        ),
        lwlt_rate=Decimal("80.495"),
    )
    assert metric_script.rule_lwlt_rate(banded, Decimal("100000000")) == Decimal("82.495")

    plain = SimpleNamespace(price_bands=None, lwlt_rate=Decimal("80.495"))
    assert metric_script.rule_lwlt_rate(plain, None) == Decimal("80.495")


# --------------------------------------------------------------------------- #
# (1) 집계
# --------------------------------------------------------------------------- #


def test_build_metrics_totals_and_scopes_are_consistent() -> None:
    samples = [
        _sample("R_A", scope=metric_script.SCOPE_REGION, notice="82.495", rule="80.495"),
        _sample("R_A", scope=metric_script.SCOPE_REGION, notice="80.495", rule="80.495"),
        _sample("R_B", scope=metric_script.SCOPE_ALL, notice="86.245", rule="86.245"),
        _sample("R_C", scope=metric_script.SCOPE_INSTITUTION, notice="80.495", rule=None),
    ]
    metrics = metric_script.build_metrics(
        samples, window={"from": "2025-11-07", "to": "2026-11-07"}, generated_at="2026-11-07"
    )

    assert metrics["schema"] == metric_script.SCHEMA
    assert metrics["generated_by"] == metric_script.GENERATED_BY
    totals = metrics["totals"]
    assert totals == {
        "rule_applied": 4,
        "compared": 3,
        "match": 2,
        "mismatch": 1,
        "mismatch_ratio": round(1 / 3, 6),
    }
    assert set(metrics["by_scope"]) == set(metric_script.SCOPES)
    assert sum(item["rule_applied"] for item in metrics["by_scope"].values()) == 4
    assert metrics["by_scope"][metric_script.SCOPE_INSTITUTION]["compared"] == 0
    assert metrics["by_scope"][metric_script.SCOPE_INSTITUTION]["mismatch_ratio"] == 0.0


def test_by_rule_drops_rules_below_minimum_mismatch() -> None:
    samples = [_sample("R_BIG", notice="82.0", rule="80.0") for _ in range(5)]
    samples += [_sample("R_SMALL", notice="82.0", rule="80.0") for _ in range(4)]
    samples += [_sample("R_MATCH", notice="80.0", rule="80.0") for _ in range(9)]

    metrics = metric_script.build_metrics(
        samples, window={"from": "x", "to": "y"}, generated_at="2026-11-07"
    )

    assert set(metrics["by_rule"]) == {"R_BIG"}
    entry = metrics["by_rule"]["R_BIG"]
    assert entry["rule_applied"] == 5
    assert entry["compared"] == 5
    assert entry["match"] == 0
    assert entry["mismatch"] == 5
    assert entry["mismatch_ratio"] == 1.0
    assert entry["top_diffs"] == [{"diff": 2.0, "count": 5}]


def test_by_rule_keeps_top_three_diffs_by_count() -> None:
    samples: list[metric_script.RateSample] = []
    for diff, count in (("1.0", 5), ("2.0", 4), ("3.0", 3), ("4.0", 2), ("5.0", 1)):
        samples += [
            _sample("R", notice=str(Decimal("80") + Decimal(diff)), rule="80") for _ in range(count)
        ]

    metrics = metric_script.build_metrics(
        samples, window={"from": "x", "to": "y"}, generated_at="2026-11-07"
    )

    entry = metrics["by_rule"]["R"]
    assert entry["mismatch"] == 15
    assert [item["diff"] for item in entry["top_diffs"]] == [1.0, 2.0, 3.0]
    assert [item["count"] for item in entry["top_diffs"]] == [5, 4, 3]


def test_by_rule_carries_edition_scope_and_declared_rate() -> None:
    samples = [
        _sample(
            "R_A",
            edition="2023-03-02",
            scope=metric_script.SCOPE_REGION,
            notice="82.495",
            rule="80.495",
            declared="85.495",
        )
        for _ in range(5)
    ]
    metrics = metric_script.build_metrics(
        samples, window={"from": "x", "to": "y"}, generated_at="2026-11-07"
    )
    entry = metrics["by_rule"]["R_A"]
    assert entry["edition"] == "2023-03-02"
    assert entry["scope"] == metric_script.SCOPE_REGION
    assert entry["declared_rate"] == "85.495"


# --------------------------------------------------------------------------- #
# (3) argparse 와 --check
# --------------------------------------------------------------------------- #


def test_parse_args_defaults() -> None:
    args = metric_script.parse_args([])
    assert args.months == 12
    assert args.category == "Servc"
    assert args.method_code == ""
    assert args.min_rule_mismatch == metric_script.MIN_RULE_MISMATCH
    assert args.output == metric_script.DEFAULT_OUTPUT
    assert args.check is False


def test_parse_args_accepts_out_alias() -> None:
    args = metric_script.parse_args(["--out", "tmp/metrics.yaml", "--check"])
    assert args.output == "tmp/metrics.yaml"
    assert args.check is True


def test_check_returns_one_when_metrics_change(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    samples = [_sample("R", notice="82.0", rule="80.0") for _ in range(5)]
    monkeypatch.setattr(metric_script, "collect_samples", lambda **kwargs: samples)

    output = tmp_path / "metrics.yaml"
    assert metric_script.main(["--check", "--output", str(output)]) == 1
    assert not output.exists()

    assert metric_script.main(["--output", str(output)]) == 0
    written = output.read_text(encoding="utf-8")
    assert metric_script.main(["--check", "--output", str(output)]) == 0
    assert output.read_text(encoding="utf-8") == written

    changed = samples + [_sample("R2", notice="82.0", rule="80.0") for _ in range(5)]
    monkeypatch.setattr(metric_script, "collect_samples", lambda **kwargs: changed)
    assert metric_script.main(["--check", "--output", str(output)]) == 1


def test_diff_metrics_ignores_generated_at_and_window() -> None:
    left: dict[str, Any] = {
        "generated_at": "2026-01-01",
        "window": {"from": "2025-01-01", "to": "2026-01-01"},
        "totals": {"mismatch": 1},
    }
    right: dict[str, Any] = {
        "generated_at": "2026-11-07",
        "window": {"from": "2025-11-07", "to": "2026-11-07"},
        "totals": {"mismatch": 2},
    }
    assert metric_script.diff_metrics(left, right) == [("totals.mismatch", 1, 2)]


# --------------------------------------------------------------------------- #
# (2) 커밋된 지표 정합
# --------------------------------------------------------------------------- #


def _metrics() -> dict[str, Any]:
    return yaml.safe_load(METRICS_PATH.read_text(encoding="utf-8"))


def test_committed_metrics_schema_and_totals() -> None:
    metrics = _metrics()
    assert metrics["schema"] == metric_script.SCHEMA
    assert metrics["generated_by"] == metric_script.GENERATED_BY
    assert set(metrics["window"]) == {"from", "to"}

    totals = metrics["totals"]
    assert set(totals) == {"rule_applied", "compared", "match", "mismatch", "mismatch_ratio"}
    assert totals["compared"] == totals["match"] + totals["mismatch"]
    assert totals["rule_applied"] >= totals["compared"]
    expected_ratio = (
        round(totals["mismatch"] / totals["compared"], 6) if totals["compared"] else 0.0
    )
    assert totals["mismatch_ratio"] == expected_ratio

    assert set(metrics["by_scope"]) == set(metric_script.SCOPES)
    for scope in metric_script.SCOPES:
        summary = metrics["by_scope"][scope]
        assert summary["compared"] == summary["match"] + summary["mismatch"]
        assert summary["rule_applied"] >= summary["compared"]
    assert (
        sum(summary["rule_applied"] for summary in metrics["by_scope"].values())
        == totals["rule_applied"]
    )
    assert (
        sum(summary["compared"] for summary in metrics["by_scope"].values()) == totals["compared"]
    )
    assert (
        sum(summary["mismatch"] for summary in metrics["by_scope"].values()) == totals["mismatch"]
    )


def test_committed_metrics_by_rule_entries() -> None:
    metrics = _metrics()
    assert metrics["by_rule"]

    for rule_id, entry in metrics["by_rule"].items():
        assert entry["rule_id"] == rule_id
        assert entry["edition"]
        assert entry["scope"] in metric_script.SCOPES
        assert entry["compared"] == entry["match"] + entry["mismatch"]
        assert entry["mismatch"] >= metric_script.MIN_RULE_MISMATCH
        assert entry["mismatch_ratio"] == round(entry["mismatch"] / entry["compared"], 6)
        assert 0 < len(entry["top_diffs"]) <= metric_script.TOP_DIFF_LIMIT
        counts = [item["count"] for item in entry["top_diffs"]]
        assert counts == sorted(counts, reverse=True)
        assert sum(counts) <= entry["mismatch"]

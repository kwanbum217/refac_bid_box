"""원장 생성기 기준일(--as-of) 시험.

DB 에 연결하지 않습니다. 수집 함수를 monkeypatch 로 바꿔 main 이 어떤 날짜를
넘기는지만 단언합니다. 점검(--check)은 원장을 만든 날과 같은 창으로 다시
계산해야 날짜가 바뀌었다는 이유만으로 차이가 나지 않습니다.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pytest
import yaml

from scripts import report_lwlt_mismatch as metric_script
from scripts import report_rule_coverage as ledger_script


def _capture_today(monkeypatch: pytest.MonkeyPatch, module: Any, name: str) -> list[date]:
    """수집 함수 호출을 가로채 넘어온 today 를 모읍니다."""
    seen: list[date] = []

    def fake(**kwargs: Any) -> Any:
        seen.append(kwargs["today"])
        return ledger_script.CollectedRecords() if module is ledger_script else []

    monkeypatch.setattr(module, name, fake)
    return seen


@pytest.fixture
def ledger_stubs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        ledger_script, "load_registry_index", lambda *a, **k: ledger_script.RegistryIndex()
    )
    monkeypatch.setattr(ledger_script, "load_manifest_sources", lambda *a, **k: {})


def _write_ledger_row(output: Path, window_to: str) -> None:
    output.write_text(
        yaml.safe_dump({"filter": {"window_to": window_to}, "totals": {}}, sort_keys=False),
        encoding="utf-8",
    )


def _write_metrics_row(output: Path, window_to: str) -> None:
    output.write_text(
        yaml.safe_dump({"window": {"to": window_to}, "totals": {}}, sort_keys=False),
        encoding="utf-8",
    )


def test_coverage_as_of_overrides(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, ledger_stubs: None
) -> None:
    seen = _capture_today(monkeypatch, ledger_script, "collect_records")
    output = tmp_path / "ledger.yaml"

    assert ledger_script.main(["--as-of", "2026-11-11", "--output", str(output)]) == 0

    assert seen == [date(2026, 11, 11)]
    assert yaml.safe_load(output.read_text(encoding="utf-8"))["filter"]["window_to"] == "2026-11-11"


def test_coverage_check_uses_saved_window_end(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, ledger_stubs: None
) -> None:
    seen = _capture_today(monkeypatch, ledger_script, "collect_records")
    output = tmp_path / "ledger.yaml"
    _write_ledger_row(output, "2026-11-11")

    ledger_script.main(["--check", "--output", str(output)])

    assert seen == [date(2026, 11, 11)]


def test_coverage_check_prefers_as_of(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, ledger_stubs: None
) -> None:
    seen = _capture_today(monkeypatch, ledger_script, "collect_records")
    output = tmp_path / "ledger.yaml"
    _write_ledger_row(output, "2026-11-11")

    ledger_script.main(["--check", "--as-of", "2026-10-01", "--output", str(output)])

    assert seen == [date(2026, 10, 1)]


def test_coverage_regeneration_defaults_to_today(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, ledger_stubs: None
) -> None:
    seen = _capture_today(monkeypatch, ledger_script, "collect_records")
    output = tmp_path / "ledger.yaml"
    _write_ledger_row(output, "2026-11-11")

    ledger_script.main(["--output", str(output)])

    assert seen == [date.today()]


def test_coverage_check_without_saved_window_uses_today(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, ledger_stubs: None
) -> None:
    seen = _capture_today(monkeypatch, ledger_script, "collect_records")

    ledger_script.main(["--check", "--output", str(tmp_path / "missing.yaml")])

    assert seen == [date.today()]


def test_lwlt_as_of_overrides(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    seen = _capture_today(monkeypatch, metric_script, "collect_samples")
    output = tmp_path / "metrics.yaml"

    assert metric_script.main(["--as-of", "2026-11-11", "--output", str(output)]) == 0

    assert seen == [date(2026, 11, 11)]
    assert yaml.safe_load(output.read_text(encoding="utf-8"))["window"]["to"] == "2026-11-11"


def test_lwlt_check_uses_saved_window_end(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    seen = _capture_today(monkeypatch, metric_script, "collect_samples")
    output = tmp_path / "metrics.yaml"
    _write_metrics_row(output, "2026-11-11")

    metric_script.main(["--check", "--output", str(output)])

    assert seen == [date(2026, 11, 11)]


def test_lwlt_check_prefers_as_of(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    seen = _capture_today(monkeypatch, metric_script, "collect_samples")
    output = tmp_path / "metrics.yaml"
    _write_metrics_row(output, "2026-11-11")

    metric_script.main(["--check", "--as-of", "2026-10-01", "--output", str(output)])

    assert seen == [date(2026, 10, 1)]


def test_lwlt_regeneration_defaults_to_today(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen = _capture_today(monkeypatch, metric_script, "collect_samples")
    output = tmp_path / "metrics.yaml"
    _write_metrics_row(output, "2026-11-11")

    metric_script.main(["--output", str(output)])

    assert seen == [date.today()]


def test_lwlt_check_without_saved_window_uses_today(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen = _capture_today(monkeypatch, metric_script, "collect_samples")

    metric_script.main(["--check", "--output", str(tmp_path / "missing.yaml")])

    assert seen == [date.today()]


@pytest.mark.parametrize("module", [ledger_script, metric_script])
def test_invalid_as_of_is_rejected(module: Any, tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as excinfo:
        module.main(["--as-of", "2026-13-01", "--output", str(tmp_path / "out.yaml")])

    assert excinfo.value.code == 2

"""scripts/generate_drift_baseline.py 단위 테스트 (DB 없이 동작).

검증 항목 (코디네이터 확정 계약):
- dry-run 이 어떤 파일도 쓰지 않는다.
- 표본 부족 시 기록하지 않고 실패로 끝난다 (fail-closed).
- --start-at 없이 --write 를 거부한다.
- 원자적 교체가 중간 실패에서 기존 baseline 을 보존한다.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pandas as pd

gen = importlib.import_module("scripts.generate_drift_baseline")


class _DummySession:
    def close(self) -> None:
        return None


def _record_row(idx: int) -> dict:
    return {
        "presumed_price": 100_000_000.0,
        "base_amount": 99_000_000.0,
        "openg_dt": "2026-06-01",
        "lwlt_rate": 88.0 if idx % 2 == 0 else None,
        "inst_hist_rate": 0.92,
        "inst_sample_cnt": 50.0,
        "inst_ewm_rate": 0.92,
        "is_repeat": 0.0,
        "repeat_cnt": 0.0,
        "repeat_hist_rate": 0.88,
        "repeat_prev_rate": 0.88,
        "repeat_hist_std": 0.0,
        "repeat_days_since": 999.0,
        "srvce_div_nm": "일반용역",
    }


def _patch_dataset(monkeypatch, n_rows: int, calls: list) -> None:
    def _fake_build(session, category_code, output_dir="data/feature_store", **kwargs):
        calls.append({"category_code": category_code, **kwargs})
        return pd.DataFrame([_record_row(i) for i in range(n_rows)])

    monkeypatch.setattr(gen, "build_training_dataset", _fake_build)
    monkeypatch.setattr(gen, "SessionLocal", lambda: _DummySession())
    monkeypatch.setattr(gen, "attach_institution_history", lambda df: df)
    monkeypatch.setattr(gen, "attach_repeat_history", lambda df: df)


def _registry_files(registry: Path) -> list[Path]:
    if not registry.exists():
        return []
    return [p for p in registry.rglob("*") if p.is_file()]


def test_dry_run_writes_nothing(tmp_path, monkeypatch):
    """dry-run(기본값)은 어떤 파일도 쓰지 않고 구간·행 수·특징 수·경로만 출력합니다."""
    calls: list = []
    _patch_dataset(monkeypatch, 240, calls)
    registry = tmp_path / "reg"

    rc = gen.main(
        [
            "--category",
            "Servc",
            "--start-at",
            "2026-05-26",
            "--baseline-version",
            "b_dry_001",
            "--registry-dir",
            str(registry),
        ]
    )

    assert rc == 0
    assert len(calls) == 1
    assert calls[0]["persist"] is False
    assert calls[0]["start_at"] == "2026-05-26"
    assert _registry_files(registry) == []


def test_write_without_start_at_rejected(tmp_path, monkeypatch):
    """--start-at 없이 --write 는 거부됩니다 (전체 이력 baseline 실수 방지)."""
    calls: list = []
    _patch_dataset(monkeypatch, 240, calls)
    registry = tmp_path / "reg"

    rc = gen.main(
        [
            "--category",
            "Servc",
            "--baseline-version",
            "b_reject_001",
            "--registry-dir",
            str(registry),
            "--write",
        ]
    )

    assert rc == 2
    assert calls == []
    assert _registry_files(registry) == []


def test_insufficient_samples_not_written(tmp_path, monkeypatch):
    """표본이 최소 기준 미만이면 --write 여도 기록하지 않고 실패로 끝납니다."""
    calls: list = []
    _patch_dataset(monkeypatch, 5, calls)
    registry = tmp_path / "reg"

    rc = gen.main(
        [
            "--category",
            "Servc",
            "--start-at",
            "2026-05-26",
            "--baseline-version",
            "b_small_001",
            "--registry-dir",
            str(registry),
            "--write",
        ]
    )

    assert rc == 1
    assert calls[0]["persist"] is False
    assert _registry_files(registry) == []


def test_atomic_replace_preserves_existing_on_failure(tmp_path, monkeypatch):
    """교체 중간 실패에서 기존 baseline 이 보존되고 staging 잔재가 남지 않습니다."""
    import src.ml.trainer as trainer_mod

    calls: list = []
    _patch_dataset(monkeypatch, 240, calls)
    registry = tmp_path / "reg"
    model_name = gen.resolve_model_name("Servc", None)
    target = registry / model_name / "baseline"
    target.mkdir(parents=True)
    old_dist = target / "feature_distributions_v1.json"
    old_meta = target / "metadata.json"
    old_dist.write_text('{"marker": "old-baseline"}', encoding="utf-8")
    old_meta.write_text('{"marker": "old-meta"}', encoding="utf-8")

    real_move = trainer_mod.shutil.move
    failed_once = {"done": False}

    def _flaky_move(src, dst, *args, **kwargs):
        if not failed_once["done"] and Path(dst) == target and Path(src) != target:
            failed_once["done"] = True
            raise RuntimeError("교체 중간 강제 실패")
        return real_move(src, dst, *args, **kwargs)

    monkeypatch.setattr(trainer_mod.shutil, "move", _flaky_move)

    rc = gen.main(
        [
            "--category",
            "Servc",
            "--start-at",
            "2026-05-26",
            "--baseline-version",
            "b_atomic_001",
            "--registry-dir",
            str(registry),
            "--write",
        ]
    )

    assert rc == 1
    assert failed_once["done"] is True
    assert old_dist.read_text(encoding="utf-8") == '{"marker": "old-baseline"}'
    assert old_meta.read_text(encoding="utf-8") == '{"marker": "old-meta"}'
    residue = list((registry / model_name).glob(".baseline_*"))
    assert residue == []
    assert calls[0]["persist"] is False

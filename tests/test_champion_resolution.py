"""
tests/test_champion_resolution.py

재학습이 무엇을 champion 으로 삼는지 검증.

2026-08-06 에 발견한 결함입니다. `_load_champion_metrics` 가 레지스트리에서
"지표를 가진 가장 최근 버전" 을 champion 으로 골랐습니다. 승격된 적 없는 실험
아티팩트가 비교 대상이 되는 구조입니다.

실제로 quantum_leap_v25_pro 는 서빙본이 25.1 인데 비교 대상이 표본 2개짜리
R2 -35999 버전이었습니다. `improved_r2 = challenger.r2 >= -35999 + 최소개선` 이라
어떤 챌린저든 통과했고, 서빙본과 무관한 근거로 승격 권고 알림이 나갔습니다.

두 가지를 고정합니다.

1. **champion 은 서빙 슬롯에서 읽을 것.** 레지스트리의 아무 버전이 아닙니다.
2. **비교 대상이 없으면 기각할 것.** 예전 cold start 값(rmse=inf)은 어떤
   챌린저든 자동으로 이기게 만들었습니다. 주석은 "무조건 승격되지 않도록"
   이라 적혀 있었으나 동작은 정반대였습니다.
"""

import json

import pytest

from src.tasks import retrain_task

CHALLENGER_METRICS = {"rmse": 2.66, "mape": 1.42, "r2": 0.6924}
SERVING_METRICS = {"rmse": 2.6998, "mape": 1.4646, "r2": 0.6824}


def _write(path, payload):
    path.mkdir(parents=True, exist_ok=True)
    (path / "metadata.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


@pytest.fixture
def serving_root(tmp_path, monkeypatch):
    root = tmp_path / "model_files"
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("src.ml.promotion.SERVING_ROOT", root)
    return root


def test_champion_comes_from_serving_slot(serving_root, tmp_path):
    """레지스트리에 더 최근 버전이 있어도 서빙본이 기준입니다."""
    _write(serving_root / "m", {"version": "v_serving", "source_metrics": SERVING_METRICS})
    registry = tmp_path / "registry"
    _write(registry / "m" / "v_experiment", {"version": "v_experiment", "metrics": {"r2": -35999.0}})

    version, metrics = retrain_task._load_champion_metrics("m", registry_dir=str(registry))

    assert version == "v_serving"
    assert metrics == SERVING_METRICS


def test_serving_without_metrics_is_not_comparable(serving_root, tmp_path):
    """원본에서 이식한 가중치가 이 상태입니다. 레지스트리로 대체하면 안 됩니다."""
    _write(serving_root / "m", {"version": "25.1"})
    registry = tmp_path / "registry"
    _write(registry / "m" / "v_junk", {"version": "v_junk", "metrics": {"r2": -35999.0}})

    version, metrics = retrain_task._load_champion_metrics("m", registry_dir=str(registry))

    assert version == "25.1"
    assert metrics == {}


def test_no_serving_and_no_champion_marking_is_not_comparable(serving_root, tmp_path):
    """champion 표시가 없는 레지스트리 버전은 비교 대상이 아닙니다."""
    registry = tmp_path / "registry"
    _write(registry / "m" / "v_a", {"version": "v_a", "metrics": {"r2": 0.5}})

    version, metrics = retrain_task._load_champion_metrics("m", registry_dir=str(registry))

    assert version == retrain_task.NO_CHAMPION
    assert metrics == {}


def test_explicit_champion_marking_is_used(serving_root, tmp_path):
    registry = tmp_path / "registry"
    _write(registry / "m" / "v_a", {"version": "v_a", "metrics": {"r2": 0.5}})
    _write(
        registry / "m" / "v_b",
        {"version": "v_b", "status": "champion", "metrics": SERVING_METRICS},
    )

    version, metrics = retrain_task._load_champion_metrics("m", registry_dir=str(registry))

    assert version == "v_b"
    assert metrics == SERVING_METRICS


# --------------------------------------------------------------------------- #
# 실측 지표 사이드카
# --------------------------------------------------------------------------- #
#
# 원본에서 이식한 4개 모델의 metadata.json 은 체크섬 매니페스트에 포함돼
# 있습니다. 거기에 지표를 써넣으면 G1 무손실 검증이 깨지므로 별도 파일에 둡니다.


@pytest.fixture
def metrics_root(tmp_path, monkeypatch):
    root = tmp_path / "model_metrics"
    monkeypatch.setattr("src.ml.promotion.METRICS_ROOT", root)
    return root


def test_sidecar_metrics_are_used_when_serving_has_none(serving_root, metrics_root):
    from src.ml import promotion

    _write(serving_root / "m", {"version": "25.1"})
    promotion.save_serving_metrics("m", "25.1", {"r2": -0.2133, "rmse": 6.3769})

    version, metrics = retrain_task._load_champion_metrics("m")

    assert version == "25.1"
    assert metrics["r2"] == -0.2133


def test_sidecar_is_ignored_when_version_differs(serving_root, metrics_root):
    """모델이 교체됐는데 옛 측정값을 물려주면 없는 근거로 판단하게 됩니다."""
    from src.ml import promotion

    _write(serving_root / "m", {"version": "25.2"})
    promotion.save_serving_metrics("m", "25.1", {"r2": -0.2133})

    _, metrics = retrain_task._load_champion_metrics("m")

    assert metrics == {}


def test_serving_metadata_wins_over_sidecar(serving_root, metrics_root):
    """승격이 기록한 값이 정본입니다. 실측은 그것이 없을 때만 씁니다."""
    from src.ml import promotion

    _write(serving_root / "m", {"version": "v1", "source_metrics": SERVING_METRICS})
    promotion.save_serving_metrics("m", "v1", {"r2": -99.0})

    _, metrics = retrain_task._load_champion_metrics("m")

    assert metrics == SERVING_METRICS


@pytest.mark.asyncio
async def test_incomparable_champion_is_warned_not_silently_rejected(monkeypatch):
    """비교 불가는 정상 기각이 아닙니다. 조용히 지나가면 아무도 모릅니다."""
    from src.tasks import notifier

    sent: list[tuple[str, list[str], str]] = []

    async def fake_notify(title, lines, *, level="info"):
        sent.append((title, lines, level))

    monkeypatch.setattr(notifier, "notify", fake_notify)

    await notifier.notify_retrain_result(
        trigger_source="weekly_schedule",
        recommendation="REJECT_CHALLENGER",
        champion_version="25.1",
        challenger_version="v_new",
        champion_metrics={},
        challenger_metrics=CHALLENGER_METRICS,
        samples=917_629,
        category="Thng",
        champion_comparable=False,
    )

    assert len(sent) == 1
    _, lines, level = sent[0]
    assert level == "warning"
    assert "비교할 수 없습니다" in "\n".join(lines)

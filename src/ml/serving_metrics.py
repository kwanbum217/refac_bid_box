"""서빙 중인 모델의 승격 시 홀드아웃 지표 집계.

새 학습이나 평가를 돌리지 않고, 승격이 serving metadata.json 에 남긴
source_metrics 만 읽습니다. 예측 검증 스텝과 지표 해석기가 같은 값을 보도록
집계 규칙을 한 곳에 둡니다.
"""

from __future__ import annotations

from typing import Any

from src.ml import model_registry as mr
from src.ml import promotion


def serving_holdout_metrics() -> dict[str, Any]:
    """카테고리별 서빙 모델의 홀드아웃 지표와 avg_r2 를 돌려줍니다.

    지표가 없는 모델은 건너뛰고, 하나도 없으면 avg_r2 키를 넣지 않습니다.
    소비자는 avg_r2 가 없을 때만 분기를 끄므로 측정값이 없는데 None 이나 0 을
    넣으면 없는 근거로 경고를 발화시킵니다.
    """
    serving_metrics: dict[str, dict[str, Any]] = {}
    r2_values: list[float] = []
    for category, model_name in mr.CATEGORY_DEFAULT_MODELS.items():
        version, metrics = promotion.load_serving_metrics(model_name)
        if not metrics:
            continue
        entry: dict[str, Any] = {"model_name": model_name, "version": version}
        r2 = metrics.get("r2")
        if r2 is not None:
            value = float(r2)
            entry["r2"] = value
            r2_values.append(value)
        rmse = metrics.get("rmse")
        if rmse is not None:
            entry["rmse"] = float(rmse)
        serving_metrics[category] = entry

    result: dict[str, Any] = {
        "serving_metrics": serving_metrics,
        "metrics_source": "serving_holdout",
    }
    if r2_values:
        result["avg_r2"] = round(sum(r2_values) / len(r2_values), 4)
    return result
